import os, random, asyncio, logging, requests, qrcode, string, re, json
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import FSInputFile, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
import google.generativeai as genai
from yt_dlp import YoutubeDL
from speech_recognition import Recognizer, AudioFile
from pydub import AudioSegment
import speech_recognition as sr

logging.basicConfig(level=logging.INFO)

# --- КОНФИГ ---
TOKEN = "8638601182:AAHAOf2wvybOOyhyt_PNijYkKkljJwGnN-g"
WEATHER_KEY = "c2b2631749aead62cfdc86b394e6399f"
GEMINI_KEY = "AIzaSyCwd4xf-PWyayAdL-yp3xx4-Tlm4aywGXQ"

# Правильная модель Gemini (рабочая)
GEMINI_MODEL = "gemini-1.5-flash"  # Эта точно работает

# Сокращения городов
CITY_MAP = {
    "екб": "Yekaterinburg", "мск": "Moscow", "спб": "Saint Petersburg",
    "костанай": "Kostanay", "кст": "Kostanay", "аст": "Astana",
    "алм": "Almaty", "нск": "Novosibirsk"
}

# Настройка ИИ
genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel(GEMINI_MODEL)

bot = Bot(token=TOKEN)
dp = Dispatcher()

# Временные файлы
TEMP_DIR = "temp_files"
if not os.path.exists(TEMP_DIR):
    os.makedirs(TEMP_DIR)

# Хранилище для анонимного чата
anon_users = {}  # user_id -> session_id
anon_messages = {}  # session_id -> last_message_time

# --- КЛАВИАТУРА ---
main_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🤖 ИИ"), KeyboardButton(text="🌦 Погода")],
        [KeyboardButton(text="🎵 Музыка"), KeyboardButton(text="📧 Почта")],
        [KeyboardButton(text="🪙 Монета"), KeyboardButton(text="🔫 Рулетка")],
        [KeyboardButton(text="📈 Курс"), KeyboardButton(text="⚡️ Команды")],
        [KeyboardButton(text="🤡 Анекдот"), KeyboardButton(text="🎲 Рандом")],
        [KeyboardButton(text="👥 Анон Чат"), KeyboardButton(text="📸 Фото в текст")]
    ],
    resize_keyboard=True
)

# --- ФУНКЦИИ ---
def clean_temp_files():
    now = datetime.now()
    for filename in os.listdir(TEMP_DIR):
        filepath = os.path.join(TEMP_DIR, filename)
        if os.path.isfile(filepath):
            file_time = datetime.fromtimestamp(os.path.getctime(filepath))
            if (now - file_time).seconds > 3600:
                try:
                    os.remove(filepath)
                except:
                    pass

async def ask_gemini(prompt, image_path=None):
    try:
        if image_path and os.path.exists(image_path):
            import PIL.Image
            img = PIL.Image.open(image_path)
            response = await asyncio.to_thread(lambda: model.generate_content([prompt, img]))
        else:
            response = await asyncio.to_thread(lambda: model.generate_content(prompt))
        return response.text[:3000]
    except Exception as e:
        return f"❌ Ошибка ИИ: {str(e)[:150]}"

def get_full_rates():
    try:
        # Курсы ЦБ РФ
        r = requests.get("https://www.cbr-xml-daily.ru/daily_json.js").json()
        usd = r['Valute']['USD']['Value']
        eur = r['Valute']['EUR']['Value']
        kzt = r['Valute']['KZT']['Value'] / 100  # Тенге к рублю
        
        # Криптовалюты
        crypto = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,the-open-network&vs_currencies=rub").json()
        btc = crypto.get('bitcoin', {}).get('rub', 0)
        ton = crypto.get('the-open-network', {}).get('rub', 0)
        
        return (f"💵 Доллар: {round(usd, 2)} ₽\n"
                f"💶 Евро: {round(eur, 2)} ₽\n"
                f"🇰🇿 Тенге: {round(kzt, 2)} ₽\n"
                f"₿ Биткоин: {round(btc, 0)} ₽\n"
                f"💎 TON: {round(ton, 2)} ₽")
    except Exception as e:
        return f"❌ Ошибка API: {str(e)[:50]}"

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
    await m.answer("🤖 **Флеш(Комбайн) - Ахуенный бот!**\n\n"
                   "🎵 Музыка с SoundCloud\n"
                   "📸 Распознавание фото в текст\n"
                   "🎤 Голосовые в текст\n"
                   "👥 Анонимный чат\n"
                   "💰 Курсы валют и крипты\n\n"
                   "Выбирай команды на клавиатуре 👇", 
                   parse_mode="Markdown", reply_markup=main_kb)

