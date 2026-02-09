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
SELECT_ACTION, CREATE_NAME, SELECT_ARCH, CREATE_TYPE, CREATE_IMAGE, CONFIRM_DELETE, SELECT_IMAGE_REBUILD, SELECT_TYPE_RESCALE = range(8)

# تنظیم لاگ
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- داده‌های ثابت (اصلاح شده برای 2025/2026) ---
# پلن CX11 حذف شده -> جایگزین: CX22
INTEL_PLANS = ["cx22", "cx32", "cx42"]  # سری جدید Intel
AMD_PLANS = ["cpx11", "cpx21", "cpx31"] # سری جدید AMD

# سیستم‌عامل‌ها
OS_IMAGES = [
    "ubuntu-24.04", "ubuntu-22.04", 
    "debian-12", "alma-9"
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
    # اگر از طریق دکمه برگشت آمده باشد، query دارد
    if update.callback_query:
        await update.callback_query.answer()
        message = update.callback_query.message
    else:
        if not await check_admin(update): return
        message = update.message

    text = (
        "👋 **پنل مدیریت Hetzner (نسخه جدید)**\n\n"
        "امکانات فعال:\n"
        "🖥 **مدیریت:** خاموش/روشن، ریست، حذف، کنسول\n"
        "➕ **ساخت:** پشتیبانی از Intel CX22 و AMD CPX\n"
        "⚙️ **تنظیمات:** نصب مجدد OS، ارتقا پلن\n"
    )
    keyboard = [
        [InlineKeyboardButton("🖥 لیست سرورها", callback_data='list_servers')],
        [InlineKeyboardButton("➕ ساخت سرور جدید", callback_data='create_start')],
        [InlineKeyboardButton("💰 مشاهده پلن‌ها", callback_data='list_plans')],
        [InlineKeyboardButton("❌ بستن منو", callback_data='cancel_action')]
    ]
    
    # اگر پیام قبلی وجود دارد آن را ویرایش کن، وگرنه پیام جدید بده
    if update.callback_query:
        await message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    else:
        await message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    
    return ConversationHandler.END

# --- لیست پلن‌ها ---
async def list_plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    text = (
        "💰 **تعرفه پلن‌های جدید (2026):**\n\n"
        "🔴 **AMD (CPX Series):**\n"
        "▫️ CPX11 (2CPU/2GB): ~€5.80\n"
        "▫️ CPX21 (3CPU/4GB): ~€10.20\n\n"
        "🔵 **Intel (CX Series):**\n"
        "▫️ CX22 (2CPU/4GB): ~€5.20 (جایگزین CX11)\n"
        "▫️ CX32 (4CPU/8GB): ~€10.60\n\n"
        "⚠️ قیمت‌ها حدودی است."
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
            keyboard.append([InlineKeyboardButton(f"{status} {server.name} ({server.public_net.ipv4.ip})", callback_data=f'manage_{server.id}')])
        
        keyboard.append([InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data='main_menu')])
        await query.edit_message_text("لیست سرورهای فعال:", reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        await query.edit_message_text(f"خطا در دریافت لیست: {e}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data='main_menu')]]))

# --- مدیریت تکی سرور ---
async def manage_server(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    server_id = int(query.data.split('_')[1])
    context.user_data['server_id'] = server_id

    try:
        server = hetzner.servers.get_by_id(server_id)
        # هندل کردن ایمیج‌هایی که ممکن است None باشند
        img_name = server.image.name if server.image else "Custom/Snapshot"
        
        info = (
            f"🖥 **{server.name}**\n"
            f"📍 IP: `{server.public_net.ipv4.ip}`\n"
            f"🏢 DC: `{server.datacenter.name}`\n"
            f"⚙️ Plan: `{server.server_type.name}`\n"
            f"💿 OS: `{img_name}`\n"
            f"📊 Status: `{server.status}`\n"
        )
        
        keyboard = [
            [InlineKeyboardButton("🔄 Reboot", callback_data=f'act_reboot_{server_id}'), InlineKeyboardButton("⚠️ Reset", callback_data=f'act_reset_{server_id}')],
            [InlineKeyboardButton("▶️ Power On", callback_data=f'act_on_{server_id}'), InlineKeyboardButton("⏹ Power Off", callback_data=f'act_off_{server_id}')],
            [InlineKeyboardButton("💿 Reinstall", callback_data=f'pre_rebuild_{server_id}'), InlineKeyboardButton("🗑 DELETE", callback_data=f'pre_delete_{server_id}')],
            [InlineKeyboardButton("🔙 بازگشت به لیست", callback_data='list_servers')]
        ]
        await query.edit_message_text(info, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    except Exception as e:
        await query.edit_message_text(f"خطا: {e}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data='list_servers')]]))

# --- اکشن‌های پاور (Reboot, Off, On) ---
async def power_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    action, server_id = data.split('_')[1], int(data.split('_')[2])
    server = hetzner.servers.get_by_id(server_id)
    
    try:
        if action == 'reboot': 
            server.reboot()
            msg = "دستور ریبوت (Soft) ارسال شد."
        elif action == 'reset': 
            server.reset()
            msg = "دستور ریست (Hard) ارسال شد."
        elif action == 'on': 
            server.power_on()
            msg = "سرور روشن شد."
        elif action == 'off': 
            server.power_off()
            msg = "سرور خاموش شد."
        
        await query.answer(msg, show_alert=True)
        await send_log(context, f"Action {action} on {server.name}")
    except Exception as e:
        await query.answer(f"Error: {e}", show_alert=True)

# --- حذف سرور (با تایید) ---
async def pre_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    server_id = int(query.data.split('_')[2])
    context.user_data['server_id'] = server_id
    
    keyboard = [
        [InlineKeyboardButton("✅ بله، حذف شود", callback_data='confirm_delete_yes')],
        [InlineKeyboardButton("❌ خیر، بازگشت", callback_data='cancel_action')]
    ]
    await query.edit_message_text("⚠️ **آیا مطمئن هستید؟**\nاطلاعات سرور کاملا پاک می‌شود و قابل برگشت نیست!", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
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
            await query.edit_message_text(f"خطا در حذف: {e}")
    return ConversationHandler.END

# --- نصب مجدد (Rebuild) ---
async def pre_rebuild(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    sid = int(query.data.split('_')[2])
    context.user_data['server_id'] = sid
    
    keyboard = []
    for img in OS_IMAGES:
        keyboard.append([InlineKeyboardButton(img, callback_data=f"rebuild_img_{img}")])
    
    keyboard.append([InlineKeyboardButton("❌ انصراف", callback_data="cancel_action")])
    await query.edit_message_text("💿 سیستم عامل جدید را انتخاب کنید (اطلاعات فعلی پاک می‌شود):", reply_markup=InlineKeyboardMarkup(keyboard))
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

# --- سناریوی ساخت سرور (FIXED) ---

# 1. شروع و گرفتن نام
async def create_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [[InlineKeyboardButton("❌ کنسل", callback_data="cancel_action")]]
    await query.edit_message_text("📝 **نام سرور** را به انگلیسی بنویسید (مثلاً: vpn-1):", reply_markup=InlineKeyboardMarkup(keyboard))
    return CREATE_NAME

async def create_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_name'] = update.message.text
    
    keyboard = [
        [InlineKeyboardButton("🔵 Intel (Series CX)", callback_data='arch_intel')],
        [InlineKeyboardButton("🔴 AMD (Series CPX)", callback_data='arch_amd')],
        [InlineKeyboardButton("❌ کنسل", callback_data="cancel_action")]
    ]
    await update.message.reply_text("⚙️ **نوع پردازنده** را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(keyboard))
    return SELECT_ARCH

# 2. انتخاب پلن
async def select_arch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    arch = query.data
    
    # اینجا پلن‌های معتبر را لود می‌کنیم
    if arch == 'arch_intel':
        plans = INTEL_PLANS
    else:
        plans = AMD_PLANS
    
    keyboard = []
    row = []
    for p in plans:
        row.append(InlineKeyboardButton(p.upper(), callback_data=p)) # p = 'cx22' مثلا
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row: keyboard.append(row)
    
    keyboard.append([InlineKeyboardButton("❌ کنسل", callback_data="cancel_action")])
    await query.edit_message_text(f"📊 یکی از پلن‌های زیر را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(keyboard))
    return CREATE_TYPE

# 3. انتخاب سیستم عامل
async def create_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    # دیتای دکمه (مثلا cx22) اینجا ذخیره میشه
    context.user_data['new_type'] = query.data 
    
    keyboard = []
    for img in OS_IMAGES:
        keyboard.append([InlineKeyboardButton(img, callback_data=img)])
    
    keyboard.append([InlineKeyboardButton("❌ کنسل", callback_data="cancel_action")])
    await query.edit_message_text("💿 **سیستم عامل** را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(keyboard))
    return CREATE_IMAGE

# 4. ساخت نهایی
async def create_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    image = query.data
    name = context.user_data['new_name']
    server_type = context.user_data['new_type']
    
    await query.edit_message_text("⏳ در حال ساخت سرور... (لطفاً صبر کنید)")
    
    try:
        # اینجا نام پلن (مثلا cx22) مستقیما به API ارسال میشه
        response = hetzner.servers.create(
            name=name,
            server_type=ServerType(name=server_type),
            image=Image(name=image),
            location=Location(name="nbg1") 
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
        await send_log(context, f"Created Server: {name} ({server_type})")
        
    except Exception as e:
        await query.edit_message_text(f"❌ خطا: {e}\n(اگر خطای Invalid Input دیدید یعنی نام پلن یا ایمیج اشتباه است)", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data='main_menu')]]))
        
    return ConversationHandler.END

# --- کنسل کردن کلی ---
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query: 
        await query.answer("عملیات لغو شد.")
    # بازگشت به منوی اصلی
    await start(update, context)
    return ConversationHandler.END

# --- MAIN ---
if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()

    # تعریف هندلر مکالمه (ساخت، حذف، ریبیلد)
    conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(create_start, pattern='^create_start$'),
            CallbackQueryHandler(pre_delete, pattern='^pre_delete_'),
            CallbackQueryHandler(pre_rebuild, pattern='^pre_rebuild_'),
        ],
        states={
            CREATE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, create_name)],
            SELECT_ARCH: [CallbackQueryHandler(select_arch)],
            CREATE_TYPE: [CallbackQueryHandler(create_type)], # اینجا پلن انتخاب میشه
            CREATE_IMAGE: [CallbackQueryHandler(create_final)], # اینجا ایمیج انتخاب میشه و سرور ساخته میشه
            CONFIRM_DELETE: [CallbackQueryHandler(delete_server_confirm)],
            SELECT_IMAGE_REBUILD: [CallbackQueryHandler(do_rebuild)],
        },
        # فال‌بک برای دکمه‌های کنسل و بازگشت
        fallbacks=[
            CommandHandler('cancel', cancel),
            CallbackQueryHandler(cancel, pattern='^cancel_action$'),
            CallbackQueryHandler(cancel, pattern='^main_menu$')
        ]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)
    
    # هندلرهای عادی (خارج از مکالمه)
    app.add_handler(CallbackQueryHandler(list_servers, pattern='^list_servers$'))
    app.add_handler(CallbackQueryHandler(list_plans, pattern='^list_plans$'))
    app.add_handler(CallbackQueryHandler(power_actions, pattern='^act_'))
    app.add_handler(CallbackQueryHandler(manage_server, pattern='^manage_'))
    app.add_handler(CallbackQueryHandler(start, pattern='^main_menu$')) # هندلر بازگشت به منوی اصلی

    print("Bot Started (Updated)...")
    app.run_polling()
