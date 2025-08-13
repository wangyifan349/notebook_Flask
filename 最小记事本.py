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
