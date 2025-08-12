import os
from flask import Flask, render_template_string, request, redirect, url_for, flash, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config.update(
    SECRET_KEY='replace-with-your-secret-key',
    SQLALCHEMY_DATABASE_URI='sqlite:///app.db',
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    UPLOAD_FOLDER=os.path.join(os.path.dirname(__file__), 'uploads'),
    ALLOWED_EXTENSIONS={'mp4', 'avi', 'mkv'},
    ADMIN_USERNAME='admin'
)
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login_user'

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    videos = db.relationship('Video', backref='owner', lazy=True)
    def set_password(self, pwd): self.password_hash = generate_password_hash(pwd)
    def check_password(self, pwd): return check_password_hash(self.password_hash, pwd)

class Video(db.Model):
    __tablename__ = 'videos'
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(128), nullable=False)
    title = db.Column(db.String(128), nullable=False)
    description = db.Column(db.Text)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    timestamp = db.Column(db.DateTime, server_default=db.func.now())

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def allowed_file(filename):
    ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
    return ext in app.config['ALLOWED_EXTENSIONS']

def compute_lcs_length(a: str, b: str) -> int:
    la, lb = len(a), len(b)
    dp = [[0]*(lb+1) for _ in range(la+1)]
    for i in range(la-1, -1, -1):
        for j in range(lb-1, -1, -1):
            if a[i] == b[j]:
                dp[i][j] = dp[i+1][j+1] + 1
            else:
                dp[i][j] = max(dp[i+1][j], dp[i][j+1])
    return dp[0][0]

def similarity_score(query: str, target: str) -> float:
    if not query or not target:
        return 0.0
    lcs = compute_lcs_length(query.lower(), target.lower())
    return lcs / max(len(query), len(target))

@app.before_first_request
def initialize_database():
    db.create_all()
    admin = User.query.filter_by(username=app.config['ADMIN_USERNAME']).first()
    if not admin:
        admin = User(username=app.config['ADMIN_USERNAME'], is_admin=True)
        admin.set_password('adminpass')
        db.session.add(admin)
        db.session.commit()

BASE_TEMPLATE = '''
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"><title>Video Manager</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body class="bg-light">
<nav class="navbar navbar-expand-lg navbar-dark bg-primary">
  <div class="container-fluid">
    <a class="navbar-brand" href="{{ url_for('home') }}">VideoManager</a>
    <div class="collapse navbar-collapse">
      <ul class="navbar-nav me-auto">
        {% if current_user.is_authenticated %}
          <li class="nav-item"><a class="nav-link" href="{{ url_for('upload_video') }}">Upload</a></li>
          {% if current_user.is_admin %}
            <li class="nav-item"><a class="nav-link" href="{{ url_for('manage_users') }}">User Admin</a></li>
          {% endif %}
          <li class="nav-item"><a class="nav-link" href="{{ url_for('logout_user') }}">Logout</a></li>
        {% else %}
          <li class="nav-item"><a class="nav-link" href="{{ url_for('login_user') }}">Login</a></li>
          <li class="nav-item"><a class="nav-link" href="{{ url_for('register_user') }}">Register</a></li>
        {% endif %}
      </ul>
      <form class="d-flex" method="get" action="{{ url_for('home') }}">
        <input class="form-control me-2" name="q" placeholder="Search videos or users" value="{{ request.args.get('q','') }}">
        <button class="btn btn-outline-light">Search</button>
      </form>
    </div>
  </div>
</nav>
<div class="container my-4">
  {% with messages = get_flashed_messages() %}
    {% if messages %}
      <div class="alert alert-info">{{ messages[0] }}</div>
    {% endif %}
  {% endwith %}
  {{ content|safe }}
</div>
</body>
</html>
'''

def render_page(content, **context):
    return render_template_string(BASE_TEMPLATE, content=content, **context)

