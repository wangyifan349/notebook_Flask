from flask import Flask, request, jsonify, render_template_string
from flask_sqlalchemy import SQLAlchemy
from flask_jwt_extended import (
    JWTManager,
    create_access_token,
    jwt_required,
    get_jwt_identity,
    unset_jwt_cookies,
    set_access_cookies
)
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import os
from marshmallow import Schema, fields, validate, ValidationError

# 创建 Flask 应用
app = Flask(__name__)

# 配置数据库和 JWT
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'change_this_secret')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///app_data.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['JWT_TOKEN_LOCATION'] = ['cookies']
app.config['JWT_COOKIE_SECURE'] = True               # 仅通过 HTTPS 发送 Cookie
app.config['JWT_ACCESS_COOKIE_PATH'] = '/'
app.config['JWT_REFRESH_COOKIE_PATH'] = '/'
app.config['JWT_COOKIE_CSRF_PROTECT'] = True         # 启用 CSRF 防护
app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET_KEY', 'change_this_jwt_secret')

# 初始化数据库和JWT管理器
database = SQLAlchemy(app)
jwt_manager = JWTManager(app)


# 用户模型
class UserModel(database.Model):
    id = database.Column(database.Integer, primary_key=True)
    user_name = database.Column(database.String(80), unique=True, nullable=False)
    user_email = database.Column(database.String(120), unique=True, nullable=False)
    password_hash = database.Column(database.String(128), nullable=False)
    created_on = database.Column(database.DateTime, default=datetime.utcnow)
    notes = database.relationship('NoteModel', backref='author', lazy=True)

    def set_password(self, password_plain):
        # 设置并保存密码哈希
        hashed = generate_password_hash(password_plain)
        self.password_hash = hashed

    def check_password(self, password_plain):
        # 验证密码正确性
        return check_password_hash(self.password_hash, password_plain)


# 笔记模型
class NoteModel(database.Model):
    id = database.Column(database.Integer, primary_key=True)
    owner_id = database.Column(database.Integer, database.ForeignKey('user_model.id'), nullable=False)
    note_title = database.Column(database.String(200))
    note_body = database.Column(database.Text, nullable=False)
    is_public = database.Column(database.Boolean, default=False)
    created_on = database.Column(database.DateTime, default=datetime.utcnow)
    updated_on = database.Column(database.DateTime,
                                default=datetime.utcnow,
                                onupdate=datetime.utcnow)


@app.before_first_request
def create_database_tables():
    # 启动时创建表
    database.create_all()


def longest_common_subsequence_length(text1, text2):
    # 计算两个字符串的最长公共子序列长度
    length1 = len(text1)
    length2 = len(text2)
    # 初始化 DP 表
    dp = []
    for _ in range(length1 + 1):
        row = []
        for __ in range(length2 + 1):
            row.append(0)
        dp.append(row)

    # 填表过程
    for i in range(1, length1 + 1):
        for j in range(1, length2 + 1):
            if text1[i - 1] == text2[j - 1]:
                dp[i][j] = dp[i - 1][j - 1] + 1
            else:
                if dp[i - 1][j] > dp[i][j - 1]:
                    dp[i][j] = dp[i - 1][j]
                else:
                    dp[i][j] = dp[i][j - 1]
    return dp[length1][length2]


def compute_similarity_score(text1, text2):
    # 基于 LCS 算法计算相似度
    if not text1 or not text2:
        return 0
    common_length = longest_common_subsequence_length(
        text1.lower(), text2.lower()
    )
    total_length = len(text1) + len(text2)
    score = common_length * 2 / total_length
    return score


# 注册请求验证模式
class RegistrationSchema(Schema):
    user_name = fields.Str(
        required=True,
        validate=validate.Length(min=3, max=80)
    )
    user_email = fields.Email(
        required=True,
        validate=validate.Length(max=120)
    )
    user_password = fields.Str(
        required=True,
        validate=validate.Length(min=6)
    )


registration_schema = RegistrationSchema()


@app.route('/api/register', methods=['POST'])
def api_register_user():
    # 用户注册接口
    request_data = request.json or {}
    try:
        validated = registration_schema.load(request_data)
    except ValidationError as error:
        return jsonify(error.messages), 400

    existing_username = UserModel.query.filter_by(user_name=validated['user_name']).first()
    existing_email = UserModel.query.filter_by(user_email=validated['user_email']).first()
    if existing_username or existing_email:
        return jsonify(message='Username or email already registered'), 400

    # 创建新用户
    user = UserModel()
    user.user_name = validated['user_name']
    user.user_email = validated['user_email']
    user.set_password(validated['user_password'])

    database.session.add(user)
    database.session.commit()
    return jsonify(message='Registration successful'), 201


