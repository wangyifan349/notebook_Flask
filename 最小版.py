from flask import Flask, request, send_from_directory, jsonify, abort, render_template_string
from flask_httpauth import HTTPBasicAuth
import os
import shutil

# ----------------------------------------------------------------------------------------------------------------------
# 配置：应用与认证
# ----------------------------------------------------------------------------------------------------------------------

app = Flask(__name__)
auth = HTTPBasicAuth()

# 基本用户名/密码对，可替换为数据库或外部存储
USERS = {
    "admin": "secret",
}

@auth.verify_password
def verify_password(username, password):
    """
    验证用户名和密码是否匹配。
    """
    if username in USERS and USERS[username] == password:
        return username
    return None

# 根存储目录（所有上传的文件与文件夹都在此目录下）
BASE_DIR = os.path.abspath('uploads')
os.makedirs(BASE_DIR, exist_ok=True)

def safe_path(rel_path: str) -> str:
    """
    将用户传入的相对路径转换为 BASE_DIR 下的绝对路径。
    防止路径遍历攻击（..）。
    """
    # 计算绝对路径
    full_path = os.path.abspath(os.path.join(BASE_DIR, rel_path or ''))
    # 检查是否仍在 BASE_DIR 之内
    if not full_path.startswith(BASE_DIR):
        abort(400, description="Invalid path")
    return full_path

# ----------------------------------------------------------------------------------------------------------------------
# 路由：前端页面
# ----------------------------------------------------------------------------------------------------------------------

@app.route('/')
@auth.login_required
def index():
    """
    主页面：展示文件列表与操作按钮，前端通过 Fetch API 与后端路由交互。
    使用 Bootstrap 5 美化界面。
    """
    return render_template_string(r'''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>文件管理器</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    .file-item { cursor: pointer; }
    .folder { font-weight: bold; }
    .actions > button { margin-right: 5px; }
  </style>
</head>
<body class="p-4">
  <div class="container">
    <h1 class="mb-4">文件管理器</h1>
    <div class="mb-3 actions">
      <button class="btn btn-secondary" onclick="goUp()">⬆️ 上级目录</button>
      <span id="current-path">/</span>
      <input type="file" id="file-input" class="form-control d-inline-block w-auto ms-3">
      <button class="btn btn-primary" onclick="uploadFile()">上传</button>
      <button class="btn btn-success" onclick="createFolder()">新建文件夹</button>
    </div>
    <ul id="file-list" class="list-group"></ul>
  </div>

  <script>
    let currentPath = '';

    // 初始化：加载文件列表
    window.onload = refreshList;

    // 刷新当前目录的文件/文件夹列表
    function refreshList() {
      fetch(`/api/list?path=${encodeURIComponent(currentPath)}`)
        .then(res => res.json())
        .then(data => {
          document.getElementById('current-path').textContent = '/' + data.path;
          const list = document.getElementById('file-list');
          list.innerHTML = '';
          data.items.forEach(item => {
            const li = document.createElement('li');
            li.className = 'list-group-item d-flex justify-content-between align-items-center file-item';
            // 文件夹名称加粗
            li.innerHTML = `
              <span class="${item.is_dir ? 'folder' : ''}">${item.name}</span>
              <div>
                <button class="btn btn-sm btn-outline-danger me-1" onclick="deleteItem('${item.name}')">删除</button>
              </div>
            `;
            // 双击：进入文件夹 / 下载文件
            li.ondblclick = () => {
              if (item.is_dir) {
                currentPath = data.path ? data.path + '/' + item.name : item.name;
                refreshList();
              } else {
                window.location = `/api/download?path=${encodeURIComponent(currentPath + '/' + item.name)}`;
              }
            };
            list.appendChild(li);
          });
        });
    }

    // 上传文件到当前目录
    function uploadFile() {
      const fileInput = document.getElementById('file-input');
      if (!fileInput.files.length) return alert('请选择文件');
      const form = new FormData();
      form.append('file', fileInput.files[0]);
      form.append('path', currentPath);
      fetch('/api/upload', { method: 'POST', body: form })
        .then(() => { fileInput.value = ''; refreshList(); });
    }

    // 在当前目录创建新文件夹
    function createFolder() {
      const name = prompt('输入文件夹名称：');
      if (!name) return;
      const form = new FormData();
      form.append('path', currentPath);
      form.append('name', name);
      fetch('/api/mkdir', { method: 'POST', body: form })
        .then(refreshList);
    }

    // 删除文件或空文件夹
    function deleteItem(name) {
      fetch('/api/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: currentPath + '/' + name })
      }).then(refreshList);
    }

    // 返回上级目录
    function goUp() {
      if (!currentPath) return;
      const parts = currentPath.split('/');
      parts.pop();
      currentPath = parts.join('/');
      refreshList();
    }
  </script>
</body>
</html>
    ''')

