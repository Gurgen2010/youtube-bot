import subprocess
import sys
import os
import asyncio
import sqlite3
import re

# -------------------------------------------------------------
# ԱՎՏՈՄԱՏ ԳՐԱԴԱՐԱՆՆԵՐԻ ՏԵՂԱԴՐՈՒՄ ԵՎ ԹԱՐՄԱՑՈՒՄ
# -------------------------------------------------------------
REQUIRED_PACKAGES = ["aiogram", "yt-dlp", "aiohttp"]

def install_and_update_packages():
    for package in REQUIRED_PACKAGES:
        try:
            __import__(package.replace("-", "_"))
        except ImportError:
            print(f"📦 Ավտոմատ տեղադրվում է {package}...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", package])

    try:
        print("🔄 Ստուգվում է yt-dlp-ի թարմացումները...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp"])
    except Exception as e:
        print(f"⚠️ Չհաջողվեց թարմացնել yt-dlp-ն: {e}")

install_and_update_packages()

import yt_dlp
from aiogram import Bot, Dispatcher, F
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.types import Message, CallbackQuery, FSInputFile, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

# BOT TOKEN
API_TOKEN = '8571888062:AAFy7fMOqDHzDVK01y3SEULaSYNI7OZaHrk'

# ⚡ Render-ի Webhook-ի փոփոխականներ
BASE_WEBHOOK_URL = os.getenv("RENDER_EXTERNAL_URL")
WEBHOOK_PATH = f"/webhook/{API_TOKEN}"
WEB_SERVER_HOST = "0.0.0.0"
WEB_SERVER_PORT = int(os.getenv("PORT", 10000))

session = AiohttpSession(timeout=120)
bot = Bot(token=API_TOKEN, session=session)
dp = Dispatcher()

