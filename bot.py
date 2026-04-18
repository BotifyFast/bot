import os, random, asyncio, logging, requests, qrcode, pytesseract, string
from PIL import Image
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.types import FSInputFile
from yt_dlp import YoutubeDL
import google.generativeai as genai

# Фикс для ffmpeg
try:
    import static_ffmpeg
    static_ffmpeg.add_paths()
except:
    pass

logging.basicConfig(level=logging.INFO)

# --- КОНФИГ ---
TOKEN = "8638601182:AAHAOf2wvybOOyhyt_PNijYkKkljJwGnN-g"
WEATHER_KEY = "c2b2631749aead62cfdc86b394e6399f"
GEMINI_KEY = "AIzaSyCwd4xf-PWyayAdL-yp3xx4-Tlm4aywGXQ" 

genai.configure(api_key=GEMINI_KEY)
ai_model = genai.GenerativeModel('gemini-1.5-flash')

bot = Bot(token=TOKEN)
dp = Dispatcher()

sc_cache, anon_pairs, anon_queue = {}, {}, None

# --- БАЗА ДАННЫХ ---
JOKES = [
    "Штирлиц шел по лесу и увидел голубые ели. Когда он подошел поближе, он увидел, что голубые не только ели, но и пили.",
    "Программист ставит на тумбочку два стакана. Один с водой — на случай, если захочет пить. Другой пустой — на случай, если не захочет.",
    "— Кукушка, кукушка, сколько мне жить осталось? — Ку... — А почему так ма...?",
    "Колобок повесился. Буратино утонул. Штирлиц выстрелил в слепую. Слепая упала как подкошенная.",
    "Идет медведь по лесу, видит — машина горит. Сел в нее и сгорел.",
    "Встречаются два программиста: — Привет! Чего такой грустный? — Да вот, вчера в чате с девчонкой познакомился. — И что? — Встретились сегодня... Оказалось, это кодировка не та!"
]

# --- КЛАВИАТУРА ---
def get_main_kb():
    kb = ReplyKeyboardBuilder()
    kb.button(text="🤖 Спросить ИИ")
    kb.button(text="🎬 Скачать видео")
    kb.button(text="🎵 Музыка")
    kb.button(text="🌦 Погода")
    kb.button(text="📧 Почта")
    kb.button(text="👥 Анон Чат")
    kb.button(text="🤡 Анекдот")
    kb.button(text="🎲 Игры")
    kb.adjust(2)
    return kb.as_markup(resize_keyboard=True)

# --- ЛОГИКА ---
async def ask_gemini(prompt, photo_path=None):
    try:
        if photo_path:
            img = Image.open(photo_path)
            response = await asyncio.to_thread(lambda: ai_model.generate_content([prompt, img]))
        else:
            response = await asyncio.to_thread(lambda: ai_model.generate_content(prompt))
        return response.text
    except Exception as e:
        return f"❌ Ошибка ИИ: {str(e)[:100]}"

# --- ОБРАБОТЧИКИ ---

@dp.message(Command("start"))
async def cmd_start(m: types.Message):
    await m.answer("⚡️ Привет! Я Флэш — твой универсальный помощник. Используй кнопки внизу!", reply_markup=get_main_kb())

@dp.message(F.text == "🤡 Анекдот")
async def send_joke(m: types.Message):
    await m.reply(f"🤣 {random.choice(JOKES)}")

@dp.message(F.text == "🎲 Игры")
async def games_menu(m: types.Message):
    kb = InlineKeyboardBuilder()
    kb.button(text="🪙 Монетка", callback_data="game_coin")
    kb.button(text="🔫 Рулетка", callback_data="game_gun")
    await m.answer("Выбери игру:", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("game_"))
async def games_logic(c: types.CallbackQuery):
    if c.data == "game_coin":
        res = random.choice(["Орёл 🦅", "Решка 🪙"])
        await c.message.answer(f"Результат: {res}")
    elif c.data == "game_gun":
        res = "💥 БАБАХ! Ты проиграл." if random.randint(1, 6) == 1 else "💨 Щелчок... Тебе повезло!"
        await c.message.answer(res)
    await c.answer()

@dp.message(F.text == "🌦 Погода")
async def ask_city(m: types.Message):
    await m.answer("Напиши: `флеш погода [город]`\nНапример: `флеш погода Астана`")

@dp.message(F.text == "🤖 Спросить ИИ")
async def ask_ai_help(m: types.Message):
    await m.answer("Напиши: `флеш вопрос [твой вопрос]`\nИ я отвечу с помощью Gemini!")

