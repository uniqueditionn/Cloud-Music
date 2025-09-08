import os
import logging
from datetime import datetime

import yt_dlp
from fastapi import FastAPI, Request
from telegram import (
    Update,
    InputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ---------------------------------------------------------
# Logging setup
# ---------------------------------------------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------
# Environment variables
# ---------------------------------------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").rstrip("/")
COOKIES_ENV = os.getenv("YT_COOKIES_FILES")

# Write cookies.txt if provided in environment
COOKIES_FILE = "cookies.txt"
if COOKIES_ENV:
    with open(COOKIES_FILE, "w", encoding="utf-8") as f:
        f.write(COOKIES_ENV)

# ---------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------
app = FastAPI()

# ---------------------------------------------------------
# Telegram application
# ---------------------------------------------------------
application = Application.builder().token(BOT_TOKEN).build()

# Track user choices
user_choices = {}


# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------
def get_greeting(username: str) -> str:
    """Return time-based greeting with username"""
    hour = datetime.utcnow().hour + 5.5  # IST (UTC+5:30)
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
    """Send typing action"""
    await ctx.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)


# ---------------------------------------------------------
# Handlers
# ---------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username or update.effective_user.first_name
    greeting = get_greeting(username)

    keyboard = [
        [
            InlineKeyboardButton("🎵 Music", callback_data="music"),
            InlineKeyboardButton("🎬 Video", callback_data="video"),
            InlineKeyboardButton("🎶 Both", callback_data="both"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"{greeting}\n\nWhat would you like to listen/watch?",
        reply_markup=reply_markup,
    )


async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    choice = query.data
    user_choices[query.from_user.id] = choice

    await query.edit_message_text(
        f"You selected: {choice.upper()}\n\nNow send me the song name 🎶"
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    choice = user_choices.get(user_id)

    if not choice:
        await update.message.reply_text("Please choose an option first using /start")
        return

    song_name = update.message.text
    await send_typing(context, update.effective_chat.id)

    # Download with yt-dlp
    ydl_opts = {
        "quiet": True,
        "format": "bestaudio/best" if choice == "music" else "bestvideo+bestaudio/best",
        "outtmpl": "%(title)s.%(ext)s",
    }
    if os.path.exists(COOKIES_FILE):
        ydl_opts["cookiefile"] = COOKIES_FILE

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(f"ytsearch1:{song_name}", download=True)
        if "entries" in info:
            info = info["entries"][0]
        filename = ydl.prepare_filename(info)

    if choice in ("music", "both"):
        await context.bot.send_audio(
            chat_id=update.effective_chat.id,
            audio=InputFile(filename),
            title=info.get("title"),
        )

    if choice in ("video", "both"):
        await context.bot.send_video(
            chat_id=update.effective_chat.id,
            video=InputFile(filename),
            caption=info.get("title"),
        )


# ---------------------------------------------------------
# Register handlers
# ---------------------------------------------------------
application.add_handler(CommandHandler("start", start))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
application.add_handler(MessageHandler(filters.COMMAND, start))
application.add_handler(
    MessageHandler(filters.StatusUpdate.WEB_APP_DATA, handle_message)
)
application.add_handler(
    MessageHandler(filters.TEXT & filters.Entity("bot_command"), start)
)
application.add_handler(application.callback_query_handler(button))


# ---------------------------------------------------------
# FastAPI routes
# ---------------------------------------------------------
@app.on_event("startup")
async def startup_event():
    # Start bot
    await application.start()
    await application.bot.set_webhook(url=f"{WEBHOOK_URL}/webhook")
    logger.info("Bot started and webhook set.")


@app.on_event("shutdown")
async def shutdown_event():
    if application.running:
        await application.stop()
    logger.info("Bot stopped.")


@app.post("/webhook")
async def telegram_webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, application.bot)
    await application.process_update(update)
    return {"ok": True}


@app.get("/")
async def root():
    return {"status": "Bot is alive ✅"}
