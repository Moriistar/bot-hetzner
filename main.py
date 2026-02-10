import os
import logging
import asyncio
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
    """ساخت دکمه‌های مدیریتی پیشرفته"""
    keyboard = [
        [
            InlineKeyboardButton("🟢 روشن", callback_data=f"on_{server_id}"),
            InlineKeyboardButton("🔴 خاموش", callback_data=f"off_{server_id}"),
        ],
        [
            InlineKeyboardButton("📸 اسنپ‌شات (Backup)", callback_data=f"snap_menu_{server_id}"),
            InlineKeyboardButton("♻️ تغییر IP (New Identity)", callback_data=f"changeip_warn_{server_id}"),
        ],
        [
            InlineKeyboardButton("🔄 ریبوت", callback_data=f"reset_{server_id}"),
            InlineKeyboardButton("🗑 حذف سرور", callback_data=f"del_confirm_{server_id}"),
        ],
        [
            InlineKeyboardButton("🔙 بازگشت به لیست", callback_data="list_servers"),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

# --- هندلرها ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_admin(update.effective_user.id):
        return
    
    keyboard = [[InlineKeyboardButton("🖥 لیست سرورها", callback_data="list_servers")]]
    await update.message.reply_text(
        "👋 سلام رئیس! به پنل پیشرفته مدیریت هتزنر خوش آمدید.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def list_servers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    try:
        servers = hclient.servers.get_all()
        if not servers:
            # دکمه ساخت سرور جدید اگر هیچ سروری نبود
            keyboard = [[InlineKeyboardButton("➕ ساخت سرور جدید (Ubuntu)", callback_data="create_new_server")]]
            await query.edit_message_text("❌ هیچ سروری یافت نشد.", reply_markup=InlineKeyboardMarkup(keyboard))
            return

        keyboard = []
        for server in servers:
            status_icon = "🟢" if server.status == "running" else "🔴"
            btn_text = f"{status_icon} {server.name} | {server.public_net.ipv4.ip}"
            keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"srv_{server.id}")])
        
        keyboard.append([InlineKeyboardButton("🔄 بروزرسانی لیست", callback_data="list_servers")])
        keyboard.append([InlineKeyboardButton("➕ ساخت سرور جدید", callback_data="create_new_server")])
        
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
        
        # محاسبه هزینه اسنپ‌شات‌ها اگر وجود داشته باشد
        # (این بخش ساده‌سازی شده است)
        
        info = (
            f"🖥 **Server:** `{server.name}`\n"
            f"🌐 **IP:** `{server.public_net.ipv4.ip}`\n"
            f"💡 **Status:** {server.status}\n"
            f"📍 **Location:** {server.datacenter.name}\n"
            f"⚙️ **Type:** {server.server_type.name}"
        )
        
        await query.edit_message_text(
            info,
            reply_markup=get_server_keyboard(server_id),
            parse_mode="Markdown"
        )
    except Exception as e:
        await query.edit_message_text(f"خطا: {str(e)}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="list_servers")]]))

# --- بخش اسنپ‌شات ---
async def snapshot_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    server_id = int(query.data.split("_")[2])
    
    keyboard = [
        [InlineKeyboardButton("📸 گرفتن اسنپ‌شات الان", callback_data=f"takesnap_{server_id}")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data=f"srv_{server_id}")]
    ]
    await query.edit_message_text(
        "📸 **مدیریت اسنپ‌شات‌ها**\n\nاسنپ‌شات یک کپی کامل از دیسک سرور شماست. هزینه نگهداری آن حدود 0.01 یورو بر گیگابایت است.",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def take_snapshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    server_id = int(query.data.split("_")[1])
    await query.answer("⏳ در حال ارسال دستور اسنپ‌شات...", show_alert=True)
    
    try:
        server = hclient.servers.get_by_id(server_id)
        # اسم اسنپ‌شات را اتوماتیک می‌گذاریم
        snap_name = f"Snap-{server.name}"
        server.create_image(description=snap_name, type="snapshot")
        
        await query.edit_message_text(
            f"✅ دستور اسنپ‌شات برای `{server.name}` ارسال شد.\nاین عملیات ممکن است چند دقیقه طول بکشد.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به سرور", callback_data=f"srv_{server_id}")]])
        )
    except Exception as e:
        await query.edit_message_text(f"خطا در اسنپ‌شات: {str(e)}")

