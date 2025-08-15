import os
import uuid
import sqlite3
from flask import Flask, g, request, redirect, url_for, render_template_string, \
                  send_from_directory, abort, flash
from flask_login import LoginManager, UserMixin, login_user, logout_user, \
                        login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

# --- App Configuration ---
app = Flask(__name__)
app.config.update(
    SECRET_KEY          = 'replace-with-a-secure-key',            # 用于会话安全
    DATABASE            = os.path.join(app.root_path, 'app.db'), # SQLite 数据库文件
    UPLOAD_FOLDER       = os.path.join(app.root_path, 'uploads'),# 存放上传图片目录
    MAX_CONTENT_LENGTH  = 5 * 1024 * 1024,                       # 限制单文件最大 5MB
    ALLOWED_EXTENSIONS  = {'png', 'jpg', 'jpeg', 'gif'}          # 允许的图片格式
)
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)          # 确保上传目录存在

# --- Login Manager Setup ---
login_manager = LoginManager(app)
login_manager.login_view = 'login'

class User(UserMixin):
    """Flask-Login 的用户模型"""
    def __init__(self, user_id, username, password_hash):
        self.id = user_id
        self.username = username
        self.password_hash = password_hash

    def check_password(self, password):
        """验证明文密码与哈希是否匹配"""
        return check_password_hash(self.password_hash, password)

@login_manager.user_loader
def load_user_by_id(user_id):
    """根据用户 ID 加载用户对象"""
    row = query_database(
        'SELECT id, username, password_hash FROM users WHERE id=?',
        [user_id],
        one=True
    )
    return User(*row) if row else None

# --- Database Helpers ---
def get_database():
    """打开（或复用）数据库连接，并设置行为为 Row"""
    if 'database' not in g:
        conn = sqlite3.connect(app.config['DATABASE'])
        conn.row_factory = sqlite3.Row
        g.database = conn
    return g.database

@app.teardown_appcontext
def close_database(exception):
    """请求结束时关闭数据库连接"""
    db_conn = g.pop('database', None)
    if db_conn:
        db_conn.close()

def initialize_database():
    """创建 users 和 images 表（如果尚未存在）"""
    db = get_database()
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

def query_database(sql, params=(), one=False):
    """执行 SELECT 查询，返回所有或单条记录"""
    cursor = get_database().execute(sql, params)
    rows = cursor.fetchall()
    cursor.close()
    return (rows[0] if rows else None) if one else rows

def execute_database(sql, params=()):
    """执行 INSERT/UPDATE/DELETE，并返回 lastrowid"""
    db = get_database()
    cursor = db.execute(sql, params)
    db.commit()
    return cursor.lastrowid

# --- File Handling Helpers ---
def is_allowed_file(filename):
    """检查文件扩展名是否在允许列表中"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def save_uploaded_file(file_storage):
    """保存上传文件，生成唯一文件名，返回保存后的名称"""
    original_name = secure_filename(file_storage.filename)
    if not is_allowed_file(original_name):
        flash('Unsupported file type', 'danger')
        return None
    unique_name = f"{uuid.uuid4().hex}_{original_name}"
    dest_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_name)
    file_storage.save(dest_path)
    return unique_name

def remove_uploaded_file(filename):
    """从磁盘删除指定文件（如果存在）"""
    path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    if os.path.exists(path):
        os.remove(path)

# --- Templates (flat, no nesting) ---
base_template = """
<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>{{ title }}</title>
<link href="https://cdn.jsdelivr.net/npm/bootswatch@5.3.2/dist/minty/bootstrap.min.css" rel="stylesheet">
<style>.gallery-img{cursor:pointer;transition:transform .2s;} .gallery-img:hover{transform:scale(1.05);}</style>
</head><body>
<nav class="navbar navbar-expand-lg navbar-dark bg-primary">
  <div class="container-fluid">
    <a class="navbar-brand" href="{{ url_for('manage_images') }}">GalleryApp</a>
    <div>
      {% if current_user.is_authenticated %}
        <a class="nav-link d-inline" href="{{ url_for('manage_images') }}">Manage</a>
        <a class="nav-link d-inline" href="{{ url_for('view_gallery') }}">Gallery</a>
        <a class="nav-link d-inline" href="{{ url_for('search_users') }}">Search</a>
        <a class="nav-link d-inline" href="{{ url_for('logout') }}">Logout</a>
      {% else %}
        <a class="nav-link d-inline" href="{{ url_for('login') }}">Login</a>
        <a class="nav-link d-inline" href="{{ url_for('register') }}">Register</a>
      {% endif %}
    </div>
  </div>
</nav>
<main class="container mt-4">
  {% with messages = get_flashed_messages(with_categories=true) %}
    {% for category, message in messages %}
      <div class="alert alert-{{ category }}">{{ message }}</div>
    {% endfor %}
  {% endwith %}
  {{ body }}