@app.route('/')
def home():
    query = request.args.get('q', '').strip()
    video_entries = []
    if query:
        for vid in Video.query.all():
            score_title = similarity_score(query, vid.title)
            score_user = similarity_score(query, vid.owner.username)
            best_score = max(score_title, score_user)
            if best_score > 0:
                video_entries.append((vid, best_score))
        video_entries.sort(key=lambda x: x[1], reverse=True)
    else:
        video_entries = [(v, 0) for v in Video.query.order_by(Video.timestamp.desc()).all()]

    content = '''
<div class="row">
  {% for vid, score in video_entries %}
    <div class="col-md-4 mb-4">
      <div class="card h-100">
        <video class="card-img-top" src="{{ url_for('serve_upload', filename=vid.filename) }}" controls muted></video>
        <div class="card-body">
          <h5 class="card-title">{{ vid.title }}</h5>
          <p class="card-text"><small class="text-muted">by {{ vid.owner.username }}</small></p>
          {% if score > 0 %}
            <p class="badge bg-info text-dark">Similarity: {{ '%.2f'|format(score*100) }}%</p>
          {% endif %}
          <a href="{{ url_for('play_video', video_id=vid.id) }}" class="btn btn-primary btn-sm">Play</a>
          <a href="{{ url_for('download_video', video_id=vid.id) }}" class="btn btn-secondary btn-sm">Download</a>
          {% if current_user.is_authenticated and (vid.owner.id==current_user.id or current_user.is_admin) %}
            <form method="post" action="{{ url_for('delete_video', video_id=vid.id) }}" class="d-inline">
              <button class="btn btn-danger btn-sm">Delete</button>
            </form>
          {% endif %}
        </div>
      </div>
    </div>
  {% endfor %}
</div>
'''
    return render_page(content, video_entries=video_entries)

@app.route('/users/register', methods=['GET','POST'])
def register_user():
    if current_user.is_authenticated:
        return redirect(url_for('home'))
    if request.method == 'POST':
        uname = request.form['username'].strip()
        pwd = request.form['password']
        if User.query.filter_by(username=uname).first():
            flash('Username already exists')
        else:
            user = User(username=uname)
            user.set_password(pwd)
            db.session.add(user)
            db.session.commit()
            flash('Registration successful')
            return redirect(url_for('login_user'))
    content = '''
<h2>Register</h2>
<form method="post">
  <div class="mb-3"><input name="username" class="form-control" placeholder="Username" required></div>
  <div class="mb-3"><input type="password" name="password" class="form-control" placeholder="Password" required></div>
  <button class="btn btn-primary">Register</button>
</form>
'''
    return render_page(content)

@app.route('/users/login', methods=['GET','POST'])
def login_user():
    if current_user.is_authenticated:
        return redirect(url_for('home'))
    if request.method == 'POST':
        uname = request.form['username'].strip()
        pwd = request.form['password']
        user = User.query.filter_by(username=uname).first()
        if user and user.check_password(pwd):
            login_user(user)
            return redirect(url_for('home'))
        flash('Invalid credentials')
    content = '''
<h2>Login</h2>
<form method="post">
  <div class="mb-3"><input name="username" class="form-control" placeholder="Username" required></div>
  <div class="mb-3"><input type="password" name="password" class="form-control" placeholder="Password" required></div>
  <button class="btn btn-primary">Login</button>
</form>
'''
    return render_page(content)

@app.route('/users/logout')
@login_required
def logout_user():
    logout_user()
    return redirect(url_for('home'))

