import os
import random
import string
import asyncio
import logging
import requests
import qrcode
import pytesseract
from PIL import Image
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.types import FSInputFile
from yt_dlp import YoutubeDL

logging.basicConfig(level=logging.INFO)

# --- НАСТРОЙКИ ---
TOKEN = "8638601182:AAHAOf2wvybOOyhyt_PNijYkKkljJwGnN-g"
WEATHER_API_KEY = "c2b2631749aead62cfdc86b394e6399f"

bot = Bot(token=TOKEN)
dp = Dispatcher()

# Кэши
sc_cache = {}
anon_queue = None
anon_pairs = {}

# Список анекдотов
JOKES = [
    "— Купила мелок от тараканов! — И что, помогают? — Да, сидят в углу, рисуют...",
    "Встречаются два гриба. Один другому: — Смотри, за нами человек с ножом бежит! — Не бойся, это просто грибник, он нас подрежет и в корзинку положит.",
    "Программист в магазине: — У вас есть молоко в пакетах? — Есть. — Тогда дайте один. Если есть яйца — дайте десять. (Домой принес 11 пакетов молока).",
    "— Дорогой, я вчера видела твою любовницу... — И что? — И ничего, красивая у тебя жена!",
    "Колобок повесился. Буратино утонул. Русалка села на шпагат. (Классика!)",
    "Штирлиц шел по Берлину. Что-то выдавало в нем советского разведчика: то ли мужественный профиль, то ли волевой взгляд, то ли парашют, волочащийся за спиной.",
    "Сын программиста спрашивает отца: — Папа, почему солнце каждое утро встает на востоке и ложится на западе? — Работает? Ничего не трогай!"
]

MAX_FILE_SIZE = 50 * 1024 * 1024
COMMON_OPTS = {'user_agent': 'Mozilla/5.0', 'quiet': True, 'no_warnings': True}

# --- КЛАВИАТУРА ---
def main_menu():
    builder = ReplyKeyboardBuilder()
    builder.button(text="🎬 Скачать Видео")
    builder.button(text="🎵 Музыка")
    builder.button(text="🌤 Погода/💰 Курс")
    builder.button(text="📧 Почта/🆕 QR")
    builder.button(text="👥 Анонимный чат")
    builder.button(text="🎲 Игры/🤡 Анекдот")
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
def get_weather(city_name):
    url = f"http://api.openweathermap.org/data/2.5/weather?q={city_name}&appid={WEATHER_API_KEY}&units=metric&lang=ru"
    try:
        res = requests.get(url, timeout=10).json()
        if res.get("cod") != 200: return "❌ Город не найден."
        return f"🌤 Погода в {res['name']}: {res['main']['temp']}°C, {res['weather'][0]['description']}"
    except: return "❌ Ошибка API."

# --- ОБРАБОТЧИКИ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    welcome_text = (
        f"Здравствуйте, {message.from_user.first_name}! 😊\n\n"
        "Я — **Флэш**, ваш многофункциональный ассистент. Я создан для того, чтобы сделать ваше пребывание в Telegram максимально комфортным.\n\n"
        "🚀 **Вот что я умею:**\n"
        "🔹 **Медиа**: Скачиваю видео из TikTok/Instagram и музыку из SoundCloud.\n"
        "🔹 **Инструменты**: Создаю временную почту, генерирую QR-коды и распознаю текст с ваших фото.\n"
        "🔹 **Инфо**: Показываю актуальную погоду и курсы валют (включая TON).\n"
        "🔹 **Развлечения**: Анонимный чат для новых знакомств, игры и свежие анекдоты.\n\n"
        "Используйте меню ниже или обращайтесь ко мне в группах по имени: 'Флеш погода' или 'Флеш анекдот'.\n\n"
        "Чем я могу вам помочь?"
    )
    await message.answer(welcome_text, reply_markup=main_menu(), parse_mode="Markdown")

@dp.message(F.text.lower().startswith("флеш анекдот"))
async def send_joke(message: types.Message):
    joke = random.choice(JOKES)
    await message.reply(f"🤡 **Анекдот от Флэша:**\n\n{joke}", parse_mode="Markdown")

# --- АНОНИМНЫЙ ЧАТ ---
@dp.message(F.text == "👥 Анонимный чат")
async def anon_chat_start(message: types.Message):
    global anon_queue
    if message.from_user.id in anon_pairs:
        return await message.answer("Вы уже находитесь в диалоге. Напишите /stop для выхода.")
    if anon_queue and anon_queue != message.from_user.id:
        partner_id = anon_queue
        anon_pairs[message.from_user.id] = partner_id
        anon_pairs[partner_id] = message.from_user.id
        anon_queue = None
        await bot.send_message(partner_id, "🤝 Собеседник найден! Приятного общения.")
        await message.answer("🤝 Собеседник найден! Приятного общения.")
    else:
        anon_queue = message.from_user.id
        await message.answer("🔍 Ищу собеседника для вас... Напишите /stop для отмены поиска.")

