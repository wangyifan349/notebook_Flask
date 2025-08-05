import socket
import threading
import sys
import os
from datetime import datetime
from cryptography.hazmat.primitives.asymmetric import dh
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import padding

# =============================== #
#           配置常量              #
# =============================== #
HOST = '127.0.0.1'            # 本地 IP
PORT = 50007                 # 通信端口
BUFFER_SIZE = 4096           # 接收缓冲大小
NONCE_SIZE = 12              # AES-GCM 非法大小（12 字节）

# =============================== #
#         输出锁用于线程安全       #
# =============================== #
print_lock = threading.Lock()  # 控制台输出锁，防止多线程打印冲突

# =============================== #
#        Diffie-Hellman 密钥交换  #
# =============================== #
def generate_parameters():
    """生成 Diffie-Hellman 参数"""
    return dh.generate_parameters(generator=2, key_size=2048, backend=default_backend())

def generate_private_key(parameters):
    """生成私钥"""
    return parameters.generate_private_key()

def generate_shared_key(private_key, peer_public_key):
    """根据私钥和对方公钥生成共享密钥"""
    shared_key = private_key.exchange(peer_public_key)
    return shared_key

def derive_secret(shared_key):
    """根据共享密钥衍生出用于加密的密钥"""
    # 使用 PBKDF2-HMAC 进行密钥派生
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=b"random_salt", iterations=100000, backend=default_backend())
    return kdf.derive(shared_key)

# =============================== #
#         AES-GCM 加密函数组     #
# =============================== #
def encrypt_message(message: str, secret_key: bytes) -> bytes:
    """
    使用 AES-GCM 模式加密消息，返回 nonce + 密文 + 标签。
    """
    nonce = os.urandom(NONCE_SIZE)  # 随机生成 nonce
    cipher = Cipher(algorithms.AES(secret_key), modes.GCM(nonce), backend=default_backend())
    encryptor = cipher.encryptor()

    encrypted = encryptor.update(message.encode('utf-8')) + encryptor.finalize()
    return nonce + encrypted + encryptor.tag  # 返回 nonce + 密文 + 标签

def decrypt_message(encrypted_data: bytes, secret_key: bytes) -> str:
    """
    解密收到的消息，提取 nonce 和标签并返回解密后的原文字符串。
    """
    nonce = encrypted_data[:NONCE_SIZE]
    ciphertext = encrypted_data[NONCE_SIZE:-16]
    tag = encrypted_data[-16:]
    
    cipher = Cipher(algorithms.AES(secret_key), modes.GCM(nonce, tag), backend=default_backend())
    decryptor = cipher.decryptor()

    decrypted = decryptor.update(ciphertext) + decryptor.finalize()
    return decrypted.decode('utf-8')

# =============================== #
#           工具函数组            #
# =============================== #
def current_time() -> str:
    """返回当前时间字符串"""
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

def safe_print(message: str):
    """线程安全打印"""
    with print_lock:
        print(message)

# =============================== #
#           服务端逻辑            #
# =============================== #
def server_recv(conn: socket.socket, secret_key: bytes):
    """接收来自客户端的数据并解密显示"""
    try:
        while True:
            data = conn.recv(BUFFER_SIZE)
            if not data:
                safe_print(f"[{current_time()}] [Server] 客户端断开连接")
                break
            try:
                msg = decrypt_message(data, secret_key)
                safe_print(f"[{current_time()}] [Client] {msg}")
            except Exception as e:
                safe_print(f"[{current_time()}] [Server 解密错误] {e}")
    except Exception as e:
        safe_print(f"[{current_time()}] [Server 接收异常] {e}")
    finally:
        conn.close()


