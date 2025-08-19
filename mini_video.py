import os
import sqlite3
from flask import Flask, g, render_template, request, redirect, url_for, flash, send_from_directory
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.utils import secure_filename
from jinja2 import DictLoader

# ——— 配置 —————————————————————————————————————————————————————————————————————————
DATABASE       = 'video.db'
UPLOAD_FOLDER  = 'uploads'
ALLOWED_EXTENSIONS = {'mp4', 'webm', 'ogg'}

# 内嵌模板字典
templates = {
    'base.html': '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <title>{% block title %}视频平台{% endblock %}</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
  <style> body{padding-top:60px;} .video-thumb{width:100%;height:auto;} </style>
</head>
<body>
<nav class="navbar navbar-expand-lg navbar-dark bg-dark fixed-top">
  <div class="container-fluid">
    <a class="navbar-brand" href="{{ url_for('index') }}">视频平台</a>
    <div class="collapse navbar-collapse">
      <ul class="navbar-nav me-auto">
        <li class="nav-item"><a class="nav-link" href="{{ url_for('index') }}">首页</a></li>
        {% if current_user.is_authenticated %}
        <li class="nav-item"><a class="nav-link" href="{{ url_for('dashboard') }}">管理中心</a></li>
        {% endif %}
      </ul>
      <form class="d-flex" method="post" action="{{ url_for('search') }}">
        <input class="form-control me-2" name="query" placeholder="搜索视频">
        <button class="btn btn-outline-success">搜索</button>
      </form>
      <ul class="navbar-nav ms-3">
        {% if current_user.is_authenticated %}
          <li class="nav-item"><a class="nav-link" href="{{ url_for('profile', username=current_user.username) }}">{{ current_user.username }}</a></li>
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
    {% for category, msg in messages %}
      <div class="alert alert-{{ category }} alert-dismissible fade show">{{ msg }}
        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
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
<h2>最新视频</h2>
<div class="row">
  {% for v in videos %}
  <div class="col-md-4 mb-4">
    <div class="card">
      <a href="{{ url_for('play', filename=v.filename) }}">
        <img src="{{ url_for('play', filename=v.filename) }}" class="card-img-top video-thumb">
      </a>
      <div class="card-body">
        <h5 class="card-title">{{ v.title }}</h5>
        <p class="card-text text-truncate">{{ v.description or '' }}</p>
        <p class="card-text"><small class="text-muted">By {{ v.username }}</small></p>
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
<h2>注册</h2>
<form method="post">
  <div class="mb-3"><label>用户名</label><input name="username" class="form-control" required></div>
  <div class="mb-3"><label>邮箱</label><input type="email" name="email" class="form-control" required></div>
  <div class="mb-3"><label>密码</label><input type="password" name="password" class="form-control" required></div>
  <button class="btn btn-primary">注册</button>
</form>
{% endblock %}
''',
    'login.html': '''
{% extends 'base.html' %}
{% block title %}登录 - 视频平台{% endblock %}
{% block content %}
<h2>登录</h2>
<form method="post">
  <div class="mb-3"><label>用户名</label><input name="username" class="form-control" required></div>
  <div class="mb-3"><label>密码</label><input type="password" name="password" class="form-control" required></div>
  <button class="btn btn-primary">登录</button>
</form>
{% endblock %}
''',
    'upload.html': '''
{% extends 'base.html' %}
{% block title %}上传视频 - 视频平台{% endblock %}
{% block content %}
<h2>上传视频</h2>
<form method="post" enctype="multipart/form-data">
  <div class="mb-3"><label>标题</label><input name="title" class="form-control" required></div>
  <div class="mb-3"><label>描述</label><textarea name="description" class="form-control"></textarea></div>
  <div class="mb-3"><label>选择视频</label><input type="file" name="video" class="form-control" accept="video/*" required></div>
  <button class="btn btn-success">上传</button>
</form>
{% endblock %}
''',
    'dashboard.html': '''
{% extends 'base.html' %}
{% block title %}我的管理中心 - 视频平台{% endblock %}
{% block content %}
<h2>我的视频管理</h2>
<a href="{{ url_for('upload') }}" class="btn btn-success mb-3">上传新视频</a>
<table class="table">
  <thead><tr><th>预览</th><th>标题</th><th>状态</th><th>操作</th></tr></thead>
  <tbody>
    {% for v in videos %}
    <tr>
      <td><a href="{{ url_for('play', filename=v.filename) }}"><video src="{{ url_for('play', filename=v.filename) }}" width="120" controls muted></video></a></td>
      <td>{{ v.title }}</td>
      <td>{% if v.is_public %}<span class="badge bg-success">公开</span>{% else %}<span class="badge bg-secondary">隐藏</span>{% endif %}</td>
      <td>
        <a href="{{ url_for('toggle_video', video_id=v.id) }}" class="btn btn-sm btn-warning">{% if v.is_public %}隐藏{% else %}公开{% endif %}</a>
        <a href="{{ url_for('delete_video', video_id=v.id) }}" class="btn btn-sm btn-danger" onclick="return confirm('确定删除？');">删除</a>
      </td>
    </tr>
    {% endfor %}
  </tbody>
</table>
{% endblock %}
''',
    'profile.html': '''
{% extends 'base.html' %}
{% block title %}{{ user.username }} 的主页 - 视频平台{% endblock %}
{% block content %}
<h2>{{ user.username }} 的视频</h2>
<div class="row">
  {% for v in videos %}
  <div class="col-md-4 mb-4">
    <div class="card">
      <a href="{{ url_for('play', filename=v.filename) }}">
        <video src="{{ url_for('play', filename=v.filename) }}" class="card-img-top video-thumb" controls muted></video>
      </a>
      <div class="card-body">
        <h5 class="card-title">{{ v.title }}</h5>
        <p class="card-text text-truncate">{{ v.description or '' }}</p>
      </div>
    </div>
  </div>
  {% endfor %}
</div>
{% endblock %}
''',
    'search.html': '''
{% extends 'base.html' %}
{% block title %}搜索:“{{ query }}” - 视频平台{% endblock %}
{% block content %}
<h2>搜索结果：“{{ query }}”</h2>
{% if results %}
<div class="row">
  {% for v in results %}
  <div class="col-md-4 mb-4">
    <div class="card">
      <a href="{{ url_for('play', filename=v.filename) }}">
        <video src="{{ url_for('play', filename=v.filename) }}" class="card-img-top video-thumb" controls muted></video>
      </a>
      <div class="card-body">
        <h5 class="card-title">{{ v.title }}</h5>
        <p class="card-text text-truncate">{{ v.description or '' }}</p>
      </div>
    </div>
  </div>
  {% endfor %}
</div>
{% else %}
<p>未找到相关视频。</p>
{% endif %}
{% endblock %}
'''
}

# ——— 应用初始化 —————————————————————————————————————————————————————————————————————————
app = Flask(__name__)
app.config['SECRET_KEY']     = 'you-will-never-guess'
app.config['UPLOAD_FOLDER']  = UPLOAD_FOLDER
app.jinja_loader = DictLoader(templates)

login_manager = LoginManager(app)
login_manager.login_view = 'login'

# ——— LCS 算法 —————————————————————————————————————————————————————————————————————————
def lcs(a: str, b: str):
    n, m = len(a), len(b)
    dp = [[0]*(m+1) for _ in range(n+1)]
    for i in range(n-1, -1, -1):
        for j in range(m-1, -1, -1):
            dp[i][j] = dp[i+1][j+1]+1 if a[i]==b[j] else max(dp[i+1][j], dp[i][j+1])
    return dp

# ——— 数据库工具 —————————————————————————————————————————————————————————————————————————
def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(exc):
    db = g.pop('db', None)
    if db: db.close()

def init_db():
    db = get_db()
    db.executescript("""
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT UNIQUE NOT NULL,
  password TEXT NOT NULL,
  email TEXT UNIQUE NOT NULL
);
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
def load_user(user_id):
    row = get_db().execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone()
    return User(row) if row else None

def allowed_file(fn):
    return '.' in fn and fn.rsplit('.',1)[1].lower() in ALLOWED_EXTENSIONS

# ——— 路由定义 —————————————————————————————————————————————————————————————————————————
@app.route('/')
def index():
    db = get_db()
    videos = db.execute('''
      SELECT v.*, u.username FROM videos v 
      JOIN users u ON v.user_id=u.id
      WHERE v.is_public=1 ORDER BY v.id DESC
    ''').fetchall()
    return render_template('index.html', videos=videos)

@app.route('/register', methods=['GET','POST'])
def register():
    if request.method=='POST':
        u, e, p = request.form['username'].strip(), request.form['email'].strip(), request.form['password']
        try:
            get_db().execute('INSERT INTO users(username,password,email) VALUES(?,?,?)',(u,p,e))
            get_db().commit()
            flash('注册成功，请登录','success'); return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('用户名或邮箱已存在','danger')
    return render_template('register.html')

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method=='POST':
        row = get_db().execute('SELECT * FROM users WHERE username=?',(request.form['username'],)).fetchone()
        if row and row['password']==request.form['password']:
            login_user(User(row)); return redirect(url_for('index'))
        flash('登录失败，请检查用户名或密码','danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user(); return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    vids = get_db().execute('SELECT * FROM videos WHERE user_id=? ORDER BY id DESC',(current_user.id,)).fetchall()
    return render_template('dashboard.html', videos=vids)

@app.route('/upload', methods=['GET','POST'])
@login_required
def upload():
    if request.method=='POST':
        title = request.form['title'].strip()
        desc  = request.form['description'].strip()
        file  = request.files.get('video')
        if not title or not file or not allowed_file(file.filename):
            flash('请填写标题并上传合法视频','danger')
        else:
            fn = secure_filename(file.filename)
            os.makedirs(UPLOAD_FOLDER, exist_ok=True)
            file.save(os.path.join(UPLOAD_FOLDER, fn))
            get_db().execute('''
              INSERT INTO videos(title,filename,description,user_id)
              VALUES(?,?,?,?)
            ''',(title, fn, desc, current_user.id))
            get_db().commit()
            flash('上传成功','success')
            return redirect(url_for('dashboard'))
    return render_template('upload.html')

@app.route('/video/<int:video_id>/delete')
@login_required
def delete_video(video_id):
    get_db().execute('DELETE FROM videos WHERE id=? AND user_id=?',(video_id,current_user.id))
    get_db().commit(); flash('视频已删除','info')
    return redirect(url_for('dashboard'))

@app.route('/video/<int:video_id>/toggle')
@login_required
def toggle_video(video_id):
    row = get_db().execute('SELECT is_public FROM videos WHERE id=? AND user_id=?',(video_id,current_user.id)).fetchone()
    if row:
        ns = 0 if row['is_public'] else 1
        get_db().execute('UPDATE videos SET is_public=? WHERE id=?',(ns,video_id))
        get_db().commit(); flash(f"视频已{'公开' if ns else '隐藏'}",'info')
    return redirect(url_for('dashboard'))

@app.route('/user/<username>')
def profile(username):
    u = get_db().execute('SELECT * FROM users WHERE username=?',(username,)).fetchone()
    if not u: return "用户不存在",404
    vids = get_db().execute('''
      SELECT * FROM videos WHERE user_id=? AND is_public=1 ORDER BY id DESC
    ''',(u['id'],)).fetchall()
    return render_template('profile.html', user=u, videos=vids)

@app.route('/play/<filename>')
def play(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

@app.route('/search', methods=['GET','POST'])
def search():
    q = request.form.get('query','').lower()
    res = []
    for v in get_db().execute('SELECT * FROM videos WHERE is_public=1').fetchall():
        txt = (v['title']+' '+(v['description'] or '')).lower()
        score = lcs(q, txt)[0][0]
        if score>0: res.append((v,score))
    res.sort(key=lambda x:x[1], reverse=True)
    return render_template('search.html', query=q, results=[r[0] for r in res])

# ——— 启动 —————————————————————————————————————————————————————————————————————————
if __name__=='__main__':
    init_db()
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    app.run(debug=True)
