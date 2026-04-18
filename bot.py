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

# Логирование
logging.basicConfig(level=logging.INFO)

# --- ТОКЕНЫ И КЛЮЧИ ---
TOKEN = "8638601182:AAHAOf2wvybOOyhyt_PNijYkKkljJwGnN-g"
WEATHER_API_KEY = "1bbc827cce2d51534681e79337ee4bdd"

bot = Bot(token=TOKEN)
dp = Dispatcher()

MAX_FILE_SIZE = 50 * 1024 * 1024 
sc_cache = {}
temp_mail_cache = {} 

# Основные сокращения (для всего остального бот будет искать по вводу пользователя)
CITIES_SHORT = {
    "мск": "Moscow", "москва": "Moscow",
    "спб": "Saint Petersburg", "питер": "Saint Petersburg",
    "кст": "Kostanay", "костанай": "Kostanay",
    "аст": "Astana", "астана": "Astana",
    "алм": "Almaty", "алматы": "Almaty",
    "екб": "Yekaterinburg", "нск": "Novosibirsk"
}

COMMON_OPTS = {'user_agent': 'Mozilla/5.0', 'quiet': True, 'no_warnings': True}

# --- КЛАВИАТУРА ---
def main_menu():
    builder = ReplyKeyboardBuilder()
    builder.button(text="🎬 Скачать Видео (TT/Insta)")
    builder.button(text="🎵 Музыка (SoundCloud)")
    builder.button(text="🌤 Погода")
    builder.button(text="💰 Курс Валют/Крипты")
    builder.button(text="📧 Временная почта")
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

# --- ПОГОДА (Теперь понимает любой город РФ и РК) ---
def get_weather(city_query):
    # Если есть сокращение - берем его, если нет - ищем по вводу пользователя
    city = CITIES_SHORT.get(city_query.lower(), city_query)
    url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_API_KEY}&units=metric&lang=ru"
    try:
        res = requests.get(url).json()
        if res.get("cod") != 200: 
            return "❌ Город не найден. Проверь название (пиши например: Флеш погода Караганда)."
        
        temp = res["main"]["temp"]
        feels_like = res["main"]["feels_like"]
        desc = res["weather"][0]["description"]
        city_name = res["name"]
        
        return (f"🌤 **Погода в {city_name}:**\n"
                f"🌡 Температура: `{temp}°C`\n"
                f"🤔 Ощущается как: `{feels_like}°C`\n"
                f"☁️ На улице: {desc.capitalize()}")
    except:
        return "❌ Ошибка связи с сервером погоды."

# --- КУРСЫ ---
def get_rates():
    try:
        crypto = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum&vs_currencies=usd").json()
        valuta = requests.get("https://api.exchangerate-api.com/v4/latest/USD").json()
        return (f"💰 **Актуальные курсы:**\n\n"
                f"Bitcoin: `${crypto['bitcoin']['usd']}`\n"
                f"Ethereum: `${crypto['ethereum']['usd']}`\n\n"
                f"USD/RUB: `{round(valuta['rates']['RUB'], 2)}₽`\n"
                f"USD/KZT: `{round(valuta['rates']['KZT'], 2)}₸`\n")
    except:
        return "❌ Ошибка при получении данных о валютах."

# --- ВРЕМЕННАЯ ПОЧТА (1secmail - API ключ не требуется) ---
def gen_mail(user_id):
    domains = ["1secmail.com", "1secmail.org", "1secmail.net"]
    login = ''.join(random.choice(string.ascii_lowercase + string.digits) for _ in range(10))
    email = f"{login}@{random.choice(domains)}"
    temp_mail_cache[user_id] = email
    return email

def check_mail(email):
    login, domain = email.split('@')
    url = f"https://www.1secmail.com/api/v1/?action=getMessages&login={login}&domain={domain}"
    res = requests.get(url).json()
    if not res: return "📬 Писем пока нет. Проверь через минуту."
    
    msg_id = res[0]['id']
    msg_url = f"https://www.1secmail.com/api/v1/?action=readMessage&login={login}&domain={domain}&id={msg_id}"
    msg_data = requests.get(msg_url).json()
    return f"📩 **От:** {msg_data['from']}\n**Тема:** {msg_data['subject']}\n\n**Текст:**\n{msg_data['textBody']}"

# --- ОБРАБОТЧИКИ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    welcome_text = (
        f"Здарова, {message.from_user.first_name}! 👋\n\n"
        "Я — Флэш. Качаю видео, ищу музыку, знаю погоду и создаю временную почту.\n\n"
        "🚀 **Команды для групп:**\n"
        "— `Флеш погода [город]`\n"
        "— `Флеш курс`\n"
        "— Просто кидай ссылку на TikTok/Insta/SoundCloud"
    )
    await message.answer(welcome_text, reply_markup=main_menu())

@dp.message(F.text.lower().startswith("флеш"))
async def flash_commands(message: types.Message):
    cmd = message.text.lower().replace("флеш", "").strip()
    if "погода" in cmd:
        city = cmd.replace("погода", "").strip()
        if not city: return await message.answer("Напиши город, например: `Флеш погода Астана`")
        await message.answer(get_weather(city), parse_mode="Markdown")
    elif "курс" in cmd:
        await message.answer(get_rates(), parse_mode="Markdown")

@dp.message(F.text == "🌤 Погода")
async def weather_btn(message: types.Message):
    await message.answer("Напиши мне: `Флеш погода [город]`\n(Работает для любого города России и Казахстана)")

@dp.message(F.text == "💰 Курс Валют/Крипты")
async def rates_btn(message: types.Message):
    await message.answer(get_rates(), parse_mode="Markdown")

@dp.message(F.text == "📧 Временная почта")
async def mail_btn(message: types.Message):
    email = gen_mail(message.from_user.id)
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🔄 Проверить входящие", callback_data="check_mail"))
    builder.row(types.InlineKeyboardButton(text="🆕 Создать новую", callback_data="new_mail"))
    await message.answer(f"📧 Твоя временная почта:\n`{email}`\n\nЖми кнопку ниже, чтобы увидеть письма.", 
                         parse_mode="Markdown", reply_markup=builder.as_markup())

@dp.callback_query(F.data == "check_mail")
async def cb_check(callback: types.CallbackQuery):
    email = temp_mail_cache.get(callback.from_user.id)
    if not email: return await callback.answer("Создай почту заново", show_alert=True)
    await callback.message.answer(check_mail(email), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "new_mail")
async def cb_new(callback: types.CallbackQuery):
    email = gen_mail(callback.from_user.id)
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🔄 Проверить входящие", callback_data="check_mail"))
    builder.row(types.InlineKeyboardButton(text="🆕 Создать новую", callback_data="new_mail"))
    await callback.message.edit_text(f"📧 Новая почта:\n`{email}`", parse_mode="Markdown", reply_markup=builder.as_markup())

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

# --- ФУНКЦИИ СКАЧИВАНИЯ (СТАНДАРТ) ---
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
    status = await message.answer("⏳ Работаю...")
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
    except: await status.edit_text("Ошибка скачивания.")
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
