import os
import shutil
import sqlite3
from flask import (
    Flask, request, redirect, url_for, flash,
    session, send_from_directory, abort, render_template_string
)
from werkzeug.security import generate_password_hash, check_password_hash
from itsdangerous import URLSafeSerializer, BadSignature

# ─── Configuration ─────────────────────────────────────────────────────────────

app = Flask(__name__)
app.config['SECRET_KEY'] = 'replace_with_a_secure_random_string'  # 运行时改为安全随机字符串！
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
BASE_UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
DATABASE_PATH = os.path.join(BASE_DIR, 'storage.db')
URL_SIGNER = URLSafeSerializer(app.config['SECRET_KEY'], salt='share_salt')

os.makedirs(BASE_UPLOAD_FOLDER, exist_ok=True)


# ─── Database Helpers ──────────────────────────────────────────────────────────

def get_database_connection():
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    return connection

def initialize_database():
    with get_database_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS shares (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token TEXT UNIQUE NOT NULL,
                path TEXT NOT NULL,
                permanent INTEGER NOT NULL DEFAULT 0
            );
        """)
        conn.commit()


# ─── Utility Functions ────────────────────────────────────────────────────────

def safe_path(relative_path=''):
    requested_path = os.path.abspath(os.path.join(BASE_UPLOAD_FOLDER, relative_path))
    base_path = os.path.abspath(BASE_UPLOAD_FOLDER)
    if os.path.commonpath([requested_path, base_path]) != base_path:
        abort(400)
    return requested_path

def current_user_id():
    return session.get('user_id')

def login_required(view):
    from functools import wraps
    @wraps(view)
    def wrapped_view(**kwargs):
        if current_user_id() is None:
            return redirect(url_for('login'))
        return view(**kwargs)
    return wrapped_view

def generate_share_token(path, permanent=False):
    token = URL_SIGNER.dumps(path)
    with get_database_connection() as conn:
        conn.execute(
            "INSERT INTO shares (token, path, permanent) VALUES (?, ?, ?);",
            (token, path, int(permanent))
        )
        conn.commit()
    return token

def revoke_share(path):
    with get_database_connection() as conn:
        conn.execute("DELETE FROM shares WHERE path = ?;", (path,))
        conn.commit()

def validate_share_token(token):
    with get_database_connection() as conn:
        row = conn.execute(
            "SELECT path FROM shares WHERE token = ?;",
            (token,)
        ).fetchone()
    if not row:
        return None
    try:
        URL_SIGNER.loads(token)
        return row['path']
    except BadSignature:
        return None


# ─── Authentication Routes ────────────────────────────────────────────────────

@app.route('/register', methods=('GET','POST'))
def register():
    title = 'Register'
    error = None
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        if not username or not password:
            error = 'Username and password are required.'
        else:
            password_hash = generate_password_hash(password)
            try:
                with get_database_connection() as conn:
                    conn.execute(
                        "INSERT INTO users (username, password_hash) VALUES (?, ?);",
                        (username, password_hash)
                    )
                    conn.commit()
                flash('Registration successful. Please log in.')
                return redirect(url_for('login'))
            except sqlite3.IntegrityError:
                error = 'Username already taken.'
        if error:
            flash(error)
    content = render_template_string(REGISTER_TEMPLATE)
    return render_template_string(BASE_TEMPLATE, title=title, CONTENT=content, session=session)

@app.route('/login', methods=('GET','POST'))
def login():
    title = 'Login'
    error = None
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        if not username or not password:
            error = 'Username and password are required.'
        else:
            with get_database_connection() as conn:
                row = conn.execute(
                    "SELECT id, password_hash FROM users WHERE username = ?;",
                    (username,)
                ).fetchone()
            if row and check_password_hash(row['password_hash'], password):
                session.clear()
                session['user_id'] = row['id']
                return redirect(url_for('browser'))
            error = 'Invalid credentials.'
        if error:
            flash(error)
    content = render_template_string(LOGIN_TEMPLATE)
    return render_template_string(BASE_TEMPLATE, title=title, CONTENT=content, session=session)

@app.route('/logout')
@login_required
def logout():
    session.clear()
    return redirect(url_for('login'))


# ─── File Browser and Operations ───────────────────────────────────────────────

@app.route('/', defaults={'subpath': ''})
@app.route('/<path:subpath>')
@login_required
def browser(subpath):
    current_path = subpath
    absolute_folder = safe_path(subpath)
    entries = []
    with get_database_connection() as conn:
        try:
            for name in sorted(os.listdir(absolute_folder)):
                rel_path = os.path.normpath(os.path.join(subpath, name))
                full_path = os.path.join(absolute_folder, name)
                share_row = conn.execute(
                    "SELECT id FROM shares WHERE path = ?;",
                    (rel_path,)
                ).fetchone()
                entries.append({
                    'name': name,
                    'is_folder': os.path.isdir(full_path),
                    'relative_path': rel_path.replace('\\', '/'),
                    'is_shared': bool(share_row)
                })
        except FileNotFoundError:
            flash('Directory not found.')
    content = render_template_string(BROWSER_TEMPLATE, entries=entries, current_path=current_path)
    return render_template_string(BASE_TEMPLATE, title=f'Browsing {current_path or "/"}', CONTENT=content, session=session)

@app.route('/upload', methods=('POST',))
@login_required
def upload_file():
    target_folder = request.form.get('current_path','')
    file = request.files.get('file')
    if file and file.filename:
        destination = os.path.join(safe_path(target_folder), file.filename)
        file.save(destination)
        flash(f'Uploaded {file.filename}')
    else:
        flash('No file selected.')
    return redirect(url_for('browser', subpath=target_folder))

@app.route('/download/<path:relative_path>')
@login_required
def download_file(relative_path):
    full = safe_path(relative_path)
    if not os.path.isfile(full):
        abort(404)
    directory, filename = os.path.split(full)
    return send_from_directory(directory, filename, as_attachment=True)

@app.route('/make_folder', methods=('POST',))
@login_required
def make_folder():
    target_folder = request.form.get('current_path','')
    new_name = request.form.get('folder_name','').strip()
    if not new_name:
        flash('Folder name cannot be empty.')
        return redirect(url_for('browser', subpath=target_folder))
    new_path = safe_path(os.path.join(target_folder, new_name))
    try:
        os.mkdir(new_path)
        flash(f'Created folder {new_name}')
    except FileExistsError:
        flash(f'Folder "{new_name}" already exists.')
    except Exception as e:
        flash(f'Error creating folder: {str(e)}')
    return redirect(url_for('browser', subpath=target_folder))

@app.route('/delete', methods=('POST',))
@login_required
def delete_entry():
    target = request.form.get('relative_path','')
    full = safe_path(target)
    try:
        if os.path.isdir(full):
            shutil.rmtree(full)
            flash(f'Deleted folder {os.path.basename(target)}')
        else:
            os.remove(full)
            flash(f'Deleted file {os.path.basename(target)}')
    except Exception as e:
        flash(f'Error deleting: {str(e)}')
    return redirect(url_for('browser', subpath=os.path.dirname(target)))

@app.route('/rename', methods=('POST',))
@login_required
def rename_entry():
    old_path = request.form.get('old_relative_path','')
    new_name = request.form.get('new_name','').strip()
    if not new_name:
        flash('New name cannot be empty.')
        return redirect(url_for('browser', subpath=os.path.dirname(old_path)))
    old_full = safe_path(old_path)
    new_full = safe_path(os.path.join(os.path.dirname(old_path), new_name))
    try:
        os.rename(old_full, new_full)
        flash(f'Renamed to {new_name}')
    except Exception as e:
        flash(f'Error renaming: {str(e)}')
    return redirect(url_for('browser', subpath=os.path.dirname(old_path)))


# ─── Sharing Routes ───────────────────────────────────────────────────────────

@app.route('/share', methods=('POST',))
@login_required
def share_entry():
    target = request.form.get('relative_path','')
    permanent = bool(request.form.get('permanent'))
    token = generate_share_token(target, permanent)
    link = url_for('shared_browser', token=token, _external=True)
    flash(f'Share link: {link}')
    return redirect(url_for('browser', subpath=os.path.dirname(target)))

@app.route('/unshare', methods=('POST',))
@login_required
def unshare_entry():
    target = request.form.get('relative_path','')
    revoke_share(target)
    flash(f'Unshared {os.path.basename(target)}')
    return redirect(url_for('browser', subpath=os.path.dirname(target)))

@app.route('/s/<token>/', defaults={'subpath': ''})
@app.route('/s/<token>/<path:subpath>')
def shared_browser(token, subpath):
    base_relative = validate_share_token(token)
    if not base_relative:
        abort(404)
    requested_relative = os.path.normpath(os.path.join(base_relative, subpath))
    absolute_path = safe_path(requested_relative)

    current_path = requested_relative.replace('\\', '/')
    if not os.path.exists(absolute_path):
        abort(404)

    if os.path.isdir(absolute_path):
        entries = []
        try:
            for name in sorted(os.listdir(absolute_path)):
                full = os.path.join(absolute_path, name)
                entries.append({
                    'name': name,
                    'is_folder': os.path.isdir(full),
                    'subpath': os.path.join(subpath, name).replace('\\', '/')
                })
        except FileNotFoundError:
            abort(404)
        content = render_template_string(
            SHARED_TEMPLATE,
            entries=entries,
            current_path=current_path,
            token=token
        )
        return render_template_string(BASE_TEMPLATE, title=f'Shared: {current_path or "/"}', CONTENT=content, session=session)
    else:
        directory, filename = os.path.split(absolute_path)
        return send_from_directory(directory, filename, as_attachment=True)


# ─── Templates ────────────────────────────────────────────────────────────────

# 我只把模板部分和新增JS脚本给你，你替换下你代码里对应部分即可

# ─── 修改后的 BASE_TEMPLATE（主框架） ──────────────────────────────

BASE_TEMPLATE = """
<!doctype html>
<html lang="zh">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{{ title if title else 'Flask 文件存储' }}</title>
  <link
    href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css"
    rel="stylesheet" />
  <style>
    /* 主题色为淡绿色背景，正文段落文字颜色适中 */
    body.bg-light {
      background-color: #e9f9ee !important; /* 比bootstrap的淡绿色还淡 */
      color: #2b4d2f;
    }
    .navbar.bg-primary {
      background-color: #4caf50 !important; /* 绿色 */
    }
    .navbar-brand, .nav-link {
      color: #e6f4ea !important;
    }
    .navbar-brand:hover, .nav-link:hover {
      color: #c8e6c9 !important;
    }
    
    /* 按钮主题 */
    .btn-primary {
      background-color: #4caf50;
      border-color: #4caf50;
    }
    .btn-primary:hover, .btn-primary:focus {
      background-color: #388e3c;
      border-color: #2e7d32;
    }

    .btn-info {
      background-color: #a5d6a7; /* 淡绿 */
      border-color: #81c784;
      color: #2e7d32;
    }
    .btn-info:hover, .btn-info:focus {
      background-color: #81c784;
      border-color: #66bb6a;
      color: white;
    }

    .btn-success {
      background-color: #66bb6a; 
      border-color: #58a65c;
    }
    .btn-success:hover, .btn-success:focus {
      background-color: #4caf50;
      border-color: #388e3c;
    }

    /* 警告用淡红色 btn-danger 修改为更柔和的红色 */
    .btn-danger {
      background-color: #ef9a9a;
      border-color: #e57373;
      color: #641e16;
    }
    .btn-danger:hover, .btn-danger:focus {
      background-color: #e57373;
      border-color: #ef5350;
      color: white;
    }

    /* 表格悬浮效果 */
    table.table tbody tr:hover {
      background-color: #d0f0c0;
      transition: background-color 0.3s ease;
    }

    /* Breadcrumb 风格调整为绿色 */
    .breadcrumb-item a {
      color: #4caf50;
      text-decoration: none;
    }
    .breadcrumb-item a:hover {
      text-decoration: underline;
      color: #2e7d32;
    }

    /* Toast 样式自定义为绿色底色 */
    .toast-success {
      background-color: #d0f0c0;
      color: #2e7d32;
    }

    /* 小动画让按钮更生动 */
    .btn {
      transition: background-color 0.3s ease, color 0.3s ease;
    }

  </style>
