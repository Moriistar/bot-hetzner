#!/bin/bash

# رنگ‌ها
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}=== نصب ربات مدیریت هتزنر (MoriiStar) ===${NC}"

# بررسی روت
if [ "$EUID" -ne 0 ]; then
  echo "لطفاً با دسترسی روت اجرا کنید (sudo)."
  exit
fi

# نصب پکیج‌ها
echo -e "${GREEN}>> نصب پیش‌نیازها...${NC}"
apt-get update -y
apt-get install -y python3 python3-pip python3-venv git

# مسیر نصب
INSTALL_DIR="/opt/bot-hetzner"

# کلون یا آپدیت
if [ -d "$INSTALL_DIR" ]; then
    echo -e "${BLUE}>> آپدیت پروژه...${NC}"
    cd $INSTALL_DIR
    git pull
else
    echo -e "${GREEN}>> دانلود پروژه...${NC}"
    git clone https://github.com/MoriiStar/bot-hetzner.git $INSTALL_DIR
    cd $INSTALL_DIR
fi

# محیط مجازی
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi

source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# دریافت متغیرها
echo -e "${BLUE}=== تنظیمات ===${NC}"

setup_env() {
    read -p "توکن ربات تلگرام: " BOT_TOKEN
    read -p "آیدی عددی ادمین: " ADMIN_ID
    read -p "توکن هتزنر (API Token): " HETZNER_TOKEN
    read -p "آیدی کانال لاگ: " LOG_CHANNEL_ID

    cat <<EOF > .env
BOT_TOKEN=$BOT_TOKEN
ADMIN_ID=$ADMIN_ID
HETZNER_TOKEN=$HETZNER_TOKEN
LOG_CHANNEL_ID=$LOG_CHANNEL_ID
EOF
}

if [ -f ".env" ]; then
    read -p "تنظیمات موجود است. تغییر میدهید؟ (y/n): " reconfig
    if [[ "$reconfig" =~ ^[Yy]$ ]]; then
        setup_env
    fi
else
    setup_env
fi

# سرویس سیستم‌دی
echo -e "${GREEN}>> ساخت سرویس...${NC}"
SERVICE_FILE="/etc/systemd/system/bot-hetzner.service"

cat <<EOF > $SERVICE_FILE
[Unit]
Description=Hetzner Manager Bot by MoriiStar
After=network.target

[Service]
User=root
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/venv/bin/python main.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable bot-hetzner
systemctl restart bot-hetzner

echo -e "${GREEN}نصب تمام شد! ربات در حال اجراست.${NC}"
