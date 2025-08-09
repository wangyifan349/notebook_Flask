# -*- coding: utf-8 -*-
"""
Flask 后端示例

功能：
1. 用户注册
2. 用户登录
3. 用户登出
4. 上传视频
5. 获取用户视频列表
6. 全局搜索视频（按视频名称）
7. 按用户名搜索视频
8. 下载视频
9. 重命名视频
10. 删除视频
11. 在线播放视频
12. 提供多个前端静态页面

依赖：
- Flask
- Flask-CORS
- Werkzeug

安装依赖：
pip install flask flask-cors werkzeug

运行：
python app.py

说明：
- 用户信息保存在 users.json 文件中
- 上传的视频保存在 uploads/<user_id>/ 目录下
- 所有前端页面嵌入在 app.py 中，无需单独的 HTML 文件
"""

import os
import json
import uuid
import re
import unicodedata
from flask import Flask, request, jsonify, send_from_directory, redirect, url_for, session, Response
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
CORS(app)  # 允许所有跨域请求，生产环境中可根据需要配置

# 配置
USER_FILE = 'users.json'           # 用户信息存储文件
UPLOAD_ROOT = 'uploads'            # 上传文件的根目录
ALLOWED_EXTENSIONS = {'mp4', 'avi', 'mov', 'mkv'}  # 允许上传的视频格式
app.config['MAX_CONTENT_LENGTH'] = 1000 * 1024 * 1024  # 最大上传大小：1000MB
app.secret_key = 'your_secret_key_here'  # 替换为你的秘密密钥，确保安全

# 确保上传目录存在
os.makedirs(UPLOAD_ROOT, exist_ok=True)

# 初始化用户数据文件
if not os.path.exists(USER_FILE):
    with open(USER_FILE, 'w', encoding='utf-8') as f:
        json.dump({}, f, ensure_ascii=False)

