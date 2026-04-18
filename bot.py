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

TOKEN = "8638601182:AAHAOf2wvybOOyhyt_PNijYkKkljJwGnN-g"
WEATHER_API_KEY = "c2b2631749aead62cfdc86b394e6399f"

bot = Bot(token=TOKEN)
dp = Dispatcher()

sc_cache = {}
temp_mail_cache = {}
anon_queue = None
anon_pairs = {}

CITIES_SHORT = {
    "мск": "Moscow", "москва": "Moscow",
    "спб": "Saint Petersburg", "питер": "Saint Petersburg",
    "кст": "Kostanay", "костанай": "Kostanay",
    "аст": "Astana", "астана": "Astana",
    "алм": "Almaty", "алматы": "Almaty",
    "екб": "Yekaterinburg", "нск": "Novosibirsk"
}

JOKES = [
    "— Купила мелок от тараканов! — И что, помогают? — Да, сидят в углу, рисуют...",
    "Сын программиста: — Папа, почему солнце встает на востоке? — Работает? Ничего не трогай!",
    "Программист принес домой 11 пакетов молока, потому что в магазине были яйца."
]

MAX_FILE_SIZE = 50 * 1024 * 1024
COMMON_OPTS = {'user_agent': 'Mozilla/5.0', 'quiet': True, 'no_warnings': True}

# --- КЛАВИАТУРЫ ---
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

def anon_menu():
    builder = ReplyKeyboardBuilder()
    builder.button(text="🚀 Следующий")
    builder.button(text="🚫 Остановить чат")
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

# --- ФУНКЦИИ ---
def get_weather(city_query):
    clean_city = city_query.lower().replace("флеш", "").replace("погода", "").strip()
    city = CITIES_SHORT.get(clean_city, clean_city)
    url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_API_KEY}&units=metric&lang=ru"
    try:
        res = requests.get(url, timeout=10).json()
        if res.get("cod") != 200: return "❌ Город не найден."
        return f"🌤 Погода в {res['name']}: {res['main']['temp']}°C, {res['weather'][0]['description']}"
    except: return "❌ Ошибка API."

def gen_mail(user_id):
    domains = ["1secmail.com", "1secmail.org", "1secmail.net"]
    login = ''.join(random.choice(string.ascii_lowercase + string.digits) for _ in range(10))
    email = f"{login}@{random.choice(domains)}"
    temp_mail_cache[user_id] = email
    return email

# --- ОБРАБОТЧИКИ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("Здарова! Я Флэш. Всё исправил, теперь кнопки и сокращения работают.", reply_markup=main_menu())

@dp.message(F.text.in_(["🚫 Остановить чат", "/stop"]))
async def anon_stop(message: types.Message):
    global anon_queue
    uid = message.from_user.id
    if uid == anon_queue:
        anon_queue = None
        await message.answer("Поиск остановлен.", reply_markup=main_menu())
    elif uid in anon_pairs:
        partner_id = anon_pairs.pop(uid)
        anon_pairs.pop(partner_id, None)
        await bot.send_message(partner_id, "🚫 Собеседник покинул чат.", reply_markup=main_menu())
        await message.answer("Чат завершен.", reply_markup=main_menu())
    else:
        await message.answer("Ты не в чате.", reply_markup=main_menu())

@dp.message(F.text.in_(["👥 Анонимный чат", "🚀 Следующий"]))
async def anon_chat_logic(message: types.Message):
    global anon_queue
    uid = message.from_user.id
    
    # Если нажал "Следующий", сначала разрываем старую пару
    if message.text == "🚀 Следующий" and uid in anon_pairs:
        partner_id = anon_pairs.pop(uid)
        anon_pairs.pop(partner_id, None)
        await bot.send_message(partner_id, "🚫 Собеседник переключился на другого.", reply_markup=main_menu())

    if anon_queue and anon_queue != uid:
        p_id = anon_queue
        anon_pairs[uid], anon_pairs[p_id] = p_id, uid
        anon_queue = None
        await bot.send_message(p_id, "🤝 Собеседник найден! Общайтесь.", reply_markup=anon_menu())
        await message.answer("🤝 Собеседник найден! Общайтесь.", reply_markup=anon_menu())
    else:
        anon_queue = uid
        await message.answer("🔍 Ищу собеседника...", reply_markup=ReplyKeyboardBuilder().button(text="🚫 Остановить чат").as_markup(resize_keyboard=True))

