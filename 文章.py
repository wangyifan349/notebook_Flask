import os
import uuid
import sqlite3
from flask import Flask, request, jsonify, g

app = Flask(__name__)
DATABASE = 'app.db'

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_db(exc):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def init_db():
    if os.path.exists(DATABASE):
        return
    with app.app_context():
        db = get_db()
        db.executescript('''
CREATE TABLE user (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL
);
CREATE TABLE token (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES user(id)
);
CREATE TABLE article (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES user(id)
);
CREATE TRIGGER article_updated_at AFTER UPDATE ON article
BEGIN
    UPDATE article SET updated_at=CURRENT_TIMESTAMP WHERE id=NEW.id;
END;
        ''')
        db.commit()

def query_db(query, args=(), one=False, commit=False):
    db = get_db()
    cursor = db.execute(query, args)
    result = None
    if commit:
        db.commit()
    else:
        result = cursor.fetchall()
        cursor.close()
    if one:
        return result[0] if result else None
    return result

def longest_common_subsequence_length(seq1, seq2):
    m, n = len(seq1), len(seq2)
    dp = [[0]*(n+1) for _ in range(m+1)]
    i = 0
    while i < m:
        j = 0
        while j < n:
            if seq1[i] == seq2[j]:
                dp[i+1][j+1] = dp[i][j] + 1
            else:
                dp[i+1][j+1] = max(dp[i][j+1], dp[i+1][j])
            j += 1
        i += 1
    return dp[m][n]

def get_user_from_token():
    token_value = request.headers.get("Authorization")
    if not token_value:
        return None
    user_row = query_db(
        "SELECT user.* FROM token JOIN user ON token.user_id = user.id WHERE token.token = ?",
        (token_value,),
        one=True,
    )
    if not user_row:
        return None
    return dict(user_row)

@app.route('/login.html')
def login_page():
    return '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <title>登录 / 注册 - 文章系统</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet" />
  <script src="https://unpkg.com/vue@3/dist/vue.global.prod.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/axios/dist/axios.min.js"></script>
  <style>
    body { max-width: 400px; margin: 50px auto; font-family: "Microsoft YaHei", Arial, sans-serif; }
  </style>
</head>
<body>

<div id="app" class="card p-4 shadow">
  <h3 class="mb-3 text-center">登录 / 注册</h3>

  <div class="mb-3">
    <input v-model="usernameInput" type="text" class="form-control" placeholder="请输入用户名" @keyup.enter="handleRegisterOrLogin" />
  </div>

  <div class="d-grid">
    <button @click="handleRegisterOrLogin" class="btn btn-primary">登录或注册</button>
  </div>

  <div class="mt-3 text-danger" v-if="errorMessage">{{ errorMessage }}</div>
</div>

<script>
const { createApp } = Vue;

createApp({
  data() {
    return {
      usernameInput: '',
      errorMessage: ''
    }
  },
  methods: {
    async handleRegisterOrLogin() {
      this.errorMessage = '';
      const trimmedUsername = this.usernameInput.trim();
      if(!trimmedUsername){
        this.errorMessage = '用户名不能为空';
        return;
      }
      try {
        const response = await axios.post('/api/register_or_login', { username: trimmedUsername });
        localStorage.setItem('token', response.data.token);
        localStorage.setItem('user', JSON.stringify(response.data.user));
        window.location.href = '/articles.html';
      } catch(err) {
        this.errorMessage = err.response?.data?.error || '请求失败';
      }
    }
  }
}).mount('#app');
</script>

