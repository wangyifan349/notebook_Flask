import os
import sqlite3
from flask import (
    Flask, g, render_template, request,
    redirect, url_for, flash, send_from_directory, jsonify
)
from flask_login import (
    LoginManager, UserMixin,
    login_user, login_required,
    logout_user, current_user
)
from werkzeug.utils import secure_filename
from jinja2 import DictLoader

# ——— 配置 —————————————————————————————————————————————————————————————————————————
DATABASE_PATH        = 'video.db'
UPLOAD_FOLDER        = 'uploads'
ALLOWED_EXTENSIONS   = {'mp4', 'webm', 'ogg'}

app = Flask(__name__)
app.config['SECRET_KEY']    = 'you-will-never-guess'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

login_manager = LoginManager(app)
login_manager.login_view = 'login'

# ——— 模板字典 —————————————————————————————————————————————————————————————————————————
templates = {
    'base.html': '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <title>{% block title %}视频平台{% endblock %}</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>body{padding-top:70px}.video-thumb{width:100%;height:auto}</style>
</head>
<body>
<nav class="navbar navbar-expand-lg navbar-dark bg-dark fixed-top">
  <div class="container-fluid">
    <a class="navbar-brand" href="{{ url_for('index') }}">视频平台</a>
    <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#navbarMenu">
      <span class="navbar-toggler-icon"></span>
    </button>
    <div class="collapse navbar-collapse" id="navbarMenu">
      <ul class="navbar-nav me-auto">
        <li class="nav-item"><a class="nav-link" href="{{ url_for('index') }}">首页</a></li>
        {% if current_user.is_authenticated %}
        <li class="nav-item"><a class="nav-link" href="{{ url_for('dashboard') }}">管理中心</a></li>
        {% endif %}
      </ul>
      <form class="d-flex me-3" method="post" action="{{ url_for('search') }}">
        <input class="form-control me-2" name="query" placeholder="搜索视频">
        <button class="btn btn-outline-success">搜索</button>
      </form>
      <ul class="navbar-nav">
        {% if current_user.is_authenticated %}
          <li class="nav-item"><a class="nav-link" href="{{ url_for('profile',username=current_user.username) }}">{{ current_user.username }}</a></li>
          <li class="nav-item"><a class="nav-link" href="{{ url_for('logout') }}">登出</a></li>
        {% else %}
          <li class="nav-item"><a class="nav-link" href="{{ url_for('login') }}">登录</a></li>
          <li class="nav-item"><a class="nav-link" href="{{ url_for('register') }}">注册</a></li>
        {% endif %}
      </ul>
    </div>
  </div>
</nav>
<div class="container">
  {% with messages = get_flashed_messages(with_categories=true) %}
    {% for category,msg in messages %}
      <div class="alert alert-{{ category }} alert-dismissible fade show">
        {{ msg }}<button type="button" class="btn-close" data-bs-dismiss="alert"></button>
      </div>
    {% endfor %}
  {% endwith %}
  {% block content %}{% endblock %}
</div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
''',
    'index.html': '''
{% extends 'base.html' %}
{% block title %}首页 - 视频平台{% endblock %}
{% block content %}
<h2 class="mb-4">最新视频</h2>
<div class="row">
  {% for video in videos %}
  <div class="col-md-4 mb-4">
    <div class="card">
      <a href="{{ url_for('play_video', filename=video.filename) }}">
        <img src="{{ url_for('play_video', filename=video.filename) }}" class="card-img-top video-thumb">
      </a>
      <div class="card-body">
        <h5 class="card-title">{{ video.title }}</h5>
        <p class="card-text text-truncate">{{ video.description or '' }}</p>
        <p class="card-text"><small class="text-muted">By {{ video.username }}</small></p>
      </div>
    </div>
  </div>
  {% endfor %}
</div>
{% endblock %}
''',
    'register.html': '''
{% extends 'base.html' %}
{% block title %}注册 - 视频平台{% endblock %}
{% block content %}
<h2 class="mb-4">注册</h2>
<form method="post">
  <div class="mb-3"><label class="form-label">用户名</label><input name="username" class="form-control" required></div>
  <div class="mb-3"><label class="form-label">邮箱</label><input type="email" name="email" class="form-control" required></div>
  <div class="mb-3"><label class="form-label">密码</label><input type="password" name="password" class="form-control" required></div>
  <button class="btn btn-primary">注册</button>
</form>
{% endblock %}
''',
    'login.html': '''
{% extends 'base.html' %}
{% block title %}登录 - 视频平台{% endblock %}
{% block content %}
<h2 class="mb-4">登录</h2>
<form method="post">
  <div class="mb-3"><label class="form-label">用户名</label><input name="username" class="form-control" required></div>
  <div class="mb-3"><label class="form-label">密码</label><input type="password" name="password" class="form-control" required></div>
  <button class="btn btn-primary">登录</button>
</form>
{% endblock %}
''',
    'upload.html': '''
{% extends 'base.html' %}
{% block title %}上传视频 - 视频平台{% endblock %}
{% block content %}
<h2 class="mb-4">上传视频</h2>
<form method="post" enctype="multipart/form-data">
  <div class="mb-3"><label class="form-label">标题</label><input name="title" class="form-control" required></div>
  <div class="mb-3"><label class="form-label">描述</label><textarea name="description" class="form-control"></textarea></div>
  <div class="mb-3"><label class="form-label">选择视频</label><input type="file" name="video" class="form-control" accept="video/*" required></div>
  <button class="btn btn-success">上传</button>
</form>
{% endblock %}
''',
    'dashboard.html': '''
{% extends 'base.html' %}
{% block title %}管理中心 - 视频平台{% endblock %}
{% block content %}
<h2 class="mb-4">我的视频管理</h2>
<a href="{{ url_for('upload_video') }}" class="btn btn-success mb-3">上传新视频</a>
<table class="table table-hover">
  <thead><tr><th>预览</th><th>标题</th><th>状态</th><th>操作</th></tr></thead>
  <tbody>
    {% for video in videos %}
    <tr id="row-{{ video.id }}">
      <td><video src="{{ url_for('play_video', filename=video.filename) }}" width="120" controls muted></video></td>
      <td>{{ video.title }}</td>
      <td class="status-{{ video.id }}">
        {% if video.is_public %}<span class="badge bg-success">公开</span>{% else %}<span class="badge bg-secondary">隐藏</span>{% endif %}
      </td>
      <td>
        <button class="btn btn-sm btn-warning" onclick="toggleVideo({{ video.id }})">
          {% if video.is_public %}隐藏{% else %}公开{% endif %}
        </button>
        <button class="btn btn-sm btn-danger" onclick="deleteVideo({{ video.id }})">删除</button>
      </td>
    </tr>
    {% endfor %}
  </tbody>
</table>
<script>
function toggleVideo(videoId) {
  fetch(`/video/${videoId}/action`, {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({action:'toggle'})
  }).then(r=>r.json()).then(data=>{
    if (data.new_state!==undefined) {
      let btn=document.querySelector(`#row-${videoId} .btn-warning`);
      let statusCell=document.querySelector(`.status-${videoId}`);
      if (data.new_state) {
        btn.textContent='隐藏';
        statusCell.innerHTML='<span class="badge bg-success">公开</span>';
      } else {
        btn.textContent='公开';
        statusCell.innerHTML='<span class="badge bg-secondary">隐藏</span>';
      }
    }
  });
}
function deleteVideo(videoId) {
  if (!confirm('确定删除？')) return;
  fetch(`/video/${videoId}/action`, {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({action:'delete'})
  }).then(r=>r.json()).then(data=>{
    if (data.deleted) document.querySelector(`#row-${videoId}`).remove();
  });
}
</script>
{% endblock %}
''',
    'profile.html': '''
{% extends 'base.html' %}
{% block title %}{{ user.username }} 的主页 - 视频平台{% endblock %}
{% block content %}
<h2 class="mb-4">{{ user.username }} 的视频</h2>
<div class="row">
  {% for video in videos %}
  <div class="col-md-4 mb-4">
    <div class="card">
      <a href="{{ url_for('play_video', filename=video.filename) }}">
        <video src="{{ url_for('play_video', filename=video.filename) }}" class="card-img-top video-thumb" controls muted></video>
      </a>
      <div class="card-body">
        <h5 class="card-title">{{ video.title }}</h5>
        <p class="card-text text-truncate">{{ video.description or '' }}</p>
      </div>
    </div>
  </div>
  {% endfor %}
</div>
{% endblock %}
'''
}
app.jinja_loader = DictLoader(templates)

# ——— 数据库工具 —————————————————————————————————————————————————————————————————————————
def get_db_connection():
    """获取 SQLite 连接并设置行工厂。"""
    if 'db_connection' not in g:
        connection = sqlite3.connect(DATABASE_PATH)
        connection.row_factory = sqlite3.Row
        g.db_connection = connection
    return g.db_connection

@app.teardown_appcontext
def close_db_connection(exception):
    """关闭数据库连接。"""
    connection = g.pop('db_connection', None)
    if connection:
        connection.close()

def initialize_database():
    """初始化数据库表结构。"""
    db = get_db_connection()
    db.executescript("""
-- 用户表
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT UNIQUE NOT NULL,
  password TEXT NOT NULL,
  email TEXT UNIQUE NOT NULL
);
-- 视频表
CREATE TABLE IF NOT EXISTS videos (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  filename TEXT NOT NULL,
  description TEXT,
  is_public INTEGER NOT NULL DEFAULT 1,
  user_id INTEGER NOT NULL,
  FOREIGN KEY(user_id) REFERENCES users(id)
);
""")
    db.commit()

# ——— 用户模型 —————————————————————————————————————————————————————————————————————————
class User(UserMixin):
    def __init__(self, row):
        self.id       = row['id']
        self.username = row['username']
        self.password = row['password']
        self.email    = row['email']

@login_manager.user_loader
def load_user_by_id(user_id):
    """通过用户 ID 加载用户。"""
    row = get_db_connection().execute(
        'SELECT * FROM users WHERE id = ?',
        (user_id,)
    ).fetchone()
    return User(row) if row else None

def is_file_allowed(filename):
    """检查文件扩展名是否在允许列表。"""
    return '.' in filename and filename.rsplit('.',1)[1].lower() in ALLOWED_EXTENSIONS

# ——— 路由 —————————————————————————————————————————————————————————————————————————

@app.route('/')
def index():
    """首页：显示所有公开视频。"""
    db = get_db_connection()
    videos = db.execute("""
        SELECT v.id, v.title, v.filename, v.description, v.is_public, u.username
        FROM videos v
        JOIN users u ON v.user_id = u.id
        WHERE v.is_public = 1
        ORDER BY v.id DESC
    """).fetchall()
    return render_template('index.html', videos=videos)

@app.route('/register', methods=['GET','POST'])
def register():
    """用户注册。"""
    if request.method == 'POST':
        username = request.form['username'].strip()
        email    = request.form['email'].strip()
        password = request.form['password']
        try:
            get_db_connection().execute(
                'INSERT INTO users(username, password, email) VALUES(?,?,?)',
                (username, password, email)
            )
            get_db_connection().commit()
            flash('注册成功，请登录', 'success')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('用户名或邮箱已存在', 'danger')
    return render_template('register.html')

@app.route('/login', methods=['GET','POST'])
def login():
    """用户登录。"""
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        row = get_db_connection().execute(
            'SELECT * FROM users WHERE username = ?',
            (username,)
        ).fetchone()
        if row and row['password'] == password:
            login_user(User(row))
            return redirect(url_for('index'))
        flash('登录失败，请检查用户名或密码', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    """登出当前用户。"""
    logout_user()
    return redirect(url_for('index'))

@app.route('/upload', methods=['GET','POST'])
@login_required
def upload_video():
    """上传视频。"""
    if request.method == 'POST':
        title       = request.form['title'].strip()
        description = request.form['description'].strip()
        file_obj    = request.files.get('video')
        if not title or not file_obj or not is_file_allowed(file_obj.filename):
            flash('请填写标题并上传合法视频', 'danger')
        else:
            safe_name = secure_filename(file_obj.filename)
            os.makedirs(UPLOAD_FOLDER, exist_ok=True)
            file_obj.save(os.path.join(UPLOAD_FOLDER, safe_name))
            get_db_connection().execute(
                'INSERT INTO videos(title, filename, description, user_id) VALUES(?,?,?,?)',
                (title, safe_name, description, current_user.id)
            )
            get_db_connection().commit()
            flash('上传成功', 'success')
            return redirect(url_for('dashboard'))
    return render_template('upload.html')

@app.route('/dashboard')
@login_required
def dashboard():
    """管理中心：用户自己的视频列表。"""
    user_videos = get_db_connection().execute(
        'SELECT * FROM videos WHERE user_id = ? ORDER BY id DESC',
        (current_user.id,)
    ).fetchall()
    return render_template('dashboard.html', videos=user_videos)

@app.route('/video/<int:video_id>/action', methods=['POST'])
@login_required
def video_action(video_id):
    """
    单一接口完成两种操作：
     - 切换公开/隐藏（action: 'toggle'）
     - 删除视频（action: 'delete'）
    """
    action_type = request.json.get('action')
    db = get_db_connection()
    if action_type == 'toggle':
        row = db.execute(
            'SELECT is_public FROM videos WHERE id = ? AND user_id = ?',
            (video_id, current_user.id)
        ).fetchone()
        if not row:
            return jsonify({'error':'视频不存在或无权限'}),404
        new_visibility = 0 if row['is_public'] else 1
        db.execute(
            'UPDATE videos SET is_public = ? WHERE id = ?',
            (new_visibility, video_id)
        )
        db.commit()
        return jsonify({'new_state':new_visibility})
    elif action_type == 'delete':
        db.execute(
            'DELETE FROM videos WHERE id = ? AND user_id = ?',
            (video_id, current_user.id)
        )
        db.commit()
        return jsonify({'deleted':True})
    return jsonify({'error':'无效操作'}),400

@app.route('/user/<username>')
def profile(username):
    """个人主页：查看某个用户的公开视频。"""
    row = get_db_connection().execute(
        'SELECT * FROM users WHERE username = ?',
        (username,)
    ).fetchone()
    if not row:
        return "用户不存在",404
    public_videos = get_db_connection().execute(
        'SELECT * FROM videos WHERE user_id = ? AND is_public = 1 ORDER BY id DESC',
        (row['id'],)
    ).fetchall()
    return render_template('profile.html', user=row, videos=public_videos)

@app.route('/play/<filename>')
def play_video(filename):
    """静态提供上传的视频文件。"""
    return send_from_directory(UPLOAD_FOLDER, filename)

# ——— 启动 —————————————————————————————————————————————————————————————————————————
if __name__ == '__main__':
    initialize_database()
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    app.run(debug=True)
