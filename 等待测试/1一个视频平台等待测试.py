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
    app.run(debug=True)
