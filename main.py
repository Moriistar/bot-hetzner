import os
import logging
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes, ConversationHandler, MessageHandler, filters
from hcloud import Client
from hcloud.images.domain import Image
from hcloud.server_types.domain import ServerType

# --- 1. پیکربندی و متغیرها ---
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")
HETZNER_TOKEN = os.getenv("HETZNER_TOKEN")
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID")

# اتصال به هتزنر
hetzner = Client(token=HETZNER_TOKEN)

# تنظیمات لاگ
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# وضعیت‌های Conversation (برای ساخت سرور)
WAITING_FOR_NAME = 1

# --- 2. توابع کمکی ---
async def check_admin(update: Update):
    user_id = str(update.effective_user.id)
    if user_id != ADMIN_ID:
        await update.effective_message.reply_text("⛔ دسترسی غیرمجاز! این ربات شخصی است.")
        return False
    return True

async def send_log(context: ContextTypes.DEFAULT_TYPE, message: str):
    """ارسال گزارش کارها به کانال لاگ"""
    if LOG_CHANNEL_ID:
        try:
            await context.bot.send_message(chat_id=LOG_CHANNEL_ID, text=f"📝 #LOG\n{message}")
        except Exception as e:
            logger.error(f"Error sending log: {e}")

# --- 3. منوها و کیبوردها ---
def main_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("➕ ساخت سرور جدید", callback_data='create_server_start')],
        [InlineKeyboardButton("🖥 لیست سرورها", callback_data='list_servers')],
        [InlineKeyboardButton("ℹ️ درباره ربات", callback_data='about')],
    ]
    return InlineKeyboardMarkup(keyboard)

def back_button(target='main_menu'):
    return InlineKeyboardButton("🔙 برگشت", callback_data=target)

# --- 4. هندلرهای اصلی ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update): return

    text = (
        "👋 **سلام رئیس! به پنل مدیریت سرورهای هتزنر خوش اومدی.**\n\n"
        "از دکمه‌های زیر برای مدیریت استفاده کن:\n"
        "🔸 **ساخت سرور:** ایجاد سریع سرور ابری\n"
        "🔸 **لیست سرورها:** مدیریت، خاموش/روشن، حذف و...\n"
    )
    
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text=text, reply_markup=main_menu_keyboard(), parse_mode='Markdown')
    else:
        await update.message.reply_text(text=text, reply_markup=main_menu_keyboard(), parse_mode='Markdown')

# --- 5. لیست سرورها و مدیریت ---
async def list_servers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("در حال دریافت لیست سرورها...")

    try:
        servers = hetzner.servers.get_all()
        if not servers:
            keyboard = [[back_button()]]
            await query.edit_message_text("❌ هیچ سروری یافت نشد!", reply_markup=InlineKeyboardMarkup(keyboard))
            return

        keyboard = []
        for server in servers:
            status_emoji = "🟢" if server.status == "running" else "🔴"
            # دکمه برای هر سرور: نام سرور + آی‌پی
            btn_text = f"{status_emoji} {server.name} ({server.public_net.ipv4.ip})"
            keyboard.append([InlineKeyboardButton(btn_text, callback_data=f'manage_{server.id}')])
        
        keyboard.append([back_button()])
        await query.edit_message_text("🖥 **لیست سرورهای فعال:**\nبرای مدیریت روی سرور کلیک کنید:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

    except Exception as e:
        await query.edit_message_text(f"خطا در دریافت لیست: {str(e)}")

# --- 6. پنل مدیریت تکی سرور ---
async def manage_server(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    server_id = int(query.data.split('_')[1])
    try:
        server = hetzner.servers.get_by_id(server_id)
        if server is None:
            await query.edit_message_text("❌ سرور یافت نشد یا حذف شده است.", reply_markup=InlineKeyboardMarkup([[back_button('list_servers')]]))
            return

        info = (
            f"🖥 **Server:** `{server.name}`\n"
            f"🌐 **IP:** `{server.public_net.ipv4.ip}`\n"
            f"📍 **Location:** {server.datacenter.location.name}\n"
            f"💡 **Status:** {server.status}\n"
            f"💿 **Image:** {server.image.name if server.image else 'Unknown'}\n"
            f"🏷 **Type:** {server.server_type.name}"
        )

        keyboard = [
            [
                InlineKeyboardButton("🔄 ریستارت (Reboot)", callback_data=f'action_reboot_{server_id}'),
                InlineKeyboardButton("⚡ خاموش/روشن", callback_data=f'action_power_{server_id}')
            ],
            [
                InlineKeyboardButton("🛠 بازنشانی سیستم‌عامل (Rebuild)", callback_data=f'action_rebuild_{server_id}'),
            ],
            [
                InlineKeyboardButton("🗑 حذف سرور (Delete)", callback_data=f'action_delete_{server_id}')
            ],
            [back_button('list_servers')]
        ]
        
        await query.edit_message_text(info, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

    except Exception as e:
        await query.edit_message_text(f"Error: {str(e)}")

# --- 7. اکشن‌های سرور (ریستارت، حذف و...) ---
async def server_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data.split('_')
    action = data[1]
    server_id = int(data[2])
    
    # تاییدیه برای حذف و ریبیلد
    if action in ['delete', 'rebuild'] and len(data) == 3:
        # نمایش منوی تایید
        confirm_btn = InlineKeyboardButton("✅ بله، مطمئنم", callback_data=f'{query.data}_confirm')
        cancel_btn = InlineKeyboardButton("❌ لغو", callback_data=f'manage_{server_id}')
        await query.edit_message_text(
            f"⚠️ **هشدار جدی!**\nآیا از انجام عملیات `{action}` اطمینان دارید؟\nاین کار غیرقابل بازگشت است.", 
            reply_markup=InlineKeyboardMarkup([[confirm_btn, cancel_btn]]), 
            parse_mode='Markdown'
        )
        return

    try:
        server = hetzner.servers.get_by_id(server_id)
        msg = ""

        if action == 'reboot':
            await query.answer("در حال ارسال دستور ریستارت...")
            server.reset() # Hard reset
            msg = f"🔄 سرور {server.name} با موفقیت ریستارت شد."

        elif action == 'power':
            await query.answer("تغییر وضعیت پاور...")
            if server.status == 'running':
                server.power_off()
                msg = f"⚫ سرور {server.name} خاموش شد."
            else:
                server.power_on()
                msg = f"🟢 سرور {server.name} روشن شد."

        elif action == 'delete' and 'confirm' in data:
            await query.answer("در حال حذف...")
            name = server.name
            server.delete()
            msg = f"🗑 سرور `{name}` با موفقیت حذف شد."
            await send_log(context, f"Admin deleted server: {name}")
            await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup([[back_button('list_servers')]]))
            return

        elif action == 'rebuild' and 'confirm' in data:
            await query.answer("در حال نصب مجدد...")
            # پیش‌فرض اوبونتو 22.04 برای ریبیلد
            image = hetzner.images.get_by_name("ubuntu-22.04")
            server.rebuild(image=image)
            msg = f"🚧 سیستم عامل سرور {server.name} به Ubuntu 22.04 تغییر یافت (Rebuild).\nپسورد جدید به ایمیل شما ارسال شد."
            await send_log(context, f"Admin rebuilt server: {server.name}")

        await send_log(context, f"Action {action} performed on server {server.name}")
        
        # بازگشت به منوی مدیریت همان سرور
        await query.edit_message_text(f"✅ {msg}\n\nبرگشت به منو...", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("بازگشت", callback_data=f'manage_{server_id}')]]))

    except Exception as e:
        await query.edit_message_text(f"❌ خطا در انجام عملیات: {str(e)}", reply_markup=InlineKeyboardMarkup([[back_button('list_servers')]]))

