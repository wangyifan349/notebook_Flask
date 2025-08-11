import os
import sqlite3
import difflib
from flask import (
    Flask, request, redirect, url_for, session,
    send_from_directory, abort, g, render_template_string
)
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'replace_with_a_secure_random_key'                   # 加密会话的密钥，请换成随机值

DATABASE_PATH = 'circlelight.db'                                      # SQLite 数据库文件路径
UPLOAD_BASE_DIR = os.path.join('static', 'videos')                   # 视频存储根目录
HIDE_PREFIX = '.hidden_'                                             # 隐藏视频文件名前缀
os.makedirs(UPLOAD_BASE_DIR, exist_ok=True)                          # 确保视频目录存在

BASE_CSS = '''
<link href="https://cdn.jsdelivr.net/npm/bootswatch@5.3.2/dist/minty/bootstrap.min.css"
      rel="stylesheet" crossorigin="anonymous">
'''                                                                    # 页面使用的 Bootswatch Minty 主题

# --- 各页面模板 ---
TPL_REGISTER = BASE_CSS + '''
<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><title>注册</title></head>
<body class="container py-4">
  <h1 class="mb-4">注册新用户</h1>
  <form method="post">
    <div class="mb-3"><label class="form-label">用户名</label>
      <input class="form-control" type="text" name="username" required>
    </div>
    <div class="mb-3"><label class="form-label">密码</label>
      <input class="form-control" type="password" name="password" required>
    </div>
    <button class="btn btn-success" type="submit">注册</button>
    <a class="btn btn-link" href="{{ url_for('login') }}">已有账号？登录</a>
  </form>
</body></html>
'''

TPL_LOGIN = BASE_CSS + '''
<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><title>登录</title></head>
<body class="container py-4">
  <h1 class="mb-4">用户登录</h1>
  <form method="post">
    <div class="mb-3"><label class="form-label">用户名</label>
      <input class="form-control" type="text" name="username" required>
    </div>
    <div class="mb-3"><label class="form-label">密码</label>
      <input class="form-control" type="password" name="password" required>
    </div>
    <button class="btn btn-success" type="submit">登录</button>
    <a class="btn btn-link" href="{{ url_for('register') }}">注册新用户</a>
  </form>
</body></html>
'''

TPL_UPLOAD = BASE_CSS + '''
<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><title>上传视频</title></head>
<body class="container py-4">
  <h1 class="mb-4">上传视频</h1>
  <form method="post" enctype="multipart/form-data">
    <div class="mb-3"><label class="form-label">视频标题</label>
      <input class="form-control" type="text" name="video_title" required>
    </div>
    <div class="mb-3"><label class="form-label">选择文件</label>
      <input class="form-control" type="file" name="video_file" accept="video/*" required>
    </div>
    <button class="btn btn-success" type="submit">上传</button>
    <a class="btn btn-link" href="{{ url_for('search_users') }}">搜索用户</a>
  </form>
</body></html>
'''

TPL_SEARCH = BASE_CSS + '''
<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><title>搜索用户</title></head>
<body class="container py-4">
  <h1 class="mb-4">🔎 搜索用户</h1>
  <form class="input-group mb-4" method="get">
    <input class="form-control" type="text" name="query" value="{{ query }}" placeholder="输入用户名">
    <button class="btn btn-success" type="submit">搜索</button>
  </form>
  {% if results %}
    <table class="table table-striped"><thead><tr><th>用户名</th><th>匹配度</th></tr></thead><tbody>
      {% for item in results %}
        <tr>
          <td><a href="{{ url_for('view_profile', username=item.username) }}">{{ item.username }}</a></td>
          <td>{{ (item.score*100)|round(1) }}%</td>
        </tr>
      {% endfor %}
    </tbody></table>
  {% elif query %}
    <div class="alert alert-warning">未找到匹配用户。</div>
  {% endif %}
</body></html>
'''

