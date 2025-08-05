import socket
import threading
import os
import time
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding

# 通用配置
HOST = '127.0.0.1'
PORT = 65432

# ===== 密钥生成与加解密功能 =====

def generate_key_pair():
    private_key = x25519.X25519PrivateKey.generate()
    public_key = private_key.public_key()
    return private_key, public_key

def derive_shared_key(private_key, peer_public_key_bytes):
    peer_public_key = x25519.X25519PublicKey.from_public_bytes(peer_public_key_bytes)
    shared_key = private_key.exchange(peer_public_key)
    derived_key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b'handshake data',
    ).derive(shared_key)
    return derived_key

def encrypt_message(message, key):
    iv = os.urandom(12)
    cipher = Cipher(algorithms.AES(key), modes.GCM(iv))
    encryptor = cipher.encryptor()
    padder = padding.PKCS7(128).padder()
    padded = padder.update(message.encode()) + padder.finalize()
    ciphertext = encryptor.update(padded) + encryptor.finalize()
    return iv + encryptor.tag + ciphertext

def decrypt_message(data, key):
    iv = data[:12]
    tag = data[12:28]
    ciphertext = data[28:]
    cipher = Cipher(algorithms.AES(key), modes.GCM(iv, tag))
    decryptor = cipher.decryptor()
    padded = decryptor.update(ciphertext) + decryptor.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    return unpadder.update(padded) + unpadder.finalize()

# ===== 发送和接收线程 =====

def send_loop(sock, key):
    while True:
        try:
            msg = input("You: ")
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
            full_msg = f"{timestamp} - {msg}"
            encrypted = encrypt_message(full_msg, key)
            sock.sendall(encrypted)
        except Exception as e:
            print(f"Error sending: {e}")
            break

def receive_loop(sock, key):
    while True:
        try:
            data = sock.recv(4096)
            if not data:
                break
            decrypted = decrypt_message(data, key)
            print(f"\n{decrypted.decode()}")
        except Exception as e:
            print(f"Error receiving: {e}")
            break

# ===== 主函数入口 =====

def start_server():
    print("Starting as server...")
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.bind((HOST, PORT))
    server_sock.listen(1)
    print(f"Listening on {HOST}:{PORT}...")
    conn, addr = server_sock.accept()
    print(f"Connected by {addr}")

    # 生成密钥并交换
    priv_key, pub_key = generate_key_pair()
    conn.sendall(pub_key.public_bytes())
    peer_pub = conn.recv(1024)
    key = derive_shared_key(priv_key, peer_pub)

    # 启动发送和接收线程
    threading.Thread(target=send_loop, args=(conn, key), daemon=True).start()
    threading.Thread(target=receive_loop, args=(conn, key), daemon=True).start()

    while True:
        time.sleep(1)

def start_client():
    print("Starting as client...")
    time.sleep(1)  # 避免客户端启动过快连接不上
    client_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client_sock.connect((HOST, PORT))
    print(f"Connected to server at {HOST}:{PORT}")

    # 生成密钥并交换
    priv_key, pub_key = generate_key_pair()
    peer_pub = client_sock.recv(1024)
    client_sock.sendall(pub_key.public_bytes())
    key = derive_shared_key(priv_key, peer_pub)

    # 启动发送和接收线程
    threading.Thread(target=send_loop, args=(client_sock, key), daemon=True).start()
    threading.Thread(target=receive_loop, args=(client_sock, key), daemon=True).start()

    while True:
        time.sleep(1)

def main():
    mode = input("作为服务器运行？（y/n）: ").strip().lower()
    if mode == 'y':
        start_server()
    else:
        start_client()

if __name__ == "__main__":
    main()
