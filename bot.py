import os, random, asyncio, logging, requests
from PIL import Image
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import FSInputFile, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from yt_dlp import YoutubeDL
import google.generativeai as genai
import pytesseract
from pydub import AudioSegment
import speech_recognition as sr

logging.basicConfig(level=logging.INFO)

# --- КОНФИГ ---
TOKEN = "8638601182:AAHAOf2wvybOOyhyt_PNijYkKkljJwGnN-g"
WEATHER_KEY = "c2b2631749aead62cfdc86b394e6399f"
GEMINI_KEY = "AIzaSyCwd4xf-PWyayAdL-yp3xx4-Tlm4aywGXQ"

# Исправленная настройка ИИ (пробуем версию flash)
genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

bot = Bot(token=TOKEN)
dp = Dispatcher()

sc_cache = {}
anon_queue = None
anon_pairs = {} 

# --- ФУНКЦИИ ПОМОЩНИКИ ---

async def ask_gemini(prompt, photo_path=None):
    try:
        # Если промпт пустой, даем стандартный запрос
        text_query = prompt if prompt.strip() else "Что тут происходит?"
        if photo_path:
            img = Image.open(photo_path)
            res = await asyncio.to_thread(lambda: model.generate_content([text_query, img]))
        else:
            res = await asyncio.to_thread(lambda: model.generate_content(text_query))
        return res.text
    except Exception as e:
        logging.error(f"AI Error: {e}")
        return "❌ ИИ временно недоступен. Попробуй позже."

def get_weather(city="Костанай"):
    try:
        url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_KEY}&units=metric&lang=ru"
        r = requests.get(url).json()
        temp = r['main']['temp']
        desc = r['weather'][0]['description']
        return f"🌡 Погода в {city}: {round(temp)}°C, {desc}"
    except: return "❌ Не удалось найти такой город."

def get_rates():
    try:
        r = requests.get("https://www.cbr-xml-daily.ru/daily_json.js").json()
        usd = r['Valute']['USD']['Value']
        eur = r['Valute']['EUR']['Value']
        kzt_rate = r['Valute']['KZT']['Value'] / 100
        crypto = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,the-open-network&vs_currencies=usd").json()
        return (f"📈 **Курсы валют:**\n"
                f"💵 USD: {round(usd, 2)}₽ | {round(usd/kzt_rate, 2)}₸\n"
                f"💶 EUR: {round(eur, 2)}₽\n"
                f"₿ BTC: ${crypto['bitcoin']['usd']}\n"
                f"💎 TON: ${crypto['the-open-network']['usd']}")
    except: return "❌ Ошибка курсов."

# --- ОБРАБОТЧИКИ ---

# Список команд
@dp.message(F.text.in_(["флеш команды", "⚡️ Команды", "/start"]))
async def send_help(m: types.Message):
    help_text = (
        "🤖 **Команды комбайна:**\n\n"
        "📈 `курс` — валюты и крипта\n"
        "🌤 `флеш погода [город]` — погода\n"
        "🎵 `флеш музыка [название]` — поиск в SoundCloud\n"
        "🎲 `флеш ролл [число]` — рандом\n"
        "👥 `флеш анон найти` — анонимный чат\n"
        "🎤 `флеш голос` (в подписи к ГС) — в текст\n"
        "🖼 `флеш фото` (в подписи) — ИИ анализ\n"
        "📝 `флеш текст` (в подписи к фото) — вытащить текст\n"
        "❓ `флеш вопрос [текст]` — чат с ИИ"
    )
    await m.answer(help_text, parse_mode="Markdown")

# Анонимный чат
@dp.message(F.text.lower() == "флеш анон найти")
async def find_partner(m: types.Message):
    global anon_queue
    uid = m.from_user.id
    if uid in anon_pairs: return await m.answer("Ты уже в чате!")
    if anon_queue == uid: return await m.answer("Поиск...")
    if anon_queue:
        p = anon_queue; anon_pairs[uid], anon_pairs[p] = p, uid; anon_queue = None
        await bot.send_message(p, "🤝 Собеседник найден!"); await m.answer("🤝 Нашел!")
    else:
        anon_queue = uid; await m.answer("🔍 Ищу...")

@dp.message(F.text == "флеш анон стоп")
async def stop_anon(m: types.Message):
    uid = m.from_user.id
    if uid in anon_pairs:
        p = anon_pairs.pop(uid); anon_pairs.pop(p)
        await bot.send_message(p, "❌ Собеседник отключился."); await m.answer("Вы вышли.")
    else: await m.answer("Ты не в чате.")