# ----------------------------------------------------------------------------------------------------------------------
# 路由：API 接口
# 所有接口均在 /api 前缀下，并添加登录认证
# ----------------------------------------------------------------------------------------------------------------------

@app.route('/api/list', methods=['GET'])
@auth.login_required
def api_list():
    """
    列出目录内容
    请求参数: path (可选) — 相对路径，例如 "subdir" 或 "subdir/nested"
    返回 JSON:
      {
        "path": 当前相对路径,
        "items": [
          {"name": 文件或文件夹名, "is_dir": true/false},
          ...
        ]
      }
    """
    rel = request.args.get('path', '')
    directory = safe_path(rel)
    entries = []
    for name in sorted(os.listdir(directory)):
        full = os.path.join(directory, name)
        entries.append({'name': name, 'is_dir': os.path.isdir(full)})
    return jsonify({'path': rel, 'items': entries})

@app.route('/api/upload', methods=['POST'])
@auth.login_required
def api_upload():
    """
    上传文件
    表单字段: file — 上传文件; path (可选) — 相对目标目录
    成功返回 204 No Content
    """
    rel = request.form.get('path', '')
    target_dir = safe_path(rel)
    uploaded = request.files.get('file')
    if not uploaded:
        abort(400, description="No file provided")
    uploaded.save(os.path.join(target_dir, uploaded.filename))
    return ('', 204)

@app.route('/api/download', methods=['GET'])
@auth.login_required
def api_download():
    """
    下载文件
    请求参数: path — 相对文件路径，例如 "subdir/file.txt"
    使用 send_from_directory 发送附件
    """
    rel = request.args.get('path', '')
    directory, filename = os.path.split(rel)
    return send_from_directory(safe_path(directory), filename, as_attachment=True)

@app.route('/api/mkdir', methods=['POST'])
@auth.login_required
def api_mkdir():
    """
    创建文件夹
    表单字段: path (可选) — 父目录; name — 新文件夹名称
    成功返回 204 No Content
    """
    rel = request.form.get('path', '')
    name = request.form.get('name')
    if not name:
        abort(400, description="Folder name required")
    os.makedirs(os.path.join(safe_path(rel), name), exist_ok=True)
    return ('', 204)

@app.route('/api/delete', methods=['POST'])
@auth.login_required
def api_delete():
    """
    删除文件或空文件夹
    JSON 请求体: { "path": 相对路径 }
    成功返回 204 No Content
    """
    data = request.get_json() or {}
    rel = data.get('path', '')
    target = safe_path(rel)
    if os.path.isdir(target):
        os.rmdir(target)
    else:
        os.remove(target)
    return ('', 204)

@app.route('/api/move', methods=['POST'])
@auth.login_required
def api_move():
    """
    移动/重命名文件或文件夹
    JSON 请求体: { "src": 源相对路径, "dst": 目标目录相对路径 }
    将 src 移到 dst 目录下，保持名称不变
    成功返回 204 No Content
    """
    data = request.get_json() or {}
    src = safe_path(data.get('src', ''))
    dst_dir = safe_path(data.get('dst', ''))
    shutil.move(src, os.path.join(dst_dir, os.path.basename(src)))
    return ('', 204)

# ----------------------------------------------------------------------------------------------------------------------
# 启动应用
# ----------------------------------------------------------------------------------------------------------------------

if __name__ == '__main__':
    app.run(debug=True)
