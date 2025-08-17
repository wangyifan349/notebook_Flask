import os
import sqlite3
import uuid
from functools import wraps
from flask import Flask, request, session, redirect, url_for, render_template_string, jsonify, send_from_directory, flash, abort
from werkzeug.security import generate_password_hash, check_password_hash

application = Flask(__name__)
application.secret_key = 'change_this_secret_key'
application_root = os.path.abspath(os.path.dirname(__file__))
database_path = os.path.join(application_root, 'application.db')
storage_root = os.path.join(application_root, 'uploads')
os.makedirs(storage_root, exist_ok=True)

template_page = '''
<!DOCTYPE html><html><head><meta charset="utf-8"><title>File Manager</title>
<style>
body{font-family:sans-serif;margin:20px;}
nav a{margin-right:10px;} .flash{color:red;}
#dropzone{border:2px dashed #888;padding:20px;text-align:center;margin-bottom:20px;}
.item{margin:5px 0;cursor:pointer;} .directory{font-weight:bold;} ul{list-style:none;padding-left:20px;}
button{margin-left:10px;}
</style>
</head><body>
<nav>
  {% if session.user %}
    User: <b>{{ session.user }}</b>
    <a href="/logout">Logout</a>
    <a href="/change_password">Change Password</a>
  {% else %}
    <a href="/login">Login</a><a href="/register">Register</a>
  {% endif %}
</nav>
{% with messages = get_flashed_messages() %}
  {% for message in messages %}<div class="flash">{{ message }}</div>{% endfor %}
{% endwith %}
{% if not session.user %}
  <form method="post">
    <p><input name="username" placeholder="Username"></p>
    <p><input name="password" type="password" placeholder="Password"></p>
    <p><button>{{ form_button_label }}</button></p>
  </form>
{% else %}
  <h1>File Manager</h1>
  <div id="dropzone">Drag files here to upload to current folder</div>
  <div>Current Folder: <span id="current-folder">/</span>
    <button onclick="createFolder()">New Folder</button>
  </div>
  <div id="file-tree"></div>
<script>
let currentFolderPath = '';
function fetchFileTree(path='') {
  currentFolderPath = path;
  document.getElementById('current-folder').textContent = '/' + path;
  fetch('/list?path=' + encodeURIComponent(path))
    .then(response=>response.json())
    .then(renderFileTree);
}
function renderFileTree(fileNodes) {
  document.getElementById('file-tree').innerHTML = buildFileList(fileNodes);
  attachEventHandlers();
}
function buildFileList(nodes) {
  let html = '<ul>';
  nodes.forEach(node=>{
    const cssClass = node.isDirectory ? 'directory' : 'file';
    const shareToken = node.shareToken || '';
    html += `<li class="item ${cssClass}" data-name="${node.name}" data-directory="${node.isDirectory}" data-share="${shareToken}">
      ${node.isDirectory ? '📁' : '📄'} ${node.name}
      ${shareToken ? '<button onclick="cancelShare(event)">Unshare</button>' : '<button onclick="initiateShare(event)">Share</button>'}
    </li>`;
    if(node.children) html += buildFileList(node.children);
  });
  html += '</ul>';
  return html;
}
function attachEventHandlers() {
  document.querySelectorAll('.item').forEach(element=>{
    const itemName = element.dataset.name;
    const isDirectory = element.dataset.directory === 'true';
    if(isDirectory) {
      element.addEventListener('dblclick', ()=> {
        const nextPath = currentFolderPath ? currentFolderPath + '/' + itemName : itemName;
        fetchFileTree(nextPath);
      });
      element.addEventListener('dragover', e=>e.preventDefault());
      element.addEventListener('drop', handleDropOnDirectory);
    } else {
      element.draggable = true;
      element.addEventListener('dblclick', ()=> {
        const filePath = (currentFolderPath ? currentFolderPath + '/' : '') + itemName;
        window.location = '/download?path=' + encodeURIComponent(filePath);
      });
      element.addEventListener('dragstart', e=> {
        e.dataTransfer.setData('text/plain', currentFolderPath + '||' + itemName);
      });
    }
    element.addEventListener('contextmenu', handleContextMenu);
  });
}
function handleDropOnDirectory(event) {
  event.preventDefault();
  const [sourcePath, fileName] = event.dataTransfer.getData('text/plain').split('||');
  const targetFolder = currentFolderPath ? currentFolderPath + '/' + event.currentTarget.dataset.name : event.currentTarget.dataset.name;
  fetch('/move', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({ source: sourcePath + '/' + fileName, destination: targetFolder })
  }).then(()=>fetchFileTree(currentFolderPath));
}
const dropzone = document.getElementById('dropzone');
dropzone.addEventListener('dragover', e=>e.preventDefault());
dropzone.addEventListener('drop', e=> {
  e.preventDefault();
  const file = e.dataTransfer.files[0];
  const formData = new FormData();
  formData.append('file', file);
  formData.append('path', currentFolderPath);
  fetch('/upload', { method:'POST', body: formData })
    .then(()=>fetchFileTree(currentFolderPath));
});
function handleContextMenu(event) {
  event.preventDefault();
  const itemName = event.currentTarget.dataset.name;
  const fullPath = currentFolderPath ? currentFolderPath + '/' + itemName : itemName;
  const action = prompt('Action: create_folder / delete / rename', 'delete');
  if(action === 'create_folder') {
    const newFolderName = prompt('Folder name:');
    if(newFolderName) {
      fetch('/create_folder', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ path: fullPath + '/' + newFolderName })
      }).then(()=>fetchFileTree(currentFolderPath));
    }
  }
  if(action === 'delete') {
    fetch('/delete', {
      method:'DELETE',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ path: fullPath })
    }).then(()=>fetchFileTree(currentFolderPath));
  }
  if(action === 'rename') {
    const newName = prompt('New name:', itemName);
    if(newName) {
      const newFullPath = currentFolderPath ? currentFolderPath + '/' + newName : newName;
      fetch('/rename', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ old_path: fullPath, new_path: newFullPath })
      }).then(()=>fetchFileTree(currentFolderPath));
    }
  }
}
function createFolder() {
  const newFolderName = prompt('New folder name:');
  if(newFolderName) {
    const fullPath = currentFolderPath ? currentFolderPath + '/' + newFolderName : newFolderName;
    fetch('/create_folder', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ path: fullPath })
    }).then(()=>fetchFileTree(currentFolderPath));
  }
}
function initiateShare(event) {
  event.stopPropagation();
  const itemName = event.currentTarget.parentNode.dataset.name;
  const fullPath = currentFolderPath ? currentFolderPath + '/' + itemName : itemName;
  fetch('/share', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({ path: fullPath })
  }).then(response=>response.json()).then(data=>{
    alert('Share link: ' + window.location.origin + '/s/' + data.share_token);
    fetchFileTree(currentFolderPath);
  });
}
function cancelShare(event) {
  event.stopPropagation();
  const shareToken = event.currentTarget.parentNode.dataset.share;
  fetch('/unshare', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({ share_token: shareToken })
  }).then(()=>fetchFileTree(currentFolderPath));
}
window.onload = ()=>fetchFileTree();
</script>
{% endif %}
</body></html>
'''

