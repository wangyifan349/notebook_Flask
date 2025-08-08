

    #!/usr/bin/env python3
    # -*- coding: utf-8 -*-
    """
    ChaCha20-Poly1305 多线程批量加/解密工具（无 AAD，原地覆盖）
    ---------------------------------------------
    - 纯 Python 实现 ChaCha20（20 轮）和 Poly1305
    - 加密时对每个文件随机生成 12 字节 nonce
    - 解密时先校验标签再写回
    - 使用 ThreadPoolExecutor 并发处理，直接覆盖源文件
    """
     
    import os
    import struct
    import hmac
    from pathlib import Path
    from concurrent.futures import ThreadPoolExecutor, as_completed
     
    # ===== 常量配置 =====
    CHACHA20_ROUNDS = 20
    POLY1305_KEY_SIZE = 32
    NONCE_SIZE = 12
    TAG_SIZE = 16
     
    # ===== 辅助函数 =====
    def rotl32(v: int, c: int) -> int:
        return ((v << c) & 0xffffffff) | (v >> (32 - c))
     
    def quarter_round(state: list, a: int, b: int, c: int, d: int):
        state[a] = (state[a] + state[b]) & 0xffffffff
        state[d] ^= state[a]; state[d] = rotl32(state[d], 16)
        state[c] = (state[c] + state[d]) & 0xffffffff
        state[b] ^= state[c]; state[b] = rotl32(state[b], 12)
        state[a] = (state[a] + state[b]) & 0xffffffff
        state[d] ^= state[a]; state[d] = rotl32(state[d], 8)
        state[c] = (state[c] + state[d]) & 0xffffffff
        state[b] ^= state[c]; state[b] = rotl32(state[b], 7)
     
    def chacha20_block(key: bytes, counter: int, nonce: bytes) -> bytes:
        constants = b"expand 32-byte k"
        st = list(struct.unpack("<4I", constants)
                  + struct.unpack("<8I", key)
                  + (counter,)
                  + struct.unpack("<3I", nonce))
        working = st.copy()
        for _ in range(CHACHA20_ROUNDS // 2):
            # column rounds
            quarter_round(working, 0, 4,  8, 12)
            quarter_round(working, 1, 5,  9, 13)
            quarter_round(working, 2, 6, 10, 14)
            quarter_round(working, 3, 7, 11, 15)
            # diagonal rounds
            quarter_round(working, 0, 5, 10, 15)
            quarter_round(working, 1, 6, 11, 12)
            quarter_round(working, 2, 7,  8, 13)
            quarter_round(working, 3, 4,  9, 14)
        out = [(working[i] + st[i]) & 0xffffffff for i in range(16)]
        return struct.pack("<16I", *out)
     
    def chacha20_encrypt(key: bytes, nonce: bytes, counter: int, data: bytes) -> bytes:
        output = bytearray()
        for i in range(0, len(data), 64):
            block = chacha20_block(key, counter, nonce)
            counter = (counter + 1) & 0xffffffff
            segment = data[i:i+64]
            output.extend(b ^ k for b, k in zip(segment, block))
        return bytes(output)
     
    # ===== Poly1305 实现 =====
    def poly1305_clamp(r: bytes):
        t0 = struct.unpack("<I", r[0:4])[0] & 0x3ffffff
        t1 = struct.unpack("<I", r[3:7])[0] >> 2 & 0x3ffff03
        t2 = struct.unpack("<I", r[6:10])[0] >> 4 & 0x3ffc0ff
        t3 = struct.unpack("<I", r[9:13])[0] >> 6 & 0x3f03fff
        t4 = struct.unpack("<I", r[12:16])[0] >> 8 & 0x00fffff
        return (t0, t1, t2, t3, t4)
     
    def poly1305_mac(msg: bytes, key: bytes) -> bytes:
        r = poly1305_clamp(key[:16])
        s = struct.unpack("<4I", key[16:32])
        p = (1 << 130) - 5
        acc = 0
        for i in range(0, len(msg), 16):
            chunk = msg[i:i+16]
            n = int.from_bytes(chunk + b'\x01', 'little')
            acc = (acc + n) * (r[0] | (r[1] << 26) | (r[2] << 52) |
                               (r[3] << 78) | (r[4] << 104))
            acc %= p
        tag_int = (acc + (s[0] | (s[1] << 32) |
                           (s[2] << 64) | (s[3] << 96))) % (1 << 128)
        return tag_int.to_bytes(16, 'little')
     
    # ===== AEAD ChaCha20-Poly1305（无 AAD） =====
    def pad16(data: bytes) -> bytes:
        return data + b'\x00' * ((16 - len(data) % 16) % 16)
     
    def aead_encrypt(key: bytes, nonce: bytes, plaintext: bytes):
        poly_key = chacha20_block(key, 0, nonce)[:POLY1305_KEY_SIZE]
        ciphertext = chacha20_encrypt(key, nonce, 1, plaintext)
        auth_data = pad16(ciphertext) + struct.pack("<Q", 0) + struct.pack("<Q", len(ciphertext))
        tag = poly1305_mac(auth_data, poly_key)
        return ciphertext, tag
     
    def aead_decrypt(key: bytes, nonce: bytes, ciphertext: bytes, tag: bytes) -> bytes:
        poly_key = chacha20_block(key, 0, nonce)[:POLY1305_KEY_SIZE]
        auth_data = pad16(ciphertext) + struct.pack("<Q", 0) + struct.pack("<Q", len(ciphertext))
        expected = poly1305_mac(auth_data, poly_key)
        if not hmac.compare_digest(expected, tag):
            raise ValueError("Tag mismatch: 数据可能已篡改")
        return chacha20_encrypt(key, nonce, 1, ciphertext)
     
    # ===== 原地文件处理 =====
    def process_file_inplace(mode: str, key: bytes, path: Path):
        data = path.read_bytes()
        if mode == 'encrypt':
            nonce = os.urandom(NONCE_SIZE)
            ciphertext, tag = aead_encrypt(key, nonce, data)
            output = nonce + ciphertext + tag
        else:
            nonce = data[:NONCE_SIZE]
            ciphertext = data[NONCE_SIZE:-TAG_SIZE]
            tag = data[-TAG_SIZE:]
            output = aead_decrypt(key, nonce, ciphertext, tag)
        path.write_bytes(output)
     
    def batch_process_inplace(src_dir: str, key: bytes,
                              mode: str = 'encrypt', max_workers: int = 4):
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = []
            for root, _, files in os.walk(src_dir):
                for fn in files:
                    p = Path(root) / fn
                    futures.append(executor.submit(process_file_inplace, mode, key, p))
            for f in as_completed(futures):
                try:
                    f.result()
                except Exception as e:
                    print(f"Error processing {e}")
     
    # ===== 主程序入口 =====
    if __name__ == '__main__':
        KEY = os.urandom(32)         # 32 字节对称密钥，请妥善保存
        SRC_DIR = 'path/to/source'   # 源目录
        MODE = 'encrypt'             # 'encrypt' 或 'decrypt'
        MAX_WORKERS = 8
     
        print(f"{MODE.title()}ing files in-place under {SRC_DIR}...")
        batch_process_inplace(SRC_DIR, KEY, mode=MODE, max_workers=MAX_WORKERS)
        print("完成。")

