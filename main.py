import os
import logging
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, CallbackQueryHandler
from hcloud import Client
from hcloud.server_types import ServerType
from hcloud.images import Image

# --- تنظیمات اولیه ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# بارگذاری متغیرها از فایل .env
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
HETZNER_TOKEN = os.getenv("HETZNER_TOKEN")

# قیمت یورو به تومان (برای محاسبه قیمت تقریبی)
EURO_PRICE = 65000 

# اتصال به هتزنر
hclient = Client(token=HETZNER_TOKEN)

# --- توابع کمکی ---

def check_admin(user_id):
    """بررسی اینکه آیا کاربر ادمین است یا خیر"""
    return user_id == ADMIN_ID

def format_bytes(size):
    """تبدیل بایت به گیگابایت برای نمایش زیباتر"""
    if size is None:
        return "0.00"
    power = 2**30 # 1024**3
    n = size / power
    return f"{n:.2f}"

def get_server_keyboard(server_id, status):
    """ساخت دکمه‌های شیشه‌ای مدیریت سرور"""
    # دکمه روشن/خاموش هوشمند
    if status == "running":
        power_btn = InlineKeyboardButton("🔴 خاموش کردن", callback_data=f"off_{server_id}")
    else:
        power_btn = InlineKeyboardButton("🟢 روشن کردن", callback_data=f"on_{server_id}")
    
    keyboard = [
        [power_btn, InlineKeyboardButton("🔄 ریبوت (Reset)", callback_data=f"reset_{server_id}")],
        [
            InlineKeyboardButton("💎 ارتقا منابع (Rescale)", callback_data=f"rescale_menu_{server_id}"),
            InlineKeyboardButton("➕ IP اضافه (Floating)", callback_data=f"add_floating_{server_id}")
        ],
        [
            InlineKeyboardButton("📸 اسنپ‌شات", callback_data=f"snap_menu_{server_id}"),
            InlineKeyboardButton("🗑 حذف سرور", callback_data=f"del_confirm_{server_id}")
        ],
        [InlineKeyboardButton("🔙 بازگشت به لیست", callback_data="list_servers")]
    ]
    return InlineKeyboardMarkup(keyboard)

# --- هندلرها (توابع اصلی) ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_admin(update.effective_user.id):
        return
    
    keyboard = [[InlineKeyboardButton("🖥 لیست سرورها", callback_data="list_servers")]]
    await update.message.reply_text(
        "👋 سلام رئیس! پنل مدیریت سرور هتزنر آماده است.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def list_servers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    try:
        servers = hclient.servers.get_all()
        keyboard = []
        
        if not servers:
            msg = "❌ هیچ سروری یافت نشد."
        else:
            msg = "📋 **لیست سرورهای فعال:**"
            for s in servers:
                icon = "🟢" if s.status == "running" else "🔴"
                # نمایش نام + IP اصلی
                btn_text = f"{icon} {s.name} | {s.public_net.ipv4.ip}"
                keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"srv_{s.id}")])
        
        # دکمه‌های پایین لیست
        keyboard.append([InlineKeyboardButton("🔄 بروزرسانی", callback_data="list_servers")])
        keyboard.append([InlineKeyboardButton("➕ ساخت سرور جدید (Ubuntu)", callback_data="create_new_server")])
        
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        
    except Exception as e:
        await query.edit_message_text(f"خطا در دریافت لیست: {str(e)}")