@app.route('/videos/upload', methods=['GET','POST'])
@login_required
def upload_video():
    if request.method == 'POST':
        file = request.files.get('file')
        title = request.form['title'].strip()
        desc = request.form.get('description','').strip()
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            vid = Video(filename=filename, title=title, description=desc, owner=current_user)
            db.session.add(vid)
            db.session.commit()
            flash('Upload successful')
            return redirect(url_for('home'))
        flash('Invalid file format')
    content = '''
<h2>Upload Video</h2>
<form method="post" enctype="multipart/form-data">
  <div class="mb-3"><input name="title" class="form-control" placeholder="Title" required></div>
  <div class="mb-3"><textarea name="description" class="form-control" placeholder="Description"></textarea></div>
  <div class="mb-3"><input type="file" name="file" class="form-control" required></div>
  <button class="btn btn-primary">Upload</button>
</form>
'''
    return render_page(content)

@app.route('/uploads/<path:filename>')
def serve_upload(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/videos/<int:video_id>/play')
def play_video(video_id):
    vid = Video.query.get_or_404(video_id)
    content = '''
<h2>{{ vid.title }}</h2>
<video class="w-100 mb-3" src="{{ url_for('serve_upload', filename=vid.filename) }}" controls autoplay></video>
<p>{{ vid.description }}</p>
'''
    return render_page(content, vid=vid)

@app.route('/videos/<int:video_id>/download')
def download_video(video_id):
    vid = Video.query.get_or_404(video_id)
    return send_from_directory(app.config['UPLOAD_FOLDER'], vid.filename, as_attachment=True)

@app.route('/videos/<int:video_id>/delete', methods=['POST'])
@login_required
def delete_video(video_id):
    vid = Video.query.get_or_404(video_id)
    if vid.owner != current_user and not current_user.is_admin:
        flash('Permission denied')
    else:
        path = os.path.join(app.config['UPLOAD_FOLDER'], vid.filename)
        if os.path.exists(path):
            os.remove(path)
        db.session.delete(vid)
        db.session.commit()
        flash('Video deleted')
    return redirect(url_for('home'))

@app.route('/admin/users', methods=['GET'])
@login_required
def manage_users():
    if not current_user.is_admin:
        flash('Permission denied')
        return redirect(url_for('home'))
    query = request.args.get('q','').strip()
    if query:
        user_list = []
        for u in User.query.all():
            score = similarity_score(query, u.username)
            if score > 0:
                user_list.append((u, score))
        user_list.sort(key=lambda x: x[1], reverse=True)
    else:
        user_list = [(u, 0) for u in User.query.order_by(User.id).all()]

    content = '''
<h2>User Management</h2>
<form class="row g-2 mb-3" method="get">
  <div class="col"><input name="q" class="form-control" placeholder="Search username" value="{{ request.args.get('q','') }}"></div>
  <div class="col-auto"><button class="btn btn-outline-primary">Search</button></div>
</form>
<table class="table table-striped">
<tr><th>ID</th><th>Username</th><th>Admin</th><th>Similarity</th><th>Actions</th></tr>
{% for user, score in user_list %}
<tr>
  <td>{{ user.id }}</td>
  <td>{{ user.username }}</td>
  <td>{{ 'Yes' if user.is_admin else 'No' }}</td>
  <td>{% if score>0 %}{{ '%.2f'|format(score*100) }}%{% endif %}</td>
  <td>
    {% if user.id != current_user.id %}
    <form method="post" action="{{ url_for('delete_user', user_id=user.id) }}" onsubmit="return confirm('Confirm delete?');">
      <button class="btn btn-danger btn-sm">Delete</button>
    </form>
    {% endif %}
  </td>
</tr>
{% endfor %}
</table>
'''
    return render_page(content, user_list=user_list)

@app.route('/admin/users/<int:user_id>/delete', methods=['POST'])
@login_required
def delete_user(user_id):
    if not current_user.is_admin:
        flash('Permission denied')
        return redirect(url_for('home'))
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash('Cannot delete yourself')
    else:
        for vid in user.videos:
            try:
                os.remove(os.path.join(app.config['UPLOAD_FOLDER'], vid.filename))
            except OSError:
                pass
            db.session.delete(vid)
        db.session.delete(user)
        db.session.commit()
        flash('User and their videos deleted')
    return redirect(url_for('manage_users'))

if __name__ == '__main__':
    app.run(debug=True）






import os
from flask import (
    Flask, request, redirect, url_for, render_template_string, flash,
    send_from_directory, abort
)
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager, UserMixin, login_user, logout_user,
    login_required, current_user
)
from werkzeug.utils import secure_filename
from flask_bcrypt import Bcrypt
import Levenshtein

# 配置
app = Flask(__name__)
app.secret_key = 'your-secret-key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///app.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# 初始化
db = SQLAlchemy(app)
login_manager = LoginManager(app)
bcrypt = Bcrypt(app)


# 数据模型
class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    videos = db.relationship('Video', back_populates='owner')

    def check_password(self, password):
        return bcrypt.check_password_hash(self.password_hash, password)

    def set_password(self, password):
        self.password_hash = bcrypt.generate_password_hash(password).decode('utf-8')


class Video(db.Model):
    __tablename__ = 'videos'
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(128), nullable=False)
    title = db.Column(db.String(128), nullable=False)
    description = db.Column(db.Text)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    timestamp = db.Column(db.DateTime, server_default=db.func.now())
    hidden = db.Column(db.Boolean, default=False)
    owner = db.relationship('User', back_populates='videos')


