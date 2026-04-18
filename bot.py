import os, random, asyncio, logging, requests, qrcode, string, re, subprocess
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import FSInputFile, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
import google.generativeai as genai
from yt_dlp import YoutubeDL

logging.basicConfig(level=logging.INFO)

# --- КОНФИГ ---
TOKEN = "8638601182:AAHAOf2wvybOOyhyt_PNijYkKkljJwGnN-g"
WEATHER_KEY = "c2b2631749aead62cfdc86b394e6399f"
GEMINI_KEY = "AIzaSyCwd4xf-PWyayAdL-yp3xx4-Tlm4aywGXQ"

# Сокращения городов
CITY_MAP = {
    "екб": "Yekaterinburg", "мск": "Moscow", "спб": "Saint Petersburg",
    "костанай": "Kostanay", "кст": "Kostanay", "аст": "Astana",
    "алм": "Almaty", "нск": "Novosibirsk"
}

# Настройка ИИ
genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-1.5-pro')

bot = Bot(token=TOKEN)
dp = Dispatcher()

# Создаем папку для временных файлов
TEMP_DIR = "temp_files"
if not os.path.exists(TEMP_DIR):
    os.makedirs(TEMP_DIR)

# --- КЛАВИАТУРА ---
main_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🤖 ИИ"), KeyboardButton(text="🌦 Погода")],
        [KeyboardButton(text="🎵 Музыка"), KeyboardButton(text="📧 Почта")],
        [KeyboardButton(text="🪙 Монета"), KeyboardButton(text="🔫 Рулетка")],
        [KeyboardButton(text="📈 Курс"), KeyboardButton(text="⚡️ Команды")],
        [KeyboardButton(text="🤡 Анекдот"), KeyboardButton(text="🎬 Видео")]
    ],
    resize_keyboard=True
)

# --- ФУНКЦИИ ---
def clean_temp_files():
    """Очистка старых файлов (старше 1 часа)"""
    now = datetime.now()
    for filename in os.listdir(TEMP_DIR):
        filepath = os.path.join(TEMP_DIR, filename)
        if os.path.isfile(filepath):
            file_time = datetime.fromtimestamp(os.path.getctime(filepath))
            if (now - file_time).seconds > 3600:  # 1 час
                try:
                    os.remove(filepath)
                except:
                    pass

async def download_media(url, media_type="audio"):
    """Скачивание медиа с автоочисткой"""
    clean_temp_files()
    timestamp = int(datetime.now().timestamp())
    filename = f"{TEMP_DIR}/{media_type}_{timestamp}"
    
    ydl_opts = {
        'outtmpl': filename,
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
        'force_generic_extractor': False,
    }
    
    # Для TikTok/Instagram без водяных знаков
    if 'tiktok.com' in url or 'instagram.com' in url:
        ydl_opts.update({
            'format': 'best',
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        })
    
    # Для аудио
    if media_type == "audio":
        ydl_opts.update({
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
        })
        filename = f"{filename}.mp3"
    else:
        ydl_opts.update({
            'format': 'best[ext=mp4]/best',
        })
        filename = f"{filename}.mp4"
    
    try:
        with YoutubeDL(ydl_opts) as ydl:
            await asyncio.to_thread(lambda: ydl.extract_info(url, download=True))
        
        # Проверяем существование файла
        if os.path.exists(filename):
            return filename
        else:
            # Ищем файл с другим расширением
            for f in os.listdir(TEMP_DIR):
                if f.startswith(os.path.basename(filename).split('.')[0]):
                    return os.path.join(TEMP_DIR, f)
            return None
    except Exception as e:
        logging.error(f"Download error: {e}")
        return None

async def ask_gemini(prompt):
    try:
        response = await asyncio.to_thread(lambda: model.generate_content(prompt))
        return response.text[:3000]
    except Exception as e:
        return f"❌ Ошибка ИИ: {str(e)[:100]}"

def get_rates():
    try:
        r = requests.get("https://www.cbr-xml-daily.ru/daily_json.js").json()
        usd = r['Valute']['USD']['Value']
        eur = r['Valute']['EUR']['Value']
        return f"💵 Доллар: {round(usd, 2)} ₽\n💶 Евро: {round(eur, 2)} ₽"
    except:
        return "❌ Ошибка API курсов."

