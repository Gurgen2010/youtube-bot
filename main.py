import os
import asyncio
import sqlite3
import re
import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, FSInputFile, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart

API_TOKEN = '8571888062:AAFIb3QBtYw-N27mlqVmbp_fKBQikeQz9u8'

# Render-ում սովորական Bot (առանց proxy-ի)
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

DB_FILE = "songs_cache.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('CREATE TABLE IF NOT EXISTS cache (video_id TEXT PRIMARY KEY, file_id TEXT NOT NULL, title TEXT NOT NULL)')
    cursor.execute('CREATE TABLE IF NOT EXISTS stats (user_id INTEGER PRIMARY KEY, username TEXT, download_count INTEGER DEFAULT 0)')
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
            cursor.execute("UPDATE stats SET download_count = download_count + 1, username = ? WHERE user_id = ?", (username, user_id))
        else:
            cursor.execute("INSERT INTO stats (user_id, username, download_count) VALUES (?, ?, 1)", (user_id, username))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Db error: {e}")

def get_top_users():
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT username, download_count FROM stats ORDER BY download_count DESC LIMIT 20")
        rows = cursor.fetchall()
        conn.close()
        return rows
    except Exception:
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
        cursor.execute("INSERT OR REPLACE INTO cache (video_id, file_id, title) VALUES (?, ?, ?)", (video_id, file_id, title))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Cache error: {e}")

main_keyboard = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="🎵 Скачать музыку"), KeyboardButton(text="📊 Top 20"), KeyboardButton(text="ℹ️ О боте")]],
    resize_keyboard=True
)

inline_keyboard = InlineKeyboardMarkup(
    inline_keyboard=[[InlineKeyboardButton(text="🔄 Скачать еще песню", callback_data="download_more")]]
)

def clean_filename(title: str) -> str:
    cleaned = re.sub(r'[\\/*?:"<>|]', "", title).strip()
    return cleaned if cleaned else "Audio"

async def fetch_youtube_audio(url: str, output_path: str, video_id: str):
    api_url = "https://api.cobalt.tools/api/json"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    payload = {
        "url": url,
        "downloadMode": "audio",
        "audioFormat": "mp3"
    }

    async with aiohttp.ClientSession() as http_session:
        async with http_session.post(api_url, json=payload, headers=headers, timeout=30) as resp:
            data = await resp.json()
            if "url" not in data:
                raise Exception("Не удалось получить ссылку на скачивание.")
            download_link = data["url"]

        file_path = os.path.join(output_path, f"{video_id}.mp3")
        
        async with http_session.get(download_link, timeout=120) as audio_resp:
            if audio_resp.status == 200:
                with open(file_path, "wb") as f:
                    f.write(await audio_resp.read())
                title = "Audio Track"
                return file_path, title
            else:
                raise Exception("Ошибка при загрузке аудиофайла.")

@dp.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer("👋 Привет! Отправь мне ссылку на YouTube!", reply_markup=main_keyboard)

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
    await message.answer("🤖 **Этот бот скачивает аудио с YouTube**")

@dp.message(F.text.contains("youtube.com") | F.text.contains("youtu.be"))
async def handle_youtube_link(message: Message):
    url = message.text.strip()
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name

    video_id_match = re.search(r'(?:v=|\/)([0-9A-Za-z_-]{11})', url)
    video_id = video_id_match.group(1) if video_id_match else None

    if not video_id:
        await message.answer("❌ Неверная ссылка YouTube.")
        return

    cached_data = get_cached_video(video_id)
    if cached_data:
        cached_file_id, cached_title = cached_data
        try:
            await message.answer_audio(audio=cached_file_id, title=cached_title, reply_markup=inline_keyboard)
            log_user_download(user_id, username)
            return
        except Exception:
            pass

    status_message = await message.answer("🔍 Պատրաստում եմ...")
    download_dir = "downloads"
    os.makedirs(download_dir, exist_ok=True)

    try:
        audio_path, real_title = await fetch_youtube_audio(url, download_dir, video_id)
        if not os.path.exists(audio_path):
            raise FileNotFoundError("Файл не найден.")

        audio_file = FSInputFile(audio_path, filename=f"{real_title}.mp3")
        sent_audio = await message.answer_audio(audio=audio_file, title=real_title, reply_markup=inline_keyboard)

        telegram_file_id = sent_audio.audio.file_id
        save_to_cache(video_id, telegram_file_id, real_title)
        log_user_download(user_id, username)

        if os.path.exists(audio_path):
            os.remove(audio_path)

        await status_message.delete()

    except Exception as e:
        print(f"Error details: {e}")
        await status_message.edit_text("❌ Ошибка при обработке ссылки.")

@dp.callback_query(F.data == "download_more")
async def process_download_more(callback: CallbackQuery):
    await callback.message.answer("Жду твою новую ссылку!")
    await callback.answer()

async def main():
    while True:
        try:
            await bot.delete_webhook(drop_pending_updates=True)
            print("🚀 Бոտը պատրաստ է...")
            await dp.start_polling(bot)
            break
        except Exception as e:
            print(f"Error: {e}")
            await asyncio.sleep(3)

if __name__ == '__main__':
    asyncio.run(main())