TPL_PROFILE = BASE_CSS + '''
<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><title>{{ username }} 的主页</title></head>
<body class="container py-4">
  <h1 class="mb-4">📽️ {{ username }} 的视频</h1>
  {% if videos %}
    <div class="row g-3">
      {% for video, is_hidden in videos %}
        <div class="col-md-6">
          <div class="card">
            <div class="card-body">
              <h5 class="card-title">
                {% if is_hidden %}<em>（隐藏）</em> {% endif %}{{ video }}
              </h5>
              {% if not is_hidden or (g.current_user and g.current_user.username == username) %}
              <a class="btn btn-success"
                 href="{{ url_for('play_video', username=username, filename=video) }}">
                ▶️ 播放
              </a>
              {% endif %}
              {% if g.current_user and g.current_user.username == username %}
              <form method="post"
                    action="{{ url_for('toggle_hide', username=username, filename=video) }}"
                    style="display:inline-block">
                <button class="btn btn-{{ 'secondary' if is_hidden else 'warning' }}">
                  {{ '取消隐藏' if is_hidden else '隐藏' }}
                </button>
              </form>
              <form method="post"
                    action="{{ url_for('delete_video', username=username, filename=video) }}"
                    style="display:inline-block" onsubmit="return confirm('确认删除？');">
                <button class="btn btn-danger">🗑️ 删除</button>
              </form>
              {% endif %}
            </div>
          </div>
        </div>
      {% endfor %}
    </div>
  {% else %}
    <div class="alert alert-info">该用户还没有上传视频。</div>
  {% endif %}
  <a class="btn btn-link mt-4" href="{{ url_for('search_users') }}">← 返回搜索</a>
</body></html>
'''

TPL_PLAY = BASE_CSS + '''
<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><title>播放：{{ filename }}</title></head>
<body class="container py-4 text-center">
  <video class="w-100 mb-3" controls>
    <source src="{{ url_for('serve_video', username=username, filename=filename) }}" type="video/mp4">
    您的浏览器不支持 video 标签。
  </video>
  <h3>{{ filename }}</h3>
  <p>上传者：<strong>{{ username }}</strong></p>
  <a class="btn btn-link" href="{{ url_for('view_profile', username=username) }}">
    ← 返回 {{ username }} 的主页
  </a>
</body></html>
'''

def get_db():
    if 'db_conn' not in g:
        g.db_conn = sqlite3.connect(DATABASE_PATH)                # 建立并缓存数据库连接
        g.db_conn.row_factory = sqlite3.Row                       # 结果行以 dict 方式访问
    return g.db_conn

@app.teardown_appcontext
def close_db(error):
    db = g.pop('db_conn', None)                                    # 获取并移除连接
    if db: db.close()                                              # 关闭数据库连接

def init_db():
    db = get_db()
    db.execute('''
        CREATE TABLE IF NOT EXISTS users (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          username TEXT NOT NULL UNIQUE,
          password_hash TEXT NOT NULL
        );
    ''')                                                           # 初始化 users 表
    db.commit()

@app.before_request
def load_current_user():
    user_id = session.get('user_id')                               # 从会话读取用户 ID
    if user_id:
        g.current_user = get_db().execute(
            'SELECT id, username FROM users WHERE id=?', (user_id,)
        ).fetchone()                                              # 加载当前用户信息
    else:
        g.current_user = None

def login_required(f):
    def wrapped(*args, **kwargs):
        if not g.current_user:
            return redirect(url_for('login'))                     # 未登录则重定向到登录
        return f(*args, **kwargs)
    wrapped.__name__ = f.__name__
    return wrapped

@app.route('/register', methods=('GET','POST'))
def register():
    if request.method == 'POST':
        username = request.form['username'].strip()                # 获取并清理用户名
        password = request.form['password']                        # 获取密码
        if not username or not password:
            return '用户名和密码为必填项',400
        pwd_hash = generate_password_hash(password)                # 安全哈希存储密码
        try:
            get_db().execute(
                'INSERT INTO users(username,password_hash) VALUES(?,?)',
                (username, pwd_hash)
            )                                                      # 插入新用户
            get_db().commit()
        except sqlite3.IntegrityError:
            return '用户名已被使用',400
        os.makedirs(os.path.join(UPLOAD_BASE_DIR, username), exist_ok=True)  # 为用户创建目录
        return redirect(url_for('login'))
    return render_template_string(TPL_REGISTER)