</head>
<body class="bg-light">
<nav class="navbar navbar-expand-lg navbar-dark bg-primary mb-4">
  <div class="container-fluid">
    <a class="navbar-brand" href="{{ url_for('browser') }}">文件存储</a>
    <div class="collapse navbar-collapse justify-content-end">
      {% if session.get('user_id') %}
      <ul class="navbar-nav">
        <li class="nav-item">
          <a class="nav-link">User #{{ session['user_id'] }}</a>
        </li>
        <li class="nav-item">
          <a class="nav-link" href="{{ url_for('logout') }}">登出</a>
        </li>
      </ul>
      {% else %}
      <ul class="navbar-nav">
        <li class="nav-item"><a class="nav-link" href="{{ url_for('login') }}">登录</a></li>
        <li class="nav-item"><a class="nav-link" href="{{ url_for('register') }}">注册</a></li>
      </ul>
      {% endif %}
    </div>
  </div>
</nav>
<div class="container">

  <!-- 弹窗区域 (toast提示) -->
  <div class="position-fixed bottom-0 end-0 p-3" style="z-index: 1100">
    <div id="toastShareLink" 
         class="toast align-items-center text-white toast-success border-0" 
         role="alert" aria-live="assertive" aria-atomic="true">
      <div class="d-flex">
        <div class="toast-body" id="toastBodyContent">
          <!-- 动态分享链接复制提示 -->
        </div>
        <button type="button" class="btn-close btn-close-white me-2 m-auto" 
                data-bs-dismiss="toast" aria-label="Close"></button>
      </div>
    </div>
  </div>

  {% with messages = get_flashed_messages() %}
    {% if messages %}
      <div class="alert alert-danger alert-dismissible fade show" role="alert">
        {% for msg in messages %}{{ msg }}<br>{% endfor %}
        <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
      </div>
    {% endif %}
  {% endwith %}
  
  {{ CONTENT | safe }}
