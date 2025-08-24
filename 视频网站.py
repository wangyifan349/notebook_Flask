import os
import time
import sqlite3
from datetime import datetime
from flask import (
    Flask, request, redirect, url_for, flash,
    send_from_directory, render_template_string, abort
)
from werkzeug.utils import secure_filename

# --------- 基本配置 ---------
app = Flask(__name__)
app.secret_key = 'replace-with-a-safe-secret-key'  # 上线时请修改

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')  # 上传视频保存路径
DATABASE = os.path.join(BASE_DIR, 'videos.db')    # SQLite 数据库文件名
ALLOWED_EXTENSIONS = {'mp4', 'mov', 'avi'}         # 允许上传的视频格式
MAX_CONTENT_LENGTH = 200 * 1024 * 1024             # 最大上传文件大小：200MB

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH
# 确保上传文件夹存在
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
# --------- 数据库操作 ---------
def init_db():
    """
    初始化数据库，创建 video 表（如果不存在）
    video 表字段：
      - id：自增主键
      - filename：服务器保存的文件名
      - creator：创作者名称
      - uploaded_at：上传时间戳（秒）
    """
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    # 执行SQL：如果 video 表不存在，就创建它
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS video (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            creator TEXT NOT NULL,
            uploaded_at INTEGER NOT NULL
        )
    ''')
    conn.commit()
    conn.close()

def get_db_connection():
    """
    获取 SQLite 连接并设置 row_factory 以支持字段名访问
    """
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

# 在程序启动时初始化数据库
init_db()
# --------- 工具函数 ---------
def allowed_file(filename):
    """
    判断上传文件的后缀是否合法
    """
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Jinja2 自定义过滤器：时间戳格式化为易读时间字符串
@app.template_filter('datetimeformat')
def datetimeformat(value):
    """
    把 Unix 时间戳转成 %Y-%m-%d %H:%M:%S 格式日期字符串
    """
    try:
        return datetime.fromtimestamp(int(value)).strftime('%Y-%m-%d %H:%M:%S')
    except Exception:
        return str(value)
# --------- HTML 模板 ---------
# 为避免嵌套和复杂结构，全部写成字符串，使用 render_template_string 直接渲染。

index_html = '''
<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<title>VideoShare - 首页</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.1/dist/css/bootstrap.min.css" rel="stylesheet">
<style>
  video { width: 100%; height: auto; }
  .card-title { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 200px; }
</style>
</head>
<body class="bg-light">
<nav class="navbar navbar-expand-lg navbar-dark bg-dark mb-4">
  <div class="container-fluid">
    <a class="navbar-brand" href="{{ url_for('index') }}">VideoShare</a>
    <div class="collapse navbar-collapse">
      <ul class="navbar-nav ms-auto mb-2 mb-lg-0">
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
          <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="关闭"></button>
        </div>
      {% endfor %}
    {% endif %}
  {% endwith %}

  <h2 class="mb-4">最新视频</h2>
  <div class="row">
    {% if videos %}
      {% for v in videos %}
      <div class="col-md-4 mb-3">
        <div class="card h-100">
          <video class="card-img-top" controls>
            <source src="{{ url_for('uploaded_file', filename=v.filename) }}" type="video/{{ v.filename.rsplit('.',1)[1] }}">
            您的浏览器不支持 video 标签。
          </video>
          <div class="card-body">
            <h5 class="card-title">{{ v.creator }}</h5>
            <p class="text-muted small">上传于 {{ v.uploaded_at | datetimeformat }}</p>
            <a href="{{ url_for('creator', creator_name=v.creator) }}" class="btn btn-sm btn-primary">查看主页</a>
            <a href="{{ url_for('uploaded_file', filename=v.filename) }}" download class="btn btn-sm btn-outline-secondary">下载</a>
          </div>
        </div>
      </div>
      {% endfor %}
    {% else %}
      <p>目前还没有视频。</p>
    {% endif %}
  </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.1/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
