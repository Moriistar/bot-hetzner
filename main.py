import os
import logging
import paramiko  # <--- کتابخانه جدید برای SSH
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, CallbackQueryHandler
from telegram.error import BadRequest
from hcloud import Client
from hcloud.server_types import ServerType
from hcloud.images import Image

# --- تنظیمات اولیه ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
HETZNER_TOKEN = os.getenv("HETZNER_TOKEN")
# پسورد مشترک سرورها برای SSH زدن (یا می‌توانید از کلید SSH استفاده کنید)
SERVER_ROOT_PASSWORD = os.getenv("SERVER_ROOT_PASSWORD") 

EURO_PRICE = 65000 

hclient = Client(token=HETZNER_TOKEN)

# --- توابع کمکی ---

def check_admin(user_id):
    return user_id == ADMIN_ID

def format_bytes(size):
    if size is None: return "0.00"
    power = 2**30
    n = size / power
    return f"{n:.2f}"

def execute_ssh_command(ip_address, command):
    """تابع برای اتصال به سرور و اجرای دستور"""
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        # اتصال با پسورد (اگر از کلید SSH استفاده می‌کنید این خط را تغییر دهید)
        ssh.connect(ip_address, username='root', password=SERVER_ROOT_PASSWORD, timeout=5)
        
        stdin, stdout, stderr = ssh.exec_command(command)
        output = stdout.read().decode().strip()
        error = stderr.read().decode().strip()
        ssh.close()
        
        if error:
            return False, error
        return True, output
    except Exception as e:
        return False, str(e)

def get_server_keyboard(server_id, status):
    if status == "running":
        power_btn = InlineKeyboardButton("🔴 خاموش کردن", callback_data=f"off_{server_id}")
    else:
        power_btn = InlineKeyboardButton("🟢 روشن کردن", callback_data=f"on_{server_id}")
    
    keyboard = [
        [power_btn, InlineKeyboardButton("🔄 ریبوت", callback_data=f"reset_{server_id}")],
        [
            InlineKeyboardButton("💎 ارتقا منابع", callback_data=f"rescale_menu_{server_id}"),
            InlineKeyboardButton("➕ IP شناور (Auto)", callback_data=f"add_floating_{server_id}")
        ],
        [
            InlineKeyboardButton("📸 اسنپ‌شات", callback_data=f"snap_menu_{server_id}"),
            InlineKeyboardButton("🗑 حذف سرور", callback_data=f"del_confirm_{server_id}")
        ],
        [InlineKeyboardButton("🔙 بازگشت به لیست", callback_data="list_servers")]
    ]
    return InlineKeyboardMarkup(keyboard)

# --- هندلرها ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_admin(update.effective_user.id): return
    keyboard = [[InlineKeyboardButton("🖥 لیست سرورها", callback_data="list_servers")]]
    await update.message.reply_text("👋 پنل مدیریت سرور آماده است.", reply_markup=InlineKeyboardMarkup(keyboard))

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
                btn_text = f"{icon} {s.name} | {s.public_net.ipv4.ip}"
                keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"srv_{s.id}")])
        
        keyboard.append([InlineKeyboardButton("🔄 بروزرسانی", callback_data="list_servers")])
        keyboard.append([InlineKeyboardButton("➕ ساخت سرور جدید", callback_data="create_new_server")])
        
        try:
            await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        except BadRequest as e:
            if "Message is not modified" in str(e): pass
            else: raise e
                
    except Exception as e:
        await query.answer(f"خطا: {str(e)}", show_alert=True)

