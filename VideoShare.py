"""
This application is a simple video-sharing platform built with Python and the Flask web framework. It uses SQLite as its database to store user accounts and video metadata, and stores uploaded video files on the server’s filesystem. Users can register, sign in, and manage their own profile pages, where they can upload new videos in mp4, mov, or avi format, browse previously uploaded content, and delete any video they no longer wish to keep. The frontend is styled with Bootstrap to provide a responsive, mobile-friendly interface, and all user passwords are securely hashed before storage.
"""


import os
import sqlite3
from flask import (
    Flask, g, render_template, request, redirect,
    url_for, flash, session, send_from_directory, abort
)
from jinja2 import DictLoader
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

# -------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
DATABASE_PATH = os.path.join(BASE_DIR, 'site.db')
ALLOWED_EXTENSIONS = {'mp4', 'mov', 'avi'}

app = Flask(__name__)
app.config.update(
    SECRET_KEY='REPLACE_WITH_A_STRONG_SECRET_KEY',
    UPLOAD_FOLDER=UPLOAD_FOLDER
)

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# -------------------------------------------------------------------
# Templates
# -------------------------------------------------------------------
TEMPLATES = {
    'layout.html': '''
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Video Sharing Platform</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.4.3/dist/css/bootstrap.min.css" rel="stylesheet">
  <style> video { border-radius: 4px; } </style>
</head>
<body>
<nav class="navbar navbar-expand-lg navbar-dark bg-dark">
  <div class="container-fluid">
    <a class="navbar-brand" href="{{ url_for('home') }}">VideoPlatform</a>
    <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#navMenu">
      <span class="navbar-toggler-icon"></span>
    </button>
    <div id="navMenu" class="collapse navbar-collapse">
      <ul class="navbar-nav me-auto">
        <li class="nav-item">
          <form class="d-flex ms-3" action="{{ url_for('profile', username='') }}" method="get">
            <input name="username" class="form-control form-control-sm me-2" placeholder="Search username">
            <button class="btn btn-outline-light btn-sm">Search</button>
          </form>
        </li>
      </ul>
      <ul class="navbar-nav">
        {% if g.current_user %}
          <li class="nav-item">
            <a class="nav-link" href="{{ url_for('profile', username=g.current_user['username']) }}">My Profile</a>
          </li>
          <li class="nav-item">
            <a class="nav-link" href="{{ url_for('logout') }}">Sign Out</a>
          </li>
        {% else %}
          <li class="nav-item">
            <a class="nav-link" href="{{ url_for('login') }}">Sign In</a>
          </li>
          <li class="nav-item">
            <a class="nav-link" href="{{ url_for('register') }}">Register</a>
          </li>
        {% endif %}
      </ul>
    </div>
  </div>
</nav>
<div class="container py-4">
  {% with messages = get_flashed_messages(with_categories=true) %}
    {% if messages %}
      {% for category, message in messages %}
        <div class="alert alert-{{ category }} alert-dismissible fade show">
          {{ message }}
          <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        </div>
      {% endfor %}
    {% endif %}
  {% endwith %}
  {% block content %}{% endblock %}
</div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.4.3/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
''',
    'home.html': '''
{% extends "layout.html" %}
{% block content %}
<div class="text-center">
  <h1 class="display-5">Welcome to VideoPlatform</h1>
  <p class="lead">Register or sign in to upload and browse videos.</p>
  <a class="btn btn-primary btn-lg me-2" href="{{ url_for('register') }}">Register</a>
  <a class="btn btn-secondary btn-lg" href="{{ url_for('login') }}">Sign In</a>
</div>
{% endblock %}
''',
    'registration.html': '''
{% extends "layout.html" %}
{% block content %}
<div class="row justify-content-center">
  <div class="col-md-6">
    <h3>Register</h3>
    <form method="post" class="needs-validation" novalidate>
      <div class="mb-3">
        <label class="form-label">Username</label>
        <input name="username" class="form-control" required minlength="3">
        <div class="invalid-feedback">Please enter at least 3 characters.</div>
      </div>
      <div class="mb-3">
        <label class="form-label">Password</label>
        <input name="password" type="password" class="form-control" required minlength="6">
        <div class="invalid-feedback">Please enter at least 6 characters.</div>
      </div>
      <button class="btn btn-success">Register</button>
    </form>
  </div>
</div>
<script>
(() => {
  'use strict';
  document.querySelectorAll('.needs-validation').forEach(form => {
    form.addEventListener('submit', event => {
      if (!form.checkValidity()) {
        event.preventDefault();
        event.stopPropagation();
      }
      form.classList.add('was-validated');
    }, false);
  });
})();
</script>
{% endblock %}
''',
    'sign_in.html': '''
{% extends "layout.html" %}
{% block content %}
<div class="row justify-content-center">
  <div class="col-md-6">
    <h3>Sign In</h3>
    <form method="post" class="needs-validation" novalidate>
      <div class="mb-3">
        <label class="form-label">Username</label>
        <input name="username" class="form-control" required>
        <div class="invalid-feedback">Username is required.</div>
      </div>
      <div class="mb-3">
        <label class="form-label">Password</label>
        <input name="password" type="password" class="form-control" required>
        <div class="invalid-feedback">Password is required.</div>
      </div>
      <button class="btn btn-primary">Sign In</button>
    </form>
  </div>
</div>
<script>
(() => {
  'use strict';
  document.querySelectorAll('.needs-validation').forEach(form => {
    form.addEventListener('submit', event => {
      if (!form.checkValidity()) {
        event.preventDefault();
        event.stopPropagation();
      }
      form.classList.add('was-validated');
    }, false);
  });
})();
</script>
{% endblock %}
''',
    'profile.html': '''
{% extends "layout.html" %}
{% block content %}
<div class="d-flex justify-content-between align-items-center mb-3">
  <h3>{{ owner['username'] }}'s Videos</h3>
  {% if g.current_user and g.current_user['id'] == owner['id'] %}
    <button class="btn btn-outline-primary" data-bs-toggle="collapse" data-bs-target="#uploadSection">
      Upload New Video
    </button>
  {% endif %}
</div>
<div class="collapse mb-4" id="uploadSection">
  <div class="card card-body">
    <form method="post" enctype="multipart/form-data">
      <div class="input-group">
        <input type="file" name="video_file" class="form-control" required>
        <button class="btn btn-success">Upload</button>
      </div>
    </form>
  </div>
</div>
<div class="row">
  {% for video in videos %}
    <div class="col-sm-6 col-lg-4 mb-4">
      <div class="card h-100">
        <video class="card-img-top" controls>
          <source src="{{ url_for('serve_video', filename=video['filename']) }}" type="video/mp4">
        </video>
        <div class="card-body">
          <p class="card-text"><small class="text-muted">{{ video['upload_time'] }}</small></p>
          {% if g.current_user and g.current_user['id'] == owner['id'] %}
            <form action="{{ url_for('delete_video', video_id=video['id']) }}" method="post">
              <button class="btn btn-danger btn-sm">Delete</button>
            </form>
          {% endif %}
        </div>
      </div>
    </div>
  {% endfor %}
  {% if not videos %}
    <p class="text-muted">No videos uploaded yet.</p>
  {% endif %}
</div>
{% endblock %}
'''
}

