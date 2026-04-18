import os
import random
import string
import asyncio
import logging
import requests
import qrcode
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.types import FSInputFile
from yt_dlp import YoutubeDL

logging.basicConfig(level=logging.INFO)

# --- ДАННЫЕ ---
TOKEN = "8638601182:AAHAOf2wvybOOyhyt_PNijYkKkljJwGnN-g"
WEATHER_API_KEY = "c2b2631749aead62cfdc86b394e6399f"

bot = Bot(token=TOKEN)
dp = Dispatcher()

sc_cache = {}
anon_queue = None
anon_pairs = {}

CITIES_SHORT = {
    "мск": "Moscow", "спб": "Saint Petersburg", "питер": "Saint Petersburg",
    "кст": "Kostanay", "костанай": "Kostanay", "аст": "Astana", 
    "алм": "Almaty", "екб": "Yekaterinburg", "нск": "Novosibirsk"
}

JOKES = [
    "Программист принес домой 11 пакетов молока, потому что в магазине были яйца.",
    "Штирлиц шел по Берлину. Что-то выдавало в нем советского разведчика: то ли волевой взгляд, то ли парашют за спиной.",
    "Гаишник: — Почему глаза красные? — Три дня не спал! — Не оправдывайтесь, дыхните!",
    "Доктор, я и есть Пальяччи.",
    "Вовочка: 'Кто обзывается, тот сам так называется!'"
]

# --- ФУНКЦИИ ---
def get_weather(text):
    clean = text.lower().replace("флеш", "").replace("погода", "").strip()
    # Берем первое слово как город, чтобы не мешало "на завтра"
    city_word = clean.split()[0] if clean.split() else ""
    city = CITIES_SHORT.get(city_word, city_word)
    url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_API_KEY}&units=metric&lang=ru"
    try:
        res = requests.get(url, timeout=10).json()
        if res.get("cod") != 200: return f"❌ Город '{city_word}' не найден."
        return f"🌤 В {res['name']}: {res['main']['temp']}°C, {res['weather'][0]['description']}"
    except: return "❌ Ошибка погоды."

def get_exchange(text):
    text = text.lower().replace("флеш", "").replace("курс", "").strip()
    try:
        res_ru = requests.get("https://www.cbr-xml-daily.ru/daily_json.js").json()
        usd_rub = res_ru['Valute']['USD']['Value']
        kzt_rub = res_ru['Valute']['KZT']['Value'] / 100
        
        if "доллар к тенге" in text or "usd к кзт" in text:
            return f"💵➡️🇰🇿 1 Доллар = {round(usd_rub / kzt_rub, 2)} тенге"
        if "рубль к тенге" in text or "руб к тенге" in text:
            return f"🇷🇺➡️🇰🇿 1 Рубль = {round(1 / kzt_rub, 2)} тенге"
        if "тенге к рублю" in text:
            return f"🇰🇿➡️🇷🇺 100 Тенге = {round(kzt_rub * 100, 2)} руб."
        if "доллар" in text or "usd" in text:
            return f"💵 1 Доллар = {round(usd_rub, 2)} руб."
        
        # Крипта
        mapping = {"тон": "the-open-network", "ton": "the-open-network", "биток": "bitcoin"}
        c_id = mapping.get(text, text)
        res_c = requests.get(f"https://api.coingecko.com/api/v3/simple/price?ids={c_id}&vs_currencies=usd").json()
        return f"💰 {text.capitalize()}: ${res_c[c_id]['usd']}"
    except: return "❌ Не понял валюту. Попробуй: 'флеш курс доллар к тенге'"

# --- ОБРАБОТЧИКИ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    builder = ReplyKeyboardBuilder()
    builder.button(text="🎬 Скачать Видео")
    builder.button(text="🎵 Музыка")
    builder.button(text="🌤 Погода/💰 Курс")
    builder.button(text="📧 Почта/🆕 QR")
    builder.button(text="👥 Анонимный чат")
    builder.button(text="🎲 Игры/🤡 Анекдот")
    builder.adjust(2)
    await message.answer("Здарова! Я Флэш. Всё починил, курсы и погода теперь работают четко.", reply_markup=builder.as_markup(resize_keyboard=True))

@dp.message(F.text.in_(["🚫 Остановить чат", "🚀 Следующий"]))
async def anon_controls(message: types.Message):
    global anon_queue
    uid = message.from_user.id
    if message.text == "🚀 Следующий" and uid in anon_pairs:
        p_id = anon_pairs.pop(uid)
        anon_pairs.pop(p_id, None)
        await bot.send_message(p_id, "🚫 Собеседник скипнул чат.")
    
    if message.text == "🚫 Остановить чат":
        if uid in anon_pairs:
            p_id = anon_pairs.pop(uid)
            anon_pairs.pop(p_id, None)
            await bot.send_message(p_id, "🚫 Чат завершен.")
        anon_queue = None
        return await message.answer("Вышли из чата.", reply_markup=types.ReplyKeyboardRemove())
    
    # Рестарт поиска для "Следующий"
    await anon_start_logic(message)

