from flask import Flask, request, redirect, url_for, flash, session, send_from_directory, g, get_flashed_messages
import sqlite3
import os
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timezone
from jinja2 import Environment, DictLoader, select_autoescape

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
DATABASE_PATH = os.path.join(BASE_DIR, 'app.db')
SECRET_KEY = 'change-this-secret-key'  # <- replace in production
MAX_CONTENT_LENGTH = 15 * 1024 * 1024  # 15 MB

app = Flask(__name__)
app.config.update(
    UPLOAD_FOLDER=UPLOAD_FOLDER,
    DATABASE=DATABASE_PATH,
    SECRET_KEY=SECRET_KEY,
    MAX_CONTENT_LENGTH=MAX_CONTENT_LENGTH
)

# --- Templates (string-based, DictLoader) ---
layout_template = """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Simple Feed</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.2.3/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    :root { --gold-500: #d4a017; --gold-700: #b8860b; }
    body { background: linear-gradient(180deg,#fffaf0,#ffffff); font-family: -apple-system,Segoe UI,Roboto,Arial; color:#2b2b2b; padding-bottom:40px; }
    .navbar, .card { border-radius:12px; }
    .brand { color:var(--gold-700); font-weight:700; font-size:1.25rem; }
    .btn-gold { background-color:var(--gold-500); border-color:var(--gold-700); color:white; }
    .container-main { max-width:920px; margin-top:28px; }
    h3 { color:#5a3d06; font-size:1.6rem; margin-bottom:18px; }
    .post-img { max-width:100%; height:auto; margin-top:12px; border-radius:8px; box-shadow:0 2px 6px rgba(0,0,0,0.08); }
    .card { background: rgba(255,250,240,0.95); }
    .username-link { color:var(--gold-700); font-weight:600; text-decoration:none; }
    .form-control, textarea.form-control { border-radius:8px; }
    footer.footer-note { margin-top:36px; padding-top:12px; color:#666; font-size:0.9rem; }
    .time-small { font-size:0.9rem; color:#6b6b6b; }
  </style>
</head>
<body>
<nav class="navbar navbar-expand-lg navbar-light bg-white shadow-sm">
  <div class="container-fluid">
    <a class="navbar-brand brand ms-3" href="{{ url_for('index') }}">Feed</a>
    <form class="d-flex w-50" action="{{ url_for('search') }}" method="get">
      <input class="form-control me-2" name="q" placeholder="Search username" value="{{ q if q is defined else '' }}">
      <button class="btn btn-outline-secondary" type="submit">Search</button>
    </form>
    <div class="ms-auto me-3">
      {% if user %}
        <span class="me-2">Hi, <strong>{{ user['username'] }}</strong></span>
        <a class="btn btn-sm btn-gold me-1" href="{{ url_for('create_post') }}">New Post</a>
        <a class="btn btn-sm btn-outline-secondary" href="{{ url_for('logout') }}">Logout</a>
      {% else %}
        <a class="btn btn-sm btn-gold me-1" href="{{ url_for('login') }}">Login</a>
        <a class="btn btn-sm btn-outline-secondary" href="{{ url_for('register') }}">Register</a>
      {% endif %}
    </div>
  </div>
</nav>
<div class="container container-main">
  {% with messages = get_flashed_messages() %}
    {% if messages %}
      <div class="alert alert-info mt-3">
        {% for m in messages %}
          <div>{{ m }}</div>
        {% endfor %}
      </div>
    {% endif %}
  {% endwith %}
  {% block content %}{% endblock %}
  <footer class="footer-note text-center">
    &copy; Simple Feed
  </footer>
</div>
</body>
</html>
"""

index_template = """{% extends "layout" %}
{% block content %}
<h3>Latest Posts</h3>
{% if posts %}
  {% for p in posts %}
    <div class="card mb-3">
      <div class="card-body">
        <div class="d-flex justify-content-between">
          <div>
            <a class="username-link" href="{{ url_for('profile', username=p['username']) }}">{{ p['username'] }}</a>
            <div class="time-small">{{ p['created_at'] }}</div>
          </div>
        </div>
        <p class="card-text fs-5 mt-2">{{ p['content'] }}</p>
        {% if p['image_filename'] %}
          <img src="{{ url_for('uploaded_file', filename=p['image_filename']) }}" class="post-img">
        {% endif %}
      </div>
    </div>
  {% endfor %}
{% else %}
  <p class="text-muted">No posts yet. Be the first to post!</p>
{% endif %}
{% endblock %}
"""

register_template = """{% extends "layout" %}
{% block content %}
<h3>Register</h3>
<form method="post" class="mt-2">
  <div class="mb-3">
    <label class="form-label">Username</label>
    <input class="form-control form-control-lg" name="username" required>
  </div>
  <div class="mb-3">
    <label class="form-label">Password</label>
    <input type="password" class="form-control form-control-lg" name="password" required>
  </div>
  <button class="btn btn-gold btn-lg" type="submit">Register</button>
</form>
{% endblock %}
"""

