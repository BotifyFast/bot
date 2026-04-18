import os, random, string, asyncio, logging, requests, qrcode, pytesseract
from PIL import Image
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.types import FSInputFile
from yt_dlp import YoutubeDL

# Фикс путей ffmpeg
try:
    import static_ffmpeg
    static_ffmpeg.add_paths()
except:
    pass

logging.basicConfig(level=logging.INFO)

TOKEN = "8638601182:AAHAOf2wvybOOyhyt_PNijYkKkljJwGnN-g"
WEATHER_API_KEY = "c2b2631749aead62cfdc86b394e6399f"

bot = Bot(token=TOKEN)
dp = Dispatcher()

sc_cache, anon_queue, anon_pairs = {}, None, {}
CITIES = {"мск": "Moscow", "спб": "Saint Petersburg", "кст": "Kostanay", "аст": "Astana", "алм": "Almaty"}

# --- ЛОГИКА ПОЧТЫ (1secmail API) ---
def get_mail_address(uid):
    return f"flash_{uid}@1secmail.com"

def check_mail(uid):
    login = f"flash_{uid}"
    domain = "1secmail.com"
    url = f"https://www.1secmail.com/api/v1/?action=getMessages&login={login}&domain={domain}"
    try:
        msgs = requests.get(url).json()
        if not msgs: return "📭 Писем пока нет. Подожди немного и введи 'флеш письма' еще раз."
        
        last_id = msgs[0]['id']
        msg_url = f"https://www.1secmail.com/api/v1/?action=readMessage&login={login}&domain={domain}&id={last_id}"
        data = requests.get(msg_url).json()
        return f"📩 **От**: {data['from']}\n**Тема**: {data['subject']}\n\n**Текст**:\n{data['textBody'][:1000]}"
    except: return "❌ Ошибка при проверке почты."

# --- ОСТАЛЬНАЯ ЛОГИКА ---
def get_weather(text):
    clean = text.lower().replace("флеш", "").replace("погода", "").strip().split()
    if not clean: return "❌ Город?"
    city = CITIES.get(clean[0], clean[0])
    try:
        res = requests.get(f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_API_KEY}&units=metric&lang=ru").json()
        return f"🌤 В {res['name']}: {res['main']['temp']}°C, {res['weather'][0]['description']}"
    except: return "❌ Город не найден."

def get_exchange(text):
    text = text.lower().replace("флеш", "").replace("курс", "").strip()
    try:
        r = requests.get("https://www.cbr-xml-daily.ru/daily_json.js").json()
        u, k = r['Valute']['USD']['Value'], r['Valute']['KZT']['Value']/100
        if "доллар к тенге" in text: return f"💵➡️🇰🇿 1$ = {round(u/k, 2)} тенге"
        if "рубль к тенге" in text: return f"🇷🇺➡️🇰🇿 1₽ = {round(1/k, 2)} тенге"
        if "доллар" in text: return f"💵 1$ = {round(u, 2)} руб."
        return f"💰 TON: ${requests.get('https://api.coingecko.com/api/v3/simple/price?ids=the-open-network&vs_currencies=usd').json()['the-open-network']['usd']}"
    except: return "❌ Ошибка валют."

# --- ОБРАБОТЧИКИ ---
@dp.message(F.text.startswith("флеш"))
async def flash_cmds(m: types.Message):
    t = m.text.lower()
    uid = m.from_user.id
    
    if "погода" in t: await m.reply(get_weather(t))
    elif "курс" in t: await m.reply(get_exchange(t))
    elif "почта" in t:
        addr = get_mail_address(uid)
        await m.reply(f"📧 Твоя временная почта:\n`{addr}`\n\nИспользуй её для регистрации. Чтобы прочитать входящие, напиши: `флеш письма`", parse_mode="Markdown")
    elif "письма" in t:
        await m.reply(check_mail(uid), parse_mode="Markdown")
    elif "команды" in t: await m.reply("⚡️ Погода, Курс, Музыка, QR, Почта, Письма, Анекдот, Монетка")
    elif "анекдот" in t: await m.reply(f"🤡 {random.choice(['Штирлиц...', 'Гаишник: Дыхните!'])}")
    elif "музыка" in t:
        q = t.replace("флеш музыка", "").strip()
        if not q: return await m.reply("Что искать?")
        wait = await m.answer(f"🔍 Ищу {q}...")
        await search_music(m, q, wait)
    elif "qr" in t:
        url = m.text[8:].strip()
        qrcode.make(url).save(f"qr_{uid}.png")
        await m.answer_photo(FSInputFile(f"qr_{uid}.png"))
        os.remove(f"qr_{uid}.png")

@dp.message(F.text == "👥 Анонимный чат")
async def start_anon(m: types.Message):
    global anon_queue
    if anon_queue and anon_queue != m.from_user.id:
        p_id = anon_queue
        anon_pairs[m.from_user.id], anon_pairs[p_id] = p_id, m.from_user.id
        anon_queue = None
        await bot.send_message(p_id, "🤝 Собеседник найден!")
        await m.answer("🤝 Собеседник найден!")
    else:
        anon_queue = m.from_user.id
        await m.answer("🔍 Ищу...")

@dp.message(F.text)
async def global_handler(m: types.Message):
    if m.from_user.id in anon_pairs and m.chat.type == 'private':
        return await bot.send_message(anon_pairs[m.from_user.id], m.text)
    if m.text.startswith("http"):
        mode = 'audio' if "soundcloud.com" in m.text else 'video'
        await dl(m, m.text, mode)

# --- ЗАГРУЗКА ---
async def search_music(m, q, w):
    try:
        with YoutubeDL({'quiet': True, 'noplaylist': True}) as ydl:
            res = await asyncio.to_thread(lambda: ydl.extract_info(f"scsearch5:{q}", download=False)['entries'])
        if not res: return await w.edit_text("Пусто.")
        b = InlineKeyboardBuilder()
        for e in res:
            sc_cache[e['id']] = e['webpage_url']
            b.row(types.InlineKeyboardButton(text=f"🎵 {e['title'][:35]}", callback_data=f"sc_{e['id']}"))
        await m.answer("Выбери трек:", reply_markup=b.as_markup()); await w.delete()
    except: await w.edit_text("Ошибка поиска.")

async def dl(m, url, mode):
    s = await m.answer("⏳ Работаю...")
    try:
        o = {'outtmpl': 'downloads/%(id)s.%(ext)s', 'quiet': True, 'noplaylist': True}
        if mode == 'audio':
            o.update({'format': 'bestaudio', 'postprocessors': [{'key': 'FFmpegExtractAudio','preferredcodec': 'mp3'}]})
        with YoutubeDL(o) as ydl:
            info = await asyncio.to_thread(lambda: ydl.extract_info(url, download=True))
            p = ydl.prepare_filename(info)
            if mode == 'audio': p = os.path.splitext(p)[0] + ".mp3"
        await (m.answer_video(FSInputFile(p)) if mode == 'video' else m.answer_audio(FSInputFile(p)))
        os.remove(p); await s.delete()
    except Exception as e: await s.edit_text(f"❌ Ошибка загрузки. Проверь ffmpeg!")

@dp.callback_query(F.data.startswith("sc_"))
async def sc_callback(c: types.CallbackQuery):
    url = sc_cache.get(c.data.split("_")[1])
    await c.message.delete(); await dl(c.message, url, "audio")

async def main():
    if not os.path.exists('downloads'): os.makedirs('downloads')
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
