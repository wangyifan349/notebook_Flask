import os
import sqlite3
from flask import Flask, request, session, redirect, url_for, render_template, flash, send_from_directory, g
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
# 配置参数
DATABASE = 'database.db'
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'mp4', 'avi', 'mov', 'mkv'}
app = Flask(__name__)
app.secret_key = 'your_secret_key'  # 请替换成安全随机的密钥
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
# 确保上传目录存在
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
# ------------------- 数据库连接 -------------------
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db
@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()
# ------------------- 数据库初始化 -------------------
def init_db():
    db = get_db()
    cursor = db.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL)")
    cursor.execute("CREATE TABLE IF NOT EXISTS videos (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, filename TEXT NOT NULL, FOREIGN KEY(user_id) REFERENCES users(id))")
    db.commit()
# ------------------- 工具函数 -------------------
def allowed_file(filename):
    if '.' not in filename:
        return False
    ext = filename.rsplit('.', 1)[1].lower()
    if ext in ALLOWED_EXTENSIONS:
        return True
    return Falss
def get_user_by_username(username):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
    user = cursor.fetchone()
    return user
def get_user_by_id(user_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    user = cursor.fetchone()
    return user
def get_videos_by_user_id(user_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM videos WHERE user_id = ?", (user_id,))
    videos = cursor.fetchall()
    return videos
def get_video_by_id(video_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM videos WHERE id = ?", (video_id,))
    video = cursor.fetchone()
    return video
def delete_video_by_id(video_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("DELETE FROM videos WHERE id = ?", (video_id,))
    db.commit()
# ------------------- 路由 -------------------
@app.route('/')
def index():
    return render_template('index.html')
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        if username == '' or password == '':
            flash('用户名和密码不能为空')
            return redirect(url_for('register'))
        if len(username) > 50 or len(password) > 128:
            flash('用户名或密码长度超限')
            return redirect(url_for('register'))
        if get_user_by_username(username) is not None:
            flash('用户名已存在')
            return redirect(url_for('register'))
        hashed_password = generate_password_hash(password)
        db = get_db()
        cursor = db.cursor()
        cursor.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, hashed_password))
        db.commit()
        flash('注册成功，请登录')
        return redirect(url_for('login'))
    return render_template('register.html')
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        if username == '' or password == '':
            flash('用户名和密码不能为空')
            return redirect(url_for('login'))
        user = get_user_by_username(username)
        if user is None:
            flash('用户名或密码错误')
            return redirect(url_for('login'))
        if not check_password_hash(user['password'], password):
            flash('用户名或密码错误')
            return redirect(url_for('login'))
        session['user_id'] = user['id']
        session['username'] = user['username']
        flash('登录成功')
        return redirect(url_for('index'))
    return render_template('login.html')
@app.route('/logout')
def logout():
    session.clear()
    flash('已退出登录')
    return redirect(url_for('index'))
@app.route('/upload', methods=['GET', 'POST'])
def upload():
    if not session.get('user_id'):
        flash('请先登录')
        return redirect(url_for('login'))
    if request.method == 'POST':
        if 'video' not in request.files:
            flash('没有视频文件')
            return redirect(request.url)
        file = request.files['video']
        if file.filename == '':
            flash('未选择文件')
            return redirect(request.url)
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            # 避免文件名冲突，加入用户id和时间戳
            import time
            filename = f"{session.get('user_id')}_{int(time.time())}_{filename}"
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            db = get_db()
            cursor = db.cursor()
            cursor.execute("INSERT INTO videos (user_id, filename) VALUES (?, ?)", (session.get('user_id'), filename))
            db.commit()
            flash('上传成功')
            return redirect(url_for('my_videos'))
        else:
            flash('不支持的文件格式')
            return redirect(request.url)
    return render_template('upload.html')
@app.route('/my_videos')
def my_videos():
    if not session.get('user_id'):
        flash('请先登录')
        return redirect(url_for('login'))
    videos = get_videos_by_user_id(session.get('user_id'))
    return render_template('my_videos.html', videos=videos)
@app.route('/delete_video/<int:video_id>', methods=['POST'])
def delete_video(video_id):
    if not session.get('user_id'):
        flash('请先登录')
        return redirect(url_for('login'))
    video = get_video_by_id(video_id)
    if video is None:
        flash('视频不存在')
        return redirect(url_for('my_videos'))
    if video['user_id'] != session.get('user_id'):
        flash('无权删除该视频')
        return redirect(url_for('my_videos'))
    # 删除文件
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], video['filename'])
    if os.path.exists(filepath):
        os.remove(filepath)
    # 删除数据库记录
    delete_video_by_id(video_id)
    flash('删除成功')
    return redirect(url_for('my_videos'))
