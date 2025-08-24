#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <string.h>

// 计算模逆
int mod_inverse(int a, int p) {
    int m0 = p, t, q;
    int x0 = 0, x1 = 1;

    if (p == 1) return 0;

    while (a > 1) {
        q = a / p;
        t = p;

        p = a % p;
        a = t;
        t = x0;

        x0 = x1 - q * x0;
        x1 = t;
    }

    if (x1 < 0) x1 += m0;

    return x1;
}

// 计算 x 的 n 次方模 p
int power(int x, int n, int p) {
    int result = 1;
    x = x % p;
    while (n > 0) {
        if (n & 1) {
            result = (result * x) % p;
        }
        n = n >> 1;
        x = (x * x) % p;
    }
    return result;
}

// 生成多项式
void generate_polynomial(int secret, int t, int prime, int *coefficients) {
    coefficients[0] = secret; // 常数项为秘密
    for (int i = 1; i < t; i++) {
        coefficients[i] = rand() % prime; // 随机生成其他系数
    }
}

// 计算多项式在某个点的值
int evaluate_polynomial(int *coefficients, int x, int t, int prime) {
    int result = 0;
    for (int i = 0; i < t; i++) {
        result = (result + coefficients[i] * power(x, i, prime)) % prime;
    }
    return result;
}

// 生成份额
void generate_shares(int secret, int n, int t, int prime, int shares[][2]) {
    int coefficients[t];
    generate_polynomial(secret, t, prime, coefficients);
    for (int i = 1; i <= n; i++) {
        shares[i - 1][0] = i; // 份额的索引
        shares[i - 1][1] = evaluate_polynomial(coefficients, i, t, prime); // 计算多项式值
    }
}

// 拉格朗日插值
int lagrange_interpolation(int x, int *x_s, int *y_s, int t, int prime) {
    int total = 0;
    for (int i = 0; i < t; i++) {
        int xi = x_s[i];
        int yi = y_s[i];
        int term = yi;

        for (int j = 0; j < t; j++) {
            if (i != j) {
                term = (term * (x - x_s[j]) % prime * mod_inverse(xi - x_s[j], prime)) % prime;
            }
        }
        total = (total + term) % prime;
    }
    return total;
}

// 重建秘密
int reconstruct_secret(int shares[][2], int t, int prime) {
    int x_s[t], y_s[t];
    for (int i = 0; i < t; i++) {
        x_s[i] = shares[i][0];
        y_s[i] = shares[i][1];
    }
    return lagrange_interpolation(0, x_s, y_s, t, prime);
}

// 将字符串转换为整数（简单示例）
int string_to_int(const char *str) {
    int result = 0;
    for (int i = 0; str[i] != '\0'; i++) {
        result += (int)str[i]; // 将字符转换为整数
    }
    return result;
}

// 将整数转换为字符串（简单示例）
void int_to_string(int value, char *str) {
    sprintf(str, "%d", value);
}

// 主函数
int main() {
    srand(time(NULL)); // 初始化随机数生成器

    const char *secret_str = "my secret mnemonic"; // 要分享的秘密（助记词）
    int secret = string_to_int(secret_str); // 将字符串转换为整数
    int n = 10;         // 份额总数
    int t = 4;          // 阈值
    int prime = 7919;   // 大素数

    // 生成份额
    int shares[n][2];
    generate_shares(secret, n, t, prime, shares);

    printf("生成的份额:\n");
    for (int i = 0; i < n; i++) {
        printf("份额 %d: %d\n", shares[i][0], shares[i][1]);
    }

    // 随机选择 t 份份额进行重建
    int selected_shares[t][2];
    for (int i = 0; i < t; i++) {
        selected_shares[i][0] = shares[i][0];
        selected_shares[i][1] = shares[i][1];
    }

    // 重建秘密
    int recovered_secret = reconstruct_secret(selected_shares, t, prime);
    char recovered_str[50];
    int_to_string(recovered_secret, recovered_str);

    printf("重建的秘密: %s\n", recovered_str);

    // 验证重建的秘密是否与原始秘密匹配
    if (recovered_secret == secret) {
        printf("重建的秘密与原始秘密匹配！\n");
    } else {
        printf("重建的秘密与原始秘密不匹配！\n");
    }

    return 0;
}