def get_joke():
    jokes = [
        "🤡 Встречаются два друга:\n- Слышал, ты женился?\n- Да.\n- И как?\n- Ну, я теперь как принтер: сплю, жру бумагу и ору когда нет картриджа.",
        "🤡 - Доктор, я себя чувствую собакой!\n- Давно?\n- С детства, гав!",
        "🤡 Идет мужик по пустыне, видит - верблюд лежит. Спрашивает:\n- Верблюд, а верблюд, сколько времени?\n- Буээээ!\n- Ясно, без пятнадцати.",
        "🤡 - Алло, это скорая?\n- Да.\n- Приезжайте, я чай пить разучился!\n- ???\n- Пью, пью - никакого чая не получается!"
    ]
    return random.choice(jokes)

# --- ОБРАБОТЧИКИ ---
@dp.message(Command("start"))
async def start(m: types.Message):
    await m.answer("🤖 **Флеш(Комбайн) - Ахуенный бот!**\n\nВыбирай команды на клавиатуре 👇\n\n🎬 **Качай видео с TikTok/Instagram без водяных знаков!**\n🎵 **Слушай музыку!**\n🌦 **Узнавай погоду!**\n🤖 **Общайся с ИИ!**", 
                   parse_mode="Markdown", reply_markup=main_kb)

@dp.message(F.text.in_(["⚡️ Команды", "флеш команды"]))
async def cmds(m: types.Message):
    await m.answer("🤖 **Все команды:**\n\n"
                   "`флеш вопрос [текст]` - спросить ИИ\n"
                   "`флеш курс` - курс валют\n"
                   "`флеш музыка [название]` - найти музыку\n"
                   "`флеш погода [город]` - погода\n"
                   "`флеш почта` - временная почта\n"
                   "`флеш монета` - орёл/решка\n"
                   "`флеш рулетка` - русская рулетка\n"
                   "`флеш qr [ссылка]` - создать QR\n\n"
                   "🎬 **Просто отправь ссылку на TikTok или Instagram** - скачаю видео без водяного знака!",
                   parse_mode="Markdown")

@dp.message(F.text.in_(["📈 Курс", "флеш курс"]))
async def rates(m: types.Message):
    await m.answer(get_rates())

@dp.message(F.text.in_(["🪙 Монета", "флеш монета"]))
async def coin(m: types.Message):
    await m.answer(f"🪙 {random.choice(['Орёл', 'Решка'])}")

@dp.message(F.text.in_(["🔫 Рулетка", "флеш рулетка"]))
async def roulette(m: types.Message):
    await m.answer("💥 БАБАХ! Ты проиграл!" if random.randint(1, 6) == 1 else "💨 Щелчок... Жив, повезло!")

@dp.message(F.text == "🤡 Анекдот")
async def joke(m: types.Message):
    await m.answer(get_joke())

@dp.message(F.text == "🎬 Видео")
async def video_info(m: types.Message):
    await m.answer("🎬 **Как скачать видео без водяного знака:**\n\n"
                   "Просто отправь мне ссылку на:\n"
                   "• TikTok (vm.tiktok.com или www.tiktok.com)\n"
                   "• Instagram (www.instagram.com)\n\n"
                   "Я скачаю видео в лучшем качестве и без водяных знаков!\n\n"
                   "⚡️ Видео автоматически удаляются с сервера через час.",
                   parse_mode="Markdown")

@dp.message(F.text == "🤖 ИИ")
async def ai_info(m: types.Message):
    await m.answer("🤖 **Спроси ИИ:**\n\nНапиши: `флеш вопрос твой вопрос`\n\nПример: `флеш вопрос кто ты?`", 
                   parse_mode="Markdown")

@dp.message(F.text == "🌦 Погода")
async def weather_info(m: types.Message):
    await m.answer("🌦 **Узнать погоду:**\n\nНапиши: `флеш погода город`\n\nПримеры:\n`флеш погода екб`\n`флеш погода мск`\n`флеш погода костанай`",
                   parse_mode="Markdown")

@dp.message(F.text == "🎵 Музыка")
async def music_info(m: types.Message):
    await m.answer("🎵 **Скачать музыку:**\n\nНапиши: `флеш музыка название трека`\n\nПример: `флеш музыка imagine dragons enemy`\n\nИщу на SoundCloud и YouTube!",
                   parse_mode="Markdown")

