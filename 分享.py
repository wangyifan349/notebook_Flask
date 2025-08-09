import os
import sqlite3
from flask import (
    Flask, request, redirect, url_for, flash,
    session, send_from_directory, abort, render_template_string
)
from werkzeug.security import generate_password_hash, check_password_hash
from itsdangerous import URLSafeSerializer

# ─── Configuration ─────────────────────────────────────────────────────────────

app = Flask(__name__)
app.config['SECRET_KEY'] = 'replace_with_a_secure_random_string'
BASE_UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
DATABASE_PATH = os.path.join(os.path.dirname(__file__), 'storage.db')
URL_SIGNER = URLSafeSerializer(app.config['SECRET_KEY'], salt='share_salt')

os.makedirs(BASE_UPLOAD_FOLDER, exist_ok=True)

# ─── Database Helpers ──────────────────────────────────────────────────────────

def get_database_connection():
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    return connection

def initialize_database():
    with get_database_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS shares (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token TEXT UNIQUE NOT NULL,
                path TEXT NOT NULL,
                permanent INTEGER NOT NULL DEFAULT 0
            );
        """)
        conn.commit()

@app.before_first_request
def setup():
    initialize_database()

# ─── Utility Functions ────────────────────────────────────────────────────────

def safe_path(relative_path=''):
    full = os.path.abspath(os.path.join(BASE_UPLOAD_FOLDER, relative_path))
    if not full.startswith(os.path.abspath(BASE_UPLOAD_FOLDER)):
        abort(400)
    return full

def current_user_id():
    return session.get('user_id')

def login_required(view):
    from functools import wraps
    @wraps(view)
    def wrapped_view(**kwargs):
        if current_user_id() is None:
            return redirect(url_for('login'))
        return view(**kwargs)
    return wrapped_view

def generate_share_token(path, permanent=False):
    token = URL_SIGNER.dumps(path)
    with get_database_connection() as conn:
        conn.execute(
            "INSERT INTO shares (token, path, permanent) VALUES (?, ?, ?);",
            (token, path, int(permanent))
        )
        conn.commit()
    return token

def revoke_share(path):
    with get_database_connection() as conn:
        conn.execute("DELETE FROM shares WHERE path = ?;", (path,))
        conn.commit()

def validate_share_token(token):
    with get_database_connection() as conn:
        row = conn.execute(
            "SELECT path FROM shares WHERE token = ?;",
            (token,)
        ).fetchone()
    if not row:
        return None
    try:
        URL_SIGNER.loads(token)
        return row['path']
    except:
        return None

# ─── Authentication Routes ────────────────────────────────────────────────────

@app.route('/register', methods=('GET','POST'))
def register():
    if request.method == 'POST':
        username = request.form['username']
        password_hash = generate_password_hash(request.form['password'])
        try:
            with get_database_connection() as conn:
                conn.execute(
                    "INSERT INTO users (username, password_hash) VALUES (?, ?);",
                    (username, password_hash)
                )
                conn.commit()
            flash('Registration successful. Please log in.')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('Username already taken.')
    return render_template_string(BASE_TEMPLATE, **locals(), CONTENT=REGISTER_TEMPLATE)

@app.route('/login', methods=('GET','POST'))
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        with get_database_connection() as conn:
            row = conn.execute(
                "SELECT id, password_hash FROM users WHERE username = ?;",
                (username,)
            ).fetchone()
        if row and check_password_hash(row['password_hash'], password):
            session.clear()
            session['user_id'] = row['id']
            return redirect(url_for('browser'))
        flash('Invalid credentials.')
    return render_template_string(BASE_TEMPLATE, **locals(), CONTENT=LOGIN_TEMPLATE)

@app.route('/logout')
@login_required
def logout():
    session.clear()
    return redirect(url_for('login'))

# ─── File Browser and Operations ───────────────────────────────────────────────

@app.route('/', defaults={'subpath': ''})
@app.route('/<path:subpath>')
@login_required
def browser(subpath):
    absolute_folder = safe_path(subpath)
    entries = []
    for name in sorted(os.listdir(absolute_folder)):
        full = os.path.join(absolute_folder, name)
        share_row = get_database_connection().execute(
            "SELECT id FROM shares WHERE path = ?;", (os.path.join(subpath, name),)
        ).fetchone()
        entries.append({
            'name': name,
            'is_folder': os.path.isdir(full),
            'relative_path': os.path.join(subpath, name),
            'is_shared': bool(share_row)
        })
    return render_template_string(
        BASE_TEMPLATE,
        **locals(),
        CONTENT=BROWSER_TEMPLATE
    )

@app.route('/upload', methods=('POST',))
@login_required
def upload_file():
    target_folder = request.form['current_path']
    file = request.files.get('file')
    if file:
        destination = os.path.join(safe_path(target_folder), file.filename)
        file.save(destination)
        flash(f'Uploaded {file.filename}')
    return redirect(url_for('browser', subpath=target_folder))

@app.route('/download/<path:relative_path>')
@login_required
def download_file(relative_path):
    full = safe_path(relative_path)
    directory, filename = os.path.split(full)
    return send_from_directory(directory, filename, as_attachment=True)

@app.route('/make_folder', methods=('POST',))
@login_required
def make_folder():
    target_folder = request.form['current_path']
    new_name = request.form['folder_name']
    os.makedirs(safe_path(os.path.join(target_folder, new_name)), exist_ok=True)
    flash(f'Created folder {new_name}')
    return redirect(url_for('browser', subpath=target_folder))

@app.route('/delete', methods=('POST',))
@login_required
def delete_entry():
    target = request.form['relative_path']
    full = safe_path(target)
    if os.path.isdir(full):
        os.rmdir(full)
        flash(f'Deleted folder {os.path.basename(target)}')
    else:
        os.remove(full)
        flash(f'Deleted file {os.path.basename(target)}')
    return redirect(url_for('browser', subpath=os.path.dirname(target)))

@app.route('/rename', methods=('POST',))
@login_required
def rename_entry():
    old_path = request.form['old_relative_path']
    new_name = request.form['new_name']
    new_path = os.path.join(os.path.dirname(old_path), new_name)
    os.rename(safe_path(old_path), safe_path(new_path))
    flash(f'Renamed to {new_name}')
    return redirect(url_for('browser', subpath=os.path.dirname(old_path)))

# ─── Sharing Routes ───────────────────────────────────────────────────────────

@app.route('/share', methods=('POST',))
@login_required
def share_entry():
    target = request.form['relative_path']
    permanent = bool(request.form.get('permanent'))
    token = generate_share_token(target, permanent)
    link = url_for('shared_browser', token=token, _external=True)
    flash(f'Share link: {link}')
    return redirect(url_for('browser', subpath=os.path.dirname(target)))

@app.route('/unshare', methods=('POST',))
@login_required
def unshare_entry():
    target = request.form['relative_path']
    revoke_share(target)
    flash(f'Unshared {os.path.basename(target)}')
    return redirect(url_for('browser', subpath=os.path.dirname(target)))

@app.route('/s/<token>/', defaults={'subpath': ''})
@app.route('/s/<token>/<path:subpath>')
def shared_browser(token, subpath):
    base_relative = validate_share_token(token)
    if not base_relative:
        abort(404)
    requested_relative = os.path.normpath(os.path.join(base_relative, subpath))
    absolute_path = safe_path(requested_relative)
    if os.path.isdir(absolute_path):
        entries = []
        for name in sorted(os.listdir(absolute_path)):
            full = os.path.join(absolute_path, name)
            entries.append({
                'name': name,
                'is_folder': os.path.isdir(full),
                'subpath': os.path.join(subpath, name)
            })
        return render_template_string(
            BASE_TEMPLATE,
            **locals(),
            CONTENT=SHARED_TEMPLATE
        )
    else:
        directory, filename = os.path.split(absolute_path)
        return send_from_directory(directory, filename, as_attachment=True)

# ─── Templates ────────────────────────────────────────────────────────────────

BASE_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{ title if title else 'Flask File Storage' }}</title>
  <link
    href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css"
    rel="stylesheet">
</head>
<body class="bg-light">
<nav class="navbar navbar-expand-lg navbar-dark bg-primary mb-4">
  <div class="container-fluid">
    <a class="navbar-brand" href="{{ url_for('browser') }}">FileStorage</a>
    <div class="collapse navbar-collapse justify-content-end">
      {% if session.user_id %}
      <ul class="navbar-nav">
        <li class="nav-item">
          <a class="nav-link">User #{{ session.user_id }}</a>
        </li>
        <li class="nav-item">
          <a class="nav-link" href="{{ url_for('logout') }}">Logout</a>
        </li>
      </ul>
      {% endif %}
    </div>
  </div>
</nav>
<div class="container">
  {% with messages = get_flashed_messages() %}
    {% if messages %}
      <div class="alert alert-info">
        {% for msg in messages %}<div>{{ msg }}</div>{% endfor %}
      </div>
    {% endif %}
  {% endwith %}
  {{ super() }}
  {{ CONTENT }}
</div>
<script
  src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js">
</script>
</body>
</html>
"""

