import os
import sqlite3
from flask import Flask, request, redirect, url_for, flash, send_from_directory, render_template
from jinja2 import DictLoader

app = Flask(__name__)
app.secret_key = 'replace-with-your-secret-key'

# 配置
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
DATABASE = os.path.join(BASE_DIR, 'videos.db')
ALLOWED_EXTENSIONS = {'mp4', 'mov', 'avi'}
MAX_CONTENT_LENGTH = 200 * 1024 * 1024  # 200 MB

app.config.update(
    UPLOAD_FOLDER=UPLOAD_FOLDER,
    MAX_CONTENT_LENGTH=MAX_CONTENT_LENGTH
)

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# 初始化 SQLite 数据库
def init_db():
    conn = sqlite3.connect(DATABASE)
    conn.execute('''
      CREATE TABLE IF NOT EXISTS video (
        id       INTEGER PRIMARY KEY AUTOINCREMENT,
        filename TEXT NOT NULL,
        creator  TEXT NOT NULL
      )
    ''')
    conn.commit()
    conn.close()

init_db()

def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# 模板字符串
templates = {
  'base.html': '''
<!DOCTYPE html>
<html lang="zh">
<head>
  <meta charset="UTF-8">
  <title>VideoShare</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.1/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body class="bg-light">
  <nav class="navbar navbar-expand-lg navbar-dark bg-dark mb-4">
    <div class="container-fluid">
      <a class="navbar-brand" href="{{ url_for('index') }}">VideoShare</a>
      <div class="collapse navbar-collapse">
        <ul class="navbar-nav ms-auto">
          <li class="nav-item"><a class="nav-link" href="{{ url_for('upload') }}">上传</a></li>
          <li class="nav-item"><a class="nav-link" href="{{ url_for('search') }}">搜索</a></li>
        </ul>
      </div>
    </div>
  </nav>
  <div class="container">
    {% with messages = get_flashed_messages(with_categories=true) %}
      {% if messages %}
        {% for category, msg in messages %}
          <div class="alert alert-{{ category }} alert-dismissible fade show" role="alert">
            {{ msg }}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
          </div>
        {% endfor %}
      {% endif %}
    {% endwith %}
    {% block content %}{% endblock %}
  </div>
  <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.1/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
''',

  'index.html': '''
{% extends 'base.html' %}
{% block content %}
<h2 class="mb-4">最新视频</h2>
<div class="row">
  {% for v in videos %}
    <div class="col-md-4 mb-3">
      <div class="card h-100">
        <video class="card-img-top" controls>
          <source src="{{ url_for('uploaded_file', filename=v.filename) }}">
        </video>
        <div class="card-body">
          <h5 class="card-title">{{ v.creator }}</h5>
          <a href="{{ url_for('creator', creator_name=v.creator) }}" class="btn btn-sm btn-primary">查看主页</a>
        </div>
      </div>
    </div>
  {% else %}
    <p>目前还没有视频。</p>
  {% endfor %}
</div>
{% endblock %}
''',

  'upload.html': '''
{% extends 'base.html' %}
{% block content %}
<h2 class="mb-4">上传新视频</h2>
<form method="post" enctype="multipart/form-data" class="row g-3">
  <div class="col-md-6">
    <label class="form-label">创作者名称</label>
    <input type="text" name="creator" class="form-control" required>
  </div>
  <div class="col-md-6">
    <label class="form-label">选择视频文件</label>
    <input type="file" name="file" class="form-control" accept=".mp4,.mov,.avi" required>
  </div>
  <div class="col-12">
    <button type="submit" class="btn btn-success">上传</button>
  </div>
</form>
{% endblock %}
''',

  'search.html': '''
{% extends 'base.html' %}
{% block content %}
<h2 class="mb-4">按创作者搜索</h2>
<form method="post" class="input-group mb-4">
  <input type="text" name="creator" class="form-control" placeholder="输入创作者名称" value="{{ query }}">
  <button class="btn btn-outline-secondary" type="submit">搜索</button>
</form>
<div class="row">
  {% for v in videos %}
    <div class="col-md-4 mb-3">
      <div class="card h-100">
        <video class="card-img-top" controls>
          <source src="{{ url_for('uploaded_file', filename=v.filename) }}">
        </video>
        <div class="card-body">
          <h5 class="card-title">{{ v.creator }}</h5>
          <a href="{{ url_for('creator', creator_name=v.creator) }}" class="btn btn-sm btn-primary">进入主页</a>
        </div>
      </div>
    </div>
  {% else %}
    {% if query %}
      <p>未找到与“{{ query }}”匹配的创作者。</p>
    {% endif %}
  {% endfor %}
</div>
{% endblock %}
''',

  'creator.html': '''
{% extends 'base.html' %}
{% block content %}
<h2 class="mb-4">创作者：{{ creator_name }}</h2>
<div class="row">
  {% for v in videos %}
    <div class="col-md-4 mb-3">
      <div class="card h-100">
        <video class="card-img-top" controls>
          <source src="{{ url_for('uploaded_file', filename=v.filename) }}">
        </video>
        <div class="card-body">
          <p class="card-text">{{ v.filename }}</p>
        </div>
      </div>
    </div>
  {% else %}
    <p>此创作者尚未上传视频。</p>
  {% endfor %}
</div>
{% endblock %}
'''
}

# 使用 DictLoader 加载内嵌模板
app.jinja_loader = DictLoader(templates)

@app.route('/')
def index():
    conn = get_db_connection()
    videos = conn.execute('SELECT * FROM video ORDER BY id DESC').fetchall()
    conn.close()
    return render_template('index.html', videos=videos)

@app.route('/upload', methods=['GET', 'POST'])
def upload():
    if request.method == 'POST':
        creator = request.form.get('creator', '').strip()
        file = request.files.get('file')
        if not creator:
            flash('请输入创作者名称。', 'warning')
        elif not file or file.filename == '':
            flash('请选择一个视频文件。', 'warning')
        elif not allowed_file(file.filename):
            flash('只允许 mp4、mov、avi 格式。', 'danger')
        else:
            filename = f"{creator}_{file.filename}".replace(' ', '_')
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            conn = get_db_connection()
            conn.execute('INSERT INTO video (filename, creator) VALUES (?, ?)',
                         (filename, creator))
            conn.commit()
            conn.close()
            flash('视频上传成功！', 'success')
            return redirect(url_for('index'))
    return render_template('upload.html')

@app.route('/search', methods=['GET', 'POST'])
def search():
    videos = []
    query = ''
    if request.method == 'POST':
        query = request.form.get('creator', '').strip()
        conn = get_db_connection()
        videos = conn.execute(
            'SELECT * FROM video WHERE creator LIKE ? ORDER BY id DESC',
            (f'%{query}%',)
        ).fetchall()
        conn.close()
    return render_template('search.html', videos=videos, query=query)

@app.route('/creator/<creator_name>')
def creator(creator_name):
    conn = get_db_connection()
    videos = conn.execute(
        'SELECT * FROM video WHERE creator = ? ORDER BY id DESC',
        (creator_name,)
    ).fetchall()
    conn.close()
    return render_template('creator.html', videos=videos, creator_name=creator_name)

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

if __name__ == '__main__':
    app.run(debug=True)
