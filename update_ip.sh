#!/bin/bash

GREEN='\033[0;32m'
NC='\033[0m'

echo -e "${GREEN}=== Intelligent Hetzner Bot Installer ===${NC}"

# 1. نصب پیش‌نیازها
echo "Updating system..."
sudo apt update && sudo apt install -y python3 python3-pip python3-venv git

# 2. مسیر نصب
INSTALL_DIR="/opt/bot-hetzner"

if [ -d "$INSTALL_DIR" ]; then
    echo "Updating existing installation..."
    cd $INSTALL_DIR
    git pull
else
    echo "Cloning repository..."
    # آدرس گیت‌هاب خودت رو اینجا چک کن که درست باشه
    sudo git clone https://github.com/Moriistar/bot-hetzner.git $INSTALL_DIR
    cd $INSTALL_DIR
fi

# 3. دسترسی اجرایی به اسکریپت آپدیت آی‌پی
chmod +x update_ip.sh

# 4. محیط مجازی پایتون
echo "Setting up Python Environment..."
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 5. دریافت اطلاعات (اگر فایل env نباشد)
if [ ! -f .env ]; then
    echo -e "${GREEN}--- Configuration ---${NC}"
    read -p "Enter Telegram Bot Token: " BOT_TOKEN
    read -p "Enter Admin Numeric ID: " ADMIN_ID
    read -p "Enter Hetzner Cloud API Token: " HETZNER_TOKEN
    read -p "Enter Log Channel ID (Optional): " LOG_CHANNEL_ID

    cat > .env <<EOL
BOT_TOKEN=$BOT_TOKEN
ADMIN_ID=$ADMIN_ID
HETZNER_TOKEN=$HETZNER_TOKEN
LOG_CHANNEL_ID=$LOG_CHANNEL_ID
EOL
fi

# 6. ساخت سرویس
echo "Creating Systemd Service..."
SERVICE_FILE="/etc/systemd/system/hetznerbot.service"

sudo cat > $SERVICE_FILE <<EOL
[Unit]
Description=Hetzner Smart Bot
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

# 7. اجرا
sudo systemctl daemon-reload
sudo systemctl enable hetznerbot
sudo systemctl restart hetznerbot

echo -e "${GREEN}✅ Bot installed and Watchdog is ACTIVE!${NC}"