login_template = """{% extends "layout" %}
{% block content %}
<h3>Login</h3>
<form method="post" class="mt-2">
  <div class="mb-3">
    <label class="form-label">Username</label>
    <input class="form-control form-control-lg" name="username" required>
  </div>
  <div class="mb-3">
    <label class="form-label">Password</label>
    <input type="password" class="form-control form-control-lg" name="password" required>
  </div>
  <button class="btn btn-gold btn-lg" type="submit">Login</button>
</form>
{% endblock %}
"""

create_post_template = """{% extends "layout" %}
{% block content %}
<h3>Create Post</h3>
<form method="post" enctype="multipart/form-data" class="mt-2">
  <div class="mb-3">
    <textarea class="form-control form-control-lg" name="content" rows="4" placeholder="Write something..."></textarea>
  </div>
  <div class="mb-3">
    <label class="form-label">Image (optional)</label>
    <input class="form-control" type="file" name="image" accept="image/*">
    <div class="form-text">Allowed: png/jpg/jpeg/gif. Max 15MB.</div>
  </div>
  <button class="btn btn-gold btn-lg" type="submit">Post</button>
</form>
{% endblock %}
"""

profile_template = """{% extends "layout" %}
{% block content %}
<h3>{{ profile_user['username'] }}'s Posts</h3>
{% if posts %}
  {% for p in posts %}
    <div class="card mb-3">
      <div class="card-body">
        <h6 class="card-subtitle mb-2 text-muted">{{ p['created_at'] }}</h6>
        <p class="card-text fs-5">{{ p['content'] }}</p>
        {% if p['image_filename'] %}
          <img src="{{ url_for('uploaded_file', filename=p['image_filename']) }}" class="post-img">
        {% endif %}
      </div>
    </div>
  {% endfor %}
{% else %}
  <p class="text-muted">No posts yet.</p>
{% endif %}
{% endblock %}
"""

search_template = """{% extends "layout" %}
{% block content %}
<h3>Search Users</h3>
{% if q %}
  <p class="mb-2">Results for "{{ q }}":</p>
  <ul class="list-unstyled">
    {% if results %}
      {% for r in results %}
        <li class="mb-2"><a class="username-link" href="{{ url_for('profile', username=r['username']) }}">{{ r['username'] }}</a></li>
      {% endfor %}
    {% else %}
      <li class="text-muted">No users found</li>
    {% endif %}
  </ul>
{% else %}
  <p class="text-muted">Enter a username keyword to search</p>
{% endif %}
{% endblock %}
"""

template_mapping = {
    'layout': layout_template,
    'index.html': index_template,
    'register.html': register_template,
    'login.html': login_template,
    'create_post.html': create_post_template,
    'profile.html': profile_template,
    'search.html': search_template
}

def render_template_by_name(name, **context):
    env = Environment(loader=DictLoader(template_mapping), autoescape=select_autoescape(['html', 'xml']))
    template = env.get_template(name)
    context['url_for'] = url_for
    context['get_flashed_messages'] = get_flashed_messages
    return template.render(**context)

# --- Database helpers ---
def get_db_connection():
    conn = getattr(g, '_database', None)
    if conn is None:
        conn = sqlite3.connect(app.config['DATABASE'])
        conn.row_factory = sqlite3.Row
        g._database = conn
    return conn

@app.teardown_appcontext
def close_db_connection(exception):
    conn = getattr(g, '_database', None)
    if conn is not None:
        conn.close()
        g._database = None

def initialize_database():
    sql = (
        "CREATE TABLE IF NOT EXISTS user ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "username TEXT UNIQUE NOT NULL,"
        "password_hash TEXT NOT NULL"
        ");"
        "CREATE TABLE IF NOT EXISTS post ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "user_id INTEGER NOT NULL,"
        "content TEXT,"
        "image_filename TEXT,"
        "created_at TEXT NOT NULL,"
        "FOREIGN KEY(user_id) REFERENCES user(id)"
        ");"
    )
    conn = get_db_connection()
    conn.executescript(sql)
    conn.commit()

def is_allowed_file(filename):
    if not filename:
        return False
    if '.' not in filename:
        return False
    parts = filename.rsplit('.', 1)
    if len(parts) != 2:
        return False
    ext = parts[1].lower()
    if ext in ALLOWED_EXTENSIONS:
        return True
    return False

def get_current_user():
    user_id = session.get('user_id')
    if not user_id:
        return None
    conn = get_db_connection()
    row = conn.execute('SELECT id, username FROM user WHERE id = ?', (user_id,)).fetchone()
    if not row:
        return None
    user = {}
    user['id'] = row['id']
    user['username'] = row['username']
    return user

