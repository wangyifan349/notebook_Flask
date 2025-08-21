#!/usr/bin/env python3
import os
import re
import time
import shutil
from pathlib import Path
from threading import Thread
from flask import Flask, request, jsonify, abort, send_from_directory, Response, stream_with_context

# --- Configuration ---
APP_ROOT = Path(os.environ.get("FILES_ROOT", "/srv/files")).resolve()
API_KEY = os.environ.get("ADMIN_API_KEY", "changeme")
MAX_CONTENT_LENGTH = int(os.environ.get("MAX_CONTENT_LENGTH", 200 * 1024 * 1024))  # default 200MB
ALLOWED_EXT = None  # set to e.g. {'txt','png','jpg'} to restrict uploads
EDITABLE_EXT = {'.txt', '.md', '.py', '.json', '.csv', '.ini', '.cfg', '.log', '.html', '.css', '.js'}

os.makedirs(APP_ROOT, exist_ok=True)

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH

# --- Helpers ---
def check_auth():
    key = request.headers.get("X-API-KEY")
    if API_KEY and key != API_KEY:
        abort(401, "Unauthorized")

def safe_path(rel_path: str) -> Path:
    # normalize empty path
    rel_path = rel_path or ""
    # prevent leading slash trick
    rel_path = rel_path.lstrip("/")
    target = (APP_ROOT / rel_path).resolve()
    if not str(target).startswith(str(APP_ROOT)):
        abort(400, "Invalid path")
    return target

def allowed_file(filename: str) -> bool:
    if not ALLOWED_EXT:
        return True
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    return ext in ALLOWED_EXT

def secure_filename_basic(filename: str) -> str:
    # keep werkzeug's secure_filename behavior if available
    try:
        from werkzeug.utils import secure_filename
        return secure_filename(filename)
    except Exception:
        return re.sub(r'[^A-Za-z0-9._-]', '_', filename)

def make_versions_backup(target: Path):
    if not target.exists():
        return None
    rel = target.relative_to(APP_ROOT)
    vs_dir = APP_ROOT / 'versions' / rel.parent
    vs_dir.mkdir(parents=True, exist_ok=True)
    ts = int(time.time())
    backup_name = f"{target.name}.{ts}.bak"
    backup_path = vs_dir / backup_name
    shutil.copy2(str(target), str(backup_path))
    return backup_path

# --- Routes ---
@app.route("/list/", defaults={"rel_path": ""}, methods=["GET"])
@app.route("/list/<path:rel_path>", methods=["GET"])
def list_dir(rel_path):
    target = safe_path(rel_path)
    if not target.exists() or not target.is_dir():
        return jsonify({"error": "not found or not a directory"}), 404
    items = []
    for p in sorted(target.iterdir()):
        stat = p.stat()
        items.append({
            "name": p.name,
            "is_dir": p.is_dir(),
            "size": stat.st_size,
            "mtime": int(stat.st_mtime)
        })
    return jsonify({"path": str(Path(rel_path)), "items": items})

@app.route("/download/<path:rel_path>", methods=["GET"])
def download(rel_path):
    target = safe_path(rel_path)
    if not target.exists() or not target.is_file():
        return jsonify({"error": "file not found"}), 404
    return send_from_directory(directory=str(target.parent), filename=target.name, as_attachment=True)

@app.route("/media/<path:rel_path>", methods=["GET"])
def media(rel_path):
    target = safe_path(rel_path)
    if not target.exists() or not target.is_file():
        return jsonify({'error': 'not found'}), 404
    file_size = target.stat().st_size
    range_header = request.headers.get('Range', None)
    if not range_header:
        return send_from_directory(directory=str(target.parent), filename=target.name, as_attachment=False)
    m = re.match(r'bytes=(\d+)-(\d*)', range_header)
    if not m:
        return Response(status=416)
    start = int(m.group(1))
    end = int(m.group(2)) if m.group(2) else file_size - 1
    if start >= file_size:
        return Response(status=416)
    if end >= file_size:
        end = file_size - 1
    length = end - start + 1

    def generate(path, start_pos, to_read):
        with open(path, 'rb') as f:
            f.seek(start_pos)
            remaining = to_read
            chunk = 8192
            while remaining > 0:
                read_len = min(chunk, remaining)
                data = f.read(read_len)
                if not data:
                    break
                yield data
                remaining -= len(data)

    import mimetypes
    ctype = mimetypes.guess_type(str(target))[0] or 'application/octet-stream'
    rv = Response(stream_with_context(generate(str(target), start, length)),
                  status=206,
                  mimetype=ctype,
                  direct_passthrough=True)
    rv.headers.add('Content-Range', f'bytes {start}-{end}/{file_size}')
    rv.headers.add('Accept-Ranges', 'bytes')
    rv.headers.add('Content-Length', str(length))
    return rv

