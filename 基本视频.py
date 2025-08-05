import os
import uuid
from datetime import datetime, timedelta

from flask import (
    Flask, request, redirect, url_for, flash, send_from_directory,
    render_template_string, jsonify, abort
)
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_jwt_extended import (
    JWTManager, create_access_token, jwt_required,
    get_jwt_identity, set_access_cookies, unset_jwt_cookies
)
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash


# 初始化 Flask
app = Flask(__name__)
BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# 配置参数
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY", "your-secret-key"),
    SQLALCHEMY_DATABASE_URI='sqlite:///' + os.path.join(BASE_DIR, 'app.db'),
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    JWT_SECRET_KEY=os.environ.get("JWT_SECRET_KEY", "your-jwt-secret-key"),
    JWT_TOKEN_LOCATION=["cookies"],
    JWT_ACCESS_COOKIE_PATH="/",
    JWT_COOKIE_CSRF_PROTECT=False,  # 简化演示，生产建议开启
    JWT_ACCESS_TOKEN_EXPIRES=timedelta(hours=1),
    MAX_CONTENT_LENGTH=500 * 1024 * 1024,  # 允许最大500MB上传
    UPLOAD_FOLDER=os.path.join(BASE_DIR, 'uploads'),
    ALLOWED_EXTENSIONS={'mp4', 'mov', 'avi', 'mkv'}
)

# 初始化扩展
db = SQLAlchemy(app)
migrate = Migrate(app, db)
jwt = JWTManager(app)

# 用户模型
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, pw):
        self.password_hash = generate_password_hash(pw)

    def check_password(self, pw):
        return check_password_hash(self.password_hash, pw)


# 视频模型
class Video(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey(User.id), nullable=False)
    original_name = db.Column(db.String(255), nullable=False)
    stored_name = db.Column(db.String(255), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    mime_type = db.Column(db.String(50))
    size = db.Column(db.Integer)
    upload_time = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default='ready')
    deleted = db.Column(db.Boolean, default=False)

    owner = db.relationship('User', backref='videos')

# 工具函数：判断文件后缀是否允许上传
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

# 创建上传目录
def create_upload_folder():
    folder = app.config['UPLOAD_FOLDER']
    if not os.path.exists(folder):
        os.makedirs(folder)
    return folder

# 内联基础模板，所有页面都继承它
base_template = '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <title>{% block title %}视频平台{% endblock %}</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet"/>
</head>
<body>
<nav class="navbar navbar-expand-lg navbar-light bg-light mb-3">
  <div class="container">
    <a class="navbar-brand" href="{{ url_for('index') }}">视频平台</a>
    <ul class="navbar-nav ms-auto">
      {% if user %}
        <li class="nav-item"><a class="nav-link" href="{{ url_for('upload') }}">上传视频</a></li>
        <li class="nav-item"><a class="nav-link" href="{{ url_for('my_videos') }}">我的视频</a></li>
        <li class="nav-item"><span class="nav-link disabled">Hi, {{ user.username }}</span></li>
        <li class="nav-item"><a class="nav-link" href="{{ url_for('logout') }}">退出</a></li>
      {% else %}
        <li class="nav-item"><a class="nav-link" href="{{ url_for('login') }}">登录</a></li>
        <li class="nav-item"><a class="nav-link" href="{{ url_for('register') }}">注册</a></li>
      {% endif %}
    </ul>
  </div>
</nav>

<div class="container">
  {% with messages = get_flashed_messages(with_categories=true) %}
    {% if messages %}
      {% for category, message in messages %}
        <div class="alert alert-{{ category }} alert-dismissible fade show" role="alert">
          {{ message }}
          <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
        </div>
      {% endfor %}
    {% endif %}
  {% endwith %}

  {% block content %}{% endblock %}
