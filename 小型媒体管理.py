#!/usr/bin/env python3
# app.py — 单文件 Flask 应用：注册/登录（bcrypt）、上传图片/视频、LCS 搜索、查看用户媒体、删除媒体。
import os, time, sqlite3
from functools import wraps
from hashlib import sha256
from flask import Flask, g, request, redirect, url_for, session, flash, abort, send_from_directory, render_template_string
from werkzeug.utils import secure_filename
import bcrypt

# ---------- 配置 ----------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_IMAGE_DIR = os.path.join(BASE_DIR, 'static', 'uploads', 'images')
UPLOAD_VIDEO_DIR = os.path.join(BASE_DIR, 'static', 'uploads', 'videos')
os.makedirs(UPLOAD_IMAGE_DIR, exist_ok=True)
os.makedirs(UPLOAD_VIDEO_DIR, exist_ok=True)

ALLOWED_IMAGE_EXT = {'png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp'}
ALLOWED_VIDEO_EXT = {'mp4', 'webm', 'ogg', 'mov', 'avi', 'mkv'}

DATABASE = os.path.join(BASE_DIR, 'database.db')
SECRET_KEY = os.environ.get('APP_SECRET_KEY', 'change_this_secret_for_prod')

app = Flask(__name__)
app.config.update(DATABASE=DATABASE, SECRET_KEY=SECRET_KEY, UPLOAD_IMAGE_DIR=UPLOAD_IMAGE_DIR, UPLOAD_VIDEO_DIR=UPLOAD_VIDEO_DIR, MAX_CONTENT_LENGTH=200*1024*1024)
app.secret_key = app.config['SECRET_KEY']

# ---------- DB ----------
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = sqlite3.connect(app.config['DATABASE'])
        db.row_factory = sqlite3.Row
        g._database = db
    return db

