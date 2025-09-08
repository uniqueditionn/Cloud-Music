import os
import logging
import asyncio
from datetime import datetime

import yt_dlp
from fastapi import FastAPI, Request
from telegram import (
    Update,
    InputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Bot,
)
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# Logging setup
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Environment variables
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").rstrip("/")
COOKIES_ENV = os.getenv("YT_COOKIES_FILES")

# Write cookies.txt if provided in environment
COOKIES_FILE = "cookies.txt"
if COOKIES_ENV:
    with open(COOKIES_FILE, "w", encoding="utf-8") as f:
        f.write(COOKIES_ENV)

# FastAPI app
app = FastAPI()

# Standalone Bot instance for webhook
bot = Bot(token=BOT_TOKEN)

# Telegram application
application = Application.builder().token(BOT_TOKEN).build()

# Track monthly users and pending song requests
monthly_users = set()
pending_songs = {}  # user_id -> song_name


# Helpers
def get_greeting(username: str) -> str:
    hour = datetime.utcnow().hour + 5.5  # IST
    hour = int(hour % 24)
    if 5 <= hour < 12:
        greeting = "🌅 Good Morning"
    elif 12 <= hour < 17:
        greeting = "🌞 Good Afternoon"
    elif 17 <= hour < 21:
        greeting = "🌇 Good Evening"
    else:
        greeting = "🌙 Good Night"
    return f"{greeting}, @{username}!"


async def send_typing(ctx: ContextTypes.DEFAULT_TYPE, chat_id: int):
    await ctx.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)


# Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    monthly_users.add(user_id)

    username = update.effective_user.username or update.effective_user.first_name
    greeting = get_greeting(username)

    await update.message.reply_text(
        f"{greeting}\n\nSend me the name of the song you want 🎶"
    )


async def handle_song_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    song_name = update.message.text
    pending_songs[user_id] = song_name

    keyboard = [
        [
            InlineKeyboardButton("🎵 Music", callback_data="music"),
            InlineKeyboardButton("🎬 Video", callback_data="video"),
            InlineKeyboardButton("🎶 Both", callback_data="both"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"Select what to receive for *{song_name}*:", reply_markup=reply_markup
    )


async def handle_option(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    choice = query.data
    user_id = query.from_user.id
    song_name = pending_songs.get(user_id)

    if not song_name:
        await query.edit_message_text("❌ No song found. Please send song name first.")
        return

    await query.edit_message_text(f"⏳ Downloading {choice} for *{song_name}*...")
    await send_typing(context, query.message.chat.id)

    # yt-dlp options
    if choice == "music":
        ydl_opts = {
            "quiet": True,
            "format": "bestaudio[ext=m4a]/bestaudio",
            "outtmpl": "%(title)s.%(ext)s",
        }
    elif choice == "video":
        ydl_opts = {
            "quiet": True,
            "format": "bestvideo[height<=720]+bestaudio/best",
            "outtmpl": "%(title)s.%(ext)s",
        }
    else:
        ydl_opts = {
            "quiet": True,
            "format": "bestvideo[height<=720]+bestaudio/best",
            "outtmpl": "%(title)s.%(ext)s",
        }

    if os.path.exists(COOKIES_FILE):
        ydl_opts["cookiefile"] = COOKIES_FILE

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"ytsearch1:{song_name}", download=True)
            if "entries" in info:
                info = info["entries"][0]
            filename = ydl.prepare_filename(info)

        chat_id = query.message.chat.id

        if choice in ("music", "both"):
            await context.bot.send_audio(
                chat_id=chat_id,
                audio=InputFile(filename),
                title=info.get("title"),
            )

        if choice in ("video", "both"):
            await context.bot.send_video(
                chat_id=chat_id,
                video=InputFile(filename),
                caption=info.get("title"),
            )

        await query.message.reply_text(f"✅ Delivered: {info.get('title')}")

        # Clean up
        if os.path.exists(filename):
            os.remove(filename)

        # Clear pending
        pending_songs.pop(user_id, None)

    except Exception as e:
        logger.error(f"Error downloading {song_name}: {e}")
        await query.message.reply_text("❌ Failed to fetch the song. Please try again.")


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"📊 Monthly active users: {len(monthly_users)}"
    )


# Register handlers
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("stats", stats))
application.add_handler(
    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_song_name)
)
application.add_handler(CallbackQueryHandler(handle_option))


# FastAPI routes
@app.on_event("startup")
async def startup_event():
    # Set webhook only
    await bot.set_webhook(url=f"{WEBHOOK_URL}/webhook")
    logger.info("Bot webhook set.")


@app.on_event("shutdown")
async def shutdown_event():
    # Remove webhook on shutdown
    await bot.delete_webhook()
    logger.info("Bot webhook removed.")


@app.post("/webhook")
async def telegram_webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, bot)
    # Process update asynchronously to avoid Telegram timeout
    asyncio.create_task(application.process_update(update))
    return {"ok": True}


@app.get("/")
async def root():
    return {"status": "Bot is alive ✅"}
