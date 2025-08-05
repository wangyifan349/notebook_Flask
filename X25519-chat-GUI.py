import socket
import threading
import os
import time
import queue
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes, padding, serialization
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

# --------- 密钥与加密操作 -----------

def generate_key_pair():
    private_key = x25519.X25519PrivateKey.generate()
    public_key = private_key.public_key()
    return private_key, public_key

def derive_shared_key(private_key, peer_public_key_bytes):
    peer_public_key = x25519.X25519PublicKey.from_public_bytes(peer_public_key_bytes)
    shared_key = private_key.exchange(peer_public_key)
    derived_key = HKDF(
        algorithm=hashes.SHA256(),
        length=32, salt=None, info=b'handshake data'
    ).derive(shared_key)
    return derived_key

def encrypt_message(message: str, key: bytes) -> bytes:
    iv = os.urandom(12)
    cipher = Cipher(algorithms.AES(key), modes.GCM(iv))
    encryptor = cipher.encryptor()
    padder = padding.PKCS7(128).padder()
    padded_data = padder.update(message.encode('utf-8')) + padder.finalize()
    ciphertext = encryptor.update(padded_data) + encryptor.finalize()
    return iv + encryptor.tag + ciphertext

def decrypt_message(data: bytes, key: bytes) -> str:
    if len(data) < 28:
        # 不足以包含iv和tag，可能数据异常
        raise ValueError("解密数据格式错误")
    iv = data[:12]
    tag = data[12:28]
    ciphertext = data[28:]
    cipher = Cipher(algorithms.AES(key), modes.GCM(iv, tag))
    decryptor = cipher.decryptor()
    padded_plaintext = decryptor.update(ciphertext) + decryptor.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    plaintext = unpadder.update(padded_plaintext) + unpadder.finalize()
    return plaintext.decode('utf-8', errors='replace')


# --------- 聊天程序 -----------