@app.route("/upload/<path:rel_path>", methods=["POST"])
def upload(rel_path):
    check_auth()
    target_dir = safe_path(rel_path)
    if not target_dir.exists() or not target_dir.is_dir():
        return jsonify({"error": "target directory not found"}), 404
    if 'file' not in request.files:
        return jsonify({"error": "no file part"}), 400
    f = request.files['file']
    if f.filename == "":
        return jsonify({"error": "empty filename"}), 400
    filename = secure_filename_basic(f.filename)
    if not allowed_file(filename):
        return jsonify({"error": "file type not allowed"}), 400
    dest = target_dir / filename
    f.save(str(dest))
    return jsonify({"saved": str(dest.relative_to(APP_ROOT))}), 201

@app.route("/overwrite_upload/<path:rel_path>", methods=["POST"])
def overwrite_upload(rel_path):
    check_auth()
    target = safe_path(rel_path)
    parent = target.parent
    if 'file' not in request.files:
        return jsonify({"error": "no file part"}), 400
    f = request.files['file']
    if f.filename == "":
        return jsonify({"error": "empty filename"}), 400
    filename = secure_filename_basic(f.filename)
    if filename != target.name:
        # allow specifying different filename but save into same parent
        dest = parent / filename
    else:
        dest = target
    if not allowed_file(filename):
        return jsonify({"error": "file type not allowed"}), 400
    parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        make_versions_backup(dest)
    f.save(str(dest))
    return jsonify({"saved": str(dest.relative_to(APP_ROOT))}), 201

@app.route("/create_dir/<path:rel_path>", methods=["POST"])
def create_dir(rel_path):
    check_auth()
    target = safe_path(rel_path)
    try:
        target.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        return jsonify({"error": "already exists"}), 409
    return jsonify({"created": str(target.relative_to(APP_ROOT))}), 201

@app.route("/delete_file/<path:rel_path>", methods=["DELETE"])
def delete_file(rel_path):
    check_auth()
    target = safe_path(rel_path)
    if not target.exists() or not target.is_file():
        return jsonify({"error": "file not found"}), 404
    make_versions_backup(target)
    target.unlink()
    return jsonify({"deleted": str(target.relative_to(APP_ROOT))})

@app.route("/delete_dir/<path:rel_path>", methods=["DELETE"])
def delete_dir(rel_path):
    check_auth()
    target = safe_path(rel_path)
    if not target.exists() or not target.is_dir():
        return jsonify({"error": "dir not found"}), 404
    try:
        target.rmdir()
    except OSError:
        return jsonify({"error": "directory not empty"}), 400
    return jsonify({"deleted": str(target.relative_to(APP_ROOT))})

@app.route("/move_or_rename", methods=["POST"])
def move_or_rename():
    check_auth()
    data = request.json or {}
    src = data.get("src")
    dst = data.get("dst")
    if not src or not dst:
        return jsonify({"error": "src and dst required"}), 400
    srcp = safe_path(src)
    dstp = safe_path(dst)
    if not srcp.exists():
        return jsonify({"error": "src not found"}), 404
    dstp.parent.mkdir(parents=True, exist_ok=True)
    if dstp.exists():
        make_versions_backup(dstp)
    shutil.move(str(srcp), str(dstp))
    return jsonify({"moved": f"{src} -> {dst}"})

@app.route("/edit/<path:rel_path>", methods=["GET"])
def edit_get(rel_path):
    target = safe_path(rel_path)
    if not target.exists() or not target.is_file():
        return jsonify({'error': 'not found'}), 404
    if target.suffix.lower() not in EDITABLE_EXT:
        return jsonify({'error': 'not editable'}), 400
    try:
        text = target.read_text(encoding='utf-8')
    except Exception:
        text = target.read_text(encoding='utf-8', errors='replace')
    return jsonify({'path': str(target.relative_to(APP_ROOT)), 'content': text})

