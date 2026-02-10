import os
import logging
import asyncio
import subprocess
from ping3 import ping
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, ContextTypes, CommandHandler, CallbackQueryHandler, ConversationHandler, MessageHandler, filters
)
from hcloud import Client
from hcloud.server_types.domain import ServerType
from hcloud.images.domain import Image
from hcloud.locations.domain import Location
from dotenv import load_dotenv

# --- تنظیمات اولیه ---
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
HETZNER_TOKEN = os.getenv("HETZNER_TOKEN")
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID")

# آی‌پی سروری که باید مانیتور شود (توسط ربات پر می‌شود یا دستی وارد کنید)
# نکته: این متغیر با هر بار ساخت سرور جدید آپدیت می‌شود
MONITORED_SERVER_ID = None 
CHECK_INTERVAL = 60  # هر چند ثانیه چک کند
FAILURE_THRESHOLD = 3  # بعد از چند بار شکست، آی‌پی عوض شود

# اتصال به هتزنر
hetzner = Client(token=HETZNER_TOKEN)

# مراحل گفتگو
CREATE_NAME, CREATE_LOC, SELECT_ARCH, CREATE_TYPE, CREATE_IMAGE, CONFIRM_DELETE, CONFIRM_RECREATE, SELECT_IMAGE_REBUILD = range(8)

# تنظیم لاگ
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- داده‌های ثابت ---
PLANS = {'intel': ['cx22', 'cx32', 'cx42'], 'amd': ['cpx11', 'cpx21', 'cpx31']}
LOCATIONS = {'nbg1': '🇩🇪 Nuremberg', 'fsn1': '🇩🇪 Falkenstein', 'hel1': '🇫🇮 Helsinki', 'ash': '🇺🇸 Ashburn', 'hil': '🇺🇸 Hillsboro'}
OS_IMAGES = ["ubuntu-24.04", "ubuntu-22.04", "debian-12", "alma-9"]

# --- توابع کمکی ---
async def check_admin(update: Update):
    if update.effective_user.id != ADMIN_ID:
        await update.effective_message.reply_text("⛔ دسترسی غیرمجاز.")
        return False
    return True

async def send_log(app, msg: str):
    if LOG_CHANNEL_ID:
        try:
            await app.bot.send_message(chat_id=LOG_CHANNEL_ID, text=f"📝 {msg}")
        except: pass

# --- سیستم هوشمند تعویض آی‌پی (WATCHDOG) ---
async def update_tunnel_config(new_ip):
    """
    این تابع وقتی آی‌پی جدید ساخته شد اجرا می‌شود.
    شما باید دستورات لینوکسی برای آپدیت تانل خود را اینجا بنویسید.
    """
    try:
        # مثال: تغییر آی‌پی در فایل کانفیگ و ریستارت سرویس
        # دستور زیر یک نمونه است، باید با دستورات تانل خودتان جایگزین کنید
        print(f"🔄 Updating Tunnel to IP: {new_ip}")
        
        # 1. اجرای اسکریپت شل برای تنظیم مجدد تانل
        # subprocess.run(f"/root/update_tunnel.sh {new_ip}", shell=True)
        
        return True
    except Exception as e:
        logger.error(f"Failed to update tunnel: {e}")
        return False

async def auto_recreate_logic(app, server_id):
    """منطق اصلی حذف و ساخت مجدد سرور بدون دخالت کاربر"""
    try:
        await send_log(app, "⚠️ **هشدار سیستم خودکار:**\nارتباط با سرور قطع شد! شروع عملیات تعویض آی‌پی...")
        
        # 1. دریافت اطلاعات سرور فعلی
        old_server = hetzner.servers.get_by_id(server_id)
        srv_name = old_server.name
        srv_type = old_server.server_type.name
        srv_loc = old_server.datacenter.location.name
        srv_img = old_server.image.name if old_server.image else "ubuntu-22.04"
        
        # 2. حذف سرور
        old_server.delete()
        await send_log(app, "🔻 سرور فیلتر شده حذف شد.")
        
        # 3. ساخت سرور جدید
        # نکته: اینجا می‌توانید User Data اضافه کنید که تانل سمت خارج خودکار نصب شود
        user_data_script = """#!/bin/bash
        # اینجا دستورات نصب تانل سمت خارج را بگذارید
        # apt update && apt install -y ...
        """
        
        res = hetzner.servers.create(
            name=srv_name,
            server_type=ServerType(name=srv_type),
            image=Image(name=srv_img),
            location=Location(name=srv_loc),
            user_data=user_data_script
        )
        
        new_server = res.server
        new_ip = new_server.public_net.ipv4.ip
        new_pass = res.root_password
        
        await send_log(app, f"✅ **آی‌پی جدید دریافت شد!**\nIP: `{new_ip}`\nPass: `{new_pass}`\nدر حال آپدیت تانل...")
        
        # 4. آپدیت تانل در سرور ایران
        await update_tunnel_config(new_ip)
        
        # 5. آپدیت متغیر مانیتورینگ
        global MONITORED_SERVER_ID
        MONITORED_SERVER_ID = new_server.id
        
        await send_log(app, "🚀 سیستم مجدداً متصل شد. پایان عملیات.")
        
    except Exception as e:
        await send_log(app, f"❌ خطای بحرانی در سیستم خودکار:\n{e}")