app.jinja_loader = DictLoader(TEMPLATES)

# -------------------------------------------------------------------
# Database Helpers
# -------------------------------------------------------------------
def get_db():
    if 'db' not in g:
        conn = sqlite3.connect(DATABASE_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
        conn.row_factory = sqlite3.Row
        g.db = conn
    return g.db

@app.teardown_appcontext
def close_db(error=None):
    db = g.pop('db', None)
    if db:
        db.close()

def init_db():
    db = get_db()
    db.executescript("""
    CREATE TABLE IF NOT EXISTS user_account (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS video_record (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        filename TEXT NOT NULL,
        upload_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        user_id INTEGER NOT NULL,
        FOREIGN KEY (user_id) REFERENCES user_account (id)
    );
    """)

@app.before_first_request
def setup_db():
    init_db()

@app.before_request
def load_current_user():
    user_id = session.get('user_id')
    g.current_user = None
    if user_id:
        g.current_user = get_db().execute(
            "SELECT * FROM user_account WHERE id = ?", (user_id,)
        ).fetchone()

# -------------------------------------------------------------------
# Utility
# -------------------------------------------------------------------
def is_allowed_video(filename):
    return (
        '.' in filename and
        filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS
    )

# -------------------------------------------------------------------
# Routes
# -------------------------------------------------------------------
@app.route('/')
def home():
    return render_template('home.html')

@app.route('/register', methods=('GET', 'POST'))
def register():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        if len(username) < 3 or len(password) < 6:
            flash('Username ≥3 chars and Password ≥6 chars required.', 'danger')
        else:
            db = get_db()
            try:
                db.execute(
                    "INSERT INTO user_account (username, password_hash) VALUES (?, ?)",
                    (username, generate_password_hash(password))
                )
                db.commit()
            except sqlite3.IntegrityError:
                flash('Username already taken.', 'danger')
            else:
                flash('Registration successful. Please sign in.', 'success')
                return redirect(url_for('login'))
    return render_template('registration.html')

@app.route('/login', methods=('GET', 'POST'))
def login():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        user = get_db().execute(
            "SELECT * FROM user_account WHERE username = ?", (username,)
        ).fetchone()
        if user and check_password_hash(user['password_hash'], password):
            session.clear()
            session['user_id'] = user['id']
            return redirect(url_for('profile', username=username))
        flash('Invalid credentials.', 'danger')
    return render_template('sign_in.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

@app.route('/user/<username>', methods=('GET', 'POST'))
def profile(username):
    db = get_db()
    owner = db.execute(
        "SELECT * FROM user_account WHERE username = ?", (username,)
    ).fetchone() or abort(404)
    if request.method == 'POST':
        if not g.current_user or g.current_user['id'] != owner['id']:
            abort(403)
        file = request.files.get('video_file')
        if file and is_allowed_video(file.filename):
            filename = secure_filename(f"{owner['id']}_{file.filename}")
            path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(path)
            db.execute(
                "INSERT INTO video_record (filename, user_id) VALUES (?, ?)",
                (filename, owner['id'])
            )
            db.commit()
            flash('Video uploaded successfully.', 'success')
            return redirect(url_for('profile', username=username))
        flash('Invalid video file.', 'danger')
    videos = db.execute(
        "SELECT * FROM video_record WHERE user_id = ? ORDER BY upload_time DESC",
        (owner['id'],)
    ).fetchall()
    return render_template('profile.html', owner=owner, videos=videos)

@app.route('/delete/<int:video_id>', methods=('POST',))
def delete_video(video_id):
    db = get_db()
    video = db.execute(
        "SELECT * FROM video_record WHERE id = ?", (video_id,)
    ).fetchone() or abort(404)
    if not g.current_user or g.current_user['id'] != video['user_id']:
        abort(403)
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], video['filename'])
    if os.path.exists(file_path):
        os.remove(file_path)
    db.execute("DELETE FROM video_record WHERE id = ?", (video_id,))
    db.commit()
    flash('Video deleted successfully.', 'info')
    return redirect(url_for('profile', username=g.current_user['username']))

