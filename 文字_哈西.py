from flask import Flask, request, session, redirect, url_for, send_file, escape
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import os, hashlib, zipfile
from io import BytesIO

app = Flask(__name__)
app.secret_key = 'replace-with-secure-key'      # 用于会话加密，部署时请换成安全密钥
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///site.db'
database = SQLAlchemy(app)                      # 初始化数据库

# 定义用户模型
class User(database.Model):
    id = database.Column(database.Integer, primary_key=True)
    username = database.Column(database.String(80), unique=True, nullable=False)
    password_hash = database.Column(database.String(128), nullable=False)

# 定义文章模型
class Article(database.Model):
    id = database.Column(database.Integer, primary_key=True)
    title = database.Column(database.String(200), nullable=False)
    filename_hash = database.Column(database.String(64), unique=True, nullable=False)
    author_id = database.Column(database.Integer, database.ForeignKey('user.id'), nullable=False)

database.create_all()                            # 创建数据库表

# 文章存储目录，位于本文件同级的 articles 文件夹
ARTICLE_DIRECTORY = os.path.join(os.path.dirname(__file__), 'articles')
os.makedirs(ARTICLE_DIRECTORY, exist_ok=True)   # 如果不存在则创建

# 基础 HTML 模板，引入 Bootstrap
BASE_HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Simple Blog</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body class="bg-light">
  <div class="container my-4">
    {body}
  </div>
  <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
"""

# 登录页面模板
LOGIN_TEMPLATE = """
<div class="card mx-auto" style="max-width: 400px;">
  <div class="card-body">
    <h2 class="card-title text-center">Login</h2>
    <form method="post">
      <div class="mb-3">
        <label class="form-label">Username</label>
        <input name="username" class="form-control">
      </div>
      <div class="mb-3">
        <label class="form-label">Password</label>
        <input name="password" type="password" class="form-control">
      </div>
      <button class="btn btn-primary w-100">Login</button>
    </form>
    <div class="mt-3 text-center">
      <a href="/register">Register</a>
    </div>
  </div>
</div>
"""

# 注册页面模板
REGISTER_TEMPLATE = """
<div class="card mx-auto" style="max-width: 400px;">
  <div class="card-body">
    <h2 class="card-title text-center">Register</h2>
    <form method="post">
      <div class="mb-3">
        <label class="form-label">Username</label>
        <input name="username" class="form-control">
      </div>
      <div class="mb-3">
        <label class="form-label">Password</label>
        <input name="password" type="password" class="form-control">
      </div>
      <button class="btn btn-success w-100">Register</button>
    </form>
    <div class="mt-3 text-center">
      <a href="/login">Already have account? Login</a>
    </div>
  </div>
</div>
"""

# 仪表盘页面模板
DASHBOARD_TEMPLATE = """
<h2>Welcome, {username}</h2>
<div class="mb-3">
  <a href="/logout" class="btn btn-outline-danger">Logout</a>
  <a href="/download_all" class="btn btn-outline-primary">Download All Articles</a>
</div>

<h3>Create Article</h3>
<form method="post" class="mb-4">
  <div class="mb-3">
    <label class="form-label">Title</label>
    <input name="title" class="form-control">
  </div>
  <div class="mb-3">
    <label class="form-label">Content</label>
    <textarea name="content" rows="5" class="form-control"></textarea>
  </div>
  <button class="btn btn-success">Publish</button>
</form>

<h3>My Articles</h3>
<ul class="list-group mb-4">
  {article_items}
</ul>

<form action="/view" method="get" class="row g-2">
  <div class="col-auto">
    <input name="hash_value" class="form-control" placeholder="Search by Hash">
  </div>
  <div class="col-auto">
    <button class="btn btn-outline-secondary">View</button>
  </div>
</form>
"""

# 编辑页面模板
EDIT_TEMPLATE = """
<div class="card mx-auto" style="max-width: 600px;">
  <div class="card-body">
    <h2 class="card-title">Edit Article</h2>
    <form method="post">
      <div class="mb-3">
        <label class="form-label">Title</label>
        <input name="title" value="{title}" class="form-control">
      </div>
      <div class="mb-3">
        <label class="form-label">Content</label>
        <textarea name="content" rows="5" class="form-control">{content}</textarea>
      </div>
      <button class="btn btn-success">Save</button>
      <a href="/dashboard" class="btn btn-secondary ms-2">Back</a>
    </form>
  </div>
