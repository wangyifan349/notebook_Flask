# app.py
import os
import time
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path
from math import ceil

from flask import Flask, request, jsonify, make_response
from flask_sqlalchemy import SQLAlchemy

import jwt
from passlib.hash import bcrypt

from whoosh import index
from whoosh.fields import Schema, TEXT, ID, DATETIME
from whoosh.qparser import MultifieldParser, OrGroup
import jieba

# ========== 配置 ==========
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
JWT_ALGO = "HS256"
JWT_EXP_HOURS = 24

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = str(BASE_DIR / "notes.db")
WHOOSH_DIR = str(BASE_DIR / "whoosh_index")

# ========== Flask + DB ==========
app = Flask(__name__, static_folder=None)
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{DB_PATH}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

# ========== 模型 ==========
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def verify_password(self, pw):
        return bcrypt.verify(pw, self.password_hash)

class Note(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), default="")
    content = db.Column(db.Text, nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self, include_author=False):
        d = {
            "id": self.id,
            "title": self.title,
            "content": self.content,
            "author_id": self.author_id,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }
        if include_author:
            user = User.query.get(self.author_id)
            d["author_username"] = user.username if user else None
        return d

# ========== Whoosh ==========
schema = Schema(
    note_id=ID(stored=True, unique=True),
    title=TEXT(stored=True),
    content=TEXT(stored=True),
    author_id=ID(stored=True),
    created_at=DATETIME(stored=True)
)

def init_whoosh():
    os.makedirs(WHOOSH_DIR, exist_ok=True)
    if not index.exists_in(WHOOSH_DIR):
        index.create_in(WHOOSH_DIR, schema)

def get_whoosh_index():
    return index.open_dir(WHOOSH_DIR)

def jieba_tokenize(text):
    return " ".join(jieba.cut_for_search(text or ""))

def add_or_update_index(note: Note):
    ix = get_whoosh_index()
    writer = ix.writer()
    writer.update_document(
        note_id=str(note.id),
        title=jieba_tokenize(note.title),
        content=jieba_tokenize(note.content),
        author_id=str(note.author_id),
        created_at=note.created_at
    )
    writer.commit()

def delete_from_index(note_id: int):
    ix = get_whoosh_index()
    writer = ix.writer()
    writer.delete_by_term("note_id", str(note_id))
    writer.commit()

# ========== JWT ==========
def create_token(user_id):
    payload = {
        "sub": str(user_id),
        "iat": int(time.time()),
        "exp": int((datetime.utcnow() + timedelta(hours=JWT_EXP_HOURS)).timestamp())
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=JWT_ALGO)

def decode_token(token):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALGO])
        return int(payload.get("sub"))
    except Exception:
        return None

def auth_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return jsonify({"error": "authorization required"}), 401
        token = auth.split(" ", 1)[1].strip()
        user_id = decode_token(token)
        if not user_id:
            return jsonify({"error": "invalid or expired token"}), 401
        request.user_id = user_id
        return f(*args, **kwargs)
    return wrapper

# ========== 初始化 ==========
@app.before_first_request
def setup():
    db.create_all()
    init_whoosh()

# ========== 辅助分页 ==========
def paginate_query_queryset(items, page, per_page):
    total = len(items)
    pages = max(1, ceil(total / per_page))
    start = (page - 1) * per_page
    end = start + per_page
    return items[start:end], total, pages

# ========== 用户 API ==========
@app.route("/api/register", methods=["POST"])
def register():
    data = request.get_json() or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    if not username or not password:
        return jsonify({"error": "username and password required"}), 400
    if User.query.filter_by(username=username).first():
        return jsonify({"error": "username taken"}), 400
    pw_hash = bcrypt.hash(password)
    user = User(username=username, password_hash=pw_hash)
    db.session.add(user)
    db.session.commit()
    token = create_token(user.id)
    return jsonify({"id": user.id, "username": user.username, "token": token}), 201

