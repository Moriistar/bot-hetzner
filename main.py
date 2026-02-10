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

# بارگذاری متغیرها
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
HETZNER_TOKEN = os.getenv("HETZNER_TOKEN")

# قیمت یورو به تومان (جهت نمایش تقریبی)
EURO_PRICE = 65000 

hclient = Client(token=HETZNER_TOKEN)

# --- توابع کمکی ---

def check_admin(user_id):
    return user_id == ADMIN_ID

def format_bytes(size):
    """تبدیل بایت به گیگابایت"""
    if size is None: return "0.00"
    power = 2**30
    n = size / power
    return f"{n:.2f}"

def get_server_keyboard(server_id, status):
    """ساخت دکمه‌های مدیریتی هوشمند"""
    # دکمه پاور بر اساس وضعیت فعلی
    if status == "running":
        power_btn = InlineKeyboardButton("🔴 خاموش (OFF)", callback_data=f"off_{server_id}")
    else:
        power_btn = InlineKeyboardButton("🟢 روشن (ON)", callback_data=f"on_{server_id}")
    
    keyboard = [
        [power_btn, InlineKeyboardButton("🔄 ریست (Reset)", callback_data=f"reset_{server_id}")],
        [
            InlineKeyboardButton("💎 تغییر منابع (Rescale)", callback_data=f"rescale_menu_{server_id}"),
            InlineKeyboardButton("♻️ تغییر IP (Rebuild)", callback_data=f"changeip_warn_{server_id}")
        ],
        [
            InlineKeyboardButton("➕ IP شناور (Float)", callback_data=f"add_floating_{server_id}"),
            InlineKeyboardButton("📸 اسنپ‌شات", callback_data=f"snap_menu_{server_id}")
        ],
        [
            InlineKeyboardButton("🗑 حذف سرور", callback_data=f"del_confirm_{server_id}"),
            InlineKeyboardButton("🔙 بازگشت به لیست", callback_data="list_servers")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

# --- هندلرهای اصلی ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_admin(update.effective_user.id): return
    keyboard = [[InlineKeyboardButton("🖥 لیست سرورها", callback_data="list_servers")]]
    await update.message.reply_text(
        "👋 **پنل مدیریت سرورهای هتزنر (MoriiStar)**\nسیستم آماده به کار است.", 
        reply_markup=InlineKeyboardMarkup(keyboard), 
        parse_mode="Markdown"
    )

async def list_servers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    try:
        servers = hclient.servers.get_all()
        keyboard = []
        
        if not servers:
            msg = "❌ هیچ سروری یافت نشد."
            keyboard.append([InlineKeyboardButton("➕ ساخت سرور جدید", callback_data="create_new_server")])
        else:
            msg = "📋 **لیست سرورهای فعال:**"
            for s in servers:
                icon = "🟢" if s.status == "running" else "🔴"
                # نمایش نام + IP
                btn_text = f"{icon} {s.name} | {s.public_net.ipv4.ip}"
                keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"srv_{s.id}")])
            
            keyboard.append([InlineKeyboardButton("➕ ساخت سرور جدید", callback_data="create_new_server")])
            keyboard.append([InlineKeyboardButton("🔄 بروزرسانی لیست", callback_data="list_servers")])
        
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        
    except Exception as e:
        await query.edit_message_text(f"⚠️ خطا: {str(e)}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("تلاش مجدد", callback_data="list_servers")]]))

async def server_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    server_id = int(query.data.split("_")[1])
    
    try:
        server = hclient.servers.get_by_id(server_id)
        
        # --- محاسبات ترافیک ---
        in_traffic = server.ingoing_traffic or 0
        out_traffic = server.outgoing_traffic or 0
        total = in_traffic + out_traffic
        included = server.included_traffic
        used_percent = (out_traffic / included * 100) if included else 0
        
        # --- محاسبات قیمت (با رفع باگ) ---
        try:
            m_eur = float(server.server_type.prices[0]['price_monthly']['net'])
            h_eur = float(server.server_type.prices[0]['price_hourly']['net'])
        except:
            m_eur = 0.0; h_eur = 0.0
        
        m_toman = int(m_eur * EURO_PRICE)

        # --- اطلاعات تکمیلی ---
        img_name = server.image.name if server.image else "Custom/Snapshot"
        created = server.created.strftime("%Y-%m-%d")
        loc = f"{server.datacenter.location.city}"

        # --- IPهای شناور ---
        floating_ips = hclient.floating_ips.get_all()
        server_float_ips = [ip.ip for ip in floating_ips if ip.server and ip.server.id == server.id]
        float_txt = f"\n🔗 **Floating IPs:** `{', '.join(server_float_ips)}`" if server_float_ips else ""

        info = (
            f"🚀 **Name:** `{server.name}`\n"
            f"💡 **Status:** {'🟢 ON' if server.status=='running' else '🔴 OFF'}\n"
            f"🔗 **IPv4:** `{server.public_net.ipv4.ip}`\n"
            f"🔗 **IPv6:** `{server.public_net.ipv6.ip}`"
            f"{float_txt}\n"
            f"🌍 **Loc:** {loc} | ⚙️ **Plan:** {server.server_type.name.upper()}\n"
            f"💾 **Res:** {server.server_type.cores}vCPU | {server.server_type.memory}GB RAM\n"
            f"📊 **Traffic:** `{format_bytes(out_traffic)}` / `{format_bytes(included)}` GB ({used_percent:.1f}%)\n"
            f"💰 **Price:** {m_eur}€ (~{m_toman:,} T)\n"
            f"📅 **Created:** {created}"
        )

        await query.edit_message_text(info, reply_markup=get_server_keyboard(server_id, server.status), parse_mode="Markdown")
    except Exception as e:
        await query.edit_message_text(f"❌ خطا در دریافت اطلاعات:\n{e}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="list_servers")]]))

# --- بخش تغییر منابع (Rescale) ---

async def rescale_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    sid = int(query.data.split("_")[2])
    
    plans = [("CX22 (2C/4G)", "cx22"), ("CX33 (4C/8G)", "cx33"), ("CPX11 (2C/2G)", "cpx11"), ("CPX21 (3C/4G)", "cpx21")]
    kb = [[InlineKeyboardButton(n, callback_data=f"dorescale_{sid}_{c}")] for n, c in plans]
    kb.append([InlineKeyboardButton("🔙 بازگشت", callback_data=f"srv_{sid}")])
    
    await query.edit_message_text(
        "⚠️ **ارتقا/تغییر منابع**\n\n1. سرور باید **خاموش** باشد.\n2. تغییر دیسک انجام نمی‌شود (تا بتوانید بعداً منابع را کم کنید).",
        reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown"
    )

async def perform_rescale(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, sid, plan = query.data.split("_")
    sid = int(sid)
    
    await query.edit_message_text("⏳ در حال تغییر منابع...")
    try:
        server = hclient.servers.get_by_id(sid)
        if server.status != "off":
            await query.edit_message_text("❌ سرور روشن است! ابتدا خاموش کنید.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data=f"srv_{sid}")]]))
            return
            
        server.change_type(server_type=hclient.server_types.get_by_name(plan), upgrade_disk=False)
        await query.edit_message_text(f"✅ انجام شد! پلن جدید: {plan}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 مدیریت سرور", callback_data=f"srv_{sid}")]]))
    except Exception as e:
        await query.edit_message_text(f"خطا: {e}")