def load_users():
    """
    从 JSON 文件中加载用户数据
    返回格式：
    {
        "username1": {
            "id": "uuid1",
            "password": "hashed_password1"
        },
        "username2": {
            "id": "uuid2",
            "password": "hashed_password2"
        },
        ...
    }
    """
    with open(USER_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_users(users):
    """
    将用户数据保存回 JSON 文件
    """
    with open(USER_FILE, 'w', encoding='utf-8') as f:
        json.dump(users, f, ensure_ascii=False, indent=4)

def allowed_file(filename):
    """
    检查文件是否允许上传
    """
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def secure_filename_unicode(filename):
    """
    自定义的 secure_filename 函数，保留中文字符，同时移除或替换其他潜在危险字符。
    """
    # 正规化 Unicode
    filename = unicodedata.normalize('NFKC', filename).strip()
    # 移除路径分隔符
    filename = re.sub(r'[\\/]+', '_', filename)
    # 保留字母、数字、下划线、点、破折号和中文字符，其他字符替换为下划线
    filename = re.sub(r'[^\w\.\-一-龥]', '_', filename)
    return filename

# =========================
# API 路由
# =========================

@app.route('/register', methods=['POST'])
def register_api():
    """
    用户注册接口（API）
    请求数据（JSON）：
    {
        "username": "desired_username",
        "password": "desired_password"
    }
    返回：
    成功：201 Created
    失败：400 Bad Request
    """
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return jsonify({'error': '用户名和密码是必需的'}), 400

    users = load_users()

    if username in users:
        return jsonify({'error': '用户名已存在'}), 400

    hashed_password = generate_password_hash(password)
    user_id = str(uuid.uuid4())
    users[username] = {'id': user_id, 'password': hashed_password}

    # 为用户创建专属上传目录
    user_dir = os.path.join(UPLOAD_ROOT, user_id)
    os.makedirs(user_dir, exist_ok=True)

    save_users(users)
    return jsonify({'message': '用户注册成功'}), 201

@app.route('/login', methods=['POST'])
def login_api():
    """
    用户登录接口（API）
    请求数据（JSON）：
    {
        "username": "your_username",
        "password": "your_password"
    }
    返回：
    成功：200 OK + 用户信息
    失败：401 Unauthorized
    """
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return jsonify({'error': '用户名和密码是必需的'}), 400

    users = load_users()
    user = users.get(username)

    if user and check_password_hash(user['password'], password):
        # 设置会话
        session['user_id'] = user['id']
        session['username'] = username
        return jsonify({'message': '登录成功', 'user_id': user['id'], 'username': username}), 200

    return jsonify({'error': '无效的凭证'}), 401

@app.route('/logout', methods=['POST'])
def logout_api():
    """
    用户登出接口（API）
    清除会话信息
    返回：
    成功：200 OK
    """
    session.pop('user_id', None)
    session.pop('username', None)
    return jsonify({'message': '登出成功'}), 200

@app.route('/upload', methods=['POST'])
def upload_api():
    """
    视频上传接口（API）
    请求数据（multipart/form-data）：
    - file: 上传的文件
    返回：
    成功：201 Created
    失败：400 Bad Request 或 404 Not Found
    """
    if 'user_id' not in session:
        return jsonify({'error': '未登录'}), 401

    user_id = session['user_id']
    file = request.files.get('file')

    if not file:
        return jsonify({'error': '未提供文件'}), 400

    if not allowed_file(file.filename):
        return jsonify({'error': '不允许的文件类型'}), 400

    user_dir = os.path.join(UPLOAD_ROOT, user_id)
    if not os.path.exists(user_dir):
        return jsonify({'error': '用户目录不存在'}), 404

    filename = secure_filename_unicode(file.filename)

    # 防止文件覆盖
    if os.path.exists(os.path.join(user_dir, filename)):
        return jsonify({'error': '文件已存在'}), 400

    file.save(os.path.join(user_dir, filename))
    return jsonify({'message': '视频上传成功'}), 201

@app.route('/videos', methods=['GET'])
def get_videos_api():
    """
    获取当前用户的视频列表（API）
    返回：
    成功：200 OK + 视频文件列表
    失败：404 Not Found 或 401 Unauthorized
    """
    if 'user_id' not in session:
        return jsonify({'error': '未登录'}), 401

    user_id = session['user_id']
    user_dir = os.path.join(UPLOAD_ROOT, user_id)
    if not os.path.exists(user_dir):
        return jsonify({'error': '用户目录不存在'}), 404

    videos = os.listdir(user_dir)
    return jsonify({'videos': videos}), 200

def search_videos(video_name=None, username=None):
    """
    搜索视频的匹配机制函数。
    - video_name: 按视频名称搜索（可以是部分名称）
    - username: 按用户名搜索其所有视频

    返回：
    - 如果仅提供 video_name，则返回全局匹配的视频列表
    - 如果仅提供 username，则返回该用户的所有视频
    - 如果同时提供两个参数，则返回该用户中匹配视频名称的视频列表
    """
    users = load_users()
    matched_videos = []

    if video_name and username:
        user = users.get(username)
        if user:
            user_id = user['id']
            user_dir = os.path.join(UPLOAD_ROOT, user_id)
            if os.path.exists(user_dir):
                for video in os.listdir(user_dir):
                    if video_name.lower() in video.lower():
                        matched_videos.append({
                            'username': username,
                            'video_name': video
                        })
    elif video_name:
        for uname, user in users.items():
            user_id = user['id']
            user_dir = os.path.join(UPLOAD_ROOT, user_id)
            if not os.path.exists(user_dir):
                continue
            for video in os.listdir(user_dir):
                if video_name.lower() in video.lower():
                    matched_videos.append({
                        'username': uname,
                        'video_name': video
                    })
    elif username:
        user = users.get(username)
        if user:
            user_id = user['id']
            user_dir = os.path.join(UPLOAD_ROOT, user_id)
            if os.path.exists(user_dir):
                for video in os.listdir(user_dir):
                    matched_videos.append({
                        'username': username,
                        'video_name': video
                    })
    return matched_videos

@app.route('/search_videos', methods=['GET'])
def search_videos_api():
    """
    全局搜索视频（按视频名称，所有用户）
    请求参数：
    - video_name: 要搜索的视频名称（可以是部分名称）
    返回：
    成功：200 OK + 匹配的视频列表
    失败：404 Not Found 或 400 Bad Request
    """
    video_name = request.args.get('video_name')

    if not video_name:
        return jsonify({'error': '视频名称是必需的'}), 400

    matched_videos = search_videos(video_name=video_name)

    if not matched_videos:
        return jsonify({'error': '未找到匹配的视频'}), 404

    return jsonify({'matched_videos': matched_videos}), 200

@app.route('/search_user_videos', methods=['GET'])
def search_user_videos_api():
    """
    按用户名搜索该用户的所有视频
    请求参数：
    - username: 要搜索的用户名
    返回：
    成功：200 OK + 视频文件列表
    失败：404 Not Found 或 400 Bad Request
    """
    username = request.args.get('username')

    if not username:
        return jsonify({'error': '用户名是必需的'}), 400

    matched_videos = search_videos(username=username)

    if not matched_videos:
        return jsonify({'error': '未找到匹配的视频或用户没有上传任何视频'}), 404

    return jsonify({'matched_videos': matched_videos}), 200

@app.route('/download/<username>/<filename>', methods=['GET'])
def download_file_api(username, filename):
    """
    下载指定用户的视频文件（API）
    路径参数：
    - username: 用户名
    - filename: 文件名
    返回：
    成功：文件内容
    失败：404 Not Found
    """
    users = load_users()
    user = users.get(username)

    if not user:
        return jsonify({'error': '用户未找到'}), 404

    user_id = user['id']
    user_dir = os.path.join(UPLOAD_ROOT, user_id)

    if not os.path.exists(user_dir):
        return jsonify({'error': '用户目录不存在'}), 404

    file_path = os.path.join(user_dir, filename)
    if not os.path.exists(file_path):
        return jsonify({'error': '文件未找到'}), 404

    return send_from_directory(user_dir, filename, as_attachment=True)

@app.route('/stream/<username>/<filename>', methods=['GET'])
def stream_file_api(username, filename):
    """
    在线播放指定用户的视频文件（API）
    路径参数：
    - username: 用户名
    - filename: 文件名
    返回：
    成功：文件内容以流形式传输
    失败：404 Not Found
    """
    users = load_users()
    user = users.get(username)

    if not user:
        return jsonify({'error': '用户未找到'}), 404

    user_id = user['id']
    user_dir = os.path.join(UPLOAD_ROOT, user_id)

    if not os.path.exists(user_dir):
        return jsonify({'error': '用户目录不存在'}), 404

    file_path = os.path.join(user_dir, filename)
    if not os.path.exists(file_path):
        return jsonify({'error': '文件未找到'}), 404

    return send_from_directory(user_dir, filename, as_attachment=False)

@app.route('/rename', methods=['POST'])
def rename_video_api():
    """
    重命名视频接口（API）
    请求数据（JSON）：
    {
        "old_filename": "旧文件名",
        "new_filename": "新文件名"
    }
    返回：
    成功：200 OK
    失败：400 Bad Request 或 404 Not Found
    """
    if 'user_id' not in session:
        return jsonify({'error': '未登录'}), 401

    data = request.get_json()
    old_filename = data.get('old_filename')
    new_filename = data.get('new_filename')

    if not old_filename or not new_filename:
        return jsonify({'error': 'old_filename 和 new_filename 是必需的'}), 400

    if not allowed_file(new_filename):
        return jsonify({'error': '不允许的文件类型'}), 400

    filename_ext = new_filename.rsplit('.', 1)[1].lower()
    if filename_ext not in ALLOWED_EXTENSIONS:
        return jsonify({'error': '不允许的文件类型'}), 400

    user_id = session['user_id']
    user_dir = os.path.join(UPLOAD_ROOT, user_id)

    if not os.path.exists(user_dir):
        return jsonify({'error': '用户目录不存在'}), 404

    old_file_path = os.path.join(user_dir, secure_filename_unicode(old_filename))
    new_file_path = os.path.join(user_dir, secure_filename_unicode(new_filename))

    if not os.path.exists(old_file_path):
        return jsonify({'error': '旧文件未找到'}), 404

    if os.path.exists(new_file_path):
        return jsonify({'error': '新文件名已存在'}), 400

    os.rename(old_file_path, new_file_path)
    return jsonify({'message': '视频重命名成功'}), 200

@app.route('/delete', methods=['POST'])
def delete_video_api():
    """
    删除视频接口（API）
    请求数据（JSON）：
    {
        "filename": "要删除的文件名"
    }
    返回：
    成功：200 OK
    失败：400 Bad Request 或 404 Not Found
    """
    if 'user_id' not in session:
        return jsonify({'error': '未登录'}), 401

    data = request.get_json()
    filename = data.get('filename')

    if not filename:
        return jsonify({'error': 'filename 是必需的'}), 400

    user_id = session['user_id']
    user_dir = os.path.join(UPLOAD_ROOT, user_id)
    file_path = os.path.join(user_dir, secure_filename_unicode(filename))

    if not os.path.exists(user_dir):
        return jsonify({'error': '用户目录不存在'}), 404

    if not os.path.exists(file_path):
        return jsonify({'error': '文件未找到'}), 404

    try:
        os.remove(file_path)
        return jsonify({'message': '视频删除成功'}), 200
    except Exception as e:
        return jsonify({'error': f'删除失败: {str(e)}'}), 500

# =========================
# 安全策略控制函数
# =========================

def apply_security_headers(app):
    """
    封装的函数，用于设置浏览器的安全策略。
    目前未启用，需手动调用此函数以应用安全策略。
    """
    @app.after_request
    def set_security_headers(response):
        # 设置内容安全策略（CSP）
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; "
            "script-src 'self' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://unpkg.com https://www.gstatic.com; "
            "style-src 'self' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://unpkg.com https://fonts.googleapis.com; "
            "img-src 'self' data:; "
            "font-src 'self' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://fonts.gstatic.com; "
            "frame-ancestors 'none';"
        )
        # 其他安全头
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        response.headers['Referrer-Policy'] = 'no-referrer'
        
        return response

