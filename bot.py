import os, random, asyncio, logging, requests, qrcode, pytesseract, string
from PIL import Image
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.types import FSInputFile, InlineKeyboardButton
from yt_dlp import YoutubeDL
import google.generativeai as genai

logging.basicConfig(level=logging.INFO)

# --- КОНФИГ ---
TOKEN = "8638601182:AAHAOf2wvybOOyhyt_PNijYkKkljJwGnN-g"
WEATHER_KEY = "c2b2631749aead62cfdc86b394e6399f"
GEMINI_KEY = "AIzaSyCwd4xf-PWyayAdL-yp3xx4-Tlm4aywGXQ" 

genai.configure(api_key=GEMINI_KEY)
# Настройка модели
model = genai.GenerativeModel('gemini-1.5-flash')

bot = Bot(token=TOKEN)
dp = Dispatcher()

sc_cache, anon_pairs, anon_queue = {}, {}, None

def get_main_kb():
    kb = ReplyKeyboardBuilder()
    kb.button(text="🤖 Спросить ИИ")
    kb.button(text="🎬 Видео").button(text="🎵 Музыка")
    kb.button(text="📧 Почта").button(text="🌦 Погода")
    kb.button(text="📈 Курс").button(text="🤡 Анекдот")
    kb.button(text="⚡️ Команды")
    kb.adjust(2)
    return kb.as_markup(resize_keyboard=True)

# --- ФУНКЦИИ ---
async def ask_gemini(prompt, photo_path=None):
    try:
        if photo_path:
            img = Image.open(photo_path)
            response = await asyncio.to_thread(lambda: model.generate_content([prompt, img]))
        else:
            response = await asyncio.to_thread(lambda: model.generate_content(prompt))
        return response.text
    except Exception as e:
        return f"❌ Ошибка ИИ: {str(e)}"

def get_rates():
    try:
        r = requests.get("https://www.cbr-xml-daily.ru/daily_json.js").json()
        usd = r['Valute']['USD']['Value']
        kzt = r['Valute']['KZT']['Value'] / 100
        crypto = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,the-open-network&vs_currencies=usd").json()
        return (f"💵 Доллар: {round(usd, 2)} ₽\n🇰🇿 Тенге: {round(usd/kzt, 2)} ₸\n₿ BTC: ${crypto['bitcoin']['usd']}\n💎 TON: ${crypto['the-open-network']['usd']}")
    except: return "❌ Ошибка API курсов."

# --- ОБРАБОТЧИКИ ---

@dp.message(F.text.in_(["⚡️ Команды", "флеш команды"]))
async def cmds(m: types.Message):
    await m.reply("🤖 `флеш вопрос` | 📈 `флеш курс` | 🎵 `флеш музыка` | 🌦 `флеш погода` | 📧 `флеш почта` | 🪙 `флеш монета` | 🔫 `флеш рулетка` | 🖼 `флеш qr [ссылка]`")

@dp.message(F.text.in_(["📈 Курс", "флеш курс"]))
async def rates(m: types.Message): await m.reply(get_rates())

@dp.message(F.text.in_(["🤡 Анекдот", "флеш анекдот"]))
async def joke(m: types.Message):
    res = requests.get("http://rzhunemogu.ru/Widjet.aspx?type=1").text # Юзаем другой API для надежности
    await m.reply(f"🤣 {res[45:-17]}")

@dp.message(F.text == "флеш монета")
async def coin(m: types.Message): await m.reply(f"🪙 {random.choice(['Орёл', 'Решка'])}")

@dp.message(F.text == "флеш рулетка")
async def roulette(m: types.Message):
    await m.reply("💥 БАБАХ!" if random.randint(1, 6) == 1 else "💨 Щелчок... Жив.")

@dp.message(F.text.startswith("флеш qr"))
async def make_qr(m: types.Message):
    data = m.text[8:].strip()
    if not data: return await m.reply("Напиши ссылку после флеш qr")
    path = f"downloads/qr_{m.from_user.id}.png"
    qrcode.make(data).save(path)
    await m.answer_photo(FSInputFile(path))
    os.remove(path)

