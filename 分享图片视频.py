import os
import sqlite3
from flask import (
    Flask, render_template_string, request, redirect, url_for,
    flash, session, send_from_directory, abort, g
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = 'set_a_very_secret_key'  # 请换成随机安全密钥

# 上传配置
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'mp4', 'mov', 'avi', 'mkv'}
MAX_CONTENT_LENGTH = 200 * 1024 * 1024  # 200MB max

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# -------- 数据库操作 --------
DATABASE = 'app.db'

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db:
        db.close()

def init_db():
    db = get_db()
    cursor = db.cursor()
    # 创建用户表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    ''')
    # 创建文件表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            filename TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    ''')
    db.commit()

# -------- 辅助函数 --------

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_user_folder(username):
    path = os.path.join(app.config['UPLOAD_FOLDER'], username)
    if not os.path.exists(path):
        os.makedirs(path)
    return path

def login_required(func):
    from functools import wraps
    @wraps(func)
    def wrapper(*args, **kwargs):
        if 'user_id' not in session:
            flash('请先登录。')
            return redirect(url_for('login'))
        return func(*args, **kwargs)
    return wrapper

def lcs(a, b):
    """最长公共子序列长度，大小写不敏感"""
    a = a.lower()
    b = b.lower()
    m, n = len(a), len(b)
    dp = [[0]*(n+1) for _ in range(m+1)]
    for i in range(m):
        for j in range(n):
            if a[i] == b[j]:
                dp[i+1][j+1] = dp[i][j] +1
            else:
                dp[i+1][j+1] = max(dp[i][j+1], dp[i+1][j])
    return dp[m][n]

def detect_media_type(filename):
    ext = filename.rsplit('.', 1)[-1].lower()
    if ext in {'png', 'jpg', 'jpeg', 'gif'}:
        return 'image'
    elif ext in {'mp4', 'mov', 'avi', 'mkv'}:
        return 'video'
    else:
        return 'unknown'

# -------- 路由 --------

