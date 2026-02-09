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

# بارگذاری متغیرها
load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
HETZNER_TOKEN = os.getenv("HETZNER_TOKEN")
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID"))

hetzner = Client(token=HETZNER_TOKEN)

# مراحل گفتگو (Conversation States)
# اضافه شدن SELECT_ARCH برای انتخاب پردازنده
SELECT_ACTION, CREATE_NAME, SELECT_ARCH, CREATE_TYPE, CREATE_IMAGE, CONFIRM_DELETE, SELECT_IMAGE_REBUILD, SELECT_TYPE_RESCALE = range(8)

# تنظیم لاگ
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- داده‌های ثابت ---
# تفکیک پلن‌ها بر اساس پردازنده
INTEL_PLANS = ["cx22", "cx32", "cx42", "cx52"]  # سری CX معمولا اینتل هستند
AMD_PLANS = ["cpx11", "cpx21", "cpx31", "cpx41"] # سری CPX معمولا AMD هستند

# لیست سیستم‌عامل‌ها
OS_IMAGES = [
    "ubuntu-24.04", "ubuntu-22.04", "ubuntu-20.04",
    "debian-12", "alma-9", "rocky-9"
]

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

# --- منوی اصلی ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update): return
    
    text = (
        "👋 **به ربات مدیریت Hetzner خوش آمدید!**\n\n"
        "امکانات جدید:\n"
        "🔹 تفکیک پردازنده AMD/Intel\n"
        "🔹 پشتیبانی از Ubuntu 20/22/24\n"
    )
    keyboard = [
        [InlineKeyboardButton("🖥 لیست سرورها", callback_data='list_servers')],
        [InlineKeyboardButton("➕ ساخت سرور جدید", callback_data='create_start')],
        [InlineKeyboardButton("💰 مشاهده پلن‌ها (قیمت)", callback_data='list_plans')],
        [InlineKeyboardButton("❌ بستن منو", callback_data='cancel_action')]
    ]
    markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=markup, parse_mode='Markdown')
    else:
        await update.message.reply_text(text, reply_markup=markup, parse_mode='Markdown')
    return ConversationHandler.END

