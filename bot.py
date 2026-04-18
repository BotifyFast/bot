import os, random, asyncio, logging, requests, datetime, string, qrcode
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import FSInputFile, InlineKeyboardButton, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from yt_dlp import YoutubeDL
from pydub import AudioSegment
import speech_recognition as sr

logging.basicConfig(level=logging.INFO)

TOKEN = "8638601182:AAHAOf2wvybOOyhyt_PNijYkKkljJwGnN-g"
WEATHER_KEY = "c2b2631749aead62cfdc86b394e6399f"

bot = Bot(token=TOKEN)
dp = Dispatcher()
sc_cache = {}

def main_kb():
    kb = ReplyKeyboardBuilder()
    btns = ["🌤 Погода", "📈 Курс", "📧 Почта", "🎵 Музыка", "🎲 Ролл", "🔫 Рулетка", "🪙 Монета", "📲 QR Код", "⚡️ Команды"]
    for b in btns: kb.add(KeyboardButton(text=b))
    kb.adjust(3, 3, 3)
    return kb.as_markup(resize_keyboard=True)

# Функция для ГС и Кружков
async def process_any_audio(m: types.Message, audio_obj):
    wait = await m.answer("👂 Обрабатываю звук...")
    fid = audio_obj.file_id
    path_o, path_w = f"{fid}.ogg", f"{fid}.wav"
    try:
        file = await bot.get_file(fid)
        await bot.download_file(file.file_path, path_o)
        AudioSegment.from_file(path_o).export(path_w, format="wav")
        r = sr.Recognizer()
        with sr.AudioFile(path_w) as s:
            t = r.recognize_google(r.record(s), language="ru-RU")
            await wait.edit_text(f"🎤 **Текст:**\n{t}")
    except Exception as e:
        await wait.edit_text(f"❌ Не удалось распознать текст.")
    finally:
        for f in [path_o, path_w]:
            if os.path.exists(f): os.remove(f)

# --- ОБРАБОТЧИКИ ---

@dp.message(F.text.lower() == "флеш")
async def flash_call(m: types.Message):
    await m.reply("Чего звал? Я тут! Вот мои команды: /start или жми '⚡️ Команды'")

@dp.message(F.text == "/start")
async def cmd_start(m: types.Message):
    await m.answer(f"Привет! Я бот **Флеш комбайн** ⚡️\n\nЯ умею качать музыку, распознавать ГС и кружки, делать почту и многое другое!", reply_markup=main_kb())

# МУЗЫКА
@dp.message(F.text.startswith("флеш музыка") | (F.text == "🎵 Музыка"))
async def music_cmd(m: types.Message):
    query = m.text.replace("флеш музыка", "").replace("🎵 Музыка", "").strip()
    if not query: return await m.answer("Напиши название музыки! Пример: `флеш музыка Скриптонит`")
    
    wait = await m.answer(f"🔍 Ищу трек...")
    try:
        with YoutubeDL({'quiet': True, 'noplaylist': True}) as ydl:
            res = await asyncio.to_thread(lambda: ydl.extract_info(f"scsearch5:{query}", download=False))
            entries = res.get('entries', [])
        if not entries: return await wait.edit_text("❌ Ничего не найдено.")
        
        kb = InlineKeyboardBuilder()
        for e in entries:
            sc_cache[e['id']] = e['webpage_url']
            kb.row(InlineKeyboardButton(text=f"🎵 {e['title'][:40]}", callback_data=f"dl_{e['id']}"))
        await wait.edit_text("Выбери трек:", reply_markup=kb.as_markup())
    except: await wait.edit_text("❌ Ошибка поиска.")

@dp.callback_query(F.data.startswith("dl_"))
async def music_download(c: types.CallbackQuery):
    tid = c.data.replace("dl_", ""); url = sc_cache.get(tid)
    if not url: return await c.answer("Ошибка")
    await c.message.edit_text("📥 Качаю... (может занять время)")
    path = f"downloads/{tid}.mp3"
    try:
        opts = {'outtmpl': path, 'format': 'bestaudio/best', 'postprocessors': [{'key': 'FFmpegExtractAudio','preferredcodec': 'mp3'}]}
        with YoutubeDL(opts) as ydl:
            await asyncio.to_thread(lambda: ydl.download([url]))
        await c.message.answer_audio(FSInputFile(path))
        await c.message.delete()
    except Exception as e: await c.message.edit_text(f"❌ Ошибка: {e}")
    finally:
        if os.path.exists(path): os.remove(path)