</body>
</html>
'''

@app.route('/articles.html')
def articles_page():
    return '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <title>文章系统</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet" />
  <script src="https://unpkg.com/vue@3/dist/vue.global.prod.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/axios/dist/axios.min.js"></script>
  <style>
    body { max-width: 900px; margin: 20px auto; font-family: "Microsoft YaHei", Arial, sans-serif; }
    .pointer { cursor: pointer; }
    .user-result:hover, .article-card:hover { background-color: #f0f0f0; cursor:pointer; }
  </style>
</head>
<body>

<div id="app">
  <div class="d-flex justify-content-between align-items-center mb-4">
    <h2>欢迎，{{ currentUser?.username || '游客'}}</h2>
    <div>
      <button v-if="isLoggedIn" @click="handleLogout" class="btn btn-sm btn-outline-danger">退出登录</button>
      <a v-else href="/login.html" class="btn btn-sm btn-primary">登录 / 注册</a>
    </div>
  </div>

  <div v-if="!isLoggedIn" class="alert alert-info">
    请先 <a href="/login.html">登录或注册</a>，以操作文章。
  </div>

  <div class="mb-4">
    <h4>搜索用户</h4>
    <input v-model="usernameQuery" @input="searchUsers" type="text" placeholder="输入用户名关键词进行搜索" class="form-control" />
    <ul class="list-group mt-2" v-if="matchedUsers.length>0">
      <li v-for="user in matchedUsers" :key="user.id" class="list-group-item user-result" @click="selectUser(user)">
        {{ user.username }} <small class="text-muted">(匹配度: {{user.score}})</small>
      </li>
    </ul>
    <div v-else-if="usernameQuery" class="text-muted mt-2">未找到匹配用户</div>
  </div>

  <div v-if="selectedUser" class="mb-5">
    <div class="d-flex justify-content-between align-items-center mb-2">
      <h4>用户 "{{ selectedUser.username }}" 的文章</h4>
      <button class="btn btn-outline-secondary btn-sm" @click="clearUserSelection">关闭</button>
    </div>
    <div v-if="selectedUserArticles.length === 0" class="text-muted">该用户暂无文章</div>
    <div>
      <div v-for="article in selectedUserArticles" :key="article.id" class="card mb-2 article-card">
        <div class="card-body">
          <h5 @click="viewArticle(article)" class="text-primary pointer">{{ article.title }}</h5>
          <p>
            <small class="text-secondary">文章ID: {{ article.id }}，更新时间: {{ article.updated_at }}</small>
          </p>
          <div v-if="isLoggedIn && currentUser.id === selectedUser.id">
            <button class="btn btn-sm btn-outline-primary me-2" @click="startEditArticle(article)">编辑</button>
            <button class="btn btn-sm btn-outline-danger" @click="confirmDeleteArticle(article)">删除</button>
          </div>
        </div>
      </div>
    </div>
  </div>

  <div v-if="articleEditorVisible" class="mb-4 card p-3">
    <h4>{{ editingArticle.id ? '编辑文章 #' + editingArticle.id : '新建文章' }}</h4>
    <div class="mb-3">
      <label>标题</label>
      <input v-model="editingArticle.title" type="text" class="form-control" placeholder="请输入标题" />
    </div>
    <div class="mb-3">
      <label>内容</label>
      <textarea v-model="editingArticle.content" rows="6" class="form-control" placeholder="请输入内容"></textarea>
    </div>
    <button class="btn btn-success me-2" @click="saveArticle">保存</button>
    <button class="btn btn-secondary" @click="cancelEditing">取消</button>
  </div>

  <button v-if="isLoggedIn && selectedUser && currentUser.id === selectedUser.id && !articleEditorVisible" class="btn btn-primary mb-4"
    @click="startCreateArticle">
    发布新文章
  </button>

  <div v-if="viewingArticle" class="card p-3 mb-4">
    <h4>文章详情：{{ viewingArticle.title }}</h4>
    <p><strong>内容：</strong></p>
    <pre style="white-space: pre-wrap;">{{ viewingArticle.content }}</pre>
    <button class="btn btn-outline-secondary mt-2" @click="closeArticleView">关闭</button>
  </div>

  <div>
    <h4>搜索文章</h4>
    <input v-model="articleTitleQuery" @input="searchArticles" type="text" class="form-control" placeholder="输入文章标题关键词进行搜索" />
    <ul class="list-group mt-2" v-if="matchedArticles.length > 0">
      <li v-for="result in matchedArticles" :key="result.article.id" class="list-group-item article-card" @click="viewArticle(result.article)">
        {{ result.article.title }}
        <br/>
        <small class="text-secondary">
          作者ID: {{ result.article.user_id }}，匹配度: {{ result.score }}
        </small>
      </li>
    </ul>
    <div v-else-if="articleTitleQuery" class="text-muted mt-2">未找到匹配文章</div>
  </div>

</div>

<script>
const { createApp } = Vue;

createApp({
  data() {
    return {
      currentUser: null,
      token: null,
      usernameQuery: '',
      matchedUsers: [],
      selectedUser: null,
      selectedUserArticles: [],
      editingArticle: null,
      articleEditorVisible: false,
      viewingArticle: null,
      articleTitleQuery: '',
      matchedArticles: []
    }
  },
  computed: {
    isLoggedIn() {
      return !!this.token && !!this.currentUser;
    }
  },
  mounted() {
    this.token = localStorage.getItem('token');
    this.currentUser = JSON.parse(localStorage.getItem('user'));
  },
  methods: {
    getAuthHeaders() {
      return { headers: { Authorization: this.token } };
    },
    async searchUsers() {
      if (!this.usernameQuery.trim()) {
        this.matchedUsers = [];
        return;
      }
      try {
        const response = await axios.get('/api/users/search', {
          params: { usernameQuery: this.usernameQuery.trim() }
        });
        this.matchedUsers = response.data;
      } catch (error) {
        console.error('搜索用户出错：', error);
      }
    },
    async selectUser(user) {
      this.selectedUser = user;
      this.selectedUserArticles = [];
      this.viewingArticle = null;
      this.articleEditorVisible = false;

      try {
        const response = await axios.get(`/api/users/${user.id}/articles`);
        this.selectedUserArticles = response.data;
      } catch (error) {
        alert('获取用户文章失败');
      }
    },
    clearUserSelection() {
      this.selectedUser = null;
      this.selectedUserArticles = [];
      this.viewingArticle = null;
      this.articleEditorVisible = false;
    },
    viewArticle(article) {
      this.viewingArticle = article;
      this.articleEditorVisible = false;
    },
    closeArticleView() {
      this.viewingArticle = null;
    },
    startCreateArticle() {
      this.editingArticle = { title: '', content: '' };
      this.articleEditorVisible = true;
      this.viewingArticle = null;
    },
    startEditArticle(article) {
      this.editingArticle = { ...article };
      this.articleEditorVisible = true;
      this.viewingArticle = null;
    },
    cancelEditing() {
      this.editingArticle = null;
      this.articleEditorVisible = false;
    },
    async saveArticle() {
      if (!this.editingArticle.title.trim() || !this.editingArticle.content.trim()) {
        alert('标题和内容不能为空');
        return;
      }
      try {
        if (this.editingArticle.id) {
          const response = await axios.put(
            `/api/articles/${this.editingArticle.id}`,
            {
              title: this.editingArticle.title.trim(),
              content: this.editingArticle.content.trim()
            },
            this.getAuthHeaders()
          );
          for (let i = 0; i < this.selectedUserArticles.length; i++) {
            if (this.selectedUserArticles[i].id === response.data.id) {
              this.selectedUserArticles[i] = response.data;
              break;
            }
          }
        } else {
          const response = await axios.post(
            '/api/articles',
            {
              title: this.editingArticle.title.trim(),
              content: this.editingArticle.content.trim()
            },
            this.getAuthHeaders()
          );
          this.selectedUserArticles.unshift(response.data);
        }
        this.cancelEditing();
      } catch (error) {
        alert(error.response?.data?.error || '保存文章失败');
      }
    },
    async confirmDeleteArticle(article) {
      if (!confirm(`确定删除文章 "${article.title}" 吗？`)) {
        return;
      }
      try {
        await axios.delete(`/api/articles/${article.id}`, this.getAuthHeaders());
        this.selectedUserArticles = this.selectedUserArticles.filter(a => a.id !== article.id);
        if(this.viewingArticle && this.viewingArticle.id === article.id) {
          this.viewingArticle = null;
        }
      } catch (error) {
        alert(error.response?.data?.error || '删除文章失败');
      }
    },
    async searchArticles() {
      if (!this.articleTitleQuery.trim()) {
        this.matchedArticles = [];
        return;
      }
      try {
        const response = await axios.get('/api/articles/search', {
          params: { titleQuery: this.articleTitleQuery.trim() }
        });
        this.matchedArticles = response.data;
      } catch (error) {
        console.error('搜索文章出错：', error);
      }
    },
    handleLogout() {
      localStorage.removeItem('token');
      localStorage.removeItem('user');
      this.token = null;
      this.currentUser = null;
    }
  }
}).mount('#app');
</script>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>

</body>
</html>
'''

