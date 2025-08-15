import os
import re
import sqlite3
from functools import wraps
from io import BytesIO

from flask import (
    Flask,
    g,
    render_template_string,
    request,
    redirect,
    url_for,
    flash,
    session,
    send_file
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

# ----------------------------
# Configuration
# ----------------------------

APPLICATION = Flask(__name__)
APPLICATION.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'your-very-secure-secret-key')

DATABASE_FILE_PATH = 'users_database.sqlite3'
USER_NOTES_ROOT_DIRECTORY = 'user_notes'

# ----------------------------
# HTML Templates (Bootstrap 5)
# ----------------------------

BASE_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Cloud Notepad</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    body { padding-top: 70px; }
    textarea { height: 300px; }
  </style>
</head>
<body>
<nav class="navbar navbar-expand-lg navbar-dark bg-primary fixed-top">
  <div class="container-fluid">
    <a class="navbar-brand" href="{{ url_for('home_page') }}">Cloud Notepad</a>
    <div class="collapse navbar-collapse">
      <ul class="navbar-nav ms-auto">
      {% if session.get('user_identifier') %}
        <li class="nav-item"><a class="nav-link" href="{{ url_for('list_notes_page') }}">My Notes</a></li>
        <li class="nav-item"><a class="nav-link" href="{{ url_for('logout_page') }}">Logout</a></li>
      {% else %}
        <li class="nav-item"><a class="nav-link" href="{{ url_for('login_page') }}">Login</a></li>
        <li class="nav-item"><a class="nav-link" href="{{ url_for('register_page') }}">Register</a></li>
      {% endif %}
      </ul>
    </div>
  </div>
</nav>
<div class="container">
  {% with messages = get_flashed_messages(with_categories=true) %}
    {% if messages %}
      {% for category, message in messages %}
        <div class="alert alert-{{ category }} mt-3">{{ message }}</div>
      {% endfor %}
    {% endif %}
  {% endwith %}
  {% block content %}{% endblock %}
</div>
</body>
</html>
"""

HOME_TEMPLATE = """
{% extends base_template %} 
{% block content %}
<div class="text-center mt-5">
  <h1>Welcome to Cloud Notepad</h1>
  <p class="lead">Register or log in to create, view, edit, and delete your notes.</p>
  <a class="btn btn-primary me-2" href="{{ url_for('register_page') }}">Register</a>
  <a class="btn btn-secondary" href="{{ url_for('login_page') }}">Login</a>
</div>
{% endblock %}
"""

AUTHENTICATION_TEMPLATE = """
{% extends base_template %} 
{% block content %}
<div class="row justify-content-center">
  <div class="col-md-6">
    <h2 class="mb-3">{{ page_title }}</h2>
    <form method="post">
      <div class="mb-3">
        <label class="form-label">Username</label>
        <input name="username" class="form-control" required maxlength="64" value="{{ request.form.get('username', '') }}">
      </div>
      <div class="mb-3">
        <label class="form-label">Email Address</label>
        <input name="email_address" type="email" class="form-control" required maxlength="128" value="{{ request.form.get('email_address', '') }}">
      </div>
      <div class="mb-3">
        <label class="form-label">Password</label>
        <input name="password" type="password" class="form-control" required>
      </div>
      {% if is_registration %}
      <div class="mb-3">
        <label class="form-label">Confirm Password</label>
        <input name="confirm_password" type="password" class="form-control" required>
      </div>
      {% endif %}
      <button class="btn btn-primary">{{ page_title }}</button>
    </form>
  </div>
</div>
{% endblock %}
"""

NOTES_LIST_TEMPLATE = """
{% extends base_template %} 
{% block content %}
<div class="d-flex justify-content-between align-items-center mt-3">
  <h2>My Notes</h2>
  <a class="btn btn-success" href="{{ url_for('create_note_page') }}">+ New Note</a>
</div>
<hr>
{% if notes_list %}
  <div class="list-group">
  {% for note_filename in notes_list %}
    <div class="list-group-item d-flex justify-content-between align-items-center">
      <div>
        <a href="{{ url_for('view_note_page', filename=note_filename) }}">{{ note_filename }}</a>
      </div>
      <div>
        <a href="{{ url_for('edit_note_page', filename=note_filename) }}" class="btn btn-sm btn-outline-primary">Edit</a>
        <form method="post" action="{{ url_for('delete_note_page', filename=note_filename) }}" style="display:inline;">
          <button type="submit" class="btn btn-sm btn-outline-danger" onclick="return confirm('Are you sure you want to delete this note?');">Delete</button>
        </form>
      </div>
    </div>
  {% endfor %}
  </div>
{% else %}
  <p class="mt-3">No notes found.</p>
{% endif %}
{% endblock %}
"""

NOTE_EDIT_TEMPLATE = """
{% extends base_template %}
{% block content %}
<nav aria-label="breadcrumb" class="mt-3">
  <ol class="breadcrumb">
    <li class="breadcrumb-item"><a href="{{ url_for('list_notes_page') }}">My Notes</a></li>
    <li class="breadcrumb-item active" aria-current="page">{{ 'Edit' if filename else 'New' }} Note</li>
  </ol>
