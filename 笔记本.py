import os
import sqlite3
from flask import Flask, g, render_template_string, request, redirect, url_for, flash, session, send_file
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from io import BytesIO

application = Flask(__name__)
application.config['SECRET_KEY'] = 'your-secret-key-here'
DATABASE_FILE = 'users.db'
NOTES_DIRECTORY = 'user_notes'

# Base HTML template with Bootstrap
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
    <a class="navbar-brand" href="{{ url_for('home') }}">Cloud Notepad</a>
    <div class="collapse navbar-collapse">
      <ul class="navbar-nav ms-auto">
      {% if session.get('user_identifier') %}
        <li class="nav-item"><a class="nav-link" href="{{ url_for('list_user_notes') }}">My Notes</a></li>
        <li class="nav-item"><a class="nav-link" href="{{ url_for('logout_user') }}">Logout</a></li>
      {% else %}
        <li class="nav-item"><a class="nav-link" href="{{ url_for('login_user') }}">Login</a></li>
        <li class="nav-item"><a class="nav-link" href="{{ url_for('register_user') }}">Register</a></li>
      {% endif %}
      </ul>
    </div>
  </div>
</nav>
<div class="container">
  {% with messages = get_flashed_messages() %}
    {% if messages %}
      <div class="alert alert-info mt-3">{{ messages[0] }}</div>
    {% endif %}
  {% endwith %}
  {% block content %}{% endblock %}
</div>
</body>
</html>
"""

HOME_TEMPLATE = """
{% extends base %}{% block content %}
<div class="text-center mt-5">
  <h1>Welcome to Cloud Notepad</h1>
  <p class="lead">Register or log in to create, view, edit, and delete your notes.</p>
  <a class="btn btn-primary" href="{{ url_for('register_user') }}">Register</a>
  <a class="btn btn-secondary" href="{{ url_for('login_user') }}">Login</a>
</div>
{% endblock %}
"""

AUTHENTICATION_TEMPLATE = """
{% extends base %}{% block content %}
<div class="row justify-content-center">
  <div class="col-md-6">
    <h2 class="mb-3">{{ page_title }}</h2>
    <form method="post">
      <div class="mb-3">
        <label class="form-label">Username</label>
        <input name="username" class="form-control" required maxlength="64" value="{{ request.form.username }}">
      </div>
      <div class="mb-3">
        <label class="form-label">Email</label>
        <input name="email_address" type="email" class="form-control" required value="{{ request.form.email_address }}">
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

LIST_TEMPLATE = """
{% extends base %}{% block content %}
<div class="d-flex justify-content-between mt-3">
  <h2>My Notes</h2>
  <a class="btn btn-success" href="{{ url_for('create_new_note') }}">+ New Note</a>
</div>
<hr>
{% if notes_list %}
  <div class="list-group">
  {% for note_filename in notes_list %}
    <div class="list-group-item d-flex justify-content-between align-items-center">
      <div>
        <a href="{{ url_for('view_note_file', filename=note_filename) }}">{{ note_filename }}</a>
      </div>
      <div>
        <a href="{{ url_for('edit_existing_note', filename=note_filename) }}" class="btn btn-sm btn-outline-primary">Edit</a>
        <a href="{{ url_for('delete_note_file', filename=note_filename) }}" class="btn btn-sm btn-outline-danger">Delete</a>
      </div>
    </div>
  {% endfor %}
  </div>
{% else %}
  <p class="mt-3">No notes found.</p>
{% endif %}
{% endblock %}
"""