# 基础模板，含Bootstrap 4 CDN
base_template = '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>{% block title %}图片视频分享{% endblock %}</title>
    <link rel="stylesheet" href="https://cdn.staticfile.org/twitter-bootstrap/4.6.2/css/bootstrap.min.css">
    <style>
        body { padding-top: 70px; }
        .media-list { max-width: 700px; margin: 20px auto; }
        .media-item { padding: 10px; border-bottom: 1px solid #ddd; }
        .media-link { cursor: pointer; color: #007bff; text-decoration: underline; }
        footer { margin: 30px 0; text-align:center; color:#aaa; }
        video { max-width: 100%; height: auto; }
        img { max-width: 100%; height: auto; }
    </style>
    {% block head %}{% endblock %}
</head>
<body>

<nav class="navbar navbar-expand-md navbar-dark bg-dark fixed-top">
  <a class="navbar-brand" href="{{ url_for('index') }}">图片视频分享</a>
  <button class="navbar-toggler" type="button" data-toggle="collapse" data-target="#navbarsExampleDefault"
   aria-controls="navbarsExampleDefault" aria-expanded="false" aria-label="切换导航">
    <span class="navbar-toggler-icon"></span>
  </button>

  <div class="collapse navbar-collapse" id="navbarsExampleDefault">
    <ul class="navbar-nav ml-auto">
      {% if session.get('username') %}
      <li class="nav-item">
        <a class="nav-link" href="{{ url_for('user_home', username=session.get('username')) }}">我的主页 ({{ session.get('username') }})</a>
      </li>
      <li class="nav-item">
        <a class="nav-link" href="{{ url_for('logout') }}">登出</a>
      </li>
      {% else %}
      <li class="nav-item">
        <a class="nav-link" href="{{ url_for('login') }}">登录</a>
      </li>
      <li class="nav-item">
        <a class="nav-link" href="{{ url_for('register') }}">注册</a>
      </li>
      {% endif %}
    </ul>
  </div>
</nav>

<div class="container">
    {% with messages = get_flashed_messages() %}
      {% if messages %}
        <div class="alert alert-info mt-2" role="alert">
          {% for msg in messages %}
            <div>{{ msg }}</div>
          {% endfor %}
        </div>
      {% endif %}
    {% endwith %}
    {% block content %}{% endblock %}
</div>

<footer>
  <small>本网站用于图片和视频分享 Demo（基于Flask）</small>
</footer>

<script src="https://cdn.staticfile.org/jquery/3.6.4/jquery.min.js"></script>
<script src="https://cdn.staticfile.org/twitter-bootstrap/4.6.2/js/bootstrap.bundle.min.js"></script>
{% block scripts %}{% endblock %}
</body>
</html>
'''

@app.route('/')
def index():
    query = request.args.get('q', '').strip()
    db = get_db()
    c = db.cursor()
    c.execute("SELECT id, username FROM users")
    users = c.fetchall()
    usernames = [u['username'] for u in users]
    if query:
        usernames.sort(key=lambda u: lcs(u, query), reverse=True)
    return render_template_string('''
    {% extends "base.html" %}
    {% block title %}用户搜索{% endblock %}
    {% block content %}
    <h1>搜索用户</h1>
    <form method="get" action="{{ url_for('index') }}" class="form-inline mb-3">
      <input type="text" name="q" value="{{ query }}" placeholder="请输入用户名搜索" class="form-control mr-2" style="width:250px;">
      <button type="submit" class="btn btn-primary">搜索</button>
    </form>
    {% if query and not usernames %}
      <p>找不到匹配用户</p>
    {% endif %}
    <ul class="list-group">
    {% for user in usernames %}
      <li class="list-group-item">
        <a href="{{ url_for('user_home', username=user) }}">{{ user }}</a>
      </li>
    {% else %}
      <li class="list-group-item text-muted">暂无用户</li>
    {% endfor %}
    </ul>
    {% endblock %}
    ''', query=query, usernames=usernames, **globals(), base=base_template)

@app.route('/register', methods=['GET','POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username','').strip()
        password = request.form.get('password','')
        password2 = request.form.get('password2','')

        if not username or not password or not password2:
            flash('所有字段不能为空')
            return redirect(url_for('register'))

        if password != password2:
            flash('两次密码输入不一致')
            return redirect(url_for('register'))

        db = get_db()
        c = db.cursor()
        c.execute("SELECT id FROM users WHERE username = ?", (username,))
        if c.fetchone() is not None:
            flash('用户名已存在')
            return redirect(url_for('register'))

        hashed = generate_password_hash(password)
        c.execute("INSERT INTO users(username, password) VALUES (?, ?)", (username, hashed))
        db.commit()
        # 创建用户文件夹
        get_user_folder(username)
        flash('注册成功，请登录')
        return redirect(url_for('login'))

    return render_template_string('''
    {% extends "base.html" %}
    {% block title %}注册{% endblock %}
    {% block content %}
    <h1>注册</h1>
    <form method="post" style="max-width:400px;">
      <div class="form-group">
        <label for="username">用户名</label>
        <input type="text" name="username" id="username" class="form-control" required autofocus>
      </div>
      <div class="form-group">
        <label for="password">密码</label>
        <input type="password" name="password" id="password" class="form-control" required>
      </div>
      <div class="form-group">
        <label for="password2">确认密码</label>
        <input type="password" name="password2" id="password2" class="form-control" required>
      </div>
      <button type="submit" class="btn btn-success">注册</button>
      <a href="{{ url_for('login') }}" class="btn btn-link">已有账号，去登录</a>
    </form>
    {% endblock %}
    ''', base=base_template)

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username','').strip()
        password = request.form.get('password','')

        if not username or not password:
            flash('请输入用户名和密码')
            return redirect(url_for('login'))

        db = get_db()
        c = db.cursor()
        c.execute("SELECT * FROM users WHERE username = ?", (username,))
        user = c.fetchone()
        if user is None:
            flash('用户不存在')
            return redirect(url_for('login'))

        if not check_password_hash(user['password'], password):
            flash('密码错误')
            return redirect(url_for('login'))

        session['user_id'] = user['id']
        session['username'] = user['username']
        flash(f'欢迎回来，{user["username"]}')
        return redirect(url_for('index'))

    return render_template_string('''
    {% extends "base.html" %}
    {% block title %}登录{% endblock %}
    {% block content %}
    <h1>登录</h1>
    <form method="post" style="max-width:400px;">
      <div class="form-group">
        <label for="username">用户名</label>
        <input type="text" name="username" id="username" class="form-control" required autofocus>
      </div>
      <div class="form-group">
        <label for="password">密码</label>
        <input type="password" name="password" id="password" class="form-control" required>
      </div>
      <button type="submit" class="btn btn-primary">登录</button>
      <a href="{{ url_for('register') }}" class="btn btn-link">去注册</a>
    </form>
    {% endblock %}
    ''', base=base_template)

@app.route('/logout')
def logout():
    session.clear()
    flash('已登出')
    return redirect(url_for('index'))

@app.route('/user/<username>')
def user_home(username):
    db = get_db()
    c = db.cursor()
    c.execute("SELECT id FROM users WHERE username = ?", (username,))
    user = c.fetchone()
    if user is None:
        abort(404)

    c.execute("SELECT filename FROM files WHERE user_id = ? ORDER BY id DESC", (user['id'],))
    files = c.fetchall()
    media = [{'filename': f['filename'],
            'type': detect_media_type(f['filename'])} for f in files]

    own = session.get('user_id') == user['id']

    return render_template_string('''
    {% extends "base.html" %}
    {% block title %}{{ username }} 的主页{% endblock %}
    {% block content %}
    <h1>{{ username }} 的主页</h1>

    {% if own %}
    <div class="mb-4">
      <form action="{{ url_for('upload') }}" method="post" enctype="multipart/form-data" class="form-inline">
        <div class="form-group">
          <input type="file" name="file" required class="form-control-file">
        </div>
        <button type="submit" class="btn btn-primary ml-2">上传 图片或视频</button>
      </form>
    </div>
    {% endif %}

    {% if media %}
    <div class="media-list list-group">
      {% for item in media %}
      <div class="media-item list-group-item d-flex justify-content-between align-items-center">
        {% if item.type == 'image' %}
          <a href="{{ url_for('uploaded_file', username=username, filename=item.filename) }}" target="_blank" class="media-link">{{ item.filename }}</a>
        {% elif item.type == 'video' %}
          <a href="{{ url_for('uploaded_file', username=username, filename=item.filename) }}" target="_blank" class="media-link">{{ item.filename }}</a>
        {% else %}
          {{ item.filename }}
        {% endif %}
        {% if own %}
        <form action="{{ url_for('delete_file', username=username, filename=item.filename) }}" method="post" style="margin:0;">
          <button type="submit" class="btn btn-sm btn-danger" onclick="return confirm('确认删除该文件？')">删除</button>
        </form>
        {% endif %}
      </div>
      {% endfor %}
    </div>

    <hr>

    <h3>预览</h3>
    {% for item in media %}
      {% if item.type == 'image' %}
        <div class="mb-3">
          <strong>{{ item.filename }}</strong><br>
          <img src="{{ url_for('uploaded_file', username=username, filename=item.filename) }}" alt="{{ item.filename }}">
        </div>
      {% elif item.type == 'video' %}
        <div class="mb-3">
          <strong>{{ item.filename }}</strong><br>
          <video controls preload="metadata" >
            <source src="{{ url_for('uploaded_file', username=username, filename=item.filename) }}">
            您的浏览器不支持视频播放。
          </video>
        </div>
      {% else %}
        <div class="mb-3"><strong>{{ item.filename }}</strong> （不支持预览）</div>
      {% endif %}
    {% else %}
      <p>该用户暂无上传内容</p>
    {% endfor %}
    {% endblock %}
    ''', username=username, media=media, own=own, base=base_template)

@app.route('/upload', methods=['POST'])
@login_required
def upload():
    if 'file' not in request.files:
        flash('没有文件上传')
        return redirect(url_for('user_home', username=session.get('username')))

    file = request.files['file']
    if not file or file.filename == '':
        flash('未选择文件')
        return redirect(url_for('user_home', username=session.get('username')))

    if not allowed_file(file.filename):
        flash('文件格式不支持，只支持图片和视频')
        return redirect(url_for('user_home', username=session.get('username')))

    filename = secure_filename(file.filename)
    user_folder = get_user_folder(session.get('username'))
    final_name = filename
    base, ext = os.path.splitext(filename)
    count = 1
    while os.path.exists(os.path.join(user_folder, final_name)):
        final_name = f"{base}_{count}{ext}"
        count += 1

    filepath = os.path.join(user_folder, final_name)
    file.save(filepath)

    # 保存记录到数据库
    db = get_db()
    c = db.cursor()
    c.execute("INSERT INTO files(user_id, filename) VALUES (?, ?)", (session['user_id'], final_name))
    db.commit()

    flash('上传成功')
    return redirect(url_for('user_home', username=session.get('username')))

@app.route('/uploads/<username>/<filename>')
def uploaded_file(username, filename):
    # 验证用户和文件存在
    db = get_db()
    c = db.cursor()
    c.execute("SELECT id FROM users WHERE username = ?", (username,))
    user = c.fetchone()
    if not user:
        abort(404)

    c.execute("SELECT id FROM files WHERE user_id = ? AND filename = ?", (user['id'], filename))
    file = c.fetchone()
    if not file:
        abort(404)

    # 发送文件
    folder = get_user_folder(username)
    return send_from_directory(folder, filename)

@app.route('/delete/<username>/<filename>', methods=['POST'])
@login_required
def delete_file(username, filename):
    # 只允许本人删除
    if session.get('username') != username:
        flash('没有权限删除该文件')
        return redirect(url_for('user_home', username=username))

    db = get_db()
    c = db.cursor()
    c.execute("SELECT id FROM users WHERE username = ?", (username,))
    user = c.fetchone()
    if not user:
        flash('用户不存在')
        return redirect(url_for('index'))

    c.execute("SELECT id FROM files WHERE user_id = ? AND filename = ?", (user['id'], filename))
    file = c.fetchone()
    if not file:
        flash('文件不存在')
        return redirect(url_for('user_home', username=username))

    # 删除文件
    file_path = os.path.join(get_user_folder(username), filename)
    try:
        os.remove(file_path)
    except OSError:
        pass

    # 删除数据库记录
    c.execute("DELETE FROM files WHERE id = ?", (file['id'],))
    db.commit()

    flash('文件已删除')
    return redirect(url_for('user_home', username=username))

# 错误页面
@app.errorhandler(404)
def page_not_found(e):
    return render_template_string('''
    {% extends "base.html" %}
    {% block title %}404 页面未找到{% endblock %}
    {% block content %}
    <h1>404 页面未找到</h1>
    <p>抱歉，您访问的页面不存在。</p>
    <a href="{{ url_for('index') }}">返回首页</a>
    {% endblock %}
    ''', base=base_template), 404


# 将base.html注入模板环境
@app.context_processor
def inject_base():
    return dict(base=base_template)


if __name__ == '__main__':
    with app.app_context():
        init_db()
    app.run(debug=True)