</div>

<script
  src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>

<script>
// 分享按钮点击：复制链接并弹出Toast
document.addEventListener('DOMContentLoaded', () => {
  const shareForms = document.querySelectorAll('form[action$="/share"]');
  const toastEl = document.getElementById('toastShareLink');
  const toastBody = document.getElementById('toastBodyContent');
  const toast = new bootstrap.Toast(toastEl);

  shareForms.forEach(form => {
    form.addEventListener('submit', (evt) => {
      evt.preventDefault(); // 先阻止提交

      // 利用FormData获取相对路径
      let relativePath = form.querySelector('input[name="relative_path"]').value;

      // 发送fetch请求模拟提交，获取FLASH消息后解析分享链接
      fetch(form.action, {
        method: form.method,
        headers: {'Content-Type': 'application/x-www-form-urlencoded'},
        body: new URLSearchParams(new FormData(form))
      })
      .then(response => response.text())
      .then(html => {
        // 从返回HTML中提取分享链接 flash message
        const div = document.createElement('div');
        div.innerHTML = html;
        const alert = div.querySelector('.alert');
        if(alert) {
          let msgs = alert.innerText.trim().split('\\n').filter(s => s.includes('Share link') || s.includes('分享链接'));
          if(msgs.length === 0) {
            // 如果没有区分信息，只显示全部flash
            showToast("分享成功，复制链接失败，请手动复制。");
            location.reload(); // 刷新页面
            return;
          }
          let shareLink = null;
          for(let m of msgs) {
            // 提取分享链接
            let matched = m.match(/(https?:\/\/[^\\s]+)/);
            if(matched) shareLink = matched[0];
          }
          if(shareLink) {
            // 复制到剪贴板
            navigator.clipboard.writeText(shareLink).then(() => {
              showToast("分享链接已复制到剪贴板:\n" + shareLink);
              location.reload(); // 我们刷新页面显示按钮等状态变化
            }).catch(() => {
              // 复制失败
              showToast("分享成功，请手动复制链接:\n" + shareLink);
              location.reload();
            });
          }
          else {
            showToast("分享成功，但未能获取链接，请刷新页面。");
            location.reload();
          }
        } else {
          showToast("分享成功。");
          location.reload();
        }
      })
      .catch(() => {
        showToast("网络错误，分享失败");
      });
    });
  });

  function showToast(msg) {
    toastBody.textContent = msg;
    toast.show();
  }
});
</script>
</body>
</html>
"""


# ─── 登录页面（LOGIN_TEMPLATE）也稍微改为绿色甜美风 ───────────────

LOGIN_TEMPLATE = """
<form method="post" class="w-50 mx-auto border p-4 rounded-3 shadow bg-white">
  <h3 class="mb-4 text-success">登录</h3>
  <div class="mb-3">
    <input name="username" class="form-control border-success" placeholder="用户名" required autofocus />
  </div>
  <div class="mb-3">
    <input type="password" name="password" class="form-control border-success" placeholder="密码" required />
  </div>
  <button class="btn btn-success w-100">登录</button>
  <div class="mt-3 text-center">
    <a href="{{ url_for('register') }}" class="text-success text-decoration-none">没有账号？注册</a>
  </div>
