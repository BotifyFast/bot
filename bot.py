import os, random, asyncio, logging, requests, string
from PIL import Image
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.types import FSInputFile, InlineKeyboardButton
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

genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

bot = Bot(token=TOKEN)
dp = Dispatcher()

# Кэш и очереди
sc_cache = {}
anon_queue = None
anon_pairs = {} # {user_id: partner_id}

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
        usd, eur, kzt = r['Valute']['USD']['Value'], r['Valute']['EUR']['Value'], r['Valute']['KZT']['Value']/100
        crypto = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,the-open-network&vs_currencies=usd").json()
        return (f"📈 **Курсы валют:**\n💵 USD: {round(usd,2)}₽ | {round(usd/kzt,2)}₸\n"
                f"💶 EUR: {round(eur,2)}₽\n₿ BTC: ${crypto['bitcoin']['usd']}\n💎 TON: ${crypto['the-open-network']['usd']}")
    except: return "❌ Ошибка API курсов."

# --- ОБРАБОТЧИКИ ---

# 1. Анонимный чат
@dp.message(F.text.in_(["флеш анон найти", "👥 Анон Чат"]))
async def find_partner(m: types.Message):
    global anon_queue
    uid = m.from_user.id
    if uid in anon_pairs: return await m.answer("Ты уже в чате! Напиши 'флеш анон стоп' для выхода.")
    if anon_queue == uid: return await m.answer("Поиск уже идет...")
    
    if anon_queue:
        partner = anon_queue
        anon_pairs[uid], anon_pairs[partner] = partner, uid
        anon_queue = None
        await bot.send_message(partner, "🤝 Собеседник найден! Можете общаться.")
        await m.answer("🤝 Собеседник найден! Напиши что-нибудь.")
    else:
        anon_queue = uid
        await m.answer("🔍 Ищу собеседника...")

@dp.message(F.text == "флеш анон стоп")
async def stop_anon(m: types.Message):
    uid = m.from_user.id
    if uid in anon_pairs:
        p = anon_pairs.pop(uid); anon_pairs.pop(p)
        await bot.send_message(p, "❌ Собеседник покинул чат.")
        await m.answer("Вы вышли из чата.")
    else: await m.answer("Ты не в чате.")

# 2. Флеш Ролл
@dp.message(F.text.startswith("флеш ролл"))
async def roll_cmd(m: types.Message):
    try:
        limit = int(m.text.split()[2])
    except: limit = 100
    res = random.randint(1, limit)
    await m.reply(f"🎲 Твой результат: **{res}** из {limit}")

# 3. Голос в текст
@dp.message(F.voice)
async def voice_h(m: types.Message):
    if m.caption and "флеш голос" in m.caption.lower():
        wait = await m.answer("👂 Слушаю...")
        fid = m.voice.file_id
        path_ogg = f"downloads/{fid}.ogg"
        path_wav = f"downloads/{fid}.wav"
        file = await bot.get_file(fid)
        await bot.download_file(file.file_path, path_ogg)
        
        # Конвертация ogg -> wav
        AudioSegment.from_ogg(path_ogg).export(path_wav, format="wav")
        
        r = sr.Recognizer()
        with sr.AudioFile(path_wav) as source:
            audio = r.record(source)
            try:
                text = r.recognize_google(audio, language="ru-RU")
                await wait.edit_text(f"🎤 Распознано:\n\n_{text}_", parse_mode="Markdown")
            except: await wait.edit_text("❌ Не удалось разобрать речь.")
        
        for p in [path_ogg, path_wav]:
            if os.path.exists(p): os.remove(p)

# 4. Фото в текст / ИИ Фото
@dp.message(F.photo)
async def photo_handler(m: types.Message):
    cap = m.caption.lower() if m.caption else ""
    if "флеш фото" in cap:
        wait = await m.answer("⏳ Анализирую...")
        fid = m.photo[-1].file_id
        path = f"downloads/{fid}.jpg"
        file = await bot.get_file(fid)
        await bot.download_file(file.file_path, path)
        
        if "флеш текст" in cap:
            text = pytesseract.image_to_string(Image.open(path), lang='rus+eng')
            await wait.edit_text(f"📝 Текст:\n`{text}`")
        else:
            ans = await ask_gemini(cap.replace("флеш фото", "").strip() or "Что на фото?", path)
            await wait.edit_text(ans)
        os.remove(path)

# 5. Основной текст и Музыка
@dp.message(F.text)
async def text_handler(m: types.Message):
    uid = m.from_user.id
    if uid in anon_pairs and not m.text.startswith("флеш"):
        return await bot.send_message(anon_pairs[uid], m.text)

    t = m.text.lower()
    if t.startswith("флеш вопрос"):
        ans = await ask_gemini(m.text[12:].strip())
        await m.reply(ans)
    elif "курс" in t: await m.reply(get_rates())
    elif "музыка" in t:
        q = t.replace("флеш музыка", "").strip()
        wait = await m.answer(f"🔍 SoundCloud: {q}...")
        with YoutubeDL({'quiet': True}) as ydl:
            res = ydl.extract_info(f"scsearch5:{q}", download=False).get('entries', [])
        if not res: return await wait.edit_text("Не нашел.")
        kb = InlineKeyboardBuilder()
        for e in res:
            sc_cache[e['id']] = e['webpage_url']
            kb.row(InlineKeyboardButton(text=f"🎵 {e['title'][:35]}", callback_data=f"ms_{e['id']}"))
        await m.answer("Выбери трек:", reply_markup=kb.as_markup())
    elif t.startswith("http"): await dl_media(m, m.text, "video")

async def dl_media(m, url, mode):
    s = await m.answer("⏳...")
    p = ""
    try:
        opts = {'outtmpl': 'downloads/%(id)s.%(ext)s', 'quiet': True}
        if mode == "mp3":
            opts.update({'format': 'bestaudio', 'postprocessors': [{'key': 'FFmpegExtractAudio','preferredcodec': 'mp3'}]})
        with YoutubeDL(opts) as ydl:
            info = await asyncio.to_thread(lambda: ydl.extract_info(url, download=True))
            p = ydl.prepare_filename(info)
            if mode == "mp3": p = os.path.splitext(p)[0] + ".mp3"
        await (m.answer_video(FSInputFile(p)) if mode == "video" else m.answer_audio(FSInputFile(p)))
    except: await s.edit_text("❌ Ошибка")
    finally:
        if p and os.path.exists(p): os.remove(p)
        await s.delete()

@dp.callback_query(F.data.startswith("ms_"))
async def music_cb(c: types.CallbackQuery):
    url = sc_cache.get(c.data.split("_")[1])
    await c.message.delete(); await dl_media(c.message, url, "mp3")

async def main():
    if not os.path.exists('downloads'): os.makedirs('downloads')
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