@dp.message(F.text == "👥 Анонимный чат")
async def anon_start_logic(message: types.Message):
    global anon_queue
    uid = message.from_user.id
    if anon_queue and anon_queue != uid:
        p_id = anon_queue
        anon_pairs[uid], anon_pairs[p_id] = p_id, uid
        anon_queue = None
        kb = ReplyKeyboardBuilder().button(text="🚀 Следующий").button(text="🚫 Остановить чат").as_markup(resize_keyboard=True)
        await bot.send_message(p_id, "🤝 Нашел кого-то! Пиши.", reply_markup=kb)
        await message.answer("🤝 Нашел кого-то! Пиши.", reply_markup=kb)
    else:
        anon_queue = uid
        await message.answer("🔍 Ищу...", reply_markup=ReplyKeyboardBuilder().button(text="🚫 Остановить чат").as_markup(resize_keyboard=True))

@dp.message(F.text)
async def handle_all(message: types.Message):
    text = message.text.lower()
    uid = message.from_user.id

    if text.startswith("флеш"):
        if "погода" in text: return await message.reply(get_weather(text))
        if "курс" in text: return await message.reply(get_exchange(text))
        if "анекдот" in text: return await message.reply(f"🤡 {random.choice(JOKES)}")
        if "команды" in text: return await message.reply("Команды: погода, курс, музыка, анекдот, qr, монетка, рулетка.")
        if "музыка" in text:
            query = text.replace("флеш музыка", "").strip()
            wait = await message.answer(f"🔍 Ищу '{query}'...")
            return await process_music_search(message, query, wait)
        if "qr" in text:
            url = text.replace("флеш qr", "").strip()
            qrcode.make(url).save(f"qr_{uid}.png")
            await message.answer_photo(FSInputFile(f"qr_{uid}.png"))
            return os.remove(f"qr_{uid}.png")
        if "монетка" in text: return await message.reply(f"🪙 {random.choice(['Орел', 'Решка'])}")
        if "рулетка" in text: return await message.reply("💥 БАХ!" if random.randint(1,6)==1 else "💨 Осечка")

    # Временная почта
    if text == "📧 почта/🆕 qr":
        return await message.answer(f"📧 Твоя почта: `flash_{uid}@1secmail.com`")

    # Анонимка (пересылка)
    if uid in anon_pairs and message.chat.type == 'private':
        return await bot.send_message(anon_pairs[uid], message.text)

    # Видео и музыка по ссылкам
    if text.startswith("http"):
        mode = "audio" if "soundcloud.com" in text else "video"
        return await start_download(message, message.text, mode)

# --- СКАЧИВАНИЕ ---
async def process_music_search(message, query, wait_msg):
    try:
        with YoutubeDL({'quiet': True}) as ydl:
            results = await asyncio.to_thread(lambda: ydl.extract_info(f"scsearch5:{query}", download=False).get('entries', []))
        if not results: return await wait_msg.edit_text("Ничего не нашел.")
        builder = InlineKeyboardBuilder()
        for e in results:
            sc_cache[e['id']] = e['webpage_url']
            builder.row(types.InlineKeyboardButton(text=f"🎵 {e['title'][:40]}", callback_data=f"sc_{e['id']}"))
        await message.answer("Выбери трек:", reply_markup=builder.as_markup())
        await wait_msg.delete()
    except: await wait_msg.edit_text("Ошибка поиска.")

async def start_download(message, url, mode):
    status = await message.answer("⏳ Качаю...")
    try:
        opts = {'outtmpl': 'downloads/%(id)s.%(ext)s', 'quiet': True}
        if mode == 'audio': opts.update({'format': 'bestaudio', 'postprocessors': [{'key': 'FFmpegExtractAudio','preferredcodec': 'mp3'}]})
        with YoutubeDL(opts) as ydl:
            info = await asyncio.to_thread(lambda: ydl.extract_info(url, download=True))
            path = ydl.prepare_filename(info)
            if mode == 'audio': path = os.path.splitext(path)[0] + ".mp3"
        
        await (message.answer_video(FSInputFile(path)) if mode == 'video' else message.answer_audio(FSInputFile(path)))
        os.remove(path)
        await status.delete()
    except Exception as e: await status.edit_text(f"❌ Ошибка: {str(e)[:50]}")

@dp.callback_query(F.data.startswith("sc_"))
async def cb_dl(call: types.CallbackQuery):
    url = sc_cache.get(call.data.split("_")[1])
    await call.message.delete()
    await start_download(call.message, url, "audio")

async def main():
    if not os.path.exists('downloads'): os.makedirs('downloads')
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
