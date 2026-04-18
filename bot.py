import os, random, asyncio, logging, requests, datetime, string
from PIL import Image
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import FSInputFile, InlineKeyboardButton, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from yt_dlp import YoutubeDL
import google.generativeai as genai
import pytesseract
from pydub import AudioSegment
import speech_recognition as sr

logging.basicConfig(level=logging.INFO)

# --- КОНФИГ (ТВОИ КЛЮЧИ) ---
TOKEN = "8638601182:AAHAOf2wvybOOyhyt_PNijYkKkljJwGnN-g"
WEATHER_KEY = "c2b2631749aead62cfdc86b394e6399f"
GEMINI_KEY = "AIzaSyCwd4xf-PWyayAdL-yp3xx4-Tlm4aywGXQ"

genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

bot = Bot(token=TOKEN)
dp = Dispatcher()

sc_cache = {}
anon_queue = None
anon_pairs = {}

# --- ФУНКЦИИ МОЗГА ---

def get_rates():
    try:
        r = requests.get("https://www.cbr-xml-daily.ru/daily_json.js").json()
        usd = r['Valute']['USD']['Value']
        eur = r['Valute']['EUR']['Value']
        kzt_rate = r['Valute']['KZT']['Value'] / 100
        crypto = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,the-open-network&vs_currencies=usd").json()
        
        return (f"💰 **Курсы валют:**\n"
                f"🇺🇸 Доллар: {round(usd, 2)}₽ | {round(usd/kzt_rate, 2)}₸\n"
                f"🇪🇺 Евро: {round(eur, 2)}₽ | {round(eur/kzt_rate, 2)}₸\n"
                f"🇰🇿 Тенге: {round(kzt_rate, 2)}₽\n\n"
                f"₿ Биткоин: ${crypto['bitcoin']['usd']:,}\n"
                f"💎 Тонкоин: ${crypto['the-open-network']['usd']}")
    except: return "❌ Ошибка курсов."

def get_weather(city="Костанай"):
    try:
        url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_KEY}&units=metric&lang=ru"
        r = requests.get(url).json()
        temp = r['main']['temp']
        desc = r['weather'][0]['description'].capitalize()
        hum = r['main']['humidity']
        wind = r['wind']['speed']
        rain = "Будет дождь" if "rain" in r else "Без осадков"
        return (f"🌤 **Город: {city.capitalize()}**\n"
                f"🌡 Градусы: {round(temp)}°C\n"
                f"☁️ {desc}\n"
                f"💧 Влажность: {hum}%\n"
                f"💨 Ветер: {wind} м/с\n"
                f"☔️ Прогноз: {rain}\n"
                f"🕒 Время: {datetime.datetime.now().strftime('%H:%M')}")
    except: return "❌ Город не найден."

async def process_voice(m: types.Message, voice):
    wait = await m.answer("👂 Слушаю...")
    path_ogg, path_wav = f"{voice.file_id}.ogg", f"{voice.file_id}.wav"
    file = await bot.get_file(voice.file_id)
    await bot.download_file(file.file_path, path_ogg)
    AudioSegment.from_ogg(path_ogg).export(path_wav, format="wav")
    r = sr.Recognizer()
    with sr.AudioFile(path_wav) as src:
        try:
            text = r.recognize_google(r.record(src), language="ru-RU")
            await wait.edit_text(f"🎤 **Текст ГС:**\n\n_{text}_", parse_mode="Markdown")
        except: await wait.edit_text("❌ Не удалось разобрать голос.")
    for f in [path_ogg, path_wav]:
        if os.path.exists(f): os.remove(f)

# --- КЛАВИАТУРЫ ---
def main_kb():
    kb = ReplyKeyboardBuilder()
    kb.row(KeyboardButton(text="📈 Курсы"), KeyboardButton(text="🌤 Погода Костанай"))
    kb.row(KeyboardButton(text="👥 Анон Чат"), KeyboardButton(text="📧 Почта"))
    kb.row(KeyboardButton(text="🎲 Рулетка"), KeyboardButton(text="⚡️ Команды"))
    return kb.as_markup(resize_keyboard=True)

def anon_kb():
    kb = ReplyKeyboardBuilder()
    kb.row(KeyboardButton(text="⏭ Следующий"), KeyboardButton(text="❌ Стоп"))
    return kb.as_markup(resize_keyboard=True)

# --- ОБРАБОТЧИКИ ---

@dp.message(F.text == "/start")
async def start(m: types.Message):
    await m.answer(f"Привет, {m.from_user.first_name}!\nЯ бот **Флеш(Комбайн)**.\nВыбирай команду на кнопках!", reply_markup=main_kb())

# ПОЧТА (на 5-10 минут)
@dp.message(F.text.in_(["📧 Почта", "флеш почта"]))
async def mail_start(m: types.Message):
    login = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
    email = f"{login}@1secmail.com"
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="📥 Проверить входящие", callback_data=f"chk_{email}"))
    await m.answer(f"📬 Твоя временная почта:\n`{email}`", reply_markup=kb.as_markup(), parse_mode="Markdown")

