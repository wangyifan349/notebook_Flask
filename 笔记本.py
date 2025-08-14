import sqlite3
from flask import Flask, g, render_template_string, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

# 应用配置
app = Flask(__name__)
app.config['SECRET_KEY'] = '请换成你自己的随机字符串'   # 用于会话和 Flash
DATABASE_FILE = 'notebook.db'                         # SQLite 数据库文件

# 基础模板
base_template = """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>在线笔记本</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>body{padding-top:70px;}textarea{height:200px;}</style>
</head>
<body>
<nav class="navbar navbar-expand-lg navbar-dark bg-dark fixed-top">
  <div class="container-fluid">
    <a class="navbar-brand" href="{{ url_for('index') }}">笔记本</a>
    <div class="collapse navbar-collapse">
      <ul class="navbar-nav ms-auto">
      {% if session.get('user_id') %}
        <li class="nav-item"><a class="nav-link" href="{{ url_for('view_notebook') }}">我的笔记</a></li>
        <li class="nav-item"><a class="nav-link" href="{{ url_for('logout') }}">退出</a></li>
      {% else %}
        <li class="nav-item"><a class="nav-link" href="{{ url_for('login') }}">登录</a></li>
        <li class="nav-item"><a class="nav-link" href="{{ url_for('register') }}">注册</a></li>
      {% endif %}
      </ul>
    </div>
  </div>
</nav>
<div class="container">
  {% with messages = get_flashed_messages() %}
    {% if messages %}
      <div class="alert alert-info">{{ messages[0] }}</div>
    {% endif %}
  {% endwith %}
  {% block content %}{% endblock %}
</div>
</body>
</html>
"""

# 首页模板
index_template = """
{% extends base_template %}{% block content %}
<div class="jumbotron text-center">
  <h1 class="display-5">欢迎使用在线笔记本</h1>
  <p>请注册或登录开始管理您的笔记。</p>
  <a class="btn btn-primary" href="{{ url_for('login') }}">登录</a>
  <a class="btn btn-secondary" href="{{ url_for('register') }}">注册</a>
</div>
{% endblock %}
"""

# 注册/登录 表单模板
auth_template = """
{% extends base_template %}{% block content %}
<h2>{{ title }}</h2>
<form method="post">
  <div class="mb-3">
    <label class="form-label">用户名</label>
    <input name="username" class="form-control" required maxlength="64" value="{{ request.form.username or '' }}">
  </div>
  <div class="mb-3">
    <label class="form-label">邮箱</label>
    <input name="email" type="email" class="form-control" required value="{{ request.form.email or '' }}">
  </div>
  <div class="mb-3">
    <label class="form-label">密码</label>
    <input name="password" type="password" class="form-control" required>
  </div>
  {% if register %}
  <div class="mb-3">
    <label class="form-label">确认密码</label>
    <input name="password_confirm" type="password" class="form-control" required>
  </div>
  {% endif %}
  <button class="btn btn-primary">{{ title }}</button>
</form>
{% endblock %}
"""

# 笔记列表模板
notebook_template = """
{% extends base_template %}{% block content %}
<div class="d-flex justify-content-between">
  <h2>我的笔记</h2>
  <a class="btn btn-success" href="{{ url_for('create_note') }}">+ 新建</a>
</div>
<hr>
{% if notes %}
  {% for note in notes %}
    <div class="card mb-3">
      <div class="card-body">
        <h5 class="card-title">{{ note.title }}</h5>
        <h6 class="card-subtitle mb-2 text-muted">{{ note.created_at }}</h6>
        <p class="card-text">{{ note.body[:200] }}{% if note.body|length > 200 %}…{% endif %}</p>
        <a href="{{ url_for('edit_note', note_id=note.id) }}" class="card-link">编辑</a>
        <a href="{{ url_for('delete_note', note_id=note.id) }}" class="card-link text-danger">删除</a>
      </div>
    </div>
  {% endfor %}
{% else %}
  <p>暂无笔记。</p>
{% endif %}
{% endblock %}
"""

# 笔记编辑/新建模板
edit_template = """
{% extends base_template %}{% block content %}
<h2>{{ '编辑' if note else '新建' }} 笔记</h2>
<form method="post">
  <div class="mb-3">
    <label class="form-label">标题</label>
    <input name="title" class="form-control" required maxlength="100" value="{{ note.title if note else '' }}">
  </div>
  <div class="mb-3">
    <label class="form-label">正文</label>
    <textarea name="body" class="form-control" required>{{ note.body if note else '' }}</textarea>
  </div>
  <button class="btn btn-primary">保存</button>
</form>
{% endblock %}
"""

