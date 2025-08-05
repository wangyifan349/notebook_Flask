#!/bin/bash

set -e

echo "===== 更新软件包缓存 ====="
apt-get update

echo "===== 安装中文字体 ====="
apt-get install -y fonts-noto-cjk fonts-wqy-zenhei fonts-wqy-microhei fonts-noto fonts-dejavu fonts-cantarell

echo "===== 安装输入法 (fcitx 及常用拼音输入法) ====="
apt-get install -y fcitx fcitx-pinyin fcitx-googlepinyin fcitx-table-wubi im-config

echo "===== 安装 PGP 和 GPG 相关工具 ====="
apt-get install -y \
  gnupg gnupg2 gnupg-agent pinentry-curses pinentry-gtk2 pinentry-qt \
  seahorse kleopatra kgpg \
  gpgsm gpgme gpgv scdaemon dirmngr

echo "===== 安装邮件客户端 ====="
apt-get install -y thunderbird claws-mail evolution mutt neomutt

echo "===== 安装开源密码管理器 ====="
apt-get install -y keepassxc pass gnome-keyring seahorse

echo "===== 安装图像处理相关软件 ====="
apt-get install -y gimp inkscape darktable krita

echo "===== 安装视频播放器 ====="
apt-get install -y vlc mpv smplayer

echo "===== 安装图像处理及视频处理相关工具 ====="
apt-get install -y gimp inkscape darktable krita imagemagick ffmpeg handbrake
echo "===== 安装压缩与解压工具 ====="
apt-get install -y p7zip-full p7zip-rar unrar zip unzip xz-utils arj lzma cabextract file-roller

echo "===== 安装办公软件 ====="
apt-get install -y libreoffice
apt-get update
apt-get install -y curl gnupg apt-transport-https software-properties-common
#!/bin/bash
sudo apt install apt-transport-https

echo "deb [arch=amd64 signed-by=/usr/share/keyrings/deb.torproject.org-keyring.gpg] https://deb.torproject.org/torproject.org $(lsb_release -sc) main" | sudo tee /etc/apt/sources.list.d/tor-project.list


set -e
# 创建APT仓库密钥存放目录（如果不存在）
sudo install -d -m 0755 /etc/apt/keyrings
# 导入Mozilla APT仓库签名密钥
if ! command -v wget >/dev/null 2>&1; then
    echo "wget 未安装，正在安装 wget ..."
    sudo apt-get update
    sudo apt-get install -y wget
fi
wget -q https://packages.mozilla.org/apt/repo-signing-key.gpg -O- | sudo tee /etc/apt/keyrings/packages.mozilla.org.asc > /dev/null
# 验证指纹，确保密钥正确
EXPECTED_FINGERPRINT="35BAA0B33E9EB396F59CA838C0BA5CE6DC6315A3"
ACTUAL_FINGERPRINT=$(gpg -n -q --import --import-options import-show /etc/apt/keyrings/packages.mozilla.org.asc | awk '/pub/{getline; gsub(/^ +| +$/,""); print $0}')
if [ "$ACTUAL_FINGERPRINT" = "$EXPECTED_FINGERPRINT" ]; then
    echo "密钥指纹匹配：$ACTUAL_FINGERPRINT"
else
    echo "密钥指纹验证失败！实际是：$ACTUAL_FINGERPRINT"
    echo "预期是：$EXPECTED_FINGERPRINT"
    echo "请检查密钥文件是否正确！"
    exit 1
fi
# 添加Mozilla APT仓库到sources.list.d
echo "deb [signed-by=/etc/apt/keyrings/packages.mozilla.org.asc] https://packages.mozilla.org/apt mozilla main" | sudo tee /etc/apt/sources.list.d/mozilla.list > /dev/null
# 优先使用Mozilla仓库的包
sudo tee /etc/apt/preferences.d/mozilla >/dev/null <<'EOF'
Package: *
Pin: origin packages.mozilla.org
Pin-Priority: 1000
EOF
# 更新软件包列表并安装Firefox
sudo apt-get update
sudo apt-get install -y firefox
sudo apt install curl
sudo curl -fsSLo /usr/share/keyrings/brave-browser-archive-keyring.gpg https://brave-browser-apt-release.s3.brave.com/brave-browser-archive-keyring.gpg
sudo curl -fsSLo /etc/apt/sources.list.d/brave-browser-release.sources https://brave-browser-apt-release.s3.brave.com/brave-browser.sources
sudo apt update
sudo apt install brave-browser




echo "===== 配置 Vim 支持粘贴模式 ====="
VIMRC="$HOME/.vimrc"
if [ ! -f "$VIMRC" ]; then
    touch "$VIMRC"
fi

if ! grep -q 'set pastetoggle' "$VIMRC"; then
    cat >> "$VIMRC" << 'EOF'

" 支持粘贴模式切换 (F2)
set pastetoggle=<F2>
set mouse=a
EOF
fi

echo "===== 脚本完成 ====="
exit 0