</div>
"""

# 首页：重定向到登录
@app.route('/')
def home():
    return redirect(url_for('login'))

# 注册路由
@app.route('/register', methods=['GET','POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        # 检查用户名是否已存在
        if User.query.filter_by(username=username).first():
            return BASE_HTML.format(
                body="<div class='alert alert-warning'>Username already exists</div>" + REGISTER_TEMPLATE
            )
        # 创建新用户
        user = User(username=username, password_hash=generate_password_hash(password))
        database.session.add(user)
        database.session.commit()
        return redirect(url_for('login'))
    return BASE_HTML.format(body=REGISTER_TEMPLATE)

# 登录路由
@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        # 验证密码
        if user and check_password_hash(user.password_hash, password):
            session['user_id'] = user.id
            return redirect(url_for('dashboard'))
        return BASE_HTML.format(
            body="<div class='alert alert-danger'>Login failed</div>" + LOGIN_TEMPLATE
        )
    return BASE_HTML.format(body=LOGIN_TEMPLATE)

# 登出路由
@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('login'))

# 仪表盘：显示、创建文章
@app.route('/dashboard', methods=['GET','POST'])
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    current_user = User.query.get(session['user_id'])

    if request.method == 'POST':
        title = request.form['title']
        content = request.form['content']
        # 生成文件名哈希
        hash_value = hashlib.sha256(content.encode('utf-16')).hexdigest()
        filename = f"{hash_value}.txt"
        filepath = os.path.join(ARTICLE_DIRECTORY, filename)
        # 保存文章内容到文件
        with open(filepath, 'w', encoding='utf-16') as file:
            file.write(content)
        # 保存文章记录到数据库
        article = Article(title=title, filename_hash=filename, author_id=current_user.id)
        database.session.add(article)
        database.session.commit()

    # 列出当前用户的文章
    article_items = ""
    for article in Article.query.filter_by(author_id=current_user.id):
        short_hash = article.filename_hash[:-4]
        article_items += (
            f"<li class='list-group-item d-flex justify-content-between align-items-center'>"
            f"{escape(article.title)}"
            f"<span>"
            f"<a href='/edit/{article.filename_hash}' class='btn btn-sm btn-outline-primary me-1'>Edit</a>"
            f"<a href='/delete/{article.filename_hash}' class='btn btn-sm btn-outline-danger me-1'>Delete</a>"
            f"<code>{short_hash}</code>"
            f"</span>"
            f"</li>"
        )

    body = DASHBOARD_TEMPLATE.format(
        username=escape(current_user.username),
        article_items=article_items
    )
    return BASE_HTML.format(body=body)

# 编辑文章
@app.route('/edit/<filename_hash>', methods=['GET','POST'])
def edit_article(filename_hash):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    article = Article.query.filter_by(filename_hash=filename_hash).first_or_404()
    if article.author_id != session['user_id']:
        return "Unauthorized", 403

    filepath = os.path.join(ARTICLE_DIRECTORY, filename_hash)
    if request.method == 'POST':
        new_title = request.form['title']
        new_content = request.form['content']
        # 写回文件
        with open(filepath, 'w', encoding='utf-16') as file:
            file.write(new_content)
        article.title = new_title
        database.session.commit()
        return redirect(url_for('dashboard'))

    with open(filepath, 'r', encoding='utf-16') as file:
        existing_content = file.read()

    body = EDIT_TEMPLATE.format(
        title=escape(article.title),
        content=escape(existing_content)
    )
    return BASE_HTML.format(body=body)

# 删除文章
@app.route('/delete/<filename_hash>')
def delete_article(filename_hash):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    article = Article.query.filter_by(filename_hash=filename_hash).first_or_404()
    if article.author_id != session['user_id']:
        return "Unauthorized", 403

    os.remove(os.path.join(ARTICLE_DIRECTORY, filename_hash))
    database.session.delete(article)
    database.session.commit()
    return redirect(url_for('dashboard'))

# 根据哈希查看文章
@app.route('/view')
def view_article():
    hash_value = request.args.get('hash_value', '')
    filename = f"{hash_value}.txt"
    filepath = os.path.join(ARTICLE_DIRECTORY, filename)
    if not os.path.exists(filepath):
        return "Article not found", 404
    binary_data = open(filepath, 'rb').read()
    return send_file(
        BytesIO(binary_data),
        mimetype='text/plain; charset=utf-16',
        as_attachment=False,
        download_name=filename
    )

# 打包下载所有文章
@app.route('/download_all')
def download_all_articles():
    if not os.path.isdir(ARTICLE_DIRECTORY):
        return "No articles directory", 404

    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for filename in os.listdir(ARTICLE_DIRECTORY):
            if filename.endswith('.txt'):
                file_path = os.path.join(ARTICLE_DIRECTORY, filename)
                zip_file.write(file_path, arcname=filename)
    zip_buffer.seek(0)

    return send_file(
        zip_buffer,
        mimetype='application/zip',
        as_attachment=True,
        download_name='all_articles.zip'
    )

if __name__ == '__main__':
    app.run(debug=True)