</div>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
'''

### 路由实现 ###

# 首页 - 显示最新视频 & 搜索用户名
@app.route('/', methods=['GET', 'POST'])
def index():
    user = None
    try:
        identity = get_jwt_identity()
        if identity:
            user = User.query.get(identity['id'])
    except:
        pass

    search_username = request.args.get('search_username','').strip()

    if search_username:
        # 根据搜索的用户名查找用户
        matched_users = User.query.filter(User.username.ilike(f"%{search_username}%")).all()
        # 如果找到多个用户，显示用户列表，否则依据需要还可以直接跳转
        return render_template_string(
            '{% extends base %}{% block title %}用户搜索结果{% endblock %}{% block content %}'
            '<h2>搜索“{{ search_username }}”结果 - 用户列表</h2>'
            '{% if users %}'
            '<ul class="list-group">'
            '{% for u in users %}'
            '<li class="list-group-item"><a href="{{ url_for(\'user_videos\', username=u.username) }}">用户：{{ u.username }}</a></li>'
            '{% endfor %}'
            '</ul>'
            '{% else %}<p>未找到相关用户</p>{% endif %}'
            '<a class="btn btn-link mt-3" href="{{ url_for(\'index\') }}">返回首页</a>'
            '{% endblock %}', 
            base=base_template, user=user, users=matched_users, search_username=search_username)

    # 不搜索时，展示最新 10 条视频
    videos = Video.query.filter_by(deleted=False, status='ready').order_by(Video.upload_time.desc()).limit(10).all()
    return render_template_string(
        '{% extends base %}{% block title %}首页 - 视频平台{% endblock %}{% block content %}'
        '<form method="get" class="mb-4">'
        '<div class="input-group">'
        '<input type="text" name="search_username" class="form-control" placeholder="输入用户名搜索视频" value="{{ request.args.get("search_username","") }}">'
        '<button type="submit" class="btn btn-primary">搜索</button>'
        '</div>'
        '</form>'
        '<h1>最新视频</h1>'
        '{% if videos %}'
        '<div class="row">'
        '{% for v in videos %}'
        '<div class="col-md-4 mb-3">'
        '<div class="card">'
        '<div class="card-body">'
        '<h5 class="card-title">{{ v.title }}</h5>'
        '<p class="card-text">上传者：{{ v.owner.username }}</p>'
        '<p class="card-text">上传时间: {{ v.upload_time.strftime(\'%Y-%m-%d %H:%M\') }}</p>'
        '<a href="{{ url_for(\'video_detail\', video_id=v.id) }}" class="btn btn-primary">播放</a>'
        '</div></div></div>'
        '{% endfor %}</div>'
        '{% else %}<p>暂无视频</p>{% endif %}'
        '{% endblock %}',
        base=base_template, user=user, videos=videos)

# 注册
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username','').strip()
        password = request.form.get('password','').strip()
        if not username or not password:
            flash('用户名和密码不能为空', 'danger')
            return redirect(url_for('register'))
        if User.query.filter_by(username=username).first():
            flash('用户名已存在', 'danger')
            return redirect(url_for('register'))
        user = User(username=username)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        flash('注册成功，请登录', 'success')
        return redirect(url_for('login'))
    return render_template_string(
        '{% extends base %}{% block title %}注册 - 视频平台{% endblock %}{% block content %}'
        '<h2>注册</h2>'
        '<form method="post">'
        '<div class="mb-3">'
        '<label class="form-label">用户名</label>'
        '<input class="form-control" name="username" required/>'
        '</div>'
        '<div class="mb-3">'
        '<label class="form-label">密码</label>'
        '<input type="password" class="form-control" name="password" required/>'
        '</div>'
        '<button type="submit" class="btn btn-primary">注册</button>'
        '</form>'
        '<p class="mt-3">已有账号？<a href="{{ url_for(\'login\') }}">登录</a></p>'
        '{% endblock %}', base=base_template)

# 登录
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username','').strip()
        password = request.form.get('password','').strip()
        user = User.query.filter_by(username=username).first()
        if not user or not user.check_password(password):
            flash('用户名或密码错误', 'danger')
            return redirect(url_for('login'))
        access_token = create_access_token(identity={'id': user.id})
        resp = redirect(url_for('index'))  # 登录成功后重定向首页
        set_access_cookies(resp, access_token)  # 将JWT写入cookies
        flash('登录成功', 'success')
        return resp
    return render_template_string(
        '{% extends base %}{% block title %}登录 - 视频平台{% endblock %}{% block content %}'
        '<h2>登录</h2>'
        '<form method="post">'
        '<div class="mb-3">'
        '<label class="form-label">用户名</label>'
        '<input class="form-control" name="username" required/>'
        '</div>'
        '<div class="mb-3">'
        '<label class="form-label">密码</label>'
        '<input type="password" class="form-control" name="password" required/>'
        '</div>'
        '<button type="submit" class="btn btn-primary">登录</button>'
        '</form>'
        '<p class="mt-3">还没有账号？<a href="{{ url_for(\'register\') }}">注册</a></p>'
        '{% endblock %}', base=base_template)

# 退出登录
@app.route('/logout')
def logout():
    resp = redirect(url_for('index'))  # 登出后跳转首页
    unset_jwt_cookies(resp)  # 清理登录cookie
    flash('已退出登录', 'success')
    return resp

# 上传视频
@app.route('/upload', methods=['GET', 'POST'])
@jwt_required()  # 需要登录
def upload():
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('未选择上传文件', 'danger')
            return redirect(url_for('upload'))
        file = request.files['file']
        if file.filename == '':
            flash('未选择上传文件', 'danger')
            return redirect(url_for('upload'))
        if not allowed_file(file.filename):
            flash('仅允许上传 mp4/mov/avi/mkv 格式的视频文件', 'danger')
            return redirect(url_for('upload'))
        title = request.form.get('title','').strip()
        description = request.form.get('description','').strip()
        if title == '':
            flash('标题不能为空', 'danger')
            return redirect(url_for('upload'))

        identity = get_jwt_identity()
        user = User.query.get(identity['id'])

        filename = secure_filename(file.filename)
        stored_name = uuid.uuid4().hex + os.path.splitext(filename)[1]
        folder = create_upload_folder()
        save_path = os.path.join(folder, stored_name)
        file.save(save_path)

        video = Video(
            owner_id=user.id,
            original_name=filename,
            stored_name=stored_name,
            title=title,
            description=description,
            mime_type=file.mimetype or 'video/mp4',
            size=os.path.getsize(save_path),
            status='ready',
            deleted=False
        )
        db.session.add(video)
        db.session.commit()
        flash('上传成功', 'success')
        return redirect(url_for('my_videos'))  # 上传成功跳去“我的视频”页面

    return render_template_string(
        '{% extends base %}{% block title %}上传视频 - 视频平台{% endblock %}{% block content %}'
        '<h2>上传视频</h2>'
        '<form method="post" enctype="multipart/form-data">'
        '<div class="mb-3">'
        '<label class="form-label">视频文件</label>'
        '<input type="file" name="file" class="form-control" required accept="video/*"/>'
        '</div>'
        '<div class="mb-3">'
        '<label class="form-label">标题</label>'
        '<input type="text" name="title" class="form-control" required/>'
        '</div>'
        '<div class="mb-3">'
        '<label class="form-label">描述</label>'
        '<textarea name="description" class="form-control"></textarea>'
        '</div>'
        '<button type="submit" class="btn btn-primary">上传</button>'
        '</form>'
        '{% endblock %}',
        base=base_template)

# 查看当前登录用户自己的视频列表，带删除按钮
@app.route('/my_videos')
@jwt_required()
def my_videos():
    identity = get_jwt_identity()
    user = User.query.get(identity['id'])
    videos = Video.query.filter_by(owner_id=user.id, deleted=False).order_by(Video.upload_time.desc()).all()

    return render_template_string(
        '{% extends base %}{% block title %}我的视频 - 视频平台{% endblock %}{% block content %}'
        '<h2>我的视频</h2>'
        '{% if videos %}'
        '<table class="table table-bordered">'
        '<thead><tr><th>标题</th><th>上传时间</th><th>操作</th></tr></thead>'
        '<tbody>'
        '{% for v in videos %}'
        '<tr>'
        '<td><a href="{{ url_for(\'video_detail\', video_id=v.id) }}">{{ v.title }}</a></td>'
        '<td>{{ v.upload_time.strftime(\'%Y-%m-%d %H:%M\') }}</td>'
        '<td>'
        '<form method="post" action="{{ url_for(\'delete_video\', video_id=v.id) }}" onsubmit="return confirm(\'确认删除该视频？\');">'
        '<button type="submit" class="btn btn-danger btn-sm">删除</button>'
        '</form>'
        '</td>'
        '</tr>'
        '{% endfor %}'
        '</tbody>'
        '</table>'
        '{% else %}<p>你还没有上传任何视频。</p>{% endif %}'
        '{% endblock %}', base=base_template, videos=videos, user=user)

# 删除视频接口，只允许删除自己上传的视频，采用POST方法防CSRF（这里未加CSRF防护，演示用）
@app.route('/delete_video/<int:video_id>', methods=['POST'])
@jwt_required()
def delete_video(video_id):
    identity = get_jwt_identity()
    user = User.query.get(identity['id'])
    video = Video.query.get_or_404(video_id)

    if video.owner_id != user.id:
        flash('无权限删除该视频', 'danger')
        return redirect(url_for('my_videos'))

    video.deleted = True  # 逻辑删除
    db.session.commit()
    flash('视频已删除', 'success')
    return redirect(url_for('my_videos'))

# 展示某个用户名下的视频列表，允许无登录访问
@app.route('/user/<username>')
def user_videos(username):
    user = None
    try:
        identity = get_jwt_identity()
        if identity:
            user = User.query.get(identity['id'])
    except:
        pass

    person = User.query.filter_by(username=username).first_or_404()

    videos = Video.query.filter_by(owner_id=person.id, deleted=False, status='ready').order_by(Video.upload_time.desc()).all()

    return render_template_string(
        '{% extends base %}{% block title %}{{ person.username }} 的视频{% endblock %}{% block content %}'
        '<h2>用户：{{ person.username }} 的视频</h2>'
        '{% if videos %}'
        '<div class="row">'
        '{% for v in videos %}'
        '<div class="col-md-4 mb-3">'
        '<div class="card">'
        '<div class="card-body">'
        '<h5 class="card-title">{{ v.title }}</h5>'
        '<p class="card-text">上传时间: {{ v.upload_time.strftime(\'%Y-%m-%d %H:%M\') }}</p>'
        '<a href="{{ url_for(\'video_detail\', video_id=v.id) }}" class="btn btn-primary">播放</a>'
        '</div></div></div>'
        '{% endfor %}'
        '</div>'
        '{% else %}<p>该用户暂无视频。</p>{% endif %}'
        '{% endblock %}', base=base_template, user=user, person=person, videos=videos)

# 视频播放页 - 允许任何人访问（前提视频状态正常且未删除）
@app.route('/videos/<int:video_id>')
def video_detail(video_id):
    user = None
    try:
        identity = get_jwt_identity()
        if identity:
            user = User.query.get(identity['id'])
    except:
        pass

    video = Video.query.get_or_404(video_id)
    if video.deleted or video.status != 'ready':
        flash('视频不可用', 'danger')
        return redirect(url_for('index'))

    return render_template_string(
        '{% extends base %}{% block title %}播放 - {{ video.title }}{% endblock %}{% block content %}'
        '<h2>{{ video.title }}</h2>'
        '<p>上传者：<a href="{{ url_for(\'user_videos\', username=video.owner.username) }}">{{ video.owner.username }}</a></p>'
        '{% if video.description %}<p>{{ video.description }}</p>{% endif %}'
        '<video width="640" controls>'
        '  <source src="{{ url_for(\'video_stream\', video_id=video.id) }}" type="{{ video.mime_type }}">'
        '您的浏览器不支持视频播放。'
        '</video>'
        '{% endblock %}',
        base=base_template, video=video, user=user)

# 视频流地址 - 返回视频文件，支持浏览器播放
@app.route('/api/videos/<int:video_id>/stream')
def video_stream(video_id):
    video = Video.query.get_or_404(video_id)
    if video.deleted or video.status != 'ready':
        return jsonify({'msg': '视频不可用'}), 404

    folder = app.config['UPLOAD_FOLDER']
    # 以附件名形式不强制下载（as_attachment=False），可直接在线播放
    return send_from_directory(folder, video.stored_name, as_attachment=False, mimetype=video.mime_type)

# 创建上传目录 & 数据库表
if __name__ == '__main__':
    create_upload_folder()
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=5000, debug=True)




import os
import sqlite3
import bcrypt
from flask import (
    Flask, request, redirect, url_for,
    render_template_string, session, flash,
    send_from_directory, g
)
from werkzeug.utils import secure_filename
from functools import wraps
app = Flask(__name__)
app.secret_key = 'replace_with_your_secret_key'
DATABASE = 'database.db'
UPLOAD_FOLDER = 'videos'
ALLOWED_EXTENSIONS = {'mp4', 'avi', 'mkv', 'mov'}
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
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


def query_db(query, args=(), one=False):
    cur = get_db().execute(query, args)
    rv = cur.fetchall()
    cur.close()
    return (rv[0] if rv else None) if one else rv
def execute_db(query, args=()):
    con = get_db()
    cur = con.execute(query, args)
    con.commit()
    return cur.lastrowid
def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('请先登录')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function
def lcs_length(str1, str2):
    # 计算最长公共子序列长度
    m, n = len(str1), len(str2)
    dp = [[0]*(n+1) for _ in range(m+1)]
    for i in range(m):
        for j in range(n):
            if str1[i].lower() == str2[j].lower():
                dp[i+1][j+1] = dp[i][j] + 1
            else:
                dp[i+1][j+1] = max(dp[i][j+1], dp[i+1][j])
    return dp[m][n]


def similarity_score(str1, str2):
    # 用最长公共子序列长度 / max(len1,len2) 作为相似度
    lcs = lcs_length(str1, str2)
    max_len = max(len(str1), len(str2))
    if max_len == 0:
        return 0.0
    return lcs / max_len


# ----- HTML 模板 用字符串 （含Bootstrap）----

base_template = '''
<!DOCTYPE html>
<html lang="zh">
<head>
    <meta charset="utf-8">
    <title>视频平台</title>
    <meta name="viewport" content="width=device-width, initial-scale=1, shrink-to-fit=no">
    <!-- Bootstrap 5 CDN -->
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body>
<nav class="navbar navbar-expand-lg navbar-dark bg-primary">
  <div class="container-fluid">
    <a class="navbar-brand" href="{{ url_for('index') }}">视频平台</a>
    <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#navbarsExample"
            aria-controls="navbarsExample" aria-expanded="false" aria-label="Toggle navigation">
      <span class="navbar-toggler-icon"></span>
    </button>
    <div class="collapse navbar-collapse" id="navbarsExample">
      <ul class="navbar-nav me-auto mb-2 mb-lg-0">
        {% if session.username %}
            <li class="nav-item">
                <a class="nav-link" href="{{ url_for('upload') }}">上传视频</a>
            </li>
            <li class="nav-item">
                <a class="nav-link" href="{{ url_for('my_videos') }}">我的视频</a>
            </li>
        {% endif %}
        <li class="nav-item">
            <a class="nav-link" href="{{ url_for('search') }}">搜索用户</a>
        </li>
      </ul>
      <ul class="navbar-nav ms-auto mb-2 mb-lg-0">
        {% if session.username %}
            <li class="nav-item">
                <span class="navbar-text me-2">欢迎，{{ session.username }}</span>
            </li>
            <li class="nav-item">
                <a class="nav-link" href="{{ url_for('logout') }}">登出</a>
            </li>
        {% else %}
            <li class="nav-item"><a class="nav-link" href="{{ url_for('login') }}">登录</a></li>
            <li class="nav-item"><a class="nav-link" href="{{ url_for('register') }}">注册</a></li>
        {% endif %}
      </ul>
    </div>
  </div>
