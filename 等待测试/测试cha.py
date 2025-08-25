#!/usr/bin/env python3
"""
chacha20_poly1305_batch_nestfree.py

纯 Python ChaCha20-Poly1305（无 AAD）批量加密/解密工具（无命令行）。
- 不使用嵌套表达式或列表推导（函数内部用显式循环）。
- 不检测是否已加密，直接对每个文件执行加密/解密。
- 覆盖原文件，格式： nonce(12) || ciphertext || tag(16)
- 支持多线程（ThreadPoolExecutor），调用 encrypt_directory / decrypt_directory。
- 详细注释，完整实现 Poly1305（不是 HMAC）。
"""
import os
import secrets
from typing import Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
# ------------------ 低级操作：32-bit 循环左移 ------------------
def rotl32(v: int, n: int) -> int:
    # 32-bit 循环左移
    left = (v << n) & 0xffffffff
    right = v >> (32 - n)
    return left | right
# ------------------ ChaCha20 quarter round ------------------
def quarter_round(state: list, a: int, b: int, c: int, d: int) -> None:
    # 按 RFC 规定对 state 原地修改
    state[a] = (state[a] + state[b]) & 0xffffffff
    state[d] = state[d] ^ state[a]
    state[d] = rotl32(state[d], 16)

    state[c] = (state[c] + state[d]) & 0xffffffff
    state[b] = state[b] ^ state[c]
    state[b] = rotl32(state[b], 12)

    state[a] = (state[a] + state[b]) & 0xffffffff
    state[d] = state[d] ^ state[a]
    state[d] = rotl32(state[d], 8)

    state[c] = (state[c] + state[d]) & 0xffffffff
    state[b] = state[b] ^ state[c]
    state[b] = rotl32(state[b], 7)
# ------------------ ChaCha20 block 函数 ------------------
def to_u32_list_no_listcomp(b: bytes) -> list:
    # 将字节序列按每 4 字节小端转换为 u32 列表（显式循环，避免列表推导）
    out = []
    i = 0
    blen = len(b)
    while i < blen:
        chunk = b[i:i+4]
        val = int.from_bytes(chunk, 'little')
        out.append(val)
        i += 4
    return out
def chacha20_block(key: bytes, counter: int, nonce: bytes) -> bytes:
    # 参数检查
    if len(key) != 32:
        raise ValueError("Key must be 32 bytes")
    if len(nonce) != 12:
        raise ValueError("Nonce must be 12 bytes")
    constants = b"expand 32-byte k"
    # 构造初始 state：constants(4) || key(8) || counter(1) || nonce(3)
    state = []
    cons_list = to_u32_list_no_listcomp(constants)
    j = 0
    while j < len(cons_list):
        state.append(cons_list[j])
        j += 1
    key_list = to_u32_list_no_listcomp(key)
    j = 0
    while j < len(key_list):
        state.append(key_list[j])
        j += 1
    state.append(counter & 0xffffffff)
    nonce_list = to_u32_list_no_listcomp(nonce)
    j = 0
    while j < len(nonce_list):
        state.append(nonce_list[j])
        j += 1
    # working 是 state 的拷贝
    working = []
    j = 0
    while j < len(state):
        working.append(state[j])
        j += 1
    # 进行 10 次 double-round（共 20 轮）
    round_i = 0
    while round_i < 10:
        quarter_round(working, 0, 4, 8, 12)
        quarter_round(working, 1, 5, 9, 13)
        quarter_round(working, 2, 6, 10, 14)
        quarter_round(working, 3, 7, 11, 15)
        quarter_round(working, 0, 5, 10, 15)
        quarter_round(working, 1, 6, 11, 12)
        quarter_round(working, 2, 7, 8, 13)
        quarter_round(working, 3, 4, 9, 14)
        round_i += 1
    # 将 working 与 state 相加并输出为 64 字节
    out = bytearray(64)
    i = 0
    while i < 16:
        word = (working[i] + state[i]) & 0xffffffff
        out_index = i * 4
        out[out_index:out_index+4] = word.to_bytes(4, 'little')
        i += 1
    return bytes(out)
