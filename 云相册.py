import os
import sqlite3
from flask import Flask, g, request, redirect, url_for, render_template_string, send_from_directory, abort
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

# --- App Configuration ---
app = Flask(__name__)
app.config.update(
    SECRET_KEY='replace-with-a-secure-key',
    DATABASE=os.path.join(app.root_path, 'app.db'),
    UPLOAD_FOLDER=os.path.join(app.root_path, 'uploads')
)
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# --- Login Manager ---
login_manager = LoginManager(app)
login_manager.login_view = 'login'

class User(UserMixin):
    def __init__(self, id, username, password_hash):
        self.id = id
        self.username = username
        self.password_hash = password_hash
    def verify_password(self, pwd):
        return check_password_hash(self.password_hash, pwd)

@login_manager.user_loader
def load_user(user_id):
    row = query_db('SELECT id,username,password_hash FROM users WHERE id=?', [user_id], one=True)
    return User(*row) if row else None

# --- Database Helpers ---
def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(app.config['DATABASE'])
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(exc):
    db = g.pop('db', None)
    if db: db.close()

def init_db():
    db = get_db()
    db.executescript('''
    CREATE TABLE IF NOT EXISTS users (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      username TEXT UNIQUE NOT NULL,
      password_hash TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS images (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER NOT NULL,
      filename TEXT NOT NULL,
      upload_time DATETIME DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY(user_id) REFERENCES users(id)
    );
    ''')
    db.commit()

def query_db(sql, args=(), one=False):
    cur = get_db().execute(sql, args)
    rv = cur.fetchall()
    cur.close()
    return (rv[0] if rv else None) if one else rv

def execute_db(sql, args=()):
    db = get_db()
    cur = db.execute(sql, args)
    db.commit()
    return cur.lastrowid

# --- Templates (embedded) ---
base_html = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{% block title %}Image Gallery{% endblock %}</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootswatch@5.3.2/dist/minty/bootstrap.min.css">
  <style>
    body { padding-top: 4.5rem; }
    .gallery-img { cursor: pointer; transition: transform .2s; }
    .gallery-img:hover { transform: scale(1.05); }
  </style>
</head>
<body>
<nav class="navbar navbar-expand-md navbar-dark bg-primary fixed-top">
  <div class="container-fluid">
    <a class="navbar-brand" href="{{ url_for('manage') }}">GalleryApp</a>
    <button class="navbar-toggler" type="button" data-bs-toggle="collapse"
      data-bs-target="#navbarsExampleDefault">
      <span class="navbar-toggler-icon"></span>
    </button>
    <div class="collapse navbar-collapse" id="navbarsExampleDefault">
      <ul class="navbar-nav me-auto">
        {% if current_user.is_authenticated %}
        <li class="nav-item"><a class="nav-link" href="{{ url_for('manage') }}">Manage</a></li>
        <li class="nav-item"><a class="nav-link" href="{{ url_for('gallery') }}">Gallery</a></li>
        <li class="nav-item"><a class="nav-link" href="{{ url_for('search') }}">Search</a></li>
        <li class="nav-item"><a class="nav-link" href="{{ url_for('logout') }}">Logout</a></li>
        {% else %}
        <li class="nav-item"><a class="nav-link" href="{{ url_for('login') }}">Login</a></li>
        <li class="nav-item"><a class="nav-link" href="{{ url_for('register') }}">Register</a></li>
        {% endif %}
      </ul>
    </div>
  </div>
</nav>
<main class="container">
  {% block content %}{% endblock %}
</main>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
"""

register_html = """
{% extends 'base.html' %}{% block title %}Register{% endblock %}
{% block content %}
<div class="row justify-content-center">
  <div class="col-md-6">
    <h2>Register</h2>
    <form method="post">
      <div class="mb-3">
        <label class="form-label">Username</label>
        <input class="form-control" name="username" required>
      </div>
      <div class="mb-3">
        <label class="form-label">Password</label>
        <input class="form-control" type="password" name="password" required>
      </div>
      <button class="btn btn-success">Register</button>
    </form>
  </div>
