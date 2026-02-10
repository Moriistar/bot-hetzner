import os
import logging
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, CallbackQueryHandler
from hcloud import Client
from hcloud.server_types import ServerType

# --- تنظیمات اولیه ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
HETZNER_TOKEN = os.getenv("HETZNER_TOKEN")

# قیمت یورو به تومان (جهت نمایش در فاکتور) - قابل تغییر
EURO_PRICE = 65000 

hclient = Client(token=HETZNER_TOKEN)

# --- توابع کمکی و فرمت‌دهی ---
def check_admin(user_id):
    return user_id == ADMIN_ID

def format_bytes(size):
    # تبدیل بایت به گیگابایت
    power = 2**30
    n = size / power
    return f"{n:.2f}"

def get_server_keyboard(server_id, status):
    """منوی اصلی مدیریت سرور"""
    # دکمه روشن/خاموش بر اساس وضعیت فعلی
    power_btn = InlineKeyboardButton("🔴 خاموش کردن", callback_data=f"off_{server_id}") if status == "running" else InlineKeyboardButton("🟢 روشن کردن", callback_data=f"on_{server_id}")
    
    keyboard = [
        [power_btn, InlineKeyboardButton("🔄 ریبوت", callback_data=f"reset_{server_id}")],
        [InlineKeyboardButton("💎 ارتقا منابع (Rescale)", callback_data=f"rescale_menu_{server_id}")],
        [InlineKeyboardButton("➕ افزودن IP جدید (Floating)", callback_data=f"add_floating_{server_id}")],
        [InlineKeyboardButton("📸 اسنپ‌شات", callback_data=f"snap_menu_{server_id}"), InlineKeyboardButton("🗑 حذف سرور", callback_data=f"del_confirm_{server_id}")],
        [InlineKeyboardButton("🔙 بازگشت به لیست", callback_data="list_servers")]
    ]
    return InlineKeyboardMarkup(keyboard)

# --- هندلرها ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_admin(update.effective_user.id): return
    await update.message.reply_text("👋 پنل مدیریت سرور آماده است:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🖥 لیست سرورها", callback_data="list_servers")]]))

