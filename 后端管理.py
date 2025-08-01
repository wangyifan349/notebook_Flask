import os
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_jwt_extended import (
    JWTManager, create_access_token,
    jwt_required, get_jwt_identity
)
import bcrypt
from dotenv import load_dotenv

# 加载 .env（可选）
load_dotenv()

# --- 1. 配置 ---
app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
    "DATABASE_URL",
    "sqlite:///notesapp.db"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["JWT_SECRET_KEY"] = os.getenv("JWT_SECRET_KEY", "jwt-please-change")
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(days=7)

# --- 2. 初始化 ---
db = SQLAlchemy(app)
jwt = JWTManager(app)

# --- 3. 定义模型 ---
class User(db.Model):
    __tablename__ = "users"
    id           = db.Column(db.Integer, primary_key=True)
    username     = db.Column(db.String(50), unique=True, nullable=False)
    email        = db.Column(db.String(120), unique=True, nullable=False)
    password_hash= db.Column(db.LargeBinary(60), nullable=False)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, pw):
        self.password_hash = bcrypt.hashpw(pw.encode(), bcrypt.gensalt())

    def check_password(self, pw):
        return bcrypt.checkpw(pw.encode(), self.password_hash)

class Note(db.Model):
    __tablename__ = "notes"
    id         = db.Column(db.Integer, primary_key=True)
    author_id  = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    title      = db.Column(db.String(255), nullable=False)
    content    = db.Column(db.Text, nullable=False)
    is_public  = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime,
                           default=datetime.utcnow,
                           onupdate=datetime.utcnow)

    author = db.relationship("User", backref=db.backref("notes", lazy=True))

# FTS5 虚拟表，用于全文搜索 title 和 content
# 建表时会手工执行 CREATE VIRTUAL TABLE ... AFTER db.create_all()
FTS_TABLE = "notes_fts"

# --- 4. 建表 & 初始化 FTS ---
@app.before_first_request
def init_db():
    db.create_all()
    # 如果 FTS 表不存在，则创建
    sql = f"SELECT name FROM sqlite_master WHERE type='table' AND name='{FTS_TABLE}'"
    res = db.session.execute(sql).fetchone()
    if not res:
        db.session.execute(f"""
            CREATE VIRTUAL TABLE {FTS_TABLE}
            USING fts5(title, content, note_id UNINDEXED);
        """)
        # 初次同步现有数据
        notes = Note.query.all()
        for n in notes:
            db.session.execute(f"""
                INSERT INTO {FTS_TABLE}(rowid, title, content, note_id)
                VALUES (:rid, :t, :c, :nid)
            """, {"rid": n.id, "t": n.title, "c": n.content, "nid": n.id})
        db.session.commit()

# 工具：同步单条 Note 到 FTS
def sync_fts(note: Note):
    # 删除旧记录
    db.session.execute(f"DELETE FROM {FTS_TABLE} WHERE note_id=:nid",
                       {"nid": note.id})
    # 插入新记录
    db.session.execute(f"""
        INSERT INTO {FTS_TABLE}(rowid, title, content, note_id)
        VALUES (:rid, :t, :c, :nid)
    """, {"rid": note.id, "t": note.title, "c": note.content, "nid": note.id})
    db.session.commit()

# --- 5. 路由：注册、登录 ---
@app.route("/auth/register", methods=["POST"])
def register():
    data = request.get_json()
    if User.query.filter_by(username=data["username"]).first():
        return jsonify({"msg": "用户名已存在"}), 400
    if User.query.filter_by(email=data["email"]).first():
        return jsonify({"msg": "邮箱已注册"}), 400

    u = User(username=data["username"], email=data["email"])
    u.set_password(data["password"])
    db.session.add(u)
    db.session.commit()
    return jsonify({"msg": "注册成功"}), 201

