import os
import logging
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes, ConversationHandler, MessageHandler, filters
from hcloud import Client
from hcloud.images.domain import Image
from hcloud.server_types.domain import ServerType
from hcloud.locations.domain import Location
from hcloud.floating_ips.domain import FloatingIPType

# --- 1. پیکربندی ---
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")
HETZNER_TOKEN = os.getenv("HETZNER_TOKEN")
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID")

hetzner = Client(token=HETZNER_TOKEN)

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

WAITING_FOR_NAME = 1

# --- 2. توابع کمکی ---
async def check_admin(update: Update):
    user_id = str(update.effective_user.id)
    if user_id != ADMIN_ID:
        await update.effective_message.reply_text("⛔ دسترسی غیرمجاز!")
        return False
    return True

async def send_log(context: ContextTypes.DEFAULT_TYPE, message: str):
    if LOG_CHANNEL_ID:
        try:
            await context.bot.send_message(chat_id=LOG_CHANNEL_ID, text=f"📝 #LOG\n{message}")
        except Exception as e:
            logger.error(f"Error sending log: {e}")

def back_button(target='main_menu'):
    return InlineKeyboardButton("🔙 برگشت", callback_data=target)

# --- 3. منوها ---
def main_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("➕ ساخت سرور جدید", callback_data='create_server_start')],
        [InlineKeyboardButton("🖥 لیست سرورها", callback_data='list_servers')],
    ]
    return InlineKeyboardMarkup(keyboard)

# --- 4. هندلرها ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update): return
    text = "👋 **پنل مدیریت پیشرفته هتزنر**\n\nمدیریت سرورها و آی‌پی‌های چندگانه:"
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text=text, reply_markup=main_menu_keyboard(), parse_mode='Markdown')
    else:
        await update.message.reply_text(text=text, reply_markup=main_menu_keyboard(), parse_mode='Markdown')