# =========================
# 前端页面路由
# =========================

# 定义多个 HTML 页面作为多路由响应
@app.route('/')
def serve_index():
    """
    首页路由，返回主页 HTML
    """
    return index_html()

@app.route('/register.html')
def serve_register():
    """
    注册页面路由，返回注册页面 HTML
    """
    return register_html()

@app.route('/login.html')
def serve_login():
    """
    登录页面路由，返回登录页面 HTML
    """
    return login_html()

@app.route('/upload.html')
def serve_upload():
    """
    上传视频页面路由，返回上传页面 HTML
    """
    return upload_html()

@app.route('/my_videos.html')
def serve_my_videos():
    """
    我的视屏列表页面路由，返回我的视频页面 HTML
    """
    return my_videos_html()

@app.route('/search.html')
def serve_search():
    """
    搜索视频页面路由，返回搜索视频页面 HTML
    """
    return search_html()

# =========================
# 前端 HTML 页面定义
# =========================

def index_html():
    """
    首页 HTML 内容
    """
    return """
    <!DOCTYPE html>
    <html lang="zh-CN">
    <head>
        <meta charset="UTF-8">
        <title>首页 - 视频管理系统</title>
        <!-- 引入 Bootstrap (Bootswatch 的 Minty 绿色主题) -->
        <link 
            rel="stylesheet" 
            href="https://cdn.jsdelivr.net/npm/bootswatch@5.3.0/dist/minty/bootstrap.min.css" 
            crossorigin="anonymous">
        <style>
            body {
                padding-top: 70px;
                background-color: #f8f9fa;
            }
            .jumbotron {
                background-color: #ffffff;
                padding: 2rem 1rem;
                border-radius: 0.3rem;
                box-shadow: 0 0.125rem 0.25rem rgba(0, 0, 0, 0.075);
            }
        </style>
    </head>
    <body>

    <!-- 导航栏 -->
    <nav class="navbar navbar-expand-lg navbar-dark bg-primary fixed-top">
      <div class="container-fluid">
        <a class="navbar-brand" href="/">视频管理系统</a>
        <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#navbarNav" 
            aria-controls="navbarNav" aria-expanded="false" aria-label="Toggle navigation">
          <span class="navbar-toggler-icon"></span>
        </button>
        <div class="collapse navbar-collapse" id="navbarNav">
          <ul class="navbar-nav ms-auto" id="navbar-links">
            <!-- 动态生成导航链接 -->
          </ul>
        </div>
      </div>
    </nav>

    <!-- 主内容 -->
    <div class="container">
        <div class="jumbotron text-center">
            <h1 class="display-4">欢迎来到视频管理系统！</h1>
            <p class="lead">轻松管理、上传和分享你的视频。</p>
            <hr class="my-4">
            <div id="welcome-message">
                <!-- 动态生成欢迎信息 -->
            </div>
            <div id="action-buttons">
                <!-- 动态生成行动按钮 -->
            </div>
        </div>
    </div>

    <!-- JavaScript 逻辑 -->
    <script>
        // 获取用户登录状态
        const user_id = sessionStorage.getItem('user_id');
        const username = sessionStorage.getItem('username');

        const navbarLinks = document.getElementById('navbar-links');
        const welcomeMessage = document.getElementById('welcome-message');
        const actionButtons = document.getElementById('action-buttons');

        if (user_id && username) {
            // 已登录用户
            navbarLinks.innerHTML = `
                <li class="nav-item">
                  <a class="nav-link" href="/upload.html">上传视频</a>
                </li>
                <li class="nav-item">
                  <a class="nav-link" href="/my_videos.html">我的视频</a>
                </li>
                <li class="nav-item">
                  <a class="nav-link" href="/search.html">搜索视频</a>
                </li>
                <li class="nav-item">
                  <a class="nav-link" href="#" onclick="logout()">登出</a>
                </li>
            `;

            welcomeMessage.innerHTML = `<p class="lead">欢迎，<strong>${username}</strong>！</p>`;
            actionButtons.innerHTML = `
                <a class="btn btn-success btn-lg me-2" href="/upload.html" role="button">上传视频</a>
                <a class="btn btn-primary btn-lg" href="/my_videos.html" role="button">查看我的视频</a>
            `;
        } else {
            // 未登录用户
            navbarLinks.innerHTML = `
                <li class="nav-item">
                  <a class="nav-link active" href="/register.html">注册</a>
                </li>
                <li class="nav-item">
                  <a class="nav-link" href="/login.html">登录</a>
                </li>
                <li class="nav-item">
                  <a class="nav-link" href="/search.html">搜索视频</a>
                </li>
            `;

            welcomeMessage.innerHTML = `<p class="lead">请登录或注册以开始使用。</p>`;
            actionButtons.innerHTML = `
                <a class="btn btn-success btn-lg me-2" href="/register.html" role="button">注册</a>
                <a class="btn btn-primary btn-lg" href="/login.html" role="button">登录</a>
            `;
        }

        // 登出功能
        async function logout() {
            try {
                const response = await fetch('/logout', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                });
                const result = await response.json();

                if (response.ok) {
                    // 清除前端会话
                    sessionStorage.removeItem('user_id');
                    sessionStorage.removeItem('username');
                    // 重新加载页面
                    window.location.reload();
                } else {
                    alert(`登出失败：${result.error}`);
                }
            } catch (error) {
                console.error(error);
                alert('请求异常，请检查控制台。');
            }
        }
    </script>

    <!-- 引入 Bootstrap JS -->
    <script 
        src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js" 
        crossorigin="anonymous">
    </script>
    </body>
    </html>
    """