# --- لیست پلن‌ها ---
async def list_plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    text = (
        "💰 **تعرفه سرورهای ابری:**\n\n"
        "🔴 **AMD (CPX Series):**\n"
        "▫️ CPX11 (2CPU/2GB): ~€5.30\n"
        "▫️ CPX21 (3CPU/4GB): ~€9.20\n"
        "▫️ CPX31 (4CPU/8GB): ~€16.40\n\n"
        "🔵 **Intel (CX Series):**\n"
        "▫️ CX22 (2CPU/4GB): ~€4.50\n"
        "▫️ CX32 (4CPU/8GB): ~€9.40\n\n"
        "⚠️ قیمت‌ها حدودی و بدون مالیات است."
    )
    keyboard = [[InlineKeyboardButton("🔙 بازگشت", callback_data='main_menu')]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

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
            # نمایش IP و نام
            keyboard.append([InlineKeyboardButton(f"{status} {server.name} | {server.public_net.ipv4.ip}", callback_data=f'manage_{server.id}')])
        
        keyboard.append([InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data='main_menu')])
        await query.edit_message_text("لیست سرورهای شما:", reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        await query.edit_message_text(f"خطا: {e}")

# --- مدیریت تکی سرور ---
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
            f"⚙️ Plan: {server.server_type.name}\n"
            f"💿 OS: {server.image.name if server.image else 'Unknown'}\n"
            f"📊 Status: {server.status}\n"
        )
        
        keyboard = [
            [InlineKeyboardButton("🔄 Reboot", callback_data=f'act_reboot_{server_id}'), InlineKeyboardButton("⚠️ Reset", callback_data=f'act_reset_{server_id}')],
            [InlineKeyboardButton("▶️ On", callback_data=f'act_on_{server_id}'), InlineKeyboardButton("⏹ Off", callback_data=f'act_off_{server_id}')],
            [InlineKeyboardButton("💿 Reinstall", callback_data=f'pre_rebuild_{server_id}'), InlineKeyboardButton("🗑 DELETE", callback_data=f'pre_delete_{server_id}')],
            [InlineKeyboardButton("🔙 بازگشت به لیست", callback_data='list_servers')]
        ]
        await query.edit_message_text(info, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    except Exception as e:
        await query.edit_message_text(f"خطا: {e}")

# --- اکشن‌های پاور ---
async def power_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    action, server_id = data.split('_')[1], int(data.split('_')[2])
    server = hetzner.servers.get_by_id(server_id)
    
    try:
        if action == 'reboot': server.reboot()
        elif action == 'reset': server.reset()
        elif action == 'on': server.power_on()
        elif action == 'off': server.power_off()
        
        await query.answer(f"دستور {action} ارسال شد.", show_alert=True)
        await send_log(context, f"Action {action} on {server.name}")
    except Exception as e:
        await query.answer(f"Error: {e}", show_alert=True)

# --- حذف سرور ---
async def pre_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    server_id = int(query.data.split('_')[2])
    context.user_data['server_id'] = server_id
    
    keyboard = [
        [InlineKeyboardButton("✅ بله، حذف شود", callback_data='confirm_delete_yes')],
        [InlineKeyboardButton("❌ خیر", callback_data='list_servers')]
    ]
    await query.edit_message_text("⚠️ **آیا مطمئن هستید؟**\nاطلاعات سرور کاملا پاک می‌شود.", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    return CONFIRM_DELETE

async def delete_server_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == 'confirm_delete_yes':
        try:
            sid = context.user_data['server_id']
            server = hetzner.servers.get_by_id(sid)
            name = server.name
            server.delete()
            await query.edit_message_text(f"✅ سرور {name} حذف شد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 منو", callback_data='main_menu')]]))
            await send_log(context, f"Server {name} DELETED.")
        except Exception as e:
            await query.edit_message_text(f"خطا: {e}")
    else:
        await start(update, context)
    return ConversationHandler.END

# --- بازسازی (Rebuild) ---
async def pre_rebuild(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    sid = int(query.data.split('_')[2])
    context.user_data['server_id'] = sid
    
    # نمایش لیست جدید سیستم‌عامل‌ها
    keyboard = []
    row = []
    for i, img in enumerate(OS_IMAGES):
        row.append(InlineKeyboardButton(img, callback_data=f"rebuild_img_{img}"))
        if (i + 1) % 2 == 0:
            keyboard.append(row)
            row = []
    if row: keyboard.append(row)
    
    keyboard.append([InlineKeyboardButton("❌ انصراف", callback_data="main_menu")])
    await query.edit_message_text("💿 سیستم عامل جدید را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(keyboard))
    return SELECT_IMAGE_REBUILD

async def do_rebuild(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    img_name = query.data.split('_')[2]
    sid = context.user_data['server_id']
    
    try:
        server = hetzner.servers.get_by_id(sid)
        image = hetzner.images.get_by_name(img_name)
        server.rebuild(image=image)
        await query.edit_message_text(f"✅ بازسازی {server.name} با {img_name} شروع شد.\nرمز عبور جدید ایمیل می‌شود.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 منو", callback_data='main_menu')]]))
        await send_log(context, f"Rebuild {server.name} -> {img_name}")
    except Exception as e:
        await query.edit_message_text(f"خطا: {e}")
    return ConversationHandler.END

# --- ساخت سرور جدید (STEP BY STEP) ---