async def list_servers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("دریافت لیست...")
    try:
        servers = hetzner.servers.get_all()
        if not servers:
            await query.edit_message_text("❌ سروری یافت نشد.", reply_markup=InlineKeyboardMarkup([[back_button()]]))
            return

        keyboard = []
        for server in servers:
            status = "🟢" if server.status == "running" else "🔴"
            ip = server.public_net.ipv4.ip if server.public_net.ipv4 else "No IP"
            keyboard.append([InlineKeyboardButton(f"{status} {server.name} | {ip}", callback_data=f'manage_{server.id}')])
        
        keyboard.append([back_button()])
        await query.edit_message_text("🖥 **لیست سرورها:**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    except Exception as e:
        await query.edit_message_text(f"خطا: {e}", reply_markup=InlineKeyboardMarkup([[back_button()]]))

async def manage_server(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    server_id = int(query.data.split('_')[1])
    try:
        server = hetzner.servers.get_by_id(server_id)
        
        # دریافت آی‌پی‌های شناور (Floating IPs) متصل به این سرور
        floating_ips = hetzner.floating_ips.get_all()
        server_floating_ips = [ip.ip for ip in floating_ips if ip.server and ip.server.id == server.id]
        
        ip_list_text = f"1️⃣ Main: `{server.public_net.ipv4.ip}`"
        for i, fip in enumerate(server_floating_ips):
            ip_list_text += f"\n{i+2}️⃣ Float: `{fip}`"

        info = (
            f"🖥 **{server.name}**\n"
            f"📍 `{server.datacenter.location.name}` | 💡 `{server.status}`\n"
            f"➖➖➖➖➖➖\n"
            f"🌐 **لیست آی‌پی‌ها:**\n{ip_list_text}\n"
            f"➖➖➖➖➖➖"
        )

        keyboard = [
            [InlineKeyboardButton("➕ خرید آی‌پی جدید (Floating IP)", callback_data=f'action_addip_{server_id}')],
            [InlineKeyboardButton("⚡ خاموش/روشن", callback_data=f'action_power_{server_id}'),
             InlineKeyboardButton("🔄 ریستارت", callback_data=f'action_reboot_{server_id}')],
            [InlineKeyboardButton("♻️ تغییر آی‌پی اصلی", callback_data=f'action_changeip_{server_id}')],
            [InlineKeyboardButton("🗑 حذف سرور", callback_data=f'action_delete_{server_id}')],
            [back_button('list_servers')]
        ]
        
        await query.edit_message_text(info, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    except Exception as e:
        await query.edit_message_text(f"Error: {e}", reply_markup=InlineKeyboardMarkup([[back_button('list_servers')]]))

async def server_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data.split('_')
    action = data[1]
    server_id = int(data[2])

    # تاییدیه
    if action in ['delete', 'changeip', 'addip'] and 'confirm' not in data:
        warn = "⚠️ **تایید عملیات**\n"
        if action == 'addip': warn += "آیا مطمئنید؟ آی‌پی اضافه در هتزنر هزینه دارد (حدود 4 یورو)."
        elif action == 'changeip': warn += "سرور فعلی حذف و سرور جدید ساخته می‌شود!"
        elif action == 'delete': warn += "حذف سرور غیرقابل بازگشت است."
        
        btns = [[InlineKeyboardButton("✅ بله", callback_data=f'{query.data}_confirm'), InlineKeyboardButton("❌ خیر", callback_data=f'manage_{server_id}')]]
        await query.edit_message_text(warn, reply_markup=InlineKeyboardMarkup(btns), parse_mode='Markdown')
        return

    try:
        server = hetzner.servers.get_by_id(server_id)

        if action == 'power':
            await query.answer("تغییر وضعیت پاور...")
            if server.status == 'running': server.power_off()
            else: server.power_on()
            msg = "دستور پاور ارسال شد."

        elif action == 'reboot':
            await query.answer("ریستارت...")
            server.reset()
            msg = "ریستارت انجام شد."

        elif action == 'addip' and 'confirm' in data:
            await query.edit_message_text("⏳ در حال خرید و اتصال آی‌پی جدید...")
            # خرید آی‌پی شناور و اتصال به سرور
            fip = hetzner.floating_ips.create(
                type=FloatingIPType("ipv4"),
                home_location=server.datacenter.location,
                server=server
            )
            msg = f"✅ آی‌پی جدید اضافه شد:\n`{fip.floating_ip.ip}`\n\n(نکته: ممکن است نیاز به تنظیم دستی کارت شبکه در سرور داشته باشید)"
            await send_log(context, f"Added Floating IP {fip.floating_ip.ip} to {server.name}")

        elif action == 'changeip' and 'confirm' in data:
            await query.edit_message_text("♻️ در حال تعویض سرور...")
            old_name, old_loc, old_type = server.name, server.datacenter.location.name, server.server_type.name
            
            # حذف آی‌پی‌های شناور قبل از حذف سرور (برای جلوگیری از هزینه)
            floating_ips = hetzner.floating_ips.get_all()
            for fip in floating_ips:
                if fip.server and fip.server.id == server.id:
                    fip.delete()

            server.delete()
            
            new_server = hetzner.servers.create(name=old_name, server_type=ServerType(name=old_type), image=Image(name="ubuntu-22.04"), location=Location(name=old_loc))
            msg = f"✅ آی‌پی اصلی تغییر کرد.\nIP جدید: `{new_server.server.public_net.ipv4.ip}`\nPass: `{new_server.root_password}`"

        elif action == 'delete' and 'confirm' in data:
            await query.answer("حذف...")
            # حذف آی‌پی‌های شناور متصل
            floating_ips = hetzner.floating_ips.get_all()
            for fip in floating_ips:
                if fip.server and fip.server.id == server.id:
                    fip.delete()
            
            server.delete()
            await query.edit_message_text(f"✅ سرور {server.name} و آی‌پی‌های آن حذف شدند.", reply_markup=InlineKeyboardMarkup([[back_button('list_servers')]]))
            return

        await query.edit_message_text(f"{msg}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("بازگشت", callback_data=f'manage_{server_id}')]]), parse_mode='Markdown')

    except Exception as e:
        await query.edit_message_text(f"❌ خطا: {e}", reply_markup=InlineKeyboardMarkup([[back_button('list_servers')]]))

# --- 5. پروسه ساخت ---
async def create_server_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("📝 نام سرور جدید:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ لغو", callback_data='cancel_process')]]))
    return WAITING_FOR_NAME

async def create_server_finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text
    if str(update.effective_user.id) != ADMIN_ID: return ConversationHandler.END
    
    msg = await update.message.reply_text("⏳ ساخت سرور...")
    try:
        res = hetzner.servers.create(name=name, server_type=ServerType(name="cx22"), image=Image(name="ubuntu-22.04"), location=Location(name="nbg1"))
        await msg.edit_text(f"✅ انجام شد!\nIP: `{res.server.public_net.ipv4.ip}`\nPass: `{res.root_password}`", parse_mode='Markdown')
    except Exception as e:
        await msg.edit_text(f"❌ خطا: {e}")
    return ConversationHandler.END

async def cancel_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await start(update, context)
    return ConversationHandler.END

if __name__ == '__main__':
    if not BOT_TOKEN: exit()
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    conv = ConversationHandler(entry_points=[CallbackQueryHandler(create_server_start, pattern='^create_server_start$')], states={WAITING_FOR_NAME: [MessageHandler(filters.TEXT, create_server_finish)]}, fallbacks=[CallbackQueryHandler(cancel_process, pattern='^cancel_process$')])
    
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CallbackQueryHandler(start, pattern='^main_menu$'))
    app.add_handler(CallbackQueryHandler(list_servers, pattern='^list_servers$'))
    app.add_handler(CallbackQueryHandler(manage_server, pattern='^manage_'))
    app.add_handler(CallbackQueryHandler(server_actions, pattern='^action_'))
    app.add_handler(conv)
    
    app.run_polling()