def register_html():
    """
    注册页面 HTML 内容
    """
    return """
    <!DOCTYPE html>
    <html lang="zh-CN">
    <head>
        <meta charset="UTF-8">
        <title>注册 - 视频管理系统</title>
        <!-- 引入 Bootstrap (Bootswatch 的 Minty 绿色主题) -->
        <link 
            rel="stylesheet" 
            href="https://cdn.jsdelivr.net/npm/bootswatch@5.3.0/dist/minty/bootstrap.min.css" 
            crossorigin="anonymous">
        <style>
            body {
                padding-top: 70px;
                background-color: #f8f9fa;
            }
            .form-container {
                background-color: #ffffff;
                padding: 2rem;
                border-radius: 0.3rem;
                box-shadow: 0 0.125rem 0.25rem rgba(0, 0, 0, 0.075);
            }
        </style>
    </head>
    <body>

    <!-- 导航栏 -->
    <nav class="navbar navbar-expand-lg navbar-dark bg-primary fixed-top">
      <div class="container-fluid">
        <a class="navbar-brand" href="/">视频管理系统</a>
        <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#navbarNav" 
            aria-controls="navbarNav" aria-expanded="false" aria-label="Toggle navigation">
          <span class="navbar-toggler-icon"></span>
        </button>
        <div class="collapse navbar-collapse" id="navbarNav">
          <ul class="navbar-nav ms-auto" id="navbar-links">
            <!-- 动态生成导航链接 -->
          </ul>
        </div>
      </div>
    </nav>

    <!-- 主内容 -->
    <div class="container d-flex justify-content-center">
        <div class="form-container mt-5">
            <h2 class="mb-4 text-center">用户注册</h2>
            <form id="register-form">
                <div class="mb-3">
                    <label for="reg-username" class="form-label">用户名</label>
                    <input type="text" class="form-control" id="reg-username" required>
                </div>
                <div class="mb-3">
                    <label for="reg-password" class="form-label">密码</label>
                    <input type="password" class="form-control" id="reg-password" required>
                </div>
                <button type="submit" class="btn btn-success w-100">注册</button>
            </form>
            <div id="register-result" class="mt-3"></div>
        </div>
    </div>

    <!-- JavaScript 逻辑 -->
    <script>
        // 更新导航栏
        const navbarLinks = document.getElementById('navbar-links');
        navbarLinks.innerHTML = `
            <li class="nav-item">
              <a class="nav-link active" href="/register.html">注册</a>
            </li>
            <li class="nav-item">
              <a class="nav-link" href="/login.html">登录</a>
            </li>
            <li class="nav-item">
              <a class="nav-link" href="/search.html">搜索视频</a>
            </li>
        `;

        document.getElementById('register-form').addEventListener('submit', async function(e) {
            e.preventDefault();
            const username = document.getElementById('reg-username').value.trim();
            const password = document.getElementById('reg-password').value.trim();

            if (!username || !password) {
                displayResult('请输入用户名和密码！', 'danger');
                return;
            }

            try {
                const response = await fetch('/register', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ username, password })
                });
                const result = await response.json();

                if (response.ok) {
                    displayResult('注册成功！即将跳转到登录页面...', 'success');
                    setTimeout(() => {
                        window.location.href = '/login.html';
                    }, 1500);
                } else {
                    displayResult(`注册失败：${result.error}`, 'danger');
                }
            } catch (error) {
                console.error(error);
                displayResult('请求异常，请检查控制台。', 'danger');
            }
        });

        function displayResult(message, type) {
            const resultDiv = document.getElementById('register-result');
            resultDiv.innerHTML = `<div class="alert alert-${type}" role="alert">${message}</div>`;
        }
    </script>

    <!-- 引入 Bootstrap JS -->
    <script 
        src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js" 
        crossorigin="anonymous">
    </script>
    </body>
    </html>
    """

def login_html():
    """
    登录页面 HTML 内容
    """
    return """
    <!DOCTYPE html>
    <html lang="zh-CN">
    <head>
        <meta charset="UTF-8">
        <title>登录 - 视频管理系统</title>
        <!-- 引入 Bootstrap (Bootswatch 的 Minty 绿色主题) -->
        <link 
            rel="stylesheet" 
            href="https://cdn.jsdelivr.net/npm/bootswatch@5.3.0/dist/minty/bootstrap.min.css" 
            crossorigin="anonymous">
        <style>
            body {
                padding-top: 70px;
                background-color: #f8f9fa;
            }
            .form-container {
                background-color: #ffffff;
                padding: 2rem;
                border-radius: 0.3rem;
                box-shadow: 0 0.125rem 0.25rem rgba(0, 0, 0, 0.075);
            }
        </style>
    </head>
    <body>

    <!-- 导航栏 -->
    <nav class="navbar navbar-expand-lg navbar-dark bg-primary fixed-top">
      <div class="container-fluid">
        <a class="navbar-brand" href="/">视频管理系统</a>
        <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#navbarNav" 
            aria-controls="navbarNav" aria-expanded="false" aria-label="Toggle navigation">
          <span class="navbar-toggler-icon"></span>
        </button>
        <div class="collapse navbar-collapse" id="navbarNav">
          <ul class="navbar-nav ms-auto" id="navbar-links">
            <!-- 动态生成导航链接 -->
          </ul>
        </div>
      </div>
    </nav>

    <!-- 主内容 -->
    <div class="container d-flex justify-content-center">
        <div class="form-container mt-5">
            <h2 class="mb-4 text-center">用户登录</h2>
            <form id="login-form">
                <div class="mb-3">
                    <label for="login-username" class="form-label">用户名</label>
                    <input type="text" class="form-control" id="login-username" required>
                </div>
                <div class="mb-3">
                    <label for="login-password" class="form-label">密码</label>
                    <input type="password" class="form-control" id="login-password" required>
                </div>
                <button type="submit" class="btn btn-primary w-100">登录</button>
            </form>
            <div id="login-result" class="mt-3"></div>
        </div>
    </div>

    <!-- JavaScript 逻辑 -->
    <script>
        // 更新导航栏
        const navbarLinks = document.getElementById('navbar-links');
        navbarLinks.innerHTML = `
            <li class="nav-item">
              <a class="nav-link" href="/register.html">注册</a>
            </li>
            <li class="nav-item">
              <a class="nav-link active" href="/login.html">登录</a>
            </li>
            <li class="nav-item">
              <a class="nav-link" href="/search.html">搜索视频</a>
            </li>
        `;

        document.getElementById('login-form').addEventListener('submit', async function(e) {
            e.preventDefault();
            const username = document.getElementById('login-username').value.trim();
            const password = document.getElementById('login-password').value.trim();

            if (!username || !password) {
                displayResult('请输入用户名和密码！', 'danger');
                return;
            }

            try {
                const response = await fetch('/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ username, password })
                });
                const result = await response.json();

                if (response.ok) {
                    displayResult('登录成功！即将跳转...', 'success');
                    // 将用户信息存储在 sessionStorage
                    sessionStorage.setItem('user_id', result.user_id);
                    sessionStorage.setItem('username', result.username);
                    setTimeout(() => {
                        window.location.href = '/';
                    }, 1500);
                } else {
                    displayResult(`登录失败：${result.error}`, 'danger');
                }
            } catch (error) {
                console.error(error);
                displayResult('请求异常，请检查控制台。', 'danger');
            }
        });

        function displayResult(message, type) {
            const resultDiv = document.getElementById('login-result');
            resultDiv.innerHTML = `<div class="alert alert-${type}" role="alert">${message}</div>`;
        }
    </script>

    <!-- 引入 Bootstrap JS -->
    <script 
        src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js" 
        crossorigin="anonymous">
    </script>
    </body>
    </html>
    """

