import os
import logging
from datetime import datetime
import yt_dlp

from fastapi import FastAPI, Request
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
)
from telegram.constants import ChatAction
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)

# ----------------- CONFIG -----------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # Example: https://your-app.onrender.com/webhook

# ----------------- LOGGING -----------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ----------------- FASTAPI -----------------
app = FastAPI()
application = Application.builder().token(BOT_TOKEN).build()

# Track user choices
user_preferences = {}
monthly_users = set()

# ----------------- HELPERS -----------------
def get_greeting(username: str, first_name: str) -> str:
    hour = datetime.utcnow().hour + 5.5  # IST offset
    if hour < 12:
        greet = "Good Morning"
    elif hour < 17:
        greet = "Good Afternoon"
    elif hour < 21:
        greet = "Good Evening"
    else:
        greet = "Good Night"
    
    name = f"@{username}" if username else first_name
    return f"{greet}, {name} 👋"

async def send_typing(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

def download_media(query: str, download_audio=True, download_video=False):
    ydl_opts = {
        "format": "bestaudio/best" if download_audio else "best",
        "outtmpl": "%(id)s.%(ext)s",
        "quiet": True,
        "noplaylist": True,
        "writesubtitles": False,
        "writethumbnail": True,
        "postprocessors": []
    }

    if download_audio:
        ydl_opts["postprocessors"].append({
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        })
        ydl_opts["postprocessors"].append({
            "key": "EmbedThumbnail"
        })

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(f"ytsearch1:{query}", download=True)
        file_path = ydl.prepare_filename(info["entries"][0])
        if download_audio:
            file_path = file_path.rsplit(".", 1)[0] + ".mp3"
        return file_path, info["entries"][0]["title"]

# ----------------- HANDLERS -----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    greeting = get_greeting(user.username, user.first_name)
    monthly_users.add(user.id)

    keyboard = [
        [InlineKeyboardButton("🎵 Music", callback_data="music")],
        [InlineKeyboardButton("🎬 Video", callback_data="video")],
        [InlineKeyboardButton("🎶 Both", callback_data="both")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"{greeting}\n\nWhat would you like to listen to?",
        reply_markup=reply_markup
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    choice = query.data
    user_preferences[query.from_user.id] = choice
    await query.edit_message_text(
        text=f"You selected: {choice.upper()} ✅\n\nNow send me a song name 🎵"
    )

async def song_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    choice = user_preferences.get(user_id, "music")
    query = update.message.text

    await send_typing(context, update.effective_chat.id)

    if choice == "music":
        file_path, title = download_media(query, download_audio=True, download_video=False)
        await update.message.reply_audio(audio=InputFile(file_path), title=title)

    elif choice == "video":
        file_path, title = download_media(query, download_audio=False, download_video=True)
        await update.message.reply_video(video=InputFile(file_path), caption=title)

    elif choice == "both":
        audio_path, title = download_media(query, download_audio=True, download_video=False)
        video_path, _ = download_media(query, download_audio=False, download_video=True)
        await update.message.reply_audio(audio=InputFile(audio_path), title=title)
        await update.message.reply_video(video=InputFile(video_path), caption=title)

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"📊 Monthly active users: {len(monthly_users)}")

# ----------------- ROUTES -----------------
@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, application.bot)
    await application.update_queue.put(update)
    return {"ok": True}

@app.on_event("startup")
async def startup_event():
    await application.bot.set_webhook(WEBHOOK_URL)
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, song_handler))

@app.on_event("shutdown")
async def shutdown_event():
    await application.shutdown()
    await application.stop()
