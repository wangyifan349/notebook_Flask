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

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'change_this_secret')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///data.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['JWT_TOKEN_LOCATION'] = ['cookies']
app.config['JWT_COOKIE_SECURE'] = False
app.config['JWT_ACCESS_COOKIE_PATH'] = '/'
app.config['JWT_REFRESH_COOKIE_PATH'] = '/'
app.config['JWT_COOKIE_CSRF_PROTECT'] = False
app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET_KEY', 'change_this_jwt_secret')

database = SQLAlchemy(app)
jwt_manager = JWTManager(app)

# ---- Models ----
class User(database.Model):
    id = database.Column(database.Integer, primary_key=True)
    username = database.Column(database.String(80), unique=True, nullable=False)
    email = database.Column(database.String(120), unique=True, nullable=False)
    password_hash = database.Column(database.String(128), nullable=False)
    created_at = database.Column(database.DateTime, default=datetime.utcnow)
    notes = database.relationship('Note', backref='author', lazy=True)

    def set_password(self, plain_password):
        self.password_hash = generate_password_hash(plain_password)

    def check_password(self, plain_password):
        return check_password_hash(self.password_hash, plain_password)

class Note(database.Model):
    id = database.Column(database.Integer, primary_key=True)
    user_id = database.Column(database.Integer, database.ForeignKey('user.id'), nullable=False)
    title = database.Column(database.String(200))
    content = database.Column(database.Text, nullable=False)
    created_at = database.Column(database.DateTime, default=datetime.utcnow)
    updated_at = database.Column(database.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

# ---- Database Initialization ----
@app.before_first_request
def create_tables():
    database.create_all()

# ---- Utility Functions: LCS & similarity ----
def longest_common_subsequence_length(string_a, string_b):
    length_a, length_b = len(string_a), len(string_b)
    dp_table = [[0] * (length_b + 1) for _ in range(length_a + 1)]
    for index_a in range(1, length_a + 1):
        for index_b in range(1, length_b + 1):
            if string_a[index_a - 1] == string_b[index_b - 1]:
                dp_table[index_a][index_b] = dp_table[index_a - 1][index_b - 1] + 1
            else:
                dp_table[index_a][index_b] = max(
                    dp_table[index_a - 1][index_b],
                    dp_table[index_a][index_b - 1]
                )
    return dp_table[length_a][length_b]

def similarity_score(text_a, text_b):
    if not text_a or not text_b:
        return 0
    common_length = longest_common_subsequence_length(text_a.lower(), text_b.lower())
    return common_length * 2 / (len(text_a) + len(text_b))

# ---- Authentication Endpoints ----
@app.route('/api/register', methods=['POST'])
def register_user():
    data = request.json or {}
    if not data.get('username') or not data.get('email') or not data.get('password'):
        return jsonify(message='Missing required fields'), 400
    existing_user = User.query.filter(
        (User.username == data['username']) | (User.email == data['email'])
    ).first()
    if existing_user:
        return jsonify(message='Username or email already exists'), 400
    new_user = User(username=data['username'], email=data['email'])
    new_user.set_password(data['password'])
    database.session.add(new_user)
    database.session.commit()
    return jsonify(message='Registration successful'), 201

@app.route('/api/login', methods=['POST'])
def login_user():
    data = request.json or {}
    if not data.get('username') or not data.get('password'):
        return jsonify(message='Missing required fields'), 400
    user = User.query.filter_by(username=data['username']).first()
    if not user or not user.check_password(data['password']):
        return jsonify(message='Invalid username or password'), 401
    access_token = create_access_token(identity=user.id, expires_delta=timedelta(hours=1))
    response = jsonify(message='Login successful')
    set_access_cookies(response, access_token)
    return response, 200

@app.route('/api/logout', methods=['POST'])
def logout_user():
    response = jsonify(message='Logout successful')
    unset_jwt_cookies(response)
    return response, 200

# ---- Note Management Endpoints ----
@app.route('/api/note', methods=['POST'])
@jwt_required()
def create_note():
    data = request.json or {}
    if not data.get('content'):
        return jsonify(message='Content is required'), 400
    current_user_id = get_jwt_identity()
    new_note = Note(
        user_id=current_user_id,
        title=data.get('title', ''),
        content=data['content']
    )
    database.session.add(new_note)
    database.session.commit()
    return jsonify(message='Note created', note_id=new_note.id), 201

@app.route('/api/note/<int:note_id>', methods=['PUT'])
@jwt_required()
def update_note(note_id):
    existing_note = Note.query.get_or_404(note_id)
    current_user_id = get_jwt_identity()
    if existing_note.user_id != current_user_id:
        return jsonify(message='Forbidden'), 403
    data = request.json or {}
    if 'title' in data:
        existing_note.title = data['title']
    if 'content' in data:
        existing_note.content = data['content']
    database.session.commit()
    return jsonify(message='Note updated'), 200

@app.route('/api/note/<int:note_id>', methods=['DELETE'])
@jwt_required()
def delete_note(note_id):
    existing_note = Note.query.get_or_404(note_id)
    current_user_id = get_jwt_identity()
    if existing_note.user_id != current_user_id:
        return jsonify(message='Forbidden'), 403
    database.session.delete(existing_note)
    database.session.commit()
    return jsonify(message='Note deleted'), 200

@app.route('/api/dashboard', methods=['GET'])
@jwt_required()
def get_user_dashboard():
    current_user_id = get_jwt_identity()
    user_notes = Note.query.filter_by(user_id=current_user_id).order_by(Note.created_at.desc()).all()
    note_list = []
    for note in user_notes:
        note_list.append({
            'noteId': note.id,
            'noteTitle': note.title,
            'createdAt': note.created_at.isoformat(),
            'updatedAt': note.updated_at.isoformat()
        })
    return jsonify(notes=note_list), 200

@app.route('/api/note/<int:note_id>/view', methods=['GET'])
@jwt_required(optional=True)
def view_note_detail(note_id):
    note = Note.query.get_or_404(note_id)
    return jsonify({
        'noteId': note.id,
        'noteTitle': note.title,
        'noteContent': note.content,
        'noteAuthor': note.author.username,
        'createdAt': note.created_at.isoformat(),
        'updatedAt': note.updated_at.isoformat()
    }), 200

# ---- Search Endpoints ----
@app.route('/api/search/user', methods=['GET'])
def search_users():
    query_text = request.args.get('q', '').strip()
    if not query_text:
        return jsonify(message='Please provide a search query'), 400
    matched_list = []
    for user in User.query.all():
        score = similarity_score(user.username, query_text)
        if score > 0:
            matched_list.append((user, score))
    matched_list.sort(key=lambda pair: pair[1], reverse=True)
    results = []
    for user, score in matched_list:
        results.append({
            'username': user.username,
            'similarityScore': round(score, 3)
        })
    return jsonify(results=results), 200

@app.route('/api/search/note', methods=['GET'])
def search_notes():
    query_text = request.args.get('q', '').strip()
    if not query_text:
        return jsonify(message='Please provide a search query'), 400
    matched_list = []
    for note in Note.query.all():
        if not note.title:
            continue
        score = similarity_score(note.title, query_text)
        if score > 0:
            matched_list.append((note, score))
    # sort by similarity score then by creation date, both descending
    matched_list.sort(key=lambda pair: (pair[1], pair[0].created_at), reverse=True)
    results = []
    for note, score in matched_list:
        results.append({
            'noteId': note.id,
            'noteTitle': note.title,
            'noteAuthor': note.author.username,
            'similarityScore': round(score, 3),
            'createdAt': note.created_at.isoformat()
        })
    return jsonify(results=results), 200

# ---- Frontend Template ----
FRONTEND_HTML = """
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Plain Text Knowledge Publishing</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 20px; }
    input, button, textarea { margin: 5px 0; padding: 5px; width: 100%; }
    .note { border: 1px solid #ccc; padding: 10px; margin: 5px 0; }
  </style>
</head>
<body>

<h2>Register / Login</h2>
<div id="authentication">
  <input id="registerUsername" placeholder="Username"><br>
  <input id="registerEmail" placeholder="Email"><br>
  <input id="registerPassword" type="password" placeholder="Password"><br>
  <button onclick="registerUser()">Register</button>
  <hr>
  <input id="loginUsername" placeholder="Username"><br>
  <input id="loginPassword" type="password" placeholder="Password"><br>
  <button onclick="loginUser()">Login</button>
  <button onclick="logoutUser()">Logout</button>
</div>

<h2>Create / Edit Note</h2>
<div id="noteEditor">
  <input id="editorNoteId" type="hidden">
  <input id="editorNoteTitle" placeholder="Title (optional)"><br>
  <textarea id="editorNoteContent" rows="4" placeholder="Content"></textarea><br>
  <button onclick="saveOrUpdateNote()">Save Note</button>
</div>

<h2>My Dashboard</h2>
<div id="dashboardContainer"></div>

<h2>Search Users / Notes by Title</h2>
<input id="searchQuery" placeholder="Search term"><br>
<button onclick="searchUsers()">Search Users</button>
<button onclick="searchNotes()">Search Notes</button>
<div id="searchResults"></div>

<script>
function apiRequest(path, method = 'GET', data = null) {
  const options = { method: method, headers: { 'Content-Type': 'application/json' }, credentials: 'same-origin' };
  if (data) {
    options.body = JSON.stringify(data);
  }
  return fetch(path, options).then(response => response.json());
}

function registerUser() {
  const username = document.getElementById('registerUsername').value;
  const email = document.getElementById('registerEmail').value;
  const password = document.getElementById('registerPassword').value;
  apiRequest('/api/register', 'POST', { username: username, email: email, password: password })
    .then(response => alert(response.message));
}

function loginUser() {
  const username = document.getElementById('loginUsername').value;
  const password = document.getElementById('loginPassword').value;
  apiRequest('/api/login', 'POST', { username: username, password: password })
    .then(response => { alert(response.message); loadDashboard(); });
}

function logoutUser() {
  apiRequest('/api/logout', 'POST')
    .then(response => { alert(response.message); document.getElementById('dashboardContainer').innerHTML = ''; });
}

function loadDashboard() {
  apiRequest('/api/dashboard').then(response => {
    let html = '';
    response.notes.forEach(note => {
      html += `<div class="note">
        <a href="#" onclick="viewNoteDetail(${note.noteId})"><b>${note.noteTitle || '(No Title)'}</b></a><br>
        <i>${note.createdAt}</i><br>
        <button onclick="populateEditor(${note.noteId}, '${note.noteTitle}', '')">Edit</button>
        <button onclick="deleteNote(${note.noteId})">Delete</button>
      </div>`;
    });
    document.getElementById('dashboardContainer').innerHTML = html;
  });
}

function saveOrUpdateNote() {
  const noteId = document.getElementById('editorNoteId').value;
  const title = document.getElementById('editorNoteTitle').value;
  const content = document.getElementById('editorNoteContent').value;
  const path = noteId ? `/api/note/${noteId}` : '/api/note';
  const method = noteId ? 'PUT' : 'POST';
  apiRequest(path, method, { title: title, content: content })
    .then(response => {
      alert(response.message);
      clearEditor();
      loadDashboard();
    });
}

function populateEditor(id, title, content) {
  document.getElementById('editorNoteId').value = id;
  document.getElementById('editorNoteTitle').value = title;
  document.getElementById('editorNoteContent').value = content;
}

function deleteNote(id) {
  if (!confirm('Confirm deletion?')) { return; }
  apiRequest(`/api/note/${id}`, 'DELETE')
    .then(response => { alert(response.message); loadDashboard(); });
}

function searchUsers() {
  const queryText = document.getElementById('searchQuery').value;
  apiRequest(`/api/search/user?q=${encodeURIComponent(queryText)}`)
    .then(response => {
      let html = '<h4>User Search Results</h4>';
      response.results.forEach(user => {
        html += `<div>${user.username} (Similarity: ${user.similarityScore})</div>`;
      });
      document.getElementById('searchResults').innerHTML = html;
    });
}

function searchNotes() {
  const queryText = document.getElementById('searchQuery').value;
  apiRequest(`/api/search/note?q=${encodeURIComponent(queryText)}`)
    .then(response => {
      let html = '<h4>Note Search Results</h4>';
      response.results.forEach(note => {
        html += `<div>
          <a href="#" onclick="viewNoteDetail(${note.noteId})">${note.noteTitle}</a>
          by ${note.noteAuthor} (Similarity: ${note.similarityScore})
        </div>`;
      });
      document.getElementById('searchResults').innerHTML = html;
    });
}

function viewNoteDetail(noteId) {
  apiRequest(`/api/note/${noteId}/view`).then(note => {
    const contentHtml = note.noteContent.replace(/\\n/g, '<br>');
    const detailHtml = `
      <h3>${note.noteTitle || '(No Title)'}</h3>
      <p>Author: ${note.noteAuthor}</p>
      <p>${contentHtml}</p>
      <p><i>Created: ${note.createdAt}</i></p>
    `;
    const popup = window.open('', '_blank', 'width=600,height=400');
    popup.document.write(detailHtml);
  });
}

window.onload = loadDashboard;
</script>

</body>
</html>
"""

@app.route('/')
def index_page():
    return render_template_string(FRONTEND_HTML)

if __name__ == '__main__':
    app.run(debug=True)