@app.route('/search', methods=['GET', 'POST'])
def search():
    user = None
    videos = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        if username == '':
            flash('请输入用户名')
            return redirect(url_for('search'))
        user = get_user_by_username(username)
        if user is None:
            flash('未找到该用户')
            user = None
            videos = None
        else:
            videos = get_videos_by_user_id(user['id'])
    return render_template('search.html', user=user, videos=videos)
@app.route('/play/<int:video_id>')
def play(video_id):
    video = get_video_by_id(video_id)
    if video is None:
        flash('视频不存在')
        return redirect(url_for('index'))
    return render_template('play.html', video=video)
@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)
# ------------------- 启动前初始化 -------------------
@app.before_first_request
def before_first_request_func():
    init_db()
if __name__ == '__main__':
    app.run(debug=True)




1. `base.html`（全局基础模板）

```html
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>{% block title %}短视频平台{% endblock %}</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <!-- Bootstrap 5 CSS CDN -->
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
  {% block head %}{% endblock %}
</head>
<body>
<nav class="navbar navbar-expand-lg navbar-dark bg-primary mb-4">
  <div class="container">
    <a class="navbar-brand" href="{{ url_for('index') }}">短视频平台</a>
    <div>
      {% if session.get('user_id') %}
        <span class="navbar-text me-3">你好，{{ session.get('username') }}！</span>
        <a href="{{ url_for('upload') }}" class="btn btn-outline-light btn-sm me-2">上传视频</a>
        <a href="{{ url_for('my_videos') }}" class="btn btn-outline-light btn-sm me-2">我的视频</a>
        <a href="{{ url_for('logout') }}" class="btn btn-outline-light btn-sm">登出</a>
      {% else %}
        <a href="{{ url_for('login') }}" class="btn btn-outline-light btn-sm me-2">登录</a>
        <a href="{{ url_for('register') }}" class="btn btn-outline-light btn-sm">注册</a>
      {% endif %}
      <a href="{{ url_for('search') }}" class="btn btn-warning btn-sm ms-3">搜索视频</a>
    </div>
  </div>
</nav>

<div class="container">
  {% with messages = get_flashed_messages() %}
    {% if messages %}
      <div class="alert alert-info">
        {% for msg in messages %}
          <div>{{ msg }}</div>
        {% endfor %}
      </div>
    {% endif %}
  {% endwith %}
  {% block content %}{% endblock %}
</div>

<!-- Bootstrap 5 JS Bundle CDN -->
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
{% block scripts %}{% endblock %}
</body>
</html>
```

---

### 2. `index.html` （首页）

```html
{% extends "base.html" %}
{% block title %}首页 - 短视频平台{% endblock %}
{% block content %}
<div class="text-center">
  <h1 class="mb-4">欢迎来到短视频平台</h1>
  {% if session.get('user_id') %}
    <p>你好，{{ session.get('username') }}！可以开始上传、管理你的视频，或搜索其他用户的视频。</p>
    <a href="{{ url_for('upload') }}" class="btn btn-primary me-2">上传视频</a>
    <a href="{{ url_for('my_videos') }}" class="btn btn-secondary me-2">管理我的视频</a>
  {% else %}
    <p>请先登录或注册，开启你的短视频之旅。</p>
    <a href="{{ url_for('login') }}" class="btn btn-success me-2">登录</a>
    <a href="{{ url_for('register') }}" class="btn btn-info">注册</a>
  {% endif %}
  <a href="{{ url_for('search') }}" class="btn btn-warning mt-3">搜索视频</a>
</div>
{% endblock %}
```

---

### 3. `register.html` （注册页）

```html
{% extends "base.html" %}
{% block title %}注册 - 短视频平台{% endblock %}
{% block content %}
<h2 class="mb-4">注册新用户</h2>
<form method="post" class="w-50 mx-auto">
  <div class="mb-3">
    <label for="username" class="form-label">用户名</label>
    <input type="text" class="form-control" id="username" name="username" required maxlength="50" placeholder="请输入用户名">
  </div>

  <div class="mb-3">
    <label for="password" class="form-label">密码</label>
    <input type="password" class="form-control" id="password" name="password" required maxlength="128" placeholder="请输入密码">
  </div>

  <button type="submit" class="btn btn-primary">注册</button>
  <a href="{{ url_for('login') }}" class="btn btn-link">已有账号？登录</a>
</form>
{% endblock %}
```

---

### 4. `login.html` （登录页）