@dp.message(F.text.in_(["⚡️ Команды", "флеш команды"]))
async def cmds(m: types.Message):
    await m.answer("🤖 **Все команды:**\n\n"
                   "`флеш вопрос [текст]` - спросить ИИ\n"
                   "`флеш фото` - распознать текст с фото (ответь на фото)\n"
                   "`флеш голос` - распознать голосовое (ответь на голосовое)\n"
                   "`флеш курс` - курс валют + крипта\n"
                   "`флеш музыка [название]` - найти музыку на SoundCloud\n"
                   "`флеш погода [город]` - погода\n"
                   "`флеш почта` - временная почта\n"
                   "`флеш монета` - орёл/решка\n"
                   "`флеш рулетка` - русская рулетка\n"
                   "`флеш ролл [число]` - бросить кубик\n"
                   "`флеш qr [ссылка]` - создать QR\n"
                   "`флеш анон` - анонимный чат\n\n"
                   "👥 **Анонимный чат:**\n"
                   "`флеш анон найти` - найти собеседника\n"
                   "`флеш анон стоп` - выйти из чата\n"
                   "Просто пиши сообщения в чате",
                   parse_mode="Markdown")

@dp.message(F.text == "📈 Курс")
async def rates_cmd(m: types.Message):
    await m.answer(get_full_rates())

@dp.message(F.text == "флеш курс")
async def rates_cmd2(m: types.Message):
    await m.answer(get_full_rates())

@dp.message(F.text.in_(["🪙 Монета", "флеш монета"]))
async def coin(m: types.Message):
    await m.answer(f"🪙 {random.choice(['Орёл', 'Решка'])}")

@dp.message(F.text.in_(["🔫 Рулетка", "флеш рулетка"]))
async def roulette(m: types.Message):
    await m.answer("💥 БАБАХ! Ты проиграл!" if random.randint(1, 6) == 1 else "💨 Щелчок... Жив, повезло!")

@dp.message(F.text.in_(["🤡 Анекдот"]))
async def joke_cmd(m: types.Message):
    await m.answer(get_joke())

@dp.message(F.text.in_(["🎲 Рандом", "флеш ролл"]))
async def roll_dice(m: types.Message):
    num = random.randint(1, 100)
    await m.answer(f"🎲 Тебе выпало: **{num}**", parse_mode="Markdown")

# Обработка флеш ролл с числом
@dp.message(F.text.startswith("флеш ролл"))
async def roll_dice_custom(m: types.Message):
    parts = m.text.split()
    if len(parts) > 1:
        try:
            max_num = int(parts[1])
            if max_num > 1000:
                max_num = 1000
            num = random.randint(1, max_num)
            await m.answer(f"🎲 Тебе выпало: **{num}** из {max_num}", parse_mode="Markdown")
        except:
            await m.answer("❌ Напиши число: `флеш ролл 50`", parse_mode="Markdown")
    else:
        num = random.randint(1, 100)
        await m.answer(f"🎲 Тебе выпало: **{num}**", parse_mode="Markdown")

# --- РАСПОЗНАВАНИЕ ФОТО В ТЕКСТ ---
@dp.message(F.photo)
async def photo_to_text(m: types.Message):
    if m.caption and m.caption.startswith("флеш фото"):
        photo = m.photo[-1]
        file = await bot.get_file(photo.file_id)
        file_path = f"{TEMP_DIR}/photo_{m.from_user.id}.jpg"
        await bot.download_file(file.file_path, file_path)
        
        wait_msg = await m.answer("📸 Распознаю текст с фото...")
        text = await ask_gemini("Опиши что на этом фото и выведи весь текст который видишь", file_path)
        await wait_msg.edit_text(f"📸 **Текст с фото:**\n\n{text[:3000]}", parse_mode="Markdown")
        
        if os.path.exists(file_path):
            os.remove(file_path)