</nav>

<div class="container mt-4">
    {% with messages = get_flashed_messages() %}
    {% if messages %}
        <div class="alert alert-warning" role="alert">
            <ul class="mb-0">
            {% for message in messages %}
                <li>{{ message }}</li>
            {% endfor %}
            </ul>
        </div>
    {% endif %}
    {% endwith %}
    {% block content %}{% endblock %}
</div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
'''
index_template = '''
{% extends "base.html" %}
{% block content %}
<div class="text-center">
    <h1>欢迎来到视频平台</h1>
    <p class="lead">上传、管理你的精彩视频，探索其他用户的视频世界！</p>
    {% if not session.username %}
    <a href="{{ url_for('login') }}" class="btn btn-primary me-2">登录</a>
    <a href="{{ url_for('register') }}" class="btn btn-secondary">注册</a>
    {% endif %}
</div>
{% endblock %}
'''
login_template = '''
{% extends "base.html" %}
{% block content %}
<h2>登录</h2>
<form method="post" class="mx-auto" style="max-width: 400px;">
  <div class="mb-3">
    <label for="username" class="form-label">用户名</label>
    <input type="text" class="form-control" id="username" name="username" required autofocus>
  </div>
  <div class="mb-3">
    <label for="password" class="form-label">密码</label>
    <input type="password" class="form-control" id="password" name="password" required>
  </div>
  <button type="submit" class="btn btn-primary">登录</button>
