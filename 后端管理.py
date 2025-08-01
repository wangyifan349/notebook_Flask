import os
import re
import json
import bcrypt
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_jwt_extended import (
    JWTManager, create_access_token, jwt_required, get_jwt_identity,
    jwt_optional
)
from sqlalchemy import event, text
from sqlalchemy.engine import Engine

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///notesapp.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["JWT_SECRET_KEY"] = os.getenv("JWT_SECRET_KEY","super-secret-key")
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(days=7)
db = SQLAlchemy(app)
jwt = JWTManager(app)

@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.LargeBinary(60), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, pw:str):
        self.password_hash = bcrypt.hashpw(pw.encode(), bcrypt.gensalt())

    def check_password(self, pw:str) -> bool:
        return bcrypt.checkpw(pw.encode(), self.password_hash)

class Note(db.Model):
    __tablename__ = "notes"
    id = db.Column(db.Integer, primary_key=True)
    author_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    title = db.Column(db.String(255), nullable=False)
    content = db.Column(db.Text, nullable=False)
    is_public = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    author = db.relationship("User", backref=db.backref("notes", lazy=True))

def setup_fts5():
    with app.app_context():
        conn = db.engine.raw_connection()
        c = conn.cursor()
        c.execute("CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(title, content, content='notes', content_rowid='id');")
        c.execute("""
            CREATE TRIGGER IF NOT EXISTS notes_ai AFTER INSERT ON notes BEGIN
                INSERT INTO notes_fts(rowid, title, content) VALUES (new.id, new.title, new.content);
            END;
        """)
        c.execute("""
            CREATE TRIGGER IF NOT EXISTS notes_ad AFTER DELETE ON notes BEGIN
                INSERT INTO notes_fts(notes_fts, rowid, title, content) VALUES('delete', old.id, old.title, old.content);
            END;
        """)
        c.execute("""
            CREATE TRIGGER IF NOT EXISTS notes_au AFTER UPDATE ON notes BEGIN
                INSERT INTO notes_fts(notes_fts, rowid, title, content) VALUES('delete', old.id, old.title, old.content);
                INSERT INTO notes_fts(rowid, title, content) VALUES (new.id, new.title, new.content);
            END;
        """)
        conn.commit()
        c.close()
        conn.close()

def longest_common_subsequence(a: str, b: str) -> int:
    a = a.lower()
    b = b.lower()
    m, n = len(a), len(b)
    dp = [ [0]*(n+1) for _ in range(m+1)]
    for i in range(m):
        for j in range(n):
            if a[i] == b[j]:
                dp[i+1][j+1] = dp[i][j] +1
            else:
                dp[i+1][j+1] = max(dp[i][j+1], dp[i+1][j])
    return dp[m][n]

@app.route("/auth/register", methods=["POST"])
def register():
    data = request.json
    if not data or not all(k in data for k in ("username","email","password")):
        return jsonify({"msg":"缺少注册信息"}), 400
    if User.query.filter_by(username=data["username"]).first():
        return jsonify({"msg":"用户名已被注册"}), 400
    if User.query.filter_by(email=data["email"]).first():
        return jsonify({"msg":"邮箱已被注册"}), 400
    u = User(username=data["username"], email=data["email"])
    u.set_password(data["password"])
    db.session.add(u)
    db.session.commit()
    return jsonify({"msg":"注册成功"}), 201

@app.route("/auth/login", methods=["POST"])
def login():
    data = request.json
    if not data or not data.get("username") or not data.get("password"):
        return jsonify({"msg":"请输入用户名和密码"}), 400
    user = User.query.filter((User.username==data['username']) | (User.email==data['username'])).first()
    if not user or not user.check_password(data["password"]):
        return jsonify({"msg":"用户名或密码错误"}), 401
    access_token = create_access_token(identity=user.id)
    return jsonify({"access_token": access_token, "username": user.username})

