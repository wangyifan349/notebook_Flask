import os
import shutil
import sqlite3
import uuid
from flask import Flask, request, send_from_directory, jsonify, render_template_string, g, session, redirect, url_for, abort
from werkzeug.security import generate_password_hash, check_password_hash

# —— 应用与配置 —— 
app = Flask(__name__)
app.secret_key = 'replace-with-a-secure-random-key'   # 用于 Flask session 加密

BASE_DIR = os.path.abspath(os.path.dirname(__file__))  
STORAGE_DIR = os.path.join(BASE_DIR, 'uploads')       
os.makedirs(STORAGE_DIR, exist_ok=True)               # 创建上传目录（如果不存在）
DATABASE = os.path.join(BASE_DIR, 'app.db')           # SQLite 数据库文件路径

# —— SQLite3 数据库连接与初始化 —— 
def get_db():
    """获取当前请求的数据库连接（单例）。"""
    db = getattr(g, '_database', None)
    if not db:
        db = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
        g._database = db
    return db

def init_db():
    """初始化数据表：users 和 shares。"""
    with app.app_context():
        db = get_db()
        db.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username TEXT UNIQUE,
            password_hash TEXT
        );
        CREATE TABLE IF NOT EXISTS shares (
            id INTEGER PRIMARY KEY,
            token TEXT UNIQUE,
            path TEXT,
            is_directory INTEGER,
            creator_id INTEGER,
            FOREIGN KEY(creator_id) REFERENCES users(id)
        );
        ''')
        db.commit()

@app.teardown_appcontext
def close_connection(exception):
    """请求结束后关闭数据库连接。"""
    db = getattr(g, '_database', None)
    if db:
        db.close()

# —— 用户注册接口 —— 
@app.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    if not username or not password:
        return jsonify(error='用户名和密码不能为空'), 400
    # 将明文密码哈希后存储
    password_hash = generate_password_hash(password)
    db = get_db()
    try:
        db.execute(
            'INSERT INTO users(username, password_hash) VALUES(?, ?)',
            (username, password_hash)
        )
        db.commit()
    except sqlite3.IntegrityError:
        return jsonify(error='用户名已存在'), 400
    return jsonify(message='注册成功'), 201

# —— 用户登录接口 —— 
@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    db = get_db()
    user = db.execute(
        'SELECT * FROM users WHERE username = ?',
        (username,)
    ).fetchone()
    # 验证密码正确性
    if user and check_password_hash(user['password_hash'], password):
        session['user_id'] = user['id']
        session['username'] = username
        return jsonify(message='登录成功')
    return jsonify(error='用户名或密码错误'), 401

# —— 用户登出 —— 
@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')

# —— 登录保护装饰器 —— 
def login_required(f):
    def wrapped(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify(error='请先登录'), 401
        return f(*args, **kwargs)
    wrapped.__name__ = f.__name__
    return wrapped

PAGE_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Flask File Manager</title>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/jquery/3.6.0/jquery.min.js"></script>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/jquery-contextmenu/2.9.2/jquery.contextMenu.min.js"></script>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/jquery-contextmenu/2.9.2/jquery.contextMenu.min.css"/>
  <style>
    body { font-family: Arial, sans-serif; margin: 20px; }
    ul { list-style: none; padding: 0; }
    li { padding: 8px; margin: 4px 0; border: 1px solid #ddd; cursor: pointer; }
    .directory { font-weight: bold; background-color: #f9f9f9; }
    .drag-over { background-color: #d0ebff !important; }
    #playerModal { display:none; position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.7); justify-content:center; align-items:center; }
    #playerContainer { background:#fff; padding:20px; }
  </style>
</head>
<body>
  <h1>Flask File Manager</h1>
  <div>
    <button id="button-new-folder">Create Folder</button>
    <input type="file" id="input-file-upload">
    <button id="button-go-up">Go Up</button>
    <button id="button-logout">Logout</button>
  </div>
  <ul id="file-list"></ul>

  <div id="playerModal">
    <div id="playerContainer">
      <button id="closePlayer">Close</button>
      <div id="playerContent"></div>
    </div>
  </div>

<script>
let currentFolder = '';

function refreshFileList() {
  $.get('/list', { path: currentFolder }, data => {
    const list = $('#file-list').empty();
    data.forEach(item => {
      const li = $('<li draggable="true">')
        .text(item.name + (item.isDirectory ? '/' : ''))
        .data('name', item.name)
        .toggleClass('directory', item.isDirectory);
      list.append(li);
    });
  });
}

function isMediaFile(name) {
  return /\.(mp3|wav|ogg|mp4|webm)$/i.test(name);
}

$(function(){
  refreshFileList();

  $('#file-list').on('dblclick', 'li', function(){
    const name = $(this).data('name');
    const fullPath = (currentFolder ? currentFolder + '/' : '') + name;
    if ($(this).hasClass('directory')) {
      currentFolder = currentFolder ? `${currentFolder}/${name}` : name;
      refreshFileList();
    } else if (isMediaFile(name)) {
      const url = `/stream?path=${encodeURIComponent(fullPath)}`;
      const tag = /\.(mp3|wav|ogg)$/i.test(name)
        ? `<audio controls src="${url}" style="width:100%;"></audio>`
        : `<video controls src="${url}" style="width:100%;"></video>`;
      $('#playerContent').html(tag);
      $('#playerModal').css('display','flex');
    } else {
      window.location = `/download?path=${encodeURIComponent(fullPath)}`;
    }
  });

  $('#closePlayer').click(() => {
    $('#playerModal').hide();
    $('#playerContent').empty();
  });

  $('#button-go-up').click(() => {
    if (!currentFolder) return;
    const parts = currentFolder.split('/');
    parts.pop();
    currentFolder = parts.join('');
    refreshFileList();
  });

  $('#input-file-upload').change(function(){
    const file = this.files[0];
    const fd = new FormData();
    fd.append('file', file);
    fd.append('path', currentFolder);
    $.ajax({ url:'/upload', method:'POST', data:fd, processData:false, contentType:false })
      .always(refreshFileList);
  });

  $('#button-new-folder').click(() => {
    const name = prompt('Enter new folder name:');
    if (!name) return;
    $.ajax({
      url:'/mkdir', method:'POST', contentType:'application/json',
      data: JSON.stringify({ path: currentFolder, folder_name: name })
    }).always(refreshFileList);
  });

  $('#button-logout').click(() => {
    window.location = '/logout';
  });

  $.contextMenu({
    selector: '#file-list li',
    callback: (action, opts) => {
      const name = opts.$trigger.data('name');
      const fullPath = (currentFolder ? currentFolder + '/' : '') + name;
      if (action === 'delete' && confirm(`Delete "${name}"?`)) {
        $.ajax({
          url:'/delete', method:'POST', contentType:'application/json',
          data: JSON.stringify({ path: fullPath })
        }).always(refreshFileList);
      }
      if (action === 'rename') {
        const newName = prompt('New name:', name);
        if (newName && newName !== name) {
          $.ajax({
            url:'/rename', method:'POST', contentType:'application/json',
            data: JSON.stringify({ path: fullPath, new_name: newName })
          }).always(refreshFileList);
        }
      }
      if (action === 'share') {
        $.ajax({
          url:'/share', method:'POST', contentType:'application/json',
          data: JSON.stringify({ path: fullPath, is_directory: opts.$trigger.hasClass('directory') })
        }).done(res => {
          prompt('Share link:', res.share_link);
        });
      }
    },
    items: {
      delete: { name: "Delete" },
      rename: { name: "Rename" },
      share: { name: "Share" }
    }
  });

  let dragged = null;
  $('#file-list').on('dragstart','li', e => {
    dragged = $(e.target).data('name');
  });
  $('#file-list').on('dragover','li.directory', e => {
    e.preventDefault();
    $(e.target).addClass('drag-over');
  });
  $('#file-list').on('dragleave drop','li.directory', e => {
    e.preventDefault();
    $(e.target).removeClass('drag-over');
  });
  $('#file-list').on('drop','li.directory', e => {
    const dest = $(e.target).data('name');
    const src = (currentFolder ? currentFolder+'/' : '') + dragged;
    const dst = (currentFolder ? currentFolder+'/' : '') + dest;
    $.ajax({
      url:'/move', method:'POST', contentType:'application/json',
      data: JSON.stringify({ source: src, destination_directory: dst })
    }).always(refreshFileList);
  });
});
</script>
</body>
</html>
"""

# —— 渲染主页面 —— 
@app.route('/')
@login_required
def home():
    return render_template_string(PAGE_TEMPLATE)

# —— 列出目录内容 —— 
@app.route('/list')
@login_required
def list_directory():
    rel = request.args.get('path', '')
    abs_path = os.path.join(STORAGE_DIR, rel)
    # 防止越权访问
    if not abs_path.startswith(STORAGE_DIR) or not os.path.isdir(abs_path):
        abort(403)
    entries = []
    for name in sorted(os.listdir(abs_path)):
        full = os.path.join(abs_path, name)
        entries.append({
            'name': name,
            'isDirectory': os.path.isdir(full)
        })
    return jsonify(entries)

# —— 上传文件 —— 
@app.route('/upload', methods=['POST'])
@login_required
def upload_file():
    target = request.form.get('path', '')
    folder = os.path.join(STORAGE_DIR, target)
    os.makedirs(folder, exist_ok=True)
    fileobj = request.files['file']
    fileobj.save(os.path.join(folder, fileobj.filename))
    return '', 204

# —— 创建新文件夹 —— 
@app.route('/mkdir', methods=['POST'])
@login_required
def make_directory():
    data = request.get_json()
    path = data.get('path', '')
    name = data.get('folder_name')
    newdir = os.path.join(STORAGE_DIR, path, name)
    os.makedirs(newdir, exist_ok=True)
    return '', 204

# —— 下载文件 —— 
@app.route('/download')
@login_required
def download_file():
    rel = request.args.get('path', '')
    folder, filename = os.path.split(rel)
    return send_from_directory(
        os.path.join(STORAGE_DIR, folder),
        filename,
        as_attachment=True
    )

# —— 媒体流式播放 —— 
@app.route('/stream')
@login_required
def stream_file():
    rel = request.args.get('path', '')
    folder, filename = os.path.split(rel)
    return send_from_directory(
        os.path.join(STORAGE_DIR, folder),
        filename
    )

# —— 删除文件或文件夹 —— 
@app.route('/delete', methods=['POST'])
@login_required
def delete_entry():
    data = request.get_json()
    rel = data.get('path')
    abs_path = os.path.join(STORAGE_DIR, rel)
    if os.path.isdir(abs_path):
        shutil.rmtree(abs_path)
    else:
        os.remove(abs_path)
    return '', 204

# —— 重命名 —— 
@app.route('/rename', methods=['POST'])
@login_required
def rename_entry():
    data = request.get_json()
    rel = data.get('path')
    new_name = data.get('new_name')
    abs_old = os.path.join(STORAGE_DIR, rel)
    parent = os.path.dirname(abs_old)
    abs_new = os.path.join(parent, new_name)
    os.rename(abs_old, abs_new)
    return '', 204

# —— 移动文件/文件夹 —— 
@app.route('/move', methods=['POST'])
@login_required
def move_entry():
    data = request.get_json()
    src = os.path.join(STORAGE_DIR, data.get('source'))
    dst_dir = os.path.join(STORAGE_DIR, data.get('destination_directory'))
    os.makedirs(dst_dir, exist_ok=True)
    shutil.move(src, os.path.join(dst_dir, os.path.basename(src)))
    return '', 204

# —— 创建分享链接 —— 
@app.route('/share', methods=['POST'])
@login_required
def create_share():
    data = request.get_json()
    rel = data.get('path')
    is_dir = data.get('is_directory', False)
    abs_path = os.path.join(STORAGE_DIR, rel)
    if not os.path.exists(abs_path):
        return jsonify(error='路径不存在'), 400
    token = str(uuid.uuid4())
    db = get_db()
    db.execute(
        'INSERT INTO shares(token, path, is_directory, creator_id) VALUES(?, ?, ?, ?)',
        (token, rel, int(is_dir), session['user_id'])
    )
    db.commit()
    link = url_for('access_share', token=token, _external=True)
    return jsonify(share_link=link)

# —— 访问分享 —— 
@app.route('/share/<token>')
def access_share(token):
    db = get_db()
    rec = db.execute(
        'SELECT * FROM shares WHERE token = ?',
        (token,)
    ).fetchone()
    if not rec:
        abort(404)
    path = rec['path']
    abs_path = os.path.join(STORAGE_DIR, path)
    if rec['is_directory']:
        items = []
        for name in sorted(os.listdir(abs_path)):
            full = os.path.join(abs_path, name)
            items.append({
                'name': name,
                'isDirectory': os.path.isdir(full)
            })
        return jsonify(path=path, items=items)
    else:
        folder, filename = os.path.split(path)
        return send_from_directory(
            os.path.join(STORAGE_DIR, folder),
            filename,
            as_attachment=True
        )

if __name__ == '__main__':
    init_db()        # 启动前初始化数据库
    app.run(debug=True)