# 用户加载器
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# 计算LCS长度，根据Levenshtein库简化版返回相似度
def similarity_score(s1, s2):
    if not s1 or not s2:
        return 0
    lcs_length = Levenshtein.seqratio(s1.lower(), s2.lower())  # 0~1 之间
    return lcs_length


# 帮助：判断当前用户是否可以查看该视频
def can_view_video(vid):
    if not vid.hidden:
        return True
    if current_user.is_authenticated and (current_user.is_admin or vid.owner.id == current_user.id):
        return True
    return False


# 帮助：判断当前用户是否可以操作（隐藏/删除等）
def can_modify_video(vid):
    if not current_user.is_authenticated:
        return False
    return current_user.is_admin or vid.owner.id == current_user.id


# 首页及搜索页面
@app.route('/')
def home():
    query = request.args.get('q', '').strip()
    # 视频结果，来自数据库的Video对象及相似度得分列表
    video_results = []
    # 用户结果，来自数据库User对象及相似度得分列表
    user_results = []

    if query:
        # 遍历所有视频，计算相似度
        all_videos = Video.query.order_by(Video.timestamp.desc()).all()
        for v in all_videos:
            if not can_view_video(v):
                continue
            score_title = similarity_score(query, v.title)
            score_user = similarity_score(query, v.owner.username)
            score = max(score_title, score_user)
            if score > 0:
                video_results.append((v, score))

        # 按相似度降序排列
        video_results.sort(key=lambda x: x[1], reverse=True)

        # 遍历所有用户，按用户名相似度
        all_users = User.query.order_by(User.username).all()
        for u in all_users:
            score = similarity_score(query, u.username)
            if score > 0:
                user_results.append((u, score))
        # 按相似度降序
        user_results.sort(key=lambda x: x[1], reverse=True)
    else:
        # 无查询时显示最新视频，且用户按名字排序
        all_videos = Video.query.order_by(Video.timestamp.desc()).all()
        for v in all_videos:
            if can_view_video(v):
                video_results.append((v, 0))
        all_users = User.query.order_by(User.username).all()
        for u in all_users:
            user_results.append((u, 0))

    # 渲染模板
    html = '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <title>视频平台首页</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    video { max-width: 100%; height: auto; }
  </style>
