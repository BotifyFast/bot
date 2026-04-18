import os, random, asyncio, logging, requests, datetime, string, qrcode
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import FSInputFile, InlineKeyboardButton, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from yt_dlp import YoutubeDL
from pydub import AudioSegment
import speech_recognition as sr

logging.basicConfig(level=logging.INFO)

# --- ТОКЕНЫ ---
TOKEN = "8638601182:AAHAOf2wvybOOyhyt_PNijYkKkljJwGnN-g"
WEATHER_KEY = "c2b2631749aead62cfdc86b394e6399f"

bot = Bot(token=TOKEN)
dp = Dispatcher()
sc_cache = {}

# --- КЛАВИАТУРА ---
def main_kb():
    kb = ReplyKeyboardBuilder()
    btns = ["🌤 Погода", "📈 Курс", "📧 Почта", "🎵 Музыка", "🎲 Ролл", "🔫 Рулетка", "🪙 Монета", "📲 QR Код", "⚡️ Команды"]
    for b in btns: kb.add(KeyboardButton(text=b))
    kb.adjust(3, 3, 3)
    return kb.as_markup(resize_keyboard=True)

# --- ФУНКЦИИ ---
async def process_any_audio(m: types.Message, audio_obj):
    wait = await m.answer("👂 Обрабатываю звук (ГС/Кружок)...")
    fid = audio_obj.file_id
    path_o, path_w = f"{fid}.ogg", f"{fid}.wav"
    try:
        file = await bot.get_file(fid)
        await bot.download_file(file.file_path, path_o)
        
        # Конвертация (подходит и для видео-кружков)
        audio = AudioSegment.from_file(path_o)
        audio.export(path_w, format="wav")
        
        r = sr.Recognizer()
        with sr.AudioFile(path_w) as s:
            t = r.recognize_google(r.record(s), language="ru-RU")
            await wait.edit_text(f"🎤 **Текст:**\n{t}")
    except Exception as e:
        await wait.edit_text(f"❌ Не удалось распознать: {e}")
    finally:
        for f in [path_o, path_w]:
            if os.path.exists(f): os.remove(f)

# --- ОБРАБОТЧИКИ ---

# Реакция на просто "флеш"
@dp.message(F.text.lower() == "флеш")
async def flash_call(m: types.Message):
    await m.reply("Чего звал? Я тут! Вот мои команды: /start или жми '⚡️ Команды'")

@dp.message(F.text == "/start")
async def cmd_start(m: types.Message):
    await m.answer(f"Привет! Я бот **Флеш комбайн** ⚡️\n\nРаботаю в группах и в личке. Умею качать музыку, распознавать ГС и кружки, делать почту и многое другое!", reply_markup=main_kb())

# ГЛАСОВАЯ КОМАНДА (на ГС и на Кружки)
@dp.message(F.text.lower() == "флеш голос")
async def voice_reply_cmd(m: types.Message):
    reply = m.reply_to_message
    if not reply:
        return await m.reply("Ответь этой командой на ГС или Кружок!")
    
    if reply.voice:
        await process_any_audio(m, reply.voice)
    elif reply.video_note:
        await process_any_audio(m, reply.video_note)
    elif reply.audio:
        await process_any_audio(m, reply.audio)
    else:
        await m.reply("Это не голосовое и не кружок!")

# МУЗЫКА
@dp.message(F.text.startswith("флеш музыка") | (F.text == "🎵 Музыка"))
async def music_cmd(m: types.Message):
    query = m.text.replace("флеш музыка", "").replace("🎵 Музыка", "").strip()
    if not query:
        return await m.answer("Напиши название музыки после команды!")
    
    wait = await m.answer(f"🔍 Ищу '{query}' в SoundCloud...")
    try:
        with YoutubeDL({'quiet': True, 'noplaylist': True}) as ydl:
            search_res = await asyncio.to_thread(lambda: ydl.extract_info(f"scsearch5:{query}", download=False))
            entries = search_res.get('entries', [])
        
        if not entries:
            return await wait.edit_text("❌ Ничего не найдено.")
        
        kb = InlineKeyboardBuilder()
        for e in entries:
            sc_cache[e['id']] = e['webpage_url']
            kb.row(InlineKeyboardButton(text=f"🎵 {e['title'][:40]}", callback_data=f"dl_{e['id']}"))
        await wait.edit_text("Выбери трек для загрузки:", reply_markup=kb.as_markup())
    except Exception as e:
        await wait.edit_text(f"❌ Ошибка поиска: {e}")