</form>
{% endblock %}
'''
register_template = '''
{% extends "base.html" %}
{% block content %}
<h2>注册</h2>
<form method="post" class="mx-auto" style="max-width: 400px;">
  <div class="mb-3">
    <label for="username" class="form-label">用户名</label>
    <input type="text" class="form-control" id="username" name="username" required autofocus>
  </div>
  <div class="mb-3">
    <label for="password" class="form-label">密码</label>
    <input type="password" class="form-control" id="password" name="password" required>
  </div>
  <button type="submit" class="btn btn-success">注册</button>
</form>
{% endblock %}
'''
upload_template = '''
{% extends "base.html" %}
{% block content %}
<h2>上传视频</h2>
<form method="post" enctype="multipart/form-data" class="mx-auto" style="max-width: 500px;">
  <div class="mb-3">
    <label for="file" class="form-label">选择视频文件</label>
    <input class="form-control" type="file" id="file" name="file" accept=".mp4,.avi,.mkv,.mov" required>
    <div class="form-text">支持格式: mp4, avi, mkv, mov</div>
  </div>
  <button type="submit" class="btn btn-primary">上传</button>
</form>
{% endblock %}
'''
user_videos_template = '''
{% extends "base.html" %}
{% block content %}
<h2>{{ owner }} 的视频列表</h2>
{% if videos %}
<div class="row gy-3">
{% for video in videos %}
  <div class="col-md-6 col-lg-4">
    <div class="card">
      <video class="card-img-top" controls preload="metadata" style="max-height:210px;">
        <source src="{{ url_for('serve_video', filename=video.filename) }}" type="video/mp4">
        您的浏览器不支持播放此视频。
      </video>
      <div class="card-body">
        <h5 class="card-title text-truncate" title="{{ video.filename }}">{{ video.filename }}</h5>
        {% if is_owner %}
        <form action="{{ url_for('delete_video', video_id=video.id) }}" method="post" 
              onsubmit="return confirm('确定删除此视频？');">
          <button type="submit" class="btn btn-danger btn-sm">删除</button>
        </form>
        {% endif %}
      </div>
    </div>
  </div>
{% endfor %}
</div>
{% else %}
<p>暂无视频</p>
{% endif %}
{% endblock %}
'''
search_template = '''
{% extends "base.html" %}
{% block content %}
<h2>搜索用户</h2>
<form method="post" class="row row-cols-lg-auto g-3 align-items-center mb-3">
  <div class="col-12">
    <input type="text" class="form-control" name="keyword" placeholder="输入用户名关键字" value="{{ keyword|default('') }}" required>
  </div>
  <div class="col-12">
    <button type="submit" class="btn btn-primary">搜索</button>
  </div>
