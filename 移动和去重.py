import os
import shutil
import hashlib
import threading
import queue
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

class WorkerThread(threading.Thread):
    def __init__(self, src_dirs, dest_dir, move_files, remove_duplicates, 
                 log_queue, progress_queue, stop_event):
        super().__init__()
        self.src_dirs = src_dirs
        self.dest_dir = dest_dir
        self.move_files = move_files
        self.remove_duplicates = remove_duplicates
        self.log_queue = log_queue
        self.progress_queue = progress_queue
        self.stop_event = stop_event
    
    def log(self, message):
        self.log_queue.put(message)
    
    def progress(self, message):
        self.progress_queue.put(message)
    
    def ensure_unique_filename(self, target_directory, original_filename):
        base_name, extension = os.path.splitext(original_filename)
        counter = 1
        candidate_name = original_filename
        while os.path.exists(os.path.join(target_directory, candidate_name)):
            candidate_name = f"{base_name}_{counter}{extension}"
            counter += 1
        return candidate_name
    
    def compute_file_hash(self, file_path, chunk_size=8192):
        hasher = hashlib.md5()
        with open(file_path, "rb") as file:
            for chunk in iter(lambda: file.read(chunk_size), b""):
                if self.stop_event.is_set():
                    raise Exception("操作已被用户中断")
                hasher.update(chunk)
        return hasher.hexdigest()
    
    def gather_files_by_extensions(self, source_directories, extensions_set):
        collected = []
        for directory in source_directories:
            if self.stop_event.is_set():
                raise Exception("操作已被用户中断")
            for root, _, file_names in os.walk(directory):
                if self.stop_event.is_set():
                    raise Exception("操作已被用户中断")
                for name in file_names:
                    if os.path.splitext(name)[1].lower() in extensions_set:
                        full_path = os.path.join(root, name)
                        collected.append(full_path)
        return collected

    def run(self):
        try:
            self.log("任务启动...")
            image_exts = {".jpg", ".jpeg", ".png", ".gif", ".bmp"}
            video_exts = {".mp4", ".avi", ".mkv", ".mov"}
            doc_exts = {".txt", ".md", ".doc", ".docx", ".pdf"}

            self.log("正在扫描源目录文件...")
            images = self.gather_files_by_extensions(self.src_dirs, image_exts)
            videos = self.gather_files_by_extensions(self.src_dirs, video_exts)
            documents = self.gather_files_by_extensions(self.src_dirs, doc_exts)

            total_files = len(images) + len(videos) + len(documents)
            self.log(f"共找到文件数量: 图片 {len(images)}，视频 {len(videos)}，文档 {len(documents)}，合计 {total_files}")

            # 建立分类目录
            img_dir = os.path.join(self.dest_dir, "Images")
            vid_dir = os.path.join(self.dest_dir, "Videos")
            doc_dir = os.path.join(self.dest_dir, "Documents")
            for d in (img_dir, vid_dir, doc_dir):
                os.makedirs(d, exist_ok=True)

            all_files = (
                [(path, img_dir) for path in images] +
                [(path, vid_dir) for path in videos] +
                [(path, doc_dir) for path in documents]
            )

            if total_files == 0:
                self.log("未找到需要处理的文件，任务结束。")
                self.progress("完成")
                return

            self.log(f"开始{'移动' if self.move_files else '复制'}文件...")
            for idx, (src_path, tgt_dir) in enumerate(all_files, start=1):
                if self.stop_event.is_set():
                    self.log("文件处理被用户中断，任务中止。")
                    self.progress("中止")
                    return
                original_name = os.path.basename(src_path)
                unique_name = self.ensure_unique_filename(tgt_dir, original_name)
                dest_path = os.path.join(tgt_dir, unique_name)
                try:
                    if self.move_files:
                        shutil.move(src_path, dest_path)
                    else:
                        shutil.copy2(src_path, dest_path)
                    self.log(f"[{idx}/{total_files}] {'移动' if self.move_files else '复制'}: {original_name} -> {unique_name}")
                except Exception as e:
                    self.log(f"[错误] 处理文件 {src_path} 出错: {e}")
                self.progress(f"进度: {idx}/{total_files}")

            self.log("文件全部整理完成。")

            if self.remove_duplicates:
                self.log("开始重复文件扫描及删除...")
                total_removed = 0
                for check_dir in (img_dir, vid_dir, doc_dir):
                    if self.stop_event.is_set():
                        self.log("重复文件删除被用户中断，任务中止。")
                        self.progress("中止")
                        return
                    hash_to_paths = {}
                    for root, _, files in os.walk(check_dir):
                        for f in files:
                            full_path = os.path.join(root, f)
                            try:
                                file_hash = self.compute_file_hash(full_path)
                            except Exception as e:
                                self.log(f"[错误] 计算文件哈希失败: {full_path}，{e}")
                                continue
                            hash_to_paths.setdefault(file_hash, []).append(full_path)
                    for dups in hash_to_paths.values():
                        # 留一个，删除其余
                        for dup_file in dups[1:]:
                            if self.stop_event.is_set():
                                self.log("重复文件删除被用户中断，任务中止。")
                                self.progress("中止")
                                return
                            try:
                                os.remove(dup_file)
                                total_removed += 1
                                self.log(f"删除重复文件: {dup_file}")
                            except Exception as e:
                                self.log(f"[错误] 删除失败: {dup_file}，{e}")
                self.log(f"重复文件删除完成，共删除 {total_removed} 个文件。")
            else:
                self.log("用户选择跳过重复文件删除步骤。")

            self.progress("完成")
            self.log("全部任务完成。")
        except Exception as ex:
            self.log(f"任务异常结束: {ex}")
            self.progress("异常")