def upload_html():
    """
    上传视频页面 HTML 内容
    """
    return """
    <!DOCTYPE html>
    <html lang="zh-CN">
    <head>
        <meta charset="UTF-8">
        <title>上传视频 - 视频管理系统</title>
        <!-- 引入 Bootstrap (Bootswatch 的 Minty 绿色主题) -->
        <link 
            rel="stylesheet" 
            href="https://cdn.jsdelivr.net/npm/bootswatch@5.3.0/dist/minty/bootstrap.min.css" 
            crossorigin="anonymous">
        <style>
            body {
                padding-top: 70px;
                background-color: #f8f9fa;
            }
            .form-container {
                background-color: #ffffff;
                padding: 2rem;
                border-radius: 0.3rem;
                box-shadow: 0 0.125rem 0.25rem rgba(0, 0, 0, 0.075);
            }
        </style>
    </head>
    <body>

    <!-- 导航栏 -->
    <nav class="navbar navbar-expand-lg navbar-dark bg-primary fixed-top">
      <div class="container-fluid">
        <a class="navbar-brand" href="/">视频管理系统</a>
        <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#navbarNav" 
            aria-controls="navbarNav" aria-expanded="false" aria-label="Toggle navigation">
          <span class="navbar-toggler-icon"></span>
        </button>
        <div class="collapse navbar-collapse" id="navbarNav">
          <ul class="navbar-nav ms-auto" id="navbar-links">
            <!-- 动态生成导航链接 -->
          </ul>
        </div>
      </div>
    </nav>

    <!-- 主内容 -->
    <div class="container d-flex justify-content-center">
        <div class="form-container mt-5">
            <h2 class="mb-4 text-center">上传视频</h2>
            <form id="upload-form" enctype="multipart/form-data">
                <div class="mb-3">
                    <label for="video-file" class="form-label">选择视频文件</label>
                    <input type="file" class="form-control" id="video-file" accept="video/*" required>
                </div>
                <button type="submit" class="btn btn-success w-100">上传</button>
            </form>
            <div id="upload-result" class="mt-3"></div>
        </div>
    </div>

    <!-- JavaScript 逻辑 -->
    <script>
        // 获取用户登录状态
        const user_id = sessionStorage.getItem('user_id');
        const username = sessionStorage.getItem('username');

        const navbarLinks = document.getElementById('navbar-links');

        if (user_id && username) {
            // 已登录用户
            navbarLinks.innerHTML = `
                <li class="nav-item">
                  <a class="nav-link active" href="/upload.html">上传视频</a>
                </li>
                <li class="nav-item">
                  <a class="nav-link" href="/my_videos.html">我的视频</a>
                </li>
                <li class="nav-item">
                  <a class="nav-link" href="/search.html">搜索视频</a>
                </li>
                <li class="nav-item">
                  <a class="nav-link" href="#" onclick="logout()">登出</a>
                </li>
            `;
        } else {
            // 未登录用户
            navbarLinks.innerHTML = `
                <li class="nav-item">
                  <a class="nav-link" href="/register.html">注册</a>
                </li>
                <li class="nav-item">
                  <a class="nav-link" href="/login.html">登录</a>
                </li>
                <li class="nav-item">
                  <a class="nav-link" href="/search.html">搜索视频</a>
                </li>
            `;
        }

        // 登出功能
        async function logout() {
            try {
                const response = await fetch('/logout', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                });
                const result = await response.json();

                if (response.ok) {
                    // 清除前端会话
                    sessionStorage.removeItem('user_id');
                    sessionStorage.removeItem('username');
                    // 重新加载页面
                    window.location.href = '/';
                } else {
                    alert(`登出失败：${result.error}`);
                }
            } catch (error) {
                console.error(error);
                alert('请求异常，请检查控制台。');
            }
        }

        document.getElementById('upload-form').addEventListener('submit', async function(e) {
            e.preventDefault();

            if (!user_id || !username) {
                displayResult('请先登录！即将跳转到登录页面...', 'danger');
                setTimeout(() => {
                    window.location.href = '/login.html';
                }, 1500);
                return;
            }

            const fileInput = document.getElementById('video-file');
            if (fileInput.files.length === 0) {
                displayResult('请先选择文件！', 'danger');
                return;
            }

            const file = fileInput.files[0];
            const formData = new FormData();
            formData.append('file', file);

            try {
                const response = await fetch('/upload', {
                    method: 'POST',
                    body: formData
                });
                const result = await response.json();

                if (response.ok) {
                    displayResult('上传成功！', 'success');
                    document.getElementById('upload-form').reset();
                } else {
                    displayResult(`上传失败：${result.error}`, 'danger');
                }
            } catch (error) {
                console.error(error);
                displayResult('请求异常，请检查控制台。', 'danger');
            }
        });

        function displayResult(message, type) {
            const resultDiv = document.getElementById('upload-result');
            resultDiv.innerHTML = `<div class="alert alert-${type}" role="alert">${message}</div>`;
        }
    </script>

    <!-- 引入 Bootstrap JS -->
    <script 
        src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js" 
        crossorigin="anonymous">
    </script>
    </body>
    </html>
    """

