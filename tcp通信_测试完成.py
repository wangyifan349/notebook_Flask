import socket
import threading
import sys
import os
from datetime import datetime
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
import struct

HOST = '127.0.0.1'
PORT = 50007
BUFFER_SIZE = 4096
NONCE_SIZE = 36   # AES-GCM 推荐 12 字节
TAG_SIZE = 16     # AES-GCM 标签 16 字节
KDF_SALT = b"static_salt_for_demo"  # 演示用，生产环境请使用更安全的方式
KDF_ITERATIONS = 100000

print_lock = threading.Lock()
def safe_print(*args, **kwargs):
    with print_lock:
        print(*args, **kwargs)

def current_time():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

def send_with_length(sock: socket.socket, data: bytes):
    prefix = struct.pack('>I', len(data))
    sock.sendall(prefix + data)

def recv_all(sock: socket.socket, n: int) -> bytes:
    data = b''
    while len(data) < n:
        packet = sock.recv(n - len(data))
        if not packet:
            return None
        data += packet
    return data

def recv_with_length(sock: socket.socket) -> bytes:
    prefix = recv_all(sock, 4)
    if not prefix:
        return None
    length = struct.unpack('>I', prefix)[0]
    return recv_all(sock, length)

def derive_key(shared_secret: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=KDF_SALT,
        iterations=KDF_ITERATIONS,
        backend=default_backend()
    )
    return kdf.derive(shared_secret)

def encrypt_message(plaintext: str, key: bytes) -> bytes:
    nonce = os.urandom(NONCE_SIZE)
    cipher = Cipher(algorithms.AES(key), modes.GCM(nonce), backend=default_backend())
    encryptor = cipher.encryptor()
    ct = encryptor.update(plaintext.encode('utf-8')) + encryptor.finalize()
    return nonce + ct + encryptor.tag

def decrypt_message(blob: bytes, key: bytes) -> str:
    if len(blob) < NONCE_SIZE + TAG_SIZE:
        raise ValueError("密文格式错误")
    nonce = blob[:NONCE_SIZE]
    tag = blob[-TAG_SIZE:]
    ct = blob[NONCE_SIZE:-TAG_SIZE]
    cipher = Cipher(algorithms.AES(key), modes.GCM(nonce, tag), backend=default_backend())
    decryptor = cipher.decryptor()
    pt = decryptor.update(ct) + decryptor.finalize()
    return pt.decode('utf-8')

def recv_thread(sock, key, stop_evt, peer):
    threading.current_thread().name = f"{peer}-Recv"
    try:
        while not stop_evt.is_set():
            data = recv_with_length(sock)
            if data is None:
                safe_print(f"[{current_time()}] [{peer}] 连接关闭")
                stop_evt.set()
                break
            try:
                msg = decrypt_message(data, key)
                safe_print(f"[{current_time()}] [{peer}] 收到: {msg}")
            except Exception as e:
                safe_print(f"[{current_time()}] [{peer}] 解密异常: {e}")
    finally:
        stop_evt.set()

def send_thread(sock, key, stop_evt, self_name):
    threading.current_thread().name = f"{self_name}-Send"
    try:
        while not stop_evt.is_set():
            line = sys.stdin.readline()
            if not line:
                stop_evt.set()
                break
            msg = line.strip()
            if msg.lower() == 'exit':
                stop_evt.set()
                break
            try:
                blob = encrypt_message(msg, key)
                send_with_length(sock, blob)
            except Exception as e:
                safe_print(f"[{current_time()}] [{self_name}] 发送异常: {e}")
                stop_evt.set()
                break
    finally:
        stop_evt.set()

def start_server():
    safe_print(f"[{current_time()}] [Server] 启动，监听 {HOST}:{PORT}")
    serv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    serv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    serv.bind((HOST, PORT))
    serv.listen(1)
    conn, addr = serv.accept()
    safe_print(f"[{current_time()}] [Server] 连接来自 {addr}")
    with conn:
        # X25519 密钥对
        priv = X25519PrivateKey.generate()
        pub = priv.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw
        )
        # 发送公钥，接收客户端公钥
        send_with_length(conn, pub)
        peer_pub_raw = recv_with_length(conn)
        if peer_pub_raw is None:
            safe_print(f"[{current_time()}] [Server] 公钥接收失败")
            return
        peer_pub = X25519PublicKey.from_public_bytes(peer_pub_raw)
        shared = priv.exchange(peer_pub)
        key = derive_key(shared)
        safe_print(f"[{current_time()}] [Server] 密钥协商完成")

        evt = threading.Event()
        t_r = threading.Thread(target=recv_thread, args=(conn, key, evt, "Client"))
        t_s = threading.Thread(target=send_thread, args=(conn, key, evt, "Server"))
        t_r.start(); t_s.start()
        t_r.join(); t_s.join()
        safe_print(f"[{current_time()}] [Server] 会话结束")

def start_client():
    safe_print(f"[{current_time()}] [Client] 连接 {HOST}:{PORT}")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((HOST, PORT))
    with sock:
        # X25519 密钥对
        priv = X25519PrivateKey.generate()
        pub = priv.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw
        )
        # 接收服务器公钥，发送自己的
        serv_pub_raw = recv_with_length(sock)
        if serv_pub_raw is None:
            safe_print(f"[{current_time()}] [Client] 公钥接收失败")
            return
        send_with_length(sock, pub)
        serv_pub = X25519PublicKey.from_public_bytes(serv_pub_raw)
        shared = priv.exchange(serv_pub)
        key = derive_key(shared)
        safe_print(f"[{current_time()}] [Client] 密钥协商完成")

        evt = threading.Event()
        t_r = threading.Thread(target=recv_thread, args=(sock, key, evt, "Server"))
        t_s = threading.Thread(target=send_thread, args=(sock, key, evt, "Client"))
        t_r.start(); t_s.start()
        t_r.join(); t_s.join()
        safe_print(f"[{current_time()}] [Client] 会话结束")

def main():
    safe_print("请选择模式 (server/client): ", end='', flush=True)
    mode = sys.stdin.readline().strip().lower()
    if mode == 'server':
        start_server()
    elif mode == 'client':
        start_client()
    else:
        safe_print("无效输入，请输入 'server' 或 'client'。")

main()