# --- Routes ---
@app.route('/')
def index():
    conn = get_db_connection()
    rows = conn.execute(
        'SELECT post.id, post.user_id, post.content, post.image_filename, post.created_at, user.username '
        'FROM post JOIN user ON post.user_id = user.id ORDER BY datetime(post.created_at) DESC'
    ).fetchall()
    posts = []
    for r in rows:
        p = {}
        p['id'] = r['id']
        p['user_id'] = r['user_id']
        p['content'] = r['content']
        p['image_filename'] = r['image_filename']
        # store raw ISO and formatted display
        stored = r['created_at']
        p['created_at_iso'] = stored
        formatted = stored
        try:
            dt = datetime.fromisoformat(stored)
            if dt.tzinfo is None:
                # treat as UTC
                formatted = dt.strftime('%Y-%m-%d %H:%M UTC')
            else:
                dt_utc = dt.astimezone(timezone.utc)
                formatted = dt_utc.strftime('%Y-%m-%d %H:%M UTC')
        except Exception:
            formatted = stored
        p['created_at'] = formatted
        p['username'] = r['username']
        posts.append(p)
    return render_template_by_name('index.html', posts=posts, user=get_current_user())

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        if not username or not password:
            flash('Username and password are required')
            return redirect(url_for('register'))
        conn = get_db_connection()
        try:
            password_hash = generate_password_hash(password)
            conn.execute('INSERT INTO user (username, password_hash) VALUES (?, ?)', (username, password_hash))
            conn.commit()
        except sqlite3.IntegrityError:
            flash('Username already exists')
            return redirect(url_for('register'))
        flash('Registration successful, please log in')
        return redirect(url_for('login'))
    return render_template_by_name('register.html', user=get_current_user())

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        conn = get_db_connection()
        row = conn.execute('SELECT id, username, password_hash FROM user WHERE username = ?', (username,)).fetchone()
        if row:
            stored_hash = row['password_hash']
            if check_password_hash(stored_hash, password):
                session.clear()
                session['user_id'] = row['id']
                flash('Login successful')
                return redirect(url_for('index'))
        flash('Invalid username or password')
        return redirect(url_for('login'))
    return render_template_by_name('login.html', user=get_current_user())

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename, conditional=True)

@app.route('/create_post', methods=['GET', 'POST'])
def create_post():
    user = get_current_user()
    if not user:
        flash('Please log in first')
        return redirect(url_for('login'))
    if request.method == 'POST':
        content = request.form.get('content', '').strip()
        file = request.files.get('image')
        filename_on_disk = None
        if file and file.filename != '':
            original_filename = file.filename
            if not is_allowed_file(original_filename):
                flash('Only image files are allowed (png/jpg/jpeg/gif)')
                return redirect(url_for('create_post'))
            safe_name = secure_filename(original_filename)
            if not safe_name:
                flash('Invalid file name')
                return redirect(url_for('create_post'))
            name_part, ext_part = os.path.splitext(safe_name)
            timestamp = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')
            filename_on_disk = name_part + "_" + timestamp + ext_part
            save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename_on_disk)
            file.save(save_path)
        # store UTC ISO 8601 without microseconds for readability
        created_at_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        conn = get_db_connection()
        conn.execute('INSERT INTO post (user_id, content, image_filename, created_at) VALUES (?, ?, ?, ?)',
                     (user['id'], content, filename_on_disk, created_at_iso))
        conn.commit()
        flash('Posted')
        return redirect(url_for('index'))
    return render_template_by_name('create_post.html', user=get_current_user())

@app.route('/user/<username>')
def profile(username):
    conn = get_db_connection()
    row = conn.execute('SELECT id, username FROM user WHERE username = ?', (username,)).fetchone()
    if not row:
        flash('User not found')
        return redirect(url_for('index'))
    profile_user = {}
    profile_user['id'] = row['id']
    profile_user['username'] = row['username']
    post_rows = conn.execute('SELECT id, user_id, content, image_filename, created_at FROM post WHERE user_id = ? ORDER BY datetime(created_at) DESC', (profile_user['id'],)).fetchall()
    posts = []
    for r in post_rows:
        p = {}
        p['id'] = r['id']
        p['user_id'] = r['user_id']
        p['content'] = r['content']
        p['image_filename'] = r['image_filename']
        stored = r['created_at']
        p['created_at_iso'] = stored
        formatted = stored
        try:
            dt = datetime.fromisoformat(stored)
            if dt.tzinfo is None:
                formatted = dt.strftime('%Y-%m-%d %H:%M UTC')
            else:
                dt_utc = dt.astimezone(timezone.utc)
                formatted = dt_utc.strftime('%Y-%m-%d %H:%M UTC')
        except Exception:
            formatted = stored
        p['created_at'] = formatted
        posts.append(p)
    return render_template_by_name('profile.html', profile_user=profile_user, posts=posts, user=get_current_user())

@app.route('/search', methods=['GET'])
def search():
    q = request.args.get('q', '').strip()
    results = []
    if q:
        conn = get_db_connection()
        rows = conn.execute('SELECT id, username FROM user WHERE username LIKE ? LIMIT 50', ('%' + q + '%',)).fetchall()
        for r in rows:
            item = {}
            item['id'] = r['id']
            item['username'] = r['username']
            results.append(item)
    return render_template_by_name('search.html', q=q, results=results, user=get_current_user())

# --- Startup: ensure environment and initialize DB ---
def ensure_environment():
    if not os.path.exists(app.config['UPLOAD_FOLDER']):
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    if not os.path.exists(app.config['DATABASE']):
        with app.app_context():
            initialize_database()

if __name__ == '__main__':
    app.secret_key = app.config['SECRET_KEY']
    ensure_environment()
    app.run(debug=True)