async def list_servers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        servers = hclient.servers.get_all()
        if not servers:
            await query.edit_message_text("❌ سروری یافت نشد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("➕ ساخت سرور جدید", callback_data="create_new_server")]]))
            return

        keyboard = []
        for s in servers:
            icon = "🟢" if s.status == "running" else "🔴"
            keyboard.append([InlineKeyboardButton(f"{icon} {s.name} | {s.public_net.ipv4.ip}", callback_data=f"srv_{s.id}")])
        
        keyboard.append([InlineKeyboardButton("🔄 بروزرسانی", callback_data="list_servers"), InlineKeyboardButton("➕ ساخت سرور جدید", callback_data="create_new_server")])
        await query.edit_message_text("📋 لیست سرورهای شما:", reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        await query.edit_message_text(f"Error: {e}")

async def server_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    server_id = int(query.data.split("_")[1])
    
    try:
        server = hclient.servers.get_by_id(server_id)
        
        # --- محاسبات دیتا ---
        # ترافیک (توجه: هتزنر ترافیک دقیق را در لحظه ممکن است ندهد، این مقادیر از آبجکت سرور خوانده می‌شود)
        in_traffic = server.ingoing_traffic or 0
        out_traffic = server.outgoing_traffic or 0
        total_traffic = in_traffic + out_traffic
        included_traffic = server.included_traffic # معمولا 20TB
        
        used_percent = (out_traffic / included_traffic * 100) if included_traffic else 0
        
        # قیمت‌ها
        monthly_eur = server.server_type.prices[0]['price_monthly']['net']
        hourly_eur = server.server_type.prices[0]['price_hourly']['net']
        
        monthly_toman = int(monthly_eur * EURO_PRICE)
        hourly_toman = int(hourly_eur * EURO_PRICE)

        # تاریخ ساخت
        created_date = server.created.strftime("%Y-%m-%d")
        days_ago = (datetime.now(server.created.tzinfo) - server.created).days

        # لیست IPهای شناور (Floating IPs)
        floating_ips = hclient.floating_ips.get_all()
        server_float_ips = [ip.ip for ip in floating_ips if ip.server and ip.server.id == server.id]
        float_ip_text = f"\n🔗 **Floating IPs:** {', '.join(server_float_ips)}" if server_float_ips else ""

        # --- متن نهایی شبیه نمونه شما ---
        info_text = (
            f"🚀 **Name:** `{server.name}` [{'running' if server.status=='running' else 'off'}]\n"
            f"🔗 **IPV4:** `{server.public_net.ipv4.ip}`\n"
            f"🔗 **IPV6:** `{server.public_net.ipv6.ip}`"
            f"{float_ip_text}\n"
            f"🌍 **Location:** {server.datacenter.location.city}, {server.datacenter.location.country}\n"
            f"⚙️ **Cpu:** {server.server_type.cores} Core\n"
            f"💾 **Ram:** {server.server_type.memory} GB\n"
            f"💿 **Disk:** {server.server_type.disk} GB\n"
            f"📸 **Snapshots:** ن/م\n" # تعداد اسنپ شات نیاز به کال جدا دارد
            f"🖼️ **Image:** {server.image.name if server.image else 'Custom'}\n"
            f"📊 **Traffic:**\n"
            f" • In: {format_bytes(in_traffic)} GB\n"
            f" • Out: {format_bytes(out_traffic)} GB\n"
            f" • Total: {format_bytes(total_traffic)} GB\n"
            f" • Included: {format_bytes(included_traffic)} GB\n"
            f" • Used: {used_percent:.1f}% [Out/Included]\n"
            f"💰 **Price:**\n"
            f" • Hourly: {hourly_eur}€ [{hourly_toman:,} T]\n"
            f" • Monthly: {monthly_eur}€ [{monthly_toman:,} T]\n"
            f"📅 **Created:** {created_date} [{days_ago} days ago]"
        )

        await query.edit_message_text(
            info_text,
            reply_markup=get_server_keyboard(server_id, server.status),
            parse_mode="Markdown"
        )
    except Exception as e:
        await query.edit_message_text(f"Error: {e}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="list_servers")]]))

# --- بخش ارتقا (Rescale) ---
async def rescale_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    server_id = int(query.data.split("_")[2])
    
    # لیست پلن‌های محبوب
    plans = [
        ("CX22 (2vCPU/4GB)", "cx22"),
        ("CX33 (4vCPU/8GB)", "cx33"),
        ("CX43 (8vCPU/16GB)", "cx43"),
        ("CPX11 (2vCPU/2GB)", "cpx11"),
        ("CPX21 (3vCPU/4GB)", "cpx21"),
    ]
    
    keyboard = []
    for name, code in plans:
        keyboard.append([InlineKeyboardButton(name, callback_data=f"dorescale_{server_id}_{code}")])
    keyboard.append([InlineKeyboardButton("🔙 لغو", callback_data=f"srv_{server_id}")])

    await query.edit_message_text(
        "⚠️ **منوی ارتقا (Rescale)**\n\n"
        "1. برای ارتقا سرور باید **خاموش** باشد.\n"
        "2. تغییر فقط روی CPU/RAM اعمال می‌شود (دیسک تغییر نمی‌کند تا امکان بازگشت به پلن پایین‌تر باشد).\n\n"
        "یکی از پلن‌های زیر را انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def perform_rescale(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data.split("_")
    server_id = int(data[1])
    plan_name = data[2]
    
    await query.edit_message_text(f"⏳ در حال تغییر پلن به {plan_name}...\nلطفا صبر کنید.")
    
    try:
        server = hclient.servers.get_by_id(server_id)
        
        # چک کردن خاموش بودن سرور
        if server.status != "off":
            await query.edit_message_text(
                "❌ **خطا:** سرور روشن است!\nلطفا ابتدا سرور را خاموش کنید و دوباره تلاش کنید.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data=f"srv_{server_id}")]])
            )
            return

        new_type = hclient.server_types.get_by_name(plan_name)
        # upgrade_disk=False یعنی دیسک بزرگ نشود تا بشود بعدا دوباره پلن را ضعیف کرد (Downscale)
        server.change_type(server_type=new_type, upgrade_disk=False)
        
        await query.edit_message_text(
            f"✅ ارتقا به پلن `{plan_name}` با موفقیت انجام شد!\nمی‌توانید سرور را روشن کنید.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 مدیریت سرور", callback_data=f"srv_{server_id}")]])
        )
    except Exception as e:
        await query.edit_message_text(f"❌ خطا در ارتقا: {str(e)}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data=f"srv_{server_id}")]]))

# --- بخش IP اضافه (Floating IP) ---
async def add_floating_ip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    server_id = int(query.data.split("_")[2])
    
    try:
        server = hclient.servers.get_by_id(server_id)
        location = server.datacenter.location # IP باید در لوکیشن سرور باشد
        
        # ساخت IP جدید
        floating_ip = hclient.floating_ips.create(
            type="ipv4",
            server=server,
            description=f"Extra IP for {server.name}"
        )
        
        new_ip = floating_ip.ip
        
        await query.edit_message_text(
            f"✅ **IP جدید با موفقیت اضافه شد!**\n\n"
            f"🔗 New IP: `{new_ip}`\n"
            f"📍 Location: {location.name}\n\n"
            f"این IP الان روی سرور شما ست شده است. برای استفاده باید در تنظیمات شبکه لینوکس (Netplan) آن را اضافه کنید.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data=f"srv_{server_id}")]])
        )

    except Exception as e:
         await query.edit_message_text(f"❌ خطا در ساخت IP: {str(e)}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data=f"srv_{server_id}")]]))


# --- سایر اکشن‌های ساده ---
async def server_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action, server_id = query.data.split("_")[0], int(query.data.split("_")[1])
    try:
        server = hclient.servers.get_by_id(server_id)
        if action == "on": server.power_on()
        elif action == "off": server.power_off()
        elif action == "reset": server.reset()
        
        await query.answer(f"دستور {action} ارسال شد", show_alert=True)
        await server_details(update, context) # رفرش صفحه
    except Exception as e:
        await query.answer(f"خطا: {e}", show_alert=True)

# --- اجرای برنامه ---
if __name__ == '__main__':
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(list_servers, pattern="^list_servers$"))
    app.add_handler(CallbackQueryHandler(server_details, pattern="^srv_"))
    
    # Rescale Handlers
    app.add_handler(CallbackQueryHandler(rescale_menu, pattern="^rescale_menu_"))
    app.add_handler(CallbackQueryHandler(perform_rescale, pattern="^dorescale_"))
    
    # Floating IP Handler
    app.add_handler(CallbackQueryHandler(add_floating_ip, pattern="^add_floating_"))
    
    # Actions
    app.add_handler(CallbackQueryHandler(server_actions, pattern="^(on|off|reset)_"))

    print("Bot is running...")
    app.run_polling()
