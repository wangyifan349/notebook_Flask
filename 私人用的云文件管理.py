import os
from flask import Flask, request, jsonify, send_from_directory, abort, Response
from flask_httpauth import HTTPBasicAuth

app = Flask(__name__)
auth = HTTPBasicAuth()

# ----------------------------------------
# Configuration and User Authentication
# ----------------------------------------
# Simple in-memory user store. Replace with a real backend as needed.
USER_CREDENTIALS = {
    "admin": "secret123",
    "user": "passwd456"
}

@auth.verify_password
def verify_password(username, password):
    """
    Verify username and password for HTTP Basic Auth.
    Returns the username if valid, else None.
    """
    if username in USER_CREDENTIALS and USER_CREDENTIALS[username] == password:
        return username

# Directory where files and folders are stored
STORAGE_ROOT = os.path.abspath("storage")
os.makedirs(STORAGE_ROOT, exist_ok=True)

def secure_path(relative_path=""):
    """
    Resolve and sanitize a relative path under STORAGE_ROOT.
    Prevents directory traversal attacks.
    """
    absolute = os.path.normpath(os.path.join(STORAGE_ROOT, relative_path))
    if not absolute.startswith(STORAGE_ROOT):
        abort(400, "Invalid path")
    return absolute

# ----------------------------------------
# Main Page (Frontend + Embedded JS/CSS)
# ----------------------------------------
@app.route("/")
@auth.login_required
def home():
    """
    Serve the single-page file manager application.
    Embeds HTML, CSS, and JavaScript in one response.
    """
    html = """
<!DOCTYPE html>
<html lang="zh">
<head>
  <meta charset="UTF-8">
  <title>Flask File Manager</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    :root {
      --bg-light-green: #eafaf1;
      --bg-light-red:   #fde8e9;
      --btn-hover: rgba(0,0,0,0.05);
      --transition: all 0.15s ease-in-out;
    }
    body {
      font-family: "Segoe UI", Tahoma, sans-serif;
      margin: 0; padding: 20px;
      background-color: var(--bg-light-green);
      transition: var(--transition);
    }
    body.theme-red { background-color: var(--bg-light-red); }
    #toolbar .btn {
      transition: var(--transition);
    }
    #toolbar .btn:hover {
      background-color: var(--btn-hover);
      transform: translateY(-1px);
    }
    #pathDisplay {
      font-weight: 500; margin-bottom: 12px; color: #444;
    }
    #fileTree ul { list-style: none; padding-left: 20px; }
    #fileTree li {
      margin: 6px 0; cursor: pointer;
      padding: 4px 8px; border-radius: 4px;
      transition: var(--transition);
    }
    #fileTree li:hover {
      background-color: var(--btn-hover);
    }
    .folder::before { content: "📁 "; }
    .file::before   { content: "📄 "; }
    #contextMenu {
      position: absolute; display: none; z-index: 1000;
      background: #fff; border: 1px solid #ccc;
      border-radius: 4px; box-shadow: 0 2px 6px rgba(0,0,0,0.1);
    }
    #contextMenu button {
      display: block; width: 100%; border: none;
      background: none; padding: 8px 16px; text-align: left;
      transition: var(--transition);
    }
    #contextMenu button:hover {
      background-color: var(--btn-hover);
    }
  </style>
</head>
<body>
  <!-- Toolbar with primary actions -->
  <div id="toolbar" class="d-flex mb-3">
    <button id="btnUp" class="btn btn-outline-primary me-2" title="Go Up">
      <i class="bi bi-arrow-up"></i> 上级
    </button>
    <button id="btnNewFolder" class="btn btn-outline-success me-2">
      <i class="bi bi-folder-plus"></i> 新建文件夹
    </button>
    <button id="btnUpload" class="btn btn-outline-info me-2">
      <i class="bi bi-upload"></i> 上传
    </button>
    <input type="file" id="fileInput" multiple style="display:none">
    <div class="ms-auto">
      <button id="themeGreen" class="btn btn-sm btn-success me-1">淡绿</button>
      <button id="themeRed" class="btn btn-sm btn-danger">淡红</button>
    </div>
  </div>

  <!-- Current path display -->
  <div id="pathDisplay">/</div>

  <!-- File and folder tree -->
  <div id="fileTree" class="border bg-white p-3 rounded"></div>

  <!-- Custom context menu -->
  <div id="contextMenu">
    <button data-action="delete">删除</button>
    <button data-action="rename">重命名</button>
    <button data-action="move">移动</button>
  </div>

  <!-- Bootstrap Icons (for toolbar icons) -->
  <script src="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.10.5/font/bootstrap-icons.js"></script>
  <script>
    // ----------------------------------------
    // Frontend Logic (JavaScript)
    // ----------------------------------------
    let currentPath = "";
    let contextItem = null;

    // Element bindings
    document.getElementById("btnUp").onclick        = navigateUp;
    document.getElementById("btnNewFolder").onclick = createFolder;
    document.getElementById("btnUpload").onclick    = () => fileInput.click();
    document.getElementById("fileInput").onchange   = uploadFiles;
    document.getElementById("themeGreen").onclick   = () => setTheme('green');
    document.getElementById("themeRed").onclick     = () => setTheme('red');
    window.addEventListener('click', hideContextMenu);
    document.getElementById("contextMenu")
            .addEventListener('click', onContextAction);

    // Toggle between green and red background themes
    function setTheme(color) {
      document.body.classList.toggle('theme-red', color === 'red');
    }

    // Fetch directory listing from backend
    function fetchDirectory() {
      fetch(`/api/list?path=${encodeURIComponent(currentPath)}`)
        .then(res => res.json())
        .then(renderFileTree);
      document.getElementById("pathDisplay").textContent = "/" + currentPath;
    }

    // Render file/folder list as nested UL
    function renderFileTree(items) {
      const container = document.getElementById("fileTree");
      container.innerHTML = "";
      const ul = document.createElement("ul");

      items.forEach(item => {
        const li = document.createElement("li");
        li.textContent = item.name;
        li.className = item.is_dir ? "folder" : "file";
        li.draggable = true;

        // Click to navigate or download
        li.onclick = e => {
          e.stopPropagation();
          if (item.is_dir) {
            currentPath += item.name + "/";
            fetchDirectory();
          } else {
            window.open(`/api/download?path=${encodeURIComponent(currentPath + item.name)}`);
          }
        };

        // Drag & drop to move items
        li.ondragstart = e => {
          e.dataTransfer.setData("text/plain", currentPath + item.name);
        };
        li.ondragover = e => item.is_dir && e.preventDefault();
        li.ondrop = e => {
          if (item.is_dir) {
            const source = e.dataTransfer.getData("text/plain");
            sendMoveRequest(source, currentPath + item.name + "/");
          }
        };

        // Right-click context menu
        li.addEventListener('contextmenu', e => {
          e.preventDefault();
          contextItem = item;
          showContextMenu(e.pageX, e.pageY);
        });

        ul.appendChild(li);
      });

      container.appendChild(ul);
    }

    // Show custom context menu at x,y
    function showContextMenu(x, y) {
      const menu = document.getElementById("contextMenu");
      menu.style.top = y + "px";
      menu.style.left = x + "px";
      menu.style.display = "block";
    }

    // Hide context menu
    function hideContextMenu() {
      document.getElementById("contextMenu").style.display = "none";
    }

    // Handle context menu actions
    function onContextAction(e) {
      const action = e.target.dataset.action;
      if (!action) return;
      const name = contextItem.name;
      const isDir = contextItem.is_dir;
      const fullPath = currentPath + name + (isDir ? "/" : "");
      hideContextMenu();
      if (action === "delete")   deleteEntry(fullPath);
      if (action === "rename")   renameEntry(fullPath);
      if (action === "move")     moveEntry(fullPath);
    }

    // Navigate up one directory
    function navigateUp() {
      if (!currentPath) return;
      currentPath = currentPath.split("/").filter(Boolean).slice(0, -1).join("/") + "/";
      fetchDirectory();
    }

    // Create a new folder
    function createFolder() {
      const folderName = prompt("请输入文件夹名称：");
      if (!folderName) return;
      fetch("/api/mkdir", {
        method: "POST",
        headers: {"Content-Type":"application/json"},
        body: JSON.stringify({path: currentPath, name: folderName})
      }).then(fetchDirectory);
    }

    // Upload selected files
    function uploadFiles() {
      const input = document.getElementById("fileInput");
      const form = new FormData();
      Array.from(input.files).forEach(f => form.append("files", f));
      form.append("path", currentPath);
      fetch("/api/upload", {method:"POST", body: form})
        .then(() => { input.value=""; fetchDirectory(); });
    }

    // Delete a file or folder
    function deleteEntry(path) {
      fetch("/api/delete", {
        method:"POST",
        headers: {"Content-Type":"application/json"},
        body: JSON.stringify({path})
      }).then(fetchDirectory);
    }

    // Rename a file or folder
    function renameEntry(path) {
      const newName = prompt("新名称：", path.split("/").pop());
      if (!newName) return;
      fetch("/api/rename", {
        method:"POST",
        headers: {"Content-Type":"application/json"},
        body: JSON.stringify({path, new_name: newName})
      }).then(fetchDirectory);
    }

    // Move a file or folder via prompt
    function moveEntry(path) {
      const destination = prompt("目标目录 (相对路径)：", currentPath);
      if (destination == null) return;
      sendMoveRequest(path, destination);
    }

    // Send move request to backend
    function sendMoveRequest(src, dst) {
      fetch("/api/move", {
        method:"POST",
        headers: {"Content-Type":"application/json"},
        body: JSON.stringify({src, dst})
      }).then(fetchDirectory);
    }

    window.onload = fetchDirectory;
  </script>
</body>
</html>
    """
    return Response(html, mimetype="text/html")

