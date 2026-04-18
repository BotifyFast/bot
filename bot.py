import os, random, asyncio, logging, requests, datetime, string, qrcode
from PIL import Image
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import FSInputFile, InlineKeyboardButton, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from yt_dlp import YoutubeDL
import google.generativeai as genai
from pydub import AudioSegment
import speech_recognition as sr

logging.basicConfig(level=logging.INFO)

# --- КОНФИГ ---
TOKEN = "8638601182:AAHAOf2wvybOOyhyt_PNijYkKkljJwGnN-g"
WEATHER_KEY = "c2b2631749aead62cfdc86b394e6399f"
GEMINI_KEY = "AIzaSyCwd4xf-PWyayAdL-yp3xx4-Tlm4aywGXQ"

genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

bot = Bot(token=TOKEN)
dp = Dispatcher()

sc_cache = {}

# --- КЛАВИАТУРА ---
def main_kb():
    kb = ReplyKeyboardBuilder()
    buttons = [
        "🌤 Погода", "📈 Курс", "📧 Почта", 
        "🎵 Музыка", "🎬 Видео", "🎲 Ролл", 
        "🔫 Рулетка", "🪙 Монета", "📲 QR Код", "⚡️ Команды"
    ]
    for btn in buttons:
        kb.add(KeyboardButton(text=btn))
    kb.adjust(3, 3, 2, 2)
    return kb.as_markup(resize_keyboard=True)

# --- ФУНКЦИИ МОЗГА ---

def get_rates():
    try:
        r = requests.get("https://www.cbr-xml-daily.ru/daily_json.js").json()
        usd, eur = r['Valute']['USD']['Value'], r['Valute']['EUR']['Value']
        kzt = r['Valute']['KZT']['Value'] / 100
        crypto = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,the-open-network&vs_currencies=usd").json()
        return (f"📊 **Курсы валют:**\n\n"
                f"💵 Доллар: {round(usd, 2)}₽ | {round(usd/kzt, 2)}₸\n"
                f"💶 Евро: {round(eur, 2)}₽ | {round(eur/kzt, 2)}₸\n"
                f"🇰🇿 Тенге: {round(kzt, 2)}₽\n"
                f"₿ Bitcoin: ${crypto['bitcoin']['usd']:,}\n"
                f"💎 TON: ${crypto['the-open-network']['usd']}")
    except: return "❌ Ошибка курсов."

def get_weather(city):
    try:
        url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_KEY}&units=metric&lang=ru"
        r = requests.get(url).json()
        return (f"🌤 **Погода: {city.capitalize()}**\n"
                f"🌡 Температура: {round(r['main']['temp'])}°C\n"
                f"☁️ Статус: {r['weather'][0]['description']}\n"
                f"🕒 Время: {datetime.datetime.now().strftime('%H:%M')}")
    except: return "❌ Город не найден."

# --- ОБРАБОТЧИКИ ---

@dp.message(F.text == "/start")
async def start_cmd(m: types.Message):
    text = (f"Привет! Я бот **Флеш комбайн** ⚡️\n\n"
            "Я умею:\n"
            "• 🌤 Показывать погоду\n"
            "• 📧 Создавать почту на 5 минут\n"
            "• 📈 Следить за курсом (USD, RUB, KZT, BTC, TON)\n"
            "• 🎤 Переводить ГС в текст (через реплай)\n"
            "• 🎵 Качать музыку из SoundCloud\n"
            "• 🎬 Качать видео из TT/Insta\n"
            "• 📲 Делать QR-коды\n"
            "• 🎲 Игры: Ролл, Рулетка, Монета")
    await m.answer(text, reply_markup=main_kb(), parse_mode="Markdown")

# ФЛЕШ КОМАНДЫ
@dp.message(F.text.in_(["⚡️ Команды", "флеш команды"]))
async def help_cmd(m: types.Message):
    await m.answer("📝 **Список всех команд:**\n\n"
                   "• `флеш погода [город]`\n"
                   "• `флеш почта` — временный ящик\n"
                   "• `флеш курс` — валюты\n"
                   "• `флеш ролл [от-до]`\n"
                   "• `флеш рулетка` — пан или пропал\n"
                   "• `флеш монета` — орел/решка\n"
                   "• `флеш голос` — (реплай на ГС)\n"
                   "• `флеш музыка [название]`\n"
                   "• `флеш видео [ссылка]`\n"
                   "• `флеш qr [ссылка]`")

# ПОЧТА
@dp.message(F.text.in_(["📧 Почта", "флеш почта"]))
async def mail_cmd(m: types.Message):
    login = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
    email = f"{login}@1secmail.com"
    kb = InlineKeyboardBuilder().row(InlineKeyboardButton(text="📥 Проверить письма", callback_data=f"chk_{email}"))
    await m.answer(f"📬 Твоя почта на 5 минут:\n`{email}`", reply_markup=kb.as_markup(), parse_mode="Markdown")

@dp.callback_query(F.data.startswith("chk_"))
async def mail_check(c: types.CallbackQuery):
    email = c.data.replace("chk_", "")
    l, d = email.split('@')
    res = requests.get(f"https://www.1secmail.com/api/v1/?action=getMessages&login={l}&domain={d}").json()
    if not res: return await c.answer("Писем нет", show_alert=True)
    msg = res[0]
    det = requests.get(f"https://www.1secmail.com/api/v1/?action=readMessage&login={l}&domain={d}&id={msg['id']}").json()
    await c.message.answer(f"📩 **От:** {msg['from']}\n**Текст:**\n{det['textBody']}")