</form>
"""

# ─── 注册页面（REGISTER_TEMPLATE）同理───────────────

REGISTER_TEMPLATE = """
<form method="post" class="w-50 mx-auto border p-4 rounded-3 shadow bg-white">
  <h3 class="mb-4 text-success">注册</h3>
  <div class="mb-3">
    <input name="username" class="form-control border-success" placeholder="用户名" required autofocus />
  </div>
  <div class="mb-3">
    <input type="password" name="password" class="form-control border-success" placeholder="密码" required />
  </div>
  <button class="btn btn-success w-100">注册</button>
  <div class="mt-3 text-center">
    <a href="{{ url_for('login') }}" class="text-success text-decoration-none">已有账号？登录</a>
  </div>
</form>
"""

# ─── 文件浏览页面（BROWSER_TEMPLATE）颜色调整，按钮采用绿色主题，删除用淡红色 ──────

BROWSER_TEMPLATE = """
<h4 class="mb-3 text-success">目录: {{ current_path or '/' }}</h4>
<table class="table table-striped shadow-sm rounded bg-white">
  <thead class="table-success">
    <tr><th>名称</th><th>类型</th><th>操作</th></tr>
  </thead>
  <tbody>
  {% for entry in entries %}
    <tr>
      <td>
        {% if entry.is_folder %}
          <a class="text-success fw-semibold" href="{{ url_for('browser', subpath=entry.relative_path) }}">{{ entry.name }}</a>
        {% else %}
          {{ entry.name }}
        {% endif %}
      </td>
      <td>{{ '文件夹' if entry.is_folder else '文件' }}</td>
      <td>
        <div class="btn-group btn-group-sm" role="group" aria-label="操作按钮组">
          {% if not entry.is_folder %}
            <a class="btn btn-success"
               href="{{ url_for('download_file', relative_path=entry.relative_path) }}">下载</a>
          {% endif %}
          <button type="button" class="btn btn-secondary"
                  data-bs-toggle="modal"
                  data-bs-target="#renameModal"
                  data-old="{{ entry.relative_path }}">重命名</button>
          {% if entry.is_shared %}
            <form action="{{ url_for('unshare_entry') }}" method="post" style="display:inline;">
              <input type="hidden" name="relative_path" value="{{ entry.relative_path }}" />
              <button class="btn btn-warning" title="取消分享">取消分享</button>
            </form>
          {% else %}
            <form action="{{ url_for('share_entry') }}" method="post" style="display:inline;">
              <input type="hidden" name="relative_path" value="{{ entry.relative_path }}" />
              <button class="btn btn-info" title="分享">分享</button>
            </form>
          {% endif %}
          <form action="{{ url_for('delete_entry') }}" method="post" style="display:inline;">
            <input type="hidden" name="relative_path" value="{{ entry.relative_path }}" />
            <button class="btn btn-danger"
              onclick="return confirm('确定删除 {{ entry.name }} 吗?');">删除</button>
          </form>
        </div>
      </td>
    </tr>
  {% endfor %}
  </tbody>