'''

upload_html = '''
<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<title>上传视频 - VideoShare</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.1/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body class="bg-light">
<nav class="navbar navbar-expand-lg navbar-dark bg-dark mb-4">
  <div class="container-fluid">
    <a class="navbar-brand" href="{{ url_for('index') }}">VideoShare</a>
    <div class="collapse navbar-collapse">
      <ul class="navbar-nav ms-auto mb-2 mb-lg-0">
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
          <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="关闭"></button>
        </div>
      {% endfor %}
    {% endif %}
  {% endwith %}

  <h2 class="mb-4">上传新视频</h2>
  <form method="post" enctype="multipart/form-data" class="row g-3">
    <div class="col-md-6">
      <label for="creator" class="form-label">创作者名称</label>
      <input type="text" name="creator" id="creator" class="form-control" required>
    </div>
    <div class="col-md-6">
      <label for="file" class="form-label">选择视频文件 (.mp4, .mov, .avi)</label><br>
      <input type="file" name="file" id="file" class="form-control" accept=".mp4,.mov,.avi" required>
    </div>
    <div class="col-12">
      <button type="submit" class="btn btn-success">上传</button>
      <a href="{{ url_for('index') }}" class="btn btn-secondary">返回首页</a>
    </div>
  </form>
</div>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.1/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
'''

search_html = '''
<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<title>搜索 - VideoShare</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.1/dist/css/bootstrap.min.css" rel="stylesheet">
<style>
  video { width: 100%; height: auto; }
</style>
</head>
<body class="bg-light">
<nav class="navbar navbar-expand-lg navbar-dark bg-dark mb-4">
  <div class="container-fluid">
    <a class="navbar-brand" href="{{ url_for('index') }}">VideoShare</a>
    <div class="collapse navbar-collapse">
      <ul class="navbar-nav ms-auto mb-2 mb-lg-0">
        <li class="nav-item"><a class="nav-link" href="{{ url_for('upload') }}">上传</a></li>
        <li class="nav-item"><a class="nav-link" href="{{ url_for('search') }}">搜索</a></li>
      </ul>
    </div>
  </div>
</nav>

<div class="container">
  <h2 class="mb-4">按创作者搜索</h2>
  <form method="get" class="row g-3 mb-4">
    <div class="col-md-9">
      <input type="text" name="creator" value="{{ query }}" class="form-control" placeholder="输入创作者名称（支持模糊匹配）">
    </div>
    <div class="col-md-3">
      <button type="submit" class="btn btn-primary w-100">搜索</button>
    </div>
  </form>

  <div class="row">
  {% if videos %}
    {% for v in videos %}
    <div class="col-md-4 mb-3">
      <div class="card h-100">
        <video class="card-img-top" controls>
          <source src="{{ url_for('uploaded_file', filename=v.filename) }}" type="video/{{ v.filename.rsplit('.',1)[1] }}">
          您的浏览器不支持 video 标签。
        </video>
        <div class="card-body">
          <h5 class="card-title">{{ v.creator }}</h5>
          <p class="text-muted small">上传于 {{ v.uploaded_at | datetimeformat }}</p>
          <a href="{{ url_for('creator', creator_name=v.creator) }}" class="btn btn-sm btn-primary">查看主页</a>
        </div>
      </div>
    </div>
    {% endfor %}
  {% else %}
    <p>没有找到匹配的视频。</p>
  {% endif %}
  </div>

  <a href="{{ url_for('index') }}" class="btn btn-secondary mt-3">返回首页</a>
</div>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.1/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
'''

creator_html = '''
<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<title>{{ creator_name }} 的主页 - VideoShare</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.1/dist/css/bootstrap.min.css" rel="stylesheet">
<style>
  video { width: 100%; height: auto; }
</style>
</head>
<body class="bg-light">
<nav class="navbar navbar-expand-lg navbar-dark bg-dark mb-4">
  <div class="container-fluid">
    <a class="navbar-brand" href="{{ url_for('index') }}">VideoShare</a>
    <div class="collapse navbar-collapse">
      <ul class="navbar-nav ms-auto mb-2 mb-lg-0">
        <li class="nav-item"><a class="nav-link" href="{{ url_for('upload') }}">上传</a></li>
        <li class="nav-item"><a class="nav-link" href="{{ url_for('search') }}">搜索</a></li>
      </ul>
    </div>
  </div>
</nav>

<div class="container">
  <h2 class="mb-4">{{ creator_name }} 的视频</h2>
  <div class="row">
    {% if videos %}
      {% for v in videos %}
      <div class="col-md-4 mb-3">
        <div class="card h-100">
          <video class="card-img-top" controls>
            <source src="{{ url_for('uploaded_file', filename=v.filename) }}" type="video/{{ v.filename.rsplit('.',1)[1] }}">
            您的浏览器不支持 video 标签。
          </video>
          <div class="card-body">
            <p class="text-muted small">上传于 {{ v.uploaded_at | datetimeformat }}</p>
            <a href="{{ url_for('uploaded_file', filename=v.filename) }}" download class="btn btn-sm btn-outline-secondary">下载</a>
          </div>
        </div>
      </div>
      {% endfor %}
    {% else %}
      <p>该创作者还没有上传视频。</p>
    {% endif %}
  </div>

  <a href="{{ url_for('index') }}" class="btn btn-secondary">返回首页</a>