def get_database_connection():
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    return connection

def initialize_database():
    with get_database_connection() as connection:
        connection.execute('''CREATE TABLE IF NOT EXISTS users(
                                id INTEGER PRIMARY KEY,
                                username TEXT UNIQUE,
                                password_hash TEXT)''')
        connection.execute('''CREATE TABLE IF NOT EXISTS shares(
                                share_token TEXT PRIMARY KEY,
                                path TEXT,
                                is_directory INTEGER)''')
initialize_database()

def login_required(view_function):
    @wraps(view_function)
    def wrapper(*args, **kwargs):
        if not session.get('user'):
            return redirect(url_for('login'))
        return view_function(*args, **kwargs)
    return wrapper

@application.route('/register', methods=['GET','POST'])
def register():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        if not username or not password:
            flash('Username and password required')
            return redirect(url_for('register'))
        password_hash = generate_password_hash(password)
        try:
            with get_database_connection() as connection:
                connection.execute(
                    'INSERT INTO users(username,password_hash) VALUES(?,?)',
                    (username, password_hash)
                )
            flash('Registration succeeded')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('Username already exists')
            return redirect(url_for('register'))
    return render_template_string(template_page, form_button_label='Register')

@application.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        row = get_database_connection().execute(
            'SELECT * FROM users WHERE username=?', (username,)
        ).fetchone()
        if row and check_password_hash(row['password_hash'], password):
            session['user'] = username
            return redirect(url_for('index'))
        flash('Invalid username or password')
        return redirect(url_for('login'))
    return render_template_string(template_page, form_button_label='Login')

@application.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@application.route('/change_password', methods=['GET','POST'])
@login_required
def change_password():
    if request.method == 'POST':
        old_password = request.form['old_password']
        new_password = request.form['new_password']
        row = get_database_connection().execute(
            'SELECT * FROM users WHERE username=?', (session['user'],)
        ).fetchone()
        if not check_password_hash(row['password_hash'], old_password):
            flash('Old password incorrect')
            return redirect(url_for('change_password'))
        new_hash = generate_password_hash(new_password)
        with get_database_connection() as connection:
            connection.execute(
                'UPDATE users SET password_hash=? WHERE username=?',
                (new_hash, session['user'])
            )
        flash('Password updated')
        return redirect(url_for('index'))
    return render_template_string(template_page, form_button_label='Change Password')

def secure_join(root_directory, *subpaths):
    absolute_path = os.path.abspath(os.path.join(root_directory, *subpaths))
    if not absolute_path.startswith(root_directory):
        raise ValueError('Illegal path')
    return absolute_path

@application.route('/')
@login_required
def index():
    return render_template_string(template_page)

@application.route('/upload', methods=['POST'])
@login_required
def upload_file():
    upload_file_object = request.files['file']
    folder_path = request.form.get('path','').strip('/')
    target_directory = secure_join(storage_root, folder_path)
    os.makedirs(target_directory, exist_ok=True)
    upload_file_object.save(os.path.join(target_directory, upload_file_object.filename))
    return '', 204