</main>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
</body></html>
"""

# --- Route: Register ---
register_form = """
<h2>Register</h2>
<form method="post">
  <div class="mb-3">
    <label>Username</label>
    <input name="username" class="form-control" required>
  </div>
  <div class="mb-3">
    <label>Password</label>
    <input type="password" name="password" class="form-control" required>
  </div>
  <button class="btn btn-success">Submit</button>
</form>
"""

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        # 检查用户名是否已存在
        if query_database('SELECT 1 FROM users WHERE username=?', [username], one=True):
            flash('Username already exists', 'warning')
            return redirect(url_for('register'))

        # 插入新用户并提示
        password_hash = generate_password_hash(password)
        execute_database(
            'INSERT INTO users(username, password_hash) VALUES(?, ?)',
            [username, password_hash]
        )
        flash('Registration successful, please log in', 'success')
        return redirect(url_for('login'))

    # GET 请求：渲染注册表单
    body = register_form
    return render_template_string(base_template, title='Register', body=body)

# --- Route: Login ---
login_form = """
<h2>Login</h2>
<form method="post">
  <div class="mb-3">
    <label>Username</label>
    <input name="username" class="form-control" required>
  </div>
  <div class="mb-3">
    <label>Password</label>
    <input type="password" name="password" class="form-control" required>
  </div>
  <button class="btn btn-primary">Login</button>
</form>
"""

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        # 获取用户记录
        row = query_database(
            'SELECT id, username, password_hash FROM users WHERE username=?',
            [username],
            one=True
        )
        if row and User(*row).check_password(password):
            login_user(User(*row))
            return redirect(url_for('manage_images'))
        flash('Invalid username or password', 'danger')
        return redirect(url_for('login'))

    body = login_form
    return render_template_string(base_template, title='Login', body=body)

# --- Route: Logout ---
@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# --- Route: Manage Images (Upload/Delete + Pagination) ---
manage_body = """
<h2>Upload New Image</h2>
<form method="post" enctype="multipart/form-data">
  <input type="file" name="file" accept="image/*" class="form-control">
  <button class="btn btn-success mt-2">Upload</button>
</form>
<hr>
<div class="row">
  {% for img in images %}
    <div class="col-sm-4 text-center mb-3">
      <img src="{{ url_for('uploaded_file', filename=img.filename) }}"
           class="img-fluid rounded gallery-img">
      <p class="small text-muted">{{ img.upload_time }}</p>
      <form method="post" action="{{ url_for('delete_image', image_id=img.id) }}">
        <button class="btn btn-sm btn-danger">Delete</button>
      </form>
    </div>
  {% endfor %}
  {% if not images %}
    <p>No images uploaded yet.</p>
  {% endif %}
</div>
<nav><ul class="pagination">
  {% for p in range(1, total_pages+1) %}
    <li class="page-item {% if p==current_page %}active{% endif %}">
      <a class="page-link" href="?page={{ p }}">{{ p }}</a>
    </li>
  {% endfor %}
</ul></nav>
"""

@app.route('/manage', methods=['GET', 'POST'])
@login_required
def manage_images():
    if request.method == 'POST':
        upload_file = request.files.get('file')
        if not upload_file or upload_file.filename == '':
            flash('Please select a file', 'warning')
            return redirect(url_for('manage_images'))

        saved_name = save_uploaded_file(upload_file)
        if saved_name:
            execute_database(
                'INSERT INTO images(user_id, filename) VALUES(?, ?)',
                [current_user.id, saved_name]
            )
            flash('Upload successful', 'success')
        return redirect(url_for('manage_images'))

    # 分页逻辑
    page = int(request.args.get('page', 1))
    per_page = 9
    all_images = query_database(
        'SELECT id, filename, upload_time FROM images '
        'WHERE user_id=? ORDER BY upload_time DESC',
        [current_user.id]
    )
    total_images = len(all_images)
    total_pages = (total_images + per_page - 1) // per_page
    images = all_images[(page-1)*per_page : page*per_page]

    body = render_template_string(
        manage_body,
        images=images,
        current_page=page,
        total_pages=total_pages
    )
    return render_template_string(base_template, title='Manage Images', body=body)

# --- Route: Delete Image ---
@app.route('/delete/<int:image_id>', methods=['POST'])
@login_required
def delete_image(image_id):
    # 检查图片是否属于当前用户
    record = query_database(
        'SELECT user_id, filename FROM images WHERE id=?',
        [image_id],
        one=True
    )
    if not record or record['user_id'] != current_user.id:
        abort(403)

    remove_uploaded_file(record['filename'])
    execute_database('DELETE FROM images WHERE id=?', [image_id])
    flash('Image deleted', 'info')
    return redirect(url_for('manage_images'))

# --- Route: Gallery (Fullscreen Lightbox) ---
gallery_body = """
<h2>Fullscreen Gallery</h2>
<div class="row">
  {% for img in images %}
    <div class="col-sm-3 mb-3">
      <img src="{{ url_for('uploaded_file', filename=img.filename) }}"
           class="img-fluid rounded gallery-img" data-index="{{ loop.index0 }}">
    </div>
  {% endfor %}
