import tkinter as tk
from tkinter import filedialog, simpledialog, messagebox, font
import threading, re, chardet

class SmartNotepad:
    def __init__(self, root):
        self.root = root
        self.root.title("智能记事本")
        self._build_ui()
        self.current_font = font.Font(family="Consolas", size=14)
        self.text.configure(font=self.current_font)

    def _build_ui(self):
        # 文本区
        self.text = tk.Text(self.root, wrap='word',
                            bg='#1e1e1e', fg='#ff5555',
                            insertbackground='#ff5555',
                            selectbackground='#44475a',
                            relief='flat', bd=0,
                            padx=10, pady=10)
        self.text.pack(expand=True, fill='both')

        # 菜单
        menubar = tk.Menu(self.root, tearoff=False)
        # 文件
        file_menu = tk.Menu(menubar, tearoff=False)
        file_menu.add_command(label="打开...", command=self.open_file)
        file_menu.add_command(label="保存...", command=self.save_file)
        file_menu.add_separator()
        file_menu.add_command(label="退出", command=self.root.quit)
        menubar.add_cascade(label="文件", menu=file_menu)
        # 编辑
        edit_menu = tk.Menu(menubar, tearoff=False)
        edit_menu.add_command(label="查找...", command=self.find_thread)
        edit_menu.add_command(label="替换...", command=self.replace_thread)
        menubar.add_cascade(label="编辑", menu=edit_menu)
        # 视图
        view_menu = tk.Menu(menubar, tearoff=False)
        view_menu.add_command(label="调整字体大小", command=self.change_font_size)
        menubar.add_cascade(label="视图", menu=view_menu)

        self.root.config(menu=menubar)

    def open_file(self):
        path = filedialog.askopenfilename(filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")])
        if not path:
            return
        raw = open(path, 'rb').read()
        det = chardet.detect(raw)
        enc = det['encoding'] or 'utf-8'
        try:
            content = raw.decode(enc)
        except:
            content = raw.decode('utf-8', errors='ignore')
            enc = 'utf-8'
        self.text.delete("1.0", tk.END)
        self.text.insert(tk.END, content)
        self.root.title(f"智能记事本 — {path} ({enc})")

    def save_file(self):
        content = self.text.get("1.0", tk.END)
        chinese = len(re.findall(r'[\u4e00-\u9fff]', content))
        english = len(re.findall(r'[A-Za-z0-9\s\.,;:\'"\?\!\-$$]', content))
        encoding = 'utf-16' if chinese > english else 'ascii'
        path = filedialog.asksaveasfilename(defaultextension=".txt",
                                            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")])
        if not path:
            return
        try:
            with open(path, 'w', encoding=encoding) as f:
                f.write(content)
        except UnicodeEncodeError:
            encoding = 'utf-16'
            with open(path, 'w', encoding=encoding) as f:
                f.write(content)
            messagebox.showwarning("编码回退", "ASCII编码失败，已改用UTF-16。")
        finally:
            self.root.title(f"智能记事本 — {path} ({encoding})")
            messagebox.showinfo("保存成功", f"已使用 {encoding} 编码保存。")

    def _highlight_all(self, target):
        self.text.tag_remove('highlight', '1.0', tk.END)
        if not target:
            return
        idx = '1.0'
        while True:
            pos = self.text.search(target, idx, stopindex=tk.END)
            if not pos:
                break
            end = f"{pos}+{len(target)}c"
            self.text.tag_add('highlight', pos, end)
            idx = end
        self.text.tag_config('highlight', foreground='#FFD700', background='#1e1e1e')

    def _replace_all(self, find_str, replace_str):
        content = self.text.get("1.0", tk.END)
        new_content = content.replace(find_str, replace_str)
        self.text.delete("1.0", tk.END)
        self.text.insert(tk.END, new_content)

    def find_thread(self):
        def task():
            target = simpledialog.askstring("查找", "请输入要查找的内容：")
            self._highlight_all(target)
            count = len(self.text.tag_ranges('highlight')) // 2
            messagebox.showinfo("查找结果", f"共找到 {count} 处匹配。")
        threading.Thread(target=task, daemon=True).start()

    def replace_thread(self):
        def task():
            find_str = simpledialog.askstring("替换", "要替换的内容：")
            if find_str is None:
                return
            replace_str = simpledialog.askstring("替换", "替换为：")
            if replace_str is None:
                return
            self._replace_all(find_str, replace_str)
            messagebox.showinfo("替换完成", f"已将所有 “{find_str}” 替换为 “{replace_str}”。")
        threading.Thread(target=task, daemon=True).start()

    def change_font_size(self):
        size = simpledialog.askinteger("字体大小", "请输入字号（8–48）：",
                                       initialvalue=self.current_font['size'],
                                       minvalue=8, maxvalue=48)
        if size:
            self.current_font.configure(size=size)

if __name__ == "__main__":
    # 需先安装： pip install chardet
    root = tk.Tk()
    root.geometry("800x600")
    app = SmartNotepad(root)
    root.mainloop()









from flask import Flask, request, send_from_directory, jsonify, abort, render_template_string
from flask_httpauth import HTTPBasicAuth
import os, chardet

app = Flask(__name__)
auth = HTTPBasicAuth()

# --- 配置 ---
UPLOAD_FOLDER = 'files'
ALLOWED_EXTENSIONS = {'txt'}
MAX_SIZE = 5 * 1024 * 1024  # 5 MB
app.config['MAX_CONTENT_LENGTH'] = MAX_SIZE
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# 用户认证示例
USERS = {
    "admin": "secret"
}

@auth.verify_password
def verify(username, password):
    if username in USERS and USERS[username] == password:
        return username

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# 列出目录
@app.route('/list')
@auth.login_required
def list_files():
    items = []
    for name in os.listdir(UPLOAD_FOLDER):
        full = os.path.join(UPLOAD_FOLDER, name)
        items.append({
            'name': name,
            'path': name.replace('\\', '/'),
            'is_dir': os.path.isdir(full)
        })
    return jsonify(items)

# 上传文件
@app.route('/upload', methods=['POST'])
@auth.login_required
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    if not allowed_file(file.filename):
        return jsonify({'error': 'Type not allowed'}), 400

    # 保存临时文件
    temp_path = os.path.join(UPLOAD_FOLDER, file.filename + '.tmp')
    file.save(temp_path)
    size = os.path.getsize(temp_path)
    if size > MAX_SIZE:
        os.remove(temp_path)
        return jsonify({'error': 'File too large (max 5 MB)'}), 413

    # 检测编码并转换到 UTF-8
    with open(temp_path, 'rb') as f:
        raw = f.read()
    result = chardet.detect(raw)
    encoding = result['encoding'] or 'utf-8'
    try:
        text = raw.decode(encoding, errors='replace')
    except:
        text = raw.decode('utf-8', errors='replace')

    final_path = os.path.join(UPLOAD_FOLDER, file.filename)
    with open(final_path, 'w', encoding='utf-8') as f:
        f.write(text)
    os.remove(temp_path)

    return jsonify({'success': 'Uploaded and converted to UTF-8'}), 200

# 查看文件内容
@app.route('/view')
@auth.login_required
def view_file():
    path = request.args.get('path', '')
    full = os.path.join(UPLOAD_FOLDER, path)
    if os.path.isfile(full) and allowed_file(full):
        with open(full, 'rb') as f:
            raw = f.read()
        result = chardet.detect(raw)
        text = raw.decode(result['encoding'] or 'utf-8', errors='replace')
        return text, 200, {'Content-Type': 'text/plain; charset=utf-8'}
    abort(404)

# 下载
@app.route('/files/<path:subpath>')
@auth.login_required
def download_file(subpath):
    full = os.path.join(UPLOAD_FOLDER, subpath)
    if os.path.exists(full):
        return send_from_directory(UPLOAD_FOLDER, subpath, as_attachment=True)
    abort(404)

# 删除
@app.route('/delete', methods=['POST'])
@auth.login_required
def delete():
    data = request.json or {}
    path = data.get('path', '')
    full = os.path.join(UPLOAD_FOLDER, path)
    if not os.path.exists(full):
        return jsonify({'error': 'Not found'}), 404
    try:
        if os.path.isdir(full):
            os.rmdir(full)
        else:
            os.remove(full)
        return jsonify({'success': 'Deleted'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# 移动/重命名
@app.route('/move', methods=['POST'])
@auth.login_required
def move():
    data = request.json or {}
    src = os.path.join(UPLOAD_FOLDER, data.get('src', ''))
    dest = os.path.join(UPLOAD_FOLDER, data.get('dest', ''))
    if not os.path.exists(src):
        return jsonify({'error': 'Source not found'}), 404
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    os.rename(src, dest)
    return jsonify({'success': 'Moved'}), 200

# 前端页面
@app.route('/')
@auth.login_required
def index():
    return render_template_string("""
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>File Manager</title>
  <style>
    body { font-family: sans-serif; margin: 20px; }
    #drop { border: 2px dashed #888; padding: 20px; text-align: center; }
    ul { list-style: none; padding: 0; }
    li { padding: 5px; border: 1px solid #ccc; margin: 2px; cursor: pointer; }
    li.dir { font-weight: bold; }
    #ctx { position:absolute; background:#fff; border:1px solid #888; display:none; }
  </style>
</head>
<body>
  <h2>📂 File Manager (UTF-8 转换 & 5 MB 限制)</h2>
  <div id="drop">Drag & Drop .txt files here or click to upload<input type="file" id="ufile" style="display:none" accept=".txt"></div>
  <ul id="list"></ul>
  <pre id="viewer" style="white-space: pre-wrap; border:1px solid #ccc; padding:10px; display:none;"></pre>
  <div id="ctx"><div id="del">Delete</div></div>
<script>
const drop = document.getElementById('drop'), ufile = document.getElementById('ufile');
const list = document.getElementById('list'), viewer = document.getElementById('viewer'), ctx = document.getElementById('ctx');
let ctxPath = '';

drop.addEventListener('click',()=>ufile.click());
ufile.addEventListener('change',e=>upload(e.target.files));
drop.addEventListener('dragover',e=>e.preventDefault());
drop.addEventListener('drop',e=>{ e.preventDefault(); upload(e.dataTransfer.files); });

function upload(files){
  [...files].forEach(file=>{
    if(!file.name.endsWith('.txt')) return alert('Only .txt');
    let fd=new FormData(); fd.append('file',file);
    fetch('/upload',{method:'POST',body:fd})
      .then(r=>r.json()).then(j=>{ alert(j.success||j.error); refresh(); });
  });
}

function refresh(){
  fetch('/list').then(r=>r.json()).then(data=>{
    list.innerHTML=''; viewer.style.display='none';
    data.forEach(it=>{
      let li=document.createElement('li'); li.textContent=it.name+(it.is_dir?'/':'');
      li.className=it.is_dir?'dir':''; li.draggable=true; li.dataset.path=it.path;
      if(!it.is_dir) li.addEventListener('click',()=>view(it.path));
      li.addEventListener('contextmenu',e=>{ e.preventDefault(); ctx.style.top=e.pageY+'px'; ctx.style.left=e.pageX+'px'; ctx.style.display='block'; ctxPath=it.path; });
      li.addEventListener('dragstart',e=>e.dataTransfer.setData('text/plain',it.path));
      li.addEventListener('dragover',e=>e.preventDefault());
      li.addEventListener('drop',e=>{ e.preventDefault(); let src=e.dataTransfer.getData('text/plain'); let dest=it.is_dir? it.path+'/'+src.split('/').pop() : prompt('New name:',src.split('/').pop()); if(dest) fetch('/move',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({src,dest:it.is_dir?dest:it.path.split('/').slice(0,-1).concat(dest).join('/')})}).then(()=>refresh()); });
      list.appendChild(li);
    });
  });
}

function view(path){
  fetch('/view?path='+encodeURIComponent(path)).then(r=>r.text()).then(txt=>{ viewer.style.display='block'; viewer.textContent=txt; });
}

document.body.addEventListener('click',e=>{
  if(e.target.id=='del'){
    fetch('/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:ctxPath})})
      .then(()=>{ctx.style.display='none'; refresh();});
  } else ctx.style.display='none';
});

refresh();
</script>
</body>
</html>
""")

if __name__ == '__main__':
    app.run(debug=True)