</form>

{% if users %}
<h5>搜索结果（按相似度降序排列）:</h5>
<ul class="list-group">
  {% for user, sim in users %}
  <li class="list-group-item d-flex justify-content-between align-items-center">
    <a href="{{ url_for('user_videos', username=user.username) }}">{{ user.username }}</a>
    <span class="badge bg-primary rounded-pill">{{ '%.1f%%' % (sim * 100) }}</span>
  </li>
  {% endfor %}
</ul>
{% endif %}
{% endblock %}
'''
# --- 路由实现 ---
@app.route('/')
def index():
    return render_template_string(index_template)
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        if not username or not password:
            flash("用户名和密码不能为空")
            return redirect(url_for('register'))
        if query_db("SELECT * FROM users WHERE username = ?", (username,), one=True):
            flash("用户名已存在")
            return redirect(url_for('register'))
        # 哈希密码
        password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
        execute_db("INSERT INTO users (username, password) VALUES (?, ?)", (username, password_hash))
        flash("注册成功，请登录")
        return redirect(url_for('login'))
    return render_template_string(register_template)
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        user = query_db("SELECT * FROM users WHERE username = ?", (username,), one=True)
        if user:
            pwd_hash = user['password']
            # 注意 SQLite 存的是 bytes，需要encode/decode处理，先确认数据类型：
            if isinstance(pwd_hash, str):
                pwd_hash = pwd_hash.encode('utf-8')
            if bcrypt.checkpw(password.encode('utf-8'), pwd_hash):
                session['user_id'] = user['id']
                session['username'] = user['username']
                flash('登录成功')
                return redirect(url_for('index'))
        flash('用户名或密码错误')
        return redirect(url_for('login'))
    return render_template_string(login_template)
@app.route('/logout')
def logout():
    session.clear()
    flash('已退出')
    return redirect(url_for('index'))
@app.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('没有上传文件')
            return redirect(request.url)
        file = request.files['file']
        if file.filename == '':
            flash('未选择文件')
            return redirect(request.url)
        if file and allowed_file(file.filename):
            filename_raw = secure_filename(file.filename)
            filename = f"{session['user_id']}_{filename_raw}"
            filepath = os.path.join(UPLOAD_FOLDER, filename)
            file.save(filepath)
            execute_db("INSERT INTO videos (user_id, filename) VALUES (?, ?)", (session['user_id'], filename))
            flash('上传成功')
            return redirect(url_for('my_videos'))
        flash('只允许上传视频文件(mp4, avi, mkv, mov)')
        return redirect(request.url)
    return render_template_string(upload_template)
@app.route('/my_videos')
@login_required
def my_videos():
    user_id = session['user_id']
    videos = query_db("SELECT * FROM videos WHERE user_id = ?", (user_id,))
    return render_template_string(user_videos_template, videos=videos, owner=session['username'], is_owner=True)
@app.route('/search', methods=['GET', 'POST'])
def search():
    users = []
    keyword = ''
    if request.method == 'POST':
        keyword = request.form['keyword'].strip()
        if keyword:
            user_list = query_db("SELECT * FROM users")
            scored_users = []
            for u in user_list:
                sim = similarity_score(keyword, u['username'])
                if sim > 0:
                    scored_users.append((u, sim))
            # 按相似度降序排序
            scored_users.sort(key=lambda x: x[1], reverse=True)
            users = scored_users
    return render_template_string(search_template, users=users, keyword=keyword)
@app.route('/user/<username>')
def user_videos(username):
    user = query_db("SELECT * FROM users WHERE username = ?", (username,), one=True)
    if not user:
        flash("用户不存在")
        return redirect(url_for('search'))
    videos = query_db("SELECT * FROM videos WHERE user_id = ?", (user['id'],))
    is_owner = ('user_id' in session and session['user_id'] == user['id'])
    return render_template_string(user_videos_template, videos=videos, owner=username, is_owner=is_owner)
@app.route('/videos/<filename>')
def serve_video(filename):
    return send_from_directory(UPLOAD_FOLDER, filename, as_attachment=False)
@app.route('/delete_video/<int:video_id>', methods=['POST'])
@login_required
def delete_video(video_id):
    user_id = session['user_id']
    video = query_db("SELECT * FROM videos WHERE id = ?", (video_id,), one=True)
    if not video:
        flash('视频不存在')
        return redirect(url_for('my_videos'))
    if video['user_id'] != user_id:
        flash('无权限删除此视频')
        return redirect(url_for('my_videos'))
    filepath = os.path.join(UPLOAD_FOLDER, video['filename'])
    if os.path.exists(filepath):
        os.remove(filepath)
    execute_db("DELETE FROM videos WHERE id = ?", (video_id,))
    flash('删除成功')
    return redirect(url_for('my_videos'))
# 初始化数据库
def init_db():
    with app.app_context():
        db = get_db()
        c = db.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password BLOB NOT NULL
            );
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS videos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                filename TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
        ''')
        db.commit()
# 注册 base 模板给 render_template_string 支持继承
@app.context_processor
def inject_base():
    return dict(
        base=base_template
    )
if __name__ == '__main__':
    init_db()
    app.run(debug=True)