# ПОЧТА
@dp.message(F.text.in_(["📧 Почта", "флеш почта"]))
async def mail(m: types.Message):
    l = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
    kb = InlineKeyboardBuilder()
    kb.add(InlineKeyboardButton(text="🔄 Проверить", callback_data=f"c_{l}_1secmail.com"))
    kb.add(InlineKeyboardButton(text="🗑 Удалить", callback_data="del"))
    await m.answer(f"📧 Почта: `{l}@1secmail.com`", parse_mode="Markdown", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("c_"))
async def chk(c: types.CallbackQuery):
    _, l, d = c.data.split("_")
    res = requests.get(f"https://www.1secmail.com/api/v1/?action=getMessages&login={l}&domain={d}").json()
    if not res: return await c.answer("Писем нет", show_alert=True)
    msg = requests.get(f"https://www.1secmail.com/api/v1/?action=readMessage&login={l}&domain={d}&id={res[0]['id']}").json()
    await c.message.answer(f"📩 {msg['textBody']}")
    await c.answer()

# МЕДИА (ВИДЕО И МУЗЫКА)
@dp.message(F.text)
async def handle_text(m: types.Message):
    t = m.text.lower()
    if t.startswith("флеш вопрос"):
        wait = await m.answer("🤔...")
        ans = await ask_gemini(m.text[12:].strip())
        await wait.edit_text(ans)
    elif "музыка" in t:
        q = t.replace("флеш музыка", "").strip()
        wait = await m.answer(f"🔍 Ищу MP3: {q}...")
        with YoutubeDL({'quiet': True, 'noplaylist': True}) as ydl:
            res = ydl.extract_info(f"scsearch5:{q}", download=False).get('entries', [])
        if not res: return await wait.edit_text("Не нашел.")
        kb = InlineKeyboardBuilder()
        for e in res:
            sc_cache[e['id']] = e['webpage_url']
            kb.row(InlineKeyboardButton(text=f"🎵 {e['title'][:35]}", callback_data=f"mp3_{e['id']}"))
        await m.answer("Выбери трек:", reply_markup=kb.as_markup())
    elif t.startswith("http"):
        await dl_media(m, m.text, "video")
    elif "погода" in t:
        city = t.replace("флеш погода", "").strip() or "Костанай"
        r = requests.get(f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_KEY}&units=metric&lang=ru").json()
        if r.get("cod") == 200: await m.reply(f"🌤 {r['name']}: {r['main']['temp']}°C")

async def dl_media(m, url, mode):
    s = await m.answer("⏳ Качаю...")
    try:
        opts = {'outtmpl': 'downloads/%(id)s.%(ext)s', 'quiet': True}
        if mode == "mp3":
            opts.update({'format': 'bestaudio', 'postprocessors': [{'key': 'FFmpegExtractAudio','preferredcodec': 'mp3'}]})
        
        with YoutubeDL(opts) as ydl:
            info = await asyncio.to_thread(lambda: ydl.extract_info(url, download=True))
            p = ydl.prepare_filename(info)
            if mode == "mp3": p = os.path.splitext(p)[0] + ".mp3"
        
        if mode == "video": await m.answer_video(FSInputFile(p))
        else: await m.answer_audio(FSInputFile(p))
        
        if os.path.exists(p): os.remove(p) # УДАЛЕНИЕ С СЕРВЕРА
        await s.delete()
    except Exception as e: await s.edit_text(f"❌ Ошибка: {str(e)[:50]}")

@dp.callback_query(F.data.startswith("mp3_"))
async def mp3_cb(c: types.CallbackQuery):
    url = sc_cache.get(c.data.split("_")[1])
    await c.message.delete()
    await dl_media(c.message, url, "mp3")

async def main():
    if not os.path.exists('downloads'): os.makedirs('downloads')
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
