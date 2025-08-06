import os
import uuid
import sqlite3
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, g

app = Flask(__name__)
DATABASE = 'app.db'
TOKEN_EXPIRE_HOURS = 24  # token过期时间，单位：小时

def get_db():
    """获取当前请求的数据库连接，会话结束时自动关闭"""
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)  # 连接数据库
        db.row_factory = sqlite3.Row  # 结果以字典形式返回，方便使用
    return db

@app.teardown_appcontext
def close_db(exc):
    """关闭数据库连接，在请求结束时触发"""
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def init_db():
    """初始化数据库，创建表（如果不存在）"""
    if os.path.exists(DATABASE):
        return  # 已存在数据库，跳过初始化
    with app.app_context():
        db = get_db()
        # 创建用户、token、文章表，注意token表增加过期时间字段 expire_at
        db.executescript('''
CREATE TABLE user (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL
);
CREATE TABLE token (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expire_at TIMESTAMP NOT NULL,
    FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE CASCADE
);
CREATE TABLE article (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE CASCADE
);
        ''')
        db.commit()  # 提交创建表

def query_db(query, args=(), one=False, commit=False):
    """
    查询数据库辅助函数，执行SQL，支持提取单条或多条结果，或提交修改
    """
    db = get_db()
    cursor = db.execute(query, args)
    if commit:
        db.commit()
        cursor.close()
        return None
    else:
        rv = cursor.fetchall()
        cursor.close()
        if one:
            return rv[0] if rv else None
        return rv

def longest_common_subsequence_length(seq1, seq2):
    """
    计算两个字符串序列的最长公共子序列长度（LCS），作为匹配评分依据
    seq1, seq2: list[str]
    返回：int，LCS长度
    """
    m, n = len(seq1), len(seq2)
    dp = [[0]*(n+1) for _ in range(m+1)]
    for i in range(m):
        for j in range(n):
            if seq1[i] == seq2[j]:
                dp[i+1][j+1] = dp[i][j] + 1
            else:
                dp[i+1][j+1] = max(dp[i][j+1], dp[i+1][j])
    return dp[m][n]

def get_user_from_token():
    """
    根据请求头 Authorization 获取用户信息，验证 token 有效性和过期情况
    返回用户字典 或 None 表示未登录或无效token
    """
    token_value = request.headers.get("Authorization")
    if not token_value:
        return None

    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    # 查询 token 是否存在且未过期，同时联表获取用户信息
    user_row = query_db(
        "SELECT user.* FROM token JOIN user ON token.user_id = user.id "
        "WHERE token.token = ? AND expire_at > ?",
        (token_value, now_str),
        one=True,
    )
    if not user_row:
        return None
    return dict(user_row)