</div>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.1/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
'''
# --------- 路由处理 ---------
@app.route('/')
def index():
    """
    首页，列出最新上传视频，按 id 降序排列
    """
    conn = get_db_connection()
    # SQL查询：select所有视频，按 id 递减
    videos = conn.execute("SELECT * FROM video ORDER BY id DESC").fetchall()
    conn.close()

    # 渲染首页模板
    return render_template_string(index_html, videos=videos)
@app.route('/upload', methods=['GET', 'POST'])
def upload():
    """
    视频上传页面，
    GET 返回上传页面，
    POST 处理上传操作
    """
    if request.method == 'POST':
        creator = request.form.get('creator', '').strip()
        file = request.files.get('file')

        # 基本表单验证
        if not creator:
            flash('请输入创作者名称。', 'warning')
            return redirect(url_for('upload'))
        if not file or file.filename == '':
            flash('请选择一个视频文件。', 'warning')
            return redirect(url_for('upload'))

        if not allowed_file(file.filename):
            flash('只允许上传 mp4、mov、avi 格式。', 'danger')
            return redirect(url_for('upload'))

        # 用安全的文件名，避免目录穿越等安全隐患
        ext = file.filename.rsplit('.', 1)[1].lower()
        safe_creator = secure_filename(creator).replace(' ', '_') or 'user'
        timestamp = int(time.time())
        filename = f"{safe_creator}_{timestamp}.{ext}"
        save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)

        try:
            # 保存文件到服务器上传目录
            file.save(save_path)
        except Exception as e:
            flash('保存文件失败：' + str(e), 'danger')
            return redirect(url_for('upload'))

        # 插入数据库记录
        conn = get_db_connection()

        # SQL 插入操作：
        # INSERT INTO video (filename, creator, uploaded_at) VALUES (?, ?, ?)
        conn.execute(
            "INSERT INTO video (filename, creator, uploaded_at) VALUES (?, ?, ?)",
            (filename, creator, timestamp)
        )
        conn.commit()
        conn.close()

        flash('视频上传成功！', 'success')
        return redirect(url_for('index'))

    # GET 方法返回上传表单
    return render_template_string(upload_html)


@app.route('/search')
def search():
    """
    按创作者名称搜索视频，支持模糊匹配
    通过 GET 参数 ?creator=...
    """
    query = request.args.get('creator', '').strip()
    videos = []

    if query:
        conn = get_db_connection()

        # SQL 查询，LIKE 语句，模糊匹配创作者名
        # 例如 search='alice' 可以匹配 'Alice', 'alice123' 等
        videos = conn.execute(
            "SELECT * FROM video WHERE creator LIKE ? ORDER BY id DESC",
            (f'%{query}%',)
        ).fetchall()
        conn.close()

    # 渲染搜索结果页面
    return render_template_string(search_html, videos=videos, query=query)

@app.route('/creator/<path:creator_name>')
def creator(creator_name):
    """
    查看某个创作者的视频主页，显示该创作者所有视频
    """
    conn = get_db_connection()

    # SQL 查询该创作者的所有视频
    videos = conn.execute(
        "SELECT * FROM video WHERE creator = ? ORDER BY id DESC",
        (creator_name,)
    ).fetchall()
    conn.close()
    return render_template_string(creator_html, videos=videos, creator_name=creator_name)
@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    """
    提供上传视频的访问接口，浏览器可以直接访问视频文件
    对 filename 简单做安全检查，防止路径穿越攻击
    """
    if '..' in filename or filename.startswith('/'):
        abort(400)
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename, as_attachment=False)
# --------- 错误处理 ---------
@app.errorhandler(413)
def request_entity_too_large(error):
    """
    文件上传过大时，返回提示信息
    """
    flash('文件过大，最大允许 200MB。', 'danger')
    return redirect(request.referrer or url_for('upload'))
@app.errorhandler(404)
def page_not_found(e):
    """
    404错误页面简单提示
    """
    return "<h1>404 未找到</h1><p>请求的页面不存在。</p>", 404
# --------- 启动 ---------
if __name__ == '__main__':
    # 启动调试服务器，可以局域网访问：host='0.0.0.0'
    # 部署时请使用 gunicorn 或 uwsgi 等生产级服务器
    app.run(debug=True, port=5000)
