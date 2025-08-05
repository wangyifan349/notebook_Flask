from flask import Flask, request, send_from_directory, jsonify, render_template_string
from flask_httpauth import HTTPBasicAuth
from werkzeug.security import generate_password_hash, check_password_hash
import os
import shutil

app = Flask(__name__)

# —— HTTP Basic Auth 配置 —— 
auth = HTTPBasicAuth()

# 示例用户表：用户名 -> 密码哈希
users = {
    "alice": generate_password_hash("password123"),
    "bob":   generate_password_hash("secret456")
}

@auth.verify_password
def verify_password(username, password):
    if username in users and check_password_hash(users.get(username), password):
        return username
    return None

# —— 目录配置 —— 
BASE_DIRECTORY = os.path.abspath(os.path.dirname(__file__))
STORAGE_DIRECTORY = os.path.join(BASE_DIRECTORY, 'uploads')
os.makedirs(STORAGE_DIRECTORY, exist_ok=True)

# —— 前端 HTML 模板 —— 
PAGE_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Flask File Manager</title>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/jquery/3.6.0/jquery.min.js"></script>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/jquery-contextmenu/2.9.2/jquery.contextMenu.min.js"></script>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/jquery-contextmenu/2.9.2/jquery.contextMenu.min.css"/>
  <style>
    body { font-family: Arial, sans-serif; margin: 20px; }
    ul { list-style: none; padding: 0; }
    li { padding: 8px; margin: 4px 0; border: 1px solid #ddd; cursor: pointer; }
    .directory { font-weight: bold; background-color: #f9f9f9; }
    .drag-over { background-color: #d0ebff !important; }
  </style>
</head>
<body>
  <h1>Flask File Manager</h1>
  <button id="button-new-folder">Create Folder</button>
  <input type="file" id="input-file-upload">
  <button id="button-go-up">Go Up</button>
  <ul id="file-list"></ul>

<script>
let currentFolder = '';

function refreshFileList() {
  $.get('/list', { path: currentFolder }, data => {
    const listElement = $('#file-list').empty();
    data.forEach(item => {
      const listItem = $('<li draggable="true">')
        .text(item.name + (item.isDirectory ? '/' : ''))
        .data('name', item.name)
        .toggleClass('directory', item.isDirectory);
      listElement.append(listItem);
    });
  });
}

$(document).ready(function(){
  refreshFileList();

  $('#file-list').on('dblclick', 'li', function(){
    const itemName = $(this).data('name');
    if ($(this).hasClass('directory')) {
      currentFolder = currentFolder 
        ? `${currentFolder}/${itemName}` 
        : itemName;
      refreshFileList();
    } else {
      window.location = `/download?path=${encodeURIComponent((currentFolder ? currentFolder + '/' : '') + itemName)}`;
    }
  });

  $('#button-go-up').click(() => {
    if (!currentFolder) return;
    const pathParts = currentFolder.split('/');
    pathParts.pop();
    currentFolder = pathParts.join('/');
    refreshFileList();
  });

  $('#input-file-upload').change(function(){
    const fileToUpload = this.files[0];
    const formData = new FormData();
    formData.append('file', fileToUpload);
    formData.append('path', currentFolder);
    $.ajax({
      url: '/upload',
      method: 'POST',
      data: formData,
      processData: false,
      contentType: false
    }).always(refreshFileList);
  });

  $('#button-new-folder').click(() => {
    const folderName = prompt('Enter new folder name:');
    if (!folderName) return;
    $.ajax({
      url: '/mkdir',
      method: 'POST',
      contentType: 'application/json',
      data: JSON.stringify({ path: currentFolder, folder_name: folderName })
    }).always(refreshFileList);
  });

  $.contextMenu({
    selector: '#file-list li',
    callback: function(action, options) {
      const itemName = options.$trigger.data('name');
      const fullPath = (currentFolder ? currentFolder + '/' : '') + itemName;

      if (action === 'delete') {
        if (confirm(`Delete "${itemName}"?`)) {
          $.ajax({
            url: '/delete',
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ path: fullPath })
          }).always(refreshFileList);
        }
      }

      if (action === 'rename') {
        const newName = prompt('Enter new name:', itemName);
        if (newName && newName !== itemName) {
          $.ajax({
            url: '/rename',
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ path: fullPath, new_name: newName })
          }).always(refreshFileList);
        }
      }
    },
    items: {
      "delete": { name: "Delete" },
      "sep1": "---------",
      "rename": { name: "Rename" }
    }
  });

  let draggedItemName = null;

  $('#file-list').on('dragstart', 'li', function(event) {
    draggedItemName = $(this).data('name');
    event.originalEvent.dataTransfer.setData('text/plain', '');
  });

  $('#file-list').on('dragover', 'li.directory', function(event) {
    event.preventDefault();
    $(this).addClass('drag-over');
  });

  $('#file-list').on('dragleave drop', 'li.directory', function(event) {
    event.preventDefault();
    $(this).removeClass('drag-over');
  });

  $('#file-list').on('drop', 'li.directory', function() {
    const destinationName = $(this).data('name');
    const sourcePath = (currentFolder ? currentFolder + '/' : '') + draggedItemName;
    const destinationPath = (currentFolder ? currentFolder + '/' : '') + destinationName;

    $.ajax({
      url: '/move',
      method: 'POST',
      contentType: 'application/json',
      data: JSON.stringify({ source: sourcePath, destination_directory: destinationPath })
    }).always(refreshFileList);
  });
});
</script>
</body>
</html>
"""

# —— 路由定义 —— 

@app.route('/')
@auth.login_required
def home():
    return render_template_string(PAGE_TEMPLATE)

@app.route('/list')
@auth.login_required
def list_directory():
    relative_path = request.args.get('path', '')
    absolute_path = os.path.join(STORAGE_DIRECTORY, relative_path)
    entries = []
    for entry_name in sorted(os.listdir(absolute_path)):
        full_path = os.path.join(absolute_path, entry_name)
        entries.append({
            'name': entry_name,
            'isDirectory': os.path.isdir(full_path)
        })
    return jsonify(entries)

@app.route('/upload', methods=['POST'])
@auth.login_required
def upload_file():
    target_folder = request.form.get('path', '')
    file_object = request.files['file']
    destination_folder = os.path.join(STORAGE_DIRECTORY, target_folder)
    os.makedirs(destination_folder, exist_ok=True)
    file_object.save(os.path.join(destination_folder, file_object.filename))
    return '', 204

@app.route('/mkdir', methods=['POST'])
@auth.login_required
def make_directory():
    data = request.get_json()
    new_folder_path = os.path.join(STORAGE_DIRECTORY, data.get('path', ''), data['folder_name'])
    os.makedirs(new_folder_path, exist_ok=True)
    return '', 204

@app.route('/download')
@auth.login_required
def download_file():
    relative_path = request.args.get('path', '')
    directory, filename = os.path.split(relative_path)
    return send_from_directory(
        os.path.join(STORAGE_DIRECTORY, directory),
        filename,
        as_attachment=True
    )

@app.route('/delete', methods=['POST'])
@auth.login_required
def delete_entry():
    data = request.get_json()
    target_path = os.path.join(STORAGE_DIRECTORY, data['path'])
    if os.path.isdir(target_path):
        shutil.rmtree(target_path)
    else:
        os.remove(target_path)
    return '', 204

@app.route('/rename', methods=['POST'])
@auth.login_required
def rename_entry():
    data = request.get_json()
    source_path = os.path.join(STORAGE_DIRECTORY, data['path'])
    parent_directory, _ = os.path.split(source_path)
    new_path = os.path.join(parent_directory, data['new_name'])
    os.rename(source_path, new_path)
    return '', 204

@app.route('/move', methods=['POST'])
@auth.login_required
def move_entry():
    data = request.get_json()
    source_path = os.path.join(STORAGE_DIRECTORY, data['source'])
    destination_folder = os.path.join(STORAGE_DIRECTORY, data['destination_directory'])
    os.makedirs(destination_folder, exist_ok=True)
    shutil.move(source_path, os.path.join(destination_folder, os.path.basename(source_path)))
    return '', 204

if __name__ == '__main__':
    app.run(debug=True)