def init_db():
    db = get_db()
    cur = db.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash BLOB NOT NULL
        );
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS media (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            filename TEXT NOT NULL,
            media_type TEXT NOT NULL,
            uploaded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
    ''')
    db.commit()

@app.teardown_appcontext
def close_db(exc):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

# ---------- Utils ----------
def hash_password(password: str) -> bytes:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())

def check_password(password: str, pw_hash: bytes) -> bool:
    try:
        return bcrypt.checkpw(password.encode('utf-8'), pw_hash)
    except:
        return False

def allowed_file(filename: str, kind: str) -> bool:
    if '.' not in filename: return False
    ext = filename.rsplit('.',1)[1].lower()
    if kind == 'image': return ext in ALLOWED_IMAGE_EXT
    if kind == 'video': return ext in ALLOWED_VIDEO_EXT
    return False

def lcs_length(a: str, b: str) -> int:
    a = a or ''
    b = b or ''
    la, lb = len(a), len(b)
    if la == 0 or lb == 0: return 0
    dp = [0]*(lb+1)
    for i in range(1, la+1):
        prev = 0
        ai = a[i-1]
        for j in range(1, lb+1):
            tmp = dp[j]
            if ai == b[j-1]:
                dp[j] = prev + 1
            else:
                dp[j] = max(dp[j], dp[j-1])
            prev = tmp
    return dp[lb]

def similarity_score(q: str, target: str) -> int:
    return lcs_length(q.lower(), target.lower())

def login_required(f):
    @wraps(f)
    def w(*args, **kwargs):
        if 'user_id' not in session:
            flash('请先登录', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return w

# ---------- Templates (render_template_string) ----------
base_tpl = """
<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Mini Social</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
<style>body{padding-top:70px;background:#f8f9fa}.media-card img,.media-card video{width:100%;height:auto;border-radius:6px}.user-card{cursor:pointer;transition:transform .12s}.user-card:hover{transform:translateY(-4px)}.uploader-box{max-width:760px;margin:0 auto}.small-muted{font-size:.85rem;color:#6c757d}</style>
</head>
<body>
<nav class="navbar navbar-expand-lg navbar-dark bg-dark fixed-top"><div class="container">
<a class="navbar-brand" href="{{ url_for('index') }}">Mini Social</a>
<button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#navbarsMain"><span class="navbar-toggler-icon"></span></button>
<div class="collapse navbar-collapse" id="navbarsMain">
<ul class="navbar-nav me-auto mb-2 mb-lg-0"><li class="nav-item"><a class="nav-link" href="{{ url_for('index') }}">首页</a></li>{% if session.get('user_id') %}<li class="nav-item"><a class="nav-link" href="{{ url_for('upload') }}">上传</a></li>{% endif %}</ul>
<form class="d-flex" action="{{ url_for('search') }}" method="get"><input class="form-control me-2" type="search" placeholder="搜索用户名" name="q" value="{{ request.args.get('q','') }}"><button class="btn btn-outline-light" type="submit">搜索</button></form>
<ul class="navbar-nav ms-3">{% if session.get('user_id') %}<li class="nav-item dropdown"><a class="nav-link dropdown-toggle" href="#" id="userMenu" data-bs-toggle="dropdown">{{ session.get('username') }}</a><ul class="dropdown-menu dropdown-menu-end" aria-labelledby="userMenu"><li><a class="dropdown-item" href="{{ url_for('user_detail', user_id=session.get('user_id')) }}">我的主页</a></li><li><a class="dropdown-item" href="{{ url_for('upload') }}">上传媒体</a></li><li><hr class="dropdown-divider"></li><li><a class="dropdown-item text-danger" href="{{ url_for('logout') }}">登出</a></li></ul></li>{% else %}<li class="nav-item"><a class="nav-link" href="{{ url_for('login') }}">登录</a></li><li class="nav-item"><a class="nav-link" href="{{ url_for('register') }}">注册</a></li>{% endif %}</ul>
</div></div></nav>
<main class="container">
<div class="row"><div class="col-12">
{% with messages = get_flashed_messages(with_categories=true) %}
  {% if messages %}
    <div class="mt-2">
    {% for cat,msg in messages %}
      <div class="alert alert-{{ 'warning' if cat=='warning' else ('danger' if cat=='danger' else ('success' if cat=='success' else 'info')) }} alert-dismissible fade show" role="alert">{{ msg }}<button type="button" class="btn-close" data-bs-dismiss="alert"></button></div>
    {% endfor %}
    </div>
  {% endif %}
{% endwith %}
</div></div>
<div class="row mt-3"><div class="col-12">{% block body %}{% endblock %}</div></div>
</main>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
</body></html>
"""

index_tpl = """
{% extends base %}{% block body %}
<div class="card shadow-sm mb-3"><div class="card-body"><h4 class="card-title">欢迎来到 Mini Social</h4><p class="card-text">使用右上角搜索框查找用户，点击用户查看其图片/视频，登录后可上传并删除自己的媒体。</p><div class="d-flex gap-2">{% if not session.get('user_id') %}<a class="btn btn-primary" href="{{ url_for('register') }}">注册</a><a class="btn btn-outline-primary" href="{{ url_for('login') }}">登录</a>{% else %}<a class="btn btn-success" href="{{ url_for('upload') }}">上传媒体</a><a class="btn btn-secondary" href="{{ url_for('user_detail', user_id=session.get('user_id')) }}">我的主页</a>{% endif %}</div></div></div>
<div class="row"><div class="col-lg-8"><div class="card shadow-sm"><div class="card-body"><h5 class="card-title">说明</h5><p class="small-muted">搜索使用最长公共子序列（LCS）排序。媒体按上传时间降序显示。上传者可删除自己的媒体。</p></div></div></div></div>
{% endblock %}
"""

register_tpl = """
{% extends base %}{% block body %}
<div class="uploader-box mt-2"><div class="card shadow-sm"><div class="card-body"><h5 class="card-title">注册</h5><form method="post" novalidate><div class="mb-3"><label class="form-label">用户名</label><input class="form-control" name="username" required></div><div class="mb-3"><label class="form-label">密码</label><input class="form-control" type="password" name="password" required></div><div class="d-flex gap-2"><button class="btn btn-primary" type="submit">注册</button><a class="btn btn-link" href="{{ url_for('login') }}">已有账号？登录</a></div></form></div></div></div>
{% endblock %}
"""

login_tpl = """
{% extends base %}{% block body %}
<div class="uploader-box mt-2"><div class="card shadow-sm"><div class="card-body"><h5 class="card-title">登录</h5><form method="post" novalidate><div class="mb-3"><label class="form-label">用户名</label><input class="form-control" name="username" required></div><div class="mb-3"><label class="form-label">密码</label><input class="form-control" type="password" name="password" required></div><div class="d-flex gap-2"><button class="btn btn-primary" type="submit">登录</button><a class="btn btn-link" href="{{ url_for('register') }}">没有账号？注册</a></div></form></div></div></div>
{% endblock %}
"""

upload_tpl = """
{% extends base %}{% block body %}
<div class="uploader-box mt-2"><div class="card shadow-sm"><div class="card-body"><h5 class="card-title">上传媒体</h5><form method="post" enctype="multipart/form-data" class="row g-3"><div class="col-md-4"><label class="form-label">类型</label><select class="form-select" name="kind"><option value="image">图片</option><option value="video">视频</option></select></div><div class="col-md-8"><label class="form-label">选择文件</label><input class="form-control" type="file" name="file" required></div><div class="col-12"><button class="btn btn-success" type="submit">上传</button><a class="btn btn-secondary" href="{{ url_for('user_detail', user_id=session.get('user_id')) }}">返回我的主页</a></div></form><p class="small-muted mt-2">支持常见图片与视频格式，最大 200MB（后端配置）。</p></div></div></div>
{% endblock %}
"""

user_list_tpl = """
{% extends base %}{% block body %}
<div class="card shadow-sm"><div class="card-body"><h5 class="card-title">搜索结果： "{{ query }}"</h5>{% if results %}<div class="row row-cols-1 row-cols-md-2 row-cols-lg-3 g-3 mt-1">{% for r in results %}<div class="col"><a class="text-decoration-none text-dark" href="{{ url_for('user_detail', user_id=r.id) }}"><div class="card user-card h-100"><div class="card-body"><h6 class="card-title mb-1">{{ r.username }}</h6><p class="small-muted mb-0">相似度(LCS): <strong>{{ r.score }}</strong></p></div></div></a></div>{% endfor %}</div>{% else %}<p class="mt-2">未找到匹配用户。</p>{% endif %}</div></div>
{% endblock %}
"""

user_detail_tpl = """
{% extends base %}{% block body %}
<div class="d-flex justify-content-between align-items-center mb-3"><div><h4 class="m-0">{{ user.username }}</h4><div class="small-muted">用户ID: {{ user.id }}</div></div><div>{% if session.get('user_id') == user.id %}<a class="btn btn-sm btn-outline-primary" href="{{ url_for('upload') }}">上传新媒体</a>{% endif %}<a class="btn btn-sm btn-secondary" href="{{ url_for('index') }}">返回</a></div></div>
{% if media_list %}<div class="row g-3">{% for m in media_list %}<div class="col-12 col-md-6 col-lg-4"><div class="card media-card shadow-sm"><div class="card-body p-2">{% if m.media_type == 'image' %}<img src="{{ m.url }}" alt="image">{% else %}<video controls preload="metadata"><source src="{{ m.url }}"></video>{% endif %}</div><div class="card-footer small text-muted d-flex justify-content-between align-items-center"><div>{{ m.media_type|capitalize }}</div><div class="d-flex align-items-center gap-2"><div class="text-nowrap">{{ m.uploaded_at }}</div>{% if session.get('user_id') == user.id %}<form method="post" action="{{ url_for('delete_media') }}" onsubmit="return confirm('确认删除此媒体？此操作不可恢复。');" style="display:inline;"><input type="hidden" name="media_id" value="{{ m.id }}"><button type="submit" class="btn btn-sm btn-outline-danger">删除</button></form>{% endif %}</div></div></div></div>{% endfor %}</div>{% else %}<div class="card shadow-sm"><div class="card-body"><p class="mb-0">该用户暂无上传的媒体。</p></div></div>{% endif %}
{% endblock %}
"""

# ---------- Routes ----------
@app.route('/')
def index():
    return render_template_string(index_tpl, base=base_tpl)

@app.route('/register', methods=['GET','POST'])
def register():
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''
        if not username or not password:
            flash('用户名和密码不能为空', 'danger'); return redirect(url_for('register'))
        db = get_db()
        try:
            pw_hash = hash_password(password)
            db.execute('INSERT INTO users (username, password_hash) VALUES (?, ?)', (username, pw_hash))
            db.commit()
            flash('注册成功，请登录', 'success'); return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('用户名已存在', 'danger'); return redirect(url_for('register'))
    return render_template_string(register_tpl, base=base_tpl)

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''
        db = get_db()
        cur = db.execute('SELECT * FROM users WHERE username = ?', (username,))
        user = cur.fetchone()
        if user and check_password(password, user['password_hash']):
            session.clear()
            session['user_id'] = user['id']
            session['username'] = user['username']
            flash('登录成功', 'success'); return redirect(url_for('index'))
        flash('用户名或密码错误', 'danger'); return redirect(url_for('login'))
    return render_template_string(login_tpl, base=base_tpl)

@app.route('/logout')
def logout():
    session.clear(); flash('已登出', 'info'); return redirect(url_for('index'))

@app.route('/upload', methods=['GET','POST'])
@login_required
def upload():
    if request.method == 'POST':
        kind = request.form.get('kind')
        file = request.files.get('file')
        if not file or file.filename == '':
            flash('未选择文件', 'danger'); return redirect(url_for('upload'))
        if kind not in ('image','video'):
            flash('无效的媒体类型', 'danger'); return redirect(url_for('upload'))
        if not allowed_file(file.filename, kind):
            flash('不允许的文件类型', 'danger'); return redirect(url_for('upload'))
        safe = secure_filename(file.filename)
        prefix = f"{session['user_id']}_{int(time.time())}_"
        final_name = prefix + safe
        save_dir = app.config['UPLOAD_IMAGE_DIR'] if kind=='image' else app.config['UPLOAD_VIDEO_DIR']
        try:
            file.save(os.path.join(save_dir, final_name))
        except Exception as e:
            app.logger.exception("保存文件失败: %s", e); flash('保存文件失败', 'danger'); return redirect(url_for('upload'))
        db = get_db()
        db.execute('INSERT INTO media (user_id, filename, media_type) VALUES (?, ?, ?)', (session['user_id'], final_name, kind))
        db.commit()
        flash('上传成功', 'success'); return redirect(url_for('user_detail', user_id=session['user_id']))
    return render_template_string(upload_tpl, base=base_tpl)

@app.route('/uploads/<kind>/<filename>')
def uploaded_file(kind, filename):
    if kind == 'images':
        return send_from_directory(app.config['UPLOAD_IMAGE_DIR'], filename)
    if kind == 'videos':
        return send_from_directory(app.config['UPLOAD_VIDEO_DIR'], filename)
    abort(404)

@app.route('/search')
def search():
    q = (request.args.get('q') or '').strip()
    db = get_db()
    cur = db.execute('SELECT id, username FROM users')
    users = cur.fetchall()
    results = []
    if q == '':
        for u in users: results.append({'id':u['id'],'username':u['username'],'score':0})
        results.sort(key=lambda x: x['username'].lower())
    else:
        for u in users:
            score = similarity_score(q, u['username'])
            if score > 0: results.append({'id':u['id'],'username':u['username'],'score':score})
        results.sort(key=lambda x: x['score'], reverse=True)
    return render_template_string(user_list_tpl, base=base_tpl, query=q, results=results)

@app.route('/user/<int:user_id>')
def user_detail(user_id):
    db = get_db()
    cur = db.execute('SELECT id, username FROM users WHERE id = ?', (user_id,))
    user = cur.fetchone()
    if not user: abort(404)
    cur = db.execute('SELECT * FROM media WHERE user_id = ? ORDER BY uploaded_at DESC', (user_id,))
    media = cur.fetchall()
    media_list = []
    for m in media:
        if m['media_type'] == 'image':
            url = url_for('uploaded_file', kind='images', filename=m['filename'])
        else:
            url = url_for('uploaded_file', kind='videos', filename=m['filename'])
        media_list.append({'id': m['id'], 'url': url, 'media_type': m['media_type'], 'uploaded_at': m['uploaded_at']})
    return render_template_string(user_detail_tpl, base=base_tpl, user=user, media_list=media_list)

@app.route('/media/delete', methods=['POST'])
@login_required
def delete_media():
    media_id = request.form.get('media_id')
    if not media_id:
        flash('未指定媒体', 'danger'); return redirect(request.referrer or url_for('index'))
    db = get_db()
    cur = db.execute('SELECT * FROM media WHERE id = ?', (media_id,))
    m = cur.fetchone()
    if not m:
        flash('媒体不存在', 'danger'); return redirect(request.referrer or url_for('index'))
    if m['user_id'] != session.get('user_id'):
        flash('无权限删除此媒体', 'danger'); return redirect(request.referrer or url_for('index'))
    filename = m['filename']
    path = os.path.join(app.config['UPLOAD_IMAGE_DIR'] if m['media_type']=='image' else app.config['UPLOAD_VIDEO_DIR'], filename)
    try:
        if os.path.exists(path): os.remove(path)
    except Exception as e:
        app.logger.exception("删除文件失败: %s", e)
    db.execute('DELETE FROM media WHERE id = ?', (media_id,))
    db.commit()
    flash('媒体已删除', 'success'); return redirect(url_for('user_detail', user_id=session.get('user_id')))

# ---------- Run ----------
if __name__ == '__main__':
    with app.app_context():
        init_db()
    print("依赖：pip install flask bcrypt werkzeug")
    app.run(debug=True, host='0.0.0.0', port=5000)
