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

# --- КОНФИГ ---
TOKEN = "8638601182:AAHAOf2wvybOOyhyt_PNijYkKkljJwGnN-g"
WEATHER_API_KEY = "c2b2631749aead62cfdc86b394e6399f"

bot = Bot(token=TOKEN)
dp = Dispatcher()

# Кэши и состояния
sc_cache = {}
anon_queue = None
anon_pairs = {}
temp_mail_cache = {}

# Города
CITIES_SHORT = {
    "мск": "Moscow", "спб": "Saint Petersburg", "питер": "Saint Petersburg",
    "кст": "Kostanay", "костанай": "Kostanay", "аст": "Astana", 
    "алм": "Almaty", "екб": "Yekaterinburg", "нск": "Novosibirsk"
}

# Анекдоты (Все категории)
JOKES = [
    "Программист принес домой 11 пакетов молока, потому что в магазине были яйца.",
    "— Купила мелок от тараканов! — И что, помогают? — Да, сидят в углу, рисуют...",
    "Штирлиц шел по Берлину. Что-то выдавало в нем советского разведчика: то ли волевой взгляд, то ли парашют за спиной.",
    "Гаишник останавливает машину: — Почему глаза красные? — Три дня не спал! — Не оправдывайтесь, дыхните!",
    "Доктор, у меня депрессия. — Сходите в цирк к клоуну Пальяччи. — Но доктор, я и есть Пальяччи.",
    "Вовочка, почему ты не в классе? — Учительница сказала, что я дурак. А я ей: 'Кто обзывается, тот сам так называется!'"
]

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

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
def get_weather(city_query):
    clean_city = city_query.lower().replace("флеш", "").replace("погода", "").strip()
    city = CITIES_SHORT.get(clean_city, clean_city)
    url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_API_KEY}&units=metric&lang=ru"
    try:
        res = requests.get(url, timeout=10).json()
        if res.get("cod") != 200: return f"❌ Город '{clean_city}' не найден."
        return f"🌤 Погода в {res['name']}: {res['main']['temp']}°C, {res['weather'][0]['description']}"
    except: return "❌ Ошибка API погоды."

def get_crypto(coin_query):
    coin = coin_query.lower().replace("флеш", "").replace("курс", "").strip()
    mapping = {"биток": "bitcoin", "эфир": "ethereum", "тон": "the-open-network", "ton": "the-open-network"}
    c_id = mapping.get(coin, coin)
    try:
        res = requests.get(f"https://api.coingecko.com/api/v3/simple/price?ids={c_id}&vs_currencies=usd").json()
        return f"💰 Курс {coin.capitalize()}: ${res[c_id]['usd']}"
    except: return "❌ Не нашел валюту."

# --- ОБРАБОТЧИКИ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("Здарова! Я — Флэш. Я умею всё: качать видео, искать музыку, распознавать текст и даже анонимно болтать!", reply_markup=main_menu())

@dp.message(F.text.in_(["🚫 Остановить чат", "/stop"]))
async def anon_stop(message: types.Message):
    global anon_queue
    uid = message.from_user.id
    if uid in anon_pairs:
        p_id = anon_pairs.pop(uid)
        anon_pairs.pop(p_id, None)
        await bot.send_message(p_id, "🚫 Собеседник покинул чат.", reply_markup=main_menu())
        await message.answer("Чат завершен.", reply_markup=main_menu())
    elif uid == anon_queue:
        anon_queue = None
        await message.answer("Поиск остановлен.", reply_markup=main_menu())