@application.route('/create_folder', methods=['POST'])
@login_required
def create_folder():
    folder_path = request.json.get('path','').strip('/')
    os.makedirs(secure_join(storage_root, folder_path), exist_ok=True)
    return '', 204

def build_directory_listing(relative_path):
    absolute_directory = secure_join(storage_root, relative_path)
    listing = []
    for entry in sorted(os.listdir(absolute_directory)):
        entry_relative = relative_path + '/' + entry if relative_path else entry
        entry_full_path = os.path.join(absolute_directory, entry)
        share_record = get_database_connection().execute(
            'SELECT share_token FROM shares WHERE path=?', (entry_relative,)
        ).fetchone()
        if os.path.isdir(entry_full_path):
            listing.append({
                'name': entry,
                'isDirectory': True,
                'children': build_directory_listing(entry_relative),
                'shareToken': share_record['share_token'] if share_record else None
            })
        else:
            listing.append({
                'name': entry,
                'isDirectory': False,
                'shareToken': share_record['share_token'] if share_record else None
            })
    return listing

@application.route('/list')
@login_required
def list_files():
    folder_path = request.args.get('path','').strip('/')
    return jsonify(build_directory_listing(folder_path))

@application.route('/download')
@login_required
def download_file():
    file_path = request.args.get('path','').strip('/')
    absolute_file = secure_join(storage_root, file_path)
    directory_name, file_name = os.path.split(absolute_file)
    return send_from_directory(directory_name, file_name, as_attachment=True)

@application.route('/delete', methods=['DELETE'])
@login_required
def delete_entry():
    entry_path = request.json.get('path','').strip('/')
    absolute_entry = secure_join(storage_root, entry_path)
    if os.path.isdir(absolute_entry):
        os.rmdir(absolute_entry)
    else:
        os.remove(absolute_entry)
    with get_database_connection() as connection:
        connection.execute('DELETE FROM shares WHERE path=?', (entry_path,))
    return '', 204

@application.route('/rename', methods=['POST'])
@login_required
def rename_entry():
    old_path = request.json['old_path'].strip('/')
    new_path = request.json['new_path'].strip('/')
    os.rename(
        secure_join(storage_root, old_path),
        secure_join(storage_root, new_path)
    )
    with get_database_connection() as connection:
        connection.execute(
            'UPDATE shares SET path=? WHERE path=?', (new_path, old_path)
        )
    return '', 204

@application.route('/move', methods=['POST'])
@login_required
def move_entry():
    source_path = request.json['source'].strip('/')
    destination_path = request.json['destination'].strip('/')
    absolute_source = secure_join(storage_root, source_path)
    absolute_destination_dir = secure_join(storage_root, destination_path)
    os.makedirs(absolute_destination_dir, exist_ok=True)
    new_relative = destination_path + '/' + os.path.basename(source_path)
    os.rename(absolute_source, os.path.join(absolute_destination_dir, os.path.basename(source_path)))
    with get_database_connection() as connection:
        connection.execute(
            'UPDATE shares SET path=? WHERE path=?', (new_relative, source_path)
        )
    return '', 204

@application.route('/share', methods=['POST'])
@login_required
def create_share():
    entry_path = request.json.get('path','').strip('/')
    absolute_entry = secure_join(storage_root, entry_path)
    is_directory = os.path.isdir(absolute_entry)
    share_token = str(uuid.uuid4())
    with get_database_connection() as connection:
        connection.execute(
            'INSERT INTO shares(share_token,path,is_directory) VALUES(?,?,?)',
            (share_token, entry_path, int(is_directory))
        )
    return jsonify({ 'share_token': share_token })

@application.route('/unshare', methods=['POST'])
@login_required
def remove_share():
    share_token = request.json.get('share_token')
    with get_database_connection() as connection:
        connection.execute('DELETE FROM shares WHERE share_token=?', (share_token,))
    return '', 204

@application.route('/s/<share_token>')
def access_shared(share_token):
    record = get_database_connection().execute(
        'SELECT * FROM shares WHERE share_token=?', (share_token,)
    ).fetchone()
    if not record:
        abort(404)
    entry_path = record['path']
    absolute_entry = secure_join(storage_root, entry_path)
    if record['is_directory']:
        def build_shared_tree(relative):
            absolute = secure_join(storage_root, relative)
            result = []
            for name in sorted(os.listdir(absolute)):
                sub_relative = relative + '/' + name if relative else name
                sub_full = os.path.join(absolute, name)
                if os.path.isdir(sub_full):
                    result.append({
                        'name': name,
                        'isDirectory': True,
                        'children': build_shared_tree(sub_relative)
                    })
                else:
                    result.append({ 'name': name, 'isDirectory': False })
            return result
        return jsonify({ 'path': entry_path, 'tree': build_shared_tree(entry_path) })
    else:
        directory_name, file_name = os.path.split(absolute_entry)
        return send_from_directory(directory_name, file_name, as_attachment=True)

if __name__ == '__main__':
    application.run(debug=True, port=5000)