# --- 用户搜索接口 使用 LCS 排序，返回相似度score ---
@app.route("/users/search")
@jwt_required()
def user_search():
    q = request.args.get("q","").strip()
    if not q:
        return jsonify([])
    users = User.query.filter(User.username.ilike(f"%{q}%")).all()
    scored = []
    for u in users:
        score = longest_common_subsequence(u.username, q)
        scored.append( (score, u) )
    scored.sort(key=lambda x: x[0], reverse=True)
    result = [{"id":u.id,"username":u.username, "score":score} for score,u in scored[:20]]
    return jsonify(result)

# --- 用户主页获取某个用户笔记, 支持搜索 并结合标题2倍权重 + 内容1倍权重降序 ---
@app.route("/users/<int:user_id>/notes")
@jwt_optional
def user_notes(user_id):
    q = request.args.get("q", "").strip()
    current_user_id = get_jwt_identity()
    target_user = User.query.get_or_404(user_id)

    base_query = Note.query.filter_by(author_id=user_id)
    if current_user_id != user_id:
        base_query = base_query.filter_by(is_public=True)

    if q:
        fq = re.sub(r'[^\w\s]', ' ', q).strip()
        if not fq:
            return jsonify([])

        sql = text("""
            SELECT notes.id, notes.title, notes.content, notes.is_public, notes.created_at, notes.updated_at
            FROM notes JOIN notes_fts ON notes.id = notes_fts.rowid
            WHERE notes_fts MATCH :match AND notes.author_id = :uid
            """ + ("" if current_user_id==user_id else " AND notes.is_public=1 ") )
        rows = db.session.execute(sql, {"match": fq, "uid": user_id})

        scored_notes = []
        for row in rows:
            d = dict(row)
            title_score = longest_common_subsequence(d["title"], fq)
            content_score = longest_common_subsequence(d["content"], fq)
            total_score = title_score * 2 + content_score
            if total_score == 0:
                continue
            scored_notes.append( (total_score, d) )

        scored_notes.sort(key=lambda x: x[0], reverse=True)

        notes = []
        for score, d in scored_notes:
            notes.append({
                "id": d["id"],
                "title": d["title"],
                "content": d["content"],
                "is_public": bool(d["is_public"]),
                "created_at": d["created_at"].isoformat(),
                "updated_at": d["updated_at"].isoformat(),
                "score": score
            })
        return jsonify(notes)
    else:
        notes = base_query.order_by(Note.updated_at.desc()).all()
        result = []
        for n in notes:
            result.append({
                "id": n.id,
                "title": n.title,
                "content": n.content,
                "is_public": n.is_public,
                "created_at": n.created_at.isoformat(),
                "updated_at": n.updated_at.isoformat(),
            })
        return jsonify(result)

@app.route("/notes/<int:note_id>")
@jwt_optional
def note_detail(note_id):
    n = Note.query.get_or_404(note_id)
    current_user_id = get_jwt_identity()
    if (not n.is_public) and (n.author_id != current_user_id):
        return jsonify({"msg":"无权限访问"}),403
    return jsonify({
        "id": n.id,
        "title": n.title,
        "content": n.content,
        "is_public": n.is_public,
        "created_at": n.created_at.isoformat(),
        "updated_at": n.updated_at.isoformat(),
        "author_id": n.author_id,
        "author_username": n.author.username
    })

@app.route("/notes", methods=["POST"])
@jwt_required()
def create_note():
    user_id = get_jwt_identity()
    data = request.json
    if not data or not data.get("title") or not data.get("content"):
        return jsonify({"msg":"标题和内容不能为空"}), 400
    note = Note(
        author_id=user_id,
        title=data.get("title"),
        content=data.get("content"),
        is_public=bool(data.get("is_public", False))
    )
    db.session.add(note)
    db.session.commit()
    return jsonify({"id": note.id}), 201

@app.route("/notes/<int:note_id>", methods=["PUT"])
@jwt_required()
def update_note(note_id):
    user_id = get_jwt_identity()
    note = Note.query.get_or_404(note_id)
    if note.author_id != user_id:
        return jsonify({"msg":"无权限操作"}), 403
    data = request.json
    if not data:
        return jsonify({"msg":"缺少更新内容"}), 400
    note.title = data.get("title", note.title)
    note.content = data.get("content", note.content)
    note.is_public = bool(data.get("is_public", note.is_public))
    db.session.commit()
    return jsonify({"msg":"更新成功"})