@dp.message(F.text.in_(["👥 Анонимный чат", "🚀 Следующий"]))
async def anon_logic(message: types.Message):
    global anon_queue
    uid = message.from_user.id
    if message.chat.type != 'private': return await message.reply("❌ Анонимный чат только в личке!")
    
    if message.text == "🚀 Следующий" and uid in anon_pairs:
        p_id = anon_pairs.pop(uid)
        anon_pairs.pop(p_id, None)
        await bot.send_message(p_id, "🚫 Собеседник переключился.", reply_markup=main_menu())

    if anon_queue and anon_queue != uid:
        p_id = anon_queue
        anon_pairs[uid], anon_pairs[p_id] = p_id, uid
        anon_queue = None
        await bot.send_message(p_id, "🤝 Собеседник найден!", reply_markup=anon_menu())
        await message.answer("🤝 Собеседник найден!", reply_markup=anon_menu())
    else:
        anon_queue = uid
        await message.answer("🔍 Ищу собеседника...", reply_markup=ReplyKeyboardBuilder().button(text="🚫 Остановить чат").as_markup(resize_keyboard=True))

@dp.message(F.photo)
async def handle_photo(message: types.Message):
    status = await message.answer("📥 Считываю текст с фото...")
    file_info = await bot.get_file(message.photo[-1].file_id)
    path = f"downloads/{file_info.file_id}.jpg"
    await bot.download_file(file_info.file_path, path)
    try:
        text = pytesseract.image_to_string(Image.open(path), lang='rus+eng')
        await message.reply(f"📝 Текст с фото:\n\n`{text[:3000]}`" if text.strip() else "❌ Не нашел текст.")
    except: await message.reply("❌ Ошибка OCR. Проверь Tesseract на сервере.")
    finally:
        if os.path.exists(path): os.remove(path)
        await status.delete()

@dp.message(F.text)
async def handle_all(message: types.Message):
    text = message.text.lower()
    uid = message.from_user.id

    # 1. Кнопки
    if text == "🎬 скачать видео": return await message.answer("Кидай ссылку на TikTok или Instagram!")
    if text == "🎵 музыка": return await message.answer("Пиши: `Флеш музыка [название]`")
    if text == "🌤 погода/💰 курс": return await message.answer("Пиши: `Флеш погода спб` или `Флеш курс тон`.")
    if text == "📧 почта/🆕 qr": 
        login = ''.join(random.choice(string.ascii_lowercase) for _ in range(8))
        return await message.answer(f"📧 Твоя почта: `{login}@1secmail.com`\n\nИли пиши: `Флеш qr [ссылка]`")

    # 2. Команды "Флеш ..." (Работают в группах)
    if text.startswith("флеш"):
        if "команды" in text:
            return await message.reply("⚡️ Команды: `погода`, `курс`, `музыка`, `анекдот`, `qr`, `монетка`, `рулетка`.")
        elif "музыка" in text:
            query = text.replace("флеш музыка", "").strip()
            wait = await message.answer(f"🔍 Ищу '{query}'...")
            return await process_music_search(message, query, wait)
        elif "анекдот" in text: return await message.reply(f"🤡 {random.choice(JOKES)}")
        elif "погода" in text: return await message.reply(get_weather(text))
        elif "курс" in text: return await message.reply(get_crypto(text))
        elif "монетка" in text: return await message.reply(f"🪙 {random.choice(['Орел', 'Решка'])}")
        elif "рулетка" in text: return await message.reply("💥 ПАУ!" if random.randint(1, 6) == 1 else "👀 Осечка!")
        elif "qr" in text:
            url = text.replace("флеш qr", "").strip()
            path = f"qr_{uid}.png"
            qrcode.make(url).save(path)
            await message.answer_photo(FSInputFile(path))
            return os.remove(path)

    # 3. Анонимный чат
    if uid in anon_pairs and message.chat.type == 'private':
        return await bot.send_message(anon_pairs[uid], message.text)

    # 4. Ссылки
    if text.startswith("http"):
        mode = "audio" if "soundcloud.com" in text else "video"
        return await start_download(message, message.text, mode)

# --- ЛОГИКА ЗАГРУЗКИ ---
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
    status = await message.answer("⏳ Загружаю...")
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
