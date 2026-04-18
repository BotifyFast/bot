import os
import static_ffmpeg
static_ffmpeg.add_paths()
import asyncio
import logging
import requests
import random
import string
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.types import FSInputFile
from yt_dlp import YoutubeDL

logging.basicConfig(level=logging.INFO)

# --- ТОКЕНЫ И КЛЮЧИ ---
TOKEN = "8638601182:AAHAOf2wvybOOyhyt_PNijYkKkljJwGnN-g"
# Твой новый API ключ для погоды
WEATHER_API_KEY = "c2b2631749aead62cfdc86b394e6399f"

bot = Bot(token=TOKEN)
dp = Dispatcher()

MAX_FILE_SIZE = 50 * 1024 * 1024 
sc_cache = {}
temp_mail_cache = {} 

CITIES_SHORT = {
    "мск": "Moscow", "москва": "Moscow",
    "спб": "Saint Petersburg", "питер": "Saint Petersburg",
    "кст": "Kostanay", "костанай": "Kostanay",
    "аст": "Astana", "астана": "Astana",
    "алм": "Almaty", "алматы": "Almaty"
}

COMMON_OPTS = {'user_agent': 'Mozilla/5.0', 'quiet': True, 'no_warnings': True}

def main_menu():
    builder = ReplyKeyboardBuilder()
    builder.button(text="🎬 Скачать Видео (TT/Insta)")
    builder.button(text="🎵 Музыка (SoundCloud)")
    builder.button(text="🌤 Погода")
    builder.button(text="💰 Курс Валют/Крипты")
    builder.button(text="📧 Временная почта")
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

# --- ПОГОДА (ИСПРАВЛЕНО) ---
def get_weather(city_query):
    # Очищаем запрос от лишних слов
    clean_city = city_query.lower().replace("погода", "").strip()
    city = CITIES_SHORT.get(clean_city, clean_city)
    
    url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_API_KEY}&units=metric&lang=ru"
    try:
        res = requests.get(url, timeout=10).json()
        if res.get("cod") != 200: 
            return f"❌ Город '{clean_city}' не найден. Попробуй другое название."
        
        temp = res["main"]["temp"]
        desc = res["weather"][0]["description"]
        return f"🌤 Погода в {res['name']}:\n🌡 Температура: {temp}°C\n☁️ На улице: {desc.capitalize()}"
    except Exception as e:
        return "❌ Ошибка сервиса погоды."

# --- КУРСЫ (ДОБАВЛЕН TON) ---
def get_rates():
    try:
        # Крипта (добавили TON)
        crypto_url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum,the-open-network&vs_currencies=usd"
        c = requests.get(crypto_url, timeout=10).json()
        
        # Валюта
        v = requests.get("https://api.exchangerate-api.com/v4/latest/USD", timeout=10).json()
        
        btc = c.get('bitcoin', {}).get('usd', '??')
        eth = c.get('ethereum', {}).get('usd', '??')
        ton = c.get('the-open-network', {}).get('usd', '??')
        rub = round(v['rates']['RUB'], 2)
        kzt = round(v['rates']['KZT'], 2)
        
        return (f"💰 **Актуальные курсы:**\n\n"
                f"Bitcoin: `${btc}`\n"
                f"Ethereum: `${eth}`\n"
                f"TON: `${ton}`\n\n"
                f"USD/RUB: `{rub}₽`\n"
                f"USD/KZT: `{kzt}₸`\n")
    except:
        return "❌ Ошибка при получении курсов. Попробуй позже."

# --- ВРЕМЕННАЯ ПОЧТА ---
def gen_mail(user_id):
    domains = ["1secmail.com", "1secmail.org", "1secmail.net"]
    login = ''.join(random.choice(string.ascii_lowercase + string.digits) for _ in range(10))
    email = f"{login}@{random.choice(domains)}"
    temp_mail_cache[user_id] = email
    return email