</nav>
<div class="mt-3">
  <h2>{{ 'Edit' if filename else 'New' }} Note</h2>
  <form method="post">
    <div class="mb-3">
      <label class="form-label">Filename</label>
      <input name="filename" class="form-control" required maxlength="100" value="{{ filename or '' }}" {% if filename %}readonly{% endif %}>
    </div>
    <div class="mb-3">
      <label class="form-label">Content</label>
      <textarea name="note_content" class="form-control" required>{{ note_content or '' }}</textarea>
    </div>
    <button class="btn btn-primary">Save</button>
  </form>
</div>
{% endblock %}
"""

# ----------------------------
# Utility Functions
# ----------------------------

def initialize_database():
    """Create the user_account table if it does not already exist."""
    with sqlite3.connect(DATABASE_FILE_PATH) as database_connection:
        database_connection.execute("""
            CREATE TABLE IF NOT EXISTS user_account (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                email_address TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL
            );
        """)
        database_connection.commit()


def get_database_connection():
    """Get a SQLite connection stored in flask.g, with row factory."""
    if 'database_connection' not in g:
        connection = sqlite3.connect(DATABASE_FILE_PATH)
        connection.row_factory = sqlite3.Row
        g.database_connection = connection
    return g.database_connection


@APPLICATION.teardown_appcontext
def close_database_connection(error=None):
    """Close the SQLite connection at the end of the request."""
    database_connection = g.pop('database_connection', None)
    if database_connection is not None:
        database_connection.close()


def login_required(view_function):
    """Decorator to require login for protected views."""
    @wraps(view_function)
    def wrapped_function(*arguments, **keyword_arguments):
        if 'user_identifier' not in session:
            return redirect(url_for('login_page'))
        return view_function(*arguments, **keyword_arguments)
    return wrapped_function


def detect_chinese_characters(text):
    """Return True if text contains any Chinese character."""
    return bool(re.search('[\u4e00-\u9fff]', text))


def secure_user_folder(username):
    """Return the secure folder path for a given username, creating if needed."""
    folder_name = secure_filename(username)
    folder_path = os.path.join(USER_NOTES_ROOT_DIRECTORY, folder_name)
    os.makedirs(folder_path, exist_ok=True)
    return folder_path


def list_notes_for_user(username):
    """Return sorted list of filenames in the user’s notes folder."""
    user_folder = secure_user_folder(username)
    return sorted(os.listdir(user_folder))


def read_note_file(username, filename):
    """Read and return the content of a note, or None if not found."""
    secure_name = secure_filename(filename)
    file_path = os.path.join(secure_user_folder(username), secure_name)
    if not os.path.isfile(file_path):
        return None
    # Always open in binary to detect encoding if needed
    raw_data = open(file_path, 'rb').read()
    try:
        # Try UTF-16 first
        return raw_data.decode('utf-16')
    except UnicodeError:
        # Fallback to UTF-8
        return raw_data.decode('utf-8')


def write_note_file(username, filename, content, overwrite=False):
    """Write content to a note. Return True on success, False on conflict/not found."""
    secure_name = secure_filename(filename)
    if not secure_name.lower().endswith('.txt'):
        secure_name += '.txt'
    file_path = os.path.join(secure_user_folder(username), secure_name)
    if os.path.exists(file_path) and not overwrite:
        return False
    # Choose encoding: UTF-16 if Chinese, else UTF-8
    chosen_encoding = 'utf-16' if detect_chinese_characters(content) else 'utf-8'
    with open(file_path, 'w', encoding=chosen_encoding) as file_handle:
        file_handle.write(content)
    return True


def delete_note_file_for_user(username, filename):
    """Delete a note file if it exists. Return True if deleted, else False."""
    secure_name = secure_filename(filename)
    file_path = os.path.join(secure_user_folder(username), secure_name)
    if os.path.isfile(file_path):
        os.remove(file_path)
        return True
    return False


def create_user_account(username, email_address, password):
    """Insert a new user into the database. Return True on success, False on duplication."""
    password_hash = generate_password_hash(password)
    connection = get_database_connection()
    try:
        connection.execute(
            "INSERT INTO user_account (username, email_address, password_hash) VALUES (?, ?, ?);",
            (username, email_address, password_hash)
        )
        connection.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def authenticate_user_credentials(email_address, password):
    """Check credentials; return user dict on success, None on failure."""
    connection = get_database_connection()
    row = connection.execute(
        "SELECT id, username, password_hash FROM user_account WHERE email_address = ?;",
        (email_address,)
    ).fetchone()
    if row and check_password_hash(row['password_hash'], password):
        return {'id': row['id'], 'username': row['username']}
    return None


# ----------------------------
# Flask Routes
# ----------------------------

@APPLICATION.route('/')
def home_page():
    return render_template_string(HOME_TEMPLATE, base_template=BASE_TEMPLATE)


@APPLICATION.route('/register', methods=['GET', 'POST'])
def register_page():
    if request.method == 'POST':
        form_username = request.form['username'].strip()
        form_email = request.form['email_address'].strip()
        form_password = request.form['password']
        form_confirm_password = request.form['confirm_password']
        if form_password != form_confirm_password:
            flash('Passwords do not match.', 'warning')
        else:
            if create_user_account(form_username, form_email, form_password):
                # Create empty notes folder for new user
                secure_user_folder(form_username)
                flash('Registration successful. Please log in.', 'success')
                return redirect(url_for('login_page'))
            else:
                flash('Username or email address already exists.', 'danger')
    return render_template_string(
        AUTHENTICATION_TEMPLATE,
        base_template=BASE_TEMPLATE,
        page_title='Register',
        is_registration=True
    )


@APPLICATION.route('/login', methods=['GET', 'POST'])
def login_page():
    if request.method == 'POST':
        form_email = request.form['email_address'].strip()
        form_password = request.form['password']
        user_record = authenticate_user_credentials(form_email, form_password)
        if user_record:
            session.clear()
            session['user_identifier'] = user_record['id']
            session['username'] = user_record['username']
            return redirect(url_for('list_notes_page'))
        flash('Invalid email address or password.', 'danger')
    return render_template_string(
        AUTHENTICATION_TEMPLATE,
        base_template=BASE_TEMPLATE,
        page_title='Login',
        is_registration=False
    )


@APPLICATION.route('/logout')
def logout_page():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('home_page'))


@APPLICATION.route('/notes')
@login_required
def list_notes_page():
    username = session['username']
    notes_list = list_notes_for_user(username)
    return render_template_string(
        NOTES_LIST_TEMPLATE,
        base_template=BASE_TEMPLATE,
        notes_list=notes_list
    )


@APPLICATION.route('/notes/new', methods=['GET', 'POST'])
@login_required
def create_note_page():
    if request.method == 'POST':
        form_filename = request.form['filename'].strip()
        form_content = request.form['note_content']
        if write_note_file(session['username'], form_filename, form_content, overwrite=False):
            flash('Note created successfully.', 'success')
            return redirect(url_for('list_notes_page'))
        flash('A note with that filename already exists.', 'danger')
    return render_template_string(
        NOTE_EDIT_TEMPLATE,
        base_template=BASE_TEMPLATE,
        filename=None,
        note_content=''
    )


@APPLICATION.route('/notes/<filename>/edit', methods=['GET', 'POST'])
@login_required
def edit_note_page(filename):
    username = session['username']
    if request.method == 'POST':
        form_content = request.form['note_content']
        if write_note_file(username, filename, form_content, overwrite=True):
            flash('Note updated successfully.', 'success')
            return redirect(url_for('list_notes_page'))
        flash('Failed to update note.', 'danger')
    existing_content = read_note_file(username, filename) or ''
    return render_template_string(
        NOTE_EDIT_TEMPLATE,
        base_template=BASE_TEMPLATE,
        filename=filename,
        note_content=existing_content
    )


@APPLICATION.route('/notes/<filename>/delete', methods=['POST'])
@login_required
def delete_note_page(filename):
    if delete_note_file_for_user(session['username'], filename):
        flash('Note deleted successfully.', 'success')
    else:
        flash('Note not found.', 'warning')
    return redirect(url_for('list_notes_page'))


@APPLICATION.route('/notes/<filename>/view')
@login_required
def view_note_page(filename):
    note_text = read_note_file(session['username'], filename)
    if note_text is None:
        flash('Note not found.', 'warning')
        return redirect(url_for('list_notes_page'))
    # Prepare file bytes for download
    # Use UTF-16 if Chinese, else UTF-8
    encoding_for_download = 'utf-16' if detect_chinese_characters(note_text) else 'utf-8'
    note_bytes = note_text.encode(encoding_for_download)
    return send_file(
        BytesIO(note_bytes),
        mimetype=f'text/plain; charset={encoding_for_download}',
        as_attachment=True,
        download_name=filename
    )


# ----------------------------
# Application Entry Point
# ----------------------------

if __name__ == '__main__':
    os.makedirs(USER_NOTES_ROOT_DIRECTORY, exist_ok=True)
    initialize_database()
    APPLICATION.run(debug=True)