# 1. گرفتن نام
async def create_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("📝 **نام سرور** را بنویسید (مثلاً: vpn-server):", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ کنسل", callback_data="cancel_action")]]))
    return CREATE_NAME

async def create_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_name'] = update.message.text
    
    # 2. انتخاب معماری (جدید)
    keyboard = [
        [InlineKeyboardButton("🔵 Intel (Series CX)", callback_data='arch_intel')],
        [InlineKeyboardButton("🔴 AMD (Series CPX)", callback_data='arch_amd')],
        [InlineKeyboardButton("❌ کنسل", callback_data="cancel_action")]
    ]
    await update.message.reply_text("⚙️ **نوع پردازنده** را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(keyboard))
    return SELECT_ARCH

# 3. انتخاب پلن بر اساس معماری
async def select_arch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    arch = query.data
    
    if arch == 'arch_intel':
        plans = INTEL_PLANS
        title = "🔵 پلن‌های Intel"
    else:
        plans = AMD_PLANS
        title = "🔴 پلن‌های AMD"
    
    keyboard = []
    row = []
    for p in plans:
        row.append(InlineKeyboardButton(p.upper(), callback_data=p))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row: keyboard.append(row)
    
    keyboard.append([InlineKeyboardButton("❌ کنسل", callback_data="cancel_action")])
    await query.edit_message_text(f"📊 یکی از {title} را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(keyboard))
    return CREATE_TYPE

# 4. انتخاب سیستم عامل
async def create_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['new_type'] = query.data
    
    # چیدمان دکمه‌های سیستم عامل
    keyboard = []
    row = []
    for i, img in enumerate(OS_IMAGES):
        row.append(InlineKeyboardButton(img, callback_data=img))
        if (i + 1) % 2 == 0:
            keyboard.append(row)
            row = []
    if row: keyboard.append(row)
    
    await query.edit_message_text("💿 **سیستم عامل** را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(keyboard))
    return CREATE_IMAGE

# 5. ساخت نهایی
async def create_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    image = query.data
    name = context.user_data['new_name']
    server_type = context.user_data['new_type']
    
    await query.edit_message_text("⏳ در حال ساخت سرور... (ممکن است چند ثانیه طول بکشد)")
    
    try:
        response = hetzner.servers.create(
            name=name,
            server_type=ServerType(name=server_type),
            image=Image(name=image),
            location=Location(name="nbg1") # نورنبرگ آلمان
        )
        server = response.server
        root_pass = response.root_password
        
        msg = (
            f"✅ **سرور ساخته شد!**\n\n"
            f"Name: `{server.name}`\n"
            f"IP: `{server.public_net.ipv4.ip}`\n"
            f"Pass: `{root_pass}`\n"
            f"OS: {image}\n"
            f"Type: {server_type}\n\n"
            f"⚠️ پسورد را حتما ذخیره کنید."
        )
        await query.edit_message_text(msg, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 منوی اصلی", callback_data='main_menu')]]))
        await send_log(context, f"Created Server: {name} ({server_type} / {image})")
        
    except Exception as e:
        await query.edit_message_text(f"❌ خطا: {e}")
        
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query: await query.answer()
    await start(update, context)
    return ConversationHandler.END

if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(create_start, pattern='^create_start$'),
            CallbackQueryHandler(pre_delete, pattern='^pre_delete_'),
            CallbackQueryHandler(pre_rebuild, pattern='^pre_rebuild_'),
        ],
        states={
            CREATE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, create_name)],
            SELECT_ARCH: [CallbackQueryHandler(select_arch)], # مرحله جدید
            CREATE_TYPE: [CallbackQueryHandler(create_type)],
            CREATE_IMAGE: [CallbackQueryHandler(create_final)],
            CONFIRM_DELETE: [CallbackQueryHandler(delete_server_confirm)],
            SELECT_IMAGE_REBUILD: [CallbackQueryHandler(do_rebuild)],
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
    app.add_handler(CallbackQueryHandler(list_plans, pattern='^list_plans$'))
    app.add_handler(CallbackQueryHandler(power_actions, pattern='^act_'))
    app.add_handler(CallbackQueryHandler(manage_server, pattern='^manage_'))

    print("Bot Started...")
    app.run_polling()