# Голос в текст
@dp.message(F.voice)
async def voice_proc(m: types.Message):
    if m.caption and "флеш голос" in m.caption.lower():
        wait = await m.answer("👂 Слушаю...")
        fid = m.voice.file_id
        path_ogg, path_wav = f"{fid}.ogg", f"{fid}.wav"
        file = await bot.get_file(fid)
        await bot.download_file(file.file_path, path_ogg)
        AudioSegment.from_ogg(path_ogg).export(path_wav, format="wav")
        r = sr.Recognizer()
        with sr.AudioFile(path_wav) as src:
            try:
                text = r.recognize_google(r.record(src), language="ru-RU")
                await wait.edit_text(f"🎤 Текст: {text}")
            except: await wait.edit_text("❌ Не разобрал.")
        for f in [path_ogg, path_wav]: 
            if os.path.exists(f): os.remove(f)

# Фото
@dp.message(F.photo)
async def photo_proc(m: types.Message):
    cap = m.caption.lower() if m.caption else ""
    if "флеш фото" in cap or "флеш текст" in cap:
        wait = await m.answer("⏳ Работаю...")
        path = f"downloads/{m.photo[-1].file_id}.jpg"
        await bot.download(m.photo[-1], destination=path)
        if "текст" in cap:
            text = pytesseract.image_to_string(Image.open(path), lang='rus+eng')
            await wait.edit_text(f"📝 Текст с фото:\n\n{text or 'Не нашел текста'}")
        else:
            ans = await ask_gemini(cap.replace("флеш фото", ""), path)
            await wait.edit_text(ans)
        if os.path.exists(path): os.remove(path)

# Главный обработчик текста
@dp.message(F.text)
async def text_handler(m: types.Message):
    uid = m.from_user.id
    if uid in anon_pairs and not m.text.lower().startswith("флеш"):
        return await bot.send_message(anon_pairs[uid], m.text)

    t = m.text.lower()
    if t.startswith("флеш ролл"):
        try: n = int(t.split()[2])
        except: n = 100
        await m.reply(f"🎲 Результат: **{random.randint(1, n)}** (0-{n})")
    elif t.startswith("флеш погода"):
        city = m.text[12:].strip() or "Костанай"
        await m.reply(get_weather(city))
    elif "курс" in t:
        await m.reply(get_rates())
    elif t.startswith("флеш музыка"):
        q = m.text[12:].strip()
        if not q: return await m.answer("Напиши что искать.")
        wait = await m.answer("🔍 SoundCloud...")
        with YoutubeDL({'quiet': True}) as ydl:
            res = ydl.extract_info(f"scsearch5:{q}", download=False).get('entries', [])
        if not res: return await wait.edit_text("Ничего не нашел.")
        kb = InlineKeyboardBuilder()
        for e in res:
            sc_cache[e['id']] = e['webpage_url']
            kb.row(InlineKeyboardButton(text=f"🎵 {e['title'][:40]}", callback_data=f"ms_{e['id']}"))
        await m.answer("Что качаем?", reply_markup=kb.as_markup())
    elif t.startswith("флеш вопрос"):
        await m.reply(await ask_gemini(m.text[12:]))

async def download_audio(m, url):
    s = await m.answer("📥 Качаю...")
    path = ""
    try:
        opts = {'outtmpl': 'downloads/%(id)s.mp3', 'format': 'bestaudio', 'postprocessors': [{'key': 'FFmpegExtractAudio','preferredcodec': 'mp3'}]}
        with YoutubeDL(opts) as ydl:
            info = await asyncio.to_thread(lambda: ydl.extract_info(url, download=True))
            path = ydl.prepare_filename(info).replace(".webm", ".mp3").replace(".m4a", ".mp3")
        await m.answer_audio(FSInputFile(path))
    except Exception as e:
        await s.edit_text(f"❌ Ошибка: {e}")
    finally:
        if path and os.path.exists(path): os.remove(path)
        await s.delete()

@dp.callback_query(F.data.startswith("ms_"))
async def music_callback(c: types.CallbackQuery):
    url = sc_cache.get(c.data.split("_")[1])
    await c.message.delete()
    await download_audio(c.message, url)

async def main():
    if not os.path.exists('downloads'): os.makedirs('downloads')
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
