import os
import logging
import time
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
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID") # اختیاری

# اتصال به هتزنر
hetzner = Client(token=HETZNER_TOKEN)

# مراحل گفتگو (Conversation States)
CREATE_NAME, CREATE_LOC, SELECT_ARCH, CREATE_TYPE, CREATE_IMAGE, CONFIRM_DELETE, CONFIRM_RECREATE = range(7)

# تنظیم لاگ
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- داده‌های ثابت ---
# پلن‌های جدید و معتبر
PLANS = {
    'intel': ['cx22', 'cx32', 'cx42'],
    'amd': ['cpx11', 'cpx21', 'cpx31']
}

LOCATIONS = {
    'nbg1': '🇩🇪 آلمان (Nuremberg)',
    'fsn1': '🇩🇪 آلمان (Falkenstein)',
    'hel1': '🇫🇮 فنلاند (Helsinki)',
    'ash': '🇺🇸 آمریکا (Ashburn)',
    'hil': '🇺🇸 آمریکا (Hillsboro)'
}

OS_IMAGES = ["ubuntu-24.04", "ubuntu-22.04", "debian-12", "alma-9"]

# --- توابع کمکی ---
async def check_admin(update: Update):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.effective_message.reply_text("⛔ دسترسی غیرمجاز. این ربات شخصی است.")
        return False
    return True

async def send_log(context: ContextTypes.DEFAULT_TYPE, msg: str):
    if LOG_CHANNEL_ID:
        try:
            await context.bot.send_message(chat_id=LOG_CHANNEL_ID, text=f"📝 {msg}")
        except: pass