@dp.callback_query(F.data.startswith("dl_"))
async def music_download(c: types.CallbackQuery):
    track_id = c.data.replace("dl_", "")
    url = sc_cache.get(track_id)
    if not url: return await c.answer("Ошибка ссылки")
    
    await c.message.edit_text("📥 Качаю файл, подожди...")
    path = f"downloads/{track_id}.mp3"
    try:
        opts = {
            'outtmpl': path,
            'format': 'bestaudio/best',
            'postprocessors': [{'key': 'FFmpegExtractAudio','preferredcodec': 'mp3','preferredquality': '192'}],
        }
        with YoutubeDL(opts) as ydl:
            await asyncio.to_thread(lambda: ydl.download([url]))
        
        await c.message.answer_audio(FSInputFile(path))
        await c.message.delete()
    except Exception as e:
        await c.message.edit_text(f"❌ Ошибка загрузки: {e}")
    finally:
        if os.path.exists(path): os.remove(path)

# QR КОД
@dp.message(F.text.startswith("флеш qr") | (F.text == "📲 QR Код"))
async def qr_cmd(m: types.Message):
    link = m.text.replace("флеш qr", "").replace("📲 QR Код", "").strip()
    if not link:
        return await m.answer("Напиши ссылку после команды! Пример: `флеш qr google.com`")
    
    path = f"qr_{m.from_user.id}.png"
    img = qrcode.make(link)
    img.save(path)
    await m.answer_photo(FSInputFile(path), caption=f"Твой QR-код для: {link}")
    os.remove(path)

# РОЛЛ 1-100 (КТО БОЛЬШЕ)
@dp.message(F.text.startswith("флеш ролл") | (F.text == "🎲 Ролл"))
async def roll_cmd(m: types.Message):
    try:
        # Если ввели "флеш ролл 1-500"
        parts = m.text.split()
        if len(parts) > 2 and "-" in parts[-1]:
            start, end = map(int, parts[-1].split("-"))
            res = random.randint(start, end)
        else:
            res = random.randint(1, 100)
        
        await m.reply(f"🎲 Результат: **{res}**\nУ кого больше — тот и папа!")
    except:
        await m.reply(f"🎲 Результат: **{random.randint(1, 100)}**")

# ПОГОДА
@dp.message(F.text.startswith("флеш погода") | (F.text == "🌤 Погода"))
async def weather_cmd(m: types.Message):
    city = m.text.replace("флеш погода", "").replace("🌤 Погода", "").strip() or "Костанай"
    url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_KEY}&units=metric&lang=ru"
    try:
        r = requests.get(url).json()
        text = (f"🌤 **Погода: {city.capitalize()}**\n"
                f"🌡 Градусы: {round(r['main']['temp'])}°C\n"
                f"☁️ Статус: {r['weather'][0]['description']}\n"
                f"🕒 Время: {datetime.datetime.now().strftime('%H:%M')}")
        await m.answer(text)
    except:
        await m.answer("❌ Город не найден.")

# МОНЕТКА
@dp.message(F.text.in_(["флеш монетка", "флеш монета", "🪙 Монета"]))
async def coin_cmd(m: types.Message):
    res = random.choice(["Орёл", "Решка"])
    await m.reply(f"🪙 Выпало: **{res}**")

# КУРСЫ
@dp.message(F.text.in_(["флеш курс", "📈 Курс"]))
async def rates_cmd(m: types.Message):
    try:
        r = requests.get("https://www.cbr-xml-daily.ru/daily_json.js").json()
        usd = r['Valute']['USD']['Value']
        kzt = r['Valute']['KZT']['Value'] / 100
        crypto = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,the-open-network&vs_currencies=usd").json()
        await m.answer(f"📊 **Курсы:**\n💵 Доллар: {round(usd, 2)}₽ | {round(usd/kzt, 2)}₸\n🇰🇿 Тенге: {round(kzt, 2)}₽\n₿ BTC: ${crypto['bitcoin']['usd']:,}\n💎 TON: ${crypto['the-open-network']['usd']}")
    except: await m.answer("Ошибочка в курсах")

# ВСЕ КОМАНДЫ
@dp.message(F.text.in_(["⚡️ Команды", "флеш команды"]))
async def help_cmd(m: types.Message):
    await m.answer("📜 **Команды:**\n\n"
                   "• `флеш погода [город]`\n"
                   "• `флеш музыка [название]`\n"
                   "• `флеш голос` (ответ на ГС/кружок)\n"
                   "• `флеш ролл [1-100]`\n"
                   "• `флеш монетка`\n"
                   "• `флеш qr [ссылка]`\n"
                   "• `флеш почта`\n"
                   "• `флеш курс`", reply_markup=main_kb())

async def main():
    if not os.path.exists('downloads'): os.makedirs('downloads')
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