def my_videos_html():
    """
    我的视频列表页面 HTML 内容
    """
    return """
    <!DOCTYPE html>
    <html lang="zh-CN">
    <head>
        <meta charset="UTF-8">
        <title>我的视频 - 视频管理系统</title>
        <!-- 引入 Bootstrap (Bootswatch 的 Minty 绿色主题) -->
        <link 
            rel="stylesheet" 
            href="https://cdn.jsdelivr.net/npm/bootswatch@5.3.0/dist/minty/bootstrap.min.css" 
            crossorigin="anonymous">
        <style>
            body {
                padding-top: 70px;
                background-color: #f8f9fa;
            }
            .table-container {
                background-color: #ffffff;
                padding: 2rem;
                border-radius: 0.3rem;
                box-shadow: 0 0.125rem 0.25rem rgba(0, 0, 0, 0.075);
            }
        </style>
    </head>
    <body>

    <!-- 导航栏 -->
    <nav class="navbar navbar-expand-lg navbar-dark bg-primary fixed-top">
      <div class="container-fluid">
        <a class="navbar-brand" href="/">视频管理系统</a>
        <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#navbarNav" 
            aria-controls="navbarNav" aria-expanded="false" aria-label="Toggle navigation">
          <span class="navbar-toggler-icon"></span>
        </button>
        <div class="collapse navbar-collapse" id="navbarNav">
          <ul class="navbar-nav ms-auto" id="navbar-links">
            <!-- 动态生成导航链接 -->
          </ul>
        </div>
      </div>
    </nav>

    <!-- 主内容 -->
    <div class="container d-flex justify-content-center">
        <div class="table-container mt-5 w-100">
            <h2 class="mb-4 text-center">我的视频列表</h2>
            <button class="btn btn-primary mb-3" onclick="fetchMyVideos()">获取列表</button>
            <table class="table table-striped">
                <thead>
                    <tr>
                        <th>视频名称</th>
                        <th>操作</th>
                    </tr>
                </thead>
                <tbody id="my-videos">
                    <!-- 视频列表将动态插入这里 -->
                </tbody>
            </table>
            <div id="action-result" class="mt-3"></div>
        </div>
    </div>

    <!-- JavaScript 逻辑 -->
    <script>
        // 获取用户登录状态
        const user_id = sessionStorage.getItem('user_id');
        const username = sessionStorage.getItem('username');

        const navbarLinks = document.getElementById('navbar-links');

        if (user_id && username) {
            // 已登录用户
            navbarLinks.innerHTML = `
                <li class="nav-item">
                  <a class="nav-link" href="/upload.html">上传视频</a>
                </li>
                <li class="nav-item">
                  <a class="nav-link active" href="/my_videos.html">我的视频</a>
                </li>
                <li class="nav-item">
                  <a class="nav-link" href="/search.html">搜索视频</a>
                </li>
                <li class="nav-item">
                  <a class="nav-link" href="#" onclick="logout()">登出</a>
                </li>
            `;
        } else {
            // 未登录用户
            navbarLinks.innerHTML = `
                <li class="nav-item">
                  <a class="nav-link" href="/register.html">注册</a>
                </li>
                <li class="nav-item">
                  <a class="nav-link" href="/login.html">登录</a>
                </li>
                <li class="nav-item">
                  <a class="nav-link" href="/search.html">搜索视频</a>
                </li>
            `;
        }

        // 登出功能
        async function logout() {
            try {
                const response = await fetch('/logout', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                });
                const result = await response.json();

                if (response.ok) {
                    // 清除前端会话
                    sessionStorage.removeItem('user_id');
                    sessionStorage.removeItem('username');
                    // 重新加载页面
                    window.location.href = '/';
                } else {
                    alert(`登出失败：${result.error}`);
                }
            } catch (error) {
                console.error(error);
                alert('请求异常，请检查控制台。');
            }
        }

        async function fetchMyVideos() {
            if (!user_id || !username) {
                alert('请先登录！即将跳转到登录页面...');
                setTimeout(() => {
                    window.location.href = '/login.html';
                }, 1500);
                return;
            }

            try {
                const response = await fetch(`/videos`);
                const result = await response.json();

                const tbody = document.getElementById('my-videos');
                tbody.innerHTML = '';
                document.getElementById('action-result').innerHTML = '';

                if (response.ok) {
                    if (result.videos.length === 0) {
                        tbody.innerHTML = '<tr><td colspan="2" class="text-center">暂无视频上传。</td></tr>';
                        return;
                    }

                    result.videos.forEach(videoName => {
                        const tr = document.createElement('tr');

                        // 视频名称
                        const tdName = document.createElement('td');
                        tdName.textContent = videoName;
                        tr.appendChild(tdName);

                        // 操作按钮
                        const tdActions = document.createElement('td');

                        // 播放按钮
                        const playBtn = document.createElement('button');
                        playBtn.className = 'btn btn-sm btn-outline-success me-2';
                        playBtn.textContent = '播放';
                        playBtn.onclick = () => playVideo(videoName);
                        tdActions.appendChild(playBtn);

                        // 下载按钮
                        const downloadBtn = document.createElement('a');
                        downloadBtn.href = `/download/${username}/${encodeURIComponent(videoName)}`;
                        downloadBtn.className = 'btn btn-sm btn-outline-info me-2';
                        downloadBtn.textContent = '下载';
                        downloadBtn.target = '_blank';
                        tdActions.appendChild(downloadBtn);

                        # 修改：添加在线播放按钮
                        const streamBtn = document.createElement('button');
                        streamBtn.className = 'btn btn-sm btn-outline-primary me-2';
                        streamBtn.textContent = '在线播放';
                        streamBtn.onclick = () => playVideoInNewWindow(videoName);
                        tdActions.appendChild(streamBtn);

                        # 保留重命名和删除按钮
                        const renameBtn = document.createElement('button');
                        renameBtn.className = 'btn btn-sm btn-outline-warning me-2';
                        renameBtn.textContent = '重命名';
                        renameBtn.onclick = () => renameVideo(videoName);
                        tdActions.appendChild(renameBtn);

                        const deleteBtn = document.createElement('button');
                        deleteBtn.className = 'btn btn-sm btn-outline-danger';
                        deleteBtn.textContent = '删除';
                        deleteBtn.onclick = () => deleteVideo(videoName);
                        tdActions.appendChild(deleteBtn);

                        tr.appendChild(tdActions);
                        tbody.appendChild(tr);
                    });
                } else {
                    tbody.innerHTML = `<tr><td colspan="2" class="text-danger text-center">获取视频失败：${result.error}</td></tr>`;
                }
            } catch (error) {
                console.error(error);
                document.getElementById('my-videos').innerHTML = '<tr><td colspan="2" class="text-danger text-center">请求异常，请检查控制台。</td></tr>';
            }
        }

        function playVideo(filename) {
            const videoUrl = `/stream/${username}/${encodeURIComponent(filename)}`;
            const videoWindow = window.open('', '_blank');
            videoWindow.document.write(`
                <!DOCTYPE html>
                <html lang="zh-CN">
                <head>
                    <meta charset="UTF-8">
                    <title>播放视频 - ${filename}</title>
                </head>
                <body style="margin:0; display:flex; justify-content:center; align-items:center; height:100vh; background-color:#000;">
                    <video src="${videoUrl}" controls style="max-width: 100%; max-height: 100%;"></video>
                </body>
                </html>
            `);
        }

        // 新增：在线播放功能
        function playVideoInNewWindow(filename) {
            const videoUrl = `/stream/${username}/${encodeURIComponent(filename)}`;
            window.open(`/stream/${username}/${encodeURIComponent(filename)}`, '_blank');
        }

        async function renameVideo(old_filename) {
            const new_filename = prompt('请输入新的视频名称（含扩展名）：', old_filename);
            if (!new_filename) {
                alert('取消重命名操作。');
                return;
            }

            // 简单校验
            const allowed = ['mp4', 'avi', 'mov', 'mkv'];
            const ext = new_filename.split('.').pop().toLowerCase();
            if (!allowed.includes(ext)) {
                alert('不允许的文件类型！');
                return;
            }

            // 发送重命名请求
            try {
                const response = await fetch('/rename', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        old_filename: old_filename,
                        new_filename: new_filename
                    })
                });
                const result = await response.json();

                if (response.ok) {
                    displayActionResult('视频重命名成功！', 'success');
                    fetchMyVideos();
                } else {
                    displayActionResult(`重命名失败：${result.error}`, 'danger');
                }
            } catch (error) {
                console.error(error);
                displayActionResult('请求异常，请检查控制台。', 'danger');
            }
        }

        async function deleteVideo(filename) {
            if (!confirm(`确定要删除视频 "${filename}" 吗？`)) {
                return;
            }

            // 发送删除请求
            try {
                const response = await fetch('/delete', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ filename: filename })
                });
                const result = await response.json();

                if (response.ok) {
                    displayActionResult('视频删除成功！', 'success');
                    fetchMyVideos();
                } else {
                    displayActionResult(`删除失败：${result.error}`, 'danger');
                }
            } catch (error) {
                console.error(error);
                displayActionResult('请求异常，请检查控制台。', 'danger');
            }
        }

        function displayActionResult(message, type) {
            const resultDiv = document.getElementById('action-result');
            resultDiv.innerHTML = `<div class="alert alert-${type}" role="alert">${message}</div>`;
        }

        // 页面加载时自动获取视频列表
        window.onload = fetchMyVideos;
    </script>

    <!-- 引入 Bootstrap JS -->
    <script 
        src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js" 
        crossorigin="anonymous">
    </script>
    </body>
    </html>
    """