</head>
<body>
<div class="container mt-4">

  <div class="d-flex justify-content-between align-items-center mb-3">
    <h1>视频分享平台</h1>

    <form class="d-flex" method="get" action="{{ url_for('home') }}">
      <input class="form-control me-2" type="search" name="q" placeholder="搜索视频或用户名" value="{{ query }}" autocomplete="off" />
      <button class="btn btn-outline-success" type="submit">搜索</button>
    </form>
  </div>

  {% with messages = get_flashed_messages() %}
  {% if messages %}
  <div>
    {% for m in messages %}
      <div class="alert alert-info">{{ m }}</div>
    {% endfor %}
  </div>
  {% endif %}
  {% endwith %}

  <div class="mb-3">
    {% if current_user.is_authenticated %}
      <span>您好，<b>{{ current_user.username }}</b>！</span>
      <a href="{{ url_for('logout') }}" class="btn btn-outline-danger btn-sm ms-2">登出</a>
      <a href="{{ url_for('upload') }}" class="btn btn-primary btn-sm ms-2">上传视频</a>
    {% else %}
      <a href="{{ url_for('login') }}" class="btn btn-primary btn-sm">登录</a>
      <a href="{{ url_for('register') }}" class="btn btn-secondary btn-sm ms-1">注册</a>
    {% endif %}
  </div>

  <hr/>

  <h3>视频列表</h3>
  <div class="row">
    {% for vid, score in video_results %}
    <div class="col-md-4 mb-4">
      <div class="card h-100 shadow-sm">
        <video class="card-img-top" src="{{ url_for('serve_upload', filename=vid.filename) }}" controls muted></video>
        <div class="card-body d-flex flex-column">
          <h5 class="card-title">{{ vid.title }}</h5>
          <p class="card-text mb-1">作者：
            <a href="{{ url_for('user_videos', username=vid.owner.username) }}">{{ vid.owner.username }}</a>
          </p>
          {% if score > 0 %}
          <span class="badge bg-info text-dark mb-1">相似度: {{ '%.2f' | format(score*100) }}%</span>
          {% endif %}
          {% if vid.hidden %}
          <span class="badge bg-warning text-dark mb-1">已隐藏</span>
          {% endif %}
          <div class="mt-auto">
            <a class="btn btn-primary btn-sm me-1" href="{{ url_for('play_video', video_id=vid.id) }}">播放</a>
            <a class="btn btn-secondary btn-sm me-1" href="{{ url_for('download_video', video_id=vid.id) }}">下载</a>
            {% if current_user.is_authenticated and (vid.owner.id == current_user.id or current_user.is_admin) %}
              {% if not vid.hidden %}
                <form method="post" action="{{ url_for('hide_video', video_id=vid.id) }}" style="display:inline;">
                  <button type="submit" class="btn btn-warning btn-sm me-1">隐藏</button>
                </form>
              {% else %}
                <form method="post" action="{{ url_for('unhide_video', video_id=vid.id) }}" style="display:inline;">
                  <button type="submit" class="btn btn-success btn-sm me-1">取消隐藏</button>
                </form>
              {% endif %}
              <form method="post" action="{{ url_for('delete_video', video_id=vid.id) }}" style="display:inline;" onsubmit="return confirm('确认删除此视频？');">
                <button type="submit" class="btn btn-danger btn-sm">删除</button>
              </form>
            {% endif %}
          </div>
        </div>
      </div>
    </div>
    {% endfor %}
    {% if video_results|length == 0 %}
    <p>无视频内容</p>
    {% endif %}
  </div>

  <hr/>

  <h3>用户列表</h3>
  <ul class="list-group mb-5">
    {% for user, score in user_results %}
      <li class="list-group-item d-flex justify-content-between align-items-center">
        <a href="{{ url_for('user_videos', username=user.username) }}">{{ user.username }}</a>
        <span>
        {% if score > 0 %}
          <span class="badge bg-info text-dark me-1">相似度 {{ '%.2f' | format(score*100) }}%</span>
        {% endif %}
        {% if user.is_admin %}
          <span class="badge bg-primary">管理员</span>
        {% endif %}
        </span>
      </li>
    {% endfor %}
    {% if user_results|length == 0 %}
    <p>无用户</p>
    {% endif %}
  </ul>