# ПОЧТА
@dp.message(F.text.in_(["📧 Почта", "флеш почта"]))
async def mail_cmd(m: types.Message):
    mail = f"{''.join(random.choices(string.ascii_lowercase + string.digits, k=10))}@1secmail.com"
    kb = InlineKeyboardBuilder().row(InlineKeyboardButton(text="📥 Проверить письма", callback_data=f"chk_{mail}"))
    await m.answer(f"📬 Почта на 5 минут:\n`{mail}`", reply_markup=kb.as_markup(), parse_mode="Markdown")

@dp.callback_query(F.data.startswith("chk_"))
async def mail_check(c: types.CallbackQuery):
    l, d = c.data.replace("chk_", "").split('@')
    res = requests.get(f"https://www.1secmail.com/api/v1/?action=getMessages&login={l}&domain={d}").json()
    if not res: return await c.answer("Писем пока нет", show_alert=True)
    msg = requests.get(f"https://www.1secmail.com/api/v1/?action=readMessage&login={l}&domain={d}&id={res[0]['id']}").json()
    await c.message.answer(f"📩 **От:** {msg['from']}\n**Текст:**\n{msg['textBody']}")

# ГОЛОС
@dp.message(F.text.lower() == "флеш голос")
async def voice_cmd(m: types.Message):
    rep = m.reply_to_message
    if rep and (rep.voice or rep.video_note or rep.audio):
        await process_any_audio(m, rep.voice or rep.video_note or rep.audio)
    else: await m.reply("Ответь этой командой на ГС или Кружок!")

# QR
@dp.message(F.text.startswith("флеш qr") | (F.text == "📲 QR Код"))
async def qr_cmd(m: types.Message):
    link = m.text.replace("флеш qr", "").replace("📲 QR Код", "").strip()
    if not link: return await m.answer("Напиши ссылку! Пример: `флеш qr google.com`")
    path = f"qr_{m.from_user.id}.png"
    qrcode.make(link).save(path)
    await m.answer_photo(FSInputFile(path), caption=f"QR: {link}")
    if os.path.exists(path): os.remove(path)

# РОЛЛ, ПОГОДА, КУРС, МОНЕТА, РУЛЕТКА
@dp.message(F.text.startswith("флеш ролл") | (F.text == "🎲 Ролл"))
async def roll_cmd(m: types.Message):
    res = random.randint(1, 100)
    await m.reply(f"🎲 Результат: **{res}**\nУ кого больше — тот и папа!")

@dp.message(F.text.startswith("флеш погода") | (F.text == "🌤 Погода"))
async def weather_cmd(m: types.Message):
    city = m.text.replace("флеш погода", "").replace("🌤 Погода", "").strip() or "Костанай"
    r = requests.get(f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_KEY}&units=metric&lang=ru").json()
    try:
        await m.answer(f"🌤 **{city.capitalize()}**: {round(r['main']['temp'])}°C, {r['weather'][0]['description']}")
    except: await m.answer("❌ Город не найден.")

@dp.message(F.text.in_(["📈 Курс", "флеш курс"]))
async def rates_cmd(m: types.Message):
    r = requests.get("https://www.cbr-xml-daily.ru/daily_json.js").json()
    c = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,the-open-network&vs_currencies=usd").json()
    usd = r['Valute']['USD']['Value']
    await m.answer(f"📊 **Курс:**\n💵 Доллар: {round(usd, 2)}₽\n₿ BTC: ${c['bitcoin']['usd']:,}\n💎 TON: ${c['the-open-network']['usd']}")

@dp.message(F.text.in_(["флеш монетка", "🪙 Монета"]))
async def coin_cmd(m: types.Message):
    await m.reply(f"🪙 Выпало: **{random.choice(['Орёл', 'Решка'])}**")

@dp.message(F.text.in_(["флеш рулетка", "🔫 Рулетка"]))
async def roul_cmd(m: types.Message):
    await m.reply(random.choice(["💥 БАХ!", "🔫 Осечка!"]))

@dp.message(F.text.in_(["⚡️ Команды", "флеш команды"]))
async def help_cmd(m: types.Message):
    await m.answer("📜 **Команды:**\n• флеш погода\n• флеш музыка\n• флеш голос (на ГС)\n• флеш ролл\n• флеш монетка\n• флеш рулетка\n• флеш qr\n• флеш почта\n• флеш курс")

async def main():
    if not os.path.exists('downloads'): os.makedirs('downloads')
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