# ------------------ ChaCha20 xor stream ------------------
def chacha20_xor_stream(key: bytes, nonce: bytes, initial_counter: int, data: bytes) -> bytes:
    if len(nonce) != 12:
        raise ValueError("Nonce must be 12 bytes")

    out = bytearray()
    data_len = len(data)

    # 需要的块数
    blocks = (data_len + 63) // 64

    bidx = 0
    while bidx < blocks:
        block = chacha20_block(key, initial_counter + bidx, nonce)

        start = bidx * 64
        end = start + 64
        chunk = data[start:end]

        j = 0
        while j < len(chunk):
            out.append(chunk[j] ^ block[j])
            j += 1

        bidx += 1

    return bytes(out)

# ------------------ Poly1305 实现（包含 r 修剪） ------------------

def clamp_r(r_bytes: bytes) -> int:
    if len(r_bytes) != 16:
        raise ValueError("r must be 16 bytes")
    r = int.from_bytes(r_bytes, 'little')
    r = r & 0x0ffffffc0ffffffc0ffffffc0fffffff
    return r

def poly1305_mac(key: bytes, msg: bytes) -> bytes:
    if len(key) != 32:
        raise ValueError("Poly1305 key must be 32 bytes")

    r_bytes = key[:16]
    s_bytes = key[16:32]

    r = clamp_r(r_bytes)
    s = int.from_bytes(s_bytes, 'little')

    p = (1 << 130) - 5
    acc = 0

    i = 0
    mlen = len(msg)
    while i < mlen:
        block = msg[i:i+16]
        appended = block + b'\x01'
        n = int.from_bytes(appended, 'little')
        acc = (acc + n) % p
        acc = (acc * r) % p
        i += 16

    tag_int = (acc + s) % (1 << 128)
    tag = tag_int.to_bytes(16, 'little')
    return tag

def pad16_no_listexpr(xlen: int) -> bytes:
    rem = xlen % 16
    if rem == 0:
        return b''
    pad_len = 16 - rem
    zeros = b'\x00' * pad_len
    return zeros

# ------------------ 高级封装：encrypt / decrypt ------------------

def encrypt(key: bytes, nonce: bytes, plaintext: bytes, initial_counter: int = 1) -> Tuple[bytes, bytes]:
    if len(key) != 32:
        raise ValueError("Key must be 32 bytes")
    if len(nonce) != 12:
        raise ValueError("Nonce must be 12 bytes")

    # 生成一次性 Poly1305 key：ChaCha20 keystream (counter=0) 的前 32 字节
    otk = chacha20_xor_stream(key, nonce, 0, b'\x00' * 32)
    poly_key = otk[:32]

    # 生成 ciphertext（从 initial_counter 开始）
    ciphertext = chacha20_xor_stream(key, nonce, initial_counter, plaintext)

    pad = pad16_no_listexpr(len(ciphertext))
    aad_len_bytes = (0).to_bytes(8, 'little')  # 没有 AAD
    ct_len_bytes = (len(ciphertext)).to_bytes(8, 'little')

    mac_data = ciphertext + pad + aad_len_bytes + ct_len_bytes

    tag = poly1305_mac(poly_key, mac_data)
    return ciphertext, tag

def constant_time_compare(a: bytes, b: bytes) -> bool:
    if len(a) != len(b):
        return False
    res = 0
    i = 0
    while i < len(a):
        res = res | (a[i] ^ b[i])
        i += 1
    return res == 0

def decrypt(key: bytes, nonce: bytes, ciphertext: bytes, tag: bytes, initial_counter: int = 1) -> bytes:
    if len(key) != 32:
        raise ValueError("Key must be 32 bytes")
    if len(nonce) != 12:
        raise ValueError("Nonce must be 12 bytes")
    if len(tag) != 16:
        raise ValueError("Tag must be 16 bytes")

    otk = chacha20_xor_stream(key, nonce, 0, b'\x00' * 32)
    poly_key = otk[:32]

    pad = pad16_no_listexpr(len(ciphertext))
    aad_len_bytes = (0).to_bytes(8, 'little')
    ct_len_bytes = (len(ciphertext)).to_bytes(8, 'little')
    mac_data = ciphertext + pad + aad_len_bytes + ct_len_bytes

    expected_tag = poly1305_mac(poly_key, mac_data)
    if not constant_time_compare(expected_tag, tag):
        raise ValueError("Tag mismatch - decryption failed")

    plaintext = chacha20_xor_stream(key, nonce, initial_counter, ciphertext)
    return plaintext

# ------------------ 文件级操作：覆盖原文件，写入 nonce||ciphertext||tag ------------------