@app.route("/notes/<int:note_id>", methods=["DELETE"])
@jwt_required()
def delete_note(note_id):
    user_id = get_jwt_identity()
    note = Note.query.get_or_404(note_id)
    if note.author_id != user_id:
        return jsonify({"msg":"无权限操作"}),403
    db.session.delete(note)
    db.session.commit()
    return jsonify({"msg":"删除成功"})

@app.route("/me")
@jwt_required()
def me():
    user_id = get_jwt_identity()
    u = User.query.get(user_id)
    if not u:
        return jsonify({"msg":"不存在的用户"}),404
    return jsonify({
        "id": u.id,
        "username": u.username,
        "email": u.email,
        "created_at": u.created_at.isoformat()
    })

@app.route("/")
def index():
    return full_html

full_html = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8" />
    <title>笔记应用（单文件）</title>
    <script src="https://unpkg.com/vue@3/dist/vue.global.prod.js"></script>
    <script src="https://unpkg.com/axios/dist/axios.min.js"></script>
    <style>
    body { font-family: "Segoe UI", Tahoma, Geneva, Verdana, sans-serif; padding: 20px; background:#fafafa; }
    a { color: #42b983; cursor:pointer; text-decoration: underline; }
    .nav { padding: 10px 0; border-bottom:1px solid #ddd; margin-bottom: 20px; }
    .nav a { margin-right: 10px; }
    .error { color: #c00; }
    input,textarea { width: 100%; padding: 6px; margin: 4px 0 12px 0; box-sizing: border-box; border:1px solid #ccc; border-radius: 4px; }
    button { background: #42b983; border:none; color:#fff; padding: 8px 12px; cursor: pointer; border-radius: 4px;}
    button:disabled { background: #9bd4b8; cursor: not-allowed;}
    .note { border:1px solid #ddd; padding: 12px; margin-bottom: 10px; border-radius: 6px; background:#fff;}
    .note h3 { margin: 0 0 6px 0; }
    .note .meta { color: #666; font-size: 12px; margin-bottom: 6px; }
    label { font-weight: bold; }
    </style>
</head>
<body>
<div id="app">
    <div class="nav" v-if="loggedIn">
        <a @click="view = 'searchUsers'">搜索用户</a>
        <a @click="view = 'myNotes'">我的笔记</a>
        <a @click="logout">退出 ({{ username }})</a>
    </div>
    <div v-else class="nav">
        <a @click="view='login'">登录</a>
        <a @click="view='register'">注册</a>
    </div>

    <template v-if="view==='login'">
        <h2>登录</h2>
        <div v-if="error" class="error">{{ error }}</div>
        <input placeholder="用户名或邮箱" v-model="loginForm.username" />
        <input placeholder="密码" type="password" v-model="loginForm.password" />
        <button @click="doLogin" :disabled="processing">登录</button>
        <p>没有账号？<a @click="view='register'">注册</a></p>
    </template>

    <template v-if="view==='register'">
        <h2>注册</h2>
        <div v-if="error" class="error">{{ error }}</div>
        <input placeholder="用户名" v-model="registerForm.username" />
        <input placeholder="邮箱" v-model="registerForm.email" />
        <input placeholder="密码" type="password" v-model="registerForm.password" />
        <button @click="doRegister" :disabled="processing">注册</button>
        <p>已有账号？<a @click="view='login'">登录</a></p>
    </template>

    <template v-if="view==='searchUsers'">
        <h2>搜索用户</h2>
        <input placeholder="输入用户名关键字搜索" v-model="userSearchQuery" @input="searchUsers" />
        <ul>
            <li v-for="u in searchResults" :key="u.id">
                <a @click="loadUserNotes(u)">{{ u.username }} <small v-if="u.score"> (相似度: {{ u.score }})</small></a>
            </li>
        </ul>
        <div v-if="selectedUser">
            <h3>
                用户: {{ selectedUser.username }}
                <button @click="selectedUser=null; notes=[]; noteSearchQuery=''">关闭</button>
            </h3>
            <input placeholder="搜索该用户笔记..." v-model="noteSearchQuery" @input="searchUserNotes" />
            <div v-if="notes.length===0">无笔记</div>
            <div v-for="note in notes" :key="note.id" class="note">
                <h3><a @click="viewNote(note)">{{ note.title }} <small v-if="note.score">(得分: {{ note.score }})</small></a></h3>
                <div class="meta">更新时间: {{ formatDate(note.updated_at) }} | 公共: {{ note.is_public ? '是' : '否' }}</div>
                <p>{{ note.content.slice(0,150) }}{{ note.content.length>150 ? '...' : '' }}</p>
            </div>
        </div>
    </template>

    <template v-if="view==='myNotes'">
        <h2>我的笔记</h2>
        <input placeholder="搜索笔记标题或内容" v-model="noteSearchQuery" @input="searchMyNotes" />
        <button @click="newNote">+ 新建笔记</button>
        <div v-if="notes.length===0">无笔记</div>
        <div v-for="note in notes" :key="note.id" class="note">
            <h3><a @click="viewNote(note)">{{ note.title }}</a></h3>
            <div class="meta">更新时间: {{ formatDate(note.updated_at) }} | 公共: {{ note.is_public ? '是' : '否' }}</div>
            <button @click="editNote(note)">编辑</button>
            <button @click="deleteNote(note)">删除</button>
        </div>
    </template>

    <template v-if="view==='viewNote'">
        <h2>{{ editMode ? '编辑笔记' : '查看笔记' }}</h2>
        <label>标题</label>
        <input v-model="curNote.title" :readonly="!editMode" />
        <label>内容</label>
        <textarea v-model="curNote.content" rows="10" :readonly="!editMode"></textarea>
        <label><input type="checkbox" v-model="curNote.is_public" :disabled="!editMode"/> 公开笔记</label>
        <br/>
        <button v-if="editMode" @click="saveNote">保存</button>
        <button @click="cancelViewNote">关闭</button>
    </template>
</div>

<script>
const { createApp } = Vue;

createApp({
    data() {
        return {
            view: "login",
            username: "",
            token: "",
            loggedIn: false,
            error: null,
            processing: false,
            loginForm: {
                username: "",
                password: ""
            },
            registerForm: {
                username: "",
                email: "",
                password: ""
            },
            userSearchQuery: "",
            searchResults: [],
            selectedUser: null,
            notes: [],
            noteSearchQuery: "",
            curNote: null,
            editMode: false
        }
    },
    mounted() {
        const cachedToken = localStorage.getItem("token");
        if (cachedToken) {
            this.token = cachedToken;
            this.fetchMe();
        }
    },
    methods: {
        authHeaders() {
            return { Authorization: "Bearer "+this.token };
        },
        async fetchMe(){
            try {
                let res = await axios.get("/me", {headers:this.authHeaders()});
                this.username = res.data.username;
                this.loggedIn = true;
                this.view = "myNotes";
                this.error = null;
                this.searchMyNotes();
            } catch(e) {
                this.logout();
            }
        },
        async doLogin(){
            this.error = null;
            this.processing = true;
            try {
                let res = await axios.post("/auth/login", this.loginForm);
                this.token = res.data.access_token;
                this.username = res.data.username;
                localStorage.setItem("token", this.token);
                this.loggedIn = true;
                this.view = "myNotes";
                this.loginForm.password = "";
                this.searchMyNotes();
            } catch(e) {
                this.error = e.response?.data?.msg || "登录失败";
            }
            this.processing = false;
        },
        async doRegister(){
            this.error = null;
            this.processing = true;
            try {
                await axios.post("/auth/register", this.registerForm);
                alert("注册成功，请登录");
                this.view = "login";
                this.registerForm.password = "";
            } catch(e) {
                this.error = e.response?.data?.msg || "注册失败";
            }
            this.processing = false;
        },
        logout(){
            this.token = "";
            this.username = "";
            this.loggedIn = false;
            localStorage.removeItem("token");
            this.view = "login";
            this.userSearchQuery = "";
            this.searchResults = [];
            this.selectedUser = null;
            this.notes = [];
            this.noteSearchQuery = "";
        },
        async searchUsers(){
            if(!this.userSearchQuery.trim()){
                this.searchResults = [];
                this.selectedUser = null;
                this.notes = [];
                return;
            }
            try {
                let res = await axios.get("/users/search", {
                    params: { q: this.userSearchQuery.trim() },
                    headers: this.authHeaders()
                });
                this.searchResults = res.data;
            } catch(e) {
                this.error = "搜索用户失败";
            }
        },
        async loadUserNotes(user){
            if (!user) return;
            this.selectedUser = user;
            this.notes = [];
            this.noteSearchQuery = "";
            await this.searchUserNotes();
        },
        async searchUserNotes(){
            if(!this.selectedUser) return;
            try {
                let res = await axios.get(`/users/${this.selectedUser.id}/notes`, {
                    params: { q: this.noteSearchQuery.trim() },
                    headers: this.authHeaders()
                });
                this.notes = res.data;
            } catch(e){
                alert("搜索用户笔记失败");
            }
        },
        async searchMyNotes(){
            if (!this.loggedIn) return;
            try {
                let res = await axios.get(`/users/${await this.getMyUserId()}/notes`, {
                    params: { q: this.noteSearchQuery.trim() },
                    headers: this.authHeaders()
                });
                this.notes = res.data;
            } catch(e){
                alert("搜索我的笔记失败");
            }
        },
        async getMyUserId(){
            if(this._myUserId) return this._myUserId;
            let res = await axios.get("/me", {headers:this.authHeaders()});
            this._myUserId = res.data.id;
            return this._myUserId;
        },
        async newNote(){
            this.editMode = true;
            this.curNote = {title:"", content:"", is_public:false};
            this.view = "viewNote";
        },
        async viewNote(note){
            try {
                let res = await axios.get(`/notes/${note.id}`, {headers:this.authHeaders()});
                this.curNote = res.data;
                this.editMode = (this.curNote.author_id === await this.getMyUserId());
                this.view = "viewNote";
            } catch(e){
                alert("读取笔记失败");
            }
        },
        cancelViewNote(){
            this.curNote = null;
            this.editMode = false;
            this.view = this.loggedIn ? "myNotes" : "searchUsers";
            this.noteSearchQuery = "";
            if(this.view==="myNotes") this.searchMyNotes();
            else if(this.selectedUser) this.searchUserNotes();
        },
        async saveNote(){
            if(!this.curNote.title.trim()) {
                alert("标题不能为空");
                return;
            }
            try {
                if(this.curNote.id){
                    await axios.put(`/notes/${this.curNote.id}`, {
                        title: this.curNote.title,
                        content: this.curNote.content,
                        is_public: this.curNote.is_public
                    }, {headers:this.authHeaders()});
                    alert("更新成功");
                } else {
                    let res = await axios.post("/notes", {
                        title: this.curNote.title,
                        content: this.curNote.content,
                        is_public: this.curNote.is_public
                    }, {headers:this.authHeaders()});
                    this.curNote.id = res.data.id;
                    alert("创建成功");
                }
                this.editMode = false;
                this.searchMyNotes();
            } catch(e){
                alert("保存失败:"+e.response?.data?.msg||e.message);
            }
        },
        async editNote(note){
            await this.viewNote(note);
            this.editMode = true;
        },
        async deleteNote(note){
            if(!confirm("确认删除吗？此操作不可恢复")) return;
            try {
                await axios.delete(`/notes/${note.id}`, {headers:this.authHeaders()});
                alert("删除成功");
                this.searchMyNotes();
            } catch(e){
                alert("删除失败");
            }
        },
        formatDate(dtStr){
            try {
                let dt = new Date(dtStr);
                return dt.toLocaleString();
            } catch {
                return dtStr;
            }
        }
    }
}).mount("#app");
</script>
</body>
</html>
"""

if __name__ == '__main__':
    db.create_all()
    setup_fts5()
    print("启动服务器：http://127.0.0.1:5000")
    app.run()
