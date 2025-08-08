import os
from datetime import datetime
from flask import Flask, render_template, redirect, url_for, flash, request, abort
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_login import (
    LoginManager, UserMixin,
    login_user, current_user,
    logout_user, login_required
)
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Length, Email, EqualTo, ValidationError

# —— 应用与配置 —— #
app = Flask(__name__)
# 用于会话加密，生产环境请设置环境变量 SECRET_KEY
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key')
# 使用 SQLite 数据库，生产环境可替换为其他数据库 URI
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///site.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# —— 初始化扩展 —— #
db = SQLAlchemy(app)
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
# 未登录时访问 @login_required 路由将重定向到此视图
login_manager.login_view = 'login'
login_manager.login_message_category = 'info'

# —— 用户加载回调 —— #
@login_manager.user_loader
def load_user(user_id):
    # Flask-Login 根据 user_id 从数据库中加载用户实例
    return User.query.get(int(user_id))

# —— 数据模型 —— #
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(20), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(60), nullable=False)
    # 一对多关系：一个用户可以有多篇帖子
    posts = db.relationship('Post', backref='author', lazy=True)

class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    content = db.Column(db.Text, nullable=False)
    date_posted = db.Column(db.DateTime, default=datetime.utcnow)
    # 外键关联到用户表
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