async def server_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    server_id = int(query.data.split("_")[1])
    
    try:
        server = hclient.servers.get_by_id(server_id)
        
        # Data & Price Calculations
        in_traffic = server.ingoing_traffic or 0
        out_traffic = server.outgoing_traffic or 0
        total = in_traffic + out_traffic
        included = server.included_traffic
        used_percent = (out_traffic / included * 100) if included else 0
        
        try:
            m_eur = float(server.server_type.prices[0]['price_monthly']['net'])
            h_eur = float(server.server_type.prices[0]['price_hourly']['net'])
        except:
            m_eur = 0.0; h_eur = 0.0
        
        m_toman = int(m_eur * EURO_PRICE)
        h_toman = int(h_eur * EURO_PRICE)

        img_name = server.image.name if server.image else "Custom/Snapshot"
        try: loc_str = f"{server.datacenter.location.city}, {server.datacenter.location.country}"
        except: loc_str = "Unknown"

        created_date = server.created.strftime("%Y-%m-%d")
        
        floating_ips = hclient.floating_ips.get_all()
        server_float_ips = [ip.ip for ip in floating_ips if ip.server and ip.server.id == server.id]
        float_ip_text = f"\n🔗 **Floating IPs:** `{', '.join(server_float_ips)}`" if server_float_ips else ""

        info_text = (
            f"🚀 **Name:** `{server.name}` [{'ON' if server.status=='running' else 'OFF'}]\n"
            f"🔗 **IPV4:** `{server.public_net.ipv4.ip}`\n"
            f"🔗 **IPV6:** `{server.public_net.ipv6.ip}`"
            f"{float_ip_text}\n"
            f"🌍 **Location:** {loc_str}\n"
            f"⚙️ **Cpu:** {server.server_type.cores} Core\n"
            f"💾 **Ram:** {server.server_type.memory} GB\n"
            f"💿 **Disk:** {server.server_type.disk} GB\n"
            f"🖼️ **Image:** {img_name}\n"
            f"📊 **Traffic:**\n"
            f" • In: `{format_bytes(in_traffic)} GB`\n"
            f" • Out: `{format_bytes(out_traffic)} GB`\n"
            f" • Total: `{format_bytes(total)} GB`\n"
            f" • Included: `{format_bytes(included)} GB`\n"
            f" • Used: `{used_percent:.1f}%`\n"
            f"💰 **Price:**\n"
            f" • Hourly: {h_eur}€ [{h_toman:,} T]\n"
            f" • Monthly: {m_eur}€ [{m_toman:,} T]\n"
            f"📅 **Created:** {created_date}"
        )

        try:
            await query.edit_message_text(info_text, reply_markup=get_server_keyboard(server_id, server.status), parse_mode="Markdown")
        except BadRequest as e:
            if "Message is not modified" in str(e): await query.answer("اطلاعات تغییر نکرده است ✅")
            else: raise e
    except Exception as e:
        await query.edit_message_text(f"❌ خطا: {str(e)}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="list_servers")]]))

# --- بخش IP شناور با کانفیگ خودکار ---

async def add_floating_ip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    server_id = int(query.data.split("_")[2])
    
    await query.answer("⏳ در حال خرید و تنظیم IP...", show_alert=True)
    
    try:
        server = hclient.servers.get_by_id(server_id)
        
        # 1. خرید IP از هتزنر
        floating_ip = hclient.floating_ips.create(
            type="ipv4",
            server=server,
            description=f"Auto-Bot for {server.name}"
        )
        new_ip = floating_ip.ip
        
        # 2. تلاش برای اجرای دستور داخل سرور (SSH)
        # دستور: ip addr add NEW_IP dev eth0
        # نکته: در برخی سرورها کارت شبکه ens3 است. ما eth0 را طبق درخواست شما زدیم.
        ssh_cmd = f"ip addr add {new_ip} dev eth0"
        
        # اتصال SSH
        main_ip = server.public_net.ipv4.ip
        status_msg = f"✅ **IP خریداری شد:** `{new_ip}`\n\n🔄 در حال تلاش برای فعال‌سازی داخل سرور..."
        await query.edit_message_text(status_msg, parse_mode="Markdown")
        
        if not SERVER_ROOT_PASSWORD:
             await query.edit_message_text(f"⚠️ IP `{new_ip}` اضافه شد اما کانفیگ نشد (پسورد SSH در env نیست).", 
                                           reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data=f"srv_{server_id}")]]))
             return

        success, output = execute_ssh_command(main_ip, ssh_cmd)
        
        if success:
            final_msg = (
                f"✅ **عملیات با موفقیت کامل شد!**\n\n"
                f"🔗 New IP: `{new_ip}`\n"
                f"💻 Config: دستور `ip addr` با موفقیت در سرور اجرا شد.\n"
                f"📍 Server: {server.name}"
            )
        else:
            final_msg = (
                f"⚠️ **IP خریداری شد اما کانفیگ نشد!**\n\n"
                f"🔗 New IP: `{new_ip}`\n"
                f"❌ خطا در SSH: {output}\n"
                f"لطفا دستی وارد سرور شوید و دستور زیر را بزنید:\n"
                f"`sudo ip addr add {new_ip} dev eth0`"
            )
            
        await query.edit_message_text(
            final_msg,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به منو", callback_data=f"srv_{server_id}")]])
        )

    except Exception as e:
         await query.edit_message_text(f"❌ خطا: {str(e)}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data=f"srv_{server_id}")]]))

# --- سایر هندلرها (بدون تغییر) ---

async def rescale_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    server_id = int(query.data.split("_")[2])
    plans = [("CX22", "cx22"), ("CX33", "cx33"), ("CPX11", "cpx11"), ("CPX21", "cpx21")]
    kb = [[InlineKeyboardButton(n, callback_data=f"dorescale_{server_id}_{c}")] for n, c in plans]
    kb.append([InlineKeyboardButton("🔙 لغو", callback_data=f"srv_{server_id}")])
    await query.edit_message_text("یکی از پلن‌ها را انتخاب کنید (سرور باید خاموش باشد):", reply_markup=InlineKeyboardMarkup(kb))

async def perform_rescale(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    d = query.data.split("_")
    try:
        server = hclient.servers.get_by_id(int(d[1]))
        if server.status != "off":
            await query.answer("❌ سرور باید خاموش باشد!", show_alert=True); return
        await query.edit_message_text("⏳ در حال ارتقا...")
        server.change_type(server_type=hclient.server_types.get_by_name(d[2]), upgrade_disk=False)
        await query.edit_message_text("✅ انجام شد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data=f"srv_{d[1]}")]]) )
    except Exception as e:
        await query.edit_message_text(f"خطا: {e}")

async def server_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    action, sid = query.data.split("_")[0], int(query.data.split("_")[1])
    try:
        srv = hclient.servers.get_by_id(sid)
        if action == "on": srv.power_on()
        elif action == "off": srv.power_off()
        elif action == "reset": srv.reset()
        await query.answer("انجام شد ✅")
        await server_details(update, context)
    except Exception as e:
        await query.answer(f"خطا: {e}", show_alert=True)

async def create_new_server_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.edit_message_text("⏳ در حال ساخت سرور...")
    try:
        img = hclient.images.get_by_name("ubuntu-22.04") or hclient.images.get_by_name("ubuntu-24.04")
        if img is None: await query.edit_message_text("❌ خطا: ایمیج اوبونتو یافت نشد."); return
        resp = hclient.servers.create(name="New-Bot-Server", server_type=hclient.server_types.get_by_name("cx22"), image=img, location=hclient.locations.get_by_name("nbg1"))
        await query.edit_message_text(f"✅ IP: `{resp.server.public_net.ipv4.ip}`\nPass: `{resp.root_password}`", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("بازگشت", callback_data="list_servers")]]))
    except Exception as e:
        await query.edit_message_text(f"خطا: {e}")

