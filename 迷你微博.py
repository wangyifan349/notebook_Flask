from flask import Flask, request, jsonify, g, render_template_string
from flask_jwt_extended import (
    JWTManager, create_access_token,
    jwt_required, get_jwt_identity
)
import sqlite3, bcrypt, os

app = Flask(__name__)
app.config['JWT_SECRET_KEY'] = 'your-secret-key'
DATABASE_PATH = os.path.join(os.path.dirname(__file__), 'weibo.db')
jwt = JWTManager(app)

# ———— Database Connection & Initialization ————

def get_db():
    """Return a SQLite connection stored on flask.g for reuse."""
    if 'db' not in g:
        g.db = sqlite3.connect(DATABASE_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(exc):
    """Close database connection at the end of request."""
    db = g.pop('db', None)
    if db:
        db.close()

def init_db():
    """Create tables if they do not exist."""
    db = get_db()
    db.executescript("""
    -- users table: store user credentials and registration time
    CREATE TABLE IF NOT EXISTS users (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      username TEXT UNIQUE NOT NULL,
      password_hash BLOB NOT NULL,
      registration_time DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    -- posts table: store posts, support soft delete via hidden flag
    CREATE TABLE IF NOT EXISTS posts (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      author_id INTEGER NOT NULL,
      content TEXT NOT NULL,
      hidden INTEGER DEFAULT 0,       -- 0 = visible, 1 = hidden
      created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY(author_id) REFERENCES users(id)
    );
    -- comments table: store comments on posts, support soft delete
    CREATE TABLE IF NOT EXISTS comments (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      post_id INTEGER NOT NULL,
      author_id INTEGER NOT NULL,
      content TEXT NOT NULL,
      hidden INTEGER DEFAULT 0,       -- 0 = visible, 1 = hidden
      created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY(post_id) REFERENCES posts(id),
      FOREIGN KEY(author_id) REFERENCES users(id)
    );
    """)
    db.commit()

# Automatically initialize database on startup
with app.app_context():
    init_db()

# ———— Frontend Template ————
INDEX_HTML = """
<!DOCTYPE html>
<html lang="zh">
<head>
  <meta charset="UTF-8">
  <title>简约微博</title>
  <style>
    body { margin: 20px; font-family: sans-serif; background: #FFF8E1; color: #333; }
    h2 { color: #B22222; }
    button { background: #DAA520; color: #fff; padding: 5px 10px; cursor: pointer; }
    input, textarea { border: none; padding: 5px; outline: none; }
    #container { display: flex; gap: 20px; }
    #auth, #app { flex: 1; }
    .section { margin-bottom: 20px; }
    .post, .comment { margin-bottom: 10px; }
    .author { font-weight: bold; color: #B22222; }
  </style>
</head>
<body>
  <h2>简约微博示例</h2>
  <div id="container">
    <div id="auth">
      <div class="section">
        <h3>注册</h3>
        <input id="registerUsername" placeholder="用户名">
        <input id="registerPassword" type="password" placeholder="密码">
        <button onclick="registerUser()">注册</button>
      </div>
      <div class="section">
        <h3>登录</h3>
        <input id="loginUsername" placeholder="用户名">
        <input id="loginPassword" type="password" placeholder="密码">
        <button onclick="loginUser()">登录</button>
      </div>
      <div class="section">
        <h3>搜索用户</h3>
        <input id="searchUsername" placeholder="用户名">
        <button onclick="searchUsers()">搜索</button>
        <div id="searchResults"></div>
      </div>
    </div>
    <div id="app" style="display: none;">
      <div class="section"><button onclick="logoutUser()">退出</button></div>
      <div class="section">
        <h3>发帖</h3>
        <textarea id="newPostContent" rows="3" cols="30" placeholder="写点什么..."></textarea><br>
        <button onclick="createPost()">发布</button>
      </div>
      <div class="section">
        <h3>帖子列表</h3>
        <div id="postsContainer"></div>
      </div>
    </div>
  </div>
<script>
let jwtToken = '';

function registerUser() {
  fetch('/auth/register', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      username: registerUsername.value,
      password: registerPassword.value
    })
  }).then(r => r.json()).then(r => alert(r.msg));
}

function loginUser() {
  fetch('/auth/login', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      username: loginUsername.value,
      password: loginPassword.value
    })
  }).then(r => r.json()).then(r => {
    if (r.access_token) {
      jwtToken = r.access_token;
      auth.style.display = 'none';
      app.style.display = 'block';
      loadPosts();
    } else {
      alert(r.msg);
    }
  });
}

function logoutUser() {
  jwtToken = '';
  auth.style.display = 'block';
  app.style.display = 'none';
  postsContainer.innerHTML = '';
}

function createPost() {
  fetch('/posts', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': 'Bearer ' + jwtToken
    },
    body: JSON.stringify({content: newPostContent.value})
  }).then(() => { newPostContent.value = ''; loadPosts(); });
}

function loadPosts() {
  fetch('/posts').then(r => r.json()).then(posts => {
    postsContainer.innerHTML = posts.map(p => `
      <div class="post">
        <div>
          <span class="author">${p.authorName}</span> (ID:${p.authorId}) 发帖于 ${p.createdAt}
        </div>
        <div>${p.content}</div>
        <button onclick="hidePost(${p.id})">删除</button>
        <button onclick="toggleComments(${p.id})">评论 (${p.comments.length})</button>
        <div id="comments-${p.id}" class="comments" style="margin-left:10px;"></div>
        <textarea id="newComment-${p.id}" rows="2" cols="30"></textarea>
        <button onclick="addComment(${p.id})">发布评论</button>
        <hr>
      </div>`).join('');
  });
}

function hidePost(postId) {
  fetch(`/posts/${postId}`, {
    method: 'DELETE',
    headers: {'Authorization': 'Bearer ' + jwtToken}
  }).then(() => loadPosts());
}

function toggleComments(postId) {
  const container = document.getElementById(`comments-${postId}`);
  if (container.innerHTML) {
    container.innerHTML = '';
    return;
  }
  fetch(`/posts/${postId}`).then(r => r.json()).then(post => {
    container.innerHTML = post.comments.map(c => `
      <div class="comment">
        <span class="author">${c.authorName}</span> 评论于 ${c.createdAt}: ${c.content}
        <button onclick="hideComment(${c.id}, ${postId})">删除</button>
      </div>
    `).join('');
  });
}

function addComment(postId) {
  const content = document.getElementById(`newComment-${postId}`).value;
  fetch(`/posts/${postId}/comments`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': 'Bearer ' + jwtToken
    },
    body: JSON.stringify({content})
  }).then(() => toggleComments(postId));
}

function hideComment(commentId, postId) {
  fetch(`/comments/${commentId}`, {
    method: 'DELETE',
    headers: {'Authorization': 'Bearer ' + jwtToken}
  }).then(() => toggleComments(postId));
}

function searchUsers() {
  fetch(`/search?username=${encodeURIComponent(searchUsername.value)}`)
    .then(r => r.json())
    .then(users => {
      searchResults.innerHTML = users.map(u => `
        用户名：${u.username}，ID：${u.id}，注册于：${u.registrationTime}
      `).join('<br>');
    });
}
</script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(INDEX_HTML)

# ———— User Registration ————
@app.route('/auth/register', methods=['POST'])
def register():
    data = request.get_json()
    hashed_pw = bcrypt.hashpw(data['password'].encode(), bcrypt.gensalt())
    try:
        get_db().execute(
            # Insert new user with username and hashed password
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (data['username'], hashed_pw)
        )
        get_db().commit()
    except sqlite3.IntegrityError:
        return jsonify(msg="Username already exists"), 400
    return jsonify(msg="Registration successful"), 201

# ———— User Login ————
@app.route('/auth/login', methods=['POST'])
def login():
    data = request.get_json()
    row = get_db().execute(
        # Select user by username to verify password
        "SELECT id, password_hash FROM users WHERE username = ?",
        (data['username'],)
    ).fetchone()
    if not row or not bcrypt.checkpw(data['password'].encode(), row['password_hash']):
        return jsonify(msg="Invalid username or password"), 401
    token = create_access_token(identity=row['id'])
    return jsonify(access_token=token), 200

# ———— Create Post ————
@app.route('/posts', methods=['POST'])
@jwt_required()
def create_post():
    user_id = get_jwt_identity()
    content = request.json['content']
    get_db().execute(
        # Insert new post; hidden default is 0
        "INSERT INTO posts (author_id, content) VALUES (?, ?)",
        (user_id, content)
    )
    get_db().commit()
    return jsonify(msg="Post created"), 201

# ———— List All Posts ————
@app.route('/posts', methods=['GET'])
def list_posts():
    db = get_db()
    posts = db.execute(
        # Select visible posts with author info
        """SELECT p.id, p.content, p.created_at AS createdAt,
                  u.id AS authorId, u.username AS authorName
           FROM posts p
           JOIN users u ON p.author_id = u.id
           WHERE p.hidden = 0
           ORDER BY p.created_at DESC"""
    ).fetchall()
    result = []
    for p in posts:
        comments = db.execute(
            # Select visible comments for each post
            """SELECT c.id, c.content, c.created_at AS createdAt,
                      u.username AS authorName
               FROM comments c
               JOIN users u ON c.author_id = u.id
               WHERE c.post_id = ? AND c.hidden = 0
               ORDER BY c.created_at""",
            (p['id'],)
        ).fetchall()
        result.append({
            'id': p['id'], 'content': p['content'],
            'createdAt': p['createdAt'],
            'authorId': p['authorId'], 'authorName': p['authorName'],
            'comments': [dict(c) for c in comments]
        })
    return jsonify(result), 200

# ———— Get Single Post with Comments ————
@app.route('/posts/<int:post_id>', methods=['GET'])
def get_post(post_id):
    db = get_db()
    post = db.execute(
        # Select specific visible post
        """SELECT p.id, p.content, p.created_at AS createdAt,
                  u.id AS authorId, u.username AS authorName
           FROM posts p
           JOIN users u ON p.author_id = u.id
           WHERE p.id = ? AND p.hidden = 0""",
        (post_id,)
    ).fetchone()
    if not post:
        return jsonify(msg="Post not found"), 404
    comments = db.execute(
        # Select visible comments for this post
        """SELECT c.id, c.content, c.created_at AS createdAt,
                  u.username AS authorName
           FROM comments c
           JOIN users u ON c.author_id = u.id
           WHERE c.post_id = ? AND c.hidden = 0
           ORDER BY c.created_at""",
        (post_id,)
    ).fetchall()
    return jsonify({**dict(post), 'comments': [dict(c) for c in comments]}), 200

# ———— Add Comment to Post ————
@app.route('/posts/<int:post_id>/comments', methods=['POST'])
@jwt_required()
def add_comment(post_id):
    user_id = get_jwt_identity()
    content = request.json['content']
    get_db().execute(
        # Insert new comment; hidden default is 0
        "INSERT INTO comments (post_id, author_id, content) VALUES (?, ?, ?)",
        (post_id, user_id, content)
    )
    get_db().commit()
    return jsonify(msg="Comment added"), 201

# ———— Soft Delete Post ————
@app.route('/posts/<int:post_id>', methods=['DELETE'])
@jwt_required()
def delete_post(post_id):
    get_db().execute(
        # Mark post as hidden instead of deleting
        "UPDATE posts SET hidden = 1 WHERE id = ?",
        (post_id,)
    )
    get_db().commit()
    return jsonify(msg="Post hidden"), 200

# ———— Soft Delete Comment ————
@app.route('/comments/<int:comment_id>', methods=['DELETE'])
@jwt_required()
def delete_comment(comment_id):
    get_db().execute(
        # Mark comment as hidden instead of deleting
        "UPDATE comments SET hidden = 1 WHERE id = ?",
        (comment_id,)
    )
    get_db().commit()
    return jsonify(msg="Comment hidden"), 200

# ———— Search Users by Username ————
@app.route('/search')
def search_users():
    query = request.args.get('username', '')
    rows = get_db().execute(
        # Find users whose username contains query substring
        "SELECT id, username, registration_time FROM users WHERE username LIKE ?",
        (f"%{query}%",)
    ).fetchall()
    return jsonify([dict(r) for r in rows]), 200

if __name__ == '__main__':
    app.run(debug=True)