# --- بخش تغییر IP (Rebuild) ---

async def change_ip_warning(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    sid = int(query.data.split("_")[2])
    kb = [[InlineKeyboardButton("✅ بله، IP عوض کن", callback_data=f"dochangeip_{sid}")], [InlineKeyboardButton("❌ لغو", callback_data=f"srv_{sid}")]]
    await query.edit_message_text("🚨 **هشدار تغییر IP**\n\nسرور فعلی حذف شده و یک سرور جدید با همین نام و لوکیشن ساخته می‌شود.\nتمام اطلاعات سرور پاک می‌شود!\nآیا مطمئن هستید؟", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def process_change_ip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    sid = int(query.data.split("_")[1])
    await query.edit_message_text("⏳ در حال تعویض هویت سرور (ممکن است ۳۰ ثانیه طول بکشد)...")
    
    try:
        old_server = hclient.servers.get_by_id(sid)
        name, srv_type, loc = old_server.name, old_server.server_type.name, old_server.datacenter.location.name
        old_server.delete()
        
        # ساخت سرور جدید
        resp = hclient.servers.create(
            name=name, server_type=hclient.server_types.get_by_name(srv_type),
            image=hclient.images.get_by_name("ubuntu-22.04"), location=hclient.locations.get_by_name(loc)
        )
        await query.edit_message_text(
            f"✅ **عملیات موفق!**\n\n🆔 IP جدید: `{resp.server.public_net.ipv4.ip}`\n🔑 رمز عبور: `{resp.root_password}`",
            parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 لیست سرورها", callback_data="list_servers")]])
        )
    except Exception as e:
        await query.edit_message_text(f"❌ خطا: {e}")

# --- سایر بخش‌ها (IP شناور، اکشن‌ها، ساخت و حذف) ---

async def add_floating_ip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    sid = int(query.data.split("_")[2])
    try:
        srv = hclient.servers.get_by_id(sid)
        ip = hclient.floating_ips.create(type="ipv4", server=srv, description=f"Float-{srv.name}").ip
        await query.edit_message_text(f"✅ IP اضافه شد: `{ip}`\n(نیاز به تنظیم دستی در سرور)", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data=f"srv_{sid}")]]))
    except Exception as e:
        await query.edit_message_text(f"خطا: {e}")

