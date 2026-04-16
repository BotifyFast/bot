import os
import static_ffmpeg
static_ffmpeg.add_paths()
import asyncio
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.types import FSInputFile
from yt_dlp import YoutubeDL

# Логирование
logging.basicConfig(level=logging.INFO)

# ТОКЕН
TOKEN = "8638601182:AAHAOf2wvybOOyhyt_PNijYkKkljJwGnN-g"

bot = Bot(token=TOKEN)
dp = Dispatcher()

# Лимит 50 МБ
MAX_FILE_SIZE = 50 * 1024 * 1024 
sc_cache = {}

COMMON_OPTS = {
    'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
    'quiet': True,
    'no_warnings': True,
}

# --- КЛАВИАТУРА ---
def main_menu():
    builder = ReplyKeyboardBuilder()
    builder.button(text="🎬 Скачать Видео (TT/Insta)")
    builder.button(text="🎵 Музыка (SoundCloud)")
    builder.adjust(1)
    return builder.as_markup(resize_keyboard=True)

# --- ФУНКЦИИ СКАЧИВАНИЯ ---
def search_sc(query):
    with YoutubeDL(COMMON_OPTS) as ydl:
        res = ydl.extract_info(f"scsearch5:{query}", download=False)
        return res.get('entries', [])

def sync_download(url, mode):
    # Создаем папку, если её нет
    if not os.path.exists('downloads'): os.makedirs('downloads')
    
    opts = {
        **COMMON_OPTS,
        'outtmpl': 'downloads/%(id)s.%(ext)s',
    }
    if mode == 'audio':
        opts['format'] = 'bestaudio/best'
        opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }]
    else:
        opts['format'] = 'best[ext=mp4]/best'

    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        file_path = ydl.prepare_filename(info)
        if mode == 'audio':
            # yt-dlp меняет расширение после конвертации в mp3
            file_path = os.path.splitext(file_path)[0] + ".mp3"
        return file_path, info.get('title', 'Без названия')

# --- ОБРАБОТЧИКИ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    welcome_text = (
        f"Здарова, {message.from_user.first_name}! 👋\n\n"
        "Этот бот качает видосы и музыку.\n"
        "🚀 **Что я умею:**\n"
        "— TikTok и Instagram (Reels)\n"
        "— SoundCloud (по ссылке или названию)\n\n"
        "Всё лишнее удаляю сразу после отправки! 🧹"
    )
    await message.answer(welcome_text, reply_markup=main_menu())

@dp.message(F.text == "🎬 Скачать Видео (TT/Insta)")
async def video_btn_handler(message: types.Message):
    await message.answer("Присылай ссылку на ТикТок или Инстаграм! 📱")

@dp.message(F.text == "🎵 Музыка (SoundCloud)")
async def music_btn_handler(message: types.Message):
    await message.answer("Присылай ссылку на SoundCloud или название песни! 🎵")

@dp.message(F.text)
async def handle_message(message: types.Message):
    text = message.text
    if text.startswith(("http://", "https://")):
        if "soundcloud.com" in text:
            await start_download(message, text, "audio")
        elif any(domain in text for domain in ["tiktok.com", "instagram.com"]):
            await start_download(message, text, "video")
        else:
            await message.answer("❌ Эту ссылку я не поддерживаю.")
    else:
        wait = await message.answer("🔍 Ищу в SoundCloud...")
        try:
            results = await asyncio.to_thread(search_sc, text)
            if not results:
                await wait.edit_text("Ничего не нашел.")
                return
            builder = InlineKeyboardBuilder()
            for entry in results:
                t_id, t_url = entry.get('id'), entry.get('webpage_url')
                if t_id and t_url:
                    sc_cache[t_id] = t_url
                    title = (entry.get('title')[:45] + '..') if len(entry.get('title')) > 45 else entry.get('title')
                    builder.row(types.InlineKeyboardButton(text=f"🎵 {title}", callback_data=f"sc_{t_id}"))
            await wait.delete()
            await message.answer("Выбери трек:", reply_markup=builder.as_markup())
        except Exception as e:
            await wait.edit_text(f"Ошибка поиска: {e}")

async def start_download(message: types.Message, url, mode):
    status = await message.answer("⏳ Качаю...")
    file_path = None
    try:
        file_path, title = await asyncio.to_thread(sync_download, url, mode)
        
        # Проверка на существование и размер
        if not os.path.exists(file_path):
            raise Exception("Файл не найден после скачивания.")
            
        if os.path.getsize(file_path) > MAX_FILE_SIZE:
            await status.edit_text("❌ Файл больше 50МБ. Railway такое не пропустит.")
            return

        await status.edit_text("📤 Отправляю...")
        if mode == 'video':
            await message.answer_video(FSInputFile(file_path), caption=f"✅ {title}")
        else:
            await message.answer_audio(FSInputFile(file_path), title=title)
        
        await status.delete()

    except Exception as e:
        logging.error(f"Ошибка: {e}")
        await status.edit_text(f"❌ Ошибка: {str(e)[:100]}")
    
    finally:
        # ГЛАВНОЕ: Чистим место на сервере ВСЕГДА
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
            logging.info(f"Файл {file_path} удален с сервера.")

@dp.callback_query(F.data.startswith("sc_"))
async def callback_download(callback: types.CallbackQuery):
    track_id = callback.data.split("_")[1]
    url = sc_cache.get(track_id)
    if not url:
        await callback.answer("Ошибка, попробуй поиск заново", show_alert=True)
        return
    await callback.answer()
    await start_download(callback.message, url, "audio")

async def main():
    if not os.path.exists('downloads'): os.makedirs('downloads')
    print("Бот запущен и готов к работе!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