@app.route('/uploads/<filename>')
def serve_video(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


from flask import jsonify
# API: List all videos
@app.route('/api/videos', methods=['GET'])
def api_list_videos():
    db = get_db()
    rows = db.execute(
        "SELECT vr.id, vr.filename, vr.upload_time, ua.username "
        "FROM video_record AS vr "
        "JOIN user_account AS ua ON vr.user_id = ua.id "
        "ORDER BY vr.upload_time DESC"
    ).fetchall()
    videos = []
    for row in rows:
        videos.append({
            "id":            row["id"],
            "filename":      row["filename"],
            "upload_time":   row["upload_time"],
            "username":      row["username"],
            "stream_url":    url_for('serve_video', filename=row["filename"], _external=True),
            "download_url":  url_for('serve_video', filename=row["filename"], _external=True)
        })
    return jsonify(videos), 200


# API: List videos for a given user
@app.route('/api/user/<username>/videos', methods=['GET'])
def api_user_videos(username):
    db = get_db()
    user = db.execute(
        "SELECT id FROM user_account WHERE username = ?", (username,)
    ).fetchone()
    if not user:
        return jsonify({"error": "user not found"}), 404
    rows = db.execute(
        "SELECT id, filename, upload_time "
        "FROM video_record "
        "WHERE user_id = ? "
        "ORDER BY upload_time DESC",
        (user["id"],)
    ).fetchall()
    videos = []
    for row in rows:
        videos.append({
            "id":            row["id"],
            "filename":      row["filename"],
            "upload_time":   row["upload_time"],
            "stream_url":    url_for('serve_video', filename=row["filename"], _external=True),
            "download_url":  url_for('serve_video', filename=row["filename"], _external=True)
        })
    return jsonify(videos), 200


# API: Get single video metadata and URLs
@app.route('/api/video/<int:video_id>', methods=['GET'])
def api_video_detail(video_id):
    db = get_db()
    row = db.execute(
        "SELECT vr.id, vr.filename, vr.upload_time, ua.username "
        "FROM video_record AS vr "
        "JOIN user_account AS ua ON vr.user_id = ua.id "
        "WHERE vr.id = ?",
        (video_id,)
    ).fetchone()
    if not row:
        return jsonify({"error": "video not found"}), 404
    data = {
        "id":            row["id"],
        "filename":      row["filename"],
        "upload_time":   row["upload_time"],
        "username":      row["username"],
        "stream_url":    url_for('serve_video', filename=row["filename"], _external=True),
        "download_url":  url_for('serve_video', filename=row["filename"], _external=True)
    }
    return jsonify(data), 200






if __name__ == '__main__':
    app.run(debug=True)