REGISTER_TEMPLATE = """
{% block title %}Register{% endblock %}
<form method="post" class="w-50 mx-auto">
  <h3>Register</h3>
  <div class="mb-3">
    <input name="username" class="form-control" placeholder="Username" required>
  </div>
  <div class="mb-3">
    <input type="password" name="password" class="form-control" placeholder="Password" required>
  </div>
  <button class="btn btn-primary">Register</button>
  <a href="{{ url_for('login') }}" class="btn btn-link">Login</a>
</form>
"""

LOGIN_TEMPLATE = """
{% block title %}Login{% endblock %}
<form method="post" class="w-50 mx-auto">
  <h3>Login</h3>
  <div class="mb-3">
    <input name="username" class="form-control" placeholder="Username" required>
  </div>
  <div class="mb-3">
    <input type="password" name="password" class="form-control" placeholder="Password" required>
  </div>
  <button class="btn btn-primary">Login</button>
  <a href="{{ url_for('register') }}" class="btn btn-link">Register</a>
</form>
"""

BROWSER_TEMPLATE = """
{% block title %}Browsing {{ current_path or '/' }}{% endblock %}
<h4>Directory: {{ current_path or '/' }}</h4>
<table class="table table-striped">
  <thead><tr><th>Name</th><th>Type</th><th>Actions</th></tr></thead>
  <tbody>
  {% for entry in entries %}
    <tr>
      <td>
        {% if entry.is_folder %}
          <a href="{{ url_for('browser', subpath=entry.relative_path) }}">
            {{ entry.name }}
          </a>
        {% else %}
          {{ entry.name }}
        {% endif %}
      </td>
      <td>{{ 'Folder' if entry.is_folder else 'File' }}</td>
      <td>
        <div class="btn-group btn-group-sm">
          {% if not entry.is_folder %}
            <a class="btn btn-success"
               href="{{ url_for('download_file', relative_path=entry.relative_path) }}">
              Download
            </a>
          {% endif %}
          <button class="btn btn-secondary"
                  data-bs-toggle="modal"
                  data-bs-target="#renameModal"
                  data-old="{{ entry.relative_path }}">
            Rename
          </button>
          {% if entry.is_shared %}
            <form action="{{ url_for('unshare_entry') }}" method="post">
              <input type="hidden" name="relative_path" value="{{ entry.relative_path }}">
              <button class="btn btn-warning">Unshare</button>
            </form>
          {% else %}
            <form action="{{ url_for('share_entry') }}" method="post">
              <input type="hidden" name="relative_path" value="{{ entry.relative_path }}">
              <button class="btn btn-info">Share</button>
            </form>
          {% endif %}
          <form action="{{ url_for('delete_entry') }}" method="post">
            <input type="hidden" name="relative_path" value="{{ entry.relative_path }}">
            <button class="btn btn-danger">Delete</button>
          </form>
        </div>
      </td>
    </tr>
  {% endfor %}
  </tbody>
</table>

<div class="row mt-4">
  <div class="col-md-6">
    <h5>Upload File</h5>
    <form action="{{ url_for('upload_file') }}" method="post" enctype="multipart/form-data">
      <input type="hidden" name="current_path" value="{{ current_path }}">
      <div class="input-group">
        <input type="file" name="file" class="form-control" required>
        <button class="btn btn-primary">Upload</button>
      </div>
    </form>
  </div>
  <div class="col-md-6">
    <h5>Create Folder</h5>
    <form action="{{ url_for('make_folder') }}" method="post">
      <input type="hidden" name="current_path" value="{{ current_path }}">
      <div class="input-group">
        <input name="folder_name" class="form-control" placeholder="Folder Name" required>
        <button class="btn btn-primary">Create</button>
      </div>
    </form>
  </div>
</div>

<!-- Rename Modal -->
<div class="modal fade" id="renameModal" tabindex="-1">
  <div class="modal-dialog">
    <form action="{{ url_for('rename_entry') }}" method="post" class="modal-content">
      <div class="modal-header"><h5 class="modal-title">Rename</h5></div>
      <div class="modal-body">
        <input type="hidden" id="oldPath" name="old_relative_path">
        <input name="new_name" class="form-control" placeholder="New Name" required>
      </div>
      <div class="modal-footer">
        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
        <button type="submit" class="btn btn-primary">Save</button>
      </div>
    </form>
  </div>
</div>

<script>
  const renameModal = document.getElementById('renameModal');
  renameModal.addEventListener('show.bs.modal', event => {
    const button = event.relatedTarget;
    document.getElementById('oldPath').value = button.getAttribute('data-old');
  });
</script>
"""

