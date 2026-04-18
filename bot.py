import os, random, asyncio, logging, requests, qrcode, pytesseract, string
from PIL import Image
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.types import FSInputFile, InlineKeyboardButton
from yt_dlp import YoutubeDL
import google.generativeai as genai

# Фикс путей ffmpeg
try:
    import static_ffmpeg
    static_ffmpeg.add_paths()
except:
    pass

logging.basicConfig(level=logging.INFO)

# --- КОНФИГ ---
TOKEN = "8638601182:AAHAOf2wvybOOyhyt_PNijYkKkljJwGnN-g"
WEATHER_KEY = "c2b2631749aead62cfdc86b394e6399f"
# Твой ключ, который ты скинул
GEMINI_KEY = "AIzaSyCwd4xf-PWyayAdL-yp3xx4-Tlm4aywGXQ" 

genai.configure(api_key=GEMINI_KEY)
# Инициализация модели (исправлено для предотвращения 404)
ai_model = genai.GenerativeModel('gemini-1.5-flash')

bot = Bot(token=TOKEN)
dp = Dispatcher()

sc_cache, anon_pairs, anon_queue = {}, {}, None

JOKES = [
    "Штирлиц шел по лесу и увидел голубые ели. Когда он подошел поближе, он увидел, что голубые не только ели, но и пили.",
    "Программист ставит на тумбочку два стакана. Один с водой — на случай, если захочет пить. Другой пустой — на случай, если не захочет.",
    "Идет медведь по лесу, видит — машина горит. Сел в нее и сгорел.",
    "Встречаются два программиста: — Вчера с девчонкой познакомился. — И как? — Да кодировка не та, полчаса друг друга понять не могли."
]

# --- КЛАВИАТУРА ---
def get_main_kb():
    kb = ReplyKeyboardBuilder()
    kb.button(text="🤖 Спросить ИИ")
    kb.button(text="🎬 Скачать видео")
    kb.button(text="🎵 Музыка")
    kb.button(text="📧 Почта")
    kb.button(text="🌦 Погода")
    kb.button(text="👥 Анон Чат")
    kb.button(text="🤡 Анекдот")
    kb.button(text="⚡️ Команды")
    kb.adjust(2)
    return kb.as_markup(resize_keyboard=True)

# --- ЛОГИКА ПОЧТЫ (1secmail) ---
def generate_random_mail():
    login = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
    return login, "1secmail.com"

# --- ОБРАБОТЧИКИ ---

@dp.message(Command("start"))
async def cmd_start(m: types.Message):
    await m.answer("⚡️ Флэш-Комбайн готов к работе! Пользуйся кнопками или пиши команды.", reply_markup=get_main_kb())

@dp.message(F.text.in_(["⚡️ Команды", "флеш команды"]))
async def list_commands(m: types.Message):
    text = (
        "📜 **Список команд:**\n\n"
        "🤖 `флеш вопрос [текст]` — задать вопрос ИИ\n"
        "📸 `флеш фото [текст]` — анализ фото (в подписи)\n"
        "📝 `флеш текст` — распознать текст с фото\n"
        "🎬 `ссылка` — качать видео (TT, Insta, YT)\n"
        "🎵 `флеш музыка [название]` — поиск и загрузка\n"
        "📧 `флеш почта` — новый временный ящик\n"
        "🌦 `флеш погода [город]` — узнать погоду\n"
        "👥 `анонимный чат` — поиск собеседника\n"
        "🤡 `флеш анекдот` — порция юмора\n"
        "🪙 `флеш монета` — подбросить монетку"
    )
    await m.reply(text, parse_mode="Markdown")

@dp.message(F.text.in_(["🤡 Анекдот", "флеш анекдот"]))
async def send_joke(m: types.Message):
    await m.reply(f"🤣 {random.choice(JOKES)}")

@dp.message(F.text == "флеш монета")
async def flip_coin(m: types.Message):
    res = random.choice(["Орёл 🦅", "Решка 🪙"])
    await m.reply(f"Результат: **{res}**", parse_mode="Markdown")

# --- ПОЧТА С КНОПКАМИ ---
@dp.message(F.text.in_(["📧 Почта", "флеш почта"]))
async def create_mail(m: types.Message):
    login, domain = generate_random_mail()
    addr = f"{login}@{domain}"
    kb = InlineKeyboardBuilder()
    kb.add(InlineKeyboardButton(text="🔄 Проверить ящик", callback_data=f"check_{login}_{domain}"))
    kb.add(InlineKeyboardButton(text="🗑 Удалить", callback_data="del_mail"))
    await m.answer(f"📧 Твоя временная почта (5-10 мин):\n`{addr}`", parse_mode="Markdown", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("check_"))
async def check_mail_cb(c: types.CallbackQuery):
    _, login, domain = c.data.split("_")
    url = f"https://www.1secmail.com/api/v1/?action=getMessages&login={login}&domain={domain}"
    msgs = requests.get(url).json()
    if not msgs:
        return await c.answer("📭 Писем пока нет", show_alert=True)
    
    msg_id = msgs[0]['id']
    read_url = f"https://www.1secmail.com/api/v1/?action=readMessage&login={login}&domain={domain}&id={msg_id}"
    data = requests.get(read_url).json()
    text = f"📩 **От**: {data['from']}\n**Тема**: {data['subject']}\n\n{data['textBody'][:500]}"
    await c.message.answer(text, parse_mode="Markdown")
    await c.answer()