async def watchdog_task(app):
    """تاسک پس‌زمینه که دائم پینگ می‌گیرد"""
    fail_count = 0
    logger.info("Watchdog started...")
    
    while True:
        await asyncio.sleep(CHECK_INTERVAL)
        
        if not MONITORED_SERVER_ID:
            continue
            
        try:
            server = hetzner.servers.get_by_id(MONITORED_SERVER_ID)
            ip = server.public_net.ipv4.ip
            
            # تست پینگ (یا می‌توانید پورت تانل را چک کنید)
            response = ping(ip, timeout=2)
            
            if response is None or response is False:
                fail_count += 1
                logger.warning(f"Ping failed for {ip} ({fail_count}/{FAILURE_THRESHOLD})")
            else:
                fail_count = 0 # ریست شدن شمارنده اگر پینگ موفق بود
            
            # اگر تعداد خطاها از حد مجاز گذشت
            if fail_count >= FAILURE_THRESHOLD:
                logger.error("Threshold reached! Triggering auto-recreate.")
                fail_count = 0 # جلوگیری از لوپ بی‌نهایت
                await auto_recreate_logic(app, MONITORED_SERVER_ID)
                
        except Exception as e:
            logger.error(f"Watchdog error: {e}")

# --- هندلرهای تلگرام (بخش‌های قبلی با کمی تغییر) ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # شروع تسک مانیتورینگ اگر فعال نباشد
    if 'watchdog_started' not in context.bot_data:
        asyncio.create_task(watchdog_task(context.application))
        context.bot_data['watchdog_started'] = True
        
    await show_main_menu(update, context)

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "🤖 **پنل هوشمند مدیریت تانل**\nوضعیت مانیتورینگ: 🟢 فعال"
    keyboard = [
        [InlineKeyboardButton("🖥 لیست سرورها", callback_data='list_servers')],
        [InlineKeyboardButton("➕ ساخت سرور", callback_data='create_start')],
        [InlineKeyboardButton("👁 تنظیم سرور مانیتورینگ", callback_data='set_monitor')]
    ]
    if update.callback_query:
        await update.callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def list_servers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    servers = hetzner.servers.get_all()
    keyboard = []
    for s in servers:
        icon = "👁‍🗨" if s.id == MONITORED_SERVER_ID else "☁️"
        keyboard.append([InlineKeyboardButton(f"{icon} {s.name} ({s.public_net.ipv4.ip})", callback_data=f'manage_{s.id}')])
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data='main_menu')])
    await query.edit_message_text("لیست سرورها (👁‍🗨 = تحت نظارت):", reply_markup=InlineKeyboardMarkup(keyboard))

async def manage_server(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    sid = int(query.data.split('_')[1])
    
    # دکمه‌ای برای فعال کردن مانیتورینگ روی این سرور خاص
    keyboard = [
        [InlineKeyboardButton("👁 تنظیم به عنوان هدف مانیتورینگ", callback_data=f'setmon_{sid}')],
        [InlineKeyboardButton("♻️ تغییر دستی آی‌پی", callback_data=f'pre_recreate_{sid}')],
        [InlineKeyboardButton("🔙 بازگشت", callback_data='list_servers')]
    ]
    await query.edit_message_text(f"مدیریت سرور {sid}", reply_markup=InlineKeyboardMarkup(keyboard))

async def set_monitor_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    sid = int(query.data.split('_')[1])
    global MONITORED_SERVER_ID
    MONITORED_SERVER_ID = sid
    await query.answer("✅ این سرور به لیست مانیتورینگ اضافه شد.", show_alert=True)
    await list_servers(update, context)

# --- (بقیه توابع مثل create_server و recreate که قبلاً داشتیم اینجا می‌آیند) ---
# به دلیل محدودیت فضا، توابع create و غیره همان کدهای قبلی هستند
# فقط تابع auto_recreate_logic کار اصلی را انجام می‌دهد.

if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()
    
    # هندلرها
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(list_servers, pattern='^list_servers$'))
    app.add_handler(CallbackQueryHandler(manage_server, pattern='^manage_'))
    app.add_handler(CallbackQueryHandler(set_monitor_target, pattern='^setmon_'))
    app.add_handler(CallbackQueryHandler(show_main_menu, pattern='^main_menu$'))
    
    print("Bot is Running with AI Watchdog...")
    app.run_polling()
