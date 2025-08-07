# -*- coding: utf-8 -*-
"""
文件管理系统（FileHub）

功能说明：
1. 用户注册、登录、登出模块
   - 使用 SQLite 存储用户信息，密码通过哈希方式安全保存
   - 用户注册时需唯一用户名
2. 用户文件管理
   - 用户登录后可以上传、下载、删除、重命名自己的文件
   - 文件支持拖拽排序（顺序信息保存在数据库）
3. 公开分享功能
   - 用户可以开启/关闭“公开分享”开关，让别人用匿名访问的方式浏览和下载文件
4. 安全性说明
   - 文件操作均经过登录校验，权限绑定当前用户
   - 上传文件名使用 werkzeug 的 secure_filename 做安全处理
   - 公开分享页面可匿名访问，但只能访问开启了“公开分享”的用户文件夹
5. 前端界面
   - 使用 Bootstrap5 美化界面，确保响应式布局
   - 右键菜单实现“重命名”交互，文件行可拖拽排序
   - 使用 jQuery 和 jQuery UI 简化交互与拖拽开发
6. 技术栈
   - Python 3，Flask 框架
   - SQLite 数据库，使用 Flask 自带的 g 对象维护单请求内数据库连接

目录结构（运行时自动生成）：
- 本脚本文件.py
- filehub.db （数据库文件，首次运行自动生成）
- uploads/ （用户上传文件根目录）
    - {user_id}/ （每个用户独立文件夹）

使用方法：
1. 运行此脚本 `python 文件名.py`
2. 访问 http://localhost:5000
3. 注册账号，登录使用文件管理功能
4. 开启共享后可通过 http://localhost:5000/share/{username}/ 访问公开文件夹

注意事项：
- 部署时请修改app.config['SECRET_KEY']以保证安全
- 上传文件大小限制配置在 Flask 配置项 MAX_CONTENT_LENGTH
- 本系统演示用，适合学习参考，生产部署时请适当增强安全策略（如 HTTPS、CSRF防护等）

"""

import os
import sqlite3
from flask import (
    Flask, request, session, g, redirect, url_for, 
    abort, send_from_directory, render_template, jsonify, flash
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from functools import wraps

# === 配置部分 ===
BASE_DIR = os.path.abspath(os.path.dirname(__file__))    # 当前文件夹绝对路径
DATABASE = os.path.join(BASE_DIR, 'filehub.db')          # SQLite数据库文件路径
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')         # 上传文件存储根目录
ALLOWED_EXTENSIONS = None  # 允许上传的文件扩展名，None表示无限制，也可以指定集合
SECRET_KEY = 'your-secret-key-please-change'  # Flask session密钥，部署时一定要修改
MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 最大上传文件大小，50MB

# === Flask 应用初始化 ===
app = Flask(__name__)
app.config['DATABASE'] = DATABASE
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['SECRET_KEY'] = SECRET_KEY
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH

# === 数据库操作相关函数 ===

def get_db():
    """
    获取当前请求对应的数据库连接。
    使用 flask.g 管理同一请求内的数据库连接，避免重复打开。
    设置 row_factory 为 sqlite3.Row，使查询结果可以像字典一样访问字段。
    """
    if 'db' not in g:
        g.db = sqlite3.connect(
            app.config['DATABASE'],
            detect_types=sqlite3.PARSE_DECLTYPES
        )
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exception):
    """
    每个请求后会自动调用此函数，关闭数据库连接（如果已打开）。
    避免数据库连接泄露。
    """
    db = g.pop('db', None)
    if db is not None:
        db.close()


def init_db():
    """
    初始化数据库表结构，首次运行自动创建表。
    包含 users 用户表，files 文件表。
    """
    db = get_db()
    cursor = db.cursor()

    # 创建用户表:
    # id 主键自增
    # username 用户名唯一，不允许重复
    # password_hash 哈希过的密码
    # is_shared 标记是否公开分享，int 0/1
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            is_shared INTEGER NOT NULL DEFAULT 0
        )
    ''')

    # 文件表:
    # id 主键自增
    # user_id 外键，关联用户id
    # filename 文件名
    # order_index 排序字段，数字越小越靠前
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            filename TEXT NOT NULL,
            order_index INTEGER NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    ''')

    db.commit()

# === 用户认证相关辅助函数 ===


