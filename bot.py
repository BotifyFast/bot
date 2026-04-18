import os, random, asyncio, logging, requests, string
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

# --- ДАННЫЕ (Твои ключи) ---
TOKEN = "8638601182:AAHAOf2wvybOOyhyt_PNijYkKkljJwGnN-g"
WEATHER_KEY = "c2b2631749aead62cfdc86b394e6399f"
GEMINI_KEY = "AIzaSyCwd4xf-PWyayAdL-yp3xx4-Tlm4aywGXQ"

# Настройка ИИ
genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

bot = Bot(token=TOKEN)
dp = Dispatcher()

# Глобальные переменные для анонимного чата
sc_cache = {}
anon_queue = None
anon_pairs = {} 

# --- ФУНКЦИИ ---
async def ask_gemini(prompt, photo_path=None):
    try:
        if photo_path:
            img = Image.open(photo_path)
            res = await asyncio.to_thread(lambda: model.generate_content([prompt, img]))
        else:
            res = await asyncio.to_thread(lambda: model.generate_content(prompt))
        return res.text
    except Exception as e:
        return f"❌ Ошибка ИИ: {str(e)[:50]}"

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
    except: return "❌ Ошибка API курсов."

# --- ОБРАБОТЧИКИ ---

# Анонимный чат
@dp.message(F.text.in_(["флеш анон найти", "👥 Анон Чат"]))
async def find_partner(m: types.Message):
    global anon_queue
    uid = m.from_user.id
    if uid in anon_pairs: return await m.answer("Ты уже в чате! 'флеш анон стоп' для выхода.")
    if anon_queue == uid: return await m.answer("Ищу собеседника...")
    if anon_queue:
        p = anon_queue; anon_pairs[uid], anon_pairs[p] = p, uid; anon_queue = None
        await bot.send_message(p, "🤝 Собеседник найден!")
        await m.answer("🤝 Собеседник найден!")
    else:
        anon_queue = uid; await m.answer("🔍 Поиск...")

@dp.message(F.text == "флеш анон стоп")
async def stop_anon(m: types.Message):
    uid = m.from_user.id
    if uid in anon_pairs:
        p = anon_pairs.pop(uid); anon_pairs.pop(p)
        await bot.send_message(p, "❌ Собеседник вышел."); await m.answer("Вы вышли.")
    else: await m.answer("Ты не в чате.")

# Ролл
@dp.message(F.text.startswith("флеш ролл"))
async def roll(m: types.Message):
    try: num = int(m.text.split()[2])
    except: num = 100
    await m.reply(f"🎲 Результат: **{random.randint(1, num)}** (0-{num})")

# Голос в текст
@dp.message(F.voice)
async def voice_process(m: types.Message):
    if m.caption and "флеш голос" in m.caption.lower():
        wait = await m.answer("👂 Слушаю...")
        fid = m.voice.file_id
        path_ogg, path_wav = f"{fid}.ogg", f"{fid}.wav"
        file = await bot.get_file(fid)
        await bot.download_file(file.file_path, path_ogg)
        AudioSegment.from_ogg(path_ogg).export(path_wav, format="wav")
        r = sr.Recognizer()
        with sr.AudioFile(path_wav) as source:
            try:
                text = r.recognize_google(r.record(source), language="ru-RU")
                await wait.edit_text(f"🎤 Текст: _{text}_", parse_mode="Markdown")
            except: await wait.edit_text("❌ Не понял.")
        for f in [path_ogg, path_wav]: 
            if os.path.exists(f): os.remove(f)

# Фото в текст / ИИ
@dp.message(F.photo)
async def photo_process(m: types.Message):
    cap = m.caption.lower() if m.caption else ""
    if "флеш фото" in cap:
        wait = await m.answer("⏳...")
        path = f"{m.photo[-1].file_id}.jpg"
        await bot.download(m.photo[-1], destination=path)
        if "текст" in cap:
            text = pytesseract.image_to_string(Image.open(path), lang='rus+eng')
            await wait.edit_text(f"📝 Текст:\n`{text or 'Пусто'}`")
        else:
            ans = await ask_gemini(cap.replace("флеш фото", ""), path)
            await wait.edit_text(ans)
        os.remove(path)

# Музыка и Текст
@dp.message(F.text)
async def global_handler(m: types.Message):
    uid = m.from_user.id
    if uid in anon_pairs and not m.text.startswith("флеш"):
        return await bot.send_message(anon_pairs[uid], m.text)
    
    t = m.text.lower()
    if t.startswith("флеш вопрос"):
        await m.reply(await ask_gemini(m.text[12:]))
    elif "курс" in t:
        await m.reply(get_rates())
    elif "музыка" in t:
        q = t.replace("флеш музыка", "").strip()
        wait = await m.answer("🔍 SoundCloud...")
        with YoutubeDL({'quiet': True}) as ydl:
            res = ydl.extract_info(f"scsearch5:{q}", download=False).get('entries', [])
        if not res: return await wait.edit_text("Ничего.")
        kb = InlineKeyboardBuilder()
        for e in res:
            sc_cache[e['id']] = e['webpage_url']
            kb.row(InlineKeyboardButton(text=e['title'][:40], callback_data=f"ms_{e['id']}"))
        await m.answer("Выбери:", reply_markup=kb.as_markup())

async def dl(m, url):
    s = await m.answer("⏳")
    p = ""
    try:
        opts = {'outtmpl': '%(id)s.mp3', 'format': 'bestaudio', 'postprocessors': [{'key': 'FFmpegExtractAudio','preferredcodec': 'mp3'}]}
        with YoutubeDL(opts) as ydl:
            info = await asyncio.to_thread(lambda: ydl.extract_info(url, download=True))
            p = ydl.prepare_filename(info)
        await m.answer_audio(FSInputFile(p))
    except: await s.edit_text("Ошибка")
    finally:
        if p and os.path.exists(p): os.remove(p)
        await s.delete()

@dp.callback_query(F.data.startswith("ms_"))
async def music_cb(c: types.CallbackQuery):
    url = sc_cache.get(c.data.split("_")[1])
    await c.message.delete(); await dl(c.message, url)

async def main():
    if not os.path.exists('downloads'): os.makedirs('downloads')
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
