import os
import sqlite3
from flask import Flask, request, session, redirect, url_for, render_template, flash, send_from_directory, g
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from jinja2 import DictLoader

DATABASE = 'database.db'
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'mp4', 'avi', 'mov', 'mkv'}

app = Flask(__name__)
app.secret_key = 'your_secret_key'  # 请改成你自己的安全密钥
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# ------------------ 这里写所有模板 ------------------
templates = {
    'base.html': '''
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>短视频平台</title>
<style>
body {
  font-family: Arial, sans-serif;
  margin: 0;
  padding: 0;
  line-height: 1.6;
  background-color: #f7f7f7;
}
header {
  background: #333;
  color: #fff;
  padding: 1em;
}
header h1 {
  margin: 0;
}
nav a {
  color: #fff;
  margin-right: 10px;
  text-decoration: none;
}
main {
  margin: 2em;
  background: #fff;
  padding: 1em;
  border-radius: 10px;
}
footer {
  background: #333;
  color: #fff;
  text-align: center;
  padding: 1em;
  position: fixed;
  bottom: 0; left: 0; right: 0;
}
.flash {
  background-color: #ffcccb;
  color: #333;
  padding: 0.5em;
  margin-bottom: 1em;
  border-radius: 5px;
}
ul {
  padding-left: 1.5em;
}
button {
  margin-top: 1em;
  padding: 0.5em 1em;
}
.video-list video {
  max-width: 100%;
  height: auto;
  margin-bottom: 10px;
}
</style>
</head>
<body>
<header>
<h1>短视频平台</h1>
<nav>
    <a href="{{ url_for('index') }}">首页</a>
    {% if session.get('user_id') %}
        <a href="{{ url_for('upload') }}">上传视频</a>
        <a href="{{ url_for('my_videos') }}">我的视频</a>
        <a href="{{ url_for('logout') }}">退出</a>
    {% else %}
        <a href="{{ url_for('login') }}">登录</a>
        <a href="{{ url_for('register') }}">注册</a>
    {% endif %}
    <a href="{{ url_for('search') }}">搜索用户</a>
</nav>
</header>
<main>
{% with messages = get_flashed_messages() %}
  {% if messages %}
  <div class="flash">
    {% for message in messages %}
      <p>{{ message }}</p>
    {% endfor %}
  </div>
  {% endif %}
{% endwith %}
{% block content %}{% endblock %}
</main>
<footer>
<p>短视频平台 &copy; 2024</p>
</footer>
</body>
</html>
''',

    'index.html': '''
{% extends "base.html" %}
{% block content %}
<p>欢迎来到短视频平台！</p>
{% endblock %}
''',

    'register.html': '''
{% extends "base.html" %}
{% block content %}
<p>注册账户：</p>
<form method="post" action="{{ url_for('register') }}">
<p>用户名：<input type="text" name="username" required></p>
<p>密码：<input type="password" name="password" required></p>
<button type='submit'>注册</button>
</form>
{% endblock %}
''',

    'login.html': '''
{% extends "base.html" %}
{% block content %}
<p>登录：</p>
<form method="post" action="{{ url_for('login') }}">
<p>用户名：<input type="text" name="username" required></p>
<p>密码：<input type="password" name="password" required></p>
<button type="submit">登录</button>
</form>
{% endblock %}
''',

    'upload.html': '''
{% extends "base.html" %}
{% block content %}
<p>上传视频：</p>
<form method="post" enctype="multipart/form-data">
<p><input type="file" name="video" accept="video/*" required></p>
<button type="submit">上传</button>
</form>
{% endblock %}
''',

    'my_videos.html': '''
{% extends "base.html" %}
{% block content %}
<p>我的视频：</p>
<div class="video-list">
{% if videos %}
  <ul>
  {% for video in videos %}
    <li>
      <a href="{{ url_for('play', video_id=video['id']) }}">{{ video['filename'] }}</a>
      <form method="post" action="{{ url_for('delete_video', video_id=video['id']) }}" style="display:inline;" onsubmit="return confirm('确认删除该视频？');">
        <button type="submit">删除</button>
      </form>
    </li>
  {% endfor %}
  </ul>
{% else %}
<p>没有上传过视频。</p>
{% endif %}
</div>
{% endblock %}
''',

    'search.html': '''
{% extends "base.html" %}
{% block content %}
<p>搜索用户并查看视频：</p>
<form method="post" action="{{ url_for('search') }}">
<p>用户名：<input type="text" name="username" required></p>
<button type="submit">搜索</button>
</form>
{% if user %}
<h3>用户 "{{ user['username'] }}" 的视频：</h3>
    {% if videos %}
      <ul>
      {% for video in videos %}
        <li><a href="{{ url_for('play', video_id=video['id']) }}">{{ video['filename'] }}</a></li>
      {% endfor %}
      </ul>
    {% else %}
      <p>该用户无视频。</p>
    {% endif %}
{% elif user is not none %}
<p>没有找到该用户。</p>
{% endif %}
{% endblock %}
''',

    'play.html': '''
{% extends "base.html" %}
{% block content %}
<p>播放视频：</p>
<video controls width="600">
  <source src="{{ url_for('uploaded_file', filename=video['filename']) }}" type="video/mp4">
  您的浏览器不支持 video 标签。
</video>
{% endblock %}
''',
}

app.jinja_loader = DictLoader(templates)

# ---------- 下面是应用逻辑 ----------

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

def init_db():
    db = get_db()
    cursor = db.cursor()
    cursor.execute('''
      CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL
      )''')
    cursor.execute('''
      CREATE TABLE IF NOT EXISTS videos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        filename TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id)
      )
    ''')
    db.commit()

def allowed_file(filename):
    if '.' not in filename:
        return False
    ext = filename.rsplit('.', 1)[1].lower()
    return ext in ALLOWED_EXTENSIONS

def get_user_by_username(username):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
    return cursor.fetchone()

def get_user_by_id(user_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    return cursor.fetchone()

def get_videos_by_user_id(user_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM videos WHERE user_id = ?", (user_id,))
    return cursor.fetchall()

def get_video_by_id(video_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM videos WHERE id = ?", (video_id,))
    return cursor.fetchone()

def delete_video_by_id(video_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("DELETE FROM videos WHERE id = ?", (video_id,))
    db.commit()

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
        if user is None or not check_password_hash(user['password'], password):
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
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], video['filename'])
    if os.path.exists(filepath):
        os.remove(filepath)
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

@app.before_first_request
def before_first_request_func():
    init_db()

if __name__ == '__main__':
    app.run(debug=True)