@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json() or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    if not username or not password:
        return jsonify({"error": "username and password required"}), 400
    user = User.query.filter_by(username=username).first()
    if not user or not user.verify_password(password):
        return jsonify({"error": "invalid credentials"}), 401
    token = create_token(user.id)
    return jsonify({"id": user.id, "username": user.username, "token": token})

# ========== 笔记 API ==========
@app.route("/api/notes", methods=["POST"])
@auth_required
def create_note():
    data = request.get_json() or {}
    content = (data.get("content") or "").strip()
    if not content:
        return jsonify({"error": "content required"}), 400
    title = (data.get("title") or "").strip()
    note = Note(title=title, content=content, author_id=request.user_id)
    db.session.add(note)
    db.session.commit()
    add_or_update_index(note)
    return jsonify(note.to_dict(include_author=True)), 201

@app.route("/api/notes/<int:note_id>", methods=["GET"])
def get_note(note_id):
    note = Note.query.get(note_id)
    if not note:
        return jsonify({"error": "not found"}), 404
    return jsonify(note.to_dict(include_author=True))

@app.route("/api/notes/<int:note_id>", methods=["PUT"])
@auth_required
def update_note(note_id):
    note = Note.query.get(note_id)
    if not note:
        return jsonify({"error": "not found"}), 404
    if note.author_id != request.user_id:
        return jsonify({"error": "forbidden"}), 403
    data = request.get_json() or {}
    title = data.get("title")
    content = data.get("content")
    if title is not None:
        note.title = title.strip()
    if content is not None:
        if not content.strip():
            return jsonify({"error": "content cannot be empty"}), 400
        note.content = content.strip()
    db.session.commit()
    add_or_update_index(note)
    return jsonify(note.to_dict(include_author=True))

@app.route("/api/notes/<int:note_id>", methods=["DELETE"])
@auth_required
def delete_note(note_id):
    note = Note.query.get(note_id)
    if not note:
        return jsonify({"error": "not found"}), 404
    if note.author_id != request.user_id:
        return jsonify({"error": "forbidden"}), 403
    db.session.delete(note)
    db.session.commit()
    delete_from_index(note_id)
    return jsonify({"ok": True})

@app.route("/api/my/notes", methods=["GET"])
@auth_required
def my_notes():
    page = max(1, int(request.args.get("page", 1)))
    per_page = min(100, max(1, int(request.args.get("per_page", 10))))
    q = Note.query.filter_by(author_id=request.user_id).order_by(Note.created_at.desc()).all()
    items, total, pages = paginate_query_queryset(q, page, per_page)
    return jsonify({
        "notes": [n.to_dict() for n in items],
        "page": page,
        "per_page": per_page,
        "total": total,
        "pages": pages
    })

# ========== 搜索 API（Whoosh）=========
@app.route("/api/search", methods=["GET"])
def search():
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify({"error": "query parameter q required"}), 400
    page = max(1, int(request.args.get("page", 1)))
    per_page = min(100, max(1, int(request.args.get("per_page", 10))))

    ix = get_whoosh_index()
    q_tok = jieba_tokenize(q)
    parser = MultifieldParser(["title", "content"], schema=ix.schema, group=OrGroup)
    parsed = parser.parse(q_tok)

    with ix.searcher() as searcher:
        results = searcher.search(parsed, limit=page * per_page, sortedby="created_at", reverse=True)
        start = (page - 1) * per_page
        hits = results[start:start + per_page]
        notes = []
        for hit in hits:
            note = Note.query.get(int(hit["note_id"]))
            if note:
                notes.append(note.to_dict(include_author=True))
    return jsonify({
        "q": q,
        "page": page,
        "per_page": per_page,
        "results": notes
    })