# --- منوی اصلی ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # پاکسازی وضعیت‌های قبلی
    context.user_data.clear()
    
    if update.callback_query:
        try: await update.callback_query.answer()
        except: pass
        msg_func = update.callback_query.message.edit_text
    else:
        if not await check_admin(update): return
        msg_func = update.message.reply_text

    text = (
        "🎛 **کنترل پنل مدیریت هتزنر**\n"
        "نسخه: 2026 (Stable)\n\n"
        "یکی از گزینه‌ها را انتخاب کنید:"
    )
    keyboard = [
        [InlineKeyboardButton("🖥 لیست سرورها (مدیریت)", callback_data='list_servers')],
        [InlineKeyboardButton("➕ ساخت سرور جدید", callback_data='create_start')],
        [InlineKeyboardButton("💰 تعرفه‌ها", callback_data='list_plans')],
        [InlineKeyboardButton("🔄 رفرش ربات", callback_data='main_menu')]
    ]
    await msg_func(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
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
        for s in servers:
            status = "🟢" if s.status == "running" else "🔴"
            # ذخیره کردن مشخصات برای استفاده‌های بعدی
            btn_text = f"{status} {s.name} ({s.public_net.ipv4.ip})"
            keyboard.append([InlineKeyboardButton(btn_text, callback_data=f'manage_{s.id}')])
        
        keyboard.append([InlineKeyboardButton("🔙 منوی اصلی", callback_data='main_menu')])
        await query.edit_message_text("لیست سرورهای شما:", reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        await query.edit_message_text(f"خطا در دریافت لیست: {str(e)}")

# --- پنل مدیریت تکی ---
async def manage_server(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    server_id = int(query.data.split('_')[1])
    context.user_data['server_id'] = server_id

    try:
        server = hetzner.servers.get_by_id(server_id)
        img = server.image.name if server.image else "Snapshot"
        loc = server.datacenter.location.name
        
        # ذخیره اطلاعات برای عملیات Re-Create
        context.user_data['current_server_info'] = {
            'name': server.name,
            'type': server.server_type.name,
            'image': img,
            'location': loc
        }

        info = (
            f"🖥 **{server.name}**\n"
            f"🌐 IP: `{server.public_net.ipv4.ip}`\n"
            f"📍 Loc: `{LOCATIONS.get(loc, loc)}`\n"
            f"⚙️ Plan: `{server.server_type.name}`\n"
            f"💿 OS: `{img}`\n"
            f"📊 Status: `{server.status}`"
        )
        
        keyboard = [
            [InlineKeyboardButton("🔄 Reboot", callback_data=f'act_reboot_{server_id}'), InlineKeyboardButton("⚠️ Reset", callback_data=f'act_reset_{server_id}')],
            [InlineKeyboardButton("▶️ On", callback_data=f'act_on_{server_id}'), InlineKeyboardButton("⏹ Off", callback_data=f'act_off_{server_id}')],
            [InlineKeyboardButton("♻️ تغییر آی‌پی (Re-Create)", callback_data=f'pre_recreate_{server_id}')],
            [InlineKeyboardButton("💿 Rebuild", callback_data=f'pre_rebuild_{server_id}'), InlineKeyboardButton("🗑 حذف سرور", callback_data=f'pre_delete_{server_id}')],
            [InlineKeyboardButton("🔙 لیست سرورها", callback_data='list_servers')]
        ]
        await query.edit_message_text(info, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    except Exception as e:
        await query.edit_message_text(f"خطا: {e}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data='list_servers')]]))

# --- اکشن‌های سریع (پاور) ---
async def power_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    action, sid = data.split('_')[1], int(data.split('_')[2])
    
    try:
        server = hetzner.servers.get_by_id(sid)
        if action == 'reboot': server.reboot()
        elif action == 'reset': server.reset()
        elif action == 'on': server.power_on()
        elif action == 'off': server.power_off()
        
        await query.answer(f"دستور {action} ارسال شد.", show_alert=True)
    except Exception as e:
        await query.answer(f"خطا: {e}", show_alert=True)

# --- سناریوی تغییر آی‌پی (Re-Create) ---
async def pre_recreate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    sid = int(query.data.split('_')[2])
    context.user_data['server_id'] = sid
    
    text = (
        "⚠️ **هشدار تغییر آی‌پی**\n\n"
        "در هتزنر آی‌پی به سرور چسبیده است. برای تغییر آی‌پی، این ربات:\n"
        "1. سرور فعلی را **حذف** می‌کند (اطلاعات پاک می‌شود).\n"
        "2. بلافاصله یک سرور جدید با همان نام و مشخصات می‌سازد.\n\n"
        "آیا مطمئن هستید؟"
    )
    keyboard = [
        [InlineKeyboardButton("✅ بله، آی‌پی عوض کن", callback_data='confirm_recreate_yes')],
        [InlineKeyboardButton("❌ لغو", callback_data=f'manage_{sid}')]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    return CONFIRM_RECREATE

async def do_recreate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == 'confirm_recreate_yes':
        sid = context.user_data['server_id']
        info = context.user_data.get('current_server_info')
        
        if not info:
            await query.edit_message_text("❌ اطلاعات سرور یافت نشد. لطفا دوباره تلاش کنید.")
            return ConversationHandler.END
            
        await query.edit_message_text("♻️ در حال تغییر آی‌پی (1/2): حذف سرور قدیمی...")
        
        try:
            # 1. حذف
            hetzner.servers.get_by_id(sid).delete()
            await query.edit_message_text("♻️ در حال تغییر آی‌پی (2/2): ساخت سرور جدید...")
            
            # 2. ساخت مجدد
            res = hetzner.servers.create(
                name=info['name'],
                server_type=ServerType(name=info['type']),
                image=Image(name=info['image']),
                location=Location(name=info['location'])
            )
            
            srv = res.server
            pw = res.root_password
            
            msg = (
                f"✅ **آی‌پی با موفقیت تغییر کرد!**\n\n"
                f"نام: `{srv.name}`\n"
                f"آی‌پی جدید: `{srv.public_net.ipv4.ip}`\n"
                f"رمز عبور: `{pw}`\n\n"
                f"⚠️ سرور قبلی کامل پاک شد."
            )
            await query.edit_message_text(msg, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 منوی اصلی", callback_data='main_menu')]]))
            await send_log(context, f"IP Changed for {srv.name}. New IP: {srv.public_net.ipv4.ip}")
            
        except Exception as e:
            await query.edit_message_text(f"❌ خطا در پروسه تغییر آی‌پی: {e}")
            
    return ConversationHandler.END

# --- سناریوی حذف سرور ---
async def pre_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    sid = int(query.data.split('_')[2])
    context.user_data['server_id'] = sid
    
    keyboard = [[InlineKeyboardButton("✅ تایید حذف", callback_data='confirm_delete_yes'), InlineKeyboardButton("❌ لغو", callback_data='list_servers')]]
    await query.edit_message_text("⚠️ **آیا مطمئن هستید؟** این کار غیرقابل بازگشت است.", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    return CONFIRM_DELETE

async def delete_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == 'confirm_delete_yes':
        try:
            sid = context.user_data['server_id']
            hetzner.servers.get_by_id(sid).delete()
            await query.edit_message_text("✅ سرور حذف شد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 منو", callback_data='main_menu')]]))
        except Exception as e:
            await query.edit_message_text(f"خطا: {e}")
    else:
        await start(update, context)
    return ConversationHandler.END

# --- سناریوی ساخت سرور (Wizard) ---
async def create_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("📝 **نام سرور** را وارد کنید (انگلیسی، بدون فاصله):", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ لغو", callback_data='cancel_action')]]))
    return CREATE_NAME

async def create_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_name'] = update.message.text
    
    keyboard = []
    for code, name in LOCATIONS.items():
        keyboard.append([InlineKeyboardButton(name, callback_data=code)])
    
    await update.message.reply_text("🌍 **لوکیشن** را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(keyboard))
    return CREATE_LOC

async def create_loc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['new_loc'] = query.data
    
    keyboard = [
        [InlineKeyboardButton("🔵 Intel (Series CX)", callback_data='intel')],
        [InlineKeyboardButton("🔴 AMD (Series CPX)", callback_data='amd')]
    ]
    await query.edit_message_text("⚙️ **نوع پردازنده**:", reply_markup=InlineKeyboardMarkup(keyboard))
    return SELECT_ARCH

async def select_arch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    arch = query.data
    
    keyboard = []
    for p in PLANS[arch]:
        keyboard.append([InlineKeyboardButton(p.upper(), callback_data=p)])
    
    await query.edit_message_text("📊 **پلن** را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(keyboard))
    return CREATE_TYPE

async def create_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['new_type'] = query.data
    
    keyboard = [[InlineKeyboardButton(img, callback_data=img)] for img in OS_IMAGES]
    await query.edit_message_text("💿 **سیستم عامل**:", reply_markup=InlineKeyboardMarkup(keyboard))
    return CREATE_IMAGE

async def create_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    image = query.data
    
    d = context.user_data
    await query.edit_message_text(f"⏳ در حال ساخت...\nName: {d['new_name']}\nLoc: {d['new_loc']}\nPlan: {d['new_type']}")
    
    try:
        res = hetzner.servers.create(
            name=d['new_name'],
            server_type=ServerType(name=d['new_type']),
            image=Image(name=image),
            location=Location(name=d['new_loc'])
        )
        srv = res.server
        pw = res.root_password
        
        msg = (
            f"✅ **سرور ساخته شد!**\n\n"
            f"🖥 Name: `{srv.name}`\n"
            f"🌐 IP: `{srv.public_net.ipv4.ip}`\n"
            f"🔑 Pass: `{pw}`\n\n"
            f"⚠️ پسورد را ذخیره کنید."
        )
        await query.edit_message_text(msg, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 منو", callback_data='main_menu')]]))
        await send_log(context, f"Created Server: {srv.name} ({d['new_type']})")
        
    except Exception as e:
        await query.edit_message_text(f"❌ خطا: {e}\nممکن است نام تکراری باشد یا منابع پر شده باشد.")
        
    return ConversationHandler.END

# --- کنسل ---
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query: await update.callback_query.answer()
    await start(update, context)
    return ConversationHandler.END

# --- اجرا ---
if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()

    # مدیریت گفتگوها
    conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(create_start, pattern='^create_start$'),
            CallbackQueryHandler(pre_delete, pattern='^pre_delete_'),
            CallbackQueryHandler(pre_recreate, pattern='^pre_recreate_'), # هندلر تغییر آی‌پی
        ],
        states={
            CREATE_NAME: [MessageHandler(filters.TEXT, create_name)],
            CREATE_LOC: [CallbackQueryHandler(create_loc)],
            SELECT_ARCH: [CallbackQueryHandler(select_arch)],
            CREATE_TYPE: [CallbackQueryHandler(create_type)],
            CREATE_IMAGE: [CallbackQueryHandler(create_final)],
            CONFIRM_DELETE: [CallbackQueryHandler(delete_confirm)],
            CONFIRM_RECREATE: [CallbackQueryHandler(do_recreate)],
        },
        fallbacks=[CommandHandler('cancel', cancel), CallbackQueryHandler(cancel, pattern='^cancel_action$')]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(list_servers, pattern='^list_servers$'))
    app.add_handler(CallbackQueryHandler(power_actions, pattern='^act_'))
    app.add_handler(CallbackQueryHandler(manage_server, pattern='^manage_'))
    app.add_handler(CallbackQueryHandler(start, pattern='^main_menu$'))
    
    print("Bot is Running...")
    app.run_polling()