def encrypt_file_inplace_no_check(path: str, key: bytes) -> Tuple[str, str]:
    # 读取全部文件内容
    f = open(path, "rb")
    try:
        plaintext = f.read()
    finally:
        f.close()

    # 生成随机 nonce（12 字节）
    nonce = secrets.token_bytes(12)

    # 加密，得到 ciphertext 和 tag
    ciphertext, tag = encrypt(key, nonce, plaintext)

    # 写回原文件（覆盖），格式： nonce || ciphertext || tag
    fo = open(path, "wb")
    try:
        fo.write(nonce)
        fo.write(ciphertext)
        fo.write(tag)
    finally:
        fo.close()

    return path, path

def decrypt_file_inplace_no_check(path: str, key: bytes) -> Tuple[str, str]:
    # 读取全部文件内容
    f = open(path, "rb")
    try:
        data = f.read()
    finally:
        f.close()

    # 检查长度至少包含 nonce(12) + tag(16)
    if len(data) < 28:
        raise ValueError("File too short to be encrypted format")

    # 提取 nonce、ciphertext、tag
    nonce = data[:12]
    tag = data[-16:]
    ciphertext = data[12:-16]

    # 解密并验证标签
    plaintext = decrypt(key, nonce, ciphertext, tag)

    # 写回原文件（覆盖）明文
    fo = open(path, "wb")
    try:
        fo.write(plaintext)
    finally:
        fo.close()

    return path, path

# ------------------ 目录遍历与多线程（非命令行调用） ------------------

def encrypt_directory(root: str, key: bytes, workers: int = 4, dry_run: bool = False):
    # root 必须存在
    if not os.path.exists(root):
        raise FileNotFoundError("Root path does not exist: " + root)

    # 收集所有文件路径（显式循环，不用嵌套表达式）
    all_paths = []
    walker = os.walk(root)
    for dirpath, dirnames, filenames in walker:
        i = 0
        while i < len(filenames):
            name = filenames[i]
            i += 1
            full = os.path.join(dirpath, name)
            all_paths.append(full)

    if dry_run:
        idx = 0
        while idx < len(all_paths):
            p = all_paths[idx]
            idx += 1
            print("DRY ENCRYPT:", p, "-> (inplace overwrite)")
        return

    # 使用线程池并发加密
    executor = ThreadPoolExecutor(max_workers=workers)
    futures = []
    idx = 0
    while idx < len(all_paths):
        p = all_paths[idx]
        idx += 1
        fut = executor.submit(encrypt_file_inplace_no_check, p, key)
        futures.append(fut)

    # 等待完成并打印结果
    for fut in as_completed(futures):
        try:
            src, out = fut.result()
            print("ENCRYPT:", src, "->", out)
        except Exception as e:
            print("ERROR ENCRYPT:", str(e))

    executor.shutdown(wait=True)

def decrypt_directory(root: str, key: bytes, workers: int = 4, dry_run: bool = False):
    # root 必须存在
    if not os.path.exists(root):
        raise FileNotFoundError("Root path does not exist: " + root)

    all_paths = []
    walker = os.walk(root)
    for dirpath, dirnames, filenames in walker:
        i = 0
        while i < len(filenames):
            name = filenames[i]
            i += 1
            full = os.path.join(dirpath, name)
            all_paths.append(full)

    if dry_run:
        idx = 0
        while idx < len(all_paths):
            p = all_paths[idx]
            idx += 1
            print("DRY DECRYPT:", p, "-> (inplace overwrite attempt)")
        return

    executor = ThreadPoolExecutor(max_workers=workers)
    futures = []
    idx = 0
    while idx < len(all_paths):
        p = all_paths[idx]
        idx += 1
        fut = executor.submit(decrypt_file_inplace_no_check, p, key)
        futures.append(fut)

    for fut in as_completed(futures):
        try:
            src, out = fut.result()
            print("DECRYPT:", src, "->", out)
        except Exception as e:
            print("ERROR DECRYPT:", str(e))
    executor.shutdown(wait=True)
# ------------------ 示例调用 ------------------
if __name__ == "__main__":
    # 示例密钥（仅示范，请替换为你的密钥并妥善保管）
    example_key = bytes.fromhex("000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f")
    # 示例：dry run（不实际写入）
    try:
        print("Dry-run encrypt current dir:")
        encrypt_directory(".", example_key, workers=4, dry_run=True)
        print("Dry-run decrypt current dir:")
        decrypt_directory(".", example_key, workers=4, dry_run=True)
    except Exception as ex:
        print("示例运行错误:", str(ex))