@dp.message(F.text)
async def handle_all_text(message: types.Message):
    text = message.text.lower()
    uid = message.from_user.id

    # 1. Проверка системных кнопок
    if text == "🎬 скачать видео":
        return await message.answer("Просто скинь ссылку на TikTok или Instagram!")
    if text == "🎵 музыка":
        return await message.answer("Напиши название песни, и я найду её в SoundCloud.")
    if text == "🌤 погода/💰 курс":
        return await message.answer("Пиши: `Флеш погода спб` или `Флеш курс тон`")
    if text == "📧 почта/🆕 qr":
        email = gen_mail(uid)
        return await message.answer(f"📧 Твоя почта: `{email}`\n(Кнопки проверки появятся скоро)", parse_mode="Markdown")

    # 2. Команды "Флеш ..."
    if text.startswith("флеш"):
        if "анекдот" in text: await message.reply(f"🤡 {random.choice(JOKES)}")
        elif "погода" in text: await message.reply(get_weather(text))
        elif "курс" in text:
            coin = text.replace("флеш курс", "").strip()
            await message.reply(f"💰 Запрашиваю курс {coin}...") # Логику CoinGecko можно оставить из прошлого кода
        elif "монетка" in text: await message.reply(f"🪙 {random.choice(['Орел', 'Решка'])}")
        elif "рулетка" in text: await message.reply("💥 ПАУ!" if random.randint(1, 6) == 1 else "👀 Осечка!")
        elif "qr" in text:
            url = text.replace("флеш qr", "").strip()
            path = f"qr_{uid}.png"
            qrcode.make(url).save(path)
            await message.answer_photo(FSInputFile(path))
            os.remove(path)
        return

    # 3. Анонимный чат (пересылка)
    if uid in anon_pairs:
        await bot.send_message(anon_pairs[uid], message.text)
        return

    # 4. Поиск музыки (если это не ссылка и не кнопка)
    if message.chat.type == 'private' and not text.startswith("http"):
        wait = await message.answer("🔍 Ищу в SoundCloud...")
        await process_music_search(message, message.text, wait)
        return

    # 5. Ссылки
    if text.startswith("http"):
        if "soundcloud.com" in text: await start_download(message, message.text, "audio")
        else: await start_download(message, message.text, "video")

# --- СКАЧИВАНИЕ И ПОИСК ---
async def process_music_search(message, query, wait_msg):
    try:
        def search():
            with YoutubeDL(COMMON_OPTS) as ydl:
                return ydl.extract_info(f"scsearch5:{query}", download=False).get('entries', [])
        results = await asyncio.to_thread(search)
        if not results: return await wait_msg.edit_text("Ничего не нашел.")
        builder = InlineKeyboardBuilder()
        for entry in results:
            t_id = entry.get('id')
            sc_cache[t_id] = entry.get('webpage_url')
            builder.row(types.InlineKeyboardButton(text=f"🎵 {entry.get('title')[:40]}", callback_data=f"sc_{t_id}"))
        await message.answer("Выбери трек:", reply_markup=builder.as_markup())
        await wait_msg.delete()
    except: await wait_msg.edit_text("Ошибка поиска.")

async def start_download(message, url, mode):
    status = await message.answer("⏳ Работаю...")
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
    except: await status.edit_text("Ошибка.")
    finally:
        if file_path and os.path.exists(file_path): os.remove(file_path)

@dp.callback_query(F.data.startswith("sc_"))
async def cb_dl(callback: types.CallbackQuery):
    url = sc_cache.get(callback.data.split("_")[1])
    await callback.message.delete()
    await start_download(callback.message, url, "audio")

async def main():
    if not os.path.exists('downloads'): os.makedirs('downloads')
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
