import os
import static_ffmpeg
static_ffmpeg.add_paths()
import asyncio
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.types import FSInputFile
from yt_dlp import YoutubeDL

logging.basicConfig(level=logging.INFO)

TOKEN = "8638601182:AAHAOf2wvybOOyhyt_PNijYkKkljJwGnN-g"

bot = Bot(token=TOKEN)
dp = Dispatcher()

MAX_FILE_SIZE = 50 * 1024 * 1024 
sc_cache = {}

COMMON_OPTS = {
    'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
    'quiet': True,
    'no_warnings': True,
}

def main_menu():
    builder = ReplyKeyboardBuilder()
    builder.button(text="🎬 Скачать Видео (TT/Insta)")
    builder.button(text="🎵 Музыка (SoundCloud)")
    builder.adjust(1)
    return builder.as_markup(resize_keyboard=True)

def search_sc(query):
    with YoutubeDL(COMMON_OPTS) as ydl:
        res = ydl.extract_info(f"scsearch5:{query}", download=False)
        return res.get('entries', [])

def sync_download(url, mode):
    if not os.path.exists('downloads'): os.makedirs('downloads')
    opts = {**COMMON_OPTS, 'outtmpl': 'downloads/%(id)s.%(ext)s'}
    if mode == 'audio':
        opts.update({'format': 'bestaudio/best', 'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}]})
    else:
        opts['format'] = 'best[ext=mp4]/best'
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        file_path = ydl.prepare_filename(info)
        if mode == 'audio': file_path = os.path.splitext(file_path)[0] + ".mp3"
        return file_path, info.get('title', 'Без названия')

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("Здарова! Я качаю контент.\nВ группах используй /music [название] для поиска.", reply_markup=main_menu())

# Поиск через команду /music (для групп)
@dp.message(Command("music"))
async def music_command(message: types.Message, command: CommandObject):
    if not command.args:
        return await message.answer("Напиши название после команды, например: `/music Король и Шут`", parse_mode="Markdown")
    
    await process_music_search(message, command.args)
    # Удаляем команду пользователя, чтобы не засорять чат
    if message.chat.type != 'private':
        try: await message.delete()
        except: pass

@dp.message(F.text.startswith(("http://", "https://")))
async def handle_links(message: types.Message):
    text = message.text
    if "soundcloud.com" in text:
        await start_download(message, text, "audio")
    elif any(domain in text for domain in ["tiktok.com", "instagram.com"]):
        await start_download(message, text, "video")

@dp.message(F.text)
async def handle_text_logic(message: types.Message):
    # Если это кнопки меню
    if message.text == "🎬 Скачать Видео (TT/Insta)":
        return await message.answer("Присылай ссылку на ТикТок или Инсту! 📱")
    if message.text == "🎵 Музыка (SoundCloud)":
        return await message.answer("Присылай ссылку на SoundCloud или просто напиши название (только в личке). 🎵")

    # В личке ищем музыку по обычному тексту, в группах — игнорируем (там только /music)
    if message.chat.type == 'private':
        await process_music_search(message, message.text)

async def process_music_search(message, query):
    wait = await message.answer("🔍 Ищу треки...")
    try:
        results = await asyncio.to_thread(search_sc, query)
        if not results:
            return await wait.edit_text("Ничего не нашел.")
            
        builder = InlineKeyboardBuilder()
        for entry in results:
            t_id, t_url = entry.get('id'), entry.get('webpage_url')
            if t_id and t_url:
                sc_cache[t_id] = t_url
                title = (entry.get('title')[:45] + '..') if len(entry.get('title')) > 45 else entry.get('title')
                builder.row(types.InlineKeyboardButton(text=f"🎵 {title}", callback_data=f"sc_{t_id}"))
        
        await message.answer("Выбери трек:", reply_markup=builder.as_markup())
        await wait.delete()
    except Exception as e:
        await wait.edit_text(f"Ошибка поиска: {e}")

async def start_download(message: types.Message, url, mode):
    status = await message.answer("⏳ Скачиваю...")
    file_path = None
    try:
        file_path, title = await asyncio.to_thread(sync_download, url, mode)
        if os.path.getsize(file_path) > MAX_FILE_SIZE:
            await status.edit_text("❌ Файл больше 50МБ.")
            return await asyncio.sleep(3), await status.delete()

        await status.edit_text("📤 Отправляю...")
        if mode == 'video': await message.answer_video(FSInputFile(file_path), caption=f"✅ {title}")
        else: await message.answer_audio(FSInputFile(file_path), title=title)
        await status.delete()
        # В группах удаляем и ссылку пользователя после успешной отправки
        if message.chat.type != 'private':
            try: await message.delete()
            except: pass
    except Exception as e:
        await status.edit_text(f"❌ Ошибка")
        await asyncio.sleep(3), await status.delete()
    finally:
        if file_path and os.path.exists(file_path): os.remove(file_path)

@dp.callback_query(F.data.startswith("sc_"))
async def callback_download(callback: types.CallbackQuery):
    url = sc_cache.get(callback.data.split("_")[1])
    if not url: return await callback.answer("Ошибка ссылки", show_alert=True)
    await callback.answer()
    await callback.message.delete()
    await start_download(callback.message, url, "audio")

async def main():
    if not os.path.exists('downloads'): os.makedirs('downloads')
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