@dp.message(F.photo)
async def handle_photo(m: types.Message):
    cap = m.caption.lower() if m.caption else ""
    if "флеш фото" in cap:
        wait = await m.answer("📸 ИИ изучает фото...")
        fid = m.photo[-1].file_id
        path = f"downloads/{fid}.jpg"
        file = await bot.get_file(fid)
        await bot.download_file(file.file_path, path)
        ans = await ask_gemini(cap.replace("флеш фото", "").strip() or "Что на фото?", path)
        await wait.edit_text(ans)
        os.remove(path)
    elif "флеш текст" in cap:
        wait = await m.answer("📝 Читаю текст...")
        fid = m.photo[-1].file_id
        path = f"downloads/{fid}.jpg"
        file = await bot.get_file(fid)
        await bot.download_file(file.file_path, path)
        text = pytesseract.image_to_string(Image.open(path), lang='rus+eng')
        await wait.edit_text(f"📝 Текст:\n\n`{text[:3500]}`" if text.strip() else "Не нашел текста.")
        os.remove(path)

@dp.message(F.text)
async def main_handler(m: types.Message):
    t = m.text.lower()
    uid = m.from_user.id

    if uid in anon_pairs and m.chat.type == 'private' and not t.startswith("флеш"):
        return await bot.send_message(anon_pairs[uid], m.text)

    if t.startswith("флеш") or t.startswith("флэш"):
        if "вопрос" in t:
            wait = await m.answer("🤔 Думаю...")
            ans = await ask_gemini(m.text.replace("флеш вопрос", "").strip())
            return await wait.edit_text(ans)
        
        if "погода" in t:
            city = t.replace("флеш погода", "").strip() or "Костанай"
            res = requests.get(f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_KEY}&units=metric&lang=ru").json()
            if res.get("cod") == 200:
                return await m.reply(f"🌤 {res['name']}: {res['main']['temp']}°C, {res['weather'][0]['description']}")
            return await m.reply("❌ Город не найден.")

        if "музыка" in t:
            q = m.text.replace("флеш музыка", "").strip()
            wait = await m.answer(f"🔍 Ищу {q}...")
            with YoutubeDL({'quiet': True}) as ydl:
                entries = await asyncio.to_thread(lambda: ydl.extract_info(f"scsearch5:{q}", download=False)['entries'])
            if not entries: return await wait.edit_text("Ничего не нашел.")
            kb = InlineKeyboardBuilder()
            for e in entries:
                sc_cache[e['id']] = e['webpage_url']
                kb.row(types.InlineKeyboardButton(text=f"🎵 {e['title'][:35]}", callback_data=f"sc_{e['id']}"))
            return await m.answer("Выбери трек:", reply_markup=kb.as_markup())

        if "почта" in t:
            return await m.reply(f"📧 Почта: `flash_{uid}@1secmail.com` \nПисьма: `флеш письма`", parse_mode="Markdown")
        
        if "письма" in t:
            res = requests.get(f"https://www.1secmail.com/api/v1/?action=getMessages&login=flash_{uid}&domain=1secmail.com").json()
            if not res: return await m.reply("📭 Писем нет.")
            msg = requests.get(f"https://www.1secmail.com/api/v1/?action=readMessage&login=flash_{uid}&domain=1secmail.com&id={res[0]['id']}").json()
            return await m.reply(f"📩 От: {msg['from']}\n\n{msg['textBody'][:1000]}")

    if t.startswith("http"):
        await dl_media(m, m.text)

    if t == "🎬 скачать видео": await m.answer("Просто скинь ссылку на TikTok/Insta/YT!")
    if t == "🎵 музыка": await m.answer("Напиши: `флеш музыка [название]`")
    if t == "📧 почта": await m.answer("Напиши: `флеш почта` чтобы создать ящик.")
    if t == "👥 анон чат": await start_anon(m)

async def dl_media(m, url):
    s = await m.answer("⏳ Качаю...")
    try:
        with YoutubeDL({'outtmpl': 'downloads/%(id)s.%(ext)s', 'quiet': True}) as ydl:
            info = await asyncio.to_thread(lambda: ydl.extract_info(url, download=True))
            p = ydl.prepare_filename(info)
        await m.answer_video(FSInputFile(p))
        os.remove(p); await s.delete()
    except: await s.edit_text("❌ Ошибка ссылки.")

async def start_anon(m):
    global anon_queue
    if anon_queue and anon_queue != m.from_user.id:
        p_id = anon_queue; anon_pairs[m.from_user.id], anon_pairs[p_id] = p_id, m.from_user.id
        anon_queue = None
        await bot.send_message(p_id, "🤝 Собеседник найден!"); await m.answer("🤝 Собеседник найден!")
    else:
        anon_queue = m.from_user.id; await m.answer("🔍 Поиск...")

@dp.callback_query(F.data.startswith("sc_"))
async def sc_callback(c: types.CallbackQuery):
    url = sc_cache.get(c.data.split("_")[1])
    await c.message.delete(); await dl_media(c.message, url)

async def main():
    if not os.path.exists('downloads'): os.makedirs('downloads')
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