@app.route('/api/login', methods=['POST'])
def api_login_user():
    # 用户登录接口
    request_data = request.json or {}
    if 'user_name' not in request_data or 'user_password' not in request_data:
        return jsonify(message='Username and password required'), 400

    user = UserModel.query.filter_by(user_name=request_data['user_name']).first()
    if not user or not user.check_password(request_data['user_password']):
        return jsonify(message='Invalid username or password'), 401

    # 生成并设置 JWT Cookie
    token = create_access_token(identity=user.id, expires_delta=timedelta(hours=1))
    response = jsonify(message='Login successful')
    set_access_cookies(response, token)
    return response, 200


@app.route('/api/logout', methods=['POST'])
def api_logout_user():
    # 用户登出接口
    response = jsonify(message='Logout successful')
    unset_jwt_cookies(response)
    return response, 200


@app.route('/api/note', methods=['POST'])
@jwt_required()
def api_create_note():
    # 创建笔记接口
    request_data = request.json or {}
    if 'note_body' not in request_data:
        return jsonify(message='Note body is required'), 400

    user_id = get_jwt_identity()
    note = NoteModel()
    note.owner_id = user_id
    note.note_title = request_data.get('note_title', '')
    note.note_body = request_data['note_body']
    note.is_public = request_data.get('is_public', False)

    database.session.add(note)
    database.session.commit()
    return jsonify(message='Note created', note_id=note.id), 201


@app.route('/api/note/<int:note_id>', methods=['PUT'])
@jwt_required()
def api_update_note(note_id):
    # 更新笔记接口
    note = NoteModel.query.get_or_404(note_id)
    current_user = get_jwt_identity()
    if note.owner_id != current_user:
        return jsonify(message='Forbidden'), 403

    request_data = request.json or {}
    if 'note_title' in request_data:
        note.note_title = request_data['note_title']
    if 'note_body' in request_data:
        note.note_body = request_data['note_body']
    if 'is_public' in request_data:
        note.is_public = request_data['is_public']

    database.session.commit()
    return jsonify(message='Note updated'), 200


@app.route('/api/note/<int:note_id>', methods=['DELETE'])
@jwt_required()
def api_delete_note(note_id):
    # 删除笔记接口
    note = NoteModel.query.get_or_404(note_id)
    current_user = get_jwt_identity()
    if note.owner_id != current_user:
        return jsonify(message='Forbidden'), 403

    database.session.delete(note)
    database.session.commit()
    return jsonify(message='Note deleted'), 200


@app.route('/api/dashboard', methods=['GET'])
@jwt_required()
def api_get_dashboard():
    # 获取用户笔记列表
    current_user = get_jwt_identity()
    user_notes = NoteModel.query.filter_by(owner_id=current_user).order_by(
        NoteModel.created_on.desc()
    ).all()
    result_list = []
    for single_note in user_notes:
        entry = {
            'note_id': single_note.id,
            'note_title': single_note.note_title,
            'created_on': single_note.created_on.isoformat(),
            'updated_on': single_note.updated_on.isoformat()
        }
        result_list.append(entry)
    return jsonify(notes=result_list), 200


@app.route('/api/note/<int:note_id>/view', methods=['GET'])
@jwt_required()
def api_view_note_detail(note_id):
    # 查看单条笔记详情
    note = NoteModel.query.get_or_404(note_id)
    current_user = get_jwt_identity()
    if not note.is_public and note.owner_id != current_user:
        return jsonify(message='Forbidden'), 403

    data = {
        'note_id': note.id,
        'note_title': note.note_title,
        'note_body': note.note_body,
        'author_name': note.author.user_name,
        'is_public': note.is_public,
        'created_on': note.created_on.isoformat(),
        'updated_on': note.updated_on.isoformat()
    }
    return jsonify(data), 200