# ----------------------------------------
# API Endpoints (File Operations)
# ----------------------------------------

@app.route("/api/list", methods=["GET"])
@auth.login_required
def list_directory():
    """
    Return JSON list of entries (files/directories) for a given path.
    """
    rel = request.args.get("path", "")
    root = secure_path(rel)
    entries = []
    for name in os.listdir(root):
        path = os.path.join(root, name)
        entries.append({"name": name, "is_dir": os.path.isdir(path)})
    return jsonify(entries)

# ----------------------------------------

@app.route("/api/upload", methods=["POST"])
@auth.login_required
def upload_files():
    """
    Save uploaded files to the specified directory.
    """
    rel = request.form.get("path", "")
    dest = secure_path(rel)
    for f in request.files.getlist("files"):
        f.save(os.path.join(dest, f.filename))
    return jsonify(success=True)

# ----------------------------------------

@app.route("/api/download", methods=["GET"])
@auth.login_required
def download_file():
    """
    Serve a file download. Reject if it's a directory.
    """
    rel = request.args.get("path")
    full = secure_path(rel)
    if os.path.isdir(full):
        abort(400, "Cannot download a directory")
    return send_from_directory(STORAGE_ROOT, rel, as_attachment=True)

# ----------------------------------------

@app.route("/api/delete", methods=["POST"])
@auth.login_required
def delete_entry():
    """
    Delete a file or empty directory.
    """
    rel = request.json.get("path")
    full = secure_path(rel)
    if os.path.isdir(full):
        os.rmdir(full)
    else:
        os.remove(full)
    return jsonify(success=True)

# ----------------------------------------

@app.route("/api/rename", methods=["POST"])
@auth.login_required
def rename_entry():
    """
    Rename a file or directory.
    """
    rel = request.json.get("path")
    new_name = request.json.get("new_name")
    src = secure_path(rel)
    dst = os.path.join(os.path.dirname(src), new_name)
    os.rename(src, dst)
    return jsonify(success=True)

# ----------------------------------------

@app.route("/api/mkdir", methods=["POST"])
@auth.login_required
def make_directory():
    """
    Create a new directory under the specified path.
    """
    rel = request.json.get("path", "")
    name = request.json.get("name")
    target = os.path.join(secure_path(rel), name)
    os.makedirs(target, exist_ok=True)
    return jsonify(success=True)

# ----------------------------------------

@app.route("/api/move", methods=["POST"])
@auth.login_required
def move_entry():
    """
    Move (or rename) a file or directory to a new location.
    """
    src = secure_path(request.json.get("src"))
    dst = secure_path(request.json.get("dst"))
    os.rename(src, os.path.join(dst, os.path.basename(src)))
    return jsonify(success=True)

# ----------------------------------------
# Application Runner
# ----------------------------------------
if __name__ == "__main__":
    app.run(debug=True)
