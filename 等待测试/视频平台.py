import os
import sqlite3
from flask import (
    Flask, request, redirect, url_for, session,
    send_from_directory, abort, g, render_template_string
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
# 部署时请通过环境变量设置 SECRET_KEY
app.secret_key = os.getenv('SECRET_KEY', 'replace_with_a_secure_random_key')

# 配置
DATABASE_PATH   = 'circlelight.db'
UPLOAD_BASE_DIR = os.path.join('static', 'videos')
HIDE_PREFIX     = '.hidden_'
ALLOWED_EXT     = {'.mp4', '.mov', '.avi'}
app.config['MAX_CONTENT_LENGTH'] = 200 * 1024 * 1024  # 最大 200MB

os.makedirs(UPLOAD_BASE_DIR, exist_ok=True)

BASE_CSS = '''
<link href="https://cdn.jsdelivr.net/npm/bootswatch@5.3.2/dist/minty/bootstrap.min.css"
      rel="stylesheet" crossorigin="anonymous">
'''

# --- 模板定义（与原始保持一致，仅省略注释） ---
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
    <table class="table table-striped"><thead><tr><th>用户名</th><th>相似度</th></tr></thead><tbody>
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
      {% for v in videos %}
        <div class="col-md-6">
          <div class="card">
            <div class="card-body">
              <h5 class="card-title">
                {% if v.is_hidden %}<em>（隐藏）</em> {% endif %}{{ v.title }}
              </h5>
              {% if not v.is_hidden or (g.current_user and g.current_user.username == username) %}
                <a class="btn btn-success"
                   href="{{ url_for('play_video', username=username, video_id=v.id) }}">▶️ 播放</a>
              {% endif %}
              {% if g.current_user and g.current_user.username == username %}
                <form method="post" action="{{ url_for('toggle_hide', video_id=v.id) }}" style="display:inline-block">
                  <button class="btn btn-{{ 'secondary' if v.is_hidden else 'warning' }}">
                    {{ '取消隐藏' if v.is_hidden else '隐藏' }}
                  </button>
                </form>
                <form method="post" action="{{ url_for('delete_video', video_id=v.id) }}"
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

# ---- 数据库连接与初始化 ----
def get_db():
    if 'db_conn' not in g:
        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        g.db_conn = conn
    return g.db_conn

@app.teardown_appcontext
def close_db(error):
    db = g.pop('db_conn', None)
    if db:
        db.close()

def init_db():
    db = get_db()
    db.execute('''
      CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL
      );
    ''')
    db.execute('''
      CREATE TABLE IF NOT EXISTS videos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        filename TEXT NOT NULL UNIQUE,
        title TEXT NOT NULL,
        is_hidden INTEGER NOT NULL DEFAULT 0,
        upload_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
      );
    ''')
    db.commit()

# ---- 用户状态加载 & 装饰器 ----
@app.before_request
def load_current_user():
    user_id = session.get('user_id')
    if user_id:
        g.current_user = get_db().execute(
            'SELECT id, username FROM users WHERE id=?', (user_id,)
        ).fetchone()
    else:
        g.current_user = None

def login_required(view):
    def wrapped(*args, **kwargs):
        if not g.current_user:
            return redirect(url_for('login'))
        return view(*args, **kwargs)
    wrapped.__name__ = view.__name__
    return wrapped

# ---- 注册 & 登录 ----
@app.route('/register', methods=('GET','POST'))
def register():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        if not username or not password:
            return '用户名和密码为必填项',400
        pwd_hash = generate_password_hash(password)
        try:
            db = get_db()
            db.execute('INSERT INTO users(username,password_hash) VALUES(?,?)',
                       (username,pwd_hash))
            db.commit()
        except sqlite3.IntegrityError:
            return '用户名已被使用',400
        os.makedirs(os.path.join(UPLOAD_BASE_DIR,username), exist_ok=True)
        return redirect(url_for('login'))
    return render_template_string(TPL_REGISTER)

@app.route('/login', methods=('GET','POST'))
def login():
    if request.method=='POST':
        username = request.form['username'].strip()
        password = request.form['password']
        row = get_db().execute(
            'SELECT * FROM users WHERE username=?', (username,)
        ).fetchone()
        if not row or not check_password_hash(row['password_hash'], password):
            return '用户名或密码错误',401
        session.clear()
        session['user_id'] = row['id']
        return redirect(url_for('upload_video'))
    return render_template_string(TPL_LOGIN)

# ---- 上传视频 ----
def allowed_file(fn):
    return os.path.splitext(fn)[1].lower() in ALLOWED_EXT

@app.route('/upload', methods=('GET','POST'))
@login_required
def upload_video():
    if request.method=='POST':
        title = request.form['video_title'].strip()
        f = request.files.get('video_file')
        if not title or not f or f.filename=='':
            return '标题和视频文件为必填项',400
        raw = secure_filename(f.filename)
        if not allowed_file(raw):
            return '不支持的文件类型',400
        username = g.current_user['username']
        user_dir = os.path.join(UPLOAD_BASE_DIR, username)
        os.makedirs(user_dir, exist_ok=True)
        filename = f"{secure_filename(title)}_{raw}"
        f.save(os.path.join(user_dir, filename))
        # 写入数据库
        db = get_db()
        db.execute('INSERT INTO videos(user_id,filename,title,is_hidden) VALUES(?,?,?,0)',
                   (g.current_user['id'], filename, title))
        db.commit()
        return '上传成功'
    return render_template_string(TPL_UPLOAD)

# ---- LCS 相似度函数 ----
def lcs_length(a, b):
    n, m = len(a), len(b)
    dp = [[0]*(m+1) for _ in range(n+1)]
    for i in range(n-1, -1, -1):
        for j in range(m-1, -1, -1):
            if a[i] == b[j]:
                dp[i][j] = dp[i+1][j+1] + 1
            else:
                dp[i][j] = max(dp[i+1][j], dp[i][j+1])
    return dp[0][0]

# ---- 搜索用户 ----
@app.route('/search')
def search_users():
    query = request.args.get('query','').strip().lower()
    results = []
    if query:
        rows = get_db().execute('SELECT username FROM users').fetchall()
        for r in rows:
            uname = r['username']
            lcs = lcs_length(query, uname.lower())
            score = lcs / max(len(query), len(uname))
            if score > 0:
                results.append({'username': uname, 'score': score})
        results.sort(key=lambda x: x['score'], reverse=True)
    return render_template_string(TPL_SEARCH, query=query, results=results)

# ---- 查看个人主页 ----
@app.route('/user/<username>')
def view_profile(username):
    user_dir = os.path.join(UPLOAD_BASE_DIR, username)
    if not os.path.isdir(user_dir):
        abort(404)
    db = get_db()
    user = db.execute('SELECT id FROM users WHERE username=?', (username,)).fetchone()
    if not user:
        abort(404)
    videos = db.execute(
        'SELECT * FROM videos WHERE user_id=? ORDER BY upload_time DESC',
        (user['id'],)
    ).fetchall()
    return render_template_string(TPL_PROFILE, username=username, videos=videos)

# ---- 播放视频 ----
@app.route('/play/<username>/<int:video_id>')
@login_required
def play_video(username, video_id):
    db = get_db()
    video = db.execute('SELECT * FROM videos WHERE id=?', (video_id,)).fetchone()
    if not video:
        abort(404)
    if video['is_hidden'] and g.current_user['username'] != username:
        abort(403)
    return render_template_string(
        TPL_PLAY,
        username=username,
        filename=video['filename']
    )

@app.route('/videos/<username>/<filename>')
def serve_video(username, filename):
    return send_from_directory(os.path.join(UPLOAD_BASE_DIR, username), filename)

# ---- 隐藏 & 删除 ----
@app.route('/hide/<int:video_id>', methods=['POST'])
@login_required
def toggle_hide(video_id):
    db = get_db()
    video = db.execute('SELECT * FROM videos WHERE id=?', (video_id,)).fetchone()
    if not video or video['user_id'] != g.current_user['id']:
        abort(403)
    new_state = 0 if video['is_hidden'] else 1
    db.execute('UPDATE videos SET is_hidden=? WHERE id=?', (new_state, video_id))
    db.commit()
    return redirect(url_for('view_profile', username=g.current_user['username']))

@app.route('/delete/<int:video_id>', methods=['POST'])
@login_required
def delete_video(video_id):
    db = get_db()
    video = db.execute('SELECT * FROM videos WHERE id=?', (video_id,)).fetchone()
    if not video or video['user_id'] != g.current_user['id']:
        abort(403)
    path = os.path.join(UPLOAD_BASE_DIR, g.current_user['username'], video['filename'])
    if os.path.exists(path):
        os.remove(path)
    db.execute('DELETE FROM videos WHERE id=?', (video_id,))
    db.commit()
    return redirect(url_for('view_profile', username=g.current_user['username']))

# ---- 启动 ----
if __name__ == '__main__':
    with app.app_context():
        init_db()
    app.run(debug=True)