SHARED_TEMPLATE = """
{% block title %}Shared: {{ current_path or '/' }}{% endblock %}
<h4>Shared View: {{ current_path or '/' }}</h4>

<nav aria-label="breadcrumb">
  <ol class="breadcrumb">
    <li class="breadcrumb-item">
      <a href="{{ url_for('shared_browser', token=token) }}">Root</a>
    </li>
    {% if current_path %}
      {% set crumbs = current_path.split('/') %}
      {% for i in range(crumbs|length) %}
      <li class="breadcrumb-item">
        <a href="{{ url_for('shared_browser', token=token,
                  subpath=crumbs[:i+1]|join('/')) }}">
          {{ crumbs[i] }}
        </a>
      </li>
      {% endfor %}
    {% endif %}
  </ol>
</nav>

<table class="table table-bordered">
  <thead><tr><th>Name</th><th>Type</th><th>Action</th></tr></thead>
  <tbody>
    {% for entry in entries %}
      <tr>
        <td>
          {% if entry.is_folder %}
            <a href="{{ url_for('shared_browser', token=token,
                      subpath=entry.subpath) }}">{{ entry.name }}</a>
          {% else %}
            {{ entry.name }}
          {% endif %}
        </td>
        <td>{{ 'Folder' if entry.is_folder else 'File' }}</td>
        <td>
          {% if not entry.is_folder %}
            <a class="btn btn-success btn-sm"
               href="{{ url_for('shared_browser', token=token,
                            subpath=entry.subpath) }}">
              Download
            </a>
          {% endif %}
        </td>
      </tr>
    {% endfor %}
  </tbody>
</table>
"""

# ─── Run ───────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    app.run(debug=True)