@dp.callback_query(F.data == "del_mail")
async def del_mail_cb(c: types.CallbackQuery):
    await c.message.delete()
    await c.answer("Ящик удален")

# --- ФОТО И ТЕКСТ ---
@dp.message(F.photo)
async def handle_photo(m: types.Message):
    cap = m.caption.lower() if m.caption else ""
    if "флеш фото" in cap or "флэш фото" in cap:
        wait = await m.answer("📸 ИИ анализирует фото...")
        fid = m.photo[-1].file_id
        path = f"downloads/{fid}.jpg"
        file = await bot.get_file(fid)
        await bot.download_file(file.file_path, path)
        prompt = cap.replace("флеш фото", "").strip() or "Что на этом изображении?"
        try:
            img = Image.open(path)
            response = await asyncio.to_thread(lambda: ai_model.generate_content([prompt, img]))
            await wait.edit_text(response.text)
        except Exception as e:
            await wait.edit_text(f"❌ Ошибка ИИ: {e}")
        finally:
            if os.path.exists(path): os.remove(path)
            
    elif "флеш текст" in cap:
        wait = await m.answer("📝 Распознаю текст...")
        fid = m.photo[-1].file_id
        path = f"downloads/{fid}.jpg"
        file = await bot.get_file(fid)
        await bot.download_file(file.file_path, path)
        text = pytesseract.image_to_string(Image.open(path), lang='rus+eng')
        await wait.edit_text(f"📝 Нашел текст:\n\n`{text[:3500]}`" if text.strip() else "Текст не обнаружен.")
        if os.path.exists(path): os.remove(path)

# --- ГЛАВНЫЙ ОБРАБОТЧИК ---
@dp.message(F.text)
async def main_handler(m: types.Message):
    t = m.text.lower()
    uid = m.from_user.id

    if uid in anon_pairs and m.chat.type == 'private' and not t.startswith("флеш"):
        return await bot.send_message(anon_pairs[uid], m.text)

    if t.startswith("флеш") or t.startswith("флэш"):
        if "вопрос" in t:
            wait = await m.answer("🤔 Думаю...")
            prompt = m.text.replace("флеш вопрос", "").replace("Флеш вопрос", "").strip()
            if not prompt: return await wait.edit_text("Напиши вопрос после 'флеш вопрос'!")
            try:
                response = await asyncio.to_thread(lambda: ai_model.generate_content(prompt))
                await wait.edit_text(response.text)
            except Exception as e:
                await wait.edit_text(f"❌ Ошибка ИИ: {e}")
            return

        if "музыка" in t:
            q = m.text.replace("флеш музыка", "").strip()
            wait = await m.answer(f"🔍 Ищу трек: {q}...")
            with YoutubeDL({'quiet': True, 'noplaylist': True}) as ydl:
                search = await asyncio.to_thread(lambda: ydl.extract_info(f"scsearch5:{q}", download=False).get('entries', []))
            if not search: return await wait.edit_text("Ничего не нашел.")
            kb = InlineKeyboardBuilder()
            for e in search:
                sc_cache[e['id']] = e['webpage_url']
                kb.row(InlineKeyboardButton(text=f"🎵 {e['title'][:35]}", callback_data=f"sc_{e['id']}"))
            return await m.answer("Выбери трек из списка:", reply_markup=kb.as_markup())

        if "погода" in t:
            city = t.replace("флеш погода", "").strip() or "Костанай"
            res = requests.get(f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_KEY}&units=metric&lang=ru").json()
            if res.get("cod") == 200:
                return await m.reply(f"🌤 В {res['name']}: {res['main']['temp']}°C, {res['weather'][0]['description']}")
            return await m.reply("❌ Город не найден.")

    if t.startswith("http"):
        await dl_media(m, m.text)

async def dl_media(m, url):
    s = await m.answer("⏳ Загрузка...")
    try:
        opts = {'outtmpl': 'downloads/%(id)s.%(ext)s', 'quiet': True}
        if "soundcloud.com" in url:
            opts.update({'format': 'bestaudio', 'postprocessors': [{'key': 'FFmpegExtractAudio','preferredcodec': 'mp3'}]})
        with YoutubeDL(opts) as ydl:
            info = await asyncio.to_thread(lambda: ydl.extract_info(url, download=True))
            p = ydl.prepare_filename(info)
            if "soundcloud.com" in url: p = os.path.splitext(p)[0] + ".mp3"
        await (m.answer_video(FSInputFile(p)) if "soundcloud.com" not in url else m.answer_audio(FSInputFile(p)))
        os.remove(p); await s.delete()
    except Exception as e:
        await s.edit_text(f"❌ Ошибка: {str(e)[:50]}")

@dp.callback_query(F.data.startswith("sc_"))
async def sc_callback(c: types.CallbackQuery):
    url = sc_cache.get(c.data.split("_")[1])
    await c.message.delete(); await dl_media(c.message, url)

async def main():
    if not os.path.exists('downloads'): os.makedirs('downloads')
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