</div>
{% endblock %}
"""

login_html = """
{% extends 'base.html' %}{% block title %}Login{% endblock %}
{% block content %}
<div class="row justify-content-center">
  <div class="col-md-6">
    <h2>Login</h2>
    <form method="post">
      <div class="mb-3">
        <label class="form-label">Username</label>
        <input class="form-control" name="username" required>
      </div>
      <div class="mb-3">
        <label class="form-label">Password</label>
        <input class="form-control" type="password" name="password" required>
      </div>
      <button class="btn btn-primary">Login</button>
    </form>
  </div>
</div>
{% endblock %}
"""

manage_html = """
{% extends 'base.html' %}{% block title %}Manage Images{% endblock %}
{% block content %}
<h2>Upload New Image</h2>
<form method="post" enctype="multipart/form-data" class="mb-4">
  <input class="form-control" type="file" name="file" accept="image/*" required>
  <button class="btn btn-success mt-2">Upload</button>
</form>
<hr>
<div class="row">
  {% for img in images %}
  <div class="col-sm-4 mb-3 text-center">
    <img src="{{ url_for('uploaded_file', filename=img.filename) }}" 
         class="img-fluid rounded gallery-img" data-index="{{ loop.index0 }}">
    <p class="text-muted small">{{ img.upload_time }}</p>
    <form method="post" action="{{ url_for('delete_image', image_id=img.id) }}">
      <button class="btn btn-sm btn-danger">Delete</button>
    </form>
  </div>
  {% endfor %}
  {% if not images %}
    <p>No images uploaded yet.</p>
  {% endif %}
</div>
{% endblock %}
"""

gallery_html = """
{% extends 'base.html' %}{% block title %}Gallery{% endblock %}
{% block content %}
<h2>Fullscreen Gallery</h2>
<div class="row">
  {% for img in images %}
  <div class="col-sm-3 mb-3">
    <img src="{{ url_for('uploaded_file', filename=img.filename) }}"
         class="img-fluid rounded gallery-img" data-index="{{ loop.index0 }}">
  </div>
  {% endfor %}
</div>

<!-- Modal -->
<div class="modal fade" id="lightboxModal" tabindex="-1">
  <div class="modal-dialog modal-fullscreen">
    <div class="modal-content bg-dark">
      <div class="modal-body d-flex align-items-center justify-content-center">
        <button class="btn btn-outline-light me-auto" id="prevBtn">&laquo;</button>
        <img id="modalImg" src="" class="img-fluid">
        <button class="btn btn-outline-light ms-auto" id="nextBtn">&raquo;</button>
      </div>
    </div>
  </div>
</div>

<script>
  const images = {{ images|tojson }};
  let currentIndex = 0;
  const modal = new bootstrap.Modal(document.getElementById('lightboxModal'));
  const modalImg = document.getElementById('modalImg');

  document.querySelectorAll('.gallery-img').forEach(el => {
    el.addEventListener('click', () => {
      currentIndex = parseInt(el.dataset.index);
      showImage();
      modal.show();
    });
  });

  document.getElementById('prevBtn').addEventListener('click', () => {
    currentIndex = (currentIndex - 1 + images.length) % images.length;
    showImage();
  });
  document.getElementById('nextBtn').addEventListener('click', () => {
    currentIndex = (currentIndex + 1) % images.length;
    showImage();
  });

  function showImage() {
    modalImg.src = '/uploads/' + images[currentIndex].filename;
  }
</script>
{% endblock %}
"""

search_html = """
{% extends 'base.html' %}{% block title %}Search Users{% endblock %}
{% block content %}
<h2>Search Users</h2>
<form method="get" class="mb-3">
  <div class="input-group">
    <input class="form-control" name="q" placeholder="Enter username" value="{{ request.args.get('q','') }}">
    <button class="btn btn-primary">Search</button>
  </div>
