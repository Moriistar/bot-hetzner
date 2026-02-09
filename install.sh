#!/bin/bash

# رنگ‌ها
GREEN='\033[0;32m'
NC='\033[0m'

echo -e "${GREEN}=== Hetzner Bot Installer by MoriiStar ===${NC}"

# 1. بررسی و نصب پیش‌نیازها
echo "Updating system..."
sudo apt update && sudo apt install -y python3 python3-pip python3-venv git

# 2. دانلود پروژه (یا ساخت پوشه اگر دستی اجرا شود)
INSTALL_DIR="/opt/bot-hetzner"

if [ -d "$INSTALL_DIR" ]; then
    echo "Directory exists. Pulling latest changes..."
    cd $INSTALL_DIR
    git pull
else
    echo "Cloning repository..."
    # اگر ریپازیتوری هنوز عمومی نیست یا می‌خواهید فایل‌های لوکال را استفاده کنید، 
    # این قسمت به طور پیش‌فرض فرض می‌کند فایل‌ها دانلود شده‌اند.
    # اما برای دستور curl شما، ما اینجا کلون می‌کنیم:
    sudo git clone https://github.com/Moriistar/bot-hetzner.git $INSTALL_DIR
    cd $INSTALL_DIR
fi

# 3. ساخت محیط مجازی پایتون
echo "Setting up Python Virtual Environment..."
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 4. دریافت اطلاعات از کاربر
echo -e "${GREEN}--- Configuration ---${NC}"
read -p "Enter Telegram Bot Token: " BOT_TOKEN
read -p "Enter Admin Numeric ID: " ADMIN_ID
read -p "Enter Hetzner Cloud API Token: " HETZNER_TOKEN
read -p "Enter Log Channel ID (e.g., -100xxxx): " LOG_CHANNEL_ID

# 5. ذخیره در .env
cat > .env <<EOL
BOT_TOKEN=$BOT_TOKEN
ADMIN_ID=$ADMIN_ID
HETZNER_TOKEN=$HETZNER_TOKEN
LOG_CHANNEL_ID=$LOG_CHANNEL_ID
EOL

# 6. ساخت سرویس Systemd برای اجرای دائم
echo "Creating Systemd Service..."
SERVICE_FILE="/etc/systemd/system/hetznerbot.service"

sudo cat > $SERVICE_FILE <<EOL
[Unit]
Description=Hetzner Telegram Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/venv/bin/python $INSTALL_DIR/bot.py
Restart=always

[Install]
WantedBy=multi-user.target
EOL

# 7. فعال‌سازی و استارت
sudo systemctl daemon-reload
sudo systemctl enable hetznerbot
sudo systemctl restart hetznerbot

echo -e "${GREEN}✅ Bot installed and started successfully!${NC}"
echo "Check status with: systemctl status hetznerbot"