@dp.message(F.text == "📧 Почта")
async def mail_info(m: types.Message):
    await m.answer("📧 **Временная почта:**\n\nНапиши: `флеш почта`\n\nПолучишь временный ящик и сможешь проверять письма!",
                   parse_mode="Markdown")

# --- ОСНОВНЫЕ КОМАНДЫ ---
@dp.message(F.text.startswith("флеш qr"))
async def make_qr(m: types.Message):
    data = m.text[8:].strip()
    if not data:
        await m.answer("❌ Введи ссылку или текст после `флеш qr`")
        return
    path = f"{TEMP_DIR}/qr_{m.from_user.id}.png"
    qrcode.make(data).save(path)
    await m.answer_photo(FSInputFile(path))
    if os.path.exists(path):
        os.remove(path)

@dp.message(F.text == "флеш почта")
async def mail(m: types.Message):
    login = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
    kb = InlineKeyboardBuilder()
    kb.add(InlineKeyboardButton(text="🔄 Проверить письма", callback_data=f"check_{login}"))
    await m.answer(f"📧 Твоя почта: `{login}@1secmail.com`\nНажми кнопку для проверки", parse_mode="Markdown", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("check_"))
async def check_mail(c: types.CallbackQuery):
    login = c.data.split("_")[1]
    url = f"https://www.1secmail.com/api/v1/?action=getMessages&login={login}&domain=1secmail.com"
    try:
        res = requests.get(url).json()
        if not res:
            await c.answer("📭 Писем пока нет", show_alert=True)
            return
        msg_data = requests.get(f"https://www.1secmail.com/api/v1/?action=readMessage&login={login}&domain=1secmail.com&id={res[0]['id']}").json()
        text = msg_data.get('textBody', 'Нет текста')[:500]
        await c.message.answer(f"📩 Новое письмо:\n{text}")
        await c.answer()
    except:
        await c.answer("❌ Ошибка проверки", show_alert=True)

@dp.message(F.text.startswith("флеш погода"))
async def weather(m: types.Message):
    city_raw = m.text.replace("флеш погода", "").strip().lower()
    if not city_raw:
        await m.answer("🌦 Напиши город: `флеш погода екб`", parse_mode="Markdown")
        return
    
    city = CITY_MAP.get(city_raw, city_raw)
    url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_KEY}&units=metric&lang=ru"
    try:
        r = requests.get(url).json()
        if r.get("cod") == 200:
            temp = r['main']['temp']
            feels = r['main']['feels_like']
            desc = r['weather'][0]['description']
            await m.answer(f"🌤 **{r['name']}**\n🌡 Температура: {temp}°C\n🤔 Ощущается: {feels}°C\n📝 {desc}")
        else:
            await m.answer("❌ Город не найден. Попробуй: екб, мск, спб, костанай")
    except:
        await m.answer("❌ Ошибка погоды")

@dp.message(F.text.startswith("флеш вопрос"))
async def ai_question(m: types.Message):
    question = m.text.replace("флеш вопрос", "").strip()
    if not question:
        await m.answer("❌ Напиши вопрос после команды\nПример: `флеш вопрос ты кто`", parse_mode="Markdown")
        return
    wait = await m.answer("🤔 Думаю...")
    answer = await ask_gemini(question)
    await wait.edit_text(answer[:4000])

@dp.message(F.text.startswith("флеш музыка"))
async def download_music(m: types.Message):
    query = m.text.replace("флеш музыка", "").strip()
    if not query:
        await m.answer("🎵 Напиши название трека\nПример: `флеш музыка imagine dragons`", parse_mode="Markdown")
        return
    
    msg = await m.answer(f"🔍 Ищу `{query}`...")
    
    # Ищем на YouTube
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': True,
        'format': 'bestaudio',
    }
    
    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = await asyncio.to_thread(lambda: ydl.extract_info(f"ytsearch5:{query}", download=False))
            entries = info.get('entries', [])
            
            if not entries:
                await msg.edit_text("❌ Ничего не найдено")
                return
            
            # Создаем кнопки с результатами
            kb = InlineKeyboardBuilder()
            for idx, entry in enumerate(entries[:5]):
                title = entry['title'][:40]
                kb.add(InlineKeyboardButton(text=f"🎵 {title}", callback_data=f"music_{entry['url']}_{idx}"))
            
            kb.adjust(1)
            await msg.edit_text("🎵 **Найдено:**\nВыбери трек:", reply_markup=kb.as_markup(), parse_mode="Markdown")
    except Exception as e:
        await msg.edit_text(f"❌ Ошибка поиска: {str(e)[:100]}")

