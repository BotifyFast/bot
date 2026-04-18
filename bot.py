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
# Используем простую инициализацию
model = genai.GenerativeModel('gemini-1.5-flash')

bot = Bot(token=TOKEN)
dp = Dispatcher()

sc_cache, anon_pairs, anon_queue = {}, {}, None

# --- КЛАВИАТУРА ---
def get_main_kb():
    kb = ReplyKeyboardBuilder()
    kb.button(text="🤖 Спросить ИИ")
    kb.button(text="🎬 Видео")
    kb.button(text="🎵 Музыка")
    kb.button(text="📧 Почта")
    kb.button(text="🌦 Погода")
    kb.button(text="📈 Курс")
    kb.button(text="🤡 Анекдот")
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
        btc = crypto['bitcoin']['usd']
        ton = crypto['the-open-network']['usd']
        return (f"💵 USD: {round(usd, 2)} ₽\n"
                f"🇰🇿 100 KZT: {round(r['Valute']['KZT']['Value'], 2)} ₽\n"
                f"🇰🇿 USD/KZT: {round(usd/kzt, 2)} ₸\n"
                f"₿ BTC: ${btc}\n"
                f"💎 TON: ${ton}")
    except: return "❌ Ошибка получения курсов."

# --- ОБРАБОТЧИКИ ---

@dp.message(Command("start"))
async def start(m: types.Message):
    await m.answer("⚡️ Флэш на связи! Используй кнопки.", reply_markup=get_main_kb())

@dp.message(F.text.in_(["⚡️ Команды", "флеш команды"]))
async def cmds(m: types.Message):
    await m.reply("🤖 `флеш вопрос [текст]`\n📸 `флеш фото [текст]`\n📝 `флеш текст` (на фото)\n🎵 `флеш музыка [имя]`\n📧 `флеш почта`\n🌦 `флеш погода [город]`\n📈 `флеш курс`\n🪙 `флеш монета`\n🤡 `флеш анекдот`")

@dp.message(F.text.in_(["📈 Курс", "флеш курс"]))
async def send_rates(m: types.Message):
    await m.reply(get_rates())

@dp.message(F.text.in_(["🤡 Анекдот", "флеш анекдот"]))
async def joke(m: types.Message):
    res = requests.get("https://anekdotme.com/api?category=main").text
    await m.reply(f"🤣 {res}" if res else "Анекдоты кончились!")

@dp.message(F.text == "флеш монета")
async def coin(m: types.Message):
    await m.reply(f"🪙 Результат: {random.choice(['Орёл', 'Решка'])}")

# ПОЧТА
@dp.message(F.text.in_(["📧 Почта", "флеш почта"]))
async def mail(m: types.Message):
    login = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
    domain = "1secmail.com"
    kb = InlineKeyboardBuilder()
    kb.add(InlineKeyboardButton(text="🔄 Проверить", callback_data=f"chk_{login}_{domain}"))
    kb.add(InlineKeyboardButton(text="🗑 Удалить", callback_data="del"))
    await m.answer(f"📧 Новая почта:\n`{login}@{domain}`", parse_mode="Markdown", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("chk_"))
async def chk_mail(c: types.CallbackQuery):
    _, l, d = c.data.split("_")
    res = requests.get(f"https://www.1secmail.com/api/v1/?action=getMessages&login={l}&domain={d}").json()
    if not res: return await c.answer("Писем нет", show_alert=True)
    msg = requests.get(f"https://www.1secmail.com/api/v1/?action=readMessage&login={l}&domain={d}&id={res[0]['id']}").json()
    await c.message.answer(f"📩 От: {msg['from']}\n\n{msg['textBody']}")
    await c.answer()

# ИИ И ФОТО
@dp.message(F.photo)
async def photo_h(m: types.Message):
    cap = m.caption.lower() if m.caption else ""
    if "флеш фото" in cap or "флеш текст" in cap:
        wait = await m.answer("⏳ Работаю...")
        fid = m.photo[-1].file_id
        path = f"downloads/{fid}.jpg"
        file = await bot.get_file(fid)
        await bot.download_file(file.file_path, path)
        
        if "текст" in cap:
            text = pytesseract.image_to_string(Image.open(path), lang='rus+eng')
            await wait.edit_text(f"📝 Текст:\n`{text}`" if text.strip() else "Не нашел текста.")
        else:
            ans = await ask_gemini(cap.replace("флеш фото", "").strip() or "Опиши фото", path)
            await wait.edit_text(ans)
        os.remove(path)

@dp.message(F.text)
async def main_h(m: types.Message):
    t = m.text.lower()
    if t.startswith("флеш вопрос"):
        wait = await m.answer("🤔 Думаю...")
        ans = await ask_gemini(m.text[12:].strip())
        await wait.edit_text(ans)
    elif "погода" in t:
        city = t.replace("флеш погода", "").strip() or "Костанай"
        res = requests.get(f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_KEY}&units=metric&lang=ru").json()
        if res.get("cod") == 200:
            await m.reply(f"🌤 {res['name']}: {res['main']['temp']}°C, {res['weather'][0]['description']}")
    elif "музыка" in t:
        q = m.text.replace("флеш музыка", "").strip()
        wait = await m.answer(f"🔍 Ищу {q}...")
        with YoutubeDL({'quiet': True}) as ydl:
            search = ydl.extract_info(f"scsearch5:{q}", download=False).get('entries', [])
        if not search: return await wait.edit_text("Не нашел.")
        kb = InlineKeyboardBuilder()
        for e in search:
            sc_cache[e['id']] = e['webpage_url']
            kb.row(InlineKeyboardButton(text=f"🎵 {e['title'][:35]}", callback_data=f"dl_{e['id']}"))
        await m.answer("Выбери:", reply_markup=kb.as_markup())
    elif t.startswith("http"):
        await dl_media(m, m.text)

async def dl_media(m, url):
    s = await m.answer("⏳ Качаю...")
    try:
        with YoutubeDL({'outtmpl': 'downloads/%(id)s.%(ext)s', 'quiet': True}) as ydl:
            info = ydl.extract_info(url, download=True)
            p = ydl.prepare_filename(info)
        await m.answer_video(FSInputFile(p))
        os.remove(p); await s.delete()
    except: await s.edit_text("❌ Ошибка.")

@dp.callback_query(F.data.startswith("dl_"))
async def dl_cb(c: types.CallbackQuery):
    url = sc_cache.get(c.data.split("_")[1])
    await c.message.delete()
    await dl_media(c.message, url)

async def main():
    if not os.path.exists('downloads'): os.makedirs('downloads')
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