def get_db_connection():
    if 'db_connection' not in g:
        connection = sqlite3.connect(DATABASE_FILE, detect_types=sqlite3.PARSE_DECLTYPES)
        connection.row_factory = sqlite3.Row
        g.db_connection = connection
    return g.db_connection

@app.teardown_appcontext
def close_db_connection(exception=None):
    connection = g.pop('db_connection', None)
    if connection:
        connection.close()

def initialize_database():
    db = get_db_connection()
    db.executescript("""
    CREATE TABLE IF NOT EXISTS users (
      id INTEGER PRIMARY KEY,
      username TEXT UNIQUE NOT NULL,
      email TEXT UNIQUE NOT NULL,
      password_hash TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS notes (
      id INTEGER PRIMARY KEY,
      title TEXT NOT NULL,
      body TEXT NOT NULL,
      created_at TEXT NOT NULL,
      user_id INTEGER NOT NULL,
      FOREIGN KEY(user_id) REFERENCES users(id)
    );
    """)
    db.commit()

@app.before_first_request
def initialize_app():
    initialize_database()

@app.route('/')
def index():
    return render_template_string(index_template, base_template=base_template)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        password_confirm = request.form['password_confirm']
        if password != password_confirm:
            flash('两次密码不一致')
        else:
            db = get_db_connection()
            try:
                db.execute(
                    "INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)",
                    (username, email, generate_password_hash(password))
                )
                db.commit()
                flash('注册成功，请登录')
                return redirect(url_for('login'))
            except sqlite3.IntegrityError:
                flash('用户名或邮箱已存在')
    return render_template_string(auth_template,
                                  base_template=base_template,
                                  title="注册",
                                  register=True)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        db = get_db_connection()
        user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if user and check_password_hash(user['password_hash'], password):
            session.clear()
            session['user_id'] = user['id']
            session['username'] = user['username']
            return redirect(url_for('view_notebook'))
        flash('邮箱或密码错误')
    return render_template_string(auth_template,
                                  base_template=base_template,
                                  title="登录",
                                  register=False)

@app.route('/logout')
def logout():
    session.clear()
    flash('已退出登录')
    return redirect(url_for('index'))

def login_required(view_function):
    def wrapped_view(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return view_function(*args, **kwargs)
    wrapped_view.__name__ = view_function.__name__
    return wrapped_view

@app.route('/notebook')
@login_required
def view_notebook():
    db = get_db_connection()
    rows = db.execute(
        "SELECT * FROM notes WHERE user_id = ? ORDER BY created_at DESC",
        (session['user_id'],)
    ).fetchall()
    notes = [
        type('Note', (), dict(id=row['id'], title=row['title'], body=row['body'], created_at=row['created_at']))
        for row in rows
    ]
    return render_template_string(notebook_template,
                                  base_template=base_template,
                                  notes=notes)

@app.route('/note/new', methods=['GET', 'POST'])
@login_required
def create_note():
    if request.method == 'POST':
        title = request.form['title']
        body = request.form['body']
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M")
        db = get_db_connection()
        db.execute(
            "INSERT INTO notes (title, body, created_at, user_id) VALUES (?, ?, ?, ?)",
            (title, body, created_at, session['user_id'])
        )
        db.commit()
        flash('笔记已创建')
        return redirect(url_for('view_notebook'))
    return render_template_string(edit_template,
                                  base_template=base_template,
                                  note=None)

@app.route('/note/<int:note_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_note(note_id):
    db = get_db_connection()
    row = db.execute(
        "SELECT * FROM notes WHERE id = ? AND user_id = ?",
        (note_id, session['user_id'])
    ).fetchone()
    if not row:
        flash('无权限或笔记不存在')
        return redirect(url_for('view_notebook'))
    note = type('Note', (), dict(id=row['id'], title=row['title'], body=row['body'], created_at=row['created_at']))
    if request.method == 'POST':
        title = request.form['title']
        body = request.form['body']
        db.execute(
            "UPDATE notes SET title = ?, body = ? WHERE id = ?",
            (title, body, note_id)
        )
        db.commit()
        flash('笔记已更新')
        return redirect(url_for('view_notebook'))
    return render_template_string(edit_template,
                                  base_template=base_template,
                                  note=note)

@app.route('/note/<int:note_id>/delete')
@login_required
def delete_note(note_id):
    db = get_db_connection()
    db.execute(
        "DELETE FROM notes WHERE id = ? AND user_id = ?",
        (note_id, session['user_id'])
    )
    db.commit()
    flash('笔记已删除')
    return redirect(url_for('view_notebook'))

if __name__ == '__main__':
    app.run(debug=True)