@app.route("/auth/login", methods=["POST"])
def login():
    data = request.get_json()
    u = User.query.filter(
        (User.username == data["username"]) | (User.email == data["username"])
    ).first()
    if not u or not u.check_password(data["password"]):
        return jsonify({"msg": "用户名或密码错误"}), 401

    token = create_access_token(identity=u.id)
    return jsonify({"access_token": token}), 200

# --- 6. 笔记 CRUD ---
@app.route("/notes", methods=["POST"])
@jwt_required()
def create_note():
    user_id = get_jwt_identity()
    d = request.get_json()
    n = Note(author_id=user_id,
             title=d["title"],
             content=d["content"],
             is_public=d.get("is_public", False))
    db.session.add(n)
    db.session.commit()
    sync_fts(n)
    return jsonify({"id": n.id}), 201

@app.route("/notes/<int:note_id>", methods=["GET"])
@jwt_required(optional=True)
def get_note(note_id):
    n = Note.query.get_or_404(note_id)
    cur = get_jwt_identity()
    if not n.is_public and n.author_id != cur:
        return jsonify({"msg": "无权限访问"}), 403
    return jsonify({
        "id": n.id,
        "author_id": n.author_id,
        "title": n.title,
        "content": n.content,
        "is_public": n.is_public,
        "created_at": n.created_at,
        "updated_at": n.updated_at
    })

@app.route("/notes/<int:note_id>", methods=["PUT"])
@jwt_required()
def update_note(note_id):
    user_id = get_jwt_identity()
    n = Note.query.get_or_404(note_id)
    if n.author_id != user_id:
        return jsonify({"msg": "无权限操作"}), 403
    d = request.get_json()
    n.title     = d.get("title", n.title)
    n.content   = d.get("content", n.content)
    n.is_public = d.get("is_public", n.is_public)
    db.session.commit()
    sync_fts(n)
    return jsonify({"msg": "更新成功"}), 200

@app.route("/notes/<int:note_id>", methods=["DELETE"])
@jwt_required()
def delete_note(note_id):
    user_id = get_jwt_identity()
    n = Note.query.get_or_404(note_id)
    if n.author_id != user_id:
        return jsonify({"msg": "无权限操作"}), 403
    # 删除 FTS 记录
    db.session.execute(f"DELETE FROM {FTS_TABLE} WHERE note_id=:nid", {"nid": note_id})
    db.session.delete(n)
    db.session.commit()
    return jsonify({"msg": "删除成功"}), 200

# --- 7. 搜索：用户 & 笔记 ---
@app.route("/search/users", methods=["GET"])
@jwt_required()
def search_users():
    q = request.args.get("q", "")
    us = User.query.filter(User.username.ilike(f"%{q}%")).all()
    return jsonify([{"id": u.id, "username": u.username} for u in us]), 200

@app.route("/search/notes", methods=["GET"])
@jwt_required(optional=True)
def search_notes():
    q        = request.args.get("q", "")
    author   = request.args.get("author_id", type=int)
    public   = request.args.get("public_only", "true").lower() == "true"

    # 构造 FTS5 查询
    where = []
    params = {}
    if q:
        where.append(f"(notes_fts MATCH :q)")
        params["q"] = q.replace(" ", " OR ")
    if author is not None:
        where.append("notes.author_id = :aid")
        params["aid"] = author
    if public:
        where.append("notes.is_public = 1")
    sql = f"""
      SELECT notes.id, notes.author_id, notes.title, notes.content
      FROM notes_fts 
      JOIN notes ON notes_fts.note_id = notes.id
      {"WHERE " + " AND ".join(where) if where else ""}
      ORDER BY rank;
    """
    rows = db.session.execute(sql, params).fetchall()
    result = []
    for r in rows:
        result.append({
            "id": r.id,
            "author_id": r.author_id,
            "title": r.title,
            "snippet": (r.content[:200] + "...") if len(r.content)>200 else r.content
        })
    return jsonify(result), 200

# --- 8. 启动 ---
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