async def server_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    server_id = int(query.data.split("_")[1])
    
    try:
        server = hclient.servers.get_by_id(server_id)
        
        # --- محاسبات ترافیک ---
        in_traffic = server.ingoing_traffic or 0
        out_traffic = server.outgoing_traffic or 0
        total_traffic = in_traffic + out_traffic
        included_traffic = server.included_traffic
        
        used_percent = 0
        if included_traffic and included_traffic > 0:
            used_percent = (out_traffic / included_traffic) * 100
        
        # --- محاسبات قیمت (رفع باگ int) ---
        # نکته مهم: قیمت‌ها به صورت رشته برمی‌گردند، باید float شوند
        try:
            monthly_eur = float(server.server_type.prices[0]['price_monthly']['net'])
            hourly_eur = float(server.server_type.prices[0]['price_hourly']['net'])
        except (ValueError, TypeError, IndexError):
            monthly_eur = 0.0
            hourly_eur = 0.0
            
        monthly_toman = int(monthly_eur * EURO_PRICE)
        hourly_toman = int(hourly_eur * EURO_PRICE)

        # --- تاریخ و زمان ---
        created_date = server.created.strftime("%Y-%m-%d")
        days_ago = (datetime.now(server.created.tzinfo) - server.created).days

        # --- پیدا کردن Floating IPها ---
        floating_ips = hclient.floating_ips.get_all()
        # فقط IPهایی که به این سرور وصل هستند
        server_float_ips = [ip.ip for ip in floating_ips if ip.server and ip.server.id == server.id]
        if server_float_ips:
            float_ip_text = f"\n🔗 **Floating IPs:** `{', '.join(server_float_ips)}`"
        else:
            float_ip_text = ""

        # --- متن نهایی (UI درخواستی) ---
        info_text = (
            f"🚀 **Name:** `{server.name}` [{'running' if server.status=='running' else 'off'}]\n"
            f"🔗 **IPV4:** `{server.public_net.ipv4.ip}`\n"
            f"🔗 **IPV6:** `{server.public_net.ipv6.ip}`"
            f"{float_ip_text}\n"
            f"🌍 **Location:** {server.datacenter.location.city}, {server.datacenter.location.country}\n"
            f"⚙️ **Cpu:** {server.server_type.cores} Core\n"
            f"💾 **Ram:** {server.server_type.memory} GB\n"
            f"💿 **Disk:** {server.server_type.disk} GB\n"
            f"🖼️ **Image:** {server.image.name if server.image else 'Custom'}\n"
            f"📊 **Traffic:**\n"
            f" • In: `{format_bytes(in_traffic)} GB`\n"
            f" • Out: `{format_bytes(out_traffic)} GB`\n"
            f" • Total: `{format_bytes(total_traffic)} GB`\n"
            f" • Included: `{format_bytes(included_traffic)} GB`\n"
            f" • Used: `{used_percent:.1f}%` [Out/Included]\n"
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
        # اگر خطایی رخ داد، لاگ کن و به کاربر بگو
        logging.error(f"Error in server_details: {e}")
        await query.edit_message_text(
            f"❌ خطایی رخ داد:\n`{str(e)}`",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="list_servers")]]),
            parse_mode="Markdown"
        )

