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

# --- КОНФИГ ---
TOKEN = "8638601182:AAHAOf2wvybOOyhyt_PNijYkKkljJwGnN-g"
WEATHER_API_KEY = "c2b2631749aead62cfdc86b394e6399f"

bot = Bot(token=TOKEN)
dp = Dispatcher()

sc_cache = {}
anon_queue = None
anon_pairs = {}

CITIES_SHORT = {
    "мск": "Moscow", "спб": "Saint Petersburg", "кст": "Kostanay", 
    "аст": "Astana", "алм": "Almaty", "екб": "Yekaterinburg"
}

# --- ЛОГИКА ВАЛЮТ (Тенге, Рубль, Доллар) ---
def get_exchange_rate(text):
    text = text.lower().replace("флеш", "").replace("курс", "").strip()
    try:
        # Получаем данные ЦБ РФ и Нацбанка (через открытое API)
        res_ru = requests.get("https://www.cbr-xml-daily.ru/daily_json.js").json()
        usd_to_rub = res_ru['Valute']['USD']['Value']
        kzt_to_rub = res_ru['Valute']['KZT']['Value'] / (res_ru['Valute']['KZT']['Nominal'])
        
        # Логика конвертации
        if "тенге к рублю" in text or "кст к руб" in text:
            return f"🇰🇿➡️🇷🇺 100 Тенге = {round(kzt_to_rub * 100, 2)} руб."
        elif "рубля к тенге" in text or "руб к тенге" in text:
            return f"🇷🇺➡️🇰🇿 1 Рубль = {round(1 / kzt_to_rub, 2)} тенге."
        elif "доллар к тенге" in text or "usd к кзт" in text:
            usd_to_kzt = usd_to_rub / kzt_to_rub
            return f"💵➡️🇰🇿 1 Доллар = {round(usd_to_kzt, 2)} тенге."
        elif "доллар" in text or "usd" in text:
            return f"💵 1 Доллар = {round(usd_to_rub, 2)} руб."
        elif "тенге" in text or "kzt" in text:
            return f"🇰🇿 100 Тенге = {round(kzt_to_rub * 100, 2)} руб."
        else:
            # Если это крипта (тон, биток)
            mapping = {"тон": "the-open-network", "ton": "the-open-network", "биток": "bitcoin"}
            c_id = mapping.get(text, text)
            res_crypto = requests.get(f"https://api.coingecko.com/api/v3/simple/price?ids={c_id}&vs_currencies=usd").json()
            return f"💰 Курс {text.capitalize()}: ${res_crypto[c_id]['usd']}"
    except:
        return f"❌ Не осилил конвертацию '{text}'. Попробуй: 'флеш курс доллар к тенге'"

# --- ОБРАБОТЧИКИ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("Флэш на связи! Починил курсы тенге и добавил обработку музыки. Не забудь поставить ffmpeg на сервер!", reply_markup=main_menu())

@dp.message(F.text)
async def handle_text(message: types.Message):
    text = message.text.lower()
    uid = message.from_user.id

    if text.startswith("флеш"):
        if "курс" in text:
            return await message.reply(get_exchange_rate(text))
        elif "команды" in text:
            return await message.reply("⚡️ Команды: `погода`, `курс [валюта к валюте]`, `музыка`, `анекдот`, `qr`.")
        elif "музыка" in text:
            query = text.replace("флеш музыка", "").strip()
            if not query: return await message.reply("Че искать то?")
            wait = await message.answer(f"🔍 Ищу '{query}'...")
            return await process_music_search(message, query, wait)
        elif "анекдот" in text:
            jokes = ["Штирлиц бил наверняка. Наверняк защищался как мог.", "Гаишник: — Дыхните! — Не буду, я на диете."]
            return await message.reply(f"🤡 {random.choice(jokes)}")
        elif "qr" in text:
            url = text.replace("флеш qr", "").strip()
            path = f"qr_{uid}.png"
            qrcode.make(url).save(path)
            await message.answer_photo(FSInputFile(path))
            return os.remove(path)

    # Анонимный чат
    if uid in anon_pairs and message.chat.type == 'private':
        return await bot.send_message(anon_pairs[uid], message.text)

    # Загрузка по ссылкам
    if text.startswith("http"):
        mode = "audio" if "soundcloud.com" in text else "video"
        return await start_download(message, message.text, mode)

# --- ЗАГРУЗКА ---
async def start_download(message, url, mode):
    status = await message.answer("⏳ Качаю (если это музыка, нужен ffmpeg на сервере)...")
    file_path = None
    try:
        def sync_dl():
            opts = {
                'user_agent': 'Mozilla/5.0', 'quiet': True,
                'outtmpl': 'downloads/%(id)s.%(ext)s',
            }
            if mode == 'audio':
                opts.update({
                    'format': 'bestaudio',
                    'postprocessors': [{'key': 'FFmpegExtractAudio','preferredcodec': 'mp3'}]
                })
            with YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                fp = ydl.prepare_filename(info)
                if mode == 'audio': fp = os.path.splitext(fp)[0] + ".mp3"
                return fp, info.get('title')
        
        file_path, title = await asyncio.to_thread(sync_dl)
        if mode == 'video': await message.answer_video(FSInputFile(file_path), caption=title)
        else: await message.answer_audio(FSInputFile(file_path), title=title)
        await status.delete()
    except Exception as e:
        await status.edit_text(f"⚠️ Ошибка. Скорее всего, на сервере нет ffmpeg.\nЛог: {str(e)[:100]}")
    finally:
        if file_path and os.path.exists(file_path): os.remove(file_path)

async def process_music_search(message, query, wait_msg):
    try:
        def search():
            with YoutubeDL({'quiet': True}) as ydl:
                return ydl.extract_info(f"scsearch5:{query}", download=False).get('entries', [])
        results = await asyncio.to_thread(search)
        if not results: return await wait_msg.edit_text("Пусто.")
        builder = InlineKeyboardBuilder()
        for entry in results:
            t_id = entry.get('id')
            sc_cache[t_id] = entry.get('webpage_url')
            builder.row(types.InlineKeyboardButton(text=f"🎵 {entry.get('title')[:40]}", callback_data=f"sc_{t_id}"))
        await message.answer("Выбирай трек:", reply_markup=builder.as_markup())
        await wait_msg.delete()
    except: await wait_msg.edit_text("Ошибка поиска.")

@dp.callback_query(F.data.startswith("sc_"))
async def cb_dl(callback: types.CallbackQuery):
    url = sc_cache.get(callback.data.split("_")[1])
    await callback.message.delete()
    await start_download(callback.message, url, "audio")

def main_menu():
    builder = ReplyKeyboardBuilder()
    builder.button(text="🎬 Скачать Видео")
    builder.button(text="🎵 Музыка")
    builder.button(text="🌤 Погода/💰 Курс")
    builder.button(text="👥 Анонимный чат")
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

async def main():
    if not os.path.exists('downloads'): os.makedirs('downloads')
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