# --- بخش تغییر IP (Change IP) ---
async def change_ip_warning(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    server_id = int(query.data.split("_")[2])
    
    keyboard = [
        [InlineKeyboardButton("⚠️ بله، IP جدید بده (اطلاعات پاک شود)", callback_data=f"dochangeip_{server_id}")],
        [InlineKeyboardButton("❌ لغو", callback_data=f"srv_{server_id}")]
    ]
    await query.edit_message_text(
        "🚨 **هشدار تغییر IP** 🚨\n\nبرای دریافت IP جدید، سرور فعلی باید **حذف** و دوباره ساخته شود.\nآیا مطمئن هستید؟ (اطلاعات سرور پاک می‌شود)",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def process_change_ip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    server_id = int(query.data.split("_")[1])
    
    await query.edit_message_text("⏳ در حال تغییر هویت سرور... (لطفا صبر کنید)")
    
    try:
        # 1. دریافت اطلاعات سرور قدیمی
        old_server = hclient.servers.get_by_id(server_id)
        old_name = old_server.name
        old_type = old_server.server_type.name
        old_location = old_server.datacenter.location.name
        
        # 2. حذف سرور قدیمی
        old_server.delete()
        
        # 3. ساخت سرور جدید (با اوبونتو پیش‌فرض)
        # نکته: ساخت سرور حدود 10-20 ثانیه طول می‌کشد
        image = hclient.images.get_by_name("ubuntu-22.04")
        srv_type = hclient.server_types.get_by_name(old_type)
        
        new_server_response = hclient.servers.create(
            name=old_name,
            server_type=srv_type,
            image=image,
            location=hclient.locations.get_by_name(old_location)
        )
        
        new_server = new_server_response.server
        new_ip = new_server.public_net.ipv4.ip
        new_pass = new_server_response.root_password
        
        # 4. ارسال نتیجه به فرمت درخواستی شما
        success_msg = (
            f"✅ **New IP:** `{new_ip}`\n\n"
            f"🔑 **Password:** `{new_pass}`\n"
            f"سرور با موفقیت بازسازی شد."
        )
        
        await query.message.reply_text(
            success_msg,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به منو", callback_data="list_servers")]])
        )
        
    except Exception as e:
        await query.message.reply_text(f"❌ خطا در تغییر IP: {str(e)}")

# --- اکشن‌های عمومی ---
async def server_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    action, server_id = data.split("_")[0], int(data.split("_")[1])
    
    try:
        server = hclient.servers.get_by_id(server_id)
        
        if action == "on":
            server.power_on()
            await query.answer("دستور روشن شدن ارسال شد", show_alert=True)
        elif action == "off":
            server.power_off()
            await query.answer("دستور خاموش شدن ارسال شد", show_alert=True)
        elif action == "reset":
            server.reset()
            await query.answer("سرور ریست شد", show_alert=True)
            
        await server_details(update, context)
        
    except Exception as e:
        await query.answer(f"خطا: {str(e)}", show_alert=True)

# --- تایید و حذف نهایی ---
async def delete_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    server_id = int(query.data.split("_")[2])
    keyboard = [[InlineKeyboardButton("💀 حذف نهایی", callback_data=f"realdelete_{server_id}")], [InlineKeyboardButton("لغو", callback_data=f"srv_{server_id}")]]
    await query.edit_message_text("آیا از حذف سرور مطمئن هستید؟", reply_markup=InlineKeyboardMarkup(keyboard))

async def real_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    server_id = int(query.data.split("_")[1])
    hclient.servers.get_by_id(server_id).delete()
    await query.edit_message_text("🗑 سرور حذف شد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("لیست", callback_data="list_servers")]]))

async def create_new_server_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("⏳ در حال ساخت سرور...", show_alert=True)
    # ساخت یک سرور ساده ارزان (CX22) در آلمان
    try:
        resp = hclient.servers.create(
            name="New-Server-Bot",
            server_type=hclient.server_types.get_by_name("cx22"),
            image=hclient.images.get_by_name("ubuntu-22.04"),
            location=hclient.locations.get_by_name("nbg1")
        )
        await query.edit_message_text(f"✅ سرور ساخته شد!\nIP: `{resp.server.public_net.ipv4.ip}`\nPass: `{resp.root_password}`", parse_mode="Markdown")
    except Exception as e:
        await query.edit_message_text(f"خطا: {e}")

# --- اجرای برنامه ---
if __name__ == '__main__':
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(list_servers, pattern="^list_servers$"))
    app.add_handler(CallbackQueryHandler(server_details, pattern="^srv_"))
    
    # Snapshot Handlers
    app.add_handler(CallbackQueryHandler(snapshot_menu, pattern="^snap_menu_"))
    app.add_handler(CallbackQueryHandler(take_snapshot, pattern="^takesnap_"))
    
    # Change IP Handlers
    app.add_handler(CallbackQueryHandler(change_ip_warning, pattern="^changeip_warn_"))
    app.add_handler(CallbackQueryHandler(process_change_ip, pattern="^dochangeip_"))
    
    # Other Actions
    app.add_handler(CallbackQueryHandler(delete_confirm, pattern="^del_confirm_"))
    app.add_handler(CallbackQueryHandler(real_delete, pattern="^realdelete_"))
    app.add_handler(CallbackQueryHandler(create_new_server_handler, pattern="^create_new_server$"))
    app.add_handler(CallbackQueryHandler(server_actions, pattern="^(on|off|reset)_"))

    print("Bot is running...")
    app.run_polling()