# --- РАСПОЗНАВАНИЕ ГОЛОСОВЫХ ---
@dp.message(F.voice)
async def voice_to_text(m: types.Message):
    if m.caption and m.caption.startswith("флеш голос") or m.text == "флеш голос":
        voice = m.voice
        file = await bot.get_file(voice.file_id)
        oga_path = f"{TEMP_DIR}/voice_{m.from_user.id}.ogg"
        wav_path = f"{TEMP_DIR}/voice_{m.from_user.id}.wav"
        
        await bot.download_file(file.file_path, oga_path)
        
        # Конвертируем ogg в wav
        audio = AudioSegment.from_ogg(oga_path)
        audio.export(wav_path, format="wav")
        
        wait_msg = await m.answer("🎤 Распознаю голосовое сообщение...")
        
        # Распознаем речь
        recognizer = sr.Recognizer()
        with sr.AudioFile(wav_path) as source:
            audio_data = recognizer.record(source)
            try:
                text = recognizer.recognize_google(audio_data, language="ru-RU")
                await wait_msg.edit_text(f"🎤 **Текст голосового:**\n\n{text}")
            except:
                await wait_msg.edit_text("❌ Не удалось распознать голосовое сообщение")
        
        # Чистим файлы
        for path in [oga_path, wav_path]:
            if os.path.exists(path):
                os.remove(path)

@dp.message(F.text == "📸 Фото в текст")
async def photo_help(m: types.Message):
    await m.answer("📸 **Как распознать текст с фото:**\n\n"
                   "1. Отправь фото\n"
                   "2. В подписи к фото напиши: `флеш фото`\n\n"
                   "🤖 ИИ прочитает весь текст с картинки и опишет что на ней!")

# --- МУЗЫКА С SOUNDCLOUD ---
@dp.message(F.text.startswith("флеш музыка"))
async def music_soundcloud(m: types.Message):
    query = m.text.replace("флеш музыка", "").strip()
    if not query:
        await m.answer("🎵 Напиши название трека\nПример: `флеш музыка imagine dragons`", parse_mode="Markdown")
        return
    
    msg = await m.answer(f"🔍 Ищу `{query}` на SoundCloud...")
    
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,
            'format': 'bestaudio',
        }
        
        with YoutubeDL(ydl_opts) as ydl:
            info = await asyncio.to_thread(lambda: ydl.extract_info(f"scsearch5:{query}", download=False))
            entries = info.get('entries', [])
            
            if not entries:
                await msg.edit_text("❌ Ничего не найдено на SoundCloud")
                return
            
            kb = InlineKeyboardBuilder()
            for idx, entry in enumerate(entries[:5]):
                title = entry['title'][:40]
                kb.add(InlineKeyboardButton(text=f"🎵 {title}", callback_data=f"sc_{entry['url']}_{idx}"))
            
            kb.adjust(1)
            await msg.edit_text("🎵 **Найдено на SoundCloud:**\nВыбери трек:", reply_markup=kb.as_markup(), parse_mode="Markdown")
    except Exception as e:
        await msg.edit_text(f"❌ Ошибка поиска: {str(e)[:100]}")

@dp.callback_query(F.data.startswith("sc_"))
async def music_callback(c: types.CallbackQuery):
    data = c.data.split("_", 2)
    if len(data) < 2:
        await c.answer("Ошибка", show_alert=True)
        return
    
    url = data[1]
    await c.message.delete()
    
    status_msg = await c.message.answer("🎵 Скачиваю музыку с SoundCloud... ⏳")
    
    try:
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
                for f in os.listdir(TEMP_DIR):
                    if f.endswith('.mp3') and info['id'] in f:
                        filename = os.path.join(TEMP_DIR, f)
                        break
            
            if os.path.exists(filename):
                await status_msg.delete()
                await c.message.answer_audio(FSInputFile(filename), 
                                            title=info.get('title', 'Track')[:100], 
                                            performer=info.get('uploader', 'SoundCloud'))
                os.remove(filename)
            else:
                await status_msg.edit_text("❌ Не удалось скачать трек")
    except Exception as e:
        await status_msg.edit_text(f"❌ Ошибка: {str(e)[:100]}")
    
    await c.answer()

# --- АНОНИМНЫЙ ЧАТ ---
@dp.message(F.text == "👥 Анон Чат")
async def anon_help(m: types.Message):
    await m.answer("👥 **Анонимный чат:**\n\n"
                   "`флеш анон найти` - найти случайного собеседника\n"
                   "`флеш анон стоп` - выйти из чата\n"
                   "После подключения просто пиши сообщения - они пойдут собеседнику!\n\n"
                   "🔒 Все сообщения анонимны, никто не узнает кто ты!")

