import os
import logging
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

# 1. بارگذاری متغیرها از فایل .env (که توسط install.sh ساخته شده)
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")
HETZNER_TOKEN = os.getenv("HETZNER_TOKEN")
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID")

# بررسی اینکه توکن‌ها موجود باشند
if not BOT_TOKEN:
    print("خطا: فایل .env یافت نشد یا توکن خالی است. لطفا install.sh را اجرا کنید.")
    exit()

# تنظیمات لاگ
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# --- اینجا کدهای اصلی ربات شما شروع می‌شود ---
# توابع start, change_ip, create_server و دکمه‌های شیشه‌ای خود را اینجا بنویسید
# مثال ساده برای تست:

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id != ADMIN_ID:
        await update.message.reply_text("شما ادمین نیستید!")
        return
        
    keyboard = [
        [InlineKeyboardButton("تغییر آی‌پی", callback_data='change_ip')],
        [InlineKeyboardButton("ساخت سرور", callback_data='create_server')],
        [InlineKeyboardButton("کنسل", callback_data='cancel')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(f"سلام رئیس! به پنل هتزنر خوش آمدید.\nآیدی شما: {user_id}", reply_markup=reply_markup)

if __name__ == '__main__':
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    
    start_handler = CommandHandler('start', start)
    application.add_handler(start_handler)
    
    # هندلرهای دیگر خود را اینجا اضافه کنید
    
    print("Bot is running...")
    application.run_polling()
