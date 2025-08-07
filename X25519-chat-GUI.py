import base64
import socket
import threading
import queue
import os
import struct
import tkinter as tk
import tkinter.scrolledtext as scrolledtext
from tkinter import messagebox
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives.serialization import (
    Encoding, PublicFormat
)
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

# --------------------
# 加密相关函数
# --------------------
def derive_shared_key(private_key: x25519.X25519PrivateKey, peer_public_bytes: bytes) -> bytes:
    peer_public_key = x25519.X25519PublicKey.from_public_bytes(peer_public_bytes)
    shared_key = private_key.exchange(peer_public_key)
    # 使用HKDF衍生256位密钥用于AES
    derived_key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b'handshake data',
    ).derive(shared_key)
    return derived_key

def encrypt_message(message: str, key: bytes) -> bytes:
    iv = os.urandom(12)  # GCM推荐12字节IV
    cipher = Cipher(algorithms.AES(key), modes.GCM(iv))
    encryptor = cipher.encryptor()
    ct = encryptor.update(message.encode('utf-8')) + encryptor.finalize()
    return iv + encryptor.tag + ct  # 12字节IV + 16字节tag + 密文

def decrypt_message(data: bytes, key: bytes) -> str:
    if len(data) < 28:
        raise ValueError("加密数据格式错误")
    iv = data[:12]
    tag = data[12:28]
    ciphertext = data[28:]
    cipher = Cipher(algorithms.AES(key), modes.GCM(iv, tag))
    decryptor = cipher.decryptor()
    plaintext_bytes = decryptor.update(ciphertext) + decryptor.finalize()
    return plaintext_bytes.decode('utf-8')

# --------------------
# 网络通信辅助
# --------------------
def send_message(sock: socket.socket, data: bytes):
    length_prefix = struct.pack('>I', len(data))  # 4字节大端长度
    sock.sendall(length_prefix + data)

def recv_all_exact(sock: socket.socket, n: int) -> bytes:
    data = b''
    while len(data) < n:
        packet = sock.recv(n - len(data))
        if not packet:
            raise ConnectionError("连接已关闭")
        data += packet
    return data

def recv_message(sock: socket.socket) -> bytes:
    length_bytes = recv_all_exact(sock, 4)
    length = struct.unpack('>I', length_bytes)[0]
    data = recv_all_exact(sock, length)
    return data