</form>
{% if users is not none %}
  {% if users %}
    <ul class="list-group">
    {% for u in users %}
      <li class="list-group-item">
        <a href="{{ url_for('profile', username=u.username) }}">
          <b>{{ u.username }}</b>
        </a>
      </li>
    {% endfor %}
    </ul>
  {% else %}
    <p>No matching users.</p>
  {% endif %}
{% endif %}
{% endblock %}
"""

profile_html = """
{% extends 'base.html' %}{% block title %}{{ user.username }}'s Album{% endblock %}
{% block content %}
<h2>{{ user.username }}'s Album</h2>
<div class="row">
  {% for img in images %}
  <div class="col-sm-3 mb-3">
    <img src="{{ url_for('uploaded_file', filename=img.filename) }}" class="img-fluid rounded">
    <p class="text-muted small">{{ img.upload_time }}</p>
  </div>
  {% endfor %}
  {% if not images %}
    <p>No images uploaded yet.</p>
  {% endif %}
</div>
{% endblock %}
"""

# --- Routes ---
@app.route('/register', methods=['GET','POST'])
def register():
    if request.method == 'POST':
        u, p = request.form['username'], request.form['password']
        if query_db('SELECT 1 FROM users WHERE username=?', [u], one=True):
            return 'Username exists', 400
        ph = generate_password_hash(p)
        execute_db('INSERT INTO users(username,password_hash) VALUES(?,?)', [u,ph])
        return redirect(url_for('login'))
    return render_template_string(register_html)

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method=='POST':
        u,p = request.form['username'],request.form['password']
        row = query_db('SELECT id,username,password_hash FROM users WHERE username=?',[u], one=True)
        if row and User(*row).verify_password(p):
            login_user(User(*row))
            return redirect(url_for('manage'))
        return 'Invalid credentials', 400
    return render_template_string(login_html)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/manage', methods=['GET','POST'])
@login_required
def manage():
    if request.method=='POST':
        f = request.files.get('file')
        if not f or not f.filename: return 'No file',400
        fn = secure_filename(f.filename)
        f.save(os.path.join(app.config['UPLOAD_FOLDER'],fn))
        execute_db('INSERT INTO images(user_id,filename) VALUES(?,?)',[current_user.id,fn])
        return redirect(url_for('manage'))
    imgs = query_db('SELECT id,filename,upload_time FROM images WHERE user_id=? ORDER BY upload_time DESC',[current_user.id])
    return render_template_string(manage_html, images=imgs)

@app.route('/gallery')
@login_required
def gallery():
    imgs = query_db('SELECT filename FROM images WHERE user_id=? ORDER BY upload_time DESC',[current_user.id])
    return render_template_string(gallery_html, images=imgs)

@app.route('/delete/<int:image_id>', methods=['POST'])
@login_required
def delete_image(image_id):
    rec = query_db('SELECT user_id,filename FROM images WHERE id=?',[image_id], one=True)
    if not rec or rec['user_id']!=current_user.id: abort(403)
    path = os.path.join(app.config['UPLOAD_FOLDER'], rec['filename'])
    if os.path.exists(path): os.remove(path)
    execute_db('DELETE FROM images WHERE id=?',[image_id])
    return redirect(url_for('manage'))

@app.route('/search')
@login_required
def search():
    q = request.args.get('q','').strip()
    users = None
    if q:
        users = query_db('SELECT username FROM users WHERE username LIKE ? COLLATE NOCASE',[f'%{q}%'])
    return render_template_string(search_html, users=users)

@app.route('/user/<username>')
@login_required
def profile(username):
    row = query_db('SELECT id,username FROM users WHERE username=?',[username], one=True)
    if not row: abort(404)
    imgs = query_db('SELECT filename,upload_time FROM images WHERE user_id=? ORDER BY upload_time DESC',[row['id']])
    return render_template_string(profile_html, user=row, images=imgs)

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# --- Startup ---
if __name__ == '__main__':
    init_db()
    app.run(debug=True)