def login_required(f):
    """
    装饰器函数，阻止未登录用户访问被装饰的路由函数。
    如果用户未登录，则重定向到登录页面，并可跳回原请求（next）。
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            # next 用于登录成功后跳转回原页面
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function


def get_current_user():
    """
    返回当前已登录的用户记录（sqlite3.Row 类型，类似字典）或 None。
    通过 session 中存储的 user_id 进行查询。
    """
    if 'user_id' not in session:
        return None
    db = get_db()
    user = db.execute(
        "SELECT * FROM users WHERE id = ?", (session['user_id'],)
    ).fetchone()
    return user


def allowed_file(filename):
    """
    判断文件名是否允许上传。
    默认无限制（ALLOWED_EXTENSIONS = None）。
    如果想限定上传类型，可以修改 ALLOWED_EXTENSIONS 集合。
    """
    if ALLOWED_EXTENSIONS is None:
        return True
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# === 文件夹和路径相关辅助函数 ===

def get_user_upload_folder(user_id):
    """
    获取指定用户的上传文件夹路径。
    如果不存在则自动创建。
    每个用户文件保存在 uploads/{user_id}/ 目录。
    """
    folder = os.path.join(app.config['UPLOAD_FOLDER'], str(user_id))
    os.makedirs(folder, exist_ok=True)
    return folder

# === 网站路由定义 ===


@app.route('/')
@login_required
def index():
    """
    主页，显示用户文件列表及上传控件。
    """
    user = get_current_user()
    db = get_db()

    # 读取当前用户所有文件，按 order_index 升序排序
    files = db.execute(
        "SELECT filename FROM files WHERE user_id = ? ORDER BY order_index ASC",
        (user['id'],)
    ).fetchall()

    return render_template(
        'index.html',
        user=user,
        files=files
    )


@app.route('/register', methods=['GET', 'POST'])
def register():
    """
    用户注册页面。
    GET 显示注册表单，POST 处理注册逻辑。
    """
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        db = get_db()

        # 基本校验：用户名和密码不能为空
        if not username or not password:
            flash('用户名和密码不能为空')
            return redirect(url_for('register'))

        # 检查用户名是否已存在
        if db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone():
            flash('用户名已存在，请更换')
            return redirect(url_for('register'))

        # 密码哈希处理
        password_hash = generate_password_hash(password)

        # 插入新用户
        db.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (username, password_hash)
        )
        db.commit()
        flash('注册成功，请登录')
        return redirect(url_for('login'))

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    """
    用户登录页面。
    GET 显示登录表单，POST 验证用户名密码。
    成功登录保存 user_id 到 session，失败跳转回登录页。
    """
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        db = get_db()

        user = db.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()

        # 校验用户名和密码
        if user and check_password_hash(user['password_hash'], password):
            session.clear()
            session['user_id'] = user['id']
            flash('登录成功')

            # 支持登录后跳转到最初请求页面（next）
            next_url = request.args.get('next')
            return redirect(next_url or url_for('index'))
        flash('用户名或密码错误')
        return redirect(url_for('login'))

    return render_template('login.html')


@app.route('/logout')
def logout():
    """
    注销用户登录，清除 session，再跳转到登录页面。
    """
    session.clear()
    flash('已注销')
    return redirect(url_for('login'))


@app.route('/upload', methods=['POST'])
@login_required
def upload_file():
    """
    上传文件接口，使用 AJAX POST 请求。
    接收前端上传的文件单个文件，保存至用户文件夹。
    文件名安全处理，避免覆盖已有文件。
    数据库记录文件信息与排序。
    返回 JSON 结果，前端提示。
    """
    user = get_current_user()

    if 'file' not in request.files:
        return jsonify(success=False, msg='未上传文件')

    file = request.files['file']
    if file.filename == '':
        return jsonify(success=False, msg='未选择文件')

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        user_folder = get_user_upload_folder(user['id'])
        save_path = os.path.join(user_folder, filename)

        # 已有同名文件拒绝上传（避免覆盖）
        if os.path.exists(save_path):
            return jsonify(success=False, msg='文件已存在，请重命名或删除后再上传')

        file.save(save_path)

        # 更新数据库文件记录
        db = get_db()
        # 得到当前用户最大 order_index，作为新文件排序的末尾
        max_order = db.execute(
            "SELECT MAX(order_index) FROM files WHERE user_id = ?", (user['id'],)
        ).fetchone()[0]

        order_index = (max_order or 0) + 1
        db.execute(
            "INSERT INTO files (user_id, filename, order_index) VALUES (?, ?, ?)",
            (user['id'], filename, order_index)
        )
        db.commit()

        return jsonify(success=True, msg='上传成功', filename=filename)

    return jsonify(success=False, msg='文件格式不允许')


@app.route('/download/<filename>')
@login_required
def download_file(filename):
    """
    下载文件接口，通过文件名找到对应文件。
    只允许当前登录用户下载自己的文件。
    """
    user = get_current_user()
    filename = secure_filename(filename)
    db = get_db()

    file = db.execute(
        "SELECT * FROM files WHERE user_id = ? AND filename = ?", (user['id'], filename)
    ).fetchone()

    if not file:
        abort(404)

    user_folder = get_user_upload_folder(user['id'])
    file_path = os.path.join(user_folder, filename)

    if not os.path.exists(file_path):
        abort(404)

    # send_from_directory 支持断点续传和文件下载
    return send_from_directory(user_folder, filename, as_attachment=True)


@app.route('/delete', methods=['POST'])
@login_required
def delete_file():
    """
    删除文件接口，AJAX请求，接收 JSON 传入 filename。
    删除服务器文件和数据库对应记录。
    返回 JSON 反馈前端。
    """
    user = get_current_user()
    data = request.get_json(force=True)
    filename = data.get('filename')

    if not filename:
        return jsonify(success=False, msg='未指定文件名')

    filename = secure_filename(filename)
    db = get_db()

    file = db.execute(
        "SELECT * FROM files WHERE user_id = ? AND filename = ?", (user['id'], filename)
    ).fetchone()

    if not file:
        return jsonify(success=False, msg='文件不存在')

    user_folder = get_user_upload_folder(user['id'])
    file_path = os.path.join(user_folder, filename)

    try:
        if os.path.exists(file_path):
            os.remove(file_path)
        db.execute("DELETE FROM files WHERE id = ?", (file['id'],))
        db.commit()
        return jsonify(success=True)
    except Exception as e:
        return jsonify(success=False, msg=str(e))


@app.route('/rename', methods=['POST'])
@login_required
def rename_file():
    """
    重命名文件接口，AJAX，接收旧文件名和新文件名。
    安全检查文件是否存在，防止重复名，执行物理重命名和数据库更新。
    返回 JSON 结果。
    """
    user = get_current_user()
    data = request.get_json(force=True)
    old_name = data.get('old_name', '').strip()
    new_name = data.get('new_name', '').strip()

    if not old_name or not new_name:
        return jsonify(success=False, msg='文件名不能为空')

    old_name = secure_filename(old_name)
    new_name = secure_filename(new_name)

    db = get_db()

    file = db.execute(
        "SELECT * FROM files WHERE user_id = ? AND filename = ?", (user['id'], old_name)
    ).fetchone()

    if not file:
        return jsonify(success=False, msg='原文件不存在')

    # 新文件名不能已存在
    if db.execute(
        "SELECT id FROM files WHERE user_id = ? AND filename = ?", (user['id'], new_name)
    ).fetchone():
        return jsonify(success=False, msg='新文件名已存在')

    user_folder = get_user_upload_folder(user['id'])
    old_path = os.path.join(user_folder, old_name)
    new_path = os.path.join(user_folder, new_name)

    if not os.path.exists(old_path):
        return jsonify(success=False, msg='文件不存在')

    try:
        os.rename(old_path, new_path)
        db.execute(
            "UPDATE files SET filename = ? WHERE id = ?", (new_name, file['id'])
        )
        db.commit()
        return jsonify(success=True)
    except Exception as e:
        return jsonify(success=False, msg=str(e))


@app.route('/reorder', methods=['POST'])
@login_required
def reorder_files():
    """
    文件拖拽排序接口，AJAX POST接收文件名列表按顺序排列。
    遍历更新每个文件的 order_index。
    返回 JSON。
    """
    user = get_current_user()
    data = request.get_json(force=True)
    order = data.get('order', [])

    if not isinstance(order, list):
        return jsonify(success=False, msg='参数错误')

    db = get_db()
    try:
        for idx, filename in enumerate(order, 1):
            filename = secure_filename(filename)
            db.execute(
                "UPDATE files SET order_index = ? WHERE user_id = ? AND filename = ?",
                (idx, user['id'], filename)
            )
        db.commit()
        return jsonify(success=True)
    except Exception as e:
        return jsonify(success=False, msg=str(e))


@app.route('/toggle_share', methods=['POST'])
@login_required
def toggle_share():
    """
    切换用户文件夹公开分享开关。
    当用户点击切换时，通过此接口切换用户表 is_shared 字段。
    """
    user = get_current_user()
    db = get_db()
    # 反转状态 0->1 或 1->0
    new_state = 1 if user['is_shared'] == 0 else 0
    db.execute(
        "UPDATE users SET is_shared = ? WHERE id = ?", (new_state, user['id'])
    )
    db.commit()
    flash(f'分享状态更新为: {"已公开" if new_state else "未公开"}')
    return redirect(url_for('index'))


@app.route('/share/<username>/')
def share(username):
    """
    公开分享页面，允许匿名访问。
    只允许访问 is_shared=1 的用户。
    展示用户的公开文件列表，支持下载。
    """
    db = get_db()
    user = db.execute(
        "SELECT * FROM users WHERE username = ?", (username,)
    ).fetchone()

    if not user or user['is_shared'] == 0:
        abort(404)

    files = db.execute(
        "SELECT filename FROM files WHERE user_id = ? ORDER BY order_index ASC",
        (user['id'],)
    ).fetchall()

    return render_template('share.html', share_user=user, files=files)


@app.route('/share/<username>/download/<filename>')
def share_download(username, filename):
    """
    公开分享文件下载接口，匿名访问。
    需确认用户打开了公开分享，且文件存在。
    """
    filename = secure_filename(filename)
    db = get_db()
    user = db.execute(
        "SELECT * FROM users WHERE username = ?", (username,)
    ).fetchone()

    if not user or user['is_shared'] == 0:
        abort(404)

    file_record = db.execute(
        "SELECT * FROM files WHERE user_id = ? AND filename = ?", (user['id'], filename)
    ).fetchone()

    if not file_record:
        abort(404)

    user_folder = get_user_upload_folder(user['id'])
    file_path = os.path.join(user_folder, filename)

    if not os.path.exists(file_path):
        abort(404)

    return send_from_directory(user_folder, filename, as_attachment=True)

# === 模板定义 ===

# 下面以字符串形式保存 HTML 模板
# Flask 默认从 templates/ 文件夹加载，但此处内嵌方便学习和演示
# 你若想用文件形式，复制以下内容到 templates/*.html 即可。

from flask import render_template_string

# 基础模板 base.html，包含 Bootstrap、导航栏、顶部区域和底部引入资源
base_html = '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8" />
    <title>{% block title %}文件管理系统{% endblock %}</title>
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <!-- Bootstrap 5 CSS -->
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet" />
    <link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.10.5/font/bootstrap-icons.css" rel="stylesheet">
    <style>
    /* 鼠标悬浮文件列表高亮 */
    .file-row:hover {
        background-color: #f8f9fa;
        cursor: move;
    }
    /* 右键菜单样式 */
    .context-menu {
        position: absolute;
        z-index: 1050;
        width: 160px;
        background: white;
        border: 1px solid #ccc;
        box-shadow: 0 0.5rem 1rem rgb(0 0 0 / 0.15);
        display: none;
        padding: 0;
        border-radius: 0.25rem;
    }
    .context-menu ul {
        list-style: none;
        margin: 0;
        padding: 0;
    }
    .context-menu ul li {
        padding: 8px 16px;
        user-select: none;
        cursor: pointer;
    }
    .context-menu ul li:hover {
        background-color: #0d6efd;
        color: white;
    }
    </style>
    {% block head %}{% endblock %}
</head>
<body>
<nav class="navbar navbar-expand-lg navbar-light bg-light shadow-sm mb-4">
    <div class="container">
        <a class="navbar-brand" href="{{ url_for('index') }}">文件管理系统</a>
        <div class="collapse navbar-collapse justify-content-end d-flex align-items-center">
            {% if session.user_id %}
                <span class="navbar-text me-3">用户: {{ user.username }}</span>
                <a href="{{ url_for('logout') }}" class="btn btn-outline-danger btn-sm">注销</a>
            {% else %}
                <a href="{{ url_for('login') }}" class="btn btn-primary btn-sm me-2">登录</a>
                <a href="{{ url_for('register') }}" class="btn btn-secondary btn-sm">注册</a>
            {% endif %}
        </div>
    </div>
</nav>
<main class="container">
    {% with messages = get_flashed_messages() %}
      {% if messages %}
        <div class="alert alert-info" role="alert">
            {{ messages[0] }}
        </div>
      {% endif %}
    {% endwith %}
    {% block body %}{% endblock %}
</main>

<!-- Bootstrap 5 JS + Popper -->
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
<!-- jQuery 和 jQuery UI -->
<script src="https://code.jquery.com/jquery-3.6.0.min.js"></script>
<link rel="stylesheet"
      href="https://code.jquery.com/ui/1.13.2/themes/smoothness/jquery-ui.css" />
<script src="https://code.jquery.com/ui/1.13.2/jquery-ui.min.js"></script>

{% block scripts %}{% endblock %}
</body>
</html>
'''

# index.html：登录用户文件管理界面
index_html = '''
{% extends 'base.html' %}
{% block title %}我的文件 - 文件管理系统{% endblock %}
{% block body %}
<h2 class="mb-4">
    我的文件
    <form class="d-inline float-end" method="post" action="{{ url_for('toggle_share') }}">
        {% if user.is_shared == 1 %}
        <button type="submit" class="btn btn-success btn-sm" title="点击取消共享">
            <i class="bi bi-upload"></i> 文件夹已公开（点击取消）
        </button>
        {% else %}
        <button type="submit" class="btn btn-outline-secondary btn-sm" title="点击共享文件夹">
            <i class="bi bi-upload"></i> 共享我的文件夹
        </button>
        {% endif %}
    </form>
</h2>

<form id="uploadForm" class="mb-3" enctype="multipart/form-data" novalidate>
    <div class="input-group">
        <input class="form-control" type="file" name="file" id="fileInput" required>
        <button class="btn btn-primary" type="submit">上传</button>
    </div>
    <div id="uploadMsg" class="form-text"></div>
</form>

<div class="table-responsive">
    <table class="table table-bordered table-hover align-middle">
        <thead class="table-light">
            <tr>
                <th scope="col" style="width: 70%;">文件名</th>
                <th scope="col" style="width: 30%;">操作</th>
            </tr>
        </thead>
        <tbody id="filesBody">
            {% for f in files %}
            <tr data-filename="{{ f['filename'] }}" class="file-row">
                <td class="filename">{{ f['filename'] }}</td>
                <td>
                    <a href="{{ url_for('download_file', filename=f['filename']) }}" target="_blank" class="btn btn-sm btn-success">下载</a>
                    <button class="btn btn-sm btn-danger deleteFile" data-filename="{{ f['filename'] }}">删除</button>
                </td>
            </tr>
            {% else %}
            <tr><td colspan="2" class="text-center text-muted">暂无文件</td></tr>
            {% endfor %}
        </tbody>
    </table>
</div>

<!-- 右键菜单 -->
<div id="contextMenu" class="context-menu">
    <ul>
        <li id="renameAction">重命名</li>
    </ul>
</div>
{% endblock %}

{% block scripts %}
<script>
$(function(){
    // 上传文件监听，AJAX提交
    $('#uploadForm').on('submit', function(e){
        e.preventDefault();
        let fileInput = $('#fileInput')[0];
        if(fileInput.files.length === 0){
            $('#uploadMsg').addClass('text-danger').removeClass('text-success').text('请选择文件');
            return;
        }
        let formData = new FormData();
        formData.append('file', fileInput.files[0]);

        $.ajax({
            url: '/upload',
            type: 'POST',
            data: formData,
            processData: false,
            contentType: false,
            success: function(res){
                if(res.success){
                    $('#uploadMsg').addClass('text-success').removeClass('text-danger').text(res.msg);
                    addFileRow(res.filename);
                    $('#fileInput').val('');
                } else {
                    $('#uploadMsg').addClass('text-danger').removeClass('text-success').text(res.msg);
                }
            },
            error: function(xhr){
                $('#uploadMsg').addClass('text-danger').removeClass('text-success').text(xhr.responseJSON ? xhr.responseJSON.msg : '上传失败');
            }
        });
    });

    // 动态添加新上传文件行
    function addFileRow(filename){
        if($('#filesBody tr').length === 1 && $('#filesBody tr td').length === 1) {
            $('#filesBody').empty();
        }
        let row = `<tr data-filename="${filename}" class="file-row">
            <td class="filename">${filename}</td>
            <td>
                <a href="/download/${filename}" target="_blank" class="btn btn-sm btn-success">下载</a>
                <button class="btn btn-sm btn-danger deleteFile" data-filename="${filename}">删除</button>
            </td>
        </tr>`;
        $('#filesBody').append(row);
    }

    // 删除文件按钮绑定事件，发送AJAX删除请求
    $(document).on('click', '.deleteFile', function(){
        let filename = $(this).data('filename');
        if(!confirm(`确定删除文件 "${filename}" 吗？`)) return;

        $.ajax({
            url: '/delete',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({filename: filename}),
            success: function(res){
                if(res.success){
                    $(`tr[data-filename="${filename}"]`).remove();
                    if($('#filesBody tr').length === 0){
                        $('#filesBody').append('<tr><td colspan="2" class="text-center text-muted">暂无文件</td></tr>');
                    }
                } else {
                    alert(res.msg);
                }
            },
            error: function(xhr){
                alert(xhr.responseJSON ? xhr.responseJSON.msg : '删除失败');
            }
        });
    });

    // 右键菜单控制
    let $contextMenu = $('#contextMenu');
    let currentRow = null;

    // 监听文件行右键事件，显示自定义菜单
    $(document).on('contextmenu', 'tr.file-row', function(e){
        e.preventDefault();
        currentRow = $(this);
        let x = e.pageX, y = e.pageY;
        $contextMenu.css({top: y + 'px', left: x + 'px'}).show();
    });

    // 点击空白关闭菜单
    $(document).click(function(e){
        if(!$(e.target).closest('#contextMenu').length){
            $contextMenu.hide();
            cancelRename();
        }
    });

    // 菜单点击重命名触发编辑
    $('#renameAction').on('click', function(){
        $contextMenu.hide();
        startRename();
    });

    // 开启重命名编辑框
    function startRename(){
        let $filenameTd = currentRow.find('.filename');
        let oldName = $filenameTd.text();

        // 用input替换文本
        let input = $('<input type="text" id="renameInput" class="form-control form-control-sm" style="width: 90%;">').val(oldName);
        $filenameTd.empty().append(input);
        input.focus().select();

        // 键盘事件 Enter 提交，Esc 取消
        input.on('keydown', function(e){
            if(e.key === 'Enter'){
                submitRename(oldName, input.val());
            } else if(e.key === 'Escape'){
                cancelRename();
            }
        });

        // 失去焦点自动提交
        input.on('blur', function(){
            submitRename(oldName, input.val());
        });
    }

    // 取消重命名，恢复旧名显示
    function cancelRename(){
        if(!currentRow) return;
        let oldName = currentRow.data('filename');
        currentRow.find('.filename').text(oldName);
    }

    // 提交重命名请求
    function submitRename(oldName, newName){
        newName = newName.trim();
        if(newName === ''){
            alert('新文件名不能为空');
            cancelRename();
            return;
        }
        if(newName === oldName){
            cancelRename();
            return;
        }

        $.ajax({
            url: '/rename',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({old_name: oldName, new_name: newName}),
            success: function(res){
                if(res.success){
                    // 更新UI：data-filename、文件名列、下载和删除按钮 data属性
                    currentRow.attr('data-filename', newName);
                    currentRow.find('.filename').text(newName);
                    currentRow.find('a[href^="/download/"]').attr('href', '/download/' + newName);
                    currentRow.find('.deleteFile').data('filename', newName);
                } else {
                    alert(res.msg);
                    cancelRename();
                }
            },
            error: function(xhr){
                alert(xhr.responseJSON ? xhr.responseJSON.msg : '重命名失败');
                cancelRename();
            }
        });
    }

    // 启用拖拽排序，更新排序后发送请求保存
    $("#filesBody").sortable({
        axis: "y",
        cursor: "move",
        update: function(){
            let order = [];
            $('#filesBody tr').each(function(){
                order.push($(this).data('filename'));
            });
            $.ajax({
                url: '/reorder',
                type: 'POST',
                contentType: 'application/json',
                data: JSON.stringify({order: order}),
                success: function(res){
                    if(!res.success){
                        alert('保存排序失败: ' + res.msg);
                    }
                },
                error: function(){
                    alert('保存排序失败');
                }
            });
        }
    }).disableSelection();

});
</script>
{% endblock %}
'''

# 登录页 login.html
login_html = '''
{% extends 'base.html' %}
{% block title %}登录 - 文件管理系统{% endblock %}
{% block body %}
<h2 class="mb-4">登录</h2>
<form method="post" class="col-md-4">
    <div class="mb-3">
        <label class="form-label">用户名</label>
        <input type="text" name="username" class="form-control" required autofocus>
    </div>
    <div class="mb-3">
        <label class="form-label">密码</label>
        <input type="password" name="password" class="form-control" required>
    </div>
    <button type="submit" class="btn btn-primary">登录</button>
    <a href="{{ url_for('register') }}" class="btn btn-link">注册新账号</a>
</form>
{% endblock %}
'''

# 注册页 register.html
register_html = '''
{% extends 'base.html' %}
{% block title %}注册 - 文件管理系统{% endblock %}
{% block body %}
<h2 class="mb-4">注册</h2>
<form method="post" class="col-md-4">
    <div class="mb-3">
        <label class="form-label">用户名</label>
        <input type="text" name="username" class="form-control" required autofocus>
    </div>
    <div class="mb-3">
        <label class="form-label">密码</label>
        <input type="password" name="password" class="form-control" required>
    </div>
    <button type="submit" class="btn btn-primary">注册</button>
    <a href="{{ url_for('login') }}" class="btn btn-link">返回登录</a>
</form>
{% endblock %}
'''

# 公开分享 share.html
share_html = '''
{% extends 'base.html' %}
{% block title %}{{ share_user.username }} 的共享文件夹 - 文件管理系统{% endblock %}
{% block body %}
<h2 class="mb-4">{{ share_user.username }} 的共享文件夹</h2>

{% if files|length == 0 %}
  <p class="text-muted">该用户公开的文件夹为空。</p>
{% else %}
<div class="table-responsive">
    <table class="table table-bordered table-hover align-middle">
        <thead class="table-light">
            <tr>
                <th scope="col" style="width: 70%;">文件名</th>
                <th scope="col" style="width: 30%;">操作</th>
            </tr>
        </thead>
        <tbody>
            {% for file in files %}
            <tr>
                <td>{{ file.filename }}</td>
                <td>
                    <a href="{{ url_for('share_download', username=share_user.username, filename=file.filename) }}" target="_blank" class="btn btn-sm btn-success">下载</a>
                </td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
</div>
{% endif %}
{% endblock %}
'''

# === Flask 框架自定义模板渲染相关 ===

@app.context_processor
def inject_user():
    """
    全局上下文，模板中自动传入当前登录用户 user 对象。
    方便模板中直接访问 user.username 等。
    """
    user = get_current_user()
    return dict(user=user)


@app.route('/favicon.ico')
def favicon():
    """
    浏览器自动访问网站根目录 /favicon.ico 时返回空响应。
    避免报错。
    """
    return '', 204


@app.before_first_request
def setup():
    """
    Flask首次请求之前执行一次，初始化数据库表和存储目录。
    """
    init_db()
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)


@app.template_global()
def include_raw(template_name):
    """
    方便内嵌模板中快速指定include。
    这里程序不使用实际include，因为是内嵌模板，需特殊处理。
    """
    templates_map = {
        'base.html': base_html,
        'index.html': index_html,
        'login.html': login_html,
        'register.html': register_html,
        'share.html': share_html,
    }
    return templates_map.get(template_name, '')


def render_template(template_name_or_list, **context):
    """
    重写 Flask render_template 以支持上述内嵌模板字符串加载，
    读取内存字典中的模板源，避免硬盘模板文件依赖。
    """
    templates_map = {
        'base.html': base_html,
        'index.html': index_html,
        'login.html': login_html,
        'register.html': register_html,
        'share.html': share_html,
    }
    source = templates_map.get(template_name_or_list)
    if source is None:
        abort(500, description=f'模板不存在: {template_name_or_list}')
    return render_template_string(source, **context)


if __name__ == '__main__':
    # 运行 Flask 内置服务器，监听0.0.0.0允许局域网访问
    # debug=True 启用调试自动重载，生产应关闭
    app.run(host='0.0.0.0', port=5000, debug=True)