# (کدهای اسنپ شات و حذف و ... اینجا اضافه شوند که مثل قبل هستند)
async def delete_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    sid = int(q.data.split("_")[2])
    kb = [[InlineKeyboardButton("بله حذف شود", callback_data=f"realdelete_{sid}")], [InlineKeyboardButton("لغو", callback_data=f"srv_{sid}")]]
    await q.edit_message_text("مطمئن هستید؟", reply_markup=InlineKeyboardMarkup(kb))

async def real_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    sid = int(q.data.split("_")[1])
    hclient.servers.get_by_id(sid).delete()
    await q.edit_message_text("حذف شد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("لیست", callback_data="list_servers")]]))

async def snap_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    sid = int(q.data.split("_")[2])
    kb = [[InlineKeyboardButton("گرفتن بکاپ", callback_data=f"takesnap_{sid}")], [InlineKeyboardButton("بازگشت", callback_data=f"srv_{sid}")]]
    await q.edit_message_text("مدیریت اسنپ‌شات", reply_markup=InlineKeyboardMarkup(kb))

async def take_snapshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    sid = int(q.data.split("_")[1])
    await q.answer("ارسال شد...", show_alert=True)
    hclient.servers.get_by_id(sid).create_image(type="snapshot", description="Bot-Snap")
    await q.edit_message_text("دستور بکاپ ارسال شد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("بازگشت", callback_data=f"srv_{sid}")]]))

if __name__ == '__main__':
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(list_servers, pattern="^list_servers$"))
    app.add_handler(CallbackQueryHandler(server_details, pattern="^srv_"))
    app.add_handler(CallbackQueryHandler(rescale_menu, pattern="^rescale_menu_"))
    app.add_handler(CallbackQueryHandler(perform_rescale, pattern="^dorescale_"))
    app.add_handler(CallbackQueryHandler(add_floating_ip, pattern="^add_floating_"))
    app.add_handler(CallbackQueryHandler(server_actions, pattern="^(on|off|reset)_"))
    app.add_handler(CallbackQueryHandler(create_new_server_handler, pattern="^create_new_server$"))
    app.add_handler(CallbackQueryHandler(delete_confirm, pattern="^del_confirm_"))
    app.add_handler(CallbackQueryHandler(real_delete, pattern="^realdelete_"))
    app.add_handler(CallbackQueryHandler(snap_menu, pattern="^snap_menu_"))
    app.add_handler(CallbackQueryHandler(take_snapshot, pattern="^takesnap_"))

    print("Bot is running...")
    app.run_polling()