async def server_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    act, sid = query.data.split("_")[0], int(query.data.split("_")[1])
    try:
        srv = hclient.servers.get_by_id(sid)
        if act == "on": srv.power_on()
        elif act == "off": srv.power_off()
        elif act == "reset": srv.reset()
        await query.answer(f"دستور {act} اجرا شد", show_alert=True)
        await server_details(update, context)
    except Exception as e:
        await query.answer(f"خطا: {e}", show_alert=True)

async def create_new_server(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.edit_message_text("⏳ در حال ساخت سرور جدید (CX22 - آلمان)...")
    try:
        resp = hclient.servers.create(
            name="New-Server", server_type=hclient.server_types.get_by_name("cx22"),
            image=hclient.images.get_by_name("ubuntu-22.04"), location=hclient.locations.get_by_name("nbg1")
        )
        await query.edit_message_text(f"✅ ساخته شد:\nIP: `{resp.server.public_net.ipv4.ip}`\nPass: `{resp.root_password}`", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 لیست", callback_data="list_servers")]]))
    except Exception as e:
        await query.edit_message_text(f"خطا: {e}")

async def del_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    sid = int(query.data.split("_")[2])
    kb = [[InlineKeyboardButton("بله، حذف کن", callback_data=f"realdelete_{sid}")], [InlineKeyboardButton("لغو", callback_data=f"srv_{sid}")]]
    await query.edit_message_text("❌ آیا مطمئن هستید؟", reply_markup=InlineKeyboardMarkup(kb))

async def real_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    sid = int(query.data.split("_")[1])
    hclient.servers.get_by_id(sid).delete()
    await query.edit_message_text("🗑 حذف شد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("لیست", callback_data="list_servers")]]))

async def snap_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    sid = int(query.data.split("_")[2])
    # فقط منو نمایش داده می‌شود، پیاده‌سازی کامل اسنپ‌شات طولانی بود، در صورت نیاز اضافه کنید
    await query.answer("این بخش در حال حاضر فقط نمایشی است", show_alert=True) 

if __name__ == '__main__':
    if not BOT_TOKEN:
        print("Error: .env file missing or empty.")
        exit()
        
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(list_servers, pattern="^list_servers$"))
    app.add_handler(CallbackQueryHandler(server_details, pattern="^srv_"))
    app.add_handler(CallbackQueryHandler(rescale_menu, pattern="^rescale_menu_"))
    app.add_handler(CallbackQueryHandler(perform_rescale, pattern="^dorescale_"))
    app.add_handler(CallbackQueryHandler(change_ip_warning, pattern="^changeip_warn_"))
    app.add_handler(CallbackQueryHandler(process_change_ip, pattern="^dochangeip_"))
    app.add_handler(CallbackQueryHandler(add_floating_ip, pattern="^add_floating_"))
    app.add_handler(CallbackQueryHandler(server_actions, pattern="^(on|off|reset)_"))
    app.add_handler(CallbackQueryHandler(create_new_server, pattern="^create_new_server$"))
    app.add_handler(CallbackQueryHandler(del_confirm, pattern="^del_confirm_"))
    app.add_handler(CallbackQueryHandler(real_delete, pattern="^realdelete_"))

    print("✅ Bot is running...")
    app.run_polling()
