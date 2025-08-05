#!/bin/bash

# 脚本名称：setup-network-tools-and-systemd-resolved.sh
# 功能：
#  - 更新软件源
#  - 安装全面的网络相关工具（包括抓包和流量监控）
#  - 配置 systemd-resolved DNS over TLS
#  - 开启 BBR
#  - 其他网络参数提示
# 适用环境：基于 systemd 的 Linux 发行版（Ubuntu/Debian/CentOS/RHEL）
# 需 root 权限运行
set -e

echo "===== 1. 检查发行版和包管理器 ====="

PKG_INSTALL=""
UPDATE_CMD=""
IS_DEBIAN=false
IS_CENTOS=false

if [ -f /etc/debian_version ]; then
    IS_DEBIAN=true
    PKG_INSTALL="apt-get install -y"
    UPDATE_CMD="apt-get update"
elif [ -f /etc/redhat-release ]; then
    IS_CENTOS=true
    PKG_INSTALL="yum install -y"
    UPDATE_CMD="yum makecache"
else
    echo "不支持的发行版，请手动安装相关软件包。"
    exit 1
fi

echo "使用的软件包管理器为: $([ $IS_DEBIAN = true ] && echo apt 或 echo yum)"

echo
echo "===== 2. 更新软件包缓存 ====="
$UPDATE_CMD

echo
echo "===== 3. 安装全面的网络工具包 ====="
if [ "$IS_DEBIAN" = true ]; then
    $PKG_INSTALL \
    iproute2 net-tools curl wget git dnsutils tcpdump iputils-ping traceroute \
    nmap netcat iptables ethtool iftop htop mtr whois wireshark tshark bind9-host \
    lsof ss nethogs bmon
elif [ "$IS_CENTOS" = true ]; then
    $PKG_INSTALL \
    iproute net-tools curl wget git bind-utils tcpdump iputils traceroute nmap nc iptables \
    ethtool iftop htop mtr whois wireshark-cli lsof iproute ipset ss nethogs bmon
fi

echo
echo "===== 4. 启用并启动 systemd-resolved ====="
if ! systemctl is-enabled systemd-resolved >/dev/null 2>&1; then
    echo "启用 systemd-resolved 服务"
    systemctl enable --now systemd-resolved
else
    echo "systemd-resolved 服务已启用"
fi

echo
echo "===== 5. 备份 systemd-resolved 配置文件 ====="
if [ -f /etc/systemd/resolved.conf ]; then
    cp /etc/systemd/resolved.conf /etc/systemd/resolved.conf.bak.$(date +%F-%T)
    echo "备份完成"
else
    echo "未找到 /etc/systemd/resolved.conf，跳过备份"
fi

echo
echo "===== 6. 配置 systemd-resolved 启用 DNS over TLS ====="
cat > /etc/systemd/resolved.conf << EOF
[Resolve]
DNS=1.1.1.1 9.9.9.9
FallbackDNS=8.8.8.8 1.0.0.1
DNSOverTLS=yes
DNSSEC=yes
DNSStubListener=yes
EOF
echo "配置写入 /etc/systemd/resolved.conf"

echo
echo "===== 7. 确保 /etc/resolv.conf 指向 systemd stub ====="
if [ -L /etc/resolv.conf ] && readlink /etc/resolv.conf | grep -q "stub-resolv.conf"; then
    echo "/etc/resolv.conf 已正确指向 stub-resolv.conf"
else
    echo "重新创建 /etc/resolv.conf 符号链接"
    rm -f /etc/resolv.conf
    ln -s /run/systemd/resolve/stub-resolv.conf /etc/resolv.conf
fi

echo
echo "===== 8. 重启 systemd-resolved 服务 ====="
systemctl restart systemd-resolved
sleep 2
echo "验证 DNS 状态："
resolvectl status | grep -E 'Current DNS|DNS over TLS|DNSSEC'

echo
echo "===== 9. 测试 DNS 解析功能 ====="
echo "resolvectl query www.example.com"
resolvectl query www.example.com

echo
echo "===== 10. 启用 BBR TCP 拥塞控制 ====="
current_cc=$(sysctl -n net.ipv4.tcp_congestion_control)
if [ "$current_cc" == "bbr" ]; then
    echo "BBR 已启用"
else
    echo "加载 tcp_bbr 模块"
    modprobe tcp_bbr || echo "警告：内核不支持 tcp_bbr 模块，需升级内核。"
    grep -q "^net.core.default_qdisc=fq" /etc/sysctl.conf || echo "net.core.default_qdisc=fq" >> /etc/sysctl.conf
    grep -q "^net.ipv4.tcp_congestion_control=bbr" /etc/sysctl.conf || echo "net.ipv4.tcp_congestion_control=bbr" >> /etc/sysctl.conf
    sysctl -p
    echo "当前 TCP 拥塞控制算法：$(sysctl net.ipv4.tcp_congestion_control | awk '{print $3}')"
fi

echo
echo "===== 11. 网络调优参数（请根据需要手动调整） ====="
echo "# 以下参数示例，可按需添加到 /etc/sysctl.conf 并执行 sysctl -p"
cat <<'EOT'
net.core.somaxconn=1024
net.ipv4.tcp_fin_timeout=15
net.ipv4.tcp_tw_reuse=1
net.ipv4.tcp_keepalive_time=300
net.ipv4.tcp_max_syn_backlog=4096
net.ipv4.tcp_syncookies=1
net.ipv4.ip_local_port_range=1024 65000
EOT

echo
echo "===== 12. 完成 ====="
echo "建议重启系统使所有设置生效"
echo "可用命令查看 network tools 版本和服务状态，例如："
echo "  tcpdump --version"
echo "  wireshark --version"
echo "  resolvectl status"
echo "  sysctl net.ipv4.tcp_congestion_control"
echo
echo "更多网络工具详见各自官方文档。"

exit 0