class FileOrganizerGUI:
    def __init__(self, root):
        self.root = root
        root.title("批量文件分类整理器")
        root.geometry("750x650")
        root.minsize(700, 620)

        self.style = ttk.Style()
        self.style.theme_use('clam')

        # --- 源目录 ---
        frm_src = ttk.LabelFrame(root, text="源目录 (可多选，多次添加)")
        frm_src.pack(fill="x", padx=10, pady=8)
        self.txt_src = tk.Text(frm_src, height=4, width=90)
        self.txt_src.pack(side="left", padx=5, pady=5)
        frm_src_btns = ttk.Frame(frm_src)
        frm_src_btns.pack(side="left", padx=5, pady=5)
        ttk.Button(frm_src_btns, text="添加目录", command=self.add_source_dir).pack(fill="x", pady=(0,5))
        ttk.Button(frm_src_btns, text="清空列表", command=self.clear_source_dirs).pack(fill="x")

        # --- 目标目录 ---
        frm_dest = ttk.Frame(root)
        frm_dest.pack(fill="x", padx=10, pady=5)
        ttk.Label(frm_dest, text="目标根目录:").pack(side="left")
        self.dest_dir_var = tk.StringVar()
        self.ent_dest = ttk.Entry(frm_dest, textvariable=self.dest_dir_var, width=70)
        self.ent_dest.pack(side="left", padx=5)
        ttk.Button(frm_dest, text="选择目录", command=self.select_dest_dir).pack(side="left")

        # --- 操作选项 ---
        frm_opts = ttk.LabelFrame(root, text="操作设置")
        frm_opts.pack(fill="x", padx=10, pady=5)
        self.move_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(frm_opts, text="移动文件（否则复制）", variable=self.move_var).pack(anchor="w", padx=5, pady=2)
        self.dup_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(frm_opts, text="完成后删除内容重复的文件（谨慎操作）", variable=self.dup_var).pack(anchor="w", padx=5, pady=2)

        # --- 控制按钮 ---
        frm_ctrl = ttk.Frame(root)
        frm_ctrl.pack(fill="x", padx=10, pady=5)
        self.btn_start = ttk.Button(frm_ctrl, text="开始整理", command=self.start_process)
        self.btn_start.pack(side="left", padx=(0,10))
        self.btn_stop = ttk.Button(frm_ctrl, text="停止任务", command=self.stop_process, state="disabled")
        self.btn_stop.pack(side="left")

        # --- 进度条 ---
        self.progress_var = tk.StringVar(value="未开始")
        self.lbl_progress = ttk.Label(root, textvariable=self.progress_var)
        self.lbl_progress.pack(anchor="w", padx=10)
        self.pbar = ttk.Progressbar(root, orient="horizontal", mode="determinate")
        self.pbar.pack(fill="x", padx=10, pady=(0,10))

        # --- 日志输出 ---
        frm_log = ttk.LabelFrame(root, text="日志输出")
        frm_log.pack(fill="both", expand=True, padx=10, pady=5)
        self.txt_log = tk.Text(frm_log, state='disabled')
        self.txt_log.pack(fill="both", expand=True, padx=5, pady=5)

        # 线程控制
        self.worker_thread = None
        self.log_queue = queue.Queue()
        self.progress_queue = queue.Queue()
        self.stop_event = threading.Event()

        # 定时读取队列
        self.root.after(100, self.process_log_queue)
        self.root.after(100, self.process_progress_queue)

    def add_source_dir(self):
        selected = filedialog.askdirectory(title="选择源目录")
        if selected:
            existing = self.txt_src.get("1.0", "end").splitlines()
            if selected not in existing:
                self.txt_src.insert("end", selected + "\n")

    def clear_source_dirs(self):
        self.txt_src.delete("1.0", "end")

    def select_dest_dir(self):
        selected = filedialog.askdirectory(title="选择目标根目录")
        if selected:
            self.dest_dir_var.set(selected)

    def start_process(self):
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showwarning("提示", "任务正在执行中，请先停止当前任务。")
            return
        src_dirs = [line.strip() for line in self.txt_src.get("1.0", "end").splitlines() if line.strip()]
        if not src_dirs:
            messagebox.showerror("错误", "请添加至少一个有效的源目录。")
            return
        for d in src_dirs:
            if not os.path.isdir(d):
                messagebox.showerror("错误", f"源目录不存在: {d}")
                return
        dest = self.dest_dir_var.get().strip()
        if not dest:
            messagebox.showerror("错误", "请选择有效的目标根目录。")
            return
        if not os.path.isdir(dest):
            try:
                os.makedirs(dest)
            except Exception as e:
                messagebox.showerror("错误", f"目标目录创建失败: {e}")
                return

        # 禁用开始按钮，允许停止按钮
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.progress_var.set("准备启动任务...")
        self.pbar.config(value=0, maximum=100)

        self.stop_event.clear()
        self.worker_thread = WorkerThread(
            src_dirs, dest,
            self.move_var.get(), self.dup_var.get(),
            self.log_queue, self.progress_queue,
            self.stop_event
        )
        self.worker_thread.start()
    
    def stop_process(self):
        if messagebox.askyesno("确认", "确定停止当前任务吗？"):
            self.log_queue.put("用户请求停止任务，正在处理中...")
            self.stop_event.set()
            self.btn_stop.config(state="disabled")

    def process_log_queue(self):
        try:
            while True:
                msg = self.log_queue.get_nowait()
                self.append_log(msg)
        except queue.Empty:
            pass
        self.root.after(100, self.process_log_queue)

    def process_progress_queue(self):
        updated = False
        try:
            while True:
                msg = self.progress_queue.get_nowait()
                if msg == "完成":
                    self.progress_var.set("任务完成。")
                    self.pbar.config(value=100)
                    self.btn_start.config(state="normal")
                    self.btn_stop.config(state="disabled")
                elif msg == "中止":
                    self.progress_var.set("任务已中止。")
                    self.btn_start.config(state="normal")
                    self.btn_stop.config(state="disabled")
                elif msg == "异常":
                    self.progress_var.set("任务异常结束。")
                    self.btn_start.config(state="normal")
                    self.btn_stop.config(state="disabled")
                elif msg.startswith("进度:"):
                    parts = msg.split()
                    try:
                        # 格式： 进度: 当前/总数
                        cur, total = parts[1].split("/")
                        percentage = int(int(cur)/int(total)*100)
                        self.pbar.config(value=percentage)
                        self.progress_var.set(f"处理中: {cur}/{total}")
                    except Exception:
                        self.progress_var.set(msg)
                else:
                    self.progress_var.set(msg)
                updated = True
        except queue.Empty:
            pass
        self.root.after(100, self.process_progress_queue)

    def append_log(self, message):
        self.txt_log.config(state='normal')
        self.txt_log.insert("end", message + "\n")
        self.txt_log.see("end")
        self.txt_log.config(state='disabled')

def main():
    root = tk.Tk()
    app = FileOrganizerGUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()
