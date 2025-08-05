import os
import re
import json
import bcrypt
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
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
    # Enforce foreign key constraints
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.LargeBinary(60), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, pw: str):
        # Enforce minimum password length (e.g. 8)
        if len(pw) < 8:
            raise ValueError("密码长度至少8位")
        self.password_hash = bcrypt.hashpw(pw.encode('utf-8'), bcrypt.gensalt())

    def check_password(self, pw: str) -> bool:
        return bcrypt.checkpw(pw.encode('utf-8'), self.password_hash)

class Note(db.Model):
    __tablename__ = "notes"
    id = db.Column(db.Integer, primary_key=True)
    author_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    title = db.Column(db.String(255), nullable=False)
    content = db.Column(db.Text, nullable=False)
    is_public = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    author = db.relationship("User", backref=db.backref("notes", lazy="dynamic"))

def setup_fts5():
    with app.app_context():
        conn = db.engine.raw_connection()
        c = conn.cursor()
        # Create FTS5 virtual table for notes title and content
        c.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
                title, content, content='notes', content_rowid='id'
            );
        """)
        # Insert trigger for after insert on notes
        c.execute("""
            CREATE TRIGGER IF NOT EXISTS notes_ai AFTER INSERT ON notes BEGIN
                INSERT INTO notes_fts(rowid, title, content) VALUES (new.id, new.title, new.content);
            END;
        """)
        # Delete trigger for after delete on notes
        c.execute("""
            CREATE TRIGGER IF NOT EXISTS notes_ad AFTER DELETE ON notes BEGIN
                INSERT INTO notes_fts(notes_fts, rowid, title, content) VALUES('delete', old.id, old.title, old.content);
            END;
        """)
        # Update trigger for after update on notes
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
    dp = [[0]*(n+1) for _ in range(m+1)]
    for i in range(m):
        for j in range(n):
            if a[i] == b[j]:
                dp[i+1][j+1] = dp[i][j] + 1
            else:
                dp[i+1][j+1] = max(dp[i][j+1], dp[i+1][j])
    return dp[m][n]

@app.route("/auth/register", methods=["POST"])
def register():
    data = request.get_json(force=True)
    if not data or not all(k in data for k in ("username", "email", "password")):
        return jsonify({"msg": "缺少注册信息"}), 400

    username = data["username"].strip()
    email = data["email"].strip()
    password = data["password"]

    if not username or not email or not password:
        return jsonify({"msg": "请填写完整信息"}), 400

    # Validate email format simple pattern
    if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
        return jsonify({"msg": "邮箱格式错误"}), 400

    if User.query.filter_by(username=username).first():
        return jsonify({"msg": "用户名已被注册"}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({"msg": "邮箱已被注册"}), 400
    try:
        u = User(username=username, email=email)
        u.set_password(password)
    except ValueError as e:
        return jsonify({"msg": str(e)}), 400

    db.session.add(u)
    db.session.commit()
    return jsonify({"msg": "注册成功"}), 201

@app.route("/auth/login", methods=["POST"])
def login():
    data = request.get_json(force=True)
    if not data or not data.get("username") or not data.get("password"):
        return jsonify({"msg": "请输入用户名和密码"}), 400
    username = data['username'].strip()
    password = data['password']
    user = User.query.filter((User.username == username) | (User.email == username)).first()
    if not user or not user.check_password(password):
        return jsonify({"msg": "用户名或密码错误"}), 401
    access_token = create_access_token(identity=user.id)
    return jsonify({"access_token": access_token, "username": user.username})

@app.route("/users/search")
@jwt_required()
def user_search():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify([])
    # Use ilike only for filtering rather than full-text search, still efficient for small userbase
    users = User.query.filter(User.username.ilike(f"%{q}%")).limit(50).all()
    scored = []
    for u in users:
        score = longest_common_subsequence(u.username, q)
        scored.append((score, u))
    scored.sort(key=lambda x: x[0], reverse=True)
    result = [{"id": u.id, "username": u.username, "score": score} for score, u in scored[:20]]
    return jsonify(result)

@app.route("/users/<int:user_id>/notes")
@jwt_optional
def user_notes(user_id):
    q = request.args.get("q", "").strip()
    current_user_id = get_jwt_identity()
    # Use get_or_404 with optimized query to ensure user exists
    target_user = User.query.with_entities(User.id).filter_by(id=user_id).first_or_404()

    base_query = Note.query.filter_by(author_id=user_id)
    if current_user_id != user_id:
        base_query = base_query.filter_by(is_public=True)

    if q:
        # Sanitize search query for FTS5: remove special characters and fallback to phrase search
        fq = re.sub(r"[^\w\s]", " ", q).strip()
        if not fq:
            return jsonify([])

        sql = text("""
            SELECT notes.id, notes.title, notes.content, notes.is_public, notes.created_at, notes.updated_at
            FROM notes JOIN notes_fts ON notes.id = notes_fts.rowid
            WHERE notes_fts MATCH :match AND notes.author_id = :uid
            """ + ("" if current_user_id == user_id else " AND notes.is_public=1 "))
        rows = db.session.execute(sql, {"match": fq, "uid": user_id})

        scored_notes = []
        for row in rows:
            d = dict(row)
            title_score = longest_common_subsequence(d["title"], fq)
            content_score = longest_common_subsequence(d["content"], fq)
            total_score = title_score * 2 + content_score
            if total_score == 0:
                continue
            scored_notes.append((total_score, d))

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
        notes = base_query.order_by(Note.updated_at.desc()).limit(50).all()
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
        return jsonify({"msg": "无权限访问"}), 403
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
    data = request.get_json(force=True)
    if not data or not data.get("title") or not data.get("content"):
        return jsonify({"msg": "标题和内容不能为空"}), 400

    title = data.get("title").strip()
    content = data.get("content").strip()
    if not title or not content:
        return jsonify({"msg": "标题和内容不能为空"}), 400

    is_public = bool(data.get("is_public", False))

    note = Note(
        author_id=user_id,
        title=title,
        content=content,
        is_public=is_public
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
        return jsonify({"msg": "无权限操作"}), 403
    data = request.get_json(force=True)
    if not data:
        return jsonify({"msg": "缺少更新内容"}), 400

    title = data.get("title", note.title)
    content = data.get("content", note.content)
    if isinstance(title, str):
        title = title.strip()
    if isinstance(content, str):
        content = content.strip()
    if not title or not content:
        return jsonify({"msg": "标题和内容不能为空"}), 400
    note.title = title
    note.content = content
    note.is_public = bool(data.get("is_public", note.is_public))
    db.session.commit()
    return jsonify({"msg": "更新成功"})

@app.route("/notes/<int:note_id>", methods=["DELETE"])
@jwt_required()
def delete_note(note_id):
    user_id = get_jwt_identity()
    note = Note.query.get_or_404(note_id)
    if note.author_id != user_id:
        return jsonify({"msg": "无权限操作"}), 403
    db.session.delete(note)
    db.session.commit()
    return jsonify({"msg": "删除成功"})

@app.route("/me")
@jwt_required()
def me():
    user_id = get_jwt_identity()
    u = User.query.get(user_id)
    if not u:
        return jsonify({"msg": "不存在的用户"}), 404
    return jsonify({
        "id": u.id,
        "username": u.username,
        "email": u.email,
        "created_at": u.created_at.isoformat()
    })

@app.route("/")
def index():
    return full_html

if __name__ == '__main__':
    # Use threaded=True if needed, production use WSGI server recommended
    db.create_all()
    setup_fts5()
    print("启动服务器：http://127.0.0.1:5000")
    app.run(threaded=True)