```html
{% extends "base.html" %}
{% block title %}登录 - 短视频平台{% endblock %}
{% block content %}
<h2 class="mb-4">用户登录</h2>
<form method="post" class="w-50 mx-auto">
  <div class="mb-3">
    <label for="username" class="form-label">用户名</label>
    <input type="text" class="form-control" id="username" name="username" required maxlength="50" placeholder="请输入用户名">
  </div>

  <div class="mb-3">
    <label for="password" class="form-label">密码</label>
    <input type="password" class="form-control" id="password" name="password" required maxlength="128" placeholder="请输入密码">
  </div>

  <button type="submit" class="btn btn-success">登录</button>
  <a href="{{ url_for('register') }}" class="btn btn-link">还没有账号？注册</a>
</form>
{% endblock %}
```

---

### 5. `upload.html` （上传视频）

```html
{% extends "base.html" %}
{% block title %}上传视频 - 短视频平台{% endblock %}
{% block content %}
<h2 class="mb-4">上传视频</h2>
<form method="post" enctype="multipart/form-data" class="w-50 mx-auto mb-3">
  <div class="mb-3">
    <label for="video" class="form-label">选择视频文件</label>
    <input class="form-control" type="file" id="video" name="video" accept="video/*" required>
  </div>
  
  <button type="submit" class="btn btn-primary">上传</button>
  <a href="{{ url_for('index') }}" class="btn btn-secondary ms-2">返回首页</a>
</form>
<p class="text-muted text-center">支持的视频格式：mp4, avi, mov, mkv</p>
{% endblock %}
```

---

### 6. `my_videos.html` （我的视频管理）

```html
{% extends "base.html" %}
{% block title %}我的视频 - 短视频平台{% endblock %}
{% block content %}
<h2 class="mb-4">我的视频</h2>
{% if videos %}
<table class="table table-bordered table-hover align-middle">
  <thead class="table-light">
    <tr>
      <th>视频ID</th>
      <th>文件名</th>
      <th>操作</th>
    </tr>
  </thead>
  <tbody>
  {% for video in videos %}
    <tr>
      <td>{{ video['id'] }}</td>
      <td>{{ video['filename'] }}</td>
      <td>
        <a href="{{ url_for('play', video_id=video['id']) }}" class="btn btn-sm btn-success me-2">播放</a>
        <form method="post" action="{{ url_for('delete_video', video_id=video['id']) }}" style="display:inline;" onsubmit="return confirm('确认删除该视频吗？');">
          <button type="submit" class="btn btn-sm btn-danger">删除</button>
        </form>
      </td>
    </tr>
  {% endfor %}
  </tbody>
</table>
{% else %}
<p>你还没有上传任何视频，快去<a href="{{ url_for('upload') }}">上传</a>吧！</p>
{% endif %}
{% endblock %}
```

---

### 7. `search.html` （搜索用户视频）

```html
{% extends "base.html" %}
{% block title %}视频搜索 - 短视频平台{% endblock %}
{% block content %}
<h2 class="mb-4">按用户名搜索视频</h2>
<form method="post" class="w-50 mx-auto mb-4">
  <div class="input-group">
    <input type="text" class="form-control" name="username" placeholder="请输入用户名" required maxlength="50" aria-label="用户名">
    <button class="btn btn-warning" type="submit">搜索</button>
  </div>
</form>

{% if user %}
  <h5>搜索到用户名：<strong>{{ user['username'] }}</strong> 的视频列表</h5>
  {% if videos %}
    <ul class="list-group">
      {% for video in videos %}
        <li class="list-group-item d-flex justify-content-between align-items-center">
          视频ID：{{ video['id'] }}  ，文件名：{{ video['filename'] }}
          <a href="{{ url_for('play', video_id=video['id']) }}" class="btn btn-sm btn-success">播放</a>
        </li>
      {% endfor %}
    </ul>
  {% else %}
    <p>该用户暂无视频</p>
  {% endif %}
{% endif %}
{% endblock %}
```

---

### 8. `play.html` （视频播放页）

```html
{% extends "base.html" %}
{% block title %}播放视频 - 短视频平台{% endblock %}
{% block content %}
<h2 class="mb-4">播放视频</h2>
<div class="card mx-auto" style="max-width: 720px;">
  <video controls preload="metadata" class="w-100" style="max-height: 480px;">
    <source src="{{ url_for('uploaded_file', filename=video['filename']) }}" type="video/mp4">
    您的浏览器不支持视频播放。
  </video>
  <div class="card-body">
    <p class="card-text">文件名：{{ video['filename'] }}</p>
    <a href="{{ url_for('index') }}" class="btn btn-secondary">返回首页</a>
    {% if session.get('user_id') == video['user_id'] %}
      <a href="{{ url_for('my_videos') }}" class="btn btn-primary ms-2">管理我的视频</a>
    {% endif %}
  </div>
</div>
{% endblock %}