@app.route('/api/search/user', methods=['GET'])
def api_search_users():
    # 按用户名搜索接口，带分页和相似度计算
    query_text = request.args.get('q', '').strip()
    if not query_text:
        return jsonify(message='Search query required'), 400

    page_str = request.args.get('page', '1')
    per_page_str = request.args.get('per_page', '20')
    page = int(page_str)
    per_page = int(per_page_str)
    if per_page > 50:
        per_page = 50

    pagination = UserModel.query.order_by(UserModel.user_name).paginate(
        page=page, per_page=per_page, error_out=False
    )
    matched_items = []
    for user_item in pagination.items:
        score = compute_similarity_score(user_item.user_name, query_text)
        if score >= 0.1:
            matched_items.append((user_item, score))
    matched_items.sort(key=lambda pair: pair[1], reverse=True)

    result_list = []
    for pair in matched_items:
        user_item = pair[0]
        similarity_value = pair[1]
        entry = {
            'user_name': user_item.user_name,
            'similarity_score': round(similarity_value, 3)
        }
        result_list.append(entry)

    response_data = {
        'results': result_list,
        'page': page,
        'per_page': per_page,
        'total': pagination.total
    }
    return jsonify(response_data), 200


@app.route('/api/search/note', methods=['GET'])
def api_search_notes():
    # 按笔记标题搜索接口，带分页和相似度计算
    query_text = request.args.get('q', '').strip()
    if not query_text:
        return jsonify(message='Search query required'), 400

    page_str = request.args.get('page', '1')
    per_page_str = request.args.get('per_page', '20')
    page = int(page_str)
    per_page = int(per_page_str)
    if per_page > 50:
        per_page = 50

    pagination = NoteModel.query.filter(
        NoteModel.note_title.isnot(None)
    ).order_by(
        NoteModel.created_on.desc()
    ).paginate(page=page, per_page=per_page, error_out=False)

    matched_items = []
    for note_item in pagination.items:
        score = compute_similarity_score(note_item.note_title, query_text)
        if score >= 0.1:
            matched_items.append((note_item, score))
    matched_items.sort(key=lambda pair: (pair[1], pair[0].created_on), reverse=True)

    result_list = []
    for pair in matched_items:
        note_item = pair[0]
        similarity_value = pair[1]
        entry = {
            'note_id': note_item.id,
            'note_title': note_item.note_title,
            'author_name': note_item.author.user_name,
            'similarity_score': round(similarity_value, 3),
            'created_on': note_item.created_on.isoformat()
        }
        result_list.append(entry)

    response_data = {
        'results': result_list,
        'page': page,
        'per_page': per_page,
        'total': pagination.total
    }
    return jsonify(response_data), 200


