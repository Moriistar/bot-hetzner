import os
import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, ContextTypes, CommandHandler, CallbackQueryHandler, ConversationHandler, MessageHandler, filters
)
from hcloud import Client
from hcloud.server_types.domain import ServerType
from hcloud.images.domain import Image
from hcloud.locations.domain import Location
from dotenv import load_dotenv

# بارگذاری متغیرها از فایل .env
load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
HETZNER_TOKEN = os.getenv("HETZNER_TOKEN")
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID"))

# تنظیمات کلاینت هتزنر
hetzner = Client(token=HETZNER_TOKEN)

# مراحل گفتگو (Conversation States)
SELECT_ACTION, CREATE_NAME, CREATE_TYPE, CREATE_IMAGE, CONFIRM_DELETE, SELECT_IMAGE_REBUILD, SELECT_TYPE_RESCALE = range(7)

# تنظیم لاگ
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- توابع کمکی ---
async def check_admin(update: Update):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.effective_message.reply_text("⛔ شما ادمین این ربات نیستید.")
        return False
    return True

async def send_log(context: ContextTypes.DEFAULT_TYPE, message: str):
    try:
        await context.bot.send_message(chat_id=LOG_CHANNEL_ID, text=f"📝 **LOG:**\n{message}", parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Error sending log: {e}")

# --- منوی اصلی و استارت ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update): return
    
    text = (
        "👋 **به ربات مدیریت Hetzner خوش آمدید!**\n\n"
        "امکانات ربات:\n"
        "🖥 **مدیریت سرورها:** خاموش/روشن، ریست، کنسول، حذف و...\n"
        "➕ **ساخت سرور:** ایجاد سرور جدید در چند مرحله.\n"
        "⚙️ **ارتقا/نصب مجدد:** تغییر پلن یا سیستم عامل.\n"
        "❌ **کنسل:** لغو عملیات جاری."
    )
    keyboard = [
        [InlineKeyboardButton("🖥 لیست سرورها", callback_data='list_servers')],
        [InlineKeyboardButton("➕ ساخت سرور جدید", callback_data='create_start')],
        [InlineKeyboardButton("💰 مشاهده پلن‌ها (قیمت)", callback_data='list_plans')],
        [InlineKeyboardButton("❌ بستن منو", callback_data='cancel_action')]
    ]
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    return ConversationHandler.END

# --- لیست سرورها ---
async def list_servers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    try:
        servers = hetzner.servers.get_all()
        if not servers:
            await query.edit_message_text("❌ هیچ سروری یافت نشد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data='main_menu')]]))
            return

        keyboard = []
        for server in servers:
            status = "🟢" if server.status == "running" else "🔴"
            keyboard.append([InlineKeyboardButton(f"{status} {server.name} | {server.public_net.ipv4.ip}", callback_data=f'manage_{server.id}')])
        
        keyboard.append([InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data='main_menu')])
        await query.edit_message_text("لیست سرورهای شما:", reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        await query.edit_message_text(f"خطا: {e}")

# --- جزئیات سرور ---
async def manage_server(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    server_id = int(query.data.split('_')[1])
    context.user_data['server_id'] = server_id

    try:
        server = hetzner.servers.get_by_id(server_id)
        info = (
            f"🖥 **{server.name}**\n"
            f"📍 IP: `{server.public_net.ipv4.ip}`\n"
            f"🏢 DC: {server.datacenter.name}\n"
            f"⚙️ Type: {server.server_type.name}\n"
            f"📊 Status: {server.status}\n"
        )
        
        keyboard = [
            [InlineKeyboardButton("🔄 Reboot (Soft)", callback_data=f'act_reboot_{server_id}'), InlineKeyboardButton("⚠️ Reset (Hard)", callback_data=f'act_reset_{server_id}')],
            [InlineKeyboardButton("▶️ Power On", callback_data=f'act_on_{server_id}'), InlineKeyboardButton("⏹ Power Off", callback_data=f'act_off_{server_id}')],
            [InlineKeyboardButton("💿 Rebuild (Reinstall)", callback_data=f'pre_rebuild_{server_id}'), InlineKeyboardButton("⬆️ Upgrade (Rescale)", callback_data=f'pre_rescale_{server_id}')],
            [InlineKeyboardButton("🗑 DELETE SERVER", callback_data=f'pre_delete_{server_id}')],
            [InlineKeyboardButton("🔙 بازگشت به لیست", callback_data='list_servers')]
        ]
        await query.edit_message_text(info, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    except Exception as e:
        await query.edit_message_text(f"خطا در دریافت اطلاعات سرور: {e}")

# --- عملیات قدرت (Power Actions) ---
async def power_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    action, server_id = data.split('_')[1], int(data.split('_')[2])
    server = hetzner.servers.get_by_id(server_id)
    
    msg = ""
    try:
        if action == 'reboot':
            server.reboot()
            msg = f"دستور ریبوت برای {server.name} ارسال شد."
        elif action == 'reset':
            server.reset()
            msg = f"دستور ریست سخت‌افزاری برای {server.name} ارسال شد."
        elif action == 'on':
            server.power_on()
            msg = f"دستور روشن شدن برای {server.name} ارسال شد."
        elif action == 'off':
            server.power_off()
            msg = f"دستور خاموش شدن برای {server.name} ارسال شد."
        
        await send_log(context, f"Action: {action.upper()} on server {server.name} by admin.")
        await query.answer(msg, show_alert=True)
    except Exception as e:
        await query.answer(f"خطا: {e}", show_alert=True)

# --- حذف سرور ---
async def pre_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    server_id = int(query.data.split('_')[2])
    context.user_data['server_id'] = server_id
    
    keyboard = [
        [InlineKeyboardButton("✅ بله، حذف کن", callback_data='confirm_delete_yes')],
        [InlineKeyboardButton("❌ خیر، لغو کن", callback_data='main_menu')]
    ]
    await query.edit_message_text("⚠️ **آیا از حذف این سرور اطمینان دارید؟**\nاین عملیات غیرقابل بازگشت است!", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    return CONFIRM_DELETE

async def delete_server_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == 'confirm_delete_yes':
        server_id = context.user_data['server_id']
        try:
            server = hetzner.servers.get_by_id(server_id)
            name = server.name
            server.delete()
            await query.edit_message_text(f"✅ سرور {name} با موفقیت حذف شد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data='list_servers')]]))
            await send_log(context, f"Server {name} DELETED by admin.")
        except Exception as e:
            await query.edit_message_text(f"خطا در حذف: {e}")
    return ConversationHandler.END

# --- نصب مجدد (Rebuild) ---
async def pre_rebuild(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    server_id = int(query.data.split('_')[2])
    context.user_data['server_id'] = server_id
    
    # لیست سیستم عامل‌های محبوب
    images = ["ubuntu-24.04", "ubuntu-22.04", "debian-12", "centos-stream-9"]
    keyboard = [[InlineKeyboardButton(img, callback_data=f"rebuild_img_{img}")] for img in images]
    keyboard.append([InlineKeyboardButton("❌ انصراف", callback_data="main_menu")])
    
    await query.edit_message_text("💿 سیستم عامل جدید را برای نصب مجدد انتخاب کنید (تمام اطلاعات پاک می‌شود):", reply_markup=InlineKeyboardMarkup(keyboard))
    return SELECT_IMAGE_REBUILD

async def do_rebuild(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    image_name = query.data.split('_')[2]
    server_id = context.user_data['server_id']
    
    try:
        server = hetzner.servers.get_by_id(server_id)
        image = hetzner.images.get_by_name(image_name)
        server.rebuild(image=image)
        await query.edit_message_text(f"✅ دستور نصب مجدد {image_name} روی {server.name} ارسال شد.\nپسورد جدید ایمیل می‌شود.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data='list_servers')]]))
        await send_log(context, f"Server {server.name} REBUILD to {image_name}.")
    except Exception as e:
        await query.edit_message_text(f"خطا: {e}")
    return ConversationHandler.END

# --- ارتقا (Rescale) ---
async def pre_rescale(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    server_id = int(query.data.split('_')[2])
    context.user_data['server_id'] = server_id
    
    # لیست پلن‌ها
    plans = ["cx22", "cpx11", "cpx21", "cpx31"]
    keyboard = [[InlineKeyboardButton(p.upper(), callback_data=f"rescale_plan_{p}")] for p in plans]
    keyboard.append([InlineKeyboardButton("❌ انصراف", callback_data="main_menu")])
    
    await query.edit_message_text("📈 پلن جدید را انتخاب کنید (سرور باید خاموش باشد):", reply_markup=InlineKeyboardMarkup(keyboard))
    return SELECT_TYPE_RESCALE

async def do_rescale(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    plan_name = query.data.split('_')[2]
    server_id = context.user_data['server_id']
    
    try:
        server = hetzner.servers.get_by_id(server_id)
        server_type = hetzner.server_types.get_by_name(plan_name)
        server.change_type(server_type=server_type, upgrade_disk=False) # دیسک را خودکار ارتقا ندهد تا قابل دانگرید باشد
        await query.edit_message_text(f"✅ سرور به {plan_name} تغییر یافت. (اگر ارور داد، سرور را خاموش کنید و دوباره تلاش کنید)", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data='list_servers')]]))
        await send_log(context, f"Server {server.name} RESCALED to {plan_name}.")
    except Exception as e:
        await query.edit_message_text(f"خطا: {e}. مطمئن شوید سرور خاموش است.")
    return ConversationHandler.END

# --- ساخت سرور جدید (Conversation) ---
async def create_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [[InlineKeyboardButton("❌ کنسل", callback_data="cancel_action")]]
    await query.edit_message_text("📝 لطفاً **نام سرور** جدید را ارسال کنید:", reply_markup=InlineKeyboardMarkup(keyboard))
    return CREATE_NAME

async def create_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_name'] = update.message.text
    
    types = ["cx22", "cpx11", "cpx21", "cpx31"]
    keyboard = [[InlineKeyboardButton(t, callback_data=t)] for t in types]
    
    await update.message.reply_text("⚙️ **نوع سرور** (Plan) را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(keyboard))
    return CREATE_TYPE

async def create_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['new_type'] = query.data
    
    images = ["ubuntu-22.04", "debian-12", "alma-9"]
    keyboard = [[InlineKeyboardButton(img, callback_data=img)] for img in images]
    
    await query.edit_message_text("💿 **سیستم عامل** را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(keyboard))
    return CREATE_IMAGE

async def create_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    image = query.data
    name = context.user_data['new_name']
    server_type = context.user_data['new_type']
    
    await query.edit_message_text("⏳ در حال ساخت سرور... لطفاً صبر کنید.")
    
    try:
        response = hetzner.servers.create(
            name=name,
            server_type=ServerType(name=server_type),
            image=Image(name=image),
            location=Location(name="nbg1") # پیش‌فرض نورنبرگ
        )
        server = response.server
        root_pass = response.root_password
        
        msg = (
            f"✅ **سرور با موفقیت ساخته شد!**\n\n"
            f"Name: `{server.name}`\n"
            f"IP: `{server.public_net.ipv4.ip}`\n"
            f"Pass: `{root_pass}`\n\n"
            f"⚠️ پسورد را ذخیره کنید."
        )
        await query.edit_message_text(msg, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 منوی اصلی", callback_data='main_menu')]]))
        await send_log(context, f"New Server Created: {name} ({server_type})")
        
    except Exception as e:
        await query.edit_message_text(f"❌ خطا در ساخت سرور: {e}")
        
    return ConversationHandler.END

# --- کنسل کردن ---
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("عملیات لغو شد.")
    await start(update, context)
    return ConversationHandler.END

# --- راه‌اندازی ربات ---
if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()

    # هندلرهای گفتگو برای ساخت سرور، حذف و ...
    conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(create_start, pattern='^create_start$'),
            CallbackQueryHandler(pre_delete, pattern='^pre_delete_'),
            CallbackQueryHandler(pre_rebuild, pattern='^pre_rebuild_'),
            CallbackQueryHandler(pre_rescale, pattern='^pre_rescale_'),
        ],
        states={
            CREATE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, create_name)],
            CREATE_TYPE: [CallbackQueryHandler(create_type)],
            CREATE_IMAGE: [CallbackQueryHandler(create_final)],
            CONFIRM_DELETE: [CallbackQueryHandler(delete_server_confirm)],
            SELECT_IMAGE_REBUILD: [CallbackQueryHandler(do_rebuild)],
            SELECT_TYPE_RESCALE: [CallbackQueryHandler(do_rescale)],
        },
        fallbacks=[
            CommandHandler('cancel', cancel),
            CallbackQueryHandler(cancel, pattern='^cancel_action$'),
            CallbackQueryHandler(start, pattern='^main_menu$')
        ]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(list_servers, pattern='^list_servers$'))
    app.add_handler(CallbackQueryHandler(start, pattern='^main_menu$'))
    app.add_handler(CallbackQueryHandler(power_actions, pattern='^act_'))
    app.add_handler(CallbackQueryHandler(manage_server, pattern='^manage_'))

    print("Bot Started...")
    app.run_polling()