# Տվյալների բազա
DB_FILE = "songs_cache.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS cache (
            video_id TEXT PRIMARY KEY,
            file_id TEXT NOT NULL,
            title TEXT NOT NULL
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS stats (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            download_count INTEGER DEFAULT 0
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def log_user_download(user_id: int, username: str):
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT download_count FROM stats WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()

        if row:
            cursor.execute('''
                UPDATE stats
                SET download_count = download_count + 1, username = ?
                WHERE user_id = ?
            ''', (username, user_id))
        else:
            cursor.execute('''
                INSERT INTO stats (user_id, username, download_count)
                VALUES (?, ?, 1)
            ''', (user_id, username))

        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Ошибка БД (stats): {e}")

def get_top_users():
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT username, download_count
            FROM stats
            ORDER BY download_count DESC LIMIT 20
        ''')
        rows = cursor.fetchall()
        conn.close()
        return rows
    except Exception as e:
        print(f"Ошибка получения ТОП 20: {e}")
        return []

def get_cached_video(video_id: str):
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT file_id, title FROM cache WHERE video_id = ?", (video_id,))
        row = cursor.fetchone()
        conn.close()
        return row
    except Exception:
        return None

def save_to_cache(video_id: str, file_id: str, title: str):
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO cache (video_id, file_id, title) VALUES (?, ?, ?)",
                       (video_id, file_id, title))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Ошибка сохранения в cache: {e}")

main_keyboard = ReplyKeyboardMarkup(
    keyboard=[[
        KeyboardButton(text="🎵 Скачать музыку"),
        KeyboardButton(text="📊 Top 20"),
        KeyboardButton(text="ℹ️ О боте")
    ]],
    resize_keyboard=True
)

inline_keyboard = InlineKeyboardMarkup(
    inline_keyboard=[[InlineKeyboardButton(text="🔄 Скачать еще песню", callback_data="download_more")]]
)

def clean_filename(title: str) -> str:
    cleaned = re.sub(r'[\\/*?:"<>|]', "", title).strip()
    return cleaned if cleaned else "Audio"

def download_youtube_audio(url: str, output_path: str):
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': f'{output_path}/%(id)s.%(ext)s',
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
        'noplaylist': True,
        'socket_timeout': 15,
        'retries': 5,
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'ios', 'web'],
                'skip': ['hls', 'dash']
            }
        }
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)
        video_id = info.get('id')
        title = clean_filename(info.get('title', 'Audio'))
        return filename, video_id, title

@dp.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        "👋 Привет! Добро пожаловать в быстрый бот-конвертер.\n\n"
        "Отправь мне ссылку на YouTube, и я мгновенно превращу её в трек!",
        reply_markup=main_keyboard
    )

@dp.message(F.text == "🎵 Скачать музыку")
async def menu_download(message: Message):
    await message.answer("Просто отправь мне ссылку на YouTube!")

@dp.message(F.text == "📊 Top 20")
async def show_top_20(message: Message):
    top_data = get_top_users()
    if not top_data:
        await message.answer("📊 Список пока пуст.")
        return

    text = "🏆 **TOP 20 Скачавших музыку**\n\n"
    for index, (username, count) in enumerate(top_data, start=1):
        medal = "🥇" if index == 1 else "🥈" if index == 2 else "🥉" if index == 3 else f"`{index}.`"
        user_display = f"@{username}" if username else "Аноним"
        text += f"{medal} {user_display} — {count} треков\n"

    await message.answer(text, parse_mode="Markdown")

@dp.message(F.text == "ℹ️ О боте")
async def menu_about(message: Message):
    await message.answer(
        "🤖 **Этот бот скачивает аудио с YouTube**\n\n"
        "• Скорость: Максимально оптимизирована\n"
        "• Кэширование: Включено"
    )

@dp.callback_query(F.data == "download_more")
async def process_download_more(callback: CallbackQuery):
    await callback.message.answer("Отправь мне еще одну ссылку на YouTube!")
    await callback.answer()

@dp.message(F.text.contains("youtube.com") | F.text.contains("youtu.be"))
async def handle_youtube_link(message: Message):
    url = message.text.strip()
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name

    video_id_match = re.search(r'(?:v=|\/|vi=|^)([0-9A-Za-z_-]{11})', url)
    video_id = video_id_match.group(1) if video_id_match else None

    if video_id:
        cached_data = get_cached_video(video_id)
        if cached_data:
            cached_file_id, cached_title = cached_data
            try:
                await bot.send_chat_action(message.chat.id, "upload_voice")
                await message.answer_audio(audio=cached_file_id, title=cached_title, reply_markup=inline_keyboard)
                log_user_download(user_id, username)
                return
            except Exception:
                pass

    status_message = await message.answer("🔍 Պատրաստում եմ...")
    output_dir = "downloads"
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    try:
        await bot.send_chat_action(message.chat.id, "upload_voice")
        loop = asyncio.get_event_loop()
        filename, downloaded_id, title = await loop.run_in_executor(
            None, download_youtube_audio, url, output_dir
        )

        if os.path.exists(filename):
            await status_message.edit_text("📤 Ուղարկվում է Telegram...")
            audio_file = FSInputFile(filename, filename=f"{title}.m4a")
            sent_audio = await message.answer_audio(audio=audio_file, title=title, reply_markup=inline_keyboard)
            
            log_user_download(user_id, username)
            if downloaded_id:
                save_to_cache(downloaded_id, sent_audio.audio.file_id, title)
            
            os.remove(filename)
            await status_message.delete()
        else:
            await status_message.edit_text("❌ Չհաջողվեց ներբեռնել ֆայլը։")
    except Exception as e:
        print(f"Ошибка: {e}")
        await status_message.edit_text("⚠️ Տեղի ունեցավ սխալ: YouTube-ը արգելափակում է ներբեռնումը:")

# ⚡ Webhook-ի կարգավորում
async def on_startup(bot: Bot) -> None:
    if BASE_WEBHOOK_URL:
        webhook_url = f"{BASE_WEBHOOK_URL}{WEBHOOK_PATH}"
        await bot.delete_webhook(drop_pending_updates=True) # Մաքրում ենք նախորդ հարցումները
        await bot.set_webhook(webhook_url)
        print(f"🚀 Webhook-ը հաջողությամբ միացավ: {webhook_url}")

def main():
    app = web.Application()
    webhook_requests_handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
    webhook_requests_handler.register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)
    
    dp.startup.register(on_startup)
    
    web.run_app(app, host=WEB_SERVER_HOST, port=WEB_SERVER_PORT)

if __name__ == "__main__":
    main()