@dp.message(F.text.startswith("флеш анон найти"))
async def anon_find(m: types.Message):
    user_id = m.from_user.id
    
    # Ищем свободного собеседника
    for uid, session in anon_users.items():
        if session == "waiting" and uid != user_id:
            # Нашли пару
            anon_users[user_id] = uid
            anon_users[uid] = user_id
            await m.answer("✅ Найден собеседник! Можете общаться анонимно.\nДля выхода напиши: `флеш анон стоп`", parse_mode="Markdown")
            await bot.send_message(uid, "✅ Найден собеседник! Можете общаться анонимно.\nДля выхода напиши: `флеш анон стоп`", parse_mode="Markdown")
            return
    
    # Если нет свободных, ставим в очередь
    anon_users[user_id] = "waiting"
    await m.answer("🔍 Ищу собеседника... Как только кто-то подключится, я сообщу!\nДля отмены напиши: `флеш анон стоп`", parse_mode="Markdown")

@dp.message(F.text.startswith("флеш анон стоп"))
async def anon_stop(m: types.Message):
    user_id = m.from_user.id
    
    if user_id in anon_users:
        partner = anon_users[user_id]
        if partner != "waiting" and partner in anon_users:
            await bot.send_message(partner, "❌ Собеседник покинул чат\nДля поиска нового напиши: `флеш анон найти`", parse_mode="Markdown")
            anon_users[partner] = "waiting"
        
        del anon_users[user_id]
        await m.answer("❌ Вы вышли из анонимного чата", parse_mode="Markdown")
    else:
        await m.answer("❌ Вы не в чате", parse_mode="Markdown")

# Пересылка сообщений в анонимном чате
@dp.message(F.text)
async def anon_message(m: types.Message):
    user_id = m.from_user.id
    text = m.text
    
    # Пропускаем команды
    if text.startswith("флеш"):
        return
    
    if user_id in anon_users:
        partner = anon_users[user_id]
        if partner != "waiting" and partner in anon_users:
            await bot.send_message(partner, f"👤 Аноним: {text}")
        elif partner == "waiting":
            await m.answer("⏳ Вы в поиске собеседника... Напишите `флеш анон найти` для поиска", parse_mode="Markdown")

# --- QR КОД ---
@dp.message(F.text.startswith("флеш qr"))
async def make_qr(m: types.Message):
    data = m.text[8:].strip()
    if not data:
        await m.answer("❌ Введи ссылку или текст после `флеш qr`\nПример: `флеш qr https://google.com`", parse_mode="Markdown")
        return
    path = f"{TEMP_DIR}/qr_{m.from_user.id}.png"
    qrcode.make(data).save(path)
    await m.answer_photo(FSInputFile(path), caption=f"✅ QR код для: {data[:100]}")
    if os.path.exists(path):
        os.remove(path)

# --- ПОГОДА ---
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
            wind = r['wind']['speed']
            await m.answer(f"🌤 **{r['name']}**\n🌡 {temp}°C (ощущается {feels}°C)\n📝 {desc}\n💨 Ветер: {wind} м/с")
        else:
            await m.answer("❌ Город не найден. Попробуй: екб, мск, спб, костанай")
    except:
        await m.answer("❌ Ошибка погоды")

# --- ИИ ВОПРОС ---
@dp.message(F.text.startswith("флеш вопрос"))
async def ai_question(m: types.Message):
    question = m.text.replace("флеш вопрос", "").strip()
    if not question:
        await m.answer("❌ Напиши вопрос после команды\nПример: `флеш вопрос ты кто`", parse_mode="Markdown")
        return
    wait = await m.answer("🤔 Думаю...")
    answer = await ask_gemini(question)
    await wait.edit_text(answer[:4000])

# --- ПОЧТА ---
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

# --- ФОЛЛБЕК ---
@dp.message(F.text)
async def fallback(m: types.Message):
    if not m.text.startswith("флеш"):
        await m.answer("❓ Используй клавиатуру или команды с `флеш`\n\n"
                      "🎵 `флеш музыка` - найти трек\n"
                      "👥 `флеш анон найти` - анонимный чат\n"
                      "📸 Отправь фото с подписью `флеш фото`\n"
                      "🎤 Отправь голосовое с подписью `флеш голос`", 
                      reply_markup=main_kb)

async def main():
    clean_temp_files()
    print("✅ Бот Флеш запущен! Всё работает!")
    print(f"🤖 Gemini модель: {GEMINI_MODEL}")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