</table>

<div class="row mt-4">
  <div class="col-md-6">
    <h5 class="text-success">上传文件</h5>
    <form action="{{ url_for('upload_file') }}" method="post" enctype="multipart/form-data" class="shadow p-3 bg-white rounded">
      <input type="hidden" name="current_path" value="{{ current_path }}" />
      <div class="input-group">
        <input type="file" name="file" class="form-control" required />
        <button class="btn btn-success">上传</button>
      </div>
    </form>
  </div>
  <div class="col-md-6">
    <h5 class="text-success">新建文件夹</h5>
    <form action="{{ url_for('make_folder') }}" method="post" class="shadow p-3 bg-white rounded">
      <input type="hidden" name="current_path" value="{{ current_path }}" />
      <div class="input-group">
        <input name="folder_name" class="form-control" placeholder="文件夹名称" required />
        <button class="btn btn-success">创建</button>
      </div>
    </form>
  </div>
</div>

<!-- 重命名模态框 -->
<div class="modal fade" id="renameModal" tabindex="-1" aria-labelledby="renameModalLabel" aria-hidden="true">
  <div class="modal-dialog">
    <form action="{{ url_for('rename_entry') }}" method="post" class="modal-content shadow">
      <div class="modal-header bg-success text-white">
        <h5 class="modal-title" id="renameModalLabel">重命名</h5>
        <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal" aria-label="关闭"></button>
      </div>
      <div class="modal-body">
        <input type="hidden" id="oldPath" name="old_relative_path" />
        <input name="new_name" class="form-control border-success" placeholder="新名称" required autofocus />
      </div>
      <div class="modal-footer">
        <button type="button" class="btn btn-light" data-bs-dismiss="modal">取消</button>
        <button type="submit" class="btn btn-success">确认修改</button>
      </div>
    </form>
  </div>