def check_mail(email):
    try:
        login, domain = email.split('@')
        url = f"https://www.1secmail.com/api/v1/?action=getMessages&login={login}&domain={domain}"
        res = requests.get(url, timeout=10).json()
        if not res: return "📬 Писем пока нет."
        msg_id = res[0]['id']
        msg_data = requests.get(f"https://www.1secmail.com/api/v1/?action=readMessage&login={login}&domain={domain}&id={msg_id}").json()
        return f"📩 **От:** {msg_data['from']}\n**Тема:** {msg_data['subject']}\n\n{msg_data['textBody']}"
    except: return "❌ Ошибка проверки почты."

# --- ОБРАБОТЧИКИ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    welcome_text = (f"Здарова, {message.from_user.first_name}! 👋\n\nЯ — Флэш. Качаю видео, ищу музыку, знаю погоду и курсы (теперь и TON!).\n\nВыбирай режим! 👇")
    await message.answer(welcome_text, reply_markup=main_menu())

@dp.message(F.text.lower().startswith("флеш"))
async def flash_commands(message: types.Message):
    cmd = message.text.lower().replace("флеш", "").strip()
    if "погода" in cmd:
        await message.answer(get_weather(cmd), parse_mode="Markdown")
    elif "курс" in cmd:
        await message.answer(get_rates(), parse_mode="Markdown")

@dp.message(F.text == "🌤 Погода")
async def weather_btn(message: types.Message):
    await message.answer("Напиши мне: `Флеш погода Костанай` или `Флеш погода Спб`")

@dp.message(F.text == "💰 Курс Валют/Крипты")
async def rates_btn(message: types.Message):
    await message.answer(get_rates(), parse_mode="Markdown")

@dp.message(F.text == "📧 Временная почта")
async def mail_btn(message: types.Message):
    email = gen_mail(message.from_user.id)
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🔄 Проверить", callback_data="check_mail"))
    builder.row(types.InlineKeyboardButton(text="🆕 Новая", callback_data="new_mail"))
    await message.answer(f"📧 Твоя почта:\n`{email}`", parse_mode="Markdown", reply_markup=builder.as_markup())

@dp.callback_query(F.data == "check_mail")
async def cb_check(callback: types.CallbackQuery):
    email = temp_mail_cache.get(callback.from_user.id)
    if email: await callback.message.answer(check_mail(email), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "new_mail")
async def cb_new(callback: types.CallbackQuery):
    email = gen_mail(callback.from_user.id)
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🔄 Проверить", callback_data="check_mail"))
    builder.row(types.InlineKeyboardButton(text="🆕 Новая", callback_data="new_mail"))
    await callback.message.edit_text(f"📧 Новая почта:\n`{email}`", parse_mode="Markdown", reply_markup=builder.as_markup())

# --- DOWNLOAD LOGIC ---
@dp.message(F.text.startswith(("http://", "https://")))
async def handle_links(message: types.Message):
    if "soundcloud.com" in message.text: await start_download(message, message.text, "audio")
    elif any(d in message.text for d in ["tiktok.com", "instagram.com"]): await start_download(message, message.text, "video")

@dp.message(F.text)
async def handle_text(message: types.Message):
    if message.text in ["🎬 Скачать Видео (TT/Insta)", "🎵 Музыка (SoundCloud)", "🌤 Погода", "💰 Курс Валют/Крипты", "📧 Временная почта"]: return
    if message.chat.type == 'private':
        wait = await message.answer("🔍 Ищу в SoundCloud...")
        await process_music_search(message, message.text, wait)

async def process_music_search(message, query, wait_msg):
    try:
        def search():
            with YoutubeDL(COMMON_OPTS) as ydl:
                return ydl.extract_info(f"scsearch5:{query}", download=False).get('entries', [])
        results = await asyncio.to_thread(search)
        if not results: return await wait_msg.edit_text("Ничего не нашел.")
        builder = InlineKeyboardBuilder()
        for entry in results:
            t_id, t_url = entry.get('id'), entry.get('webpage_url')
            sc_cache[t_id] = t_url
            builder.row(types.InlineKeyboardButton(text=f"🎵 {entry.get('title')[:40]}", callback_data=f"sc_{t_id}"))
        await message.answer("Выбери трек:", reply_markup=builder.as_markup())
        await wait_msg.delete()
    except: await wait_msg.edit_text("Ошибка поиска.")

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
                return (os.path.splitext(fp)[0] + ".mp3") if mode == 'audio' else fp, info.get('title')
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