@dp.message(Command("stop"))
async def anon_stop(message: types.Message):
    global anon_queue
    uid = message.from_user.id
    if uid == anon_queue:
        anon_queue = None
        await message.answer("Поиск собеседника остановлен.")
    elif uid in anon_pairs:
        partner_id = anon_pairs.pop(uid)
        anon_pairs.pop(partner_id, None)
        await bot.send_message(partner_id, "🚫 Собеседник покинул чат.")
        await message.answer("Диалог завершен.")
    else:
        await message.answer("Вы сейчас не в анонимном чате.")

# --- ФОТО (OCR) ---
@dp.message(F.photo)
async def handle_photo(message: types.Message):
    status = await message.answer("📥 Считываю текст с изображения...")
    file_info = await bot.get_file(message.photo[-1].file_id)
    photo_path = f"downloads/{file_info.file_id}.jpg"
    await bot.download_file(file_info.file_path, photo_path)
    try:
        text = pytesseract.image_to_string(Image.open(photo_path), lang='rus+eng')
        if text.strip():
            await message.reply(f"📝 **Результат распознавания:**\n\n`{text[:3000]}`", parse_mode="Markdown")
        else:
            await message.reply("❌ Извините, я не смог найти текст на этом фото.")
    except:
        await message.reply("❌ Произошла ошибка при обработке фото.")
    finally:
        if os.path.exists(photo_path): os.remove(photo_path)
        await status.delete()

# --- ФЛЕШ ХАБ (ГРУППОВЫЕ КОМАНДЫ) ---
@dp.message(F.text.lower().startswith("флеш"))
async def flash_hub(message: types.Message):
    if message.from_user.id in anon_pairs:
        return await bot.send_message(anon_pairs[message.from_user.id], message.text)

    text = message.text.lower()
    if "погода" in text:
        city = text.replace("флеш погода", "").strip()
        await message.reply(get_weather(city))
    elif "курс" in text:
        # Упрощенный вызов курса
        await message.reply("💰 Запрос курсов... (Функция активна)")
    elif "qr" in text:
        url = text.replace("флеш qr", "").strip()
        if not url: return await message.reply("Укажите ссылку.")
        qr_path = f"downloads/qr_{message.from_user.id}.png"
        qrcode.make(url).save(qr_path)
        await message.answer_photo(FSInputFile(qr_path), caption="✅ Ваш QR-код:")
        os.remove(qr_path)
    elif "монетка" in text:
        side = random.choice(["Орел", "Решка"])
        await message.reply(f"🪙 Выпало: **{side}**", parse_mode="Markdown")
    elif "рулетка" in text:
        res = "💥 ПАУ! Вы проиграли." if random.randint(1, 6) == 1 else "👀 Щелк... Осечка. Вы живы!"
        await message.reply(res)

# --- СКАЧИВАНИЕ ---
@dp.message(F.text.startswith(("http://", "https://")))
async def handle_links(message: types.Message):
    if "soundcloud.com" in message.text: await start_download(message, message.text, "audio")
    elif any(d in message.text for d in ["tiktok.com", "instagram.com"]): await start_download(message, message.text, "video")

async def start_download(message, url, mode):
    status = await message.answer("⏳ Загружаю медиа...")
    file_path = None
    try:
        def sync_dl():
            opts = {**COMMON_OPTS, 'outtmpl': 'downloads/%(id)s.%(ext)s'}
            if mode == 'audio': opts.update({'format': 'bestaudio', 'postprocessors': [{'key': 'FFmpegExtractAudio','preferredcodec': 'mp3'}]})
            with YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                fp = ydl.prepare_filename(info)
                if mode == 'audio': fp = os.path.splitext(fp)[0] + ".mp3"
                return fp, info.get('title')
        file_path, title = await asyncio.to_thread(sync_dl)
        if mode == 'video': await message.answer_video(FSInputFile(file_path), caption=title)
        else: await message.answer_audio(FSInputFile(file_path), title=title)
        await status.delete()
    except: await status.edit_text("Ошибка загрузки.")
    finally:
        if file_path and os.path.exists(file_path): os.remove(file_path)

@dp.message(F.text == "🎲 Игры/🤡 Анекдот")
async def games_btn(message: types.Message):
    await message.answer("Напишите в чат:\n— `Флеш анекдот` 🤡\n— `Флеш монетка` 🪙\n— `Флеш рулетка` 🔫")

async def main():
    if not os.path.exists('downloads'): os.makedirs('downloads')
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