@app.route('/login', methods=('GET','POST'))
def login():
    if request.method=='POST':
        username = request.form['username'].strip()
        password = request.form['password']
        row = get_db().execute(
            'SELECT * FROM users WHERE username=?', (username,)
        ).fetchone()                                               # 查询用户
        if not row or not check_password_hash(row['password_hash'], password):
            return '用户名或密码错误',401
        session.clear()
        session['user_id'] = row['id']                            # 保存用户 ID 到会话
        return redirect(url_for('upload_video'))
    return render_template_string(TPL_LOGIN)

@app.route('/upload', methods=('GET','POST'))
@login_required
def upload_video():
    if request.method=='POST':
        title = request.form['video_title'].strip()               # 获取视频标题
        f = request.files.get('video_file')                       # 获取上传文件
        if not title or not f or f.filename=='':
            return '标题和视频文件为必填项',400
        user_dir = os.path.join(UPLOAD_BASE_DIR, g.current_user['username'])
        os.makedirs(user_dir, exist_ok=True)
        filename = f"{title}_{f.filename}"                        # 拼接存储文件名
        f.save(os.path.join(user_dir, filename))                  # 保存到用户目录
        return '上传成功'
    return render_template_string(TPL_UPLOAD)

@app.route('/delete/<username>/<filename>', methods=['POST'])
@login_required
def delete_video(username, filename):
    if g.current_user['username'] != username:
        abort(403)                                                # 权限校验：只能删自己的
    path = os.path.join(UPLOAD_BASE_DIR, username, filename)
    if not os.path.exists(path):
        abort(404)
    os.remove(path)                                              # 删除文件
    return redirect(url_for('view_profile', username=username))

@app.route('/hide/<username>/<filename>', methods=['POST'])
@login_required
def toggle_hide(username, filename):
    if g.current_user['username'] != username:
        abort(403)                                                # 仅作者可隐藏/显示
    user_dir = os.path.join(UPLOAD_BASE_DIR, username)
    src = os.path.join(user_dir, filename)
    if not os.path.exists(src):
        abort(404)
    if filename.startswith(HIDE_PREFIX):
        new_name = filename[len(HIDE_PREFIX):]                   # 取消隐藏
    else:
        new_name = HIDE_PREFIX + filename                        # 添加隐藏前缀
    os.rename(src, os.path.join(user_dir, new_name))            # 重命名切换状态
    return redirect(url_for('view_profile', username=username))

@app.route('/search')
def search_users():
    query = request.args.get('query','').strip()                 # 获取搜索关键词
    results = []
    if query:
        rows = get_db().execute('SELECT username FROM users').fetchall()
        for r in rows:
            score = difflib.SequenceMatcher(
                None, query.lower(), r['username'].lower()
            ).ratio()                                           # 计算匹配度
            if score > 0.2:
                results.append({'username':r['username'],'score':score})
        results.sort(key=lambda x:x['score'], reverse=True)      # 按匹配度排序
    return render_template_string(TPL_SEARCH, query=query, results=results)

@app.route('/user/<username>')
def view_profile(username):
    user_dir = os.path.join(UPLOAD_BASE_DIR, username)
    if not os.path.isdir(user_dir):
        abort(404)                                               # 用户目录不存在即 404
    videos = []
    for fname in os.listdir(user_dir):
        full = os.path.join(user_dir, fname)
        if os.path.isfile(full):
            hidden = fname.startswith(HIDE_PREFIX)               # 检查隐藏状态
            videos.append((fname, hidden))                       # 收集文件名与状态
    return render_template_string(
        TPL_PROFILE,
        username=username,
        videos=videos
    )

@app.route('/play/<username>/<filename>')
@login_required
def play_video(username, filename):
    user_dir = os.path.join(UPLOAD_BASE_DIR, username)
    full = os.path.join(user_dir, filename)
    if not os.path.exists(full):
        abort(404)
    if filename.startswith(HIDE_PREFIX) and g.current_user['username'] != username:
        abort(403)                                               # 隐藏视频仅作者可见
    return render_template_string(TPL_PLAY, username=username, filename=filename)

@app.route('/videos/<username>/<filename>')
def serve_video(username, filename):
    # 静态文件路由，直接返回视频内容
    return send_from_directory(os.path.join(UPLOAD_BASE_DIR, username), filename)

if __name__ == '__main__':
    with app.app_context():
        init_db()                                               # 启动前初始化数据库
    app.run(debug=True)