@app.route('/login.html')
def login_page():
    """
    登录/注册页面：通过用户名登录或注册账号，获取 token
    功能场景：用户输入用户名，提交至后端；前端保存token和用户信息至localStorage
    """
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
    <input v-model="usernameInput" type="text" class="form-control" placeholder="请输入用户名" maxlength="30" @keyup.enter="handleRegisterOrLogin" />
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
      if(trimmedUsername.length > 30){
        this.errorMessage = '用户名不能超过30个字符';
        return;
      }
      try {
        // 调用后端接口注册或登录，成功返回token与用户数据
        const response = await axios.post('/api/register_or_login', { username: trimmedUsername });
        localStorage.setItem('token', response.data.token);
        localStorage.setItem('user', JSON.stringify(response.data.user));
        window.location.href = '/articles.html';  // 登陆成功跳转文章页
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
    """
    文章管理主页面：
    - 显示当前登录用户信息
    - 搜索用户、查看用户文章
    - 搜索文章
    - 登录后可新建/编辑/删除自己文章
    - 基本防XSS转义显示内容
    """
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
    pre { white-space: pre-wrap; word-wrap: break-word; }
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

  <!-- 搜索用户 -->
  <div class="mb-4">
    <h4>搜索用户</h4>
    <input v-model="usernameQuery" @input="debounceSearchUsers" type="text" placeholder="输入用户名关键词进行搜索" class="form-control" maxlength="30" />
    <ul class="list-group mt-2" v-if="matchedUsers.length>0">
      <li v-for="user in matchedUsers" :key="user.id" class="list-group-item user-result" @click="selectUser(user)">
        {{ user.username }} <small class="text-muted">(匹配度: {{user.score}})</small>
      </li>
    </ul>
    <div v-else-if="usernameQuery" class="text-muted mt-2">未找到匹配用户</div>
  </div>

  <!-- 用户文章列表 -->
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
          <!-- 当前登录用户自己的文章，可编辑删除 -->
          <div v-if="isLoggedIn && currentUser.id === selectedUser.id">
            <button class="btn btn-sm btn-outline-primary me-2" @click="startEditArticle(article)">编辑</button>
            <button class="btn btn-sm btn-outline-danger" @click="confirmDeleteArticle(article)">删除</button>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- 文章编辑表单（新建或编辑） -->
  <div v-if="articleEditorVisible" class="mb-4 card p-3">
    <h4>{{ editingArticle.id ? '编辑文章 #' + editingArticle.id : '新建文章' }}</h4>
    <div class="mb-3">
      <label for="article-title">标题</label>
      <input id="article-title" v-model="editingArticle.title" type="text" class="form-control" placeholder="请输入标题" maxlength="100" />
    </div>
    <div class="mb-3">
      <label for="article-content">内容</label>
      <textarea id="article-content" v-model="editingArticle.content" rows="6" class="form-control" placeholder="请输入内容" maxlength="5000"></textarea>
    </div>
    <button class="btn btn-success me-2" @click="saveArticle">保存</button>
    <button class="btn btn-secondary" @click="cancelEditing">取消</button>
  </div>

  <!-- 新建文章按钮：登录用户且查看自己文章时显示 -->
  <button v-if="isLoggedIn && selectedUser && currentUser.id === selectedUser.id && !articleEditorVisible" class="btn btn-primary mb-4"
    @click="startCreateArticle">
    发布新文章
  </button>

  <!-- 查看文章详情 -->
  <div v-if="viewingArticle" class="card p-3 mb-4">
    <h4>文章详情：{{ viewingArticle.title }}</h4>
    <p><strong>内容：</strong></p>
    <pre v-html="viewingArticle.safe_content"></pre>
    <button class="btn btn-outline-secondary mt-2" @click="closeArticleView">关闭</button>
  </div>

  <!-- 文章搜索 -->
  <div>
    <h4>搜索文章</h4>
    <input v-model="articleTitleQuery" @input="debounceSearchArticles" type="text" class="form-control" placeholder="输入文章标题关键词进行搜索" maxlength="100" />
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

// 简单防抖函数，避免接口频繁调用
function debounce(fn, delay = 300) {
  let timer = null;
  return function(...args) {
    clearTimeout(timer);
    timer = setTimeout(() => fn.apply(this, args), delay);
  };
}

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
    this.token = localStorage.getItem('token');  // 取token
    const userStr = localStorage.getItem('user');
    this.currentUser = userStr ? JSON.parse(userStr) : null;

    // 如果token存在但用户信息缺失，强制退出登录，避免异常状态
    if(this.token && !this.currentUser){
      this.handleLogout();
    }
  },
  methods: {
    /**
     * 返回含认证头的axios请求头
     */
    getAuthHeaders() {
      return { headers: { Authorization: this.token } };
    },
    /**
     * 调用后端接口，搜索用户匹配，更新matchedUsers数组
     */
    async searchUsers() {
      const q = this.usernameQuery.trim();
      if (!q) {
        this.matchedUsers = [];
        return;
      }
      try {
        const response = await axios.get('/api/users/search', { params: { usernameQuery: q, limit: 20 } });
        this.matchedUsers = response.data;
      } catch (error) {
        console.error('搜索用户出错：', error);
      }
    },
    debounceSearchUsers: null,  // 防抖包装后赋值下面created周期
    /** 处理选中用户，显示其文章 */
    async selectUser(user) {
      this.selectedUser = user;
      this.selectedUserArticles = [];
      this.viewingArticle = null;
      this.articleEditorVisible = false;

      try {
        const response = await axios.get(`/api/users/${user.id}/articles`);
        // 转义HTML，避免XSS
        this.selectedUserArticles = response.data.map(a => {
          a.safe_content = this.escapeHtml(a.content); 
          return a;
        });
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
      // 再次转义，确保安全
      article.safe_content = this.escapeHtml(article.content);
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
      // 复制一份，避免修改过程中错误影响列表数据
      this.editingArticle = { ...article };
      this.articleEditorVisible = true;
      this.viewingArticle = null;
    },
    cancelEditing() {
      this.editingArticle = null;
      this.articleEditorVisible = false;
    },
    /**
     * 简单转义文本，防止插入非法html脚本
     * 并支持pre标签内正确显示
     */
    escapeHtml(text){
      if (!text) return '';
      return text.replace(/&/g, '&amp;')
                 .replace(/</g, '&lt;')
                 .replace(/>/g, '&gt;')
                 .replace(/"/g, '&quot;')
                 .replace(/'/g, '&#39;')
                 .replace(/\//g, '&#x2F;');
    },
    /**
     * 保存文章：新建或编辑，调用相应后端接口，带入认证头
     */
    async saveArticle() {
      if (!this.editingArticle.title.trim() || !this.editingArticle.content.trim()) {
        alert('标题和内容不能为空');
        return;
      }
      if(this.editingArticle.title.trim().length > 100){
        alert('标题不能超过100个字符');
        return;
      }
      if(this.editingArticle.content.trim().length > 5000){
        alert('内容不能超过5000个字符');
        return;
      }
      try {
        if (this.editingArticle.id) {
          // 编辑文章PUT接口
          const response = await axios.put(
            `/api/articles/${this.editingArticle.id}`,
            {
              title: this.editingArticle.title.trim(),
              content: this.editingArticle.content.trim()
            },
            this.getAuthHeaders()
          );
          // 更新本地列表对应文章
          for (let i = 0; i < this.selectedUserArticles.length; i++) {
            if (this.selectedUserArticles[i].id === response.data.id) {
              response.data.safe_content = this.escapeHtml(response.data.content);
              this.selectedUserArticles[i] = response.data;
              break;
            }
          }
        } else {
          // 新建文章POST接口
          const response = await axios.post(
            '/api/articles',
            {
              title: this.editingArticle.title.trim(),
              content: this.editingArticle.content.trim()
            },
            this.getAuthHeaders()
          );
          response.data.safe_content = this.escapeHtml(response.data.content);
          // 新文章插入到最前面列表
          this.selectedUserArticles.unshift(response.data);
        }
        this.cancelEditing();
      } catch (error) {
        if(error.response && error.response.status === 401){
          alert("登录已失效，请重新登录");
          this.handleLogout();
          return;
        }
        alert(error.response?.data?.error || '保存文章失败');
      }
    },
    /**
     * 删除文章接口，确认后调用，验证权限，刷新列表
     */
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
        if(error.response && error.response.status === 401){
          alert("登录已失效，请重新登录");
          this.handleLogout();
          return;
        }
        alert(error.response?.data?.error || '删除文章失败');
      }
    },
    /**
     * 文章搜索，调用后端搜索接口，更新matchedArticles数组
     */
    async searchArticles() {
      const q = this.articleTitleQuery.trim();
      if (!q) {
        this.matchedArticles = [];
        return;
      }
      try {
        const response = await axios.get('/api/articles/search', {
          params: { titleQuery: q, limit: 20 }
        });
        this.matchedArticles = response.data;
      } catch (error) {
        console.error('搜索文章出错：', error);
      }
    },
    debounceSearchArticles: null,
    /**
     * 注销登录，清理本地存储，跳转登录页
     */
    handleLogout() {
      localStorage.removeItem('token');
      localStorage.removeItem('user');
      this.token = null;
      this.currentUser = null;
      window.location.href = '/login.html';
    }
  },
  created() {
    // 包装搜索函数防抖，避免请求频繁
    this.debounceSearchUsers = debounce(this.searchUsers, 300);
    this.debounceSearchArticles = debounce(this.searchArticles, 300);
  }
}).mount('#app');
</script>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>