</div>
</body>
</html>
    '''
    return render_template_string(
        html,
        video_results=video_results,
        user_results=user_results,
        query=query
    )


# 上传文件允许的扩展名
ALLOWED_EXTENSIONS = {'mp4', 'mov', 'avi', 'mkv', 'webm'}


def allowed_file(filename):
    if '.' not in filename:
        return False
    ext = filename.rsplit('.', 1)[1].lower()
    return ext in ALLOWED_EXTENSIONS


# 上传视频页面及处理
@app.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    if request.method == 'POST':
        # 检查文件
        if 'file' not in request.files:
            flash('未上传视频文件')
            return redirect(url_for('upload'))

        file = request.files['file']
        if file.filename == '':
            flash('请选择文件')
            return redirect(url_for('upload'))
        if not allowed_file(file.filename):
            flash('只支持mp4, mov, avi, mkv, webm视频格式')
            return redirect(url_for('upload'))

        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        if not title:
            flash('请输入视频标题')
            return redirect(url_for('upload'))

        # 保存文件
        filename = secure_filename(file.filename)
        save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        # 处理文件名冲突
        basename, ext = os.path.splitext(filename)
        counter = 1
        while os.path.exists(save_path):
            filename = f"{basename}_{counter}{ext}"
            save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            counter += 1
        file.save(save_path)

        # 保存数据库
        new_video = Video(
            filename=filename,
            title=title,
            description=description,
            owner=current_user._get_current_object()
        )
        db.session.add(new_video)
        db.session.commit()

        flash('上传成功')
        return redirect(url_for('home'))

    # GET请求，渲染上传表单
    html_upload = '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <title>上传视频</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet" />
</head>
<body>
<div class="container mt-4">
  <h2>上传新视频</h2>
  <form method="post" enctype="multipart/form-data">
    <div class="mb-3">
      <label for="title" class="form-label">视频标题 <span class="text-danger">*</span></label>
      <input type="text" id="title" name="title" class="form-control" required maxlength="128" />
    </div>
    <div class="mb-3">
      <label for="description" class="form-label">视频描述</label>
      <textarea id="description" name="description" rows="3" class="form-control" maxlength="500"></textarea>
    </div>
    <div class="mb-3">
      <label for="file" class="form-label">选择文件 <span class="text-danger">*</span></label>
      <input type="file" id="file" name="file" accept="video/*" class="form-control" required />
    </div>
    <button type="submit" class="btn btn-primary">上传</button>
    <a href="{{ url_for('home') }}" class="btn btn-secondary ms-2">返回</a>
  </form>
  {% with messages = get_flashed_messages() %}
  {% if messages %}
  <div class="mt-3">
    {% for m in messages %}
      <div class="alert alert-warning">{{ m }}</div>
    {% endfor %}
  </div>
  {% endif %}
  {% endwith %}
</div>
</body>
</html>
    '''
    return render_template_string(html_upload)