@dp.callback_query(F.data.startswith("chk_"))
async def mail_check(c: types.CallbackQuery):
    email = c.data.replace("chk_", "")
    l, d = email.split('@')
    res = requests.get(f"https://www.1secmail.com/api/v1/?action=getMessages&login={l}&domain={d}").json()
    if not res: return await c.answer("Писем пока нет.", show_alert=True)
    msg = res[0]
    det = requests.get(f"https://www.1secmail.com/api/v1/?action=readMessage&login={l}&domain={d}&id={msg['id']}").json()
    await c.message.answer(f"📩 **От:** {msg['from']}\n**Тема:** {msg['subject']}\n**Текст:**\n{det['textBody']}")
    await c.answer()

# АНОН ЧАТ
@dp.message(F.text.in_(["👥 Анон Чат", "⏭ Следующий"]))
async def anon_find(m: types.Message):
    global anon_queue
    if m.chat.type != "private": return await m.answer("Только в ЛС!")
    uid = m.from_user.id
    if uid in anon_pairs:
        old = anon_pairs.pop(uid); anon_pairs.pop(old)
        await bot.send_message(old, "Собеседник ушел...", reply_markup=main_kb())
    if anon_queue == uid: return await m.answer("Ищем...")
    if anon_queue:
        p = anon_queue; anon_pairs[uid], anon_pairs[p] = p, uid; anon_queue = None
        await m.answer("🤝 Нашел!", reply_markup=anon_kb()); await bot.send_message(p, "🤝 Нашел!", reply_markup=anon_kb())
    else:
        anon_queue = uid; await m.answer("🔍 Поиск...", reply_markup=types.ReplyKeyboardRemove())

@dp.message(F.text == "❌ Стоп")
async def anon_stop(m: types.Message):
    uid = m.from_user.id
    if uid in anon_pairs:
        p = anon_pairs.pop(uid); anon_pairs.pop(p)
        await bot.send_message(p, "Чат окончен.", reply_markup=main_kb())
    await m.answer("Вы вышли.", reply_markup=main_kb())

# ГЛАСОВАЯ КОМАНДА (РЕПЛАЙ)
@dp.message(F.text.lower() == "флеш голос")
async def voice_cmd(m: types.Message):
    if m.reply_to_message and (m.reply_to_message.voice or m.reply_to_message.audio):
        v = m.reply_to_message.voice or m.reply_to_message.audio
        await process_voice(m, v)
    else: await m.reply("Ответь этой командой на ГС!")

# КУРСЫ И ПОГОДА
@dp.message(F.text.in_(["📈 Курсы", "курс"]))
async def rate_cmd(m: types.Message): await m.answer(get_rates())

@dp.message(F.text.lower().startswith("флеш погода"))
async def weather_cmd(m: types.Message):
    city = m.text[12:].strip() or "Костанай"
    await m.answer(get_weather(city))

@dp.message(F.text == "🎲 Рулетка")
async def roll(m: types.Message):
    await m.reply(random.choice(["💥 БАХ! Ты убит.", "🔫 Осечка!", "🔫 Осечка!", "🔫 Осечка!"]))

# МУЗЫКА (БЕЗ ЮТУБА - ЧИСТЫЙ SOUNDCLOUD)
@dp.message(F.text.lower().startswith("флеш музыка"))
async def music_sc(m: types.Message):
    q = m.text[12:].strip()
    if not q: return
    wait = await m.answer("🔍 Ищу в SoundCloud...")
    with YoutubeDL({'quiet': True}) as ydl:
        res = ydl.extract_info(f"scsearch5:{q}", download=False).get('entries', [])
    if not res: return await wait.edit_text("Ничего не нашел.")
    kb = InlineKeyboardBuilder()
    for e in res:
        sc_cache[e['id']] = e['webpage_url']
        kb.row(InlineKeyboardButton(text=e['title'][:40], callback_data=f"ms_{e['id']}"))
    await wait.edit_text("Результаты:", reply_markup=kb.as_markup())

# АНОН ПЕРЕСЫЛКА
@dp.message(F.text)
async def text_handler(m: types.Message):
    uid = m.from_user.id
    if uid in anon_pairs and not m.text.startswith("флеш"):
        return await bot.send_message(anon_pairs[uid], m.text)
    if m.text.lower().startswith("флеш вопрос"):
        await m.reply(await ask_gemini(m.text[12:]))

async def ask_gemini(p):
    try:
        r = await asyncio.to_thread(lambda: model.generate_content(p))
        return r.text
    except: return "❌ ИИ занят."

@dp.callback_query(F.data.startswith("ms_"))
async def download_sc(c: types.CallbackQuery):
    url = sc_cache.get(c.data.split("_")[1])
    await c.message.edit_text("📥 Качаю...")
    path = f"downloads/{c.data}.mp3"
    with YoutubeDL({'outtmpl': path, 'format': 'bestaudio'}) as ydl:
        await asyncio.to_thread(lambda: ydl.download([url]))
    await c.message.answer_audio(FSInputFile(path))
    if os.path.exists(path): os.remove(path)

async def main():
    if not os.path.exists('downloads'): os.makedirs('downloads')
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