EDIT_TEMPLATE = """
{% extends base %}{% block content %}
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

def get_database_connection():
    if 'database_connection' not in g:
        database_connection = sqlite3.connect(DATABASE_FILE)
        database_connection.execute("""
            CREATE TABLE IF NOT EXISTS user_account (
                id INTEGER PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                email_address TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL
            )
        """)
        database_connection.commit()
        g.database_connection = database_connection
    return g.database_connection

@application.teardown_appcontext
def close_database_connection(error=None):
    database_connection = g.pop('database_connection', None)
    if database_connection:
        database_connection.close()

def authentication_required(view_function):
    @wraps(view_function)
    def wrapped_view_function(*args, **kwargs):
        if not session.get('user_identifier'):
            return redirect(url_for('login_user'))
        return view_function(*args, **kwargs)
    return wrapped_view_function

@application.route('/')
def home():
    return render_template_string(HOME_TEMPLATE, base=BASE_TEMPLATE)

@application.route('/register', methods=['GET', 'POST'])
def register_user():
    if request.method == 'POST':
        username_value = request.form['username'].strip()
        email_value = request.form['email_address'].strip()
        password_value = request.form['password']
        confirm_password_value = request.form['confirm_password']
        if password_value != confirm_password_value:
            flash('Passwords do not match.')
        else:
            connection = get_database_connection()
            try:
                connection.execute(
                    "INSERT INTO user_account(username, email_address, password_hash) VALUES (?, ?, ?)",
                    (username_value, email_value, generate_password_hash(password_value))
                )
                connection.commit()
                os.makedirs(os.path.join(NOTES_DIRECTORY, username_value), exist_ok=True)
                flash('Registration successful. Please log in.')
                return redirect(url_for('login_user'))
            except sqlite3.IntegrityError:
                flash('Username or email already exists.')
    return render_template_string(AUTHENTICATION_TEMPLATE,
                                  page_title="Register",
                                  is_registration=True,
                                  base=BASE_TEMPLATE)

@application.route('/login', methods=['GET', 'POST'])
def login_user():
    if request.method == 'POST':
        email_value = request.form['email_address'].strip()
        password_value = request.form['password']
        user_row = get_database_connection().execute(
            "SELECT id, username, password_hash FROM user_account WHERE email_address = ?",
            (email_value,)
        ).fetchone()
        if user_row and check_password_hash(user_row[2], password_value):
            session.clear()
            session['user_identifier'] = user_row[0]
            session['username'] = user_row[1]
            return redirect(url_for('list_user_notes'))
        flash('Invalid email or password.')
    return render_template_string(AUTHENTICATION_TEMPLATE,
                                  page_title="Login",
                                  is_registration=False,
                                  base=BASE_TEMPLATE)

@application.route('/logout')
def logout_user():
    session.clear()
    flash('Logged out.')
    return redirect(url_for('home'))

@application.route('/notes')
@authentication_required
def list_user_notes():
    username_value = session['username']
    user_folder_path = os.path.join(NOTES_DIRECTORY, username_value)
    os.makedirs(user_folder_path, exist_ok=True)
    notes_list = sorted(os.listdir(user_folder_path))
    return render_template_string(LIST_TEMPLATE,
                                  notes_list=notes_list,
                                  base=BASE_TEMPLATE)

@application.route('/notes/new', methods=['GET', 'POST'])
@authentication_required
def create_new_note():
    if request.method == 'POST':
        filename_value = request.form['filename'].strip()
        if not filename_value.lower().endswith('.txt'):
            filename_value += '.txt'
        note_content_value = request.form['note_content']
        username_value = session['username']
        file_path = os.path.join(NOTES_DIRECTORY, username_value, filename_value)
        if os.path.exists(file_path):
            flash('File already exists.')
        else:
            with open(file_path, 'w', encoding='utf-16') as file_handle:
                file_handle.write(note_content_value)
            flash('Note created.')
            return redirect(url_for('list_user_notes'))
    return render_template_string(EDIT_TEMPLATE,
                                  filename=None,
                                  note_content=None,
                                  base=BASE_TEMPLATE)

@application.route('/notes/<filename>/edit', methods=['GET', 'POST'])
@authentication_required
def edit_existing_note(filename):
    username_value = session['username']
    file_path = os.path.join(NOTES_DIRECTORY, username_value, filename)
    if not os.path.isfile(file_path):
        flash('File not found.')
        return redirect(url_for('list_user_notes'))
    if request.method == 'POST':
        note_content_value = request.form['note_content']
        with open(file_path, 'w', encoding='utf-16') as file_handle:
            file_handle.write(note_content_value)
        flash('Note saved.')
        return redirect(url_for('list_user_notes'))
    with open(file_path, 'r', encoding='utf-16') as file_handle:
        note_content_value = file_handle.read()
    return render_template_string(EDIT_TEMPLATE,
                                  filename=filename,
                                  note_content=note_content_value,
                                  base=BASE_TEMPLATE)

@application.route('/notes/<filename>')
@authentication_required
def view_note_file(filename):
    username_value = session['username']
    file_path = os.path.join(NOTES_DIRECTORY, username_value, filename)
    if not os.path.isfile(file_path):
        flash('File not found.')
        return redirect(url_for('list_user_notes'))
    file_data = open(file_path, 'rb').read()
    return send_file(BytesIO(file_data),
                     mimetype='text/plain; charset=utf-16',
                     download_name=filename)

@application.route('/notes/<filename>/delete')
@authentication_required
def delete_note_file(filename):
    username_value = session['username']
    file_path = os.path.join(NOTES_DIRECTORY, username_value, filename)
    if os.path.isfile(file_path):
        os.remove(file_path)
        flash('Note deleted.')
    else:
        flash('File not found.')
    return redirect(url_for('list_user_notes'))

if __name__ == '__main__':
    os.makedirs(NOTES_DIRECTORY, exist_ok=True)
    application.run(debug=True)