# 登录页面及处理
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('home'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            flash('登录成功')
            return redirect(url_for('home'))
        else:
            flash('用户名或密码错误')
            return redirect(url_for('login'))
    # GET请求
    html_login = '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <title>登录</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet" />
</head>
<body>
<div class="container mt-4" style="max-width: 420px;">
  <h2>登录</h2>
  <form method="post" novalidate>
    <div class="mb-3">
      <label for="username" class="form-label">用户名</label>
      <input type="text" id="username" name="username" class="form-control" required autofocus />
    </div>
    <div class="mb-3">
      <label for="password" class="form-label">密码</label>
      <input type="password" id="password" name="password" class="form-control" required />
    </div>
    <button type="submit" class="btn btn-primary">登录</button>
    <a href="{{ url_for('register') }}" class="btn btn-link ms-2">没有账号？注册</a>
  </form>
  {% with messages = get_flashed_messages() %}
  {% if messages %}
  <div class="mt-3">
    {% for m in messages %}
      <div class="alert alert-warning">{{ m }}</div>
    {% endfor %}
  </div>
  {% endif %}
  {% endwith %}
</div>
</body>
</html>
    '''
    return render_template_string(html_login)


# 注销
@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('您已注销登录')
    return redirect(url_for('home'))


# 注册页面及处理
@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('home'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        if not username or not password:
            flash('请填写完整用户名和密码')
            return redirect(url_for('register'))

        if User.query.filter_by(username=username).first():
            flash('用户名已存在')
            return redirect(url_for('register'))

        user = User(username=username)
        user.set_password(password)

        # 第一个注册用户设为管理员
        if User.query.count() == 0:
            user.is_admin = True

        db.session.add(user)
        db.session.commit()
        flash('注册成功，请登录')
        return redirect(url_for('login'))

    html_register = '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <title>注册</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet" />
</head>
<body>
<div class="container mt-4" style="max-width: 420px;">
  <h2>注册</h2>
  <form method="post" novalidate>
    <div class="mb-3">
      <label for="username" class="form-label">用户名</label>
      <input type="text" id="username" name="username" class="form-control" required autofocus />
    </div>
    <div class="mb-3">
      <label for="password" class="form-label">密码</label>
      <input type="password" id="password" name="password" class="form-control" required />
    </div>
    <button type="submit" class="btn btn-primary">注册</button>
    <a href="{{ url_for('login') }}" class="btn btn-link ms-2">已有账号？登录</a>
  </form>
  {% with messages = get_flashed_messages() %}
  {% if messages %}
  <div class="mt-3">
    {% for m in messages %}
      <div class="alert alert-warning">{{ m }}</div>
    {% endfor %}
  </div>
  {% endif %}
  {% endwith %}
</div>
</body>
</html>
    '''
    return render_template_string(html_register)


# 用户视频页面，显示指定用户的视频列表
@app.route('/users/<username>')
def user_videos(username):
    user = User.query.filter_by(username=username).first_or_404()
    videos = []
    all_videos = user.videos
    for v in all_videos:
        if can_view_video(v):
            videos.append(v)
    videos.sort(key=lambda v: v.timestamp, reverse=True)

    html = '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <title>{{ user.username }} 的视频</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet" />
  <style>video { max-width: 100%; height: auto; }</style>
</head>
<body>
<div class="container mt-4">
  <h2>{{ user.username }} 的视频</h2>
  <a href="{{ url_for('home') }}" class="btn btn-secondary btn-sm mb-3">返回首页</a>
  {% if not videos %}
    <p>暂无视频。</p>
  {% else %}
    <div class="row">
      {% for vid in videos %}
      <div class="col-md-4 mb-4">
        <div class="card h-100 shadow-sm">
          <video class="card-img-top" src="{{ url_for('serve_upload', filename=vid.filename) }}" controls muted></video>
          <div class="card-body d-flex flex-column">
            <h5 class="card-title">{{ vid.title }}</h5>
            {% if vid.hidden %}
              <span class="badge bg-warning text-dark mb-1">已隐藏</span>
            {% endif %}
            <div class="mt-auto">
              <a class="btn btn-primary btn-sm me-1" href="{{ url_for('play_video', video_id=vid.id) }}">播放</a>
              <a class="btn btn-secondary btn-sm me-1" href="{{ url_for('download_video', video_id=vid.id) }}">下载</a>
              {% if current_user.is_authenticated and (vid.owner.id == current_user.id or current_user.is_admin) %}
                {% if not vid.hidden %}
                  <form method="post" action="{{ url_for('hide_video', video_id=vid.id) }}" style="display:inline;">
                    <button type="submit" class="btn btn-warning btn-sm me-1">隐藏</button>
                  </form>
                {% else %}
                  <form method="post" action="{{ url_for('unhide_video', video_id=vid.id) }}" style="display:inline;">
                    <button type="submit" class="btn btn-success btn-sm me-1">取消隐藏</button>
                  </form>
                {% endif %}
                <form method="post" action="{{ url_for('delete_video', video_id=vid.id) }}" style="display:inline;" onsubmit="return confirm('确认删除此视频？');">
                  <button type="submit" class="btn btn-danger btn-sm">删除</button>
                </form>
              {% endif %}
            </div>
          </div>
        </div>
      </div>
      {% endfor %}
    </div>
  {% endif %}
</div>
</body>
</html>
    '''
    return render_template_string(html, user=user, videos=videos)


# 播放视频页面
@app.route('/videos/<int:video_id>')
def play_video(video_id):
    vid = Video.query.get_or_404(video_id)
    if not can_view_video(vid):
        abort(403)

    html = '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <title>{{ vid.title }}</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet" />
</head>
<body>
<div class="container mt-4">
  <h2>{{ vid.title }}</h2>
  <p>上传者：<a href="{{ url_for('user_videos', username=vid.owner.username) }}">{{ vid.owner.username }}</a></p>
  {% if vid.hidden %}
    <p><span class="badge bg-warning text-dark">该视频已隐藏</span></p>
  {% endif %}
  <video controls autoplay style="width:100%; max-width:720px;">
    <source src="{{ url_for('serve_upload', filename=vid.filename) }}" type="video/mp4" />
    浏览器不支持video标签。
  </video>
  <p class="mt-3">{{ vid.description }}</p>
  <a href="{{ url_for('home') }}" class="btn btn-secondary mt-3">返回首页</a>
</div>
</body>
</html>
    '''
    return render_template_string(html, vid=vid)


# 下载视频
@app.route('/videos/<int:video_id>/download')
def download_video(video_id):
    vid = Video.query.get_or_404(video_id)
    if not can_view_video(vid):
        abort(403)
    return send_from_directory(app.config['UPLOAD_FOLDER'], vid.filename, as_attachment=True)


# 处理隐藏视频请求
@app.route('/videos/<int:video_id>/hide', methods=['POST'])
@login_required
def hide_video(video_id):
    vid = Video.query.get_or_404(video_id)
    if not can_modify_video(vid):
        flash('无权限隐藏该视频')
        return redirect(request.referrer or url_for('home'))
    vid.hidden = True
    db.session.commit()
    flash('视频已隐藏')
    return redirect(request.referrer or url_for('home'))


# 处理取消隐藏视频请求
@app.route('/videos/<int:video_id>/unhide', methods=['POST'])
@login_required
def unhide_video(video_id):
    vid = Video.query.get_or_404(video_id)
    if not can_modify_video(vid):
        flash('无权限取消隐藏该视频')
        return redirect(request.referrer or url_for('home'))
    vid.hidden = False
    db.session.commit()
    flash('视频已取消隐藏')
    return redirect(request.referrer or url_for('home'))


# 删除视频请求
@app.route('/videos/<int:video_id>/delete', methods=['POST'])
@login_required
def delete_video(video_id):
    vid = Video.query.get_or_404(video_id)
    if not can_modify_video(vid):
        flash('无权限删除该视频')
        return redirect(request.referrer or url_for('home'))

    # 删除视频文件
    path = os.path.join(app.config['UPLOAD_FOLDER'], vid.filename)
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass

    # 删除数据库记录
    db.session.delete(vid)
    db.session.commit()
    flash('视频已删除')
    return redirect(request.referrer or url_for('home'))


# 静态文件：服务上传文件
@app.route('/uploads/<filename>')
def serve_upload(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


# 初始化数据库，第一次运行时请取消下面代码注释。
# if __name__ == '__main__':
#     with app.app_context():
#         db.create_all()
#     app.run(debug=True)

if __name__ == '__main__':
    # 启动前检查db，不存在则创建
    with app.app_context():
        db.create_all()
    app.run(debug=True)

            