class SecureChatApp(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.master = master
        self.pack(fill='both', expand=True)

        # 网络变量
        self.sock = None
        self.running = False
        self.key = None

        # 线程与通信队列
        self.incoming_queue = queue.Queue()   # 存放所有接收到的消息(主线程消费)
        self.outgoing_queue = queue.Queue()   # 存放所有待发送消息(由发送线程消费)

        # 线程引用，方便管理关闭
        self.thread_recv = None
        self.thread_send = None
        self.thread_network = None

        self.create_widgets()
        self.master.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.poll_incoming()

    def create_widgets(self):
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill='both', expand=True)

        # 配置页
        self.frame_config = ttk.Frame(self.notebook)
        self.notebook.add(self.frame_config, text="配置")

        # 角色选择
        self.role_var = tk.StringVar(value='server')
        ttk.Label(self.frame_config, text="角色:").grid(row=0, column=0, sticky='w', padx=5, pady=5)
        ttk.Radiobutton(self.frame_config, text="服务器", variable=self.role_var, value='server').grid(row=0, column=1, sticky='w')
        ttk.Radiobutton(self.frame_config, text="客户端", variable=self.role_var, value='client').grid(row=0, column=2, sticky='w')

        # IP输入
        ttk.Label(self.frame_config, text="IP地址:").grid(row=1, column=0, sticky='w', padx=5, pady=5)
        self.entry_host = ttk.Entry(self.frame_config)
        self.entry_host.grid(row=1, column=1, columnspan=2, sticky='ew', padx=5)
        self.entry_host.insert(0, "127.0.0.1")

        # 端口输入
        ttk.Label(self.frame_config, text="端口:").grid(row=2, column=0, sticky='w', padx=5, pady=5)
        self.entry_port = ttk.Entry(self.frame_config)
        self.entry_port.grid(row=2, column=1, columnspan=2, sticky='ew', padx=5)
        self.entry_port.insert(0, "65432")

        # 启动按钮
        self.button_start = ttk.Button(self.frame_config, text="启动", command=self.start_connection)
        self.button_start.grid(row=3, column=0, columnspan=3, pady=10)

        for i in range(3):
            self.frame_config.columnconfigure(i, weight=1)

        # 聊天页
        self.frame_chat = ttk.Frame(self.notebook)
        self.notebook.add(self.frame_chat, text="聊天")
        self.notebook.tab(self.frame_chat, state='disabled')

        # 聊天日志
        self.text_chat = scrolledtext.ScrolledText(self.frame_chat, wrap='word', state='disabled', height=20)
        self.text_chat.pack(fill='both', expand=True, padx=5, pady=5)

        # 消息输入框
        self.entry_message = ttk.Entry(self.frame_chat)
        self.entry_message.pack(fill='x', padx=5, pady=(0,5))
        self.entry_message.bind('<Return>', self.on_send_button)

        # 发送按钮
        self.button_send = ttk.Button(self.frame_chat, text="发送", command=self.on_send_button)
        self.button_send.pack(padx=5, pady=(0,5))

    # ----- UI线程定时轮询接收队列，安全刷新界面 -----
    def poll_incoming(self):
        try:
            while True:
                msg = self.incoming_queue.get_nowait()
                self.append_chat_text(msg)
        except queue.Empty:
            pass
        self.after(100, self.poll_incoming)

    # UI安全写入聊天记录
    def append_chat_text(self, msg: str):
        self.text_chat.configure(state='normal')
        self.text_chat.insert(tk.END, msg + '\n')
        self.text_chat.configure(state='disabled')
        self.text_chat.see(tk.END)

    # 通用安全消息格式化和过滤，避免注入，去除控制字符等
    def sanitize_message(self, msg: str) -> str:
        # 简单过滤，大量场景可以自定义加强
        filtered = ''.join(c for c in msg if c.isprintable() or c in ('\n', '\r', '\t'))
        return filtered.strip()

    # 点击启动按钮
    def start_connection(self):
        if self.running:
            messagebox.showinfo("提示", "已连接，请先关闭程序重启。")
            return

        host = self.entry_host.get().strip()
        port = self.entry_port.get().strip()
        role = self.role_var.get()

        if not host:
            messagebox.showerror("错误", "IP地址不能为空")
            return
        try:
            port = int(port)
            if not (0 < port < 65536):
                raise ValueError
        except ValueError:
            messagebox.showerror("错误", "端口号无效")
            return

        self.button_start.config(state='disabled')
        self.append_chat_text("[系统] 启动角色 {}，连接 {}:{}".format(role, host, port))
        self.running = True

        # 启动网络线程
        self.thread_network = threading.Thread(target=self.network_thread_func, args=(role, host, port), daemon=True)
        self.thread_network.start()

    def network_thread_func(self, role, host, port):
        try:
            if role == 'server':
                self.server_run(host, port)
            else:
                self.client_run(host, port)
        except Exception as e:
            self.incoming_queue.put(f"[错误] 网络异常: {e}")
        finally:
            self.running = False
            self.incoming_queue.put("[系统] 连接关闭")
            self.master.after(0, lambda: self.button_start.config(state='normal'))
            self.master.after(0, lambda: self.notebook.tab(self.frame_chat, state='disabled'))

    def server_run(self, host, port):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((host, port))
            s.listen(1)
            self.incoming_queue.put("[系统] 服务器已启动，等待客户端连接...")
            s.settimeout(1.0)
            while self.running:
                try:
                    conn, addr = s.accept()
                    self.incoming_queue.put(f"[系统] 客户端已连接: {addr}")
                    self.sock = conn
                    break
                except socket.timeout:
                    continue

            if not self.running or not self.sock:
                return

            # 密钥交换
            if not self.key_exchange(is_server=True):
                self.incoming_queue.put("[系统] 密钥交换失败，断开连接")
                return

            self.after(0, self.enable_chat_tab)

            # 启动收发线程
            self.start_recv_send_threads()

            # 等待线程完成或断开
            while self.running:
                time.sleep(0.1)

            self.close_socket()

    def client_run(self, host, port):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(5)
            s.connect((host, port))
            s.settimeout(None)
            self.sock = s
            self.incoming_queue.put("[系统] 已连接到服务器")

            # 密钥交换
            if not self.key_exchange(is_server=False):
                self.incoming_queue.put("[系统] 密钥交换失败，断开连接")
                return

            self.after(0, self.enable_chat_tab)

            self.start_recv_send_threads()

            while self.running:
                time.sleep(0.1)

            self.close_socket()

    def key_exchange(self, is_server: bool) -> bool:
        try:
            priv_key, pub_key = generate_key_pair()
            pub_bytes = pub_key.public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw
            )
            if is_server:
                # 服务器先发公钥，再收客户端公钥
                self.sock.sendall(pub_bytes)
                peer_pub_bytes = self.recv_all_exact(32)
            else:
                # 客户端先接收服务端公钥，再发公钥
                peer_pub_bytes = self.recv_all_exact(32)
                self.sock.sendall(pub_bytes)

            if len(peer_pub_bytes) != 32:
                self.incoming_queue.put("[错误] 收到的公钥长度异常")
                return False

            self.key = derive_shared_key(priv_key, peer_pub_bytes)
            self.incoming_queue.put("[系统] 密钥交换完成，开始加密聊天")
            return True
        except Exception as e:
            self.incoming_queue.put(f"[错误] 密钥交换失败: {e}")
            return False

    def recv_all_exact(self, n: int) -> bytes:
        data = b''
        while len(data) < n:
            packet = self.sock.recv(n - len(data))
            if not packet:
                raise ConnectionError("连接断开")
            data += packet
        return data

    # 启动消息接收和发送线程
    def start_recv_send_threads(self):
        self.thread_recv = threading.Thread(target=self.recv_loop, daemon=True)
        self.thread_send = threading.Thread(target=self.send_loop, daemon=True)
        self.thread_recv.start()
        self.thread_send.start()

    # 接收线程
    def recv_loop(self):
        try:
            while self.running:
                data = self.sock.recv(4096)
                if not data:
                    self.incoming_queue.put("[系统] 连接已关闭")
                    break
                try:
                    text = decrypt_message(data, self.key)
                    text = self.sanitize_message(text)
                    if text:
                        self.incoming_queue.put(f"对方: {text}")
                except Exception as e:
                    self.incoming_queue.put(f"[错误] 解密消息失败: {e}")
        except Exception as e:
            self.incoming_queue.put(f"[错误] 接收异常: {e}")
        finally:
            self.running = False
            self.close_socket()

    # 发送线程从队列取消息并发送
    def send_loop(self):
        try:
            while self.running:
                try:
                    msg = self.outgoing_queue.get(timeout=0.5)
                except queue.Empty:
                    continue
                if msg is None:
                    break
                try:
                    encrypted = encrypt_message(msg, self.key)
                    self.sock.sendall(encrypted)
                except Exception as e:
                    self.incoming_queue.put(f"[错误] 发送消息失败: {e}")
        except Exception as e:
            self.incoming_queue.put(f"[错误] 发送线程异常: {e}")

    def on_send_button(self, event=None):
        if not self.running or not self.sock or not self.key:
            messagebox.showwarning("警告", "尚未连接或密钥未设置，无法发送消息")
            return
        msg = self.entry_message.get().strip()
        if not msg:
            return
        sanitized = self.sanitize_message(msg)
        if not sanitized:
            return
        # 加时间戳
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        full_msg = f"{timestamp} {sanitized}"
        self.append_chat_text(f"你: {full_msg}")
        try:
            self.outgoing_queue.put(full_msg)
        except Exception as e:
            self.incoming_queue.put(f"[错误] 发送队列异常: {e}")
        self.entry_message.delete(0, tk.END)

    def enable_chat_tab(self):
        self.notebook.tab(self.frame_chat, state='normal')
        self.notebook.select(self.frame_chat)
        self.entry_message.focus()

    def close_socket(self):
        try:
            if self.sock:
                self.sock.shutdown(socket.SHUT_RDWR)
                self.sock.close()
        except Exception:
            pass
        self.sock = None

    def on_closing(self):
        if messagebox.askokcancel("退出", "确认退出程序？"):
            self.running = False
            # 发送线程退出信号
            try:
                self.outgoing_queue.put(None)
            except:
                pass
            self.close_socket()
            self.master.destroy()


def main():
    root = tk.Tk()
    root.title("X25519加密聊天")
    root.geometry("600x500")
    app = SecureChatApp(root)
    root.mainloop()


if __name__ == '__main__':
    main()