# --- 8. پروسه ساخت سرور (Conversation) ---

async def create_server_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = [[InlineKeyboardButton("❌ کنسل", callback_data='cancel_process')]]
    await query.edit_message_text(
        "➕ **ساخت سرور جدید**\n\nلطفاً یک نام برای سرور خود بفرستید (انگلیسی):",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
    return WAITING_FOR_NAME

async def create_server_finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text
    user_id = str(update.effective_user.id)
    
    if user_id != ADMIN_ID: return ConversationHandler.END

    msg = await update.message.reply_text("⏳ در حال سفارش سرور (CX22 - Nuremberg - Ubuntu 22.04)...")
    
    try:
        # تنظیمات پیش‌فرض برای سرعت کار (می‌توانید بعداً منوی انتخاب لوکیشن اضافه کنید)
        # Location: Nuremberg (nbg1), Type: cx22 (ارزان‌ترین), Image: Ubuntu 22.04
        response = hetzner.servers.create(
            name=name,
            server_type=ServerType(name="cx22"),
            image=Image(name="ubuntu-22.04"),
            location=hetzner.locations.get_by_name("nbg1")
        )
        
        server = response.server
        root_pass = response.root_password
        
        text = (
            f"✅ **سرور با موفقیت ساخته شد!**\n\n"
            f"🏷 Name: `{server.name}`\n"
            f"🌐 IP: `{server.public_net.ipv4.ip}`\n"
            f"🔑 Root Password: `{root_pass}`\n\n"
            f"⚠️ پسورد را ذخیره کنید، دیگر نمایش داده نمی‌شود."
        )
        
        await msg.edit_text(text, parse_mode='Markdown')
        await send_log(context, f"New server created: {name} ({server.public_net.ipv4.ip})")
        
    except Exception as e:
        await msg.edit_text(f"❌ خطا در ساخت سرور: {str(e)}")
        
    return ConversationHandler.END

async def cancel_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """کنسل کردن پروسه ساخت"""
    query = update.callback_query
    await query.answer("عملیات لغو شد.")
    await start(update, context) # بازگشت به منوی اصلی
    return ConversationHandler.END

# --- 9. راه اندازی ربات ---
if __name__ == '__main__':
    if not BOT_TOKEN:
        print("Error: Config not found.")
        exit()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # هندلر ساخت سرور
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(create_server_start, pattern='^create_server_start$')],
        states={
            WAITING_FOR_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, create_server_finish)]
        },
        fallbacks=[CallbackQueryHandler(cancel_process, pattern='^cancel_process$'), CommandHandler('cancel', cancel_process)]
    )

    app.add_handler(CommandHandler('start', start))
    app.add_handler(CallbackQueryHandler(start, pattern='^main_menu$'))
    app.add_handler(CallbackQueryHandler(list_servers, pattern='^list_servers$'))
    app.add_handler(CallbackQueryHandler(manage_server, pattern='^manage_'))
    app.add_handler(CallbackQueryHandler(server_actions, pattern='^action_'))
    app.add_handler(conv_handler)

    print("✅ Bot is running...")
    app.run_polling()