</body>
</html>
'''

@app.route('/api/register_or_login', methods=['POST'])
def register_or_login():
    """
    用户注册或登录接口：
    - 如果用户名不存在则注册
    - 生成新的token，过期时间1天，存入数据库
    - 清理过期token，防止持久化token膨胀
    - 返回token和用户信息
    """
    data = request.get_json()
    username = data.get("username", "").strip()
    if not username:
        return jsonify({"error":"用户名不能为空"}), 400
    if len(username) > 30:
        return jsonify({"error":"用户名不能超过30个字符"}), 400

    existing_user = query_db("SELECT * FROM user WHERE username=?", (username,), one=True)
    db = get_db()
    if existing_user:
        user = dict(existing_user)
    else:
        try:
            cursor = db.execute("INSERT INTO user (username) VALUES (?)", (username,))
            db.commit()
            user_id = cursor.lastrowid
            new_user = query_db("SELECT * FROM user WHERE id=?", (user_id,), one=True)
            user = dict(new_user)
        except sqlite3.IntegrityError:
            # 理论上不会到这里，用户名唯一约束已检测
            return jsonify({"error": "用户名已存在"}), 400

    # 清理过期token（expire_at <=当前时间），保证数据库不会无限增长
    now = datetime.utcnow()
    expire_cutoff = now.strftime("%Y-%m-%d %H:%M:%S")
    db.execute("DELETE FROM token WHERE expire_at <= ?", (expire_cutoff,))
    db.commit()

    # 生成token，过期时间1天后
    token_str = str(uuid.uuid4())
    expire_at = (now + timedelta(hours=TOKEN_EXPIRE_HOURS)).strftime("%Y-%m-%d %H:%M:%S")
    db.execute("INSERT INTO token (token, user_id, expire_at) VALUES (?, ?, ?)", (token_str, user["id"], expire_at))
    db.commit()
    return jsonify({"token": token_str, "user": {"id": user["id"], "username": user["username"]}})

@app.route('/api/users/search')
def user_search():
    """
    用户模糊搜索接口，基于最长公共子序列算法评分匹配
    - usernameQuery: 查询关键词（多个词用空格分隔）
    - limit: 返回匹配结果数量的最大值（100以内）
    返回排序后的用户列表，包含匹配度score
    """
    username_query = request.args.get("usernameQuery", "").lower().strip()
    limit = min(int(request.args.get("limit", 20)), 100)  # 最大100条限制，防止滥用
    if not username_query:
        # 空查询返回空列表
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
    # 按score降序排序，匹配更高优先
    matched_users.sort(key=lambda u: u["score"], reverse=True)
    return jsonify(matched_users[:limit])

@app.route('/api/users/<int:user_id>/articles')
def get_user_articles(user_id):
    """
    根据用户id获取该用户所有文章接口
    返回数组，按创建时间倒序
    """
    user_row = query_db("SELECT * FROM user WHERE id=?", (user_id,), one=True)
    if not user_row:
        return jsonify({"error": "用户不存在"}), 404

    articles_rows = query_db("SELECT * FROM article WHERE user_id = ? ORDER BY created_at DESC", (user_id,))
    # 直接返回所有文章字段，前端自行转义展示
    user_articles = [dict(row) for row in articles_rows]
    return jsonify(user_articles)

@app.route('/api/articles', methods=['POST'])
def create_article():
    """
    新建文章接口，需要登录（token认证）
    必须传递title与content，前后端已限制长度
    返回新文章信息
    """
    user = get_user_from_token()
    if not user:
        return jsonify({"error": "需要登录"}), 401

    data = request.get_json()
    title = data.get("title", "").strip()
    content = data.get("content", "").strip()

    if not title or not content:
        return jsonify({"error": "标题和内容不能为空"}), 400
    if len(title) > 100:
        return jsonify({"error": "标题不能超过100个字符"}), 400
    if len(content) > 5000:
        return jsonify({"error": "内容不能超过5000个字符"}), 400

    db = get_db()
    cursor = db.execute("INSERT INTO article (user_id, title, content) VALUES (?, ?, ?)", (user["id"], title, content))
    db.commit()
    article_id = cursor.lastrowid
    new_article = query_db("SELECT * FROM article WHERE id=?", (article_id,), one=True)
    return jsonify(dict(new_article))

@app.route('/api/articles/<int:article_id>', methods=['GET'])
def get_article(article_id):
    """
    获取文章详情接口，根据文章id
    """
    article_row = query_db("SELECT * FROM article WHERE id=?", (article_id,), one=True)
    if not article_row:
        return jsonify({"error": "文章不存在"}), 404
    return jsonify(dict(article_row))

@app.route("/api/articles/<int:article_id>", methods=["PUT"])
def update_article(article_id):
    """
    编辑文章接口，仅允许本人编辑，需登录和token验证
    更新title与content，同时更新updated_at为当前时间
    删除原触发器，改为手动更新时间避免递归问题
    """
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
    if len(title) > 100:
        return jsonify({"error": "标题不能超过100个字符"}), 400
    if len(content) > 5000:
        return jsonify({"error": "内容不能超过5000个字符"}), 400

    db = get_db()
    # 手动更新时间，避免触发器递归风险
    db.execute("UPDATE article SET title=?, content=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (title, content, article_id))
    db.commit()
    updated_article = query_db("SELECT * FROM article WHERE id=?", (article_id,), one=True)
    return jsonify(dict(updated_article))

@app.route("/api/articles/<int:article_id>", methods=["DELETE"])
def delete_article(article_id):
    """
    删除文章接口，仅允许本人删除，需登录验证
    成功返回 { "success": true }
    """
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
    """
    文章标题模糊搜索接口，基于最长公共子序列算法匹配
    参数：titleQuery，limit（最多100）
    返回：匹配文章数组，包含article对象和匹配度score
    """
    title_query = request.args.get("titleQuery", "").lower().strip()
    limit = min(int(request.args.get("limit", 20)), 100)  # 最大100条，防止滥用

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
    # 按匹配度降序排列，优先显示高匹配文章
    matched.sort(key=lambda x: x["score"], reverse=True)
    return jsonify(matched[:limit])

if __name__ == '__main__':
    init_db()  # 初始化数据库（仅首次运行创建）
    app.run(debug=True)