@app.route('/api/register_or_login', methods=['POST'])
def register_or_login():
    data = request.get_json()
    username = data.get("username", "").strip()
    if not username:
        return jsonify({"error":"用户名不能为空"}), 400

    existing_user = query_db("SELECT * FROM user WHERE username=?", (username,), one=True)
    if existing_user:
        user = dict(existing_user)
    else:
        try:
            db = get_db()
            cursor = db.execute("INSERT INTO user (username) VALUES (?)", (username,))
            db.commit()
            user_id = cursor.lastrowid
            new_user = query_db("SELECT * FROM user WHERE id=?", (user_id,), one=True)
            user = dict(new_user)
        except sqlite3.IntegrityError:
            return jsonify({"error": "用户名已存在"}), 400

    token_str = str(uuid.uuid4())
    db = get_db()
    db.execute("INSERT INTO token (token, user_id) VALUES (?, ?)", (token_str, user["id"]))
    db.commit()
    return jsonify({"token": token_str, "user": {"id": user["id"], "username": user["username"]}})

@app.route('/api/users/search')
def user_search():
    username_query = request.args.get("usernameQuery", "").lower().strip()
    if not username_query:
        return jsonify([])

    query_words = username_query.split()
    users_rows = query_db("SELECT * FROM user")
    matched_users = []
    for user_row in users_rows:
        user_words = user_row['username'].lower().split()
        score = longest_common_subsequence_length(query_words, user_words)
        if score > 0:
            matched_users.append({
                "id": user_row["id"],
                "username": user_row["username"],
                "score": score
            })
    matched_users.sort(key=lambda u: u["score"], reverse=True)
    return jsonify(matched_users)