</div>
<!-- Lightbox Modal -->
<div class="modal fade" id="lightboxModal" tabindex="-1">
  <div class="modal-dialog modal-fullscreen">
    <div class="modal-content bg-dark">
      <div class="modal-body d-flex align-items-center justify-content-center">
        <button class="btn btn-outline-light me-auto" id="prevBtn">&laquo;</button>
        <img id="modalImg" class="img-fluid">
        <button class="btn btn-outline-light ms-auto" id="nextBtn">&raquo;</button>
      </div>
    </div>
  </div>
</div>
<script>
  const galleryImages = {{ images|tojson }};
  let currentIndex = 0;
  const modal = new bootstrap.Modal(document.getElementById('lightboxModal'));
  const modalImg = document.getElementById('modalImg');

  document.querySelectorAll('.gallery-img').forEach(el => {
    el.addEventListener('click', () => {
      currentIndex = +el.dataset.index;
      modalImg.src = '/uploads/' + galleryImages[currentIndex].filename;
      modal.show();
    });
  });
  document.getElementById('prevBtn').onclick = () => {
    currentIndex = (currentIndex - 1 + galleryImages.length) % galleryImages.length;
    modalImg.src = '/uploads/' + galleryImages[currentIndex].filename;
  };
  document.getElementById('nextBtn').onclick = () => {
    currentIndex = (currentIndex + 1) % galleryImages.length;
    modalImg.src = '/uploads/' + galleryImages[currentIndex].filename;
  };
</script>
"""

@app.route('/gallery')
@login_required
def view_gallery():
    images = query_database(
        'SELECT filename FROM images WHERE user_id=? ORDER BY upload_time DESC',
        [current_user.id]
    )
    body = render_template_string(gallery_body, images=images)
    return render_template_string(base_template, title='Gallery', body=body)

# --- Route: Search Users ---
search_body = """
<h2>Search Users</h2>
<form method="get" class="mb-3">
  <div class="input-group">
    <input name="q" class="form-control" placeholder="Enter username"
           value="{{ request.args.get('q','') }}">
    <button class="btn btn-primary">Search</button>
  </div>
</form>
{% if found_users is not none %}
  {% if found_users %}
    <ul class="list-group">
    {% for user in found_users %}
      <li class="list-group-item">
        <a href="{{ url_for('view_profile', username=user.username) }}">
          <b>{{ user.username }}</b>
        </a>
      </li>
    {% endfor %}
    </ul>
  {% else %}
    <p>No matching users.</p>
  {% endif %}
{% endif %}
"""

@app.route('/search')
@login_required
def search_users():
    search_query = request.args.get('q', '').strip()
    found_users = None
    if search_query:
        found_users = query_database(
            'SELECT username FROM users WHERE username LIKE ? COLLATE NOCASE',
            [f'%{search_query}%']
        )
    body = render_template_string(search_body, found_users=found_users)
    return render_template_string(base_template, title='Search Users', body=body)

# --- Route: User Profile ---
profile_body = """
<h2>{{ user.username }}'s Album</h2>
<div class="row">
  {% for img in user_images %}
    <div class="col-sm-3 mb-3">
      <img src="{{ url_for('uploaded_file', filename=img.filename) }}"
           class="img-fluid rounded">
      <p class="small text-muted">{{ img.upload_time }}</p>
    </div>
  {% endfor %}
  {% if not user_images %}
    <p>No images uploaded yet.</p>
  {% endif %}
</div>
"""

@app.route('/user/<username>')
@login_required
def view_profile(username):
    # 获取用户
    user_row = query_database(
        'SELECT id, username FROM users WHERE username=?',
        [username],
        one=True
    )
    if not user_row:
        abort(404)

    # 获取该用户所有图片
    user_images = query_database(
        'SELECT filename, upload_time FROM images '
        'WHERE user_id=? ORDER BY upload_time DESC',
        [user_row['id']]
    )
    body = render_template_string(profile_body, user=user_row, user_images=user_images)
    return render_template_string(base_template, title=f"{username}'s Album", body=body)

# --- Route: Serve Uploaded Files ---
@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# --- Custom Error Handlers ---
error_403 = """
<h2>403 Forbidden</h2>
<p>You do not have permission to access this resource.</p>
"""

@app.errorhandler(403)
def forbidden(error):
    return render_template_string(base_template, title='403 Forbidden', body=error_403), 403

error_404 = """
<h2>404 Not Found</h2>
<p>The requested page does not exist.</p>
"""

@app.errorhandler(404)
def page_not_found(error):
    return render_template_string(base_template, title='404 Not Found', body=error_404), 404

# --- App Startup ---
if __name__ == '__main__':
    initialize_database()
    app.run(debug=True)