@dp.callback_query(F.data.startswith("music_"))
async def music_callback(c: types.CallbackQuery):
    data = c.data.split("_", 2)
    if len(data) < 2:
        await c.answer("Ошибка", show_alert=True)
        return
    
    url = data[1]
    await c.message.delete()
    
    status_msg = await c.message.answer("🎵 Скачиваю музыку... Подожди немного ⏳")
    
    try:
        # Скачиваем аудио
        ydl_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'outtmpl': f'{TEMP_DIR}/%(title)s_%(id)s.%(ext)s',
            'quiet': True,
            'no_warnings': True,
        }
        
        with YoutubeDL(ydl_opts) as ydl:
            info = await asyncio.to_thread(lambda: ydl.extract_info(url, download=True))
            filename = ydl.prepare_filename(info).replace('.webm', '.mp3').replace('.m4a', '.mp3')
            
            if not os.path.exists(filename):
                # Ищем mp3 файл
                for f in os.listdir(TEMP_DIR):
                    if f.endswith('.mp3') and info['id'] in f:
                        filename = os.path.join(TEMP_DIR, f)
                        break
            
            if os.path.exists(filename):
                await status_msg.delete()
                await c.message.answer_audio(FSInputFile(filename), title=info.get('title', 'Track'), performer=info.get('uploader', 'Unknown'))
                # Удаляем файл после отправки
                os.remove(filename)
            else:
                await status_msg.edit_text("❌ Не удалось скачать трек")
    except Exception as e:
        await status_msg.edit_text(f"❌ Ошибка: {str(e)[:100]}")
    
    await c.answer()

# --- СКАЧИВАНИЕ ВИДЕО С TikTok/Instagram ---
@dp.message(F.text.regexp(r'(https?://)?(www\.)?(tiktok\.com|instagram\.com|vm\.tiktok\.com|instagr\.am)/.+'))
async def download_social_video(m: types.Message):
    url = m.text.strip()
    msg = await m.answer("🎬 Скачиваю видео без водяного знака... ⏳")
    
    try:
        # Оптимальные настройки для TikTok/Instagram
        ydl_opts = {
            'outtmpl': f'{TEMP_DIR}/video_%(id)s.%(ext)s',
            'quiet': True,
            'no_warnings': True,
            'format': 'best[ext=mp4]/best',
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'extractor_args': {'tiktok': {'embed': [True]}},
        }
        
        with YoutubeDL(ydl_opts) as ydl:
            info = await asyncio.to_thread(lambda: ydl.extract_info(url, download=True))
            filename = ydl.prepare_filename(info)
            
            # Меняем расширение на mp4 если нужно
            if not filename.endswith('.mp4'):
                base = os.path.splitext(filename)[0]
                if os.path.exists(f"{base}.mp4"):
                    filename = f"{base}.mp4"
                elif os.path.exists(f"{base}.webm"):
                    filename = f"{base}.webm"
            
            if os.path.exists(filename):
                await msg.delete()
                await m.answer_video(FSInputFile(filename), caption=f"✅ Скачано без водяного знака!\n🎥 {info.get('title', 'Video')[:100]}")
                # Удаляем файл после отправки
                os.remove(filename)
            else:
                await msg.edit_text("❌ Не удалось скачать видео")
    except Exception as e:
        await msg.edit_text(f"❌ Ошибка: {str(e)[:100]}\n\nВозможно, видео недоступно или требует авторизации")

# --- ФОЛЛБЕК ---
@dp.message(F.text)
async def fallback(m: types.Message):
    text = m.text.lower()
    if text.startswith("флеш"):
        await m.answer("❌ Неизвестная команда. Напиши `флеш команды` для списка", parse_mode="Markdown")
    else:
        await m.answer("❓ Используй клавиатуру или команды с `флеш`\n\n🎬 Или отправь ссылку на TikTok/Instagram - скачаю видео!", 
                      reply_markup=main_kb)

async def main():
    # Очищаем папку при старте
    clean_temp_files()
    print("✅ Бот Флеш запущен! Всё работает!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