</div>

<script>
  var renameModal = document.getElementById('renameModal');
  renameModal.addEventListener('show.bs.modal', function (event) {
    var button = event.relatedTarget;
    var oldPathInput = renameModal.querySelector('#oldPath');
    oldPathInput.value = button.getAttribute('data-old');
  });
</script>
"""

# ─── 共享浏览页面（SHARED_TEMPLATE）也改为绿红调 ────────────────

SHARED_TEMPLATE = """
<h4 class="mb-3 text-success">分享内容浏览: {{ current_path or '/' }}</h4>

<nav aria-label="breadcrumb">
  <ol class="breadcrumb">
    <li class="breadcrumb-item">
      <a href="{{ url_for('shared_browser', token=token) }}">根目录</a>
    </li>
    {% if current_path and current_path != '' %}
      {% set crumbs = current_path.strip('/').split('/') %}
      {% for i in range(crumbs|length) %}
        <li class="breadcrumb-item">
          <a href="{{ url_for('shared_browser', token=token,
                  subpath=crumbs[:i+1]|join('/')) }}">{{ crumbs[i] }}</a>
        </li>
      {% endfor %}
    {% endif %}
  </ol>
</nav>

<table class="table table-bordered shadow-sm bg-white rounded">
  <thead class="table-success"><tr><th>名称</th><th>类型</th><th>操作</th></tr></thead>
  <tbody>
    {% for entry in entries %}
      <tr>
        <td>
          {% if entry.is_folder %}
            <a class="text-success fw-semibold" href="{{ url_for('shared_browser', token=token,
                      subpath=entry.subpath) }}">{{ entry.name }}</a>
          {% else %}
            {{ entry.name }}
          {% endif %}
        </td>
        <td>{{ '文件夹' if entry.is_folder else '文件' }}</td>
        <td>
          {% if not entry.is_folder %}
            <a class="btn btn-success btn-sm"
               href="{{ url_for('shared_browser', token=token,
                            subpath=entry.subpath) }}">下载</a>
          {% endif %}
        </td>
      </tr>
    {% endfor %}
  </tbody>
</table>
"""




# ─── Run ───────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    initialize_database()
    app.run(debug=False)
