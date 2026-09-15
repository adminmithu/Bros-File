import os
import sys
import json
import logging
import re
import threading
import asyncio
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
from dotenv import load_dotenv


if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')


from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton
)
from telegram.error import TelegramError, BadRequest

from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters
)

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

load_dotenv()

# ================= RENDER HEALTH CHECK SERVER =================
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bot is running successfully!")

    def log_message(self, format, *args):
        return

def keep_alive_ping():
    import urllib.request
    time.sleep(10)
    port = int(os.getenv("PORT", 8080))
    render_url = os.getenv("RENDER_EXTERNAL_URL", f"http://127.0.0.1:{port}")
    logger.info(f"Self-ping Keep-Alive service started targeting: {render_url}")
    while True:
        try:
            time.sleep(260)  # Ping every 4.3 minutes
            urllib.request.urlopen(render_url, timeout=5)
        except Exception as e:
            logger.debug(f"Keep-alive ping status: {e}")

def start_health_check_server():
    port = int(os.getenv("PORT", 8080))
    ping_thread = threading.Thread(target=keep_alive_ping, daemon=True)
    ping_thread.start()
    try:
        server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
        logger.info(f"Health check HTTP server started on port {port}")
        server.serve_forever()
    except Exception as e:
        logger.error(f"Failed to start health check server: {e}")


# ================= CONFIGURATION & FILES =================
TOKEN = os.getenv("BOT_TOKEN", "8963161658:AAGwS2BtEcHKMle258Mk9TW1THP1DB12gYY")
ADMIN_ID = int(os.getenv("ADMIN_ID", "8929349073"))
ADMIN_GROUP_ID = int(os.getenv("ADMIN_GROUP_ID", "-1003955316409"))
NOTICE_CHANNEL = os.getenv("NOTICE_CHANNEL", "@socialworkerfile")
TUTORIAL_LINK = os.getenv("TUTORIAL_LINK", "https://t.me/socialworkerfile")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "Prime90999")

DB_FILE = "database.json"

# Conversation States
(
    CHOOSING_ACTION,
    SUBMIT_FILE,
    WITHDRAW_METHOD,
    WITHDRAW_NUMBER,
    WITHDRAW_AMOUNT,
    ADMIN_SELECT_USER,
    ADMIN_SELECT_SERVICE,
    ADMIN_INPUT_DATE,
    ADMIN_INPUT_COUNT,
    ADMIN_INPUT_PROOF,
    ADD_SERVICE_NAME,
    ADD_SERVICE_RATE,
    SET_START_TIME,
    SET_END_TIME,
    BROADCAST_MSG,
    ADMIN_SEARCH_USER,
    ADMIN_EDIT_BAL_AMOUNT,
    ADMIN_EDIT_SRV_RATE,
    ADMIN_SET_MIN_WD,
    USER_SET_SAVED_NUM,
    ADMIN_SET_NOTICE_LINK,
    ADMIN_SET_TUTORIAL_LINK,
    ADMIN_SET_SUPPORT_LINK,
    ADMIN_SET_PROOF_LINK
) = range(24)



# ================= DATABASE UTILS =================
def load_db():
    if not os.path.exists(DB_FILE):
        default_data = {
            "users": {},
            "services": {
                "facebook": {"name": "Facebook", "rate": 10.0},
                "instagram": {"name": "Instagram", "rate": 12.0}
            },
            "submissions": [],
            "withdraws": [],
            "settings": {
                "maintenance": False,
                "min_withdraw": 500.0,
                "bkash_active": True,
                "nagad_active": True,
                "start_time": "06:00",
                "end_time": "20:00"
            }
        }
        save_db(default_data)
        return default_data

    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logger.error(f"Error loading database: {e}")
        data = {}

    # Ensure required structure
    if "users" not in data:
        data["users"] = {}
    if "services" not in data:
        data["services"] = {
            "facebook": {"name": "Facebook", "rate": 10.0},
            "instagram": {"name": "Instagram", "rate": 12.0}
        }
    if "submissions" not in data:
        data["submissions"] = []
    if "withdraws" not in data:
        data["withdraws"] = []
    if "settings" not in data:
        data["settings"] = {}
    
    settings = data["settings"]
    if "start_time" not in settings:
        settings["start_time"] = "06:00"
    if "end_time" not in settings:
        settings["end_time"] = "20:00"
    if "maintenance" not in settings:
        settings["maintenance"] = False
    if "min_withdraw" not in settings:
        settings["min_withdraw"] = 500.0
    if "notice_channel" not in settings:
        settings["notice_channel"] = NOTICE_CHANNEL
    if "tutorial_link" not in settings:
        settings["tutorial_link"] = TUTORIAL_LINK
    if "admin_username" not in settings:
        settings["admin_username"] = ADMIN_USERNAME
    if "proof_link" not in settings:
        settings["proof_link"] = TUTORIAL_LINK


    save_db(data)
    return data

def save_db(data):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def is_within_work_time():
    db = load_db()
    settings = db.get("settings", {})
    start_str = settings.get("start_time", "06:00")
    end_str = settings.get("end_time", "20:00")
    
    now = datetime.now().time()
    try:
        start_time = datetime.strptime(start_str, "%H:%M").time()
        end_time = datetime.strptime(end_str, "%H:%M").time()
    except ValueError:
        return True

    if start_time <= end_time:
        return start_time <= now <= end_time
    else:
        return now >= start_time or now <= end_time

def check_maintenance(user_id, db):
    return db.get("settings", {}).get("maintenance", False) and user_id != ADMIN_ID

async def is_user_joined_channel(user_id, bot):
    if not NOTICE_CHANNEL:
        return True
    try:
        channel = NOTICE_CHANNEL if NOTICE_CHANNEL.startswith('@') else f"@{NOTICE_CHANNEL}"
        member = await bot.get_chat_member(chat_id=channel, user_id=user_id)
        if member.status in ["member", "administrator", "creator"]:
            return True
        return False
    except Exception as e:
        logger.warning(f"Channel join check warning for user {user_id}: {e}")
        return True

async def verify_channel_join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    is_joined = await is_user_joined_channel(user_id, context.bot)
    
    if is_joined:
        await query.answer("✅ ধন্যবাদ! আপনি চ্যানেলে যুক্ত আছেন।", show_alert=True)
        try:
            await query.message.edit_text("✅ আপনার চ্যানেল ভেরিফিকেশন সফল হয়েছে! এখন ফাইল সাবমিট করতে পারবেন।")
        except Exception:
            pass
        is_admin = (user_id == ADMIN_ID)
        await query.message.reply_text("প্রধান মেনু:", reply_markup=main_menu_keyboard(is_admin))
    else:
        await query.answer("⚠️ আপনি এখনো নোটিশ চ্যানেলে জয়েন করেননি! দয়া করে জয়েন করুন।", show_alert=True)
    return CHOOSING_ACTION


# ================= KEYBOARDS =================
def main_menu_keyboard(is_admin=False):
    keyboard = [
        [KeyboardButton("📁 Send File", api_kwargs={"style": "success"})],
        [KeyboardButton("👤 My Profile", api_kwargs={"style": "primary"})],
        [KeyboardButton("💳 Withdraw", api_kwargs={"style": "danger"}), KeyboardButton("ℹ️ Help & Links", api_kwargs={"style": "primary"})]
    ]
    if is_admin:
        keyboard.append([KeyboardButton("⚙️ Admin Panel", api_kwargs={"style": "primary"})])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def admin_reply_keyboard():
    db = load_db()
    s_time = db["settings"].get("start_time", "06:00")
    e_time = db["settings"].get("end_time", "20:00")
    m_status = "🔴 ON" if db["settings"].get("maintenance", False) else "🟢 OFF"
    min_wd = db["settings"].get("min_withdraw", 500.0)
    bkash_st = "🟢 ON" if db["settings"].get("bkash_active", True) else "🔴 OFF"
    nagad_st = "🟢 ON" if db["settings"].get("nagad_active", True) else "🔴 OFF"
    
    keyboard = [
        [KeyboardButton("📊 Bot Stats", api_kwargs={"style": "primary"}), KeyboardButton("👤 Manage Users", api_kwargs={"style": "primary"})],
        [KeyboardButton("📋 User File Report", api_kwargs={"style": "primary"}), KeyboardButton("🛠️ Manage Services", api_kwargs={"style": "primary"})],
        [KeyboardButton("➕ Add New Service", api_kwargs={"style": "success"}), KeyboardButton(f"💳 Min Withdraw [{min_wd:.0f}]", api_kwargs={"style": "danger"})],
        [KeyboardButton(f"📱 bKash [{bkash_st}]", api_kwargs={"style": "success"}), KeyboardButton(f"📱 Nagad [{nagad_st}]", api_kwargs={"style": "success"})],
        [KeyboardButton(f"⏰ Work Time: [{s_time} - {e_time}]", api_kwargs={"style": "primary"}), KeyboardButton(f"⚙️ Maintenance [{m_status}]", api_kwargs={"style": "danger"})],
        [KeyboardButton("📥 Pending Withdraws", api_kwargs={"style": "danger"}), KeyboardButton("🚫 Banned Users", api_kwargs={"style": "danger"})],
        [KeyboardButton("🔗 Link Settings", api_kwargs={"style": "primary"}), KeyboardButton("📁 Backup Data", api_kwargs={"style": "success"})],
        [KeyboardButton("📢 Broadcast Message", api_kwargs={"style": "primary"}), KeyboardButton("🔙 Main Menu", api_kwargs={"style": "danger"})]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def admin_panel_keyboard():
    db = load_db()
    s_time = db["settings"].get("start_time", "06:00")
    e_time = db["settings"].get("end_time", "20:00")
    m_status = "🔴 ON" if db["settings"].get("maintenance", False) else "🟢 OFF"
    min_wd = db["settings"].get("min_withdraw", 500.0)
    bkash_st = "🟢 ON" if db["settings"].get("bkash_active", True) else "🔴 OFF"
    nagad_st = "🟢 ON" if db["settings"].get("nagad_active", True) else "🔴 OFF"
    
    keyboard = [
        [
            InlineKeyboardButton("📊 Bot Stats", callback_data="adm_stats", api_kwargs={"style": "primary"}),
            InlineKeyboardButton("👤 Manage Users", callback_data="adm_manage_users", api_kwargs={"style": "primary"})
        ],
        [
            InlineKeyboardButton("📋 User File Report", callback_data="adm_report", api_kwargs={"style": "primary"}),
            InlineKeyboardButton("🛠️ Manage Services", callback_data="adm_manage_services", api_kwargs={"style": "primary"})
        ],
        [
            InlineKeyboardButton("➕ Add New Service", callback_data="adm_add_service", api_kwargs={"style": "success"}),
            InlineKeyboardButton(f"💳 Min Withdraw: ৳{min_wd:.0f}", callback_data="adm_min_wd", api_kwargs={"style": "danger"})
        ],
        [
            InlineKeyboardButton(f"📱 bKash: [{bkash_st}]", callback_data="adm_toggle_bkash", api_kwargs={"style": "success"}),
            InlineKeyboardButton(f"📱 Nagad: [{nagad_st}]", callback_data="adm_toggle_nagad", api_kwargs={"style": "success"})
        ],
        [
            InlineKeyboardButton(f"⏰ Work Time: [{s_time} - {e_time}]", callback_data="adm_work_time_menu", api_kwargs={"style": "primary"}),
            InlineKeyboardButton(f"⚙️ Maintenance Mode: [{m_status}]", callback_data="adm_maintenance", api_kwargs={"style": "danger"})
        ],
        [
            InlineKeyboardButton("📥 Pending Withdraws", callback_data="adm_pending_wd", api_kwargs={"style": "danger"}),
            InlineKeyboardButton("🚫 Banned Users", callback_data="adm_banned_list", api_kwargs={"style": "danger"})
        ],
        [
            InlineKeyboardButton("🔗 Link Settings", callback_data="adm_link_settings", api_kwargs={"style": "primary"}),
            InlineKeyboardButton("📁 Backup Data", callback_data="adm_backup_data", api_kwargs={"style": "success"})
        ],
        [
            InlineKeyboardButton("📢 Broadcast Message", callback_data="adm_broadcast", api_kwargs={"style": "primary"}),
            InlineKeyboardButton("🔙 Main Menu", callback_data="adm_main", api_kwargs={"style": "danger"})
        ]
    ]
    return InlineKeyboardMarkup(keyboard)




def cancel_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Cancel / 🔙 Main Menu", callback_data="cancel_action", api_kwargs={"style": "danger"})]
    ])