@app.route("/edit/<path:rel_path>", methods=["POST"])
def edit_save(rel_path):
    check_auth()
    data = request.json or {}
    content = data.get('content')
    if content is None:
        return jsonify({'error': 'content required'}), 400
    target = safe_path(rel_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        make_versions_backup(target)
    # write atomically
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(content, encoding='utf-8')
    tmp.replace(target)
    return jsonify({'saved': str(target.relative_to(APP_ROOT))})

@app.route("/versions/<path:rel_path>", methods=["GET"])
def list_versions(rel_path):
    # list backups for a given file relative path
    target = safe_path(rel_path)
    rel = target.relative_to(APP_ROOT)
    vs_dir = APP_ROOT / 'versions' / rel.parent
    if not vs_dir.exists():
        return jsonify({'versions': []})
    out = []
    for p in sorted(vs_dir.iterdir()):
        if p.name.startswith(target.name + ".") and p.suffix == ".bak":
            out.append({'name': p.name, 'path': str(p.relative_to(APP_ROOT)), 'mtime': int(p.stat().st_mtime), 'size': p.stat().st_size})
    return jsonify({'versions': out})

@app.route("/restart", methods=["POST"])
def restart():
    check_auth()
    def _exit():
        time.sleep(0.5)
        os._exit(3)
    Thread(target=_exit).start()
    return jsonify({"restarting": True}), 202

# Basic health
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "root": str(APP_ROOT)})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)



  <!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>文件管理器（支持右键/拖拽/在线编辑/在线播放）</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    body { padding: 12px; }
    #file-list { max-height: 72vh; overflow:auto; border:1px solid #dee2e6; border-radius:4px; padding:6px; }
    .file-item { padding:8px; margin-bottom:4px; border-radius:4px; display:flex; justify-content:space-between; align-items:center; cursor:grab; }
    .file-item.dragging { opacity:0.5; }
    .dir { font-weight:600; color:#0d6efd; }
    #editor { height: 60vh; width:100%; font-family: monospace; white-space: pre; }
    .context-menu { position: absolute; z-index: 2000; background:#fff; border:1px solid #ccc; box-shadow:0 2px 6px rgba(0,0,0,0.15); border-radius:4px; padding:4px 0; }
    .context-menu button { display:block; width:200px; border:none; background:transparent; padding:6px 12px; text-align:left; }
    .context-menu button:hover { background:#f8f9fa; }
    .drop-target { outline: 2px dashed rgba(13,110,253,0.5); }
  </style>
</head>
<body>
<div class="container-fluid">
  <div class="row mb-2">
    <div class="col-8">
      <h4>文件管理器</h4>
    </div>
    <div class="col-4 text-end">
      <div class="input-group">
        <input id="apiKey" class="form-control" placeholder="X-API-KEY (修改类操作需提供)" />
        <button id="saveKey" class="btn btn-outline-secondary">保存</button>
      </div>
    </div>
  </div>

  <div class="row g-2">
    <div class="col-md-3">
      <div class="d-flex mb-2">
        <input id="currentPath" class="form-control me-2" placeholder="当前路径（空为根）" />
        <button id="upBtn" class="btn btn-outline-secondary me-1">上一级</button>
        <button id="refreshBtn" class="btn btn-primary">刷新</button>
      </div>

      <div class="mb-2 d-flex">
        <input id="newFolderName" class="form-control me-2" placeholder="新建文件夹名或文件名(含扩展名)" />
        <button id="createBtn" class="btn btn-success">创建</button>
      </div>

      <div class="mb-2">
        <label class="form-label small-muted">上传文件到当前目录</label>
        <input id="uploadFile" type="file" class="form-control" />
        <button id="uploadBtn" class="btn btn-sm btn-success mt-1">上传</button>
      </div>

      <div id="file-list" oncontextmenu="return false;">
        <!-- 列表项 -->
      </div>
    </div>

    <div class="col-md-6">
      <div id="viewer" class="border p-2" style="min-height:60vh;">
        <div id="mediaContainer" class="mb-2" style="display:none;">
          <video id="videoPlayer" controls style="max-width:100%; display:none;"></video>
          <audio id="audioPlayer" controls style="width:100%; display:none;"></audio>
        </div>

        <div id="textContainer" style="display:none;">
          <div class="d-flex mb-1">
            <button id="saveTextBtn" class="btn btn-primary btn-sm me-2">保存 (Ctrl+S)</button>
            <button id="revertTextBtn" class="btn btn-secondary btn-sm me-2">恢复上个版本</button>
            <select id="versionsSelect" class="form-select form-select-sm w-auto me-2"></select>
            <button id="loadVersionBtn" class="btn btn-outline-secondary btn-sm">加载版本</button>
          </div>
          <textarea id="editor" spellcheck="false"></textarea>
        </div>

        <div id="metaContainer" style="display:none;">
          <h6>文件信息</h6>
          <pre id="metaInfo" class="small"></pre>
        </div>

        <div id="emptyHint" class="text-muted">选择左侧文件或目录以查看/编辑/播放。右键空白处可创建，右键文件可操作，支持拖拽移动。</div>
      </div>
    </div>

    <div class="col-md-3">
      <div class="card">
        <div class="card-body">
          <h6>操作</h6>
          <div class="mb-2">
            <input id="targetName" class="form-control mb-1" placeholder="重命名/移动 到（相对路径）" />
            <button id="renameBtn" class="btn btn-warning w-100">重命名 / 移动</button>
          </div>
          <div class="mb-2">
            <button id="downloadBtn" class="btn btn-outline-primary w-100 mb-1">下载</button>
            <button id="deleteBtn" class="btn btn-danger w-100">删除</button>
          </div>
          <hr>
          <h6>当前选择</h6>
          <div id="selectedInfo" class="small-muted">无</div>
        </div>
      </div>
    </div>
  </div>
</div>

<!-- context menu container -->
<div id="ctxMenu" class="context-menu" style="display:none;"></div>

<script>
const API_BASE = "/"; // 修改为后端地址（若不是根）
const MEDIA_ROUTE = API_BASE + "media/";
const LIST_ROUTE = API_BASE + "list/";
const DOWNLOAD_ROUTE = API_BASE + "download/";
const EDIT_ROUTE = API_BASE + "edit/";
const UPLOAD_ROUTE = API_BASE + "upload/";
const OVERWRITE_ROUTE = API_BASE + "overwrite_upload/";
const CREATE_DIR_ROUTE = API_BASE + "create_dir/";
const DELETE_FILE_ROUTE = API_BASE + "delete_file/";
const DELETE_DIR_ROUTE = API_BASE + "delete_dir/";
const MOVE_ROUTE = API_BASE + "move_or_rename";
const VERSIONS_ROUTE = API_BASE + "versions/";

let state = {
  currentPath: "",
  selected: null,
  apiKey: localStorage.getItem("apiKey") || ""
};

document.getElementById("apiKey").value = state.apiKey;
document.getElementById("saveKey").addEventListener("click", ()=>{
  state.apiKey = document.getElementById("apiKey").value.trim();
  localStorage.setItem("apiKey", state.apiKey);
  alert("已保存");
});

function headersWithAuth(extra={}) {
  const h = Object.assign({}, extra);
  if(state.apiKey) h["X-API-KEY"] = state.apiKey;
  return h;
}

function fmtTime(ts){ return new Date(ts*1000).toLocaleString(); }
function formatBytes(bytes){
  if(bytes===0) return "0 B";
  const k=1024; const sizes=['B','KB','MB','GB','TB'];
  const i=Math.floor(Math.log(bytes)/Math.log(k));
  return parseFloat((bytes/Math.pow(k,i)).toFixed(2)) + ' ' + sizes[i];
}

async function listCurrent() {
  const p = document.getElementById("currentPath").value.trim();
  state.currentPath = p;
  const url = LIST_ROUTE + (p ? encodeURIComponent(p) : "");
  const res = await fetch(url);
  if(!res.ok){ alert("列出失败"); return; }
  const data = await res.json();
  renderList(data.items || []);
  document.getElementById("emptyHint").style.display = "";
  clearViewer();
}

function renderList(items){
  const cont = document.getElementById("file-list");
  cont.innerHTML = "";
  // allow dropping on empty list (create in current dir)
  cont.addEventListener('dragover', ev=> ev.preventDefault());
  cont.addEventListener('drop', async ev=>{
    ev.preventDefault();
    const files = ev.dataTransfer.files;
    if(files && files.length){
      // upload files to currentPath
      for(const f of files){
        await uploadFileObject(f);
      }
      listCurrent();
    } else {
      // move via drag data
      const src = ev.dataTransfer.getData('text/plain');
      if(src){
        const dst = state.currentPath || "";
        await moveSrcToDst(src, dst);
        listCurrent();
      }
    }
  });

  // add clickable empty-space item for right-click
  const spacer = document.createElement("div");
  spacer.style.minHeight = "6px";
  cont.appendChild(spacer);

  items.forEach(it=>{
    const el = document.createElement("div");
    el.className = "file-item list-group-item";
    el.draggable = true;
    el.dataset.name = it.name;
    el.dataset.isDir = it.is_dir;
    el.innerHTML = `<div><span class="${it.is_dir? 'dir':''}">${it.name}</span><div class="small-muted">${it.is_dir ? '目录' : formatBytes(it.size)} · ${fmtTime(it.mtime)}</div></div>
                    <div><button class="btn btn-sm btn-outline-secondary btn-select">打开</button></div>`;
    // drag events
    el.addEventListener('dragstart', ev=>{
      el.classList.add('dragging');
      ev.dataTransfer.setData('text/plain', (state.currentPath ? state.currentPath + '/' + it.name : it.name));
    });
    el.addEventListener('dragend', ev=> el.classList.remove('dragging'));

    if(it.is_dir){
      el.addEventListener('dragover', ev=> { ev.preventDefault(); el.classList.add('drop-target'); });
      el.addEventListener('dragleave', ev=> { el.classList.remove('drop-target'); });
      el.addEventListener('drop', async ev=>{
        ev.preventDefault();
        el.classList.remove('drop-target');
        const src = ev.dataTransfer.getData('text/plain');
        if(src){
          const dst = (state.currentPath ? state.currentPath + '/' + it.name : it.name);
          await moveSrcToDst(src, dst);
          listCurrent();
        }
      });
    }

    el.querySelector('.btn-select').addEventListener('click', ()=> onSelectItem(it));
    el.addEventListener('contextmenu', ev=>{
      ev.preventDefault();
      showContextMenuForItem(it, ev.pageX, ev.pageY);
    });

    cont.appendChild(el);
  });

  // right-click on empty area to create
  cont.addEventListener('contextmenu', ev=>{
    // only trigger when clicking the container background (not on items)
    if(ev.target === cont || ev.target === spacer){
      ev.preventDefault();
      showContextMenuForEmpty(ev.pageX, ev.pageY);
    }
  });
}

function showContextMenuForEmpty(x,y){
  const menu = document.getElementById('ctxMenu');
  menu.innerHTML = '';
  const btnNewFolder = document.createElement('button');
  btnNewFolder.textContent = '新建文件夹';
  btnNewFolder.onclick = async ()=>{
    const name = prompt('输入新建文件夹名:');
    if(!name) return;
    const path = state.currentPath ? (state.currentPath + '/' + name) : name;
    const res = await fetch(CREATE_DIR_ROUTE + encodeURIComponent(path), {method:'POST', headers: headersWithAuth()});
    if(res.ok) listCurrent(); else alert('创建失败');
    hideContext();
  };
  const btnNewFile = document.createElement('button');
  btnNewFile.textContent = '新建记事本文件';
  btnNewFile.onclick = async ()=>{
    const name = prompt('输入文件名(含扩展名，如 note.txt):');
    if(!name) return;
    const path = state.currentPath ? (state.currentPath + '/' + name) : name;
    // create empty file via overwrite_upload with an empty blob using Fetch
    const form = new FormData();
    const blob = new Blob([''], {type:'text/plain'});
    form.append('file', blob, name);
    const res = await fetch(UPLOAD_ROUTE + encodeURIComponent(state.currentPath || ''), {method:'POST', headers: headersWithAuth(), body: form});
    if(res.ok) listCurrent(); else alert('创建失败');
    hideContext();
  };
  const btnRefresh = document.createElement('button');
  btnRefresh.textContent = '刷新';
  btnRefresh.onclick = ()=>{ listCurrent(); hideContext(); };

  menu.appendChild(btnNewFolder);
  menu.appendChild(btnNewFile);
  menu.appendChild(btnRefresh);
  showAt(menu, x, y);
}

function showContextMenuForItem(it,x,y){
  const menu = document.getElementById('ctxMenu');
  menu.innerHTML = '';
  const btnOpen = document.createElement('button');
  btnOpen.textContent = it.is_dir ? '打开目录' : '打开/预览';
  btnOpen.onclick = ()=>{ onSelectItem(it); hideContext(); };

  const btnDownload = document.createElement('button');
  btnDownload.textContent = '下载';
  btnDownload.onclick = ()=>{ const p = state.currentPath ? state.currentPath + '/' + it.name : it.name; window.open(DOWNLOAD_ROUTE + encodeURIComponent(p), '_blank'); hideContext(); };

  const btnRename = document.createElement('button');
  btnRename.textContent = '重命名/移动';
  btnRename.onclick = async ()=>{
    const dst = prompt('新的相对路径（例如 folder/newname.txt）:', state.currentPath ? (state.currentPath + '/' + it.name) : it.name);
    if(!dst) return;
    const src = state.currentPath ? (state.currentPath + '/' + it.name) : it.name;
    const res = await fetch(MOVE_ROUTE, {method:'POST', headers: Object.assign({'Content-Type':'application/json'}, headersWithAuth()), body: JSON.stringify({src,dst})});
    if(res.ok) listCurrent(); else alert('失败');
    hideContext();
  };

  const btnDelete = document.createElement('button');
  btnDelete.textContent = '删除';
  btnDelete.onclick = async ()=>{
    if(!confirm('确认删除?')) return;
    const p = state.currentPath ? state.currentPath + '/' + it.name : it.name;
    const url = it.is_dir ? (DELETE_DIR_ROUTE + encodeURIComponent(p)) : (DELETE_FILE_ROUTE + encodeURIComponent(p));
    const res = await fetch(url, {method:'DELETE', headers: headersWithAuth()});
    if(res.ok) listCurrent(); else alert('删除失败');
    hideContext();
  };

  menu.appendChild(btnOpen);
  menu.appendChild(btnDownload);
  menu.appendChild(btnRename);
  menu.appendChild(btnDelete);

  if(!it.is_dir){
    const lower = it.name.toLowerCase();
    if(lower.match(/\.(mp4|webm|ogg|mov|m4v|mp3|m4a|wav|flac)$/)){
      const btnPlay = document.createElement('button');
      btnPlay.textContent = '在线播放';
      btnPlay.onclick = ()=>{ onSelectItem(it); hideContext(); };
      menu.appendChild(btnPlay);
    }
    if(lower.match(/\.(txt|md|py|json|csv|ini|cfg|log|html|css|js)$/)){
      const btnEdit = document.createElement('button');
      btnEdit.textContent = '在线编辑';
      btnEdit.onclick = ()=>{ onSelectItem(it); hideContext(); };
      menu.appendChild(btnEdit);
    }
  }

  showAt(menu, x, y);
}

function showAt(menu, x, y){
  menu.style.left = x + 'px';
  menu.style.top = y + 'px';
  menu.style.display = '';
  document.addEventListener('click', hideContextOnce);
}
function hideContext(){
  const menu = document.getElementById('ctxMenu');
  menu.style.display = 'none';
  document.removeEventListener('click', hideContextOnce);
}
function hideContextOnce(e){
  hideContext();
  document.removeEventListener('click', hideContextOnce);
}

async function onSelectItem(it){
  state.selected = it;
  document.getElementById("selectedInfo").textContent = `${it.name} ${it.is_dir ? "(目录)" : formatBytes(it.size)}`;
  document.getElementById("emptyHint").style.display = "none";
  document.getElementById("metaContainer").style.display = "";
  document.getElementById("metaInfo").textContent = JSON.stringify(it, null, 2);
  document.getElementById("targetName").value = state.currentPath ? (state.currentPath + "/" + it.name) : it.name;

  if(it.is_dir){
    document.getElementById("currentPath").value = state.currentPath ? (state.currentPath + "/" + it.name) : it.name;
    await listCurrent();
    return;
  }

  const fullRel = (state.currentPath ? state.currentPath + "/" + it.name : it.name);
  const lower = it.name.toLowerCase();
  const isVideo = lower.match(/\.(mp4|webm|ogg|mov|m4v)$/);
  const isAudio = lower.match(/\.(mp3|m4a|wav|ogg|flac)$/);
  const isText = lower.match(/\.(txt|md|py|json|csv|ini|cfg|log|html|css|js)$/);

  if(isVideo){
    document.getElementById("mediaContainer").style.display = "";
    const v = document.getElementById("videoPlayer");
    v.style.display = "";
    v.src = MEDIA_ROUTE + encodeURIComponent(fullRel);
    v.load();
    document.getElementById("textContainer").style.display = "none";
  } else if(isAudio){
    document.getElementById("mediaContainer").style.display = "";
    const a = document.getElementById("audioPlayer");
    a.style.display = "";
    a.src = MEDIA_ROUTE + encodeURIComponent(fullRel);
    a.load();
    document.getElementById("textContainer").style.display = "none";
  } else if(isText){
    document.getElementById("textContainer").style.display = "";
    document.getElementById("mediaContainer").style.display = "none";
    await loadText(fullRel);
  } else {
    document.getElementById("mediaContainer").style.display = "none";
    document.getElementById("textContainer").style.display = "none";
  }
}

document.getElementById("refreshBtn").addEventListener("click", ()=>listCurrent());
document.getElementById("upBtn").addEventListener("click", ()=>{
  const cur = document.getElementById("currentPath").value.trim();
  if(!cur){ return; }
  const parts = cur.split('/').filter(x=>x);
  parts.pop();
  document.getElementById("currentPath").value = parts.join('/');
  listCurrent();
});

document.getElementById("createBtn").addEventListener("click", async ()=>{
  const name = document.getElementById("newFolderName").value.trim();
  if(!name){ alert("请输入名称"); return; }
  if(name.includes('.')) {
    // treat as file
    const parent = state.currentPath || "";
    const form = new FormData();
    const blob = new Blob([''], {type:'text/plain'});
    form.append('file', blob, name);
    const res = await fetch(UPLOAD_ROUTE + encodeURIComponent(parent), {method:'POST', headers: headersWithAuth(), body: form});
    if(res.ok){ listCurrent(); document.getElementById("newFolderName").value=''; } else alert('创建文件失败');
  } else {
    const path = state.currentPath ? (state.currentPath + '/' + name) : name;
    const res = await fetch(CREATE_DIR_ROUTE + encodeURIComponent(path), {method:'POST', headers: headersWithAuth()});
    if(res.ok){ listCurrent(); document.getElementById("newFolderName").value=''; } else alert('创建目录失败');
  }
});

document.getElementById("uploadBtn").addEventListener("click", async ()=>{
  const fileInput = document.getElementById("uploadFile");
  if(!fileInput.files.length){ alert("请选择文件"); return; }
  const file = fileInput.files[0];
  await uploadFileObject(file);
  fileInput.value = '';
  listCurrent();
});

async function uploadFileObject(file){
  const form = new FormData();
  form.append("file", file, file.name);
  const url = UPLOAD_ROUTE + encodeURIComponent(state.currentPath || "");
  const res = await fetch(url, {method:"POST", headers: headersWithAuth(), body: form});
  if(!res.ok){ const txt=await res.text(); alert("上传失败: "+txt); }
}

document.getElementById("downloadBtn").addEventListener("click", ()=>{
  if(!state.selected || state.selected.is_dir){ alert("请选择文件下载"); return; }
  const p = state.currentPath ? state.currentPath + "/" + state.selected.name : state.selected.name;
  const url = DOWNLOAD_ROUTE + encodeURIComponent(p);
  window.open(url, "_blank");
});

document.getElementById("deleteBtn").addEventListener("click", async ()=>{
  if(!state.selected){ alert("请选择项"); return; }
  if(!confirm("确认删除?")) return;
  const p = state.currentPath ? state.currentPath + "/" + state.selected.name : state.selected.name;
  const url = state.selected.is_dir ? (DELETE_DIR_ROUTE + encodeURIComponent(p)) : (DELETE_FILE_ROUTE + encodeURIComponent(p));
  const res = await fetch(url, {method:"DELETE", headers: headersWithAuth()});
  if(res.ok){ alert("删除成功"); listCurrent(); clearViewer(); } else { alert("删除失败"); }
});

document.getElementById("renameBtn").addEventListener("click", async ()=>{
  if(!state.selected){ alert("请选择项"); return; }
  const dst = document.getElementById("targetName").value.trim();
  if(!dst){ alert("目标名不能为空"); return; }
  const src = state.currentPath ? (state.currentPath + "/" + state.selected.name) : state.selected.name;
  const body = {src: src, dst: dst};
  const res = await fetch(MOVE_ROUTE, {method:"POST", headers: Object.assign({"Content-Type":"application/json"}, headersWithAuth()), body: JSON.stringify(body)});
  if(res.ok){ alert("已移动/重命名"); listCurrent(); } else { alert("失败"); }
});

// editing
async function loadText(fullRel) {
  const url = EDIT_ROUTE + encodeURIComponent(fullRel);
  const res = await fetch(url);
  if(!res.ok){ alert("打开失败"); return; }
  const data = await res.json();
  document.getElementById("editor").value = data.content || "";
  loadVersions(fullRel);
}

document.getElementById("saveTextBtn").addEventListener("click", ()=>saveText());
async function saveText(){
  if(!state.selected){ alert("未选择文件"); return; }
  const fullRel = state.currentPath ? state.currentPath + "/" + state.selected.name : state.selected.name;
  const content = document.getElementById("editor").value;
  const res = await fetch(EDIT_ROUTE + encodeURIComponent(fullRel), {method:"POST", headers: Object.assign({"Content-Type":"application/json"}, headersWithAuth()), body: JSON.stringify({content})});
  if(res.ok){ alert("已保存"); loadVersions(fullRel); } else { alert("保存失败"); }
}

document.getElementById("editor").addEventListener("keydown", (e)=>{
  if((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's'){
    e.preventDefault();
    saveText();
  }
});

async function loadVersions(fullRel){
  const url = VERSIONS_ROUTE + encodeURIComponent(fullRel);
  const res = await fetch(url);
  const sel = document.getElementById("versionsSelect");
  sel.innerHTML = "";
  if(!res.ok) return;
  const data = await res.json();
  const vs = data.versions || [];
  vs.forEach(v=>{
    const opt = document.createElement("option");
    opt.value = v.path;
    opt.textContent = `${v.name} · ${formatBytes(v.size)} · ${fmtTime(v.mtime)}`;
    sel.appendChild(opt);
  });
}

document.getElementById("loadVersionBtn").addEventListener("click", async ()=>{
  const val = document.getElementById("versionsSelect").value;
  if(!val){ alert("请选择版本"); return; }
  const url = DOWNLOAD_ROUTE + encodeURIComponent(val);
  window.open(url, "_blank");
});

document.getElementById("revertTextBtn").addEventListener("click", async ()=>{
  const sel = document.getElementById("versionsSelect");
  if(!sel.value){ alert("请选择版本以恢复"); return; }
  if(!confirm("将用选中版本覆盖当前文件，确认？")) return;
  const verPath = sel.value;
  const r = await fetch(DOWNLOAD_ROUTE + encodeURIComponent(verPath));
  if(!r.ok){ alert("获取版本失败"); return; }
  const blob = await r.blob();
  const text = await blob.text();
  if(!state.selected){ alert("当前未选中文件"); return; }
  const fullRel = state.currentPath ? state.currentPath + "/" + state.selected.name : state.selected.name;
  const res = await fetch(EDIT_ROUTE + encodeURIComponent(fullRel), {method:"POST", headers: Object.assign({"Content-Type":"application/json"}, headersWithAuth()), body: JSON.stringify({content: text})});
  if(res.ok){ alert("已恢复并保存"); loadVersions(fullRel); } else { alert("恢复失败"); }
});

// drag-move helper
async function moveSrcToDst(src, dstDir){
  // dstDir can be folder path; construct dst path as dstDir + '/' + basename(src)
  const name = src.split('/').pop();
  const dst = dstDir ? (dstDir + '/' + name) : name;
  const res = await fetch(MOVE_ROUTE, {method:'POST', headers: Object.assign({'Content-Type':'application/json'}, headersWithAuth()), body: JSON.stringify({src, dst})});
  if(!res.ok){ alert('移动失败'); }
}

// helpers
function clearViewer(){
  state.selected = null;
  document.getElementById("selectedInfo").textContent = "无";
  document.getElementById("mediaContainer").style.display = "none";
  document.getElementById("videoPlayer").style.display = "none";
  document.getElementById("audioPlayer").style.display = "none";
  document.getElementById("textContainer").style.display = "none";
  document.getElementById("emptyHint").style.display = "";
}

// initial bindings
document.getElementById("currentPath").addEventListener("keydown", (e)=>{ if(e.key==='Enter') listCurrent(); });
document.addEventListener('click', (e)=>{ /* hide context on click elsewhere handled in showAt/hide */ });
listCurrent();
</script>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