def server_send(conn: socket.socket, secret_key: bytes):
    """读取控制台输入，加密并发送给客户端"""
    try:
        while True:
            msg = sys.stdin.readline().strip()
            if msg.lower() == 'exit':
                conn.shutdown(socket.SHUT_RDWR)
                break
            encrypted = encrypt_message(msg, secret_key)
            conn.sendall(encrypted)
    except Exception as e:
        safe_print(f"[{current_time()}] [Server 发送异常] {e}")
    finally:
        conn.close()


def start_server():
    """启动服务端，监听连接并启动双线程通信"""
    parameters = generate_parameters()
    private_key = generate_private_key(parameters)
    public_key = private_key.public_key()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((HOST, PORT))
        sock.listen(1)
        safe_print(f"[{current_time()}] [Server] 监听中：{HOST}:{PORT}")

        conn, addr = sock.accept()
        safe_print(f"[{current_time()}] [Server] 客户端连接：{addr}")

        # 交换公钥
        conn.sendall(public_key.public_bytes(encoding=dh.Encoding.PEM, format=dh.PublicFormat.SubjectPublicKeyInfo))
        peer_public_key = dh.load_pem_public_key(conn.recv(BUFFER_SIZE), backend=default_backend())

        # 生成共享密钥
        shared_key = generate_shared_key(private_key, peer_public_key)
        secret_key = derive_secret(shared_key)

        recv_thread = threading.Thread(target=server_recv, args=(conn, secret_key), daemon=True)
        send_thread = threading.Thread(target=server_send, args=(conn, secret_key), daemon=True)
        recv_thread.start()
        send_thread.start()

        recv_thread.join()
        send_thread.join()

# =============================== #
#           客户端逻辑            #
# =============================== #
def client_recv(sock: socket.socket, secret_key: bytes):
    """接收来自服务端的数据并解密显示"""
    try:
        while True:
            data = sock.recv(BUFFER_SIZE)
            if not data:
                safe_print(f"[{current_time()}] [Client] 服务器断开连接")
                break
            try:
                msg = decrypt_message(data, secret_key)
                safe_print(f"[{current_time()}] [Server] {msg}")
            except Exception as e:
                safe_print(f"[{current_time()}] [Client 解密错误] {e}")
    except Exception as e:
        safe_print(f"[{current_time()}] [Client 接收异常] {e}")
    finally:
        sock.close()


def client_send(sock: socket.socket, secret_key: bytes):
    """读取控制台输入，加密并发送给服务端"""
    try:
        while True:
            msg = sys.stdin.readline().strip()
            if msg.lower() == 'exit':
                sock.shutdown(socket.SHUT_RDWR)
                break
            encrypted = encrypt_message(msg, secret_key)
            sock.sendall(encrypted)
    except Exception as e:
        safe_print(f"[{current_time()}] [Client 发送异常] {e}")
    finally:
        sock.close()


def start_client():
    """启动客户端并连接服务器，启动双线程通信"""
    parameters = generate_parameters()
    private_key = generate_private_key(parameters)
    public_key = private_key.public_key()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.connect((HOST, PORT))
        except Exception as e:
            safe_print(f"[{current_time()}] [Client 连接失败] {e}")
            return

        # 发送公钥，接收对方公钥并生成共享密钥
        sock.sendall(public_key.public_bytes(encoding=dh.Encoding.PEM, format=dh.PublicFormat.SubjectPublicKeyInfo))
        peer_public_key = dh.load_pem_public_key(sock.recv(BUFFER_SIZE), backend=default_backend())
        
        # 生成共享密钥
        shared_key = generate_shared_key(private_key, peer_public_key)
        secret_key = derive_secret(shared_key)

        recv_thread = threading.Thread(target=client_recv, args=(sock, secret_key), daemon=True)
        send_thread = threading.Thread(target=client_send, args=(sock, secret_key), daemon=True)
        recv_thread.start()
        send_thread.start()

        recv_thread.join()
        send_thread.join()

if __name__ == '__main__':
    mode = input("请选择模式 (server/client): ").strip().lower()
    if mode == 'server':
        start_server()
    elif mode