# --- بخش ارتقا (Rescale) ---
async def rescale_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    server_id = int(query.data.split("_")[2])
    
    # لیست پلن‌های معروف هتزنر
    plans = [
        ("CX22 (2vCPU / 4GB)", "cx22"),
        ("CX33 (4vCPU / 8GB)", "cx33"),
        ("CX43 (8vCPU / 16GB)", "cx43"),
        ("CPX11 (2vCPU / 2GB)", "cpx11"),
        ("CPX21 (3vCPU / 4GB)", "cpx21"),
    ]
    
    keyboard = []
    for name, code in plans:
        keyboard.append([InlineKeyboardButton(name, callback_data=f"dorescale_{server_id}_{code}")])
    keyboard.append([InlineKeyboardButton("🔙 لغو", callback_data=f"srv_{server_id}")])

    await query.edit_message_text(
        "⚠️ **منوی ارتقا (Rescale)**\n\n"
        "1. برای ارتقا سرور باید **خاموش** باشد.\n"
        "2. تغییر فقط روی CPU/RAM اعمال می‌شود (دیسک تغییر نمی‌کند).\n\n"
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
        
        if server.status != "off":
            await query.edit_message_text(
                "❌ **خطا:** سرور روشن است!\nلطفا ابتدا سرور را خاموش کنید.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data=f"srv_{server_id}")]])
            )
            return

        new_type = hclient.server_types.get_by_name(plan_name)
        # upgrade_disk=False خیلی مهم است تا بتوانید بعدا دوباره Downgrade کنید
        server.change_type(server_type=new_type, upgrade_disk=False)
        
        await query.edit_message_text(
            f"✅ ارتقا به پلن `{plan_name}` با موفقیت انجام شد!\nمی‌توانید سرور را روشن کنید.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 مدیریت سرور", callback_data=f"srv_{server_id}")]])
        )
    except Exception as e:
        await query.edit_message_text(f"❌ خطا در ارتقا: {str(e)}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data=f"srv_{server_id}")]]))

# --- بخش IP شناور (Floating IP) ---
async def add_floating_ip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    server_id = int(query.data.split("_")[2])
    
    await query.answer("⏳ در حال خرید IP...", show_alert=True)
    
    try:
        server = hclient.servers.get_by_id(server_id)
        
        # ساخت IP جدید در لوکیشن سرور
        floating_ip = hclient.floating_ips.create(
            type="ipv4",
            server=server,
            description=f"Extra IP for {server.name}"
        )
        
        new_ip = floating_ip.ip
        
        await query.edit_message_text(
            f"✅ **IP جدید اضافه شد!**\n\n"
            f"🔗 New IP: `{new_ip}`\n"
            f"📍 Server: {server.name}\n\n"
            f"نکته: برای استفاده از این IP باید تنظیمات شبکه لینوکس سرور را دستی انجام دهید.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به منو", callback_data=f"srv_{server_id}")]])
        )
    except Exception as e:
         await query.edit_message_text(f"❌ خطا: {str(e)}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data=f"srv_{server_id}")]]))

# --- بخش اسنپ‌شات ---
async def snapshot_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    server_id = int(query.data.split("_")[2])
    keyboard = [
        [InlineKeyboardButton("📸 گرفتن اسنپ‌شات (اکنون)", callback_data=f"takesnap_{server_id}")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data=f"srv_{server_id}")]
    ]
    await query.edit_message_text("📸 **مدیریت اسنپ‌شات**\nهزینه: 0.01 یورو/گیگابایت در ماه.", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def take_snapshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    server_id = int(query.data.split("_")[1])
    await query.answer("در حال ارسال دستور...", show_alert=True)
    try:
        server = hclient.servers.get_by_id(server_id)
        server.create_image(description=f"Snap-{server.name}", type="snapshot")
        await query.edit_message_text(f"✅ دستور اسنپ‌شات صادر شد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data=f"srv_{server_id}")]]))
    except Exception as e:
        await query.edit_message_text(f"خطا: {e}")

# --- عملیات عمومی (روشن/خاموش/ریست/حذف) ---
async def server_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action, server_id = query.data.split("_")[0], int(query.data.split("_")[1])
    
    try:
        server = hclient.servers.get_by_id(server_id)
        if action == "on": server.power_on()
        elif action == "off": server.power_off()
        elif action == "reset": server.reset()
        
        await query.answer(f"دستور {action} انجام شد ✅", show_alert=True)
        # رفرش کردن صفحه برای دیدن وضعیت جدید
        await server_details(update, context)
    except Exception as e:
        await query.answer(f"خطا: {e}", show_alert=True)

async def delete_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    server_id = int(query.data.split("_")[2])
    keyboard = [[InlineKeyboardButton("💀 بله حذف شود", callback_data=f"realdelete_{server_id}")], [InlineKeyboardButton("لغو", callback_data=f"srv_{server_id}")]]
    await query.edit_message_text("🚨 آیا مطمئن هستید؟ این کار غیرقابل بازگشت است!", reply_markup=InlineKeyboardMarkup(keyboard))

async def real_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    server_id = int(query.data.split("_")[1])
    try:
        hclient.servers.get_by_id(server_id).delete()
        await query.edit_message_text("🗑 سرور با موفقیت حذف شد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("لیست سرورها", callback_data="list_servers")]]))
    except Exception as e:
        await query.edit_message_text(f"خطا در حذف: {e}")

async def create_new_server_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.edit_message_text("⏳ در حال ساخت سرور جدید (CX22 - Ubuntu)...")
    try:
        # ساخت یک سرور پیش‌فرض ارزان
        resp = hclient.servers.create(
            name="New-Bot-Server",
            server_type=hclient.server_types.get_by_name("cx22"),
            image=hclient.images.get_by_name("ubuntu-22.04"),
            location=hclient.locations.get_by_name("nbg1") # آلمان
        )
        await query.edit_message_text(
            f"✅ سرور ساخته شد!\nIP: `{resp.server.public_net.ipv4.ip}`\nPass: `{resp.root_password}`",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("بازگشت", callback_data="list_servers")]])
        )
    except Exception as e:
        await query.edit_message_text(f"خطا: {e}")

# --- بدنه اصلی برنامه ---
if __name__ == '__main__':
    if not BOT_TOKEN or not HETZNER_TOKEN:
        print("Error: Please set BOT_TOKEN and HETZNER_TOKEN in .env file")
        exit(1)

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # دستور استارت
    app.add_handler(CommandHandler("start", start))
    
    # لیست و جزئیات
    app.add_handler(CallbackQueryHandler(list_servers, pattern="^list_servers$"))
    app.add_handler(CallbackQueryHandler(server_details, pattern="^srv_"))
    
    # هندلرهای ارتقا (Rescale)
    app.add_handler(CallbackQueryHandler(rescale_menu, pattern="^rescale_menu_"))
    app.add_handler(CallbackQueryHandler(perform_rescale, pattern="^dorescale_"))
    
    # هندلر IP شناور
    app.add_handler(CallbackQueryHandler(add_floating_ip, pattern="^add_floating_"))
    
    # هندلرهای اسنپ‌شات
    app.add_handler(CallbackQueryHandler(snapshot_menu, pattern="^snap_menu_"))
    app.add_handler(CallbackQueryHandler(take_snapshot, pattern="^takesnap_"))
    
    # هندلرهای حذف و ساخت
    app.add_handler(CallbackQueryHandler(delete_confirm, pattern="^del_confirm_"))
    app.add_handler(CallbackQueryHandler(real_delete, pattern="^realdelete_"))
    app.add_handler(CallbackQueryHandler(create_new_server_handler, pattern="^create_new_server$"))
    
    # هندلرهای عمومی (Power/Reset)
    app.add_handler(CallbackQueryHandler(server_actions, pattern="^(on|off|reset)_"))

    print("Bot is running successfully...")
    app.run_polling()