frontend_html = """
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Knowledge Sharing</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 20px; }
    input, button, textarea { margin: 5px 0; padding: 5px; width: 100%; }
    .note { border: 1px solid #ccc; padding: 10px; margin: 5px 0; }
  </style>
</head>
<body>

<h2>Register / Login</h2>
<div id="authSection">
  <input id="inputRegisterUserName" placeholder="Username"><br>
  <input id="inputRegisterEmail" placeholder="Email"><br>
  <input id="inputRegisterPassword" type="password" placeholder="Password"><br>
  <button onclick="doRegister()">Register</button>
  <hr>
  <input id="inputLoginUserName" placeholder="Username"><br>
  <input id="inputLoginPassword" type="password" placeholder="Password"><br>
  <button onclick="doLogin()">Login</button>
  <button onclick="doLogout()">Logout</button>
</div>

<h2>Create / Edit Note</h2>
<div id="noteEditorSection">
  <input id="inputNoteId" type="hidden">
  <input id="inputNoteTitle" placeholder="Title"><br>
  <textarea id="inputNoteBody" rows="4" placeholder="Content"></textarea><br>
  <label><input type="checkbox" id="inputNotePublic"> Public</label><br>
  <button onclick="saveNote()">Save Note</button>
</div>

<h2>My Notes</h2>
<div id="notesContainer"></div>

<h2>Search Users / Notes</h2>
<input id="inputSearchText" placeholder="Search term"><br>
<button onclick="searchForUsers()">Search Users</button>
<button onclick="searchForNotes()">Search Notes</button>
<div id="searchResultsContainer"></div>

<script>
function getCookie(name) {
  var match = document.cookie.match('(^|;) ?' + name + '=([^;]*)(;|$)');
  return match ? match[2] : null;
}

function apiCall(url, method, data) {
  var headers = {'Content-Type': 'application/json'};
  var csrf = getCookie('csrf_access_token');
  if (csrf) {
    headers['X-CSRF-TOKEN'] = csrf;
  }
  var options = {
    method: method,
    headers: headers,
    credentials: 'same-origin'
  };
  if (data) {
    options.body = JSON.stringify(data);
  }
  return fetch(url, options).then(function(response) {
    return response.json();
  });
}

function doRegister() {
  var name = document.getElementById('inputRegisterUserName').value;
  var email = document.getElementById('inputRegisterEmail').value;
  var pwd  = document.getElementById('inputRegisterPassword').value;
  apiCall('/api/register', 'POST', {
    user_name: name,
    user_email: email,
    user_password: pwd
  }).then(function(res) {
    alert(res.message || JSON.stringify(res));
  });
}

function doLogin() {
  var name = document.getElementById('inputLoginUserName').value;
  var pwd  = document.getElementById('inputLoginPassword').value;
  apiCall('/api/login', 'POST', {
    user_name: name,
    user_password: pwd
  }).then(function(res) {
    alert(res.message);
    loadMyNotes();
  });
}

function doLogout() {
  apiCall('/api/logout', 'POST').then(function(res) {
    alert(res.message);
    document.getElementById('notesContainer').innerHTML = '';
  });
}

function loadMyNotes() {
  apiCall('/api/dashboard', 'GET').then(function(res) {
    var container = document.getElementById('notesContainer');
    container.innerHTML = '';
    var notesList = res.notes;
    for (var i = 0; i < notesList.length; i++) {
      var note = notesList[i];
      var div = document.createElement('div');
      div.className = 'note';
      var title = note.note_title || '(No Title)';
      div.innerHTML = '<b>' + title + '</b><br>' +
                      '<i>' + note.created_on + '</i><br>' +
                      '<button onclick="editExistingNote(' + note.note_id + ')">Edit</button>' +
                      '<button onclick="deleteExistingNote(' + note.note_id + ')">Delete</button>';
      container.appendChild(div);
    }
  });
}

function editExistingNote(id) {
  apiCall('/api/note/' + id + '/view', 'GET').then(function(note) {
    document.getElementById('inputNoteId').value = note.note_id;
    document.getElementById('inputNoteTitle').value = note.note_title;
    document.getElementById('inputNoteBody').value = note.note_body;
    document.getElementById('inputNotePublic').checked = note.is_public;
  });
}

function saveNote() {
  var id    = document.getElementById('inputNoteId').value;
  var title = document.getElementById('inputNoteTitle').value;
  var body  = document.getElementById('inputNoteBody').value;
  var pub   = document.getElementById('inputNotePublic').checked;
  var url    = '/api/note';
  var method = 'POST';
  if (id) {
    url    = '/api/note/' + id;
    method = 'PUT';
  }
  apiCall(url, method, {
    note_title: title,
    note_body: body,
    is_public:  pub
  }).then(function(res) {
    alert(res.message);
    clearEditorFields();
    loadMyNotes();
  });
}

function clearEditorFields() {
  document.getElementById('inputNoteId').value = '';
  document.getElementById('inputNoteTitle').value = '';
  document.getElementById('inputNoteBody').value = '';
  document.getElementById('inputNotePublic').checked = false;
}

function deleteExistingNote(id) {
  if (!confirm('Confirm deletion?')) {
    return;
  }
  apiCall('/api/note/' + id, 'DELETE').then(function(res) {
    alert(res.message);
    loadMyNotes();
  });
}

function searchForUsers() {
  var text = encodeURIComponent(
    document.getElementById('inputSearchText').value
  );
  apiCall('/api/search/user?q=' + text, 'GET').then(function(res) {
    var out = '<h4>Users</h4>';
    var list = res.results;
    for (var i = 0; i < list.length; i++) {
      var u = list[i];
      out += '<div>' + u.user_name +
             ' (Similarity: ' + u.similarity_score + ')</div>';
    }
    document.getElementById('searchResultsContainer').innerHTML = out;
  });
}

function searchForNotes() {
  var text = encodeURIComponent(
    document.getElementById('inputSearchText').value
  );
  apiCall('/api/search/note?q=' + text, 'GET').then(function(res) {
    var out = '<h4>Notes</h4>';
    var list = res.results;
    for (var i = 0; i < list.length; i++) {
      var n = list[i];
      out += '<div>' +
             n.note_title + ' by ' + n.author_name +
             ' (Similarity: ' + n.similarity_score + ')</div>';
    }
    document.getElementById('searchResultsContainer').innerHTML = out;
  });
}

window.onload = loadMyNotes  # 页面加载后自动拉取用户笔记列表

</script>

</body>
</html>
"""


@app.route('/')
def index_page():
    # 渲染前端页面
    return render_template_string(frontend_html)


if __name__ == '__main__':
    # 启动 Flask 开发服务器
    app.run(debug=True)
