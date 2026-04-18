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
temp_mail_cache = {}
anon_queue = None
anon_pairs = {}

JOKES = [
    "— Купила мелок от тараканов! — И что, помогают? — Да, сидят в углу, рисуют...",
    "Сын программиста: — Папа, почему солнце встает на востоке? — Работает? Ничего не трогай!",
    "Программист принес домой 11 пакетов молока, потому что в магазине были яйца.",
    "Колобок повесился. Буратино утонул. Штирлиц парашют забыл.",
    "— Штирлиц, а где вы так научились водить? — В ДОСААФ, — ответил Штирлиц и подумал: 'А не сболтнул ли я лишнего?'"
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

# --- ФУНКЦИИ ---
def get_weather(city_name):
    url = f"http://api.openweathermap.org/data/2.5/weather?q={city_name}&appid={WEATHER_API_KEY}&units=metric&lang=ru"
    try:
        res = requests.get(url, timeout=10).json()
        if res.get("cod") != 200: return "❌ Город не найден."
        return f"🌤 Погода в {res['name']}: {res['main']['temp']}°C, {res['weather'][0]['description']}"
    except: return "❌ Ошибка погоды."

def get_crypto(coin):
    mapping = {"биток": "bitcoin", "эфир": "ethereum", "тон": "the-open-network", "ton": "the-open-network"}
    coin_id = mapping.get(coin.lower(), coin.lower())
    try:
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd"
        res = requests.get(url, timeout=10).json()
        val = res[coin_id]['usd']
        return f"💰 Курс {coin.capitalize()}: ${val}"
    except: return "❌ Не нашел такую валюту."

# --- ОБРАБОТЧИКИ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(f"Здарова! Я Флэш. Всё починил, теперь команды работают везде.", reply_markup=main_menu())

@dp.message(Command("stop"))
async def anon_stop(message: types.Message):
    global anon_queue
    uid = message.from_user.id
    if uid == anon_queue:
        anon_queue = None
        await message.answer("Поиск остановлен.")
    elif uid in anon_pairs:
        partner_id = anon_pairs.pop(uid)
        anon_pairs.pop(partner_id, None)
        await bot.send_message(partner_id, "🚫 Собеседник покинул чат.")
        await message.answer("Чат завершен.")
    else:
        await message.answer("Ты не в чате.")

@dp.message(F.text == "👥 Анонимный чат")
async def anon_chat_btn(message: types.Message):
    global anon_queue
    uid = message.from_user.id
    if uid in anon_pairs: return await message.answer("Ты уже в чате! Напиши /stop.")
    if anon_queue and anon_queue != uid:
        p_id = anon_queue
        anon_pairs[uid], anon_pairs[p_id] = p_id, uid
        anon_queue = None
        await bot.send_message(p_id, "🤝 Собеседник найден! Пиши любое сообщение.")
        await message.answer("🤝 Собеседник найден! Пиши любое сообщение.")
    else:
        anon_queue = uid
        await message.answer("🔍 Ищу собеседника... Напиши /stop для отмены.")

# --- ГЛАВНЫЙ ОБРАБОТЧИК ТЕКСТА (ИСПРАВЛЕНО) ---
@dp.message(F.text)
async def handle_all_text(message: types.Message):
    text = message.text.lower()
    uid = message.from_user.id

    # 1. Сначала проверяем системные кнопки меню
    if text in ["🎬 скачать видео", "🎵 музыка", "🌤 погода/💰 курс", "📧 почта/🆕 qr", "👥 анонимный чат", "🎲 игры/🤡 анекдот"]:
        if text == "🌤 погода/💰 курс": await message.answer("Пиши: `Флеш погода Костанай` или `Флеш курс тон`")
        elif text == "📧 почта/🆕 qr": await message.answer("Кнопка почты в разработке или используй `Флеш qr [ссылка]`")
        elif text == "🎲 игры/🤡 анекдот": await message.answer("Пиши: `Флеш анекдот`, `Флеш монетка` или `Флеш рулетка`")
        return

    # 2. Проверяем команды "Флеш ..."
    if text.startswith("флеш"):
        if "анекдот" in text:
            await message.reply(f"🤡 {random.choice(JOKES)}")
        elif "погода" in text:
            city = text.replace("флеш погода", "").strip()
            await message.reply(get_weather(city))
        elif "курс" in text:
            coin = text.replace("флеш курс", "").strip()
            await message.reply(get_crypto(coin))
        elif "монетка" in text:
            await message.reply(f"🪙 Выпало: {random.choice(['Орел', 'Решка'])}")
        elif "рулетка" in text:
            res = "💥 ПАУ!" if random.randint(1, 6) == 1 else "👀 Осечка!"
            await message.reply(res)
        elif "qr" in text:
            url = text.replace("флеш qr", "").strip()
            path = f"qr_{uid}.png"
            qrcode.make(url).save(path)
            await message.answer_photo(FSInputFile(path), caption="Твой QR!")
            os.remove(path)
        return

    # 3. Если человек в анонимном чате и это НЕ команда — пересылаем
    if uid in anon_pairs:
        try:
            await bot.send_message(anon_pairs[uid], message.text)
        except:
            await message.answer("⚠️ Ошибка отправки собеседнику.")
        return

    # 4. Если просто ссылка — качаем
    if text.startswith("http"):
        if "soundcloud.com" in text: await start_download(message, message.text, "audio")
        else: await start_download(message, message.text, "video")

# --- СКАЧИВАНИЕ ---
async def start_download(message, url, mode):
    status = await message.answer("⏳ Качаю...")
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

async def main():
    if not os.path.exists('downloads'): os.makedirs('downloads')
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