# ================= START / HOME HANDLER =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db = load_db()

    user_id_str = str(user.id)
    if user_id_str not in db["users"]:
        db["users"][user_id_str] = {
            "name": user.full_name,
            "username": user.username or "None",
            "balance": 0.0,
            "total_earned": 0.0,
            "total_withdrawn": 0.0,
            "saved_number": "Not Set",
            "banned": False,
            "ban_until": None
        }
        save_db(db)
    else:
        # Update user name & username if changed
        db["users"][user_id_str]["name"] = user.full_name
        db["users"][user_id_str]["username"] = user.username or "None"
        save_db(db)

    if db["users"][user_id_str].get("banned", False):
        await update.message.reply_text("⛔ আপনার অ্যাকাউন্টটি সাময়িকভাবে ব্যান করা হয়েছে। অ্যাডমিনের সাথে যোগাযোগ করুন।")
        return ConversationHandler.END

    if check_maintenance(user.id, db):
        await update.message.reply_text("🛠️ সিস্টেমের মেইনটেন্যান্স কাজ চলছে! কিছুক্ষণ পর চেষ্টা করুন।")
        return CHOOSING_ACTION

    is_admin = (user.id == ADMIN_ID)
    await update.message.reply_text(
        f"স্বাগতম, **{user.full_name}**!\nআপনার কাজের জন্য নিচের মেনু থেকে অপশন বেছে নিন:",
        reply_markup=main_menu_keyboard(is_admin),
        parse_mode="Markdown"
    )
    return CHOOSING_ACTION

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    is_admin = (user.id == ADMIN_ID)
    
    if update.callback_query:
        await update.callback_query.answer()
        try:
            await update.callback_query.message.edit_text("❌ অপারেশন বাতিল করা হয়েছে।")
        except Exception:
            pass
        await update.callback_query.message.reply_text(
            "প্রধান মেনু:", reply_markup=main_menu_keyboard(is_admin)
        )
    elif update.message:
        await update.message.reply_text(
            "❌ অপারেশন বাতিল করা হয়েছে।", reply_markup=main_menu_keyboard(is_admin)
        )
    return CHOOSING_ACTION