# ========== 前端页面 ==========
INDEX_HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <title>简易笔记平台（改进版）</title>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <style>
    body { font-family: system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial; max-width:960px; margin:18px auto; padding:0 14px; color:#222; }
    header { display:flex; justify-content:space-between; align-items:center; gap:12px; }
    .small { font-size:13px; color:#666; }
    .hidden { display:none; }
    .note { border:1px solid #e5e7eb; padding:12px; margin:10px 0; border-radius:8px; background:#fff; }
    .note h3 { margin:0 0 6px; }
    textarea { width:100%; height:140px; font-family:inherit; padding:8px; }
    input[type=text], input[type=password] { width:100%; padding:8px; box-sizing:border-box; }
    button { padding:6px 10px; margin:4px 6px 4px 0; cursor:pointer; }
    nav { display:flex; gap:8px; align-items:center; margin:12px 0; flex-wrap:wrap; }
    .controls { display:flex; gap:8px; align-items:center; }
    #message { padding:8px; margin:10px 0; border-radius:6px; display:none; }
    .msg-ok { background:#ecfdf5; border:1px solid #a7f3d0; color:#065f46; }
    .msg-err { background:#fff1f2; border:1px solid #fecaca; color:#7f1d1d; }
    .meta { font-size:12px; color:#666; margin-bottom:8px; }
    .flex { display:flex; gap:8px; align-items:center; }
    @media (max-width:600px) { header { flex-direction:column; align-items:flex-start; } }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>简易笔记平台（改进）</h1>
      <div class="small">支持中文搜索（jieba + Whoosh）、注册/登录、AJAX 分页加载</div>
    </div>
    <div id="auth-area" class="small">
      <span id="user-info"></span>
      <div style="margin-top:8px;">
        <button id="show-login">登录</button>
        <button id="show-register">注册</button>
        <button id="logout" class="hidden">登出</button>
      </div>
    </div>
  </header>

  <div id="message"></div>

  <section id="auth-forms">
    <div id="login-form" class="hidden">
      <h3>登录</h3>
      <input id="login-username" placeholder="用户名"/>
      <input id="login-password" type="password" placeholder="密码"/>
      <div><button id="btn-login">登录</button></div>
    </div>

    <div id="register-form" class="hidden">
      <h3>注册</h3>
      <input id="reg-username" placeholder="用户名"/>
      <input id="reg-password" type="password" placeholder="密码"/>
      <div><button id="btn-register">注册</button></div>
    </div>
  </section>

  <nav>
    <div class="controls">
      <button id="btn-new-note" class="hidden">新建笔记</button>
      <button id="btn-my-notes" class="hidden">我的笔记</button>
      <button id="btn-refresh">刷新</button>
    </div>
    <div style="flex:1"></div>
    <div class="controls">
      <input id="search-q" placeholder="搜索笔记（支持中文）" />
      <button id="btn-search">搜索</button>
    </div>
  </nav>

  <section id="editor" class="hidden">
    <h3 id="editor-title">新建笔记</h3>
    <input id="note-title" placeholder="标题（可选）" />
    <textarea id="note-content" placeholder="正文...（纯文本）"></textarea>
    <div>
      <button id="save-note">保存</button>
      <button id="cancel-edit">取消</button>
    </div>
  </section>

  <section id="list"></section>

<script>
const api = {
  register: '/api/register',
  login: '/api/login',
  create: '/api/notes',
  myNotes: '/api/my/notes',
  search: '/api/search'
};

let token = localStorage.getItem('token') || null;
let currentUser = JSON.parse(localStorage.getItem('currentUser') || 'null');
let editingNoteId = null;

// UI helpers
function showMessage(text, ok=true, timeout=3000) {
  const el = document.getElementById('message');
  el.textContent = text;
  el.className = ok ? 'msg-ok' : 'msg-err';
  el.style.display = 'block';
  setTimeout(() => el.style.display = 'none', timeout);
}
function setAuthUI() {
  document.getElementById('user-info').textContent = currentUser ? '已登录: ' + currentUser.username : '未登录';
  document.getElementById('logout').classList.toggle('hidden', !currentUser);
  document.getElementById('show-login').classList.toggle('hidden', !!currentUser);
  document.getElementById('show-register').classList.toggle('hidden', !!currentUser);
  document.getElementById('btn-new-note').classList.toggle('hidden', !currentUser);
  document.getElementById('btn-my-notes').classList.toggle('hidden', !currentUser);
}
function authHeader() {
  return token ? { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' } : { 'Content-Type': 'application/json' };
}

// Event bindings
document.getElementById('show-login').onclick = () => {
  document.getElementById('login-form').classList.toggle('hidden');
  document.getElementById('register-form').classList.add('hidden');
};
document.getElementById('show-register').onclick = () => {
  document.getElementById('register-form').classList.toggle('hidden');
  document.getElementById('login-form').classList.add('hidden');
};

document.getElementById('btn-register').onclick = async () => {
  const username = document.getElementById('reg-username').value.trim();
  const password = document.getElementById('reg-password').value;
  if (!username || !password) return showMessage('需要用户名和密码', false);
  const res = await fetch(api.register, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({username,password}) });
  const j = await res.json();
  if (!res.ok) return showMessage(j.error || '注册失败', false);
  token = j.token; localStorage.setItem('token', token);
  currentUser = { id:j.id, username:j.username }; localStorage.setItem('currentUser', JSON.stringify(currentUser));
  setAuthUI(); document.getElementById('register-form').classList.add('hidden'); showMessage('注册并登录成功');
  loadMyNotes(true);
};

document.getElementById('btn-login').onclick = async () => {
  const username = document.getElementById('login-username').value.trim();
  const password = document.getElementById('login-password').value;
  if (!username || !password) return showMessage('需要用户名和密码', false);
  const res = await fetch(api.login, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({username,password}) });
  const j = await res.json();
  if (!res.ok) return showMessage(j.error || '登录失败', false);
  token = j.token; localStorage.setItem('token', token);
  currentUser = { id:j.id, username:j.username }; localStorage.setItem('currentUser', JSON.stringify(currentUser));
  setAuthUI(); document.getElementById('login-form').classList.add('hidden'); showMessage('登录成功');
  loadMyNotes(true);
};

document.getElementById('logout').onclick = () => {
  token = null; localStorage.removeItem('token'); currentUser = null; localStorage.removeItem('currentUser'); setAuthUI(); document.getElementById('list').innerHTML=''; showMessage('已登出');
};

document.getElementById('btn-new-note').onclick = () => {
  editingNoteId = null;
  document.getElementById('editor-title').textContent = '新建笔记';
  document.getElementById('note-title').value = '';
  document.getElementById('note-content').value = '';
  document.getElementById('editor').classList.remove('hidden');
};
document.getElementById('cancel-edit').onclick = () => { document.getElementById('editor').classList.add('hidden'); };

document.getElementById('save-note').onclick = async () => {
  const title = document.getElementById('note-title').value.trim();
  const content = document.getElementById('note-content').value.trim();
  if (!content) return showMessage('内容不能为空', false);
  const payload = { title, content };
  let res, j;
  if (editingNoteId) {
    res = await fetch('/api/notes/' + editingNoteId, { method:'PUT', headers: authHeader(), body: JSON.stringify(payload) });
    j = await res.json();
    if (!res.ok) return showMessage(j.error || '更新失败', false);
    showMessage('更新成功');
  } else {
    res = await fetch(api.create, { method:'POST', headers: authHeader(), body: JSON.stringify(payload) });
    j = await res.json();
    if (!res.ok) return showMessage(j.error || '创建失败', false);
    showMessage('创建成功');
  }
  document.getElementById('editor').classList.add('hidden');
  loadMyNotes(true);
};

document.getElementById('btn-my-notes').onclick = () => loadMyNotes(true);
document.getElementById('btn-refresh').onclick = () => { const q = document.getElementById('search-q').value.trim(); if (q) doSearch(q,1,true); else loadMyNotes(true); };
document.getElementById('btn-search').onclick = () => {
  const q = document.getElementById('search-q').value.trim();
  if (!q) return showMessage('请输入搜索词', false);
  doSearch(q, 1, true);
};

// 分页状态
let myNotesPage = 1;
let myNotesPer = 5;
let searchPage = 1;
let searchPer = 5;
let lastSearchQ = '';

async function loadMyNotes(reset=false) {
  if (!currentUser || !token) return showMessage('请先登录', false);
  if (reset) myNotesPage = 1;
  const res = await fetch(api.myNotes + '?page=' + myNotesPage + '&per_page=' + myNotesPer, { headers: authHeader() });
  const j = await res.json();
  if (!res.ok) return showMessage(j.error || '获取失败', false);
  renderList(j.notes, '我的笔记', {
    showLoadMore: myNotesPage < j.pages,
    loadMore: () => { myNotesPage++; loadMyNotes(); }
  });
}

async function doSearch(q, page=1, reset=false) {
  if (reset) { searchPage = 1; lastSearchQ = q; } else searchPage = page;
  const res = await fetch(api.search + '?q=' + encodeURIComponent(q) + '&page=' + searchPage + '&per_page=' + searchPer);
  const j = await res.json();
  if (!res.ok) return showMessage(j.error || '搜索失败', false);
  renderList(j.results, '搜索结果: ' + q, {
    showLoadMore: j.results.length >= searchPer,
    loadMore: () => { searchPage++; doSearch(q, searchPage); }
  });
}

function renderList(notes, title, opts={}) {
  const container = document.getElementById('list');
  container.innerHTML = '';
  const header = document.createElement('div'); header.className='flex'; header.style.justifyContent='space-between';
  const h = document.createElement('h2'); h.textContent = title + '（' + notes.length + '）'; header.appendChild(h);
  container.appendChild(header);
  if (!notes.length) { const p = document.createElement('p'); p.textContent='无内容'; container.appendChild(p); return; }
  for (const n of notes) {
    const div = document.createElement('div'); div.className = 'note';
    const titleEl = document.createElement('h3'); titleEl.textContent = n.title || '(无标题)'; div.appendChild(titleEl);
    const meta = document.createElement('div'); meta.className='meta';
    meta.textContent = 'ID:' + n.id + ' • 作者:' + (n.author_username || n.author_id) + ' • ' + (new Date(n.created_at).toLocaleString());
    div.appendChild(meta);
    const p = document.createElement('pre'); p.textContent = n.content; p.style.whiteSpace='pre-wrap'; div.appendChild(p);
    // 操作
    const ops = document.createElement('div');
    if (currentUser && currentUser.id === n.author_id) {
      const btnEdit = document.createElement('button'); btnEdit.textContent='编辑';
      btnEdit.onclick = () => { editingNoteId = n.id; document.getElementById('editor-title').textContent='编辑笔记'; document.getElementById('note-title').value = n.title; document.getElementById('note-content').value = n.content; document.getElementById('editor').classList.remove('hidden'); };
      const btnDel = document.createElement('button'); btnDel.textContent='删除';
      btnDel.onclick = async () => {
        if (!confirm('确认删除？')) return;
        const res = await fetch('/api/notes/' + n.id, { method:'DELETE', headers: authHeader() });
        const j = await res.json();
        if (!res.ok) return showMessage(j.error || '删除失败', false);
        showMessage('删除成功'); loadMyNotes(true);
      };
      ops.appendChild(btnEdit); ops.appendChild(btnDel);
    } else {
      const viewAuthor = document.createElement('span'); viewAuthor.textContent = ' ';
      ops.appendChild(viewAuthor);
    }
    div.appendChild(ops);
    container.appendChild(div);
  }
  if (opts.showLoadMore) {
    const more = document.createElement('button'); more.textContent = '加载更多'; more.onclick = opts.loadMore;
    container.appendChild(more);
  }
}

// try restore auth
if (token && currentUser) setAuthUI();
</script>
</body>
</html>
"""

@app.route("/", methods=["GET"])
def index():
    resp = make_response(INDEX_HTML)
    resp.headers['Content-Type'] = 'text/html; charset=utf-8'
    return resp

# ========== 运行 ==========
if __name__ == "__main__":
    app.run(debug=True)