def search_html():
    """
    搜索视频页面 HTML 内容
    """
    return """
    <!DOCTYPE html>
    <html lang="zh-CN">
    <head>
        <meta charset="UTF-8">
        <title>搜索视频 - 视频管理系统</title>
        <!-- 引入 Bootstrap (Bootswatch 的 Minty 绿色主题) -->
        <link 
            rel="stylesheet" 
            href="https://cdn.jsdelivr.net/npm/bootswatch@5.3.0/dist/minty/bootstrap.min.css" 
            crossorigin="anonymous">
        <style>
            body {
                padding-top: 70px;
                background-color: #f8f9fa;
            }
            .search-container {
                background-color: #ffffff;
                padding: 2rem;
                border-radius: 0.3rem;
                box-shadow: 0 0.125rem 0.25rem rgba(0, 0, 0, 0.075);
                margin-bottom: 2rem;
            }
        </style>
    </head>
    <body>

    <!-- 导航栏 -->
    <nav class="navbar navbar-expand-lg navbar-dark bg-primary fixed-top">
      <div class="container-fluid">
        <a class="navbar-brand" href="/">视频管理系统</a>
        <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#navbarNav" 
            aria-controls="navbarNav" aria-expanded="false" aria-label="Toggle navigation">
          <span class="navbar-toggler-icon"></span>
        </button>
        <div class="collapse navbar-collapse" id="navbarNav">
          <ul class="navbar-nav ms-auto" id="navbar-links">
            <!-- 动态生成导航链接 -->
          </ul>
        </div>
      </div>
    </nav>

    <!-- 主内容 -->
    <div class="container">
        <!-- 搜索特定用户的视频 -->
        <div class="search-container">
            <h2 class="mb-4 text-center">搜索特定用户的视频</h2>
            <form id="search-user-videos-form" class="row g-3">
                <div class="col-md-8">
                    <label for="search-username" class="form-label">用户名</label>
                    <input type="text" class="form-control" id="search-username" placeholder="输入要搜索的用户名" required>
                </div>
                <div class="col-md-4 align-self-end">
                    <button type="submit" class="btn btn-primary w-100">搜索</button>
                </div>
            </form>
            <ul id="search-user-videos-result" class="list-group mt-3"></ul>
        </div>
        
        <!-- 分隔线 -->
        <hr class="my-5">
        
        <!-- 全局搜索视频名称 -->
        <div class="search-container">
            <h2 class="mb-4 text-center">全局搜索视频名称</h2>
            <form id="search-global-videos-form" class="row g-3">
                <div class="col-md-8">
                    <label for="search-video-name" class="form-label">视频名称</label>
                    <input type="text" class="form-control" id="search-video-name" placeholder="输入视频名称" required>
                </div>
                <div class="col-md-4 align-self-end">
                    <button type="submit" class="btn btn-success w-100">搜索</button>
                </div>
            </form>
            <ul id="search-global-videos-result" class="list-group mt-3"></ul>
        </div>
    </div>

    <!-- JavaScript 逻辑 -->
    <script>
        // 获取用户登录状态
        const user_id = sessionStorage.getItem('user_id');
        const username = sessionStorage.getItem('username');

        const navbarLinks = document.getElementById('navbar-links');

        if (user_id && username) {
            // 已登录用户
            navbarLinks.innerHTML = `
                <li class="nav-item">
                  <a class="nav-link" href="/upload.html">上传视频</a>
                </li>
                <li class="nav-item">
                  <a class="nav-link" href="/my_videos.html">我的视频</a>
                </li>
                <li class="nav-item">
                  <a class="nav-link active" href="/search.html">搜索视频</a>
                </li>
                <li class="nav-item">
                  <a class="nav-link" href="#" onclick="logout()">登出</a>
                </li>
            `;
        } else {
            // 未登录用户
            navbarLinks.innerHTML = `
                <li class="nav-item">
                  <a class="nav-link" href="/register.html">注册</a>
                </li>
                <li class="nav-item">
                  <a class="nav-link" href="/login.html">登录</a>
                </li>
                <li class="nav-item">
                  <a class="nav-link active" href="/search.html">搜索视频</a>
                </li>
            `;
        }

        // 登出功能
        async function logout() {
            try {
                const response = await fetch('/logout', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                });
                const result = await response.json();

                if (response.ok) {
                    // 清除前端会话
                    sessionStorage.removeItem('user_id');
                    sessionStorage.removeItem('username');
                    // 重新加载页面
                    window.location.href = '/';
                } else {
                    alert(`登出失败：${result.error}`);
                }
            } catch (error) {
                console.error(error);
                alert('请求异常，请检查控制台。');
            }
        }

        // 搜索特定用户的视频
        document.getElementById('search-user-videos-form').addEventListener('submit', async function(e) {
            e.preventDefault();
            const searchUsername = document.getElementById('search-username').value.trim();

            if (!searchUsername) {
                displayUserVideosResult('请输入用户名！', 'danger');
                return;
            }

            try {
                const response = await fetch(`/search_user_videos?username=${encodeURIComponent(searchUsername)}`);
                const result = await response.json();

                const listEl = document.getElementById('search-user-videos-result');
                listEl.innerHTML = '';

                if (response.ok) {
                    if (result.matched_videos.length === 0) {
                        listEl.innerHTML = '<li class="list-group-item">该用户尚未上传任何视频。</li>';
                        return;
                    }

                    result.matched_videos.forEach(video => {
                        const li = document.createElement('li');
                        li.className = 'list-group-item d-flex justify-content-between align-items-center';
                        li.textContent = video.video_name;

                        // 下载按钮
                        const downloadBtn = document.createElement('a');
                        downloadBtn.href = `/download/${searchUsername}/${encodeURIComponent(video.video_name)}`;
                        downloadBtn.className = 'btn btn-sm btn-outline-info me-2';
                        downloadBtn.textContent = '下载';
                        downloadBtn.target = '_blank';

                        // 播放按钮
                        const playBtn = document.createElement('button');
                        playBtn.className = 'btn btn-sm btn-outline-success';
                        playBtn.textContent = '播放';
                        playBtn.onclick = () => playVideoInNewWindow(video.video_name);

                        li.appendChild(downloadBtn);
                        li.appendChild(playBtn);
                        listEl.appendChild(li);
                    });
                } else {
                    listEl.innerHTML = `<li class="list-group-item text-danger">搜索失败：${result.error}</li>`;
                }
            } catch (error) {
                console.error(error);
                document.getElementById('search-user-videos-result').innerHTML = '<li class="list-group-item text-danger">请求异常，请检查控制台。</li>';
            }
        });

        function displayUserVideosResult(message, type) {
            const listEl = document.getElementById('search-user-videos-result');
            listEl.innerHTML = `<li class="list-group-item"><div class="alert alert-${type}" role="alert">${message}</div></li>`;
        }

        // 全局搜索视频名称
        document.getElementById('search-global-videos-form').addEventListener('submit', async function(e) {
            e.preventDefault();
            const video_name = document.getElementById('search-video-name').value.trim();

            if (!video_name) {
                displayGlobalVideosResult('请输入视频名称！', 'danger');
                return;
            }

            try {
                const response = await fetch(`/search_videos?video_name=${encodeURIComponent(video_name)}`);
                const result = await response.json();

                const listEl = document.getElementById('search-global-videos-result');
                listEl.innerHTML = '';

                if (response.ok) {
                    result.matched_videos.forEach(video => {
                        const li = document.createElement('li');
                        li.className = 'list-group-item d-flex justify-content-between align-items-center';
                        li.textContent = `${video.video_name} (上传者: ${video.username})`;

                        // 下载按钮
                        const downloadBtn = document.createElement('a');
                        downloadBtn.href = `/download/${video.username}/${encodeURIComponent(video.video_name)}`;
                        downloadBtn.className = 'btn btn-sm btn-outline-info me-2';
                        downloadBtn.textContent = '下载';
                        downloadBtn.target = '_blank';

                        // 播放按钮
                        const playBtn = document.createElement('button');
                        playBtn.className = 'btn btn-sm btn-outline-success';
                        playBtn.textContent = '播放';
                        playBtn.onclick = () => playVideoInNewWindow(video.video_name);

                        li.appendChild(downloadBtn);
                        li.appendChild(playBtn);
                        listEl.appendChild(li);
                    });
                } else {
                    listEl.innerHTML = `<li class="list-group-item text-danger">搜索失败：${result.error}</li>`;
                }
            } catch (error) {
                console.error(error);
                document.getElementById('search-global-videos-result').innerHTML = '<li class="list-group-item text-danger">请求异常，请检查控制台。</li>';
            }
        });

        function displayGlobalVideosResult(message, type) {
            const listEl = document.getElementById('search-global-videos-result');
            listEl.innerHTML = `<li class="list-group-item"><div class="alert alert-${type}" role="alert">${message}</div></li>`;
        }

        // 新增：在线播放功能
        function playVideoInNewWindow(filename) {
            const videoUrl = `/stream/${username}/${encodeURIComponent(filename)}`;
            window.open(`/stream/${username}/${encodeURIComponent(filename)}`, '_blank');
        }
    </script>

    <!-- 引入 Bootstrap JS -->
    <script 
        src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js" 
        crossorigin="anonymous">
    </script>
    </body>
    </html>
    """

# =========================
# 运行应用
# =========================

if __name__ == '__main__':
    # 在生产环境下，建议使用更可靠的 WSGI 服务器，如 gunicorn
    app.run(host='0.0.0.0', port=5000, debug=False)