# ГУДОК (Голос в текст)
@dp.message(F.text.lower() == "флеш голос")
async def voice_to_text(m: types.Message):
    if not m.reply_to_message or not (m.reply_to_message.voice or m.reply_to_message.audio):
        return await m.reply("Ответь на ГС этой командой!")
    
    wait = await m.answer("⌛️ Расшифровываю...")
    v = m.reply_to_message.voice or m.reply_to_message.audio
    path_ogg, path_wav = f"{v.file_id}.ogg", f"{v.file_id}.wav"
    
    file = await bot.get_file(v.file_id)
    await bot.download_file(file.file_path, path_ogg)
    AudioSegment.from_ogg(path_ogg).export(path_wav, format="wav")
    
    r = sr.Recognizer()
    with sr.AudioFile(path_wav) as src:
        try:
            text = r.recognize_google(r.record(src), language="ru-RU")
            await wait.edit_text(f"🎤 **Текст:** {text}")
        except: await wait.edit_text("❌ Не распознал.")
    
    for f in [path_ogg, path_wav]: 
        if os.path.exists(f): os.remove(f)

# QR КОД
@dp.message(F.text.startswith("флеш qr") | (F.text == "📲 QR Код"))
async def make_qr(m: types.Message):
    link = m.text.replace("флеш qr", "").strip()
    if not link: return await m.answer("Напиши ссылку после команды!")
    img = qrcode.make(link)
    img.save("qr.png")
    await m.answer_photo(FSInputFile("qr.png"), caption=f"Твой QR для: {link}")

# ИГРЫ
@dp.message(F.text.startswith("флеш ролл") | (F.text == "🎲 Ролл"))
async def roll_cmd(m: types.Message):
    try:
        parts = m.text.split()
        if len(parts) == 3: # флеш ролл 1-100
            start, end = map(int, parts[2].split('-'))
            res = random.randint(start, end)
        else: res = random.randint(1, 100)
        await m.reply(f"🎲 Результат: **{res}**")
    except: await m.reply("Пиши так: `флеш ролл 1-500`")

@dp.message(F.text == "флеш рулетка" or F.text == "🔫 Рулетка")
async def roulette(m: types.Message):
    await m.reply(random.choice(["💥 БАХ! Ты проиграл.", "🔫 Осечка! Повезло."]))

@dp.message(F.text == "флеш монета" or F.text == "🪙 Монета")
async def coin(m: types.Message):
    await m.reply(f"🪙 Выпало: {random.choice(['Орел', 'Решка'])}")

# МУЗЫКА И ВИДЕО (SoundCloud, TT, Insta)
@dp.message(F.text.startswith("флеш музыка") | (F.text == "🎵 Музыка"))
async def music_sc(m: types.Message):
    q = m.text.replace("флеш музыка", "").replace("🎵 Музыка", "").strip()
    if not q: return await m.answer("Что искать?")
    wait = await m.answer("🔍 Ищу в SoundCloud...")
    with YoutubeDL({'quiet': True, 'noplaylist': True}) as ydl:
        res = ydl.extract_info(f"scsearch5:{q}", download=False).get('entries', [])
    if not res: return await wait.edit_text("Не нашел.")
    kb = InlineKeyboardBuilder()
    for e in res:
        sc_cache[e['id']] = e['webpage_url']
        kb.row(InlineKeyboardButton(text=e['title'][:40], callback_data=f"ms_{e['id']}"))
    await wait.edit_text("Выбери трек:", reply_markup=kb.as_markup())

@dp.message(F.text.startswith("флеш видео") | (F.text == "🎬 Видео"))
async def video_dl(m: types.Message):
    url = m.text.replace("флеш видео", "").replace("🎬 Видео", "").strip()
    if not url: return await m.answer("Дай ссылку на TikTok/Insta!")
    wait = await m.answer("📥 Качаю видео...")
    path = f"downloads/{m.from_user.id}.mp4"
    try:
        with YoutubeDL({'outtmpl': path, 'format': 'mp4/best'}) as ydl:
            await asyncio.to_thread(lambda: ydl.download([url]))
        await m.answer_video(FSInputFile(path))
    except Exception as e: await wait.edit_text(f"❌ Ошибка: {e}")
    finally:
        if os.path.exists(path): os.remove(path)

# КУРСЫ И ПОГОДА (Обычные текстовые триггеры)
@dp.message(F.text.in_(["📈 Курс", "флеш курс"]))
async def rates_trigger(m: types.Message): await m.answer(get_rates())

@dp.message(F.text.startswith("флеш погода") | (F.text == "🌤 Погода"))
async def weather_trigger(m: types.Message):
    city = m.text.replace("флеш погода", "").replace("🌤 Погода", "").strip() or "Костанай"
    await m.answer(get_weather(city))

@dp.callback_query(F.data.startswith("ms_"))
async def download_sc(c: types.CallbackQuery):
    url = sc_cache.get(c.data.split("_")[1])
    await c.message.edit_text("📥 Загрузка аудио...")
    path = f"downloads/{c.data}.mp3"
    with YoutubeDL({'outtmpl': path, 'format': 'bestaudio', 'postprocessors': [{'key': 'FFmpegExtractAudio','preferredcodec': 'mp3'}]}) as ydl:
        await asyncio.to_thread(lambda: ydl.download([url]))
    await c.message.answer_audio(FSInputFile(path))
    if os.path.exists(path): os.remove(path)

async def main():
    if not os.path.exists('downloads'): os.makedirs('downloads')
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