# --------------------
# GUI主程序类
# --------------------
class SecureChat:
    def __init__(self, master):
        self.master = master
        self.master.title("安全聊天 | 支持X25519 + AES-GCM 加密传输")
        self.master.geometry('620x460')
        self.master.minsize(520, 400)

        # 网络与加密相关
        self.sock = None
        self.key = None
        self.running = False
        self.outgoing_queue = queue.Queue()
        self.incoming_queue = queue.Queue()
        self.threads = []

        self.create_widgets()
        self.master.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.check_incoming()
    
    def create_widgets(self):
        # 连接配置区
        frame_conn = tk.Frame(self.master)
        frame_conn.pack(fill='x', padx=8, pady=4)

        tk.Label(frame_conn, text="对方IP:").pack(side='left')
        self.entry_ip = tk.Entry(frame_conn, width=14)
        self.entry_ip.pack(side='left', padx=(2,8))
        self.entry_ip.insert(0, "127.0.0.1")

        tk.Label(frame_conn, text="端口:").pack(side='left')
        self.entry_port = tk.Entry(frame_conn, width=6)
        self.entry_port.pack(side='left', padx=(2,8))
        self.entry_port.insert(0, "1234")

        self.btn_connect = tk.Button(frame_conn, text="连接服务器", width=12,
                                     command=self.start_client)
        self.btn_connect.pack(side='left')

        self.btn_listen = tk.Button(frame_conn, text="启动服务器", width=12,
                                    command=self.start_server)
        self.btn_listen.pack(side='left', padx=(8,0))

        # 聊天显示区
        frame_chat = tk.Frame(self.master)
        frame_chat.pack(fill='both', expand=True, padx=8, pady=6)

        self.text_area = scrolledtext.ScrolledText(frame_chat, state='disabled', wrap='word')
        self.text_area.pack(fill='both', expand=True)

        # 输入区
        frame_input = tk.Frame(self.master)
        frame_input.pack(fill='x', padx=8, pady=6)

        self.entry_msg = tk.Entry(frame_input)
        self.entry_msg.pack(side='left', fill='x', expand=True, padx=(0,4))
        self.entry_msg.bind('<Return>', lambda event: self.send_message())

        self.btn_send = tk.Button(frame_input, text="发送", width=10,
                                  command=self.send_message, state='disabled')
        self.btn_send.pack(side='left')

    def append_text(self, text):
        self.text_area.configure(state='normal')
        self.text_area.insert('end', text + '\n')
        self.text_area.see('end')
        self.text_area.configure(state='disabled')

    def sanitize_message(self, msg: str) -> str:
        msg = msg.strip("\r\n").replace("\x00", "")
        return msg

    def start_client(self):
        if self.running:
            messagebox.showinfo("提示", "已经建立连接，无法重复连接。")
            return
        ip = self.entry_ip.get().strip()
        port_str = self.entry_port.get().strip()
        if not ip or not port_str.isdigit():
            messagebox.showerror("错误", "请填写有效的IP和端口。")
            return
        port = int(port_str)
        threading.Thread(target=self.client_thread, args=(ip, port), daemon=True).start()

    def start_server(self):
        if self.running:
            messagebox.showinfo("提示", "已经建立连接，无法重复启动。")
            return
        ip = self.entry_ip.get().strip()
        port_str = self.entry_port.get().strip()
        if not port_str.isdigit():
            messagebox.showerror("错误", "请填写有效的端口。")
            return
        port = int(port_str)
        threading.Thread(target=self.server_thread, args=(ip, port), daemon=True).start()

    # --------------------
    # 服务器线程
    # --------------------
    def server_thread(self, ip, port):
        self.append_text("[系统] 服务器正在启动，等待客户端连接...")
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind((ip, port))
            sock.listen(1)
            sock.settimeout(10)
            try:
                conn, addr = sock.accept()
            except socket.timeout:
                self.append_text("[系统] 服务器等待连接超时。")
                sock.close()
                return
            self.sock = conn
            self.append_text(f"[系统] 客户端已连接，地址：{addr[0]}:{addr[1]}")
            if not self.handshake_server(conn):
                self.append_text("[系统] 握手失败，断开连接。")
                self.close_socket()
                return
            self.post_handshake()
            self.run_communication()
        except Exception as e:
            self.append_text(f"[错误] 服务器异常: {e}")
        finally:
            sock.close()

    def handshake_server(self, sock: socket.socket) -> bool:
        # 服务端先接收客户端公钥（base64格式）
        try:
            peer_key_b64 = recv_message(sock).decode('ascii')
            peer_key_bytes = base64.b64decode(peer_key_b64)
        except Exception:
            self.append_text("[系统] 握手错误：接收客户端公钥失败。")
            return False

        # 生成服务端私钥和公钥
        self.private_key = x25519.X25519PrivateKey.generate()
        pubkey_bytes = self.private_key.public_key().public_bytes(
            encoding=Encoding.Raw,
            format=PublicFormat.Raw
        )
        pubkey_b64 = base64.b64encode(pubkey_bytes).decode('ascii')
        try:
            # 发送服务端公钥
            send_message(sock, pubkey_b64.encode('ascii'))
        except Exception:
            self.append_text("[系统] 握手错误：发送服务端公钥失败。")
            return False

        # 计算共享密钥
        try:
            self.key = derive_shared_key(self.private_key, peer_key_bytes)
        except Exception:
            self.append_text("[系统] 握手错误：计算共享密钥失败。")
            return False
        self.append_text("[系统] 握手成功，安全连接已建立。")
        return True

    # --------------------
    # 客户端线程
    # --------------------
    def client_thread(self, ip, port):
        self.append_text(f"[系统] 正在连接服务器 {ip}:{port} ...")
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.settimeout(10)
            sock.connect((ip, port))
            self.sock = sock
            self.append_text("[系统] 已连接到服务器，开始握手...")
            if not self.handshake_client(sock):
                self.append_text("[系统] 握手失败，断开连接。")
                self.close_socket()
                return
            self.post_handshake()
            self.run_communication()
        except Exception as e:
            self.append_text(f"[错误] 连接异常: {e}")
            sock.close()

    def handshake_client(self, sock: socket.socket) -> bool:
        # 生成客户端私钥和公钥
        self.private_key = x25519.X25519PrivateKey.generate()
        pubkey_bytes = self.private_key.public_key().public_bytes(
            encoding=Encoding.Raw,
            format=PublicFormat.Raw
        )
        pubkey_b64 = base64.b64encode(pubkey_bytes).decode('ascii')

        try:
            # 先发送客户端公钥
            send_message(sock, pubkey_b64.encode('ascii'))
            # 然后接收服务端公钥
            peer_key_b64 = recv_message(sock).decode('ascii')
            peer_key_bytes = base64.b64decode(peer_key_b64)
        except Exception:
            self.append_text("[系统] 握手错误：交换公钥失败。")
            return False

        try:
            self.key = derive_shared_key(self.private_key, peer_key_bytes)
        except Exception:
            self.append_text("[系统] 握手错误：计算共享密钥失败。")
            return False
        self.append_text("[系统] 握手成功，安全连接已建立。")
        return True

    # --------------------
    # 握手结束后设置
    # --------------------
    def post_handshake(self):
        self.running = True
        self.btn_send.config(state='normal')
        self.btn_connect.config(state='disabled')
        self.btn_listen.config(state='disabled')
        # 启动发送和接收线程
        t_recv = threading.Thread(target=self.recv_loop, daemon=True)
        t_send = threading.Thread(target=self.send_loop, daemon=True)
        self.threads.extend([t_recv, t_send])
        t_recv.start()
        t_send.start()
        self.append_text("[系统] 可以开始发送消息。")

    # --------------------
    # 消息发送线程
    # --------------------
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
                    send_message(self.sock, encrypted)
                except Exception as e:
                    self.incoming_queue.put(f"[错误] 发送消息失败: {e}")
        except Exception as e:
            self.incoming_queue.put(f"[错误] 发送线程异常: {e}")

    # --------------------
    # 消息接收线程
    # --------------------
    def recv_loop(self):
        try:
            while self.running:
                try:
                    data = recv_message(self.sock)
                except ConnectionError:
                    self.incoming_queue.put("[系统] 连接已关闭。")
                    break
                except Exception as e:
                    self.incoming_queue.put(f"[错误] 接收异常: {e}")
                    break
                try:
                    text = decrypt_message(data, self.key)
                    text = self.sanitize_message(text)
                    if text:
                        self.incoming_queue.put(f"对方: {text}")
                except Exception as e:
                    self.incoming_queue.put(f"[错误] 解密消息失败: {e}")
        finally:
            self.running = False
            self.close_socket()

    def send_message(self):
        msg = self.entry_msg.get()
        msg = msg.strip()
        if not msg or not self.running:
            return
        self.append_text(f"我: {msg}")
        self.entry_msg.delete(0, 'end')
        self.outgoing_queue.put(msg)

    def check_incoming(self):
        while True:
            try:
                text = self.incoming_queue.get_nowait()
            except queue.Empty:
                break
            else:
                self.append_text(text)
        self.master.after(100, self.check_incoming)

    def close_socket(self):
        self.running = False
        if self.sock:
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None
        self.btn_send.config(state='disabled')
        self.btn_connect.config(state='normal')
        self.btn_listen.config(state='normal')
        self.append_text("[系统] 连接已断开。")

    def on_closing(self):
        if messagebox.askokcancel("退出", "确定要关闭程序吗？"):
            self.running = False
            # 退出时在队列放个None用于唤醒发送线程结束
            self.outgoing_queue.put(None)
            self.close_socket()
            self.master.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = SecureChat(root)
    root.mainloop()