@app.route('/api/users/<int:user_id>/articles')
def get_user_articles(user_id):
    user_row = query_db("SELECT * FROM user WHERE id=?", (user_id,), one=True)
    if not user_row:
        return jsonify({"error": "用户不存在"}), 404

    articles_rows = query_db("SELECT * FROM article WHERE user_id = ? ORDER BY created_at DESC", (user_id,))
    user_articles = []
    for row in articles_rows:
        user_articles.append(dict(row))
    return jsonify(user_articles)

@app.route('/api/articles', methods=['POST'])
def create_article():
    user = get_user_from_token()
    if not user:
        return jsonify({"error": "需要登录"}), 401

    data = request.get_json()
    title = data.get("title", "").strip()
    content = data.get("content", "").strip()
    if not title or not content:
        return jsonify({"error": "标题和内容不能为空"}), 400

    db = get_db()
    cursor = db.execute("INSERT INTO article (user_id, title, content) VALUES (?, ?, ?)", (user["id"], title, content))
    db.commit()
    article_id = cursor.lastrowid
    new_article = query_db("SELECT * FROM article WHERE id=?", (article_id,), one=True)
    return jsonify(dict(new_article))

@app.route('/api/articles/<int:article_id>', methods=['GET'])
def get_article(article_id):
    article_row = query_db("SELECT * FROM article WHERE id=?", (article_id,), one=True)
    if not article_row:
        return jsonify({"error": "文章不存在"}), 404
    return jsonify(dict(article_row))

@app.route("/api/articles/<int:article_id>", methods=["PUT"])
def update_article(article_id):
    user = get_user_from_token()
    if not user:
        return jsonify({"error": "需要登录"}), 401

    article_row = query_db("SELECT * FROM article WHERE id=?", (article_id,), one=True)
    if not article_row:
        return jsonify({"error": "文章不存在"}), 404

    if article_row["user_id"] != user["id"]:
        return jsonify({"error": "无权限编辑此文章"}), 403

    data = request.get_json()
    title = data.get("title", "").strip()
    content = data.get("content", "").strip()
    if not title or not content:
        return jsonify({"error": "标题和内容不能为空"}), 400

    db = get_db()
    db.execute("UPDATE article SET title=?, content=? WHERE id=?", (title, content, article_id))
    db.commit()
    updated_article = query_db("SELECT * FROM article WHERE id=?", (article_id,), one=True)
    return jsonify(dict(updated_article))

@app.route("/api/articles/<int:article_id>", methods=["DELETE"])
def delete_article(article_id):
    user = get_user_from_token()
    if not user:
        return jsonify({"error": "需要登录"}), 401

    article_row = query_db("SELECT * FROM article WHERE id=?", (article_id,), one=True)
    if not article_row:
        return jsonify({"error": "文章不存在"}), 404

    if article_row["user_id"] != user["id"]:
        return jsonify({"error": "无权限删除此文章"}), 403

    db = get_db()
    db.execute("DELETE FROM article WHERE id=?", (article_id,))
    db.commit()
    return jsonify({"success": True})

@app.route("/api/articles/search")
def search_articles():
    title_query = request.args.get("titleQuery", "").lower().strip()
    if not title_query:
        return jsonify([])

    query_words = title_query.split()
    articles_rows = query_db("SELECT * FROM article")
    matched = []
    for row in articles_rows:
        title_words = row["title"].lower().split()
        score = longest_common_subsequence_length(query_words, title_words)
        if score > 0:
            matched.append({"article": dict(row), "score": score})
    matched.sort(key=lambda x: x["score"], reverse=True)
    return jsonify(matched)

if __name__ == '__main__':
    init_db()
    app.run(debug=True)
