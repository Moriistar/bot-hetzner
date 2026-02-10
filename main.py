import os
import logging
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, CallbackQueryHandler
from hcloud import Client
from hcloud.images import Image
from hcloud.server_types import ServerType

# تنظیمات لاگینگ
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# بارگذاری متغیرها
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
HETZNER_TOKEN = os.getenv("HETZNER_TOKEN")

# اتصال به هتزنر
hclient = Client(token=HETZNER_TOKEN)

# --- توابع کمکی ---
def check_admin(user_id):
    return user_id == ADMIN_ID

def get_server_keyboard(server_id):
    """ساخت دکمه‌های مدیریتی برای یک سرور"""
    keyboard = [
        [
            InlineKeyboardButton("🟢 روشن کردن", callback_data=f"on_{server_id}"),
            InlineKeyboardButton("🔴 خاموش کردن", callback_data=f"off_{server_id}"),
        ],
        [
            InlineKeyboardButton("🔄 ریبوت (Reset)", callback_data=f"reset_{server_id}"),
            InlineKeyboardButton("♻️ نصب مجدد OS", callback_data=f"rebuild_{server_id}"),
        ],
        [
            InlineKeyboardButton("🗑 حذف سرور", callback_data=f"del_confirm_{server_id}"),
            InlineKeyboardButton("🔙 بازگشت", callback_data="list_servers"),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

# --- هندلرها ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_admin(update.effective_user.id):
        return
    
    keyboard = [[InlineKeyboardButton("🖥 لیست سرورها", callback_data="list_servers")]]
    await update.message.reply_text(
        "👋 سلام رئیس! به پنل مدیریت هتزنر خوش آمدید.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def list_servers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    try:
        servers = hclient.servers.get_all()
        if not servers:
            await query.edit_message_text("❌ هیچ سروری یافت نشد.")
            return

        keyboard = []
        for server in servers:
            status_icon = "🟢" if server.status == "running" else "🔴"
            # نمایش نام سرور + آی‌پی
            btn_text = f"{status_icon} {server.name} ({server.public_net.ipv4.ip})"
            keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"srv_{server.id}")])
        
        keyboard.append([InlineKeyboardButton("🔄 بروزرسانی لیست", callback_data="list_servers")])
        
        await query.edit_message_text(
            "📋 لیست سرورهای فعال شما:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        await query.edit_message_text(f"خطا در دریافت لیست: {str(e)}")

async def server_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    server_id = int(query.data.split("_")[1])
    try:
        server = hclient.servers.get_by_id(server_id)
        
        info = (
            f"🖥 **نام سرور:** `{server.name}`\n"
            f"🌐 **IP:** `{server.public_net.ipv4.ip}`\n"
            f"💡 **وضعیت:** {server.status}\n"
            f"📍 **دیتاسنتر:** {server.datacenter.name}\n"
            f"💾 **ایمیج:** {server.image.name if server.image else 'Unknown'}\n"
            f"⚙️ **مدل:** {server.server_type.name}"
        )
        
        await query.edit_message_text(
            info,
            reply_markup=get_server_keyboard(server_id),
            parse_mode="Markdown"
        )
    except Exception as e:
        await query.edit_message_text(f"خطا: {str(e)}")

async def server_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    action, server_id = data.split("_")[0], int(data.split("_")[1])
    server = hclient.servers.get_by_id(server_id)

    try:
        if action == "on":
            server.power_on()
            await query.answer("دستور روشن شدن ارسال شد ✅", show_alert=True)
        
        elif action == "off":
            server.power_off()
            await query.answer("دستور خاموش شدن ارسال شد 💤", show_alert=True)
            
        elif action == "reset":
            server.reset()
            await query.answer("سرور ریست شد 🔄", show_alert=True)
            
        elif action == "rebuild":
            # برای سادگی فعلا اوبونتو 22.04 را پیش‌فرض می‌گیریم
            # در نسخه حرفه‌ای‌تر می‌توان منوی انتخاب سیستم عامل گذاشت
            keyboard = [
                [InlineKeyboardButton("⚠️ بله، نصب کن (Ubuntu 22.04)", callback_data=f"confirmrebuild_{server_id}")],
                [InlineKeyboardButton("❌ لغو", callback_data=f"srv_{server_id}")]
            ]
            await query.edit_message_text(
                "⚠️ **هشدار:** با نصب مجدد، تمام اطلاعات سرور پاک می‌شود!\nآیا مطمئن هستید؟",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
            return

        elif action == "confirmrebuild":
            image = hclient.images.get_by_name("ubuntu-22.04")
            server.rebuild(image=image)
            await query.edit_message_text("✅ دستور نصب مجدد سیستم عامل صادر شد.\nپسورد جدید به ایمیل شما ارسال می‌شود.", 
                                          reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="list_servers")]]))
            return

        elif action == "del": # مرحله تایید حذف
            # این هندلر در پایین جداگانه هندل می‌شود اما اینجا برای یکپارچگی ذکر شد
            pass

        # بروزرسانی صفحه
        await server_details(update, context)

    except Exception as e:
        await query.answer(f"خطا: {str(e)}", show_alert=True)

async def delete_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    server_id = int(query.data.split("_")[2])
    
    keyboard = [
        [InlineKeyboardButton("💀 بله، حذف کن Forever", callback_data=f"realdelete_{server_id}")],
        [InlineKeyboardButton("❌ منصرف شدم", callback_data=f"srv_{server_id}")]
    ]
    await query.edit_message_text(
        "🚨 **هشدار بسیار جدی** 🚨\n\nآیا مطمئن هستید که می‌خواهید این سرور را کامل حذف کنید؟\nاین عملیات غیرقابل بازگشت است!",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def real_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    server_id = int(query.data.split("_")[1])
    try:
        hclient.servers.get_by_id(server_id).delete()
        await query.edit_message_text("🗑 سرور با موفقیت حذف شد.", 
                                      reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به لیست", callback_data="list_servers")]]))
    except Exception as e:
        await query.edit_message_text(f"خطا در حذف: {str(e)}")

# --- اجرای برنامه ---
if __name__ == '__main__':
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(list_servers, pattern="^list_servers$"))
    app.add_handler(CallbackQueryHandler(server_details, pattern="^srv_"))
    app.add_handler(CallbackQueryHandler(delete_confirm, pattern="^del_confirm_"))
    app.add_handler(CallbackQueryHandler(real_delete, pattern="^realdelete_"))
    app.add_handler(CallbackQueryHandler(server_actions, pattern="^(on|off|reset|rebuild|confirmrebuild)_"))

    print("Bot is running...")
    app.run_polling()
