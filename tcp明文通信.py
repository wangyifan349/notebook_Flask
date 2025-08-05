import socket
import threading
import sys

HOST = '127.0.0.1'
PORT = 50007

def server_recv(conn):
    while True:
        try:
            data = conn.recv(1024)
            if not data:
                print('[Server] 客户端断开连接')
                break
            print(f'[Server 收到] {data.decode("utf-8")}')
        except Exception as e:
            print(f'[Server] 接收错误：{e}')
            break
    conn.close()

def server_send(conn):
    try:
        while True:
            msg = sys.stdin.readline()
            if not msg:
                break
            msg = msg.rstrip('\n')
            if msg.lower() == 'exit':
                break
            conn.sendall(msg.encode('utf-8'))
    except Exception as e:
        print(f'[Server] 发送错误：{e}')
    finally:
        conn.close()

def start_server():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind((HOST, PORT))
    sock.listen(1)
    print(f'[Server] 监听中 {HOST}:{PORT}')
    conn, addr = sock.accept()
    print(f'[Server] 客户端已连接：{addr}')
    threading.Thread(target=server_recv, args=(conn,), daemon=True).start()
    threading.Thread(target=server_send, args=(conn,), daemon=True).start()

def client_recv(sock):
    while True:
        try:
            data = sock.recv(1024)
            if not data:
                print('[Client] 服务器断开连接')
                break
            print(f'[Client 收到] {data.decode("utf-8")}')
        except Exception as e:
            print(f'[Client] 接收错误：{e}')
            break
    sock.close()

def client_send(sock):
    try:
        while True:
            msg = sys.stdin.readline()
            if not msg:
                break
            msg = msg.rstrip('\n')
            if msg.lower() == 'exit':
                break
            sock.sendall(msg.encode('utf-8'))
    except Exception as e:
        print(f'[Client] 发送错误：{e}')
    finally:
        sock.close()

def start_client():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((HOST, PORT))
    print(f'[Client] 已连接到 {HOST}:{PORT}')
    threading.Thread(target=client_recv, args=(sock,), daemon=True).start()
    threading.Thread(target=client_send, args=(sock,), daemon=True).start()

def main():
    choice = input("输入 's' 启动服务器，输入 'c' 启动客户端：").strip().lower()
    if choice == 's':
        start_server()
    elif choice == 'c':
        start_client()
    else:
        print('无效选择，程序结束')
        return
    try:
        while True:
            threading.Event().wait(1)
    except KeyboardInterrupt:
        print('\n程序终止。')

if __name__ == '__main__':
    main()
