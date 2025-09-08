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

# Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Environment
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").rstrip("/")
COOKIES_ENV = os.getenv("YT_COOKIES_FILES")

# Cookies file
COOKIES_FILE = "cookies.txt"
if COOKIES_ENV:
    with open(COOKIES_FILE, "w", encoding="utf-8") as f:
        f.write(COOKIES_ENV)

# FastAPI
app = FastAPI()

# Standalone bot instance
bot = Bot(token=BOT_TOKEN)

# Track users and pending songs
monthly_users = set()
pending_songs = {}  # user_id -> song_name


# Helper: greeting
def get_greeting(username: str) -> str:
    hour = (datetime.utcnow().hour + 5.5) % 24  # IST
    hour = int(hour)
    if 5 <= hour < 12:
        greeting = "🌅 Good Morning"
    elif 12 <= hour < 17:
        greeting = "🌞 Good Afternoon"
    elif 17 <= hour < 21:
        greeting = "🌇 Good Evening"
    else:
        greeting = "🌙 Good Night"
    return f"{greeting}, @{username}!"


# Helper: typing indicator
async def send_typing(chat_id: int):
    await bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)


# Handlers
async def start(update: Update):
    user_id = update.effective_user.id
    monthly_users.add(user_id)

    username = update.effective_user.username or update.effective_user.first_name
    greeting = get_greeting(username)

    await bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"{greeting}\n\nSend me the name of the song you want 🎶"
    )


async def handle_song_name(update: Update):
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

    await bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"Select what to receive for *{song_name}*:",
        reply_markup=reply_markup
    )


async def handle_option(update: Update):
    query = update.callback_query
    await query.answer()
    choice = query.data
    user_id = query.from_user.id
    song_name = pending_songs.get(user_id)

    if not song_name:
        await bot.edit_message_text(
            chat_id=query.message.chat.id,
            message_id=query.message.message_id,
            text="❌ No song found. Please send song name first."
        )
        return

    await bot.edit_message_text(
        chat_id=query.message.chat.id,
        message_id=query.message.message_id,
        text=f"⏳ Downloading {choice} for *{song_name}*..."
    )
    await send_typing(query.message.chat.id)

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
            await bot.send_audio(
                chat_id=chat_id,
                audio=InputFile(filename),
                title=info.get("title"),
            )

        if choice in ("video", "both"):
            await bot.send_video(
                chat_id=chat_id,
                video=InputFile(filename),
                caption=info.get("title"),
            )

        await bot.send_message(chat_id=chat_id, text=f"✅ Delivered: {info.get('title')}")

        # Clean up
        if os.path.exists(filename):
            os.remove(filename)

        pending_songs.pop(user_id, None)

    except Exception as e:
        logger.error(f"Error downloading {song_name}: {e}")
        await bot.send_message(chat_id=query.message.chat.id, text="❌ Failed to fetch the song. Please try again.")


async def stats(update: Update):
    await bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"📊 Monthly active users: {len(monthly_users)}"
    )


# Webhook route
@app.post("/webhook")
async def telegram_webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, bot)

    # Directly call handlers
    try:
        if update.message:
            if update.message.text == "/start":
                asyncio.create_task(start(update))
            elif update.message.text == "/stats":
                asyncio.create_task(stats(update))
            else:
                asyncio.create_task(handle_song_name(update))
        elif update.callback_query:
            asyncio.create_task(handle_option(update))
    except Exception as e:
        logger.error(f"Error processing update: {e}")

    # Respond quickly to Telegram
    return {"ok": True}


@app.on_event("startup")
async def startup_event():
    # Set webhook
    await bot.set_webhook(url=f"{WEBHOOK_URL}/webhook")
    logger.info("Webhook set.")


@app.on_event("shutdown")
async def shutdown_event():
    # Remove webhook
    await bot.delete_webhook()
    logger.info("Webhook removed.")


@app.get("/")
async def root():
    return {"status": "Bot is alive ✅"}