# ================= TEXT & BUTTON ROUTER =================
async def handle_menu_clicks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user = update.effective_user
    db = load_db()
    user_id_str = str(user.id)

    if text in ["🔙 Main Menu", "🔙 Back to Main Menu", "🔙 Back", "❌ Cancel", "/cancel"]:
        return await cancel(update, context)

    if db["users"].get(user_id_str, {}).get("banned", False):
        await update.message.reply_text("⛔ আপনি ব্যানকৃত ব্যবহারকারী।")
        return ConversationHandler.END

    if check_maintenance(user.id, db) and not text.startswith("⚙️ Admin Panel"):
        await update.message.reply_text("🛠️ সিস্টেমের মেইনটেন্যান্স কাজ চলছে! কিছুক্ষণ পর চেষ্টা করুন।")
        return CHOOSING_ACTION

    if text == "📁 Send File":
        # Feature 1: Mandatory Channel Join Check
        is_joined = await is_user_joined_channel(user.id, context.bot)
        if not is_joined and user.id != ADMIN_ID:
            channel_username = NOTICE_CHANNEL.replace('@', '')
            keyboard = [
                [InlineKeyboardButton("📢 Join Notice Channel", url=f"https://t.me/{channel_username}")],
                [InlineKeyboardButton("✅ Verify / I Have Joined", callback_data="verify_channel_join")],
                [InlineKeyboardButton("🔙 Main Menu", callback_data="adm_main")]
            ]
            await update.message.reply_text(
                "⚠️ **চ্যানেলে জয়েন করা বাধ্যতামূলক!**\n\n"
                "ফাইল সাবমিট করতে হলে অবশ্যই আমাদের অফিশিয়াল নোটিশ চ্যানেলে যুক্ত থাকতে হবে। জয়েন করার পর নিচের **'Verify'** বাটনে চাপ দিন।",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return CHOOSING_ACTION

        # Feature 5: Submission Cooldown Check (2 minutes = 120 sec)
        last_submit = context.user_data.get("last_submit_time", 0)
        now_ts = datetime.now().timestamp()
        cooldown_sec = 120
        time_passed = now_ts - last_submit
        
        if time_passed < cooldown_sec and user.id != ADMIN_ID:
            rem_sec = int(cooldown_sec - time_passed)
            await update.message.reply_text(
                f"⏱️ **স্প্যাম রোধন কুলডাউন!**\n\n"
                f"পরবর্তী ফাইল সাবমিট করার জন্য দয়া করে আর **{rem_sec} সেকেন্ড** অপেক্ষা করুন।",
                parse_mode="Markdown"
            )
            return CHOOSING_ACTION

        if not is_within_work_time():
            settings = db.get("settings", {})
            await update.message.reply_text(
                f"❌ দুঃখিত, বর্তমানে ফাইল জমা দেওয়ার সময় বন্ধ রয়েছে!\n"
                f"⏳ ফাইল সাবমিট করার নির্ধারিত সময়: **{settings.get('start_time')} থেকে {settings.get('end_time')}** পর্যন্ত।",
                parse_mode="Markdown"
            )
            return CHOOSING_ACTION

        services = db.get("services", {})
        if not services:
            await update.message.reply_text("⚠️ বর্তমানে কোনো সার্ভিস এভেলেবল নেই।")
            return CHOOSING_ACTION
        
        keyboard = [
            [InlineKeyboardButton(s_info["name"], callback_data=f"send_srv_{s_key}")]
            for s_key, s_info in services.items()
        ]
        keyboard.append([InlineKeyboardButton("🔙 Main Menu", callback_data="cancel_action")])
        await update.message.reply_text(
            "📂 আপনি কোন সার্ভিসের ফাইল জমা দিতে চান তা সিলেক্ট করুন:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return SUBMIT_FILE

    elif "My History" in text:
        return await show_user_history(update, context)

    elif "My Profile" in text:
        u_data = db["users"].get(user_id_str, {})
        saved_num = u_data.get("saved_number", "Not Set")
        profile_text = (
            f"👤 **USER PROFILE CARD**\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 **Name:** {u_data.get('name', user.full_name)}\n"
            f"🆔 **User ID:** `{user.id}`\n"
            f"💰 **Current Balance:** ৳{u_data.get('balance', 0.0):.2f}\n"
            f"💵 **Total Earned:** ৳{u_data.get('total_earned', 0.0):.2f}\n"
            f"💸 **Total Withdrawn:** ৳{u_data.get('total_withdrawn', 0.0):.2f}\n"
            f"📱 **Saved Payout Number:** `{saved_num}`\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📌 **Quick Actions:**"
        )
        keyboard = [
            [
                InlineKeyboardButton("✏️ Edit Saved Number", callback_data="prof_edit_num", api_kwargs={"style": "success"}),
                InlineKeyboardButton("📋 Today's Rates", callback_data="prof_today_price", api_kwargs={"style": "primary"})
            ],
            [
                InlineKeyboardButton("📜 Work & Withdraw History", callback_data="prof_history", api_kwargs={"style": "primary"})
            ]
        ]
        await update.message.reply_text(profile_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif "Withdraw" in text:
        u_data = db["users"].get(user_id_str, {})
        balance = u_data.get("balance", 0.0)
        min_wd = db["settings"].get("min_withdraw", 500.0)

        if balance < min_wd:
            await update.message.reply_text(
                f"⚠️ দুঃখিত! উইথড্র করার জন্য আপনার ব্যালেন্সে সর্বনিম্ন **৳{min_wd:.2f}** থাকতে হবে।\n"
                f"💰 আপনার বর্তমান ব্যালেন্স: **৳{balance:.2f}**",
                parse_mode="Markdown"
            )
            return CHOOSING_ACTION

        bkash_active = db["settings"].get("bkash_active", True)
        nagad_active = db["settings"].get("nagad_active", True)

        if not bkash_active and not nagad_active:
            await update.message.reply_text("⚠️ দুঃখিত! বর্তমানে সকল উইথড্রল মেথড বন্ধ রয়েছে। কিছু সময় পর চেষ্টা করুন।")
            return CHOOSING_ACTION

        row = []
        if bkash_active:
            row.append(InlineKeyboardButton("📱 bKash", callback_data="wd_method_bkash", api_kwargs={"style": "success"}))
        if nagad_active:
            row.append(InlineKeyboardButton("📱 Nagad", callback_data="wd_method_nagad", api_kwargs={"style": "success"}))

        keyboard = [row, [InlineKeyboardButton("🔙 Main Menu", callback_data="cancel_action", api_kwargs={"style": "danger"})]]
        await update.message.reply_text(
            f"💸 **WITHDRAW REQUEST**\n\n"
            f"💰 বর্তমান ব্যালেন্স: ৳{balance:.2f}\n"
            f"পেমেন্ট মেথড সিলেক্ট করুন:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return WITHDRAW_METHOD

    elif "Today's Price" in text:
        services = db.get("services", {})
        price_text = "📋 **TODAY'S SERVICE RATES**\n━━━━━━━━━━━━━━━━━━━━\n"
        for s_key, s_info in services.items():
            price_text += f"🔹 **{s_info['name']}:** ৳{s_info['rate']} প্রতি আইডি\n"
        await update.message.reply_text(price_text, parse_mode="Markdown")

    elif "Terms & Rules" in text:
        rules_text = (
            f"📜 **WORK TERMS & GUIDELINES**\n\n"
            f"১. কোনো ভুয়া বা ফেক ফাইল সাবমিট করা যাবে না।\n"
            f"২. একই ফাইল বা কাজ দ্বিতীয়বার (Double Submit) করলে অ্যাকাউন্ট স্বয়ংক্রিয়ভাবে **১ দিনের জন্য ব্যান** হয়ে যাবে।\n"
            f"৩. নির্দিষ্ট সময়ের মধ্যে ফাইল জমা দিতে হবে।\n"
            f"৪. অ্যাডমিন ফাইল যাচাই করে ব্যালেন্স যুক্ত করে দেবেন।"
        )
        await update.message.reply_text(rules_text)

    elif "Help & Links" in text or "Help & Info" in text:
        tut_link = db["settings"].get("tutorial_link", TUTORIAL_LINK)
        adm_usr = db["settings"].get("admin_username", ADMIN_USERNAME).replace("@", "")
        supp_link = f"https://t.me/{adm_usr}"
        channel_raw = db["settings"].get("notice_channel", NOTICE_CHANNEL).replace('@', '')
        notice_link = f"https://t.me/{channel_raw}"
        proof_url = db["settings"].get("proof_link", TUTORIAL_LINK)

        info_text = (
            "📌 **HELP CENTER & ESSENTIAL LINKS**\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "1️⃣ 📖 **Video Tutorial:** কিভাবে কাজ শুরু করবেন তা শিখুন।\n"
            "2️⃣ 🧾 **Payment Proofs:** আমাদের বটের লাইভ পেমেন্ট প্রুফ।\n"
            "3️⃣ 💬 **Admin Support:** সরাসরি অ্যাডমিনের সাথে চ্যাট করুন।\n"
            "4️⃣ 📢 **Notice Channel:** অফিশিয়াল আপডেট ও নোটিশ চ্যানেল।\n"
            "5️⃣ 📜 **Terms & Rules:** অ্যাকাউন্ট ব্যান এড়াতে নিয়ম পড়ুন।\n"
            "━━━━━━━━━━━━━━━━━━━━"
        )
        keyboard = [
            [InlineKeyboardButton("📖 Video Tutorial", url=tut_link, api_kwargs={"style": "primary"}), InlineKeyboardButton("🧾 Payment Proofs", url=proof_url, api_kwargs={"style": "success"})],
            [InlineKeyboardButton("💬 Admin Support", url=supp_link, api_kwargs={"style": "primary"}), InlineKeyboardButton("📢 Notice Channel", url=notice_link, api_kwargs={"style": "primary"})],
            [InlineKeyboardButton("📜 Terms & Rules", callback_data="user_rules", api_kwargs={"style": "primary"})]
        ]
        await update.message.reply_text(info_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif text == "📱 Saved Number":
        u_data = db["users"].get(user_id_str, {})
        saved_num = u_data.get("saved_number", "Not Set")
        msg_text = (
            f"📱 **SAVED WITHDRAWAL NUMBER**\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📌 বর্তমান সেভকৃত নম্বর: `{saved_num}`\n\n"
            f"বিকাশ বা নগদে টাকা তোলার সময় এই নম্বরটি ১-ক্লিকেই ব্যবহার করতে পারবেন।\n"
            f"নতুন নম্বর সেট বা আপডেট করতে নিচে আপনার **১১ ডিজিটের মোবাইল নম্বর** লিখুন:"
        )
        await update.message.reply_text(msg_text, reply_markup=cancel_keyboard(), parse_mode="Markdown")
        return USER_SET_SAVED_NUM

    elif text == "📖 Video Tutorial":
        tut_link = db["settings"].get("tutorial_link", TUTORIAL_LINK)
        keyboard = [[InlineKeyboardButton("📺 Watch Tutorial / Join Channel", url=tut_link)]]
        await update.message.reply_text("📖 কাজের নিয়ম শিখতে এবং লাইভ আপডেট পেতে নিচের চ্যানেলে জয়েন করুন:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif text == "💬 Admin Support":
        adm_usr = db["settings"].get("admin_username", ADMIN_USERNAME).replace("@", "")
        keyboard = [[InlineKeyboardButton("👤 💬 Contact Admin", url=f"https://t.me/{adm_usr}")]]
        await update.message.reply_text("💬 যেকোনো সমস্যায় সরাসরি অ্যাডমিনের ইনবক্সে যোগাযোগ করুন:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif text == "📢 Notice Channel":
        channel_raw = db["settings"].get("notice_channel", NOTICE_CHANNEL)
        channel_username = channel_raw.replace('@', '')
        keyboard = [[InlineKeyboardButton("📢 Join Notice Channel", url=f"https://t.me/{channel_username}")]]
        await update.message.reply_text("📢 অফিশিয়াল নোটিশ ও পিন মেসেজ দেখতে আমাদের চ্যানেলে যুক্ত থাকুন:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif text == "🧾 Payment Proofs":
        proof_url = db["settings"].get("proof_link", TUTORIAL_LINK)
        keyboard = [[InlineKeyboardButton("🧾 View Payment Proofs", url=proof_url)]]
        await update.message.reply_text("🧾 আমাদের সকল সফল পেমেন্টের প্রুফ দেখতে নিচের বাটনে ক্লিক করুন:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif text.startswith("🚫 Banned Users") and user.id == ADMIN_ID:
        return await show_banned_users_list(update, context)

    elif text.startswith("🔗 Link Settings") and user.id == ADMIN_ID:
        return await show_link_settings(update, context)

    elif text.startswith("📁 Backup Data") and user.id == ADMIN_ID:
        return await send_database_backup(update, context)


    elif ("Admin Panel" in text or text == "/admin") and user.id == ADMIN_ID:
        await update.message.reply_text("⚙️ **ADMIN CONTROL PANEL**", reply_markup=admin_reply_keyboard(), parse_mode="Markdown")
        await update.message.reply_text("ইনলাইন মেনু বিকল্প:", reply_markup=admin_panel_keyboard())

    elif text.startswith("📱 bKash") and user.id == ADMIN_ID:
        db["settings"]["bkash_active"] = not db["settings"].get("bkash_active", True)
        save_db(db)
        st = "🟢 ON" if db["settings"]["bkash_active"] else "🔴 OFF"
        await update.message.reply_text(f"📱 bKash Payment Method is now **{st}**", reply_markup=admin_reply_keyboard(), parse_mode="Markdown")
        return CHOOSING_ACTION

    elif text.startswith("📱 Nagad") and user.id == ADMIN_ID:
        db["settings"]["nagad_active"] = not db["settings"].get("nagad_active", True)
        save_db(db)
        st = "🟢 ON" if db["settings"]["nagad_active"] else "🔴 OFF"
        await update.message.reply_text(f"📱 Nagad Payment Method is now **{st}**", reply_markup=admin_reply_keyboard(), parse_mode="Markdown")
        return CHOOSING_ACTION

    elif text.startswith("📊 Bot Stats") and user.id == ADMIN_ID:

        return await show_bot_stats(update, context)

    elif text.startswith("👤 Manage Users") and user.id == ADMIN_ID:
        return await show_user_manager(update, context)

    elif text.startswith("🛠️ Manage Services") and user.id == ADMIN_ID:
        return await show_service_manager(update, context)

    elif text.startswith("💳 Min Withdraw") and user.id == ADMIN_ID:
        return await show_min_withdraw_setting(update, context)

    elif text.startswith("📥 Pending Withdraws") and user.id == ADMIN_ID:
        return await show_pending_withdraws(update, context)

    elif text.startswith("📋 User File Report") and user.id == ADMIN_ID:
        users = db.get("users", {})
        if not users:
            await update.message.reply_text("⚠️ কোনো রেজিস্টার্ড ইউজার নেই!", reply_markup=admin_reply_keyboard())
            return CHOOSING_ACTION
        
        keyboard = [
            [InlineKeyboardButton(f"👤 {u_info.get('name', u_id)} ({u_id})", callback_data=f"rep_usr_{u_id}")]
            for u_id, u_info in users.items()
        ]
        keyboard.append([InlineKeyboardButton("🔙 Main Menu", callback_data="adm_main")])
        await update.message.reply_text("📋 যার রিপোর্ট জমা দিতে চান সেই ইউজার সিলেক্ট করুন:", reply_markup=InlineKeyboardMarkup(keyboard))
        return ADMIN_SELECT_USER


    elif text.startswith("➕ Add New Service") and user.id == ADMIN_ID:
        await update.message.reply_text(
            "➕ নতুন সার্ভিসের নাম লিখুন (যেমন: Telegram, TikTok):",
            reply_markup=cancel_keyboard()
        )
        return ADD_SERVICE_NAME

    elif text.startswith("⏰ Work Time") and user.id == ADMIN_ID:
        return await show_work_time_menu(update, context)

    elif text.startswith("⚙️ Maintenance") and user.id == ADMIN_ID:
        db["settings"]["maintenance"] = not db["settings"]["maintenance"]
        save_db(db)
        status = "🔴 ON" if db["settings"]["maintenance"] else "🟢 OFF"
        await update.message.reply_text(
            f"⚙️ Maintenance Mode is now **{status}**",
            reply_markup=admin_reply_keyboard(),
            parse_mode="Markdown"
        )
        return CHOOSING_ACTION

    elif text.startswith("📢 Broadcast Message") and user.id == ADMIN_ID:
        await update.message.reply_text(
            "📢 **BROADCAST MESSAGE**\n\n"
            "সব ইউজারদের উদ্দেশ্যে পাঠানোর জন্য কোনো টেক্সট বা ছবি পাঠান:",
            parse_mode="Markdown",
            reply_markup=cancel_keyboard()
        )
        return BROADCAST_MSG

    return CHOOSING_ACTION


# ================= FILE SUBMISSION HANDLER =================
async def select_service_for_submission(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "cancel_action":
        return await cancel(update, context)

    if query.data.startswith("send_srv_"):
        srv_key = query.data.replace("send_srv_", "")
        context.user_data["selected_service"] = srv_key
        await query.message.edit_text(
            f"✅ আপনি **{srv_key.upper()}** সিলেক্ট করেছেন।\n\n"
            f"📥 এখন আপনার ফাইল (Document) অথবা গুগল শিট লিংক পাঠান:",
            parse_mode="Markdown",
            reply_markup=cancel_keyboard()
        )
        return SUBMIT_FILE

async def receive_user_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ Cancel":
        return await cancel(update, context)

    if not is_within_work_time():
        await update.message.reply_text("❌ কাজের সময় শেষ হয়ে গেছে! ফাইল গ্রহণ করা সম্ভব নয়।")
        return CHOOSING_ACTION

    user = update.effective_user
    srv_key = context.user_data.get("selected_service", "general")
    db = load_db()
    srv_info = db.get("services", {}).get(srv_key, {})
    srv_rate = srv_info.get("rate", 0.0)
    
    forward_text = (
        f"💎 **PREMIUM WORK SUBMISSION**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 **Worker Name:** {user.full_name}\n"
        f"🆔 **Telegram ID:** `{user.id}`\n"
        f"📂 **Service Type:** `{srv_key.upper()}`\n"
        f"💰 **Service Rate:** `৳{srv_rate:.2f} / ID`\n"
        f"📅 **Submitted At:** `{datetime.now().strftime('%d %b %Y | %I:%M %p')}`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━"
    )
    
    rcv_markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⚡ ✅ ACCEPT & PAY", callback_data=f"rcv_done_{user.id}", api_kwargs={"style": "success"}),
            InlineKeyboardButton("⚠️ 📝 REPORT ISSUE", callback_data=f"quick_rep_{user.id}", api_kwargs={"style": "danger"})
        ]
    ])
    
    file_caption = update.message.caption or ""
    file_text = update.message.text or ""

    try:
        if update.message.document:
            await context.bot.send_document(
                chat_id=ADMIN_GROUP_ID,
                document=update.message.document.file_id,
                caption=f"{forward_text}\n\n📄 **Submission Details:**\n{file_caption}",
                reply_markup=rcv_markup,
                parse_mode="Markdown"
            )
        else:
            await context.bot.send_message(
                chat_id=ADMIN_GROUP_ID,
                text=f"{forward_text}\n\n🔗 **Submission Content:**\n{file_text or file_caption}",
                reply_markup=rcv_markup,
                parse_mode="Markdown"
            )
        await update.message.reply_text("✅ আপনার ফাইল বা লিংক সফলভাবে অ্যাডমিন গ্রুপে পাঠানো হয়েছে! যাচাই করার পর ব্যালেন্স আপডেট করা হবে।")
    except Exception as e:
        logger.error(f"Failed to forward user file to admin group: {e}")
        await update.message.reply_text("⚠️ ফাইল পাঠাতে সমস্যা হয়েছে। অ্যাডমিন গ্রুপের সেটআপ যাচাই করুন।")

    return CHOOSING_ACTION

async def select_withdraw_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "cancel_action":
        return await cancel(update, context)

    if query.data.startswith("wd_method_"):
        method = query.data.replace("wd_method_", "").capitalize()
        context.user_data["withdraw_method"] = method
        
        db = load_db()
        u_id_str = str(query.from_user.id)
        saved_num = db.get("users", {}).get(u_id_str, {}).get("saved_number", "Not Set")

        if saved_num and saved_num != "Not Set" and len(saved_num) >= 11 and saved_num.isdigit():
            keyboard = [
                [InlineKeyboardButton(f"📞 Use Saved: {saved_num}", callback_data="wd_use_saved")],
                [InlineKeyboardButton("✍️ Type New Number", callback_data="wd_type_new")],
                [InlineKeyboardButton("🔙 Main Menu", callback_data="cancel_action")]
            ]
            await query.message.edit_text(
                f"📱 আপনি **{method}** সিলেক্ট করেছেন।\n\n"
                f"আপনার সেভকৃত নম্বর **`{saved_num}`** ব্যবহার করতে নিচের বাটন চাপুন অথবা নতুন নম্বর লিখুন:",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return WITHDRAW_NUMBER
        else:
            await query.message.edit_text(
                f"📱 আপনি **{method}** সিলেক্ট করেছেন।\n\nআপনার {method} পারসোনাল নাম্বারটি লিখুন:",
                parse_mode="Markdown",
                reply_markup=cancel_keyboard()
            )
            return WITHDRAW_NUMBER

async def handle_withdraw_number_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "wd_use_saved":
        db = load_db()
        u_id_str = str(query.from_user.id)
        saved_num = db.get("users", {}).get(u_id_str, {}).get("saved_number", "")
        context.user_data["withdraw_number"] = saved_num
        balance = db["users"][u_id_str]["balance"]
        min_wd = db["settings"].get("min_withdraw", 500.0)

        await query.message.edit_text(
            f"✅ সেভকৃত নম্বর **`{saved_num}`** ব্যবহার করা হচ্ছে।\n\n"
            f"💵 কত টাকা উইথড্র করতে চান? (সংখ্যায় লিখুন)\n"
            f"💰 আপনার বর্তমান ব্যালেন্স: ৳{balance:.2f}\n"
            f"🔻 সর্বনিম্ন উইথড্র: ৳{min_wd:.2f}",
            parse_mode="Markdown",
            reply_markup=cancel_keyboard()
        )
        return WITHDRAW_AMOUNT

    elif query.data == "wd_type_new":
        method = context.user_data.get("withdraw_method", "Bkash")
        await query.message.edit_text(
            f"📱 আপনার **{method}** পারসোনাল নাম্বারটি লিখুন:",
            parse_mode="Markdown",
            reply_markup=cancel_keyboard()
        )
        return WITHDRAW_NUMBER

async def save_user_saved_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.text in ["❌ Cancel", "🔙 Main Menu", "🔙 Back to Main Menu", "🔙 Back", "/cancel"]:
        return await cancel(update, context)

    number = update.message.text.strip()
    if len(number) < 11 or not number.isdigit():
        await update.message.reply_text("⚠️ দয়া করে সঠিক ১১ ডিজিটের মোবাইল নম্বর লিখুন (যেমন: 01712345678):")
        return USER_SET_SAVED_NUM

    db = load_db()
    u_id_str = str(update.effective_user.id)
    if u_id_str in db["users"]:
        db["users"][u_id_str]["saved_number"] = number
        save_db(db)

    is_admin = (update.effective_user.id == ADMIN_ID)
    await update.message.reply_text(
        f"✅ আপনার পেমেন্ট নম্বর **`{number}`** সফলভাবে সেভ করা হয়েছে!\n"
        f"এখন থেকে উইথড্রল করার সময় ১-ক্লিকেই এই নম্বর ব্যবহার করতে পারবেন।",
        reply_markup=main_menu_keyboard(is_admin),
        parse_mode="Markdown"
    )
    return CHOOSING_ACTION


async def receive_withdraw_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ Cancel":
        return await cancel(update, context)

    number = update.message.text.strip()
    if len(number) < 11 or not number.isdigit():
        await update.message.reply_text("⚠️ দয়া করে সঠিক ১১ ডিজিটের মোবাইল নাম্বার লিখুন:")
        return WITHDRAW_NUMBER

    context.user_data["withdraw_number"] = number
    user_id_str = str(update.effective_user.id)
    
    # Save default number for user
    db = load_db()
    if user_id_str in db["users"]:
        db["users"][user_id_str]["saved_number"] = number
        save_db(db)

    balance = db["users"][user_id_str]["balance"]
    min_wd = db["settings"].get("min_withdraw", 500.0)

    await update.message.reply_text(
        f"💵 কত টাকা উইথড্র করতে চান? (সংখ্যায় লিখুন)\n"
        f"💰 আপনার বর্তমান ব্যালেন্স: ৳{balance:.2f}\n"
        f"🔻 সর্বনিম্ন উইথড্র: ৳{min_wd:.2f}",
        reply_markup=cancel_keyboard()
    )
    return WITHDRAW_AMOUNT

async def receive_withdraw_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ Cancel":
        return await cancel(update, context)

    try:
        amount = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("⚠️ দয়া করে সঠিক সংখ্যায় পরিমাণ লিখুন (যেমন: 250):")
        return WITHDRAW_AMOUNT

    user = update.effective_user
    user_id_str = str(user.id)
    db = load_db()

    balance = db["users"][user_id_str]["balance"]
    min_wd = db["settings"].get("min_withdraw", 500.0)

    if amount < min_wd:
        await update.message.reply_text(f"⚠️ সর্বনিম্ন উইথড্র পরিমাণ ৳{min_wd:.2f}")
        return WITHDRAW_AMOUNT

    if amount > balance:
        await update.message.reply_text(f"⚠️ আপনার ব্যালেন্সে পর্যাপ্ত টাকা নেই! বর্তমান ব্যালেন্স: ৳{balance:.2f}")
        return WITHDRAW_AMOUNT

    # Deduct balance temporarily & add pending request
    db["users"][user_id_str]["balance"] -= amount
    method = context.user_data.get("withdraw_method", "Bkash")
    number = context.user_data.get("withdraw_number", "")

    req_id = len(db["withdraws"]) + 1
    db["withdraws"].append({
        "id": req_id,
        "user_id": user.id,
        "user_name": user.full_name,
        "method": method,
        "number": number,
        "amount": amount,
        "status": "Pending",
        "date": datetime.now().strftime('%d-%m-%Y %I:%M %p')
    })
    save_db(db)

    # Notify Admin Group
    admin_wd_text = (
        f"👑 **PREMIUM PAYOUT REQUEST**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 **Payout ID:** `#{req_id}`\n"
        f"👤 **Account Holder:** {user.full_name}\n"
        f"🆔 **Telegram ID:** `{user.id}`\n"
        f"📱 **Payout Network:** `{method.upper()}`\n"
        f"📞 **Account Number:** `{number}`\n"
        f"💰 **Cash Amount:** `৳{amount:.2f}`\n"
        f"⏰ **Requested At:** `{datetime.now().strftime('%d %b %Y | %I:%M %p')}`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━"
    )
    admin_markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💸 ✅ APPROVE PAYOUT", callback_data=f"wd_approve_{user.id}_{amount}_{req_id}", api_kwargs={"style": "success"}),
            InlineKeyboardButton("❌ REJECT & REFUND", callback_data=f"wd_reject_{user.id}_{amount}_{req_id}", api_kwargs={"style": "danger"})
        ]
    ])

    try:
        await context.bot.send_message(
            chat_id=ADMIN_GROUP_ID,
            text=admin_wd_text,
            reply_markup=admin_markup,
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Failed to send withdraw request to admin group: {e}")

    await update.message.reply_text(
        f"✅ আপনার **৳{amount:.2f}** উইথড্র রিকোয়েস্ট সফলভাবে জমা নেওয়া হয়েছে!\n"
        f"অ্যাডমিন শীঘ্রই তা প্রসেস করবেন।",
        reply_markup=main_menu_keyboard(user.id == ADMIN_ID)
    )
    return CHOOSING_ACTION

# ================= WORK TIME INTERACTIVE PICKER =================
async def show_work_time_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = load_db()
    s_time = db["settings"].get("start_time", "06:00")
    e_time = db["settings"].get("end_time", "20:00")
    
    msg_text = (
        f"⏰ **WORK TIME SETTINGS**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📍 **বর্তমান কাজের সময়:** `{s_time}` থেকে `{e_time}` পর্যন্ত\n\n"
        f"ঘড়ির মতো ইন্টারঅ্যাক্টিভ বাটন দিয়ে অথবা ম্যানুয়ালি সময় পরিবর্তন করতে নিচের অপশন নির্বাচন করুন:"
    )
    
    keyboard = [
        [InlineKeyboardButton("🕐 ঘড়ির মতো সময় পরিবর্তন করুন (Interactive)", callback_data="wt_picker_start")],
        [InlineKeyboardButton("⌨️ টাইপ করে সময় লিখুন (Manual Input)", callback_data="adm_set_time")],
        [InlineKeyboardButton("🔙 Main Menu", callback_data="adm_main")]
    ]
    markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.edit_text(msg_text, reply_markup=markup, parse_mode="Markdown")
    elif update.message:
        await update.message.reply_text(msg_text, reply_markup=markup, parse_mode="Markdown")
    return CHOOSING_ACTION

def format_time_24(hr, min_str, period):
    h = int(hr)
    if period == "PM" and h < 12:
        h += 12
    elif period == "AM" and h == 12:
        h = 0
    return f"{h:02d}:{min_str}"

def render_clock_picker(stage, hr, min_str, period):
    time_24 = format_time_24(hr, min_str, period)
    stage_title = "🌅 **কাজের শুরু সময় (Start Time)**" if stage == "start" else "🌆 **কাজের শেষ সময় (End Time)**"
    
    msg_text = (
        f"{stage_title} নির্ধারণ করুন:\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 নির্বাচিত সময়: **{hr}:{min_str} {period}** (`{time_24}`)\n\n"
        f"ঘণ্টা (1-12), AM/PM এবং মিনিট পছন্দ করতে বাটন চাপুন:"
    )

    keyboard = []
    # Row 1: Hours 1-4
    h_row1 = []
    for h in range(1, 5):
        h_str = f"{h:02d}"
        label = f"[{h_str} ✅]" if h_str == hr else h_str
        h_row1.append(InlineKeyboardButton(label, callback_data=f"wt_{stage}_hr_{h_str}"))
    keyboard.append(h_row1)

    # Row 2: Hours 5-8
    h_row2 = []
    for h in range(5, 9):
        h_str = f"{h:02d}"
        label = f"[{h_str} ✅]" if h_str == hr else h_str
        h_row2.append(InlineKeyboardButton(label, callback_data=f"wt_{stage}_hr_{h_str}"))
    keyboard.append(h_row2)

    # Row 3: Hours 9-12
    h_row3 = []
    for h in range(9, 13):
        h_str = f"{h:02d}"
        label = f"[{h_str} ✅]" if h_str == hr else h_str
        h_row3.append(InlineKeyboardButton(label, callback_data=f"wt_{stage}_hr_{h_str}"))
    keyboard.append(h_row3)

    # Row 4: AM / PM
    am_label = "☀️ AM ✅" if period == "AM" else "☀️ AM"
    pm_label = "🌙 PM ✅" if period == "PM" else "🌙 PM"
    keyboard.append([
        InlineKeyboardButton(am_label, callback_data=f"wt_{stage}_period_AM"),
        InlineKeyboardButton(pm_label, callback_data=f"wt_{stage}_period_PM")
    ])

    # Row 5: Minutes (:00 / :30)
    m00_label = ":00 ✅" if min_str == "00" else ":00"
    m30_label = ":30 ✅" if min_str == "30" else ":30"
    keyboard.append([
        InlineKeyboardButton(m00_label, callback_data=f"wt_{stage}_min_00"),
        InlineKeyboardButton(m30_label, callback_data=f"wt_{stage}_min_30")
    ])

    # Row 6 & 7: Navigation
    if stage == "start":
        keyboard.append([InlineKeyboardButton("➡️ Next: End Time সেট করুন", callback_data="wt_goto_end")])
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="adm_work_time_menu")])
    else:
        keyboard.append([InlineKeyboardButton("✅ Confirm & Save Work Time", callback_data="wt_save_all")])
        keyboard.append([InlineKeyboardButton("⬅️ Back to Start Time", callback_data="wt_goto_start")])
        keyboard.append([InlineKeyboardButton("🔙 Main Menu", callback_data="adm_main")])

    return msg_text, InlineKeyboardMarkup(keyboard)

async def admin_wt_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data in ["wt_picker_start", "wt_goto_start"]:
        context.user_data.setdefault("wt_start_hr", "06")
        context.user_data.setdefault("wt_start_min", "00")
        context.user_data.setdefault("wt_start_period", "AM")
        msg_text, markup = render_clock_picker(
            "start",
            context.user_data["wt_start_hr"],
            context.user_data["wt_start_min"],
            context.user_data["wt_start_period"]
        )
        await query.message.edit_text(msg_text, reply_markup=markup, parse_mode="Markdown")
        return CHOOSING_ACTION

    elif data.startswith("wt_start_hr_"):
        hr = data.replace("wt_start_hr_", "")
        context.user_data["wt_start_hr"] = hr
        msg_text, markup = render_clock_picker(
            "start",
            hr,
            context.user_data.get("wt_start_min", "00"),
            context.user_data.get("wt_start_period", "AM")
        )
        await query.message.edit_text(msg_text, reply_markup=markup, parse_mode="Markdown")
        return CHOOSING_ACTION

    elif data.startswith("wt_start_period_"):
        period = data.replace("wt_start_period_", "")
        context.user_data["wt_start_period"] = period
        msg_text, markup = render_clock_picker(
            "start",
            context.user_data.get("wt_start_hr", "06"),
            context.user_data.get("wt_start_min", "00"),
            period
        )
        await query.message.edit_text(msg_text, reply_markup=markup, parse_mode="Markdown")
        return CHOOSING_ACTION

    elif data.startswith("wt_start_min_"):
        m_str = data.replace("wt_start_min_", "")
        context.user_data["wt_start_min"] = m_str
        msg_text, markup = render_clock_picker(
            "start",
            context.user_data.get("wt_start_hr", "06"),
            m_str,
            context.user_data.get("wt_start_period", "AM")
        )
        await query.message.edit_text(msg_text, reply_markup=markup, parse_mode="Markdown")
        return CHOOSING_ACTION

    elif data == "wt_goto_end":
        context.user_data.setdefault("wt_end_hr", "08")
        context.user_data.setdefault("wt_end_min", "00")
        context.user_data.setdefault("wt_end_period", "PM")
        msg_text, markup = render_clock_picker(
            "end",
            context.user_data["wt_end_hr"],
            context.user_data["wt_end_min"],
            context.user_data["wt_end_period"]
        )
        await query.message.edit_text(msg_text, reply_markup=markup, parse_mode="Markdown")
        return CHOOSING_ACTION

    elif data.startswith("wt_end_hr_"):
        hr = data.replace("wt_end_hr_", "")
        context.user_data["wt_end_hr"] = hr
        msg_text, markup = render_clock_picker(
            "end",
            hr,
            context.user_data.get("wt_end_min", "00"),
            context.user_data.get("wt_end_period", "PM")
        )
        await query.message.edit_text(msg_text, reply_markup=markup, parse_mode="Markdown")
        return CHOOSING_ACTION

    elif data.startswith("wt_end_period_"):
        period = data.replace("wt_end_period_", "")
        context.user_data["wt_end_period"] = period
        msg_text, markup = render_clock_picker(
            "end",
            context.user_data.get("wt_end_hr", "08"),
            context.user_data.get("wt_end_min", "00"),
            period
        )
        await query.message.edit_text(msg_text, reply_markup=markup, parse_mode="Markdown")
        return CHOOSING_ACTION

    elif data.startswith("wt_end_min_"):
        m_str = data.replace("wt_end_min_", "")
        context.user_data["wt_end_min"] = m_str
        msg_text, markup = render_clock_picker(
            "end",
            context.user_data.get("wt_end_hr", "08"),
            m_str,
            context.user_data.get("wt_end_period", "PM")
        )
        await query.message.edit_text(msg_text, reply_markup=markup, parse_mode="Markdown")
        return CHOOSING_ACTION

    elif data == "wt_save_all":
        s_hr = context.user_data.get("wt_start_hr", "06")
        s_min = context.user_data.get("wt_start_min", "00")
        s_period = context.user_data.get("wt_start_period", "AM")

        e_hr = context.user_data.get("wt_end_hr", "08")
        e_min = context.user_data.get("wt_end_min", "00")
        e_period = context.user_data.get("wt_end_period", "PM")

        start_24 = format_time_24(s_hr, s_min, s_period)
        end_24 = format_time_24(e_hr, e_min, e_period)

        db = load_db()
        db["settings"]["start_time"] = start_24
        db["settings"]["end_time"] = end_24
        save_db(db)

        await query.message.edit_text(
            f"✅ **কাজের সময় সফলভাবে আপডেট হয়েছে!**\n\n"
            f"🌅 **শুরু:** {s_hr}:{s_min} {s_period} (`{start_24}`)\n"
            f"<ctrl42> **শেষ:** {e_hr}:{e_min} {e_period} (`{end_24}`)",
            parse_mode="Markdown"
        )
        is_admin = (query.from_user.id == ADMIN_ID)
        await query.message.reply_text(
            "অ্যাডমিন প্যানেল:",
            reply_markup=admin_reply_keyboard() if is_admin else main_menu_keyboard()
        )
        return CHOOSING_ACTION

# ================= ADMIN CONTROL PANEL HANDLERS =================
async def admin_panel_clicks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    db = load_db()

    if query.data == "adm_main":
        await query.message.edit_text("মূল মেনুতে ফিরে গেছেন।")
        is_admin = (query.from_user.id == ADMIN_ID)
        await query.message.reply_text("প্রধান মেনু:", reply_markup=main_menu_keyboard(is_admin))
        return CHOOSING_ACTION

    elif query.data == "adm_toggle_bkash":
        db["settings"]["bkash_active"] = not db["settings"].get("bkash_active", True)
        save_db(db)
        st = "🟢 ON" if db["settings"]["bkash_active"] else "🔴 OFF"
        await query.message.edit_text(f"📱 bKash Payment Method is now **{st}**", reply_markup=admin_panel_keyboard(), parse_mode="Markdown")
        return CHOOSING_ACTION

    elif query.data == "adm_toggle_nagad":
        db["settings"]["nagad_active"] = not db["settings"].get("nagad_active", True)
        save_db(db)
        st = "🟢 ON" if db["settings"].get("nagad_active", True) else "🔴 OFF"
        await query.message.edit_text(f"📱 Nagad Payment Method is now **{st}**", reply_markup=admin_panel_keyboard(), parse_mode="Markdown")
        return CHOOSING_ACTION

    elif query.data == "adm_banned_list":
        return await show_banned_users_list(update, context)

    elif query.data == "adm_link_settings":
        return await show_link_settings(update, context)

    elif query.data == "adm_backup_data":
        return await send_database_backup(update, context)

    elif query.data == "adm_stats":


        return await show_bot_stats(update, context)

    elif query.data == "adm_manage_users":
        return await show_user_manager(update, context)

    elif query.data == "adm_manage_services":
        return await show_service_manager(update, context)

    elif query.data == "adm_min_wd":
        return await show_min_withdraw_setting(update, context)

    elif query.data == "adm_pending_wd":
        return await show_pending_withdraws(update, context)

    elif query.data in ["adm_set_time", "adm_work_time_menu"]:
        return await show_work_time_menu(update, context)

    elif query.data == "adm_maintenance":
        db["settings"]["maintenance"] = not db["settings"]["maintenance"]
        save_db(db)
        status = "🔴 ON" if db["settings"]["maintenance"] else "🟢 OFF"
        await query.message.edit_text(f"⚙️ Maintenance Mode is now **{status}**", reply_markup=admin_panel_keyboard(), parse_mode="Markdown")
        return CHOOSING_ACTION

    elif query.data == "adm_add_service":
        await query.message.edit_text(
            "➕ নতুন সার্ভিসের নাম লিখুন (যেমন: Telegram, TikTok):",
            reply_markup=cancel_keyboard()
        )
        return ADD_SERVICE_NAME

    elif query.data == "adm_broadcast":
        await query.message.edit_text(
            "📢 **BROADCAST MESSAGE**\n\n"
            "সব ইউজারদের উদ্দেশ্যে পাঠানোর জন্য কোনো টেক্সট বা ছবি পাঠান:",
            parse_mode="Markdown",
            reply_markup=cancel_keyboard()
        )
        return BROADCAST_MSG

    elif query.data == "adm_report":
        users = db.get("users", {})
        if not users:
            await query.message.edit_text("⚠️ কোনো রেজিস্টার্ড ইউজার নেই!", reply_markup=admin_panel_keyboard())
            return CHOOSING_ACTION
        
        keyboard = [
            [InlineKeyboardButton(f"👤 {u_info.get('name', u_id)} ({u_id})", callback_data=f"rep_usr_{u_id}")]
            for u_id, u_info in users.items()
        ]
        keyboard.append([InlineKeyboardButton("🔙 Main Menu", callback_data="adm_main")])
        await query.message.edit_text("📋 যার রিপোর্ট জমা দিতে চান সেই ইউজার সিলেক্ট করুন:", reply_markup=InlineKeyboardMarkup(keyboard))
        return ADMIN_SELECT_USER


# ================= USER HISTORY HANDLER =================
async def show_user_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db = load_db()
    u_id_str = str(user.id)
    u_data = db.get("users", {}).get(u_id_str, {})

    withdraws = [w for w in db.get("withdraws", []) if str(w.get("user_id")) == u_id_str]
    submissions = [s for s in db.get("submissions", []) if str(s.get("user_id")) == u_id_str]

    msg_text = (
        f"📜 **YOUR WORK & WITHDRAWAL HISTORY**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 **Name:** {u_data.get('name', user.full_name)}\n"
        f"📁 **Total Submitted Files:** {len(submissions)} টি\n"
        f"💰 **Current Balance:** ৳{u_data.get('balance', 0.0):.2f}\n"
        f"💵 **Total Earned:** ৳{u_data.get('total_earned', 0.0):.2f}\n"
        f"💸 **Total Withdrawn:** ৳{u_data.get('total_withdrawn', 0.0):.2f}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📋 **RECENT WITHDRAWALS:**\n"
    )

    if not withdraws:
        msg_text += "• কোনো উইথড্রল হিস্ট্রি পাওয়া যায়নি।\n"
    else:
        for wd in reversed(withdraws[-5:]):
            status_icon = "✅" if wd.get("status") == "Approved" else ("❌" if wd.get("status") == "Rejected" else "⏳")
            msg_text += f"• #{wd.get('id')} | ৳{wd.get('amount', 0.0):.2f} ({wd.get('method')}) - {status_icon} {wd.get('status')}\n"

    await update.message.reply_text(msg_text, parse_mode="Markdown")
    return CHOOSING_ACTION


# ================= FEATURE 1: BOT STATS =================

async def show_bot_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = load_db()
    users = db.get("users", {})
    services = db.get("services", {})
    submissions = db.get("submissions", [])
    withdraws = db.get("withdraws", [])

    total_users = len(users)
    active_users = sum(1 for u in users.values() if not u.get("banned", False))
    banned_users = sum(1 for u in users.values() if u.get("banned", False))
    
    total_balance = sum(u.get("balance", 0.0) for u in users.values())
    total_earned = sum(u.get("total_earned", 0.0) for u in users.values())
    total_withdrawn = sum(u.get("total_withdrawn", 0.0) for u in users.values())

    pending_wd = [w for w in withdraws if w.get("status") == "Pending"]
    pending_count = len(pending_wd)
    pending_amount = sum(w.get("amount", 0.0) for w in pending_wd)

    stats_text = (
        f"📊 **BOT OVERALL STATISTICS**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 **মোট ইউজার:** Total {total_users} (Active: {active_users}, Banned: {banned_users})\n"
        f"💰 **ইউজার মোট ব্যালেন্স:** ৳{total_balance:.2f}\n"
        f"💵 **মোট অর্জিত ইনকাম:** ৳{total_earned:.2f}\n"
        f"💸 **মোট উইথড্র (Paid Out):** ৳{total_withdrawn:.2f}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📥 **পেন্ডিং উইথড্র:** {pending_count} টি (মোট ৳{pending_amount:.2f})\n"
        f"📁 **মোট সাবমিটেড ফাইল:** {len(submissions)} টি\n"
        f"🛠️ **এক্টিভ সার্ভিস:** {len(services)} টি\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )
    keyboard = [[InlineKeyboardButton("🔙 Main Menu", callback_data="adm_main")]]
    markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.edit_text(stats_text, reply_markup=markup, parse_mode="Markdown")
    elif update.message:
        await update.message.reply_text(stats_text, reply_markup=markup, parse_mode="Markdown")
    return CHOOSING_ACTION


# ================= FEATURE 2: USER MANAGER & SEARCH =================
async def show_user_manager(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = load_db()
    users = db.get("users", {})
    
    msg_text = (
        f"👤 **USER MANAGEMENT HUB**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"বটে নিবন্ধিত মোট ইউজার: **{len(users)}** জন\n\n"
        f"নির্দিষ্ট ইউজার সার্চ করতে অথবা তালিকা দেখতে নিচের অপশন বেছে নিন:"
    )
    
    keyboard = [
        [InlineKeyboardButton("🔍 User Search (by ID / Username)", callback_data="usr_search_prompt")],
        [InlineKeyboardButton("📋 Registered Users List", callback_data="adm_report")],
        [InlineKeyboardButton("🔙 Main Menu", callback_data="adm_main")]
    ]
    markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.edit_text(msg_text, reply_markup=markup, parse_mode="Markdown")
    elif update.message:
        await update.message.reply_text(msg_text, reply_markup=markup, parse_mode="Markdown")
    return CHOOSING_ACTION

async def prompt_user_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.edit_text(
        "🔍 যে ইউজারের তথ্য দেখতে চান তার **User ID** (যেমন: `6380625902`) অথবা **Username** (যেমন: `username`) লিখুন:",
        parse_mode="Markdown",
        reply_markup=cancel_keyboard()
    )
    return ADMIN_SEARCH_USER

async def handle_admin_user_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.text in ["❌ Cancel", "🔙 Main Menu", "🔙 Back to Main Menu", "🔙 Back", "/cancel"]:
        return await cancel(update, context)

    query_str = update.message.text.strip().replace("@", "")
    db = load_db()
    users = db.get("users", {})

    target_uid = None
    if query_str in users:
        target_uid = query_str
    else:
        for u_id, u_info in users.items():
            if u_info.get("username", "").lower() == query_str.lower() or u_info.get("name", "").lower() == query_str.lower():
                target_uid = u_id
                break

    if not target_uid:
        await update.message.reply_text(
            f"❌ **'{query_str}'** নামের কোনো ইউজার খুঁজে পাওয়া যায়নি!\nদয়া করে সঠিক User ID বা Username দিন:",
            reply_markup=cancel_keyboard()
        )
        return ADMIN_SEARCH_USER

    return await show_user_detail_admin(update, context, target_uid)

async def show_user_detail_admin(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id):
    db = load_db()
    u_info = db.get("users", {}).get(str(user_id))
    if not u_info:
        if update.callback_query:
            await update.callback_query.answer("ইউজার পাওয়া যায়নি!", show_alert=True)
        return CHOOSING_ACTION

    status_str = "⛔ BANNED" if u_info.get("banned", False) else "🟢 ACTIVE"

    detail_text = (
        f"👤 **USER PROFILE DETAILS**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 **Name:** {u_info.get('name')}\n"
        f"🆔 **User ID:** `{user_id}`\n"
        f"👤 **Username:** @{u_info.get('username', 'None')}\n"
        f"💰 **Current Balance:** ৳{u_info.get('balance', 0.0):.2f}\n"
        f"💵 **Total Earned:** ৳{u_info.get('total_earned', 0.0):.2f}\n"
        f"💸 **Total Withdrawn:** ৳{u_info.get('total_withdrawn', 0.0):.2f}\n"
        f"📱 **Saved Number:** `{u_info.get('saved_number', 'Not Set')}`\n"
        f"🚦 **Account Status:** {status_str}\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )

    ban_btn_label = "🟢 Unban User" if u_info.get("banned", False) else "⛔ Ban User"

    keyboard = [
        [
            InlineKeyboardButton("➕ Add Balance", callback_data=f"usr_bal_add_{user_id}"),
            InlineKeyboardButton("➖ Deduct Balance", callback_data=f"usr_bal_sub_{user_id}")
        ],
        [InlineKeyboardButton(ban_btn_label, callback_data=f"usr_toggle_ban_{user_id}")],
        [InlineKeyboardButton("🔙 Back to User Manager", callback_data="adm_manage_users")]
    ]
    markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.edit_text(detail_text, reply_markup=markup, parse_mode="Markdown")
    elif update.message:
        await update.message.reply_text(detail_text, reply_markup=markup, parse_mode="Markdown")
    return CHOOSING_ACTION

async def admin_user_action_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    await query.answer()

    if data == "usr_search_prompt":
        return await prompt_user_search(update, context)

    elif data.startswith("usr_bal_add_"):
        u_id = data.replace("usr_bal_add_", "")
        context.user_data["edit_bal_target_uid"] = u_id
        context.user_data["edit_bal_mode"] = "add"
        await query.message.edit_text(
            f"💰 ID `{u_id}` ইউজারের একাউন্টে কত টাকা **যোগ** করতে চান লিখুন (যেমন: 50):",
            parse_mode="Markdown",
            reply_markup=cancel_keyboard()
        )
        return ADMIN_EDIT_BAL_AMOUNT

    elif data.startswith("usr_bal_sub_"):
        u_id = data.replace("usr_bal_sub_", "")
        context.user_data["edit_bal_target_uid"] = u_id
        context.user_data["edit_bal_mode"] = "sub"
        await query.message.edit_text(
            f"🔻 ID `{u_id}` ইউজারের একাউন্ট থেকে কত টাকা **কাটতে** চান লিখুন (যেমন: 30):",
            parse_mode="Markdown",
            reply_markup=cancel_keyboard()
        )
        return ADMIN_EDIT_BAL_AMOUNT

    elif data.startswith("usr_toggle_ban_"):
        u_id = data.replace("usr_toggle_ban_", "")
        db = load_db()
        if str(u_id) in db["users"]:
            curr = db["users"][str(u_id)].get("banned", False)
            db["users"][str(u_id)]["banned"] = not curr
            save_db(db)
        return await show_user_detail_admin(update, context, u_id)

async def save_admin_edit_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.text in ["❌ Cancel", "🔙 Main Menu", "🔙 Back to Main Menu", "🔙 Back", "/cancel"]:
        return await cancel(update, context)

    try:
        amount = float(update.message.text.strip())
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("⚠️ দয়া করে সঠিক ধনাত্মক সংখ্যা লিখুন (যেমন: 50):")
        return ADMIN_EDIT_BAL_AMOUNT

    u_id = context.user_data.get("edit_bal_target_uid")
    mode = context.user_data.get("edit_bal_mode", "add")
    
    db = load_db()
    u_id_str = str(u_id)
    if u_id_str in db["users"]:
        if mode == "add":
            db["users"][u_id_str]["balance"] = db["users"][u_id_str].get("balance", 0.0) + amount
            db["users"][u_id_str]["total_earned"] = db["users"][u_id_str].get("total_earned", 0.0) + amount
            save_db(db)
            try:
                await context.bot.send_message(
                    chat_id=int(u_id),
                    text=f"🎉 **BALANCE ADDED!**\nঅ্যাডমিন আপনার একাউন্টে **৳{amount:.2f}** যুক্ত করেছেন!",
                    parse_mode="Markdown"
                )
            except Exception:
                pass
        else:
            db["users"][u_id_str]["balance"] = max(0.0, db["users"][u_id_str].get("balance", 0.0) - amount)
            save_db(db)
            try:
                await context.bot.send_message(
                    chat_id=int(u_id),
                    text=f"⚠️ **BALANCE DEDUCTED!**\nঅ্যাডমিন আপনার একাউন্ট থেকে **৳{amount:.2f}** কেটে নিয়েছেন।",
                    parse_mode="Markdown"
                )
            except Exception:
                pass

    await update.message.reply_text(f"✅ ব্যালেন্স সফলভাবে আপডেট করা হয়েছে!")
    return await show_user_detail_admin(update, context, u_id)


# ================= FEATURE 3: SERVICE MANAGER =================
async def show_service_manager(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = load_db()
    services = db.get("services", {})

    msg_text = "🛠️ **SERVICE & RATE MANAGER**\n━━━━━━━━━━━━━━━━━━━━\n"
    keyboard = []
    
    for s_key, s_info in services.items():
        msg_text += f"🔹 **{s_info['name']}:** ৳{s_info['rate']:.2f} / ID\n"
        keyboard.append([
            InlineKeyboardButton(f"✏️ Edit Rate ({s_info['name']})", callback_data=f"srv_edit_{s_key}"),
            InlineKeyboardButton(f"🗑️ Delete", callback_data=f"srv_del_{s_key}")
        ])

    keyboard.append([InlineKeyboardButton("➕ Add New Service", callback_data="adm_add_service")])
    keyboard.append([InlineKeyboardButton("🔙 Main Menu", callback_data="adm_main")])

    markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.edit_text(msg_text, reply_markup=markup, parse_mode="Markdown")
    elif update.message:
        await update.message.reply_text(msg_text, reply_markup=markup, parse_mode="Markdown")
    return CHOOSING_ACTION

async def admin_srv_action_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    await query.answer()

    if data.startswith("srv_edit_"):
        s_key = data.replace("srv_edit_", "")
        context.user_data["edit_srv_key"] = s_key
        db = load_db()
        s_name = db.get("services", {}).get(s_key, {}).get("name", s_key)
        await query.message.edit_text(
            f"💵 **{s_name}** সার্ভিসের নতুন প্রতি আইডির রেট কত হবে সেটি লিখুন (যেমন: 15):",
            reply_markup=cancel_keyboard()
        )
        return ADMIN_EDIT_SRV_RATE

    elif data.startswith("srv_del_"):
        s_key = data.replace("srv_del_", "")
        db = load_db()
        if s_key in db.get("services", {}):
            del db["services"][s_key]
            save_db(db)
        return await show_service_manager(update, context)

async def save_admin_edit_srv_rate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.text in ["❌ Cancel", "🔙 Main Menu", "🔙 Back to Main Menu", "🔙 Back", "/cancel"]:
        return await cancel(update, context)

    try:
        new_rate = float(update.message.text.strip())
        if new_rate < 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("⚠️ দয়া করে সঠিক রেট লিখুন (যেমন: 15):")
        return ADMIN_EDIT_SRV_RATE

    s_key = context.user_data.get("edit_srv_key")
    db = load_db()
    if s_key in db.get("services", {}):
        db["services"][s_key]["rate"] = new_rate
        save_db(db)

    await update.message.reply_text("✅ সার্ভিসের রেট সফলভাবে পরিবর্তন করা হয়েছে!")
    return await show_service_manager(update, context)


# ================= FEATURE 4: MIN WITHDRAW LIMIT ADJUSTER =================
async def show_min_withdraw_setting(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = load_db()
    curr_min = db["settings"].get("min_withdraw", 500.0)

    msg_text = (
        f"💳 **MINIMUM WITHDRAW LIMIT**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📍 বর্তমান সর্বনিম্ন উইথড্র লিমিট: **৳{curr_min:.2f}**\n\n"
        f"নতুন সর্বনিম্ন উইথড্র লিমিট লিখুন (যেমন: 100 বা 150):"
    )

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.edit_text(msg_text, reply_markup=cancel_keyboard(), parse_mode="Markdown")
    elif update.message:
        await update.message.reply_text(msg_text, reply_markup=cancel_keyboard(), parse_mode="Markdown")
    return ADMIN_SET_MIN_WD

async def save_min_withdraw_setting(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.text in ["❌ Cancel", "🔙 Main Menu", "🔙 Back to Main Menu", "🔙 Back", "/cancel"]:
        return await cancel(update, context)

    try:
        new_min = float(update.message.text.strip())
        if new_min <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("⚠️ দয়া করে সঠিক সংখ্যায় পরিমাণ লিখুন (যেমন: 150):")
        return ADMIN_SET_MIN_WD

    db = load_db()
    db["settings"]["min_withdraw"] = new_min
    save_db(db)

    await update.message.reply_text(
        f"✅ সর্বনিম্ন উইথড্র লিমিট সফলভাবে **৳{new_min:.2f}** সেট করা হয়েছে!",
        reply_markup=admin_reply_keyboard()
    )
    return CHOOSING_ACTION


# ================= FEATURE 5: PENDING WITHDRAWS MANAGER =================
async def show_pending_withdraws(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = load_db()
    withdraws = db.get("withdraws", [])
    pending_list = [w for w in withdraws if w.get("status") == "Pending"]

    if not pending_list:
        msg_text = "📥 **PENDING WITHDRAWALS**\n━━━━━━━━━━━━━━━━━━━━\n🎉 বর্তমানে কোনো পেন্ডিং উইথড্র রিকোয়েস্ট নেই!"
        keyboard = [[InlineKeyboardButton("🔙 Main Menu", callback_data="adm_main")]]
        markup = InlineKeyboardMarkup(keyboard)
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.message.edit_text(msg_text, reply_markup=markup, parse_mode="Markdown")
        elif update.message:
            await update.message.reply_text(msg_text, reply_markup=markup, parse_mode="Markdown")
        return CHOOSING_ACTION

    msg_text = f"📥 **PENDING WITHDRAWALS ({len(pending_list)} টি)**\n━━━━━━━━━━━━━━━━━━━━\n"
    keyboard = []
    
    for wd in pending_list:
        w_id = wd.get("id")
        u_name = wd.get("user_name", "User")
        u_id = wd.get("user_id")
        amt = wd.get("amount", 0.0)
        method = wd.get("method", "Bkash")
        num = wd.get("number", "")

        msg_text += f"📌 **#{w_id}** | {u_name} (`{u_id}`)\n💸 **{method}** ({num}): ৳{amt:.2f}\n──────────────\n"
        keyboard.append([
            InlineKeyboardButton(f"✅ Approve #{w_id}", callback_data=f"pnd_app_{w_id}"),
            InlineKeyboardButton(f"❌ Reject #{w_id}", callback_data=f"pnd_rej_{w_id}")
        ])

    keyboard.append([InlineKeyboardButton("🔙 Main Menu", callback_data="adm_main")])
    markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.edit_text(msg_text, reply_markup=markup, parse_mode="Markdown")
    elif update.message:
        await update.message.reply_text(msg_text, reply_markup=markup, parse_mode="Markdown")
    return CHOOSING_ACTION

async def admin_pending_wd_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    db = load_db()

    if data.startswith("pnd_app_"):
        req_id = int(data.replace("pnd_app_", ""))
        wd_req = None
        for w in db.get("withdraws", []):
            if w.get("id") == req_id and w.get("status") == "Pending":
                wd_req = w
                break

        if wd_req:
            wd_req["status"] = "Approved"
            u_id_str = str(wd_req["user_id"])
            if u_id_str in db["users"]:
                db["users"][u_id_str]["total_withdrawn"] = db["users"][u_id_str].get("total_withdrawn", 0.0) + wd_req["amount"]
            save_db(db)

            await query.answer("উইথড্র অ্যাপ্রুভ করা হয়েছে!")
            try:
                await context.bot.send_message(
                    chat_id=wd_req["user_id"],
                    text=f"🎉 **WITHDRAW APPROVED!**\nআপনার **৳{wd_req['amount']:.2f}** উইথড্র সফলভাবে দেওয়া হয়েছে!",
                    parse_mode="Markdown"
                )
            except Exception:
                pass

        return await show_pending_withdraws(update, context)

    elif data.startswith("pnd_rej_"):
        req_id = int(data.replace("pnd_rej_", ""))
        wd_req = None
        for w in db.get("withdraws", []):
            if w.get("id") == req_id and w.get("status") == "Pending":
                wd_req = w
                break

        if wd_req:
            wd_req["status"] = "Rejected"
            u_id_str = str(wd_req["user_id"])
            if u_id_str in db["users"]:
                db["users"][u_id_str]["balance"] = db["users"][u_id_str].get("balance", 0.0) + wd_req["amount"]
            save_db(db)

            await query.answer("উইথড্র বাতিল করা হয়েছে!")
            try:
                await context.bot.send_message(
                    chat_id=wd_req["user_id"],
                    text=f"❌ **WITHDRAW REJECTED**\nআপনার **৳{wd_req['amount']:.2f}** উইথড্র বাতিল এবং ব্যালেন্স রিফান্ড করা হয়েছে।",
                    parse_mode="Markdown"
                )
            except Exception:
                pass

        return await show_pending_withdraws(update, context)


# ================= BANNED USERS LIST =================
async def show_banned_users_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = load_db()
    users = db.get("users", {})
    banned_list = {u_id: u_info for u_id, u_info in users.items() if u_info.get("banned", False)}

    if not banned_list:
        msg_text = "🚫 **BANNED USERS LIST**\n━━━━━━━━━━━━━━━━━━━━\n🎉 বর্তমানে কোনো ব্যানকৃত ইউজার নেই!"
        keyboard = [[InlineKeyboardButton("🔙 Main Menu", callback_data="adm_main")]]
        markup = InlineKeyboardMarkup(keyboard)
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.message.edit_text(msg_text, reply_markup=markup, parse_mode="Markdown")
        elif update.message:
            await update.message.reply_text(msg_text, reply_markup=markup, parse_mode="Markdown")
        return CHOOSING_ACTION

    msg_text = f"🚫 **BANNED USERS LIST ({len(banned_list)} জন)**\n━━━━━━━━━━━━━━━━━━━━\n"
    keyboard = []
    
    for u_id, u_info in banned_list.items():
        name = u_info.get("name", "User")
        uname = u_info.get("username", "None")
        msg_text += f"• **{name}** (`{u_id}`) | @{uname}\n"
        keyboard.append([InlineKeyboardButton(f"🟢 Unban {name} ({u_id})", callback_data=f"usr_toggle_ban_{u_id}")])

    keyboard.append([InlineKeyboardButton("🔙 Main Menu", callback_data="adm_main")])
    markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.edit_text(msg_text, reply_markup=markup, parse_mode="Markdown")
    elif update.message:
        await update.message.reply_text(msg_text, reply_markup=markup, parse_mode="Markdown")
    return CHOOSING_ACTION


# ================= LINK SETTINGS =================
async def show_link_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = load_db()
    s = db.get("settings", {})
    n_ch = s.get("notice_channel", NOTICE_CHANNEL)
    t_lk = s.get("tutorial_link", TUTORIAL_LINK)
    a_us = s.get("admin_username", ADMIN_USERNAME)
    p_lk = s.get("proof_link", TUTORIAL_LINK)

    msg_text = (
        f"🔗 **BOT LINK & CONTACT SETTINGS**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📢 **Notice Channel:** `{n_ch}`\n"
        f"📖 **Tutorial Link:** {t_lk}\n"
        f"💬 **Admin Support:** `@{a_us.replace('@', '')}`\n"
        f"🧾 **Payment Proof Link:** {p_lk}\n\n"
        f"যেকোনো লিংক পরিবর্তন করতে নিচের বাটনে ক্লিক করুন:"
    )

    keyboard = [
        [InlineKeyboardButton("✏️ Edit Notice Channel", callback_data="set_link_notice", api_kwargs={"style": "primary"})],
        [InlineKeyboardButton("✏️ Edit Tutorial Link", callback_data="set_link_tutorial", api_kwargs={"style": "primary"})],
        [InlineKeyboardButton("✏️ Edit Admin Support", callback_data="set_link_support", api_kwargs={"style": "primary"})],
        [InlineKeyboardButton("✏️ Edit Proof Link", callback_data="set_link_proof", api_kwargs={"style": "success"})],
        [InlineKeyboardButton("🔙 Main Menu", callback_data="adm_main", api_kwargs={"style": "danger"})]
    ]
    markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.edit_text(msg_text, reply_markup=markup, parse_mode="Markdown")
    elif update.message:
        await update.message.reply_text(msg_text, reply_markup=markup, parse_mode="Markdown")
    return CHOOSING_ACTION

async def admin_link_action_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    await query.answer()

    if data == "set_link_notice":
        await query.message.edit_text("📢 নতুন **Notice Channel** লিখুন (যেমন: `@MyChannel`):", reply_markup=cancel_keyboard())
        return ADMIN_SET_NOTICE_LINK
    elif data == "set_link_tutorial":
        await query.message.edit_text("📖 নতুন **Tutorial Link** লিখুন (যেমন: `https://t.me/...`):", reply_markup=cancel_keyboard())
        return ADMIN_SET_TUTORIAL_LINK
    elif data == "set_link_support":
        await query.message.edit_text("💬 নতুন **Admin Support Username** লিখুন (যেমন: `AdminUser`):", reply_markup=cancel_keyboard())
        return ADMIN_SET_SUPPORT_LINK
    elif data == "set_link_proof":
        await query.message.edit_text("🧾 নতুন **Payment Proof Link** লিখুন (যেমন: `https://t.me/...`):", reply_markup=cancel_keyboard())
        return ADMIN_SET_PROOF_LINK

async def save_notice_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.text in ["❌ Cancel", "🔙 Main Menu", "🔙 Back to Main Menu", "🔙 Back", "/cancel"]:
        return await cancel(update, context)

    val = update.message.text.strip()
    db = load_db()
    db["settings"]["notice_channel"] = val
    save_db(db)
    await update.message.reply_text(f"✅ Notice Channel আপডেট করা হয়েছে: `{val}`", parse_mode="Markdown")
    return await show_link_settings(update, context)

async def save_tutorial_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.text in ["❌ Cancel", "🔙 Main Menu", "🔙 Back to Main Menu", "🔙 Back", "/cancel"]:
        return await cancel(update, context)

    val = update.message.text.strip()
    db = load_db()
    db["settings"]["tutorial_link"] = val
    save_db(db)
    await update.message.reply_text(f"✅ Tutorial Link আপডেট করা হয়েছে!", parse_mode="Markdown")
    return await show_link_settings(update, context)

async def save_support_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.text in ["❌ Cancel", "🔙 Main Menu", "🔙 Back to Main Menu", "🔙 Back", "/cancel"]:
        return await cancel(update, context)

    val = update.message.text.strip().replace("@", "")
    db = load_db()
    db["settings"]["admin_username"] = val
    save_db(db)
    await update.message.reply_text(f"✅ Admin Support Username আপডেট করা হয়েছে: `@{val}`", parse_mode="Markdown")
    return await show_link_settings(update, context)

async def save_proof_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.text in ["❌ Cancel", "🔙 Main Menu", "🔙 Back to Main Menu", "🔙 Back", "/cancel"]:
        return await cancel(update, context)

    val = update.message.text.strip()
    db = load_db()
    db["settings"]["proof_link"] = val
    save_db(db)
    await update.message.reply_text(f"✅ Payment Proof Link আপডেট করা হয়েছে!", parse_mode="Markdown")
    return await show_link_settings(update, context)


# ================= DATABASE BACKUP =================
async def send_database_backup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if os.path.exists(DB_FILE):
            await context.bot.send_document(
                chat_id=update.effective_user.id,
                document=open(DB_FILE, "rb"),
                filename=f"bot_database_backup_{datetime.now().strftime('%d_%m_%Y')}.json",
                caption="📁 **BOT DATABASE BACKUP FILE**\nসকল ইউজার, ব্যালেন্স ও ফাইল রেকর্ড ব্যাকআপ ফাইল।"
            )
            if update.callback_query:
                await update.callback_query.answer("✅ ব্যাকআপ ফাইল পাঠানো হয়েছে!")
        else:
            await update.message.reply_text("⚠️ কোনো ডেটাবেজ ফাইল পাওয়া যায়নি।")
    except Exception as e:
        logger.error(f"Failed to send DB backup: {e}")
        await update.message.reply_text("⚠️ ব্যাকআপ ফাইল পাঠাতে ব্যর্থ হয়েছে।")
    return CHOOSING_ACTION




async def save_start_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.text in ["❌ Cancel", "🔙 Main Menu", "🔙 Back to Main Menu", "🔙 Back", "/cancel"]:
        return await cancel(update, context)

    text = update.message.text.strip()
    if not re.match(r"^([01]?[0-9]|2[0-3]):[0-5][0-9]$", text):
        await update.message.reply_text("⚠️ দয়া করে সঠিক 24-ঘণ্টার ফরম্যাটে সময় লিখুন (যেমন: `06:00`):", parse_mode="Markdown")
        return SET_START_TIME

    context.user_data["temp_start_time"] = text
    await update.message.reply_text(
        "⏰ কাজের শেষ সময় (End Time) লিখুন (24 ঘণ্টার ফরম্যাটে, যেমন: `20:00`):",
        parse_mode="Markdown",
        reply_markup=cancel_keyboard()
    )
    return SET_END_TIME

async def save_end_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.text in ["❌ Cancel", "🔙 Main Menu", "🔙 Back to Main Menu", "🔙 Back", "/cancel"]:
        return await cancel(update, context)


    end_text = update.message.text.strip()
    if not re.match(r"^([01]?[0-9]|2[0-3]):[0-5][0-9]$", end_text):
        await update.message.reply_text("⚠️ দয়া করে সঠিক 24-ঘণ্টার ফরম্যাটে সময় লিখুন (যেমন: `20:00`):", parse_mode="Markdown")
        return SET_END_TIME

    start_text = context.user_data.get("temp_start_time", "06:00")
    
    db = load_db()
    db["settings"]["start_time"] = start_text
    db["settings"]["end_time"] = end_text
    save_db(db)

    await update.message.reply_text(
        f"✅ কাজের সময় সফলভাবে আপডেট হয়েছে!\n⏳ নতুন শিডিউল: **{start_text} থেকে {end_text}**",
        reply_markup=main_menu_keyboard(True),
        parse_mode="Markdown"
    )
    return CHOOSING_ACTION

async def save_new_service_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.text in ["❌ Cancel", "🔙 Main Menu", "🔙 Back to Main Menu", "🔙 Back", "/cancel"]:
        return await cancel(update, context)

    context.user_data["new_srv_name"] = update.message.text.strip()
    await update.message.reply_text(
        "💵 প্রতি আইডির রেট কত হবে সেটি সংখ্যায় লিখুন (যেমন: 15):",
        reply_markup=cancel_keyboard()
    )
    return ADD_SERVICE_RATE

async def save_new_service_rate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.text in ["❌ Cancel", "🔙 Main Menu", "🔙 Back to Main Menu", "🔙 Back", "/cancel"]:
        return await cancel(update, context)


    try:
        rate = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("⚠️ দয়া করে সঠিক সংখ্যা লিখুন (যেমন: 15):")
        return ADD_SERVICE_RATE

    srv_name = context.user_data["new_srv_name"]
    srv_key = srv_name.lower().replace(" ", "_")
    
    db = load_db()
    db["services"][srv_key] = {"name": srv_name.title(), "rate": rate}
    save_db(db)

    await update.message.reply_text(
        f"✅ নতুন সার্ভিস **{srv_name.title()}** সফলভাবে যুক্ত হয়েছে! রেট: ৳{rate}",
        reply_markup=main_menu_keyboard(True),
        parse_mode="Markdown"
    )
    return CHOOSING_ACTION

# ================= BROADCAST HANDLER =================
async def handle_broadcast_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.text in ["❌ Cancel", "🔙 Main Menu", "🔙 Back to Main Menu", "🔙 Back", "/cancel"]:
        return await cancel(update, context)


    db = load_db()
    users = db.get("users", {})
    success_count = 0
    failed_count = 0

    await update.message.reply_text("⏳ ব্রডকাস্ট পাঠানো হচ্ছে, দয়া করে অপেক্ষা করুন...")

    for u_id in users.keys():
        try:
            if update.message.photo:
                photo_id = update.message.photo[-1].file_id
                caption = update.message.caption or ""
                await context.bot.send_photo(chat_id=int(u_id), photo=photo_id, caption=caption)
            else:
                await context.bot.send_message(chat_id=int(u_id), text=update.message.text)
            success_count += 1
        except Exception:
            failed_count += 1

    await update.message.reply_text(
        f"📢 **BROADCAST COMPLETED!**\n\n"
        f"✅ সফলভাবে পৌঁছেছে: **{success_count}** জন ইউজারের কাছে\n"
        f"❌ ব্যর্থ হয়েছে: **{failed_count}** জন",
        reply_markup=main_menu_keyboard(True),
        parse_mode="Markdown"
    )
    return CHOOSING_ACTION

# ================= ADMIN REPORT FLOW =================
async def admin_selected_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "adm_main":
        await query.message.edit_text("মূল মেনুতে ফিরে গেছেন।")
        return CHOOSING_ACTION

    u_id = None
    if query.data.startswith("rep_usr_"):
        u_id = query.data.replace("rep_usr_", "")
    elif query.data.startswith("quick_rep_"):
        u_id = query.data.replace("quick_rep_", "")

    if u_id:
        context.user_data["report_user_id"] = u_id
        db = load_db()
        services = db.get("services", {})
        
        keyboard = [
            [InlineKeyboardButton(s_info["name"], callback_data=f"rep_srv_{s_key}")]
            for s_key, s_info in services.items()
        ]
        keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel_action")])
        await query.message.edit_text("📌 কাজের সার্ভিস সিলেক্ট করুন:", reply_markup=InlineKeyboardMarkup(keyboard))
        return ADMIN_SELECT_SERVICE

async def admin_selected_service(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "cancel_action":
        return await cancel(update, context)

    if query.data.startswith("rep_srv_"):
        srv_key = query.data.replace("rep_srv_", "")
        context.user_data["report_service"] = srv_key
        
        await query.message.edit_text(
            f"📅 কাজের তারিখ লিখুন (যেমন: `{datetime.now().strftime('%Y-%m-%d')}`):",
            parse_mode="Markdown",
            reply_markup=cancel_keyboard()
        )
        return ADMIN_INPUT_DATE

async def admin_input_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.text in ["❌ Cancel", "🔙 Main Menu", "🔙 Back to Main Menu", "🔙 Back", "/cancel"]:
        return await cancel(update, context)

    context.user_data["report_date"] = update.message.text.strip()
    await update.message.reply_text(
        "🔢 ফাইলে থাকা মোট OK ID-এর সংখ্যা লিখুন (যেমন: 50):",
        reply_markup=cancel_keyboard()
    )
    return ADMIN_INPUT_COUNT

async def admin_input_count(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.text in ["❌ Cancel", "🔙 Main Menu", "🔙 Back to Main Menu", "🔙 Back", "/cancel"]:
        return await cancel(update, context)


    try:
        count = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("⚠️ দয়া করে সঠিক সংখ্যা লিখুন:")
        return ADMIN_INPUT_COUNT

    context.user_data["report_count"] = count
    await update.message.reply_text(
        "📸 কাজের প্রমাণস্বরূপ একটি স্ক্রিনশট (Photo) আপলোড করুন:",
        reply_markup=cancel_keyboard()
    )
    return ADMIN_INPUT_PROOF

async def admin_input_proof(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.text in ["❌ Cancel", "🔙 Main Menu", "🔙 Back to Main Menu", "🔙 Back", "/cancel"]:
        return await cancel(update, context)

    if not update.message.photo:
        await update.message.reply_text("⚠️ দয়া করে একটি সঠিক ছবি (Screenshot) পাঠান:")
        return ADMIN_INPUT_PROOF


    photo_id = update.message.photo[-1].file_id
    u_id = context.user_data["report_user_id"]
    srv_key = context.user_data["report_service"]
    w_date = context.user_data["report_date"]
    ok_count = context.user_data["report_count"]

    db = load_db()
    srv_info = db.get("services", {}).get(srv_key, {})
    rate = srv_info.get("rate", 10.0)
    srv_name = srv_info.get("name", srv_key.upper())
    added_amount = ok_count * rate

    if u_id not in db["users"]:
        await update.message.reply_text("❌ ইউজার ডাটাবেজে পাওয়া যায়নি!")
        return CHOOSING_ACTION

    u_data = db["users"][u_id]
    prev_balance = u_data.get("balance", 0.0)
    new_balance = prev_balance + added_amount

    u_data["balance"] = new_balance
    u_data["total_earned"] = u_data.get("total_earned", 0.0) + added_amount
    save_db(db)

    user_msg = (
        f"🎉 **NEW WORK REPORT APPROVED!**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 **Service:** {srv_name}\n"
        f"📅 **Work Date:** {w_date}\n"
        f"🔢 **Total OK IDs:** {ok_count} টি\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 **Previous Balance:** ৳{prev_balance:.2f}\n"
        f"➕ **Added Amount:** ৳{added_amount:.2f}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💵 **New Total Balance:** ৳{new_balance:.2f}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ আপনার কাজটি সফলভাবে যাচাই ও গ্রহণ করা হয়েছে। ধন্যবাদ!"
    )
    
    try:
        await context.bot.send_photo(chat_id=int(u_id), photo=photo_id, caption=user_msg, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Failed to send user notification: {e}")

    await update.message.reply_text(
        f"✅ সফলভাবে রিপোর্ট সাবমিট হয়েছে এবং ইউজার ({u_data.get('name', u_id)}) ব্যালেন্সে ৳{added_amount:.2f} যোগ করা হয়েছে!",
        reply_markup=main_menu_keyboard(True)
    )
    return CHOOSING_ACTION

# ================= CALLBACK HANDLERS FOR GROUP ACTIONS =================
async def admin_rcv_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("ফাইলটি রিসিভ করা হয়েছে!")
    
    if query.data.startswith("rcv_done_"):
        original_caption = query.message.caption or query.message.text or ""
        updated_caption = f"{original_caption}\n\n✅ **[RECEIVED BY ADMIN]**"
        
        try:
            if query.message.document or query.message.photo:
                await query.message.edit_caption(caption=updated_caption, parse_mode="Markdown")
            else:
                await query.message.edit_text(text=updated_caption, parse_mode="Markdown")
        except Exception:
            pass

async def admin_withdraw_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    db = load_db()

    if data.startswith("wd_approve_"):
        parts = data.split("_")
        u_id = parts[2]
        amount = float(parts[3])
        req_id = int(parts[4]) if len(parts) > 4 else None

        await query.answer("উইথড্র অ্যাপ্রুভ করা হয়েছে!")
        
        # Update user total withdrawn
        u_id_str = str(u_id)
        if u_id_str in db["users"]:
            db["users"][u_id_str]["total_withdrawn"] = db["users"][u_id_str].get("total_withdrawn", 0.0) + amount
            save_db(db)

        # Update withdrawal request status
        if req_id:
            for wd in db.get("withdraws", []):
                if wd.get("id") == req_id:
                    wd["status"] = "Approved"
                    save_db(db)
                    break

        original_text = query.message.text or ""
        await query.message.edit_text(f"{original_text}\n\n✅ **[APPROVED & PAID]**", parse_mode="Markdown")

        # Notify user
        try:
            await context.bot.send_message(
                chat_id=int(u_id),
                text=f"🎉 **WITHDRAW SUCCESSFUL!**\n\n"
                     f"আপনার ৳{amount:.2f} টাকা উইথড্র সফলভাবে পেমেন্ট করা হয়েছে!",
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Failed to notify user about withdrawal approval: {e}")

    elif data.startswith("wd_reject_"):
        parts = data.split("_")
        u_id = parts[2]
        amount = float(parts[3])
        req_id = int(parts[4]) if len(parts) > 4 else None

        await query.answer("উইথড্র রিজেক্ট করা হয়েছে!")

        # Refund user balance
        u_id_str = str(u_id)
        if u_id_str in db["users"]:
            db["users"][u_id_str]["balance"] += amount
            save_db(db)

        # Update withdrawal request status
        if req_id:
            for wd in db.get("withdraws", []):
                if wd.get("id") == req_id:
                    wd["status"] = "Rejected"
                    save_db(db)
                    break

        original_text = query.message.text or ""
        await query.message.edit_text(f"{original_text}\n\n❌ **[REJECTED & REFUNDED]**", parse_mode="Markdown")

        # Notify user
        try:
            await context.bot.send_message(
                chat_id=int(u_id),
                text=f"❌ **WITHDRAW REJECTED**\n\n"
                     f"আপনার ৳{amount:.2f} টাকা উইথড্র রিকোয়েস্ট বাতিল করা হয়েছে এবং ব্যালেন্স রিফান্ড করা হয়েছে।",
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Failed to notify user about withdrawal rejection: {e}")

async def user_rules_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    rules_text = (
        f"📜 **WORK TERMS & GUIDELINES**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"১. কোনো ভুয়া বা ফেক ফাইল সাবমিট করা যাবে না।\n"
        f"২. একই ফাইল বা কাজ দ্বিতীয়বার (Double Submit) করলে অ্যাকাউন্ট স্বয়ংক্রিয়ভাবে **১ দিনের জন্য ব্যান** হয়ে যাবে।\n"
        f"৩. নির্দিষ্ট সময়ের মধ্যে ফাইল জমা দিতে হবে।\n"
        f"৪. অ্যাডমিন ফাইল যাচাই করে ব্যালেন্স যুক্ত করে দেবেন।"
    )
    await query.message.reply_text(rules_text, parse_mode="Markdown")

async def profile_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user = update.effective_user
    u_id_str = str(user.id)
    db = load_db()

    if data == "prof_edit_num":
        u_data = db["users"].get(u_id_str, {})
        saved_num = u_data.get("saved_number", "Not Set")
        msg_text = (
            f"📱 **SAVED WITHDRAWAL NUMBER**\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📌 বর্তমান সেভকৃত নম্বর: `{saved_num}`\n\n"
            f"বিকাশ বা নগদে টাকা তোলার সময় এই নম্বরটি ১-ক্লিকেই ব্যবহার করতে পারবেন।\n"
            f"নতুন নম্বর সেট বা আপডেট করতে নিচে আপনার **১১ ডিজিটের মোবাইল নম্বর** লিখুন:"
        )
        await query.message.reply_text(msg_text, reply_markup=cancel_keyboard(), parse_mode="Markdown")
        return USER_SET_SAVED_NUM

    elif data == "prof_today_price":
        services = db.get("services", {})
        price_text = "📋 **TODAY'S SERVICE RATES**\n━━━━━━━━━━━━━━━━━━━━\n"
        for s_key, s_info in services.items():
            price_text += f"🔹 **{s_info['name']}:** ৳{s_info['rate']} প্রতি আইডি\n"
        await query.message.reply_text(price_text, parse_mode="Markdown")

    elif data == "prof_history":
        return await show_user_history(update, context)

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ADMIN_ID:
        await update.message.reply_text("⛔ আপনি এই বটের অ্যাডমিন নন!")
        return CHOOSING_ACTION
    await update.message.reply_text("⚙️ **ADMIN CONTROL PANEL**", reply_markup=admin_reply_keyboard(), parse_mode="Markdown")
    await update.message.reply_text("ইনলাইন মেনু বিকল্প:", reply_markup=admin_panel_keyboard())
    return CHOOSING_ACTION

# ================= MAIN APPLICATION SETUP =================
def main():
    print("🤖 Starting Telegram Bot...")
    load_db()

    app = ApplicationBuilder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CommandHandler("admin", admin_command),
            CommandHandler("cancel", cancel)
        ],
        states={
            CHOOSING_ACTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu_clicks),
                CallbackQueryHandler(profile_callbacks, pattern="^prof_"),
                CallbackQueryHandler(user_rules_callback, pattern="^user_rules$"),
                CallbackQueryHandler(verify_channel_join_callback, pattern="^verify_channel_join$"),
                CallbackQueryHandler(admin_wt_callback, pattern="^wt_"),
                CallbackQueryHandler(admin_panel_clicks, pattern="^adm_"),
                CallbackQueryHandler(admin_user_action_callback, pattern="^usr_"),
                CallbackQueryHandler(admin_srv_action_callback, pattern="^srv_"),
                CallbackQueryHandler(admin_pending_wd_action, pattern="^pnd_"),
                CallbackQueryHandler(admin_link_action_callback, pattern="^set_link_"),
                CallbackQueryHandler(admin_selected_user, pattern="^quick_rep_")
            ],
            SUBMIT_FILE: [
                CallbackQueryHandler(select_service_for_submission, pattern="^send_srv_|^cancel_action$"),
                MessageHandler(filters.Document.ALL | filters.TEXT & ~filters.COMMAND, receive_user_file)
            ],
            WITHDRAW_METHOD: [
                CallbackQueryHandler(select_withdraw_method, pattern="^wd_method_|^cancel_action$")
            ],
            WITHDRAW_NUMBER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_withdraw_number),
                CallbackQueryHandler(handle_withdraw_number_choice, pattern="^wd_use_saved$|^wd_type_new$"),
                CallbackQueryHandler(cancel, pattern="^cancel_action$")
            ],
            WITHDRAW_AMOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_withdraw_amount),
                CallbackQueryHandler(cancel, pattern="^cancel_action$")
            ],
            ADD_SERVICE_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_new_service_name),
                CallbackQueryHandler(cancel, pattern="^cancel_action$")
            ],
            ADD_SERVICE_RATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_new_service_rate),
                CallbackQueryHandler(cancel, pattern="^cancel_action$")
            ],
            SET_START_TIME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_start_time),
                CallbackQueryHandler(cancel, pattern="^cancel_action$")
            ],
            SET_END_TIME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_end_time),
                CallbackQueryHandler(cancel, pattern="^cancel_action$")
            ],
            BROADCAST_MSG: [
                MessageHandler(filters.ALL & ~filters.COMMAND, handle_broadcast_msg),
                CallbackQueryHandler(cancel, pattern="^cancel_action$")
            ],
            ADMIN_SELECT_USER: [
                CallbackQueryHandler(admin_selected_user, pattern="^rep_usr_|^adm_main$")
            ],
            ADMIN_SELECT_SERVICE: [
                CallbackQueryHandler(admin_selected_service, pattern="^rep_srv_|^cancel_action$")
            ],
            ADMIN_INPUT_DATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_input_date),
                CallbackQueryHandler(cancel, pattern="^cancel_action$")
            ],
            ADMIN_INPUT_COUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_input_count),
                CallbackQueryHandler(cancel, pattern="^cancel_action$")
            ],
            ADMIN_INPUT_PROOF: [
                MessageHandler(filters.PHOTO, admin_input_proof),
                CallbackQueryHandler(cancel, pattern="^cancel_action$")
            ],
            ADMIN_SEARCH_USER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_user_search),
                CallbackQueryHandler(cancel, pattern="^cancel_action$|^adm_main$")
            ],
            ADMIN_EDIT_BAL_AMOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_admin_edit_balance),
                CallbackQueryHandler(cancel, pattern="^cancel_action$|^adm_main$")
            ],
            ADMIN_EDIT_SRV_RATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_admin_edit_srv_rate),
                CallbackQueryHandler(cancel, pattern="^cancel_action$|^adm_main$")
            ],
            ADMIN_SET_MIN_WD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_min_withdraw_setting),
                CallbackQueryHandler(cancel, pattern="^cancel_action$|^adm_main$")
            ],
            USER_SET_SAVED_NUM: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_user_saved_number),
                CallbackQueryHandler(cancel, pattern="^cancel_action$|^adm_main$")
            ],
            ADMIN_SET_NOTICE_LINK: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_notice_link),
                CallbackQueryHandler(cancel, pattern="^cancel_action$|^adm_main$")
            ],
            ADMIN_SET_TUTORIAL_LINK: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_tutorial_link),
                CallbackQueryHandler(cancel, pattern="^cancel_action$|^adm_main$")
            ],
            ADMIN_SET_SUPPORT_LINK: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_support_link),
                CallbackQueryHandler(cancel, pattern="^cancel_action$|^adm_main$")
            ],
            ADMIN_SET_PROOF_LINK: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_proof_link),
                CallbackQueryHandler(cancel, pattern="^cancel_action$|^adm_main$")
            ]
        },
        fallbacks=[
            CommandHandler("start", start),
            CommandHandler("admin", admin_command),
            CommandHandler("cancel", cancel),
            CallbackQueryHandler(cancel, pattern="^cancel_action$")
        ]
    )

    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(admin_rcv_callback, pattern="^rcv_done_"))
    app.add_handler(CallbackQueryHandler(admin_withdraw_callback, pattern="^wd_approve_|^wd_reject_"))

    # Start health check HTTP server for Render compatibility if PORT is set
    port = os.getenv("PORT")
    if port:
        t = threading.Thread(target=start_health_check_server, daemon=True)
        t.start()
        print(f"🌐 Health check HTTP server running on port {port}")

    print("✅ Bot is running smoothly with your credentials...")
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    app.run_polling(close_loop=False)

if __name__ == "__main__":
    main()