# —— 表单定义 —— #
class RegistrationForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(2, 20)])
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    confirm = PasswordField('Confirm Password', validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('Register')

    def validate_username(self, username):
        # 校验用户名唯一
        if User.query.filter_by(username=username.data).first():
            raise ValidationError('Username already taken.')

    def validate_email(self, email):
        # 校验邮箱唯一
        if User.query.filter_by(email=email.data).first():
            raise ValidationError('Email already registered.')

class LoginForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Login')

class PostForm(FlaskForm):
    title = StringField('Title', validators=[DataRequired(), Length(1, 100)])
    content = TextAreaField('Content', validators=[DataRequired()])
    submit = SubmitField('Submit')

# —— 路由 —— #

@app.route('/')
def index():
    """首页：显示所有用户的帖子，按发布时间倒序"""
    posts = Post.query.order_by(Post.date_posted.desc()).all()
    return render_template('index.html', posts=posts)

@app.route('/register', methods=['GET', 'POST'])
def register():
    """用户注册"""
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    form = RegistrationForm()
    if form.validate_on_submit():
        # 密码哈希
        hashed = bcrypt.generate_password_hash(form.password.data).decode('utf-8')
        user = User(username=form.username.data, email=form.email.data, password=hashed)
        db.session.add(user)
        db.session.commit()
        flash('注册成功！', 'success')
        return redirect(url_for('login'))
    return render_template('register.html', form=form)

@app.route('/login', methods=['GET', 'POST'])
def login():
    """用户登录"""
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        # 验证密码
        if user and bcrypt.check_password_hash(user.password, form.password.data):
            login_user(user)
            return redirect(url_for('index'))
        flash('登录失败，请检查凭据。', 'danger')
    return render_template('login.html', form=form)

@app.route('/logout')
def logout():
    """用户登出"""
    logout_user()
    return redirect(url_for('index'))

@app.route('/post/new', methods=['GET', 'POST'])
@login_required
def new_post():
    """创建新帖子"""
    form = PostForm()
    if form.validate_on_submit():
        post = Post(title=form.title.data, content=form.content.data, author=current_user)
        db.session.add(post)
        db.session.commit()
        flash('文章已创建。', 'success')
        return redirect(url_for('index'))
    return render_template('edit_post.html', form=form)

@app.route('/post/<int:post_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_post(post_id):
    """编辑自己的帖子"""
    post = Post.query.get_or_404(post_id)
    if post.author != current_user:
        abort(403)  # 禁止非作者编辑
    form = PostForm(obj=post)  # 用现有数据填充表单
    if form.validate_on_submit():
        post.title = form.title.data
        post.content = form.content.data
        db.session.commit()
        flash('文章已更新。', 'success')
        return redirect(url_for('index'))
    return render_template('edit_post.html', form=form)

@app.route('/post/<int:post_id>/delete', methods=['POST'])
@login_required
def delete_post(post_id):
    """删除自己的帖子"""
    post = Post.query.get_or_404(post_id)
    if post.author != current_user:
        abort(403)
    db.session.delete(post)
    db.session.commit()
    flash('文章已删除。', 'info')
    return redirect(url_for('index'))

@app.route('/users')
def search_users():
    """用户搜索：支持 ?q=关键词，模糊匹配用户名"""
    query = request.args.get('q', '')
    # 使用 SQL LIKE 实现模糊搜索，不区分大小写
    users = User.query.filter(User.username.ilike(f'%{query}%')).all() if query else []
    return render_template('search_users.html', users=users, query=query)

@app.route('/user/<string:username>')
def view_user(username):
    """查看指定用户的所有帖子（只读）"""
    user = User.query.filter_by(username=username).first_or_404()
    posts = Post.query.filter_by(author=user).order_by(Post.date_posted.desc()).all()
    return render_template('view_user.html', user=user, posts=posts)

# —— 程序入口 —— #
if __name__ == '__main__':
    # 首次运行会自动创建数据库表
    db.create_all()
    app.run(debug=True)


## ✨ 改进后的 `base.html`（全局布局与导航）  

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{% block title %}Flask 写作平台{% endblock %}</title>
  <link
    href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css"
    rel="stylesheet"
  />
  <style>
    body { padding-top: 5rem; }
    footer { margin-top: 4rem; padding: 2rem 0; background: #f8f9fa; text-align: center; }
  </style>
</head>
<body>
<nav class="navbar navbar-expand-md navbar-dark bg-primary fixed-top">
  <div class="container">
    <a class="navbar-brand fw-bold" href="{{ url_for('index') }}">写作平台</a>
    <button
      class="navbar-toggler"
      type="button"
      data-bs-toggle="collapse"
      data-bs-target="#navMenu"
      aria-controls="navMenu"
      aria-expanded="false"
      aria-label="Toggle navigation"
    >
      <span class="navbar-toggler-icon"></span>
    </button>

    <div class="collapse navbar-collapse" id="navMenu">
      <ul class="navbar-nav me-auto mb-2 mb-md-0">
        {% if current_user.is_authenticated %}
          <li class="nav-item">
            <a class="nav-link" href="{{ url_for('new_post') }}">新建文章</a>
          </li>
        {% endif %}
        <li class="nav-item">
          <a class="nav-link" href="{{ url_for('search_users') }}">搜索作者</a>
        </li>
      </ul>

      <form class="d-flex me-3" method="get" action="{{ url_for('search_users') }}">
        <input
          class="form-control form-control-sm"
          type="search"
          name="q"
          placeholder="作者名搜索"
          value="{{ request.args.get('q','') }}"
        />
        <button class="btn btn-sm btn-light ms-2" type="submit">搜索</button>
      </form>

      <ul class="navbar-nav mb-2 mb-md-0">
        {% if current_user.is_authenticated %}
          <li class="nav-item">
            <span class="nav-link">你好，<b>{{ current_user.username }}</b></span>
          </li>
          <li class="nav-item">
            <a class="nav-link" href="{{ url_for('logout') }}">登出</a>
          </li>
        {% else %}
          <li class="nav-item">
            <a class="nav-link" href="{{ url_for('login') }}">登录</a>
          </li>
          <li class="nav-item">
            <a class="nav-link" href="{{ url_for('register') }}">注册</a>
          </li>
        {% endif %}
      </ul>
    </div>
  </div>
</nav>

<main class="container">
  {% with messages = get_flashed_messages(with_categories=true) %}
    {% if messages %}
      {% for category, msg in messages %}
        <div class="alert alert-{{ category }} alert-dismissible fade show mt-3">
          {{ msg }}
          <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        </div>
      {% endfor %}
    {% endif %}
  {% endwith %}
  {% block content %}{% endblock %}
</main>

<footer>
  <div class="container">
    <small>&copy; 2025 写作平台 &middot; Powered by Flask</small>
  </div>
</footer>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
```

<hr>

## 🏠 改进后的首页 `index.html`  

```html
{% extends "base.html" %}
{% block title %}首页 · 写作平台{% endblock %}

{% block content %}
  <div class="d-flex justify-content-between align-items-center mt-4 mb-3">
    <h1 class="h3">最新文章</h1>
    {% if current_user.is_authenticated %}
      <a href="{{ url_for('new_post') }}" class="btn btn-sm btn-success">撰写新文</a>
    {% endif %}
  </div>

  {% if posts %}
    {% for post in posts %}
      <div class="card mb-4 shadow-sm">
        <div class="card-body">
          <h5 class="card-title">{{ post.title }}</h5>
          <h6 class="card-subtitle text-muted mb-2">
            <a href="{{ url_for('view_user', username=post.author.username) }}">
              {{ post.author.username }}
            </a>
            • {{ post.date_posted.strftime('%Y-%m-%d %H:%M') }}
          </h6>
          <p class="card-text">{{ post.content[:200] }}{% if post.content|length > 200 %}…{% endif %}</p>
          <div class="d-flex justify-content-end">
            <a href="{{ url_for('view_user', username=post.author.username) }}" class="btn btn-sm btn-outline-primary me-2">
              查看更多
            </a>
            {% if post.author == current_user %}
              <a href="{{ url_for('edit_post', post_id=post.id) }}" class="btn btn-sm btn-outline-secondary me-2">编辑</a>
              <form action="{{ url_for('delete_post', post_id=post.id) }}" method="post" onsubmit="return confirm('确认删除？');">
                <button type="submit" class="btn btn-sm btn-outline-danger">删除</button>
              </form>
            {% endif %}
          </div>
        </div>
      </div>
    {% endfor %}
  {% else %}
    <p class="text-center text-muted">暂时没有文章，来<span class="text-primary">写一篇</span>吧！</p>
  {% endif %}
{% endblock %}
```

<hr>

## 📝 改进后的表单模板 `form_helpers.html`  

```html
{% macro render_field(field, label_class='form-label', input_class='form-control', **kwargs) %}
  <div class="mb-3">
    {{ field.label(class=label_class) }}
    {{ field(class=input_class, **kwargs) }}
    {% if field.errors %}
      <div class="form-text text-danger">
        {% for err in field.errors %}{{ err }}{% if not loop.last %}<br>{% endif %}{% endfor %}
      </div>
    {% endif %}
  </div>
{% endmacro %}
```

将此文件放在 `templates/` 下，然后在其他表单页引入：
```jinja
{% import "form_helpers.html" as forms %}
```

<hr>

## 📝 改进后的注册页面 `register.html`  

```html
{% extends "base.html" %}
{% import "form_helpers.html" as forms %}
{% block title %}注册 · 写作平台{% endblock %}

{% block content %}
  <div class="mx-auto" style="max-width: 400px;">
    <h2 class="mb-4 text-center">创建新账号</h2>
    <form method="post" novalidate>
      {{ form.hidden_tag() }}
      {{ forms.render_field(form.username) }}
      {{ forms.render_field(form.email) }}
      {{ forms.render_field(form.password) }}
      {{ forms.render_field(form.confirm) }}
      <button type="submit" class="btn btn-primary w-100">注册</button>
    </form>
    <p class="mt-3 text-center">
      已有账号？<a href="{{ url_for('login') }}">立即登录</a>
    </p>
  </div>
{% endblock %}
```

<hr>

## 🔑 改进后的登录页面 `login.html`  

```html
{% extends "base.html" %}
{% import "form_helpers.html" as forms %}
{% block title %}登录 · 写作平台{% endblock %}

{% block content %}
  <div class="mx-auto" style="max-width: 400px;">
    <h2 class="mb-4 text-center">用户登录</h2>
    <form method="post" novalidate>
      {{ form.hidden_tag() }}
      {{ forms.render_field(form.email) }}
      {{ forms.render_field(form.password) }}
      <button type="submit" class="btn btn-success w-100">登录</button>
    </form>
    <p class="mt-3 text-center">
      没有账号？<a href="{{ url_for('register') }}">去注册</a>
    </p>
  </div>
{% endblock %}
```

<hr>

## ✍️ 改进后的文章编辑页面 `edit_post.html`  

```html
{% extends "base.html" %}
{% import "form_helpers.html" as forms %}
{% block title %}{{ '编辑' if form.title.data else '新建' }}文章 · 写作平台{% endblock %}

{% block content %}
  <div class="mx-auto" style="max-width: 700px;">
    <h2 class="mb-4">{{ '编辑' if form.title.data else '撰写' }}文章</h2>
    <form method="post" novalidate>
      {{ form.hidden_tag() }}
      {{ forms.render_field(form.title) }}
      {{ forms.render_field(form.content, rows=8) }}
      <button type="submit" class="btn btn-primary">
        {{ '更新文章' if form.title.data else '发布文章' }}
      </button>
      <a href="{{ url_for('index') }}" class="btn btn-secondary ms-2">取消</a>
    </form>
  </div>
{% endblock %}
```

<hr>

## 🔍 改进后的用户搜索与查看页面  

search_users.html  
```html
{% extends "base.html" %}
{% block title %}搜索作者 · 写作平台{% endblock %}

{% block content %}
  <h2 class="mt-4 mb-3">搜索作者</h2>
  <form class="row g-2 mb-4" method="get">
    <div class="col-sm-8">
      <input
        name="q"
        type="text"
        class="form-control"
        placeholder="输入用户名关键词"
        value="{{ query }}"
      />
    </div>
    <div class="col-sm-4">
      <button class="btn btn-primary w-100" type="submit">搜索</button>
    </div>
  </form>

  {% if users %}
    <ul class="list-group">
      {% for user in users %}
        <li class="list-group-item d-flex justify-content-between align-items-center">
          <a href="{{ url_for('view_user', username=user.username) }}">
            {{ user.username }}
          </a>
          <span class="badge bg-secondary rounded-pill">{{ user.posts|length }}</span>
        </li>
      {% endfor %}
    </ul>
  {% elif query %}
    <p class="text-muted">未找到匹配作者。</p>
  {% endif %}
{% endblock %}
```

view_user.html  
```html
{% extends "base.html" %}
{% block title %}{{ user.username }} 的文章 · 写作平台{% endblock %}

{% block content %}
  <h2 class="mt-4 mb-3">{{ user.username }} 的作品</h2>
  {% if posts %}
    {% for post in posts %}
      <div class="card mb-3">
        <div class="card-body">
          <h5 class="card-title">{{ post.title }}</h5>
          <p class="card-text">{{ post.content }}</p>
          <p class="text-end text-muted mb-0">
            {{ post.date_posted.strftime('%Y-%m-%d %H:%M') }}
          </p>
        </div>
      </div>
    {% endfor %}
  {% else %}
    <p class="text-center text-muted">Ta 还没有发表文章。</p>
  {% endif %}
{% endblock %}
```
