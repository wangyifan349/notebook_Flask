import os
import random
import numpy as np
import bip39
import bip32
import bitcoin

# 计算模逆
def mod_inverse(a, p):
    """计算 a 在模 p 下的逆元"""
    m0, x0, x1 = p, 0, 1
    if p == 1:
        return 0
    while a > 1:
        q = a // p
        m0, a = a, a % p
        x0, x1 = x1 - q * x0, m0
    if x1 < 0:
        x1 += p
    return x1

# 拉格朗日插值
def lagrange_interpolation(x, x_s, y_s, prime):
    """使用拉格朗日插值法重建秘密"""
    total = 0
    for i in range(len(x_s)):
        xi, yi = x_s[i], y_s[i]
        term = yi
        for j in range(len(x_s)):
            if i != j:
                term = (term * (x - x_s[j]) % prime * mod_inverse(xi - x_s[j], prime)) % prime
        total = (total + term) % prime
    return total

# 生成助记词
def generate_mnemonic():
    """生成助记词"""
    return bip39.generate_mnemonic()

# 将助记词转换为整数
def mnemonic_to_int(mnemonic):
    """将助记词转换为整数"""
    return sum(ord(c) for c in mnemonic)

# 生成份额
def generate_shares(secret, n, t, prime):
    """生成 n 份份额，阈值为 t"""
    coefficients = [random.randint(0, prime - 1) for _ in range(t - 1)]
    coefficients.insert(0, secret)  # 将秘密作为常数项
    shares = []
    for i in range(1, n + 1):
        share_value = sum(coef * (i ** idx) for idx, coef in enumerate(coefficients)) % prime
        shares.append((i, share_value))
    return shares

# 重建助记词
def reconstruct_mnemonic(shares, prime):
    """通过给定的份额重建助记词"""
    x_s, y_s = zip(*shares)
    secret = lagrange_interpolation(0, x_s, y_s, prime)
    return secret

# 从助记词生成私钥
def mnemonic_to_private_key(mnemonic):
    """从助记词生成私钥"""
    seed = bip39.mnemonic_to_seed(mnemonic)
    root_key = bip32.BIP32.from_seed(seed)
    private_key = root_key.get_privkey()
    return private_key

# 从私钥生成公钥
def private_key_to_public_key(private_key):
    """从私钥生成公钥"""
    public_key = bitcoin.privkey_to_pubkey(private_key)
    return public_key

# 从公钥生成比特币地址
def public_key_to_address(public_key):
    """从公钥生成比特币地址"""
    address = bitcoin.pubkey_to_address(public_key)
    return address

# 主程序
if __name__ == "__main__":
    # 生成助记词
    mnemonic = generate_mnemonic()
    print("生成的助记词:", mnemonic)

    # 将助记词转换为整数
    secret = mnemonic_to_int(mnemonic)
    print("助记词的整数表示:", secret)

    # 设置份额总数和阈值
    n = 10  # 份额总数
    t = 4   # 阈值
    prime = 7919  # 大素数

    # 生成份额
    shares = generate_shares(secret, n, t, prime)
    print("生成的份额:")
    for share in shares:
        print(f"份额 {share[0]}: {share[1]}")

    # 随机选择 t 份份额进行重建
    selected_shares = random.sample(shares, t)
    print("选择的份额:")
    for share in selected_shares:
        print(f"份额 {share[0]}: {share[1]}")
    # 重建助记词
    recovered_secret = reconstruct_mnemonic(selected_shares, prime)
    print("重建的助记词的整数表示:", recovered_secret)

    # 验证重建的助记词是否与原始助记词匹配
    if recovered_secret == secret:
        print("重建的助记词与原始助记词匹配！")
    else:
        print("重建的助记词与原始助记词不匹配！")

    # 从助记词生成私钥
    private_key = mnemonic_to_private_key(mnemonic)
    print("生成的私钥:", private_key.hex())

    # 从私钥生成公钥
    public_key = private_key_to_public_key(private_key)
    print("生成的公钥:", public_key)

    # 从公钥生成比特币地址
    address = public_key_to_address(public_key)
    print("生成的比特币地址:", address)
