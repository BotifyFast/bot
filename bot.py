import logging
import random
import os
import re
import asyncio
import aiohttp
import aiofiles
import tempfile
import json
import shutil
import subprocess
import sys
import signal
import time
import gc
from pathlib import Path
from datetime import datetime, timedelta, timezone

time.sleep(3)

try:
    import psutil
    current_pid = os.getpid()
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmdline = proc.info['cmdline']
            if cmdline and proc.info['pid'] != current_pid:
                if any('bot' in str(arg).lower() for arg in cmdline) and 'python' in str(cmdline[0]).lower():
                    os.kill(proc.info['pid'], signal.SIGTERM)
        except: pass
except: pass

try:
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--upgrade", "yt-dlp"], check=True)
except: pass

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from telegram.constants import ChatType, ParseMode

# ═══════════════ КОНФИГ ═══════════════
TOKEN = os.environ.get("BOT_TOKEN", "8518299800:AAF8W7j7spj7MxAJH119dbU3ybSwcPH_TmE").strip()
WEATHER_API_KEY = os.environ.get("WEATHER_API_KEY", "c2b2631749aead62cfdc86b394e6399f").strip()
OWNER_ID = int(os.environ.get("OWNER_ID", "1202730193"))
TMDB_KEY = os.environ.get("TMDB_KEY", "8265bd1679663a7ea12ac168da84d2e8").strip()

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

SUPPORTED_DOMAINS = ["youtube.com","youtu.be","tiktok.com","vm.tiktok.com","instagram.com","instagr.am","soundcloud.com","twitter.com","x.com","vk.com","facebook.com","fb.watch"]
TG_PATTERN = re.compile(r'https?://t\.me/(?:c/)?([^/]+)/(\d+)')
URL_REGEX = re.compile(r'https?://[^\s<>"{}|\\^`\[\]]+')

pending_music = {}
pending_idea = set()
active_timers = {}
anon_chat_queue = []
anon_chat_pairs = {}
anon_chat_users = set()

CITY_ALIASES = {
    "екб": "Екатеринбург", "спб": "Санкт-Петербург", "мск": "Москва",
    "кст": "Костанай", "нск": "Новосибирск", "кзн": "Казань",
    "алм": "Алматы", "аст": "Астана",
}

BAD_WORDS = ["порно", "porn", "секс", "sex", "xxx", "18+", "эротика", "хентай", "hentai"]
SHAME_RESPONSES = [
    "🫣 АЙ-АЙ-АЙ! Иди лучше Машу и Медведя смотри!",
    "😤 ЧТО ЭТО ТАКОЕ?! Марш смотреть Смешариков!",
]

def is_private(u): return u.effective_chat.type == ChatType.PRIVATE
def extract_url(t):
    m = URL_REGEX.search(t)
    return m.group(0) if m else None
def is_supported_url(url): return any(d in url.lower() for d in SUPPORTED_DOMAINS)
def is_tg_url(url): return bool(TG_PATTERN.search(url))
def resolve_city(city_input: str) -> str:
    return CITY_ALIASES.get(city_input.lower().strip(), city_input)

def cleanup_temp():
    try:
        tmp = tempfile.gettempdir()
        for item in os.listdir(tmp):
            path = os.path.join(tmp, item)
            if os.path.isdir(path) and item.startswith('tmp'):
                shutil.rmtree(path, ignore_errors=True)
    except: pass
    gc.collect()

# ═══════════════ КЛАВИАТУРЫ ═══════════════
MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [[KeyboardButton("🎲 Ролл"), KeyboardButton("🪙 Монетка")],
     [KeyboardButton("🌤 Погода"), KeyboardButton("🎵 Музыка")],
     [KeyboardButton("📧 Почта (5 мин)"), KeyboardButton("⚡ Флеш")],
     [KeyboardButton("💡 Предложить"), KeyboardButton("😂 Мем")],
     [KeyboardButton("💬 Анонимный чат")]],
    resize_keyboard=True, is_persistent=True
)

ANON_CHAT_KEYBOARD = ReplyKeyboardMarkup(
    [[KeyboardButton("➡️ Следующий"), KeyboardButton("🚪 Выйти")]],
    resize_keyboard=True
)

MAGIC_BALL_ANSWERS = [
    "✅ Бесспорно", "🎯 Предрешено", "💯 Никаких сомнений", "👍 Определённо да",
    "🔮 Можешь быть уверен", "😏 Мне кажется — да", "🤔 Вероятнее всего",
    "🌟 Хорошие перспективы", "✨ Знаки говорят — да", "💤 Пока не ясно",
    "⏳ Спроси позже", "🤐 Лучше не рассказывать", "❓ Сейчас нельзя предсказать",
]

# ═══════════════ СТАРТ ═══════════════
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in anon_chat_pairs:
        await exit_anon_chat(user_id, context)
    
    text = (
        "⚡ *Привет! Я Flash Bot!*\n\n"
        "🎲 `флеш ролл` — бросок 1-100\n"
        "🌤 `флеш погода [город]` — погода\n"
        "🪙 `флеш монетка` — орёл или решка\n"
        "🎙 `флеш голос` — голосовое → текст\n"
        "🎵 `флеш музыка [название]` — найти трек\n"
        "📧 `флеш почта` — временная почта\n"
        "💱 `флеш курс` — курс валют\n"
        "🪙 `флеш крипта` — BTC и ETH\n"
        "🎱 `флеш шар [вопрос]` — шар судьбы\n"
        "⏰ `флеш таймер [минуты]` — таймер\n"
        "🎬 `флеш кино [название]` — поиск фильма\n"
        "📺 `флеш сериал [название]` — поиск сериала\n"
        "🔗 `флеш сократить [ссылка]` — короткая ссылка\n"
        "📝 `флеш перевод [текст]` — перевод\n"
        "😂 `флеш мем` — случайный мем\n"
        "📥 `флеш тг [ссылка]` — скачать из ТГ\n"
        "💬 `флеш чат` — анонимный чат\n"
        "💡 `флеш предложить` — идея для бота\n\n"
        "🔗 *Скинь ссылку* из YouTube/TikTok — скачаю!"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=MAIN_KEYBOARD)

async def flash_help(update, context): await start(update, context)

# ═══════════════ РАЗВЛЕЧЕНИЯ ═══════════════
async def flash_roll(update, context):
    user = update.effective_user
    roll = random.randint(1, 100)
    name = user.first_name or "Игрок"
    if roll == 100: c = "🏆 МАКСИМУМ!"
    elif roll >= 80: c = "🔥 Отлично!"
    elif roll >= 50: c = "😎 Неплохо!"
    elif roll >= 20: c = "😅 Так себе..."
    else: c = "💀 Провал!"
    await update.message.reply_text(f"🎲 *{name}* бросает кости...\n\nВыпало: *{roll}/100*\n{c}", parse_mode=ParseMode.MARKDOWN)

async def flash_coin(update, context):
    await update.message.reply_text(f"Подбрасываю...\n\n{random.choice(['🦅 Орёл!', '🪙 Решка!'])}")

async def flash_magic_ball(update, context, question=None):
    if not question: await update.message.reply_text("🎱 Задай вопрос: `флеш шар я выиграю?`", parse_mode=ParseMode.MARKDOWN); return
    await update.message.reply_text(f"🎱 *Вопрос:* {question}\n\n🔮 *Ответ:* {random.choice(MAGIC_BALL_ANSWERS)}", parse_mode=ParseMode.MARKDOWN)

async def flash_timer(update, context, minutes_str=None):
    if not minutes_str: await update.message.reply_text("⏰ Укажи: `флеш таймер 5`", parse_mode=ParseMode.MARKDOWN); return
    try:
        minutes = int(minutes_str)
        if not 1 <= minutes <= 120: await update.message.reply_text("⏰ 1-120 мин."); return
    except: await update.message.reply_text("⏰ Число."); return
    uid, cid = update.effective_user.id, update.effective_chat.id
    finish = datetime.now() + timedelta(minutes=minutes)
    active_timers[uid] = finish
    await update.message.reply_text(f"⏰ *Таймер {minutes} мин.*\nЗакончится в {finish.strftime('%H:%M:%S')}", parse_mode=ParseMode.MARKDOWN)
    await asyncio.sleep(minutes * 60)
    if uid in active_timers:
        try: await context.bot.send_message(cid, "⏰ *Время вышло!*", parse_mode=ParseMode.MARKDOWN)
        except: pass
        del active_timers[uid]

async def flash_crypto(update, context):
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum&vs_currencies=usd&include_24hr_change=true") as r:
                data = await r.json()
        btc, eth = data.get("bitcoin", {}), data.get("ethereum", {})
        await update.message.reply_text(f"🪙 *Крипта:*\n₿ BTC: *${btc.get('usd','?'):,.0f}* ({btc.get('usd_24h_change',0):+.2f}%)\n♦️ ETH: *${eth.get('usd','?'):,.0f}* ({eth.get('usd_24h_change',0):+.2f}%)", parse_mode=ParseMode.MARKDOWN)
    except: await update.message.reply_text("❌ Ошибка.")

# ═══════════════ ПОГОДА ═══════════════
async def flash_weather(update, context, city=None):
    if not city: await update.message.reply_text("❗ Укажи город: `флеш погода Алматы`", parse_mode=ParseMode.MARKDOWN); return
    city = resolve_city(city)
    msg = await update.message.reply_text(f"🌤 Ищу погоду в *{city}*...", parse_mode=ParseMode.MARKDOWN)
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://api.openweathermap.org/data/2.5/weather", params={"q": city, "appid": WEATHER_API_KEY, "units": "metric", "lang": "ru"}) as r:
                if r.status != 200: await msg.edit_text(f"❌ Город *{city}* не найден.", parse_mode=ParseMode.MARKDOWN); return
                c = await r.json()
            lat, lon = c["coord"]["lat"], c["coord"]["lon"]
            tzo = c["timezone"]
            async with s.get("https://api.openweathermap.org/data/2.5/forecast", params={"lat": lat, "lon": lon, "appid": WEATHER_API_KEY, "units": "metric", "lang": "ru", "cnt": 4}) as r:
                fc = await r.json() if r.status == 200 else None
        icons = {"Clear":"☀️","Clouds":"☁️","Rain":"🌧","Snow":"❄️","Thunderstorm":"⛈","Drizzle":"🌦","Mist":"🌫","Fog":"🌫"}
        icon = icons.get(c["weather"][0]["main"], "🌡")
        tz = timezone(timedelta(seconds=tzo))
        lt = datetime.now(timezone.utc).astimezone(tz).strftime("%H:%M")
        sr = datetime.fromtimestamp(c["sys"]["sunrise"], tz=tz).strftime("%H:%M")
        ss = datetime.fromtimestamp(c["sys"]["sunset"], tz=tz).strftime("%H:%M")
        text = f"{icon} *Погода в {c['name']}*\n🕐 {lt}\n\n🌡 *{c['main']['temp']:.0f}°C* (ощущается {c['main']['feels_like']:.0f}°C)\n💧 {c['main']['humidity']}%\n💨 {c['wind']['speed']} м/с\n📋 {c['weather'][0]['description'].capitalize()}\n🌅 {sr}\n🌇 {ss}"
        if fc and fc.get("list"):
            text += "\n\n📊 *Прогноз:*\n"
            for item in fc["list"][:4]:
                ft = datetime.fromtimestamp(item["dt"], tz=tz).strftime("%H:%M")
                fi = icons.get(item["weather"][0]["main"], "🌡")
                text += f"{fi} {ft} — *{item['main']['temp']:.0f}°C*\n"
        await msg.edit_text(text, parse_mode=ParseMode.MARKDOWN)
    except: await msg.edit_text("❌ Ошибка.")

# ═══════════════ ГОЛОС (speech_recognition + ffmpeg) ═══════════════
async def flash_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg.reply_to_message:
        await msg.reply_text("❗ Ответь на голосовое `флеш голос`", parse_mode=ParseMode.MARKDOWN)
        return
    target = msg.reply_to_message.voice or msg.reply_to_message.video_note or msg.reply_to_message.audio
    if not target:
        await msg.reply_text("❗ Ответь на голосовое, видео или аудио.")
        return
    
    status = await msg.reply_text("🎙 Скачиваю...")
    tmpdir = None
    
    try:
        tmpdir = tempfile.mkdtemp()
        
        file = await context.bot.get_file(target.file_id)
        input_path = os.path.join(tmpdir, "input.ogg")
        wav_path = os.path.join(tmpdir, "output.wav")
        await file.download_to_drive(input_path)
        
        await status.edit_text("🎙 Конвертирую...")
        
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-i", input_path, "-ar", "16000", "-ac", "1", "-f", "wav", wav_path,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL
        )
        await proc.wait()
        
        if not os.path.exists(wav_path) or os.path.getsize(wav_path) == 0:
            await status.edit_text("❌ Ошибка конвертации.")
            return
        
        await status.edit_text("🎙 Распознаю...")
        
        import speech_recognition as sr
        
        def recognize():
            r = sr.Recognizer()
            with sr.AudioFile(wav_path) as source:
                audio = r.record(source)
            try:
                return r.recognize_google(audio, language="ru-RU")
            except sr.UnknownValueError:
                return None
            except sr.RequestError:
                return None
        
        loop = asyncio.get_event_loop()
        text = await loop.run_in_executor(None, recognize)
        
        if text:
            await status.edit_text(f"🎙 *Расшифровка:*\n\n{text}", parse_mode=ParseMode.MARKDOWN)
        else:
            await status.edit_text("🎙 Не распознано. Попробуй говорить чётче.")
    
    except Exception as e:
        logger.error(f"Voice: {e}")
        await status.edit_text("❌ Ошибка распознавания.")
    finally:
        if tmpdir and os.path.exists(tmpdir):
            shutil.rmtree(tmpdir, ignore_errors=True)

# ═══════════════ МУЗЫКА (SOUNDCLOUD + YOUTUBE) ═══════════════
async def flash_music_search(update: Update, context: ContextTypes.DEFAULT_TYPE, query: str):
    if not query:
        await update.message.reply_text("🎵 Укажи название: `флеш музыка Imagine Dragons`", parse_mode=ParseMode.MARKDOWN)
        return
    
    msg = await update.message.reply_text(f"🔍 Ищу *{query}*...", parse_mode=ParseMode.MARKDOWN)
    
    try:
        import yt_dlp
        
        def search_sc():
            opts = {
                "quiet": True, "no_warnings": True, "extract_flat": "in_playlist",
                "http_headers": {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Referer": "https://soundcloud.com/"
                }
            }
            with yt_dlp.YoutubeDL(opts) as ydl:
                return ydl.extract_info(f"scsearch5:{query}", download=False)
        
        def search_yt():
            opts = {"quiet": True, "no_warnings": True, "extract_flat": "in_playlist"}
            with yt_dlp.YoutubeDL(opts) as ydl:
                return ydl.extract_info(f"ytsearch5:{query}", download=False)
        
        loop = asyncio.get_event_loop()
        
        source = "YouTube"
        info = None
        try:
            info = await loop.run_in_executor(None, search_sc)
            if info and info.get("entries"):
                source = "SoundCloud"
        except:
            pass
        
        if not info or not info.get("entries"):
            info = await loop.run_in_executor(None, search_yt)
        
        entries = info.get("entries", []) if info else []
        entries = [e for e in entries if e]
        
        if not entries:
            await msg.edit_text(f"❌ По запросу *{query}* ничего не найдено.", parse_mode=ParseMode.MARKDOWN)
            return
        
        uid = update.effective_user.id
        results = []
        buttons = []
        src_icon = "🔊" if source == "SoundCloud" else "▶️"
        
        for i, entry in enumerate(entries[:5]):
            title = entry.get("title") or f"Трек {i+1}"
            url = entry.get("webpage_url") or entry.get("url") or ""
            duration = int(entry.get("duration") or 0)
            
            if duration > 0:
                mins, secs = divmod(duration, 60)
                dur_str = f"{mins}:{secs:02d}"
            else:
                dur_str = "??:??"
            
            results.append({"title": title, "url": url, "duration": duration, "source": source})
            buttons.append([InlineKeyboardButton(f"{src_icon} {i+1}. {title[:40]} [{dur_str}]", callback_data=f"dl_music:{uid}:{i}")])
        
        pending_music[uid] = results
        
        await msg.edit_text(
            f"🎵 *Найдено на {source}*\n🔍 `{query}`\n\nВыбери трек:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(buttons)
        )
    
    except Exception as e:
        logger.error(f"Music search: {e}")
        await msg.edit_text("❌ Ошибка поиска.")

async def download_music_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    
    if not q.data.startswith("dl_music:"): return
    _, uid_str, idx_str = q.data.split(":")
    uid, idx = int(uid_str), int(idx_str)
    
    tracks = pending_music.get(uid, [])
    if idx >= len(tracks):
        await q.message.edit_text("❌ Сессия устарела.")
        return
    
    track = tracks[idx]
    source = track.get("source", "")
    await q.message.edit_text(f"⬇️ Скачиваю с *{source}*:\n*{track['title'][:50]}*", parse_mode=ParseMode.MARKDOWN)
    
    tmpdir = None
    try:
        tmpdir = tempfile.mkdtemp()
        import yt_dlp
        
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": os.path.join(tmpdir, "%(title)s.%(ext)s"),
            "quiet": True, "no_warnings": True,
            "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}],
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://soundcloud.com/" if source == "SoundCloud" else "https://www.youtube.com/",
            },
            "max_filesize": 48 * 1024 * 1024,
        }
        
        def dl():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([track["url"]])
        
        await asyncio.get_event_loop().run_in_executor(None, dl)
        
        files = list(Path(tmpdir).glob("*.mp3"))
        if not files:
            files = [f for f in Path(tmpdir).iterdir() if f.suffix.lower() in (".mp3", ".m4a", ".opus", ".ogg", ".webm")]
        
        if not files: raise FileNotFoundError("Файл не найден")
        if files[0].stat().st_size > 50*1024*1024:
            await q.message.edit_text("⚠️ Файл > 50 МБ.")
            return
        
        await q.message.edit_text("📤 Отправляю...")
        async with aiofiles.open(files[0], "rb") as f:
            data = await f.read()
        
        await q.message.reply_audio(audio=data, title=track["title"], duration=track["duration"])
        await q.message.delete()
    
    except Exception as e:
        logger.error(f"Music DL: {e}")
        await q.message.edit_text(f"❌ Не удалось скачать трек. Попробуй другой.")
    finally:
        if tmpdir: shutil.rmtree(tmpdir, ignore_errors=True); gc.collect()

# ═══════════════ ВРЕМЕННАЯ ПОЧТА ═══════════════
async def flash_mail(update, context):
    if not is_private(update): await update.message.reply_text("📧 Только в личке."); return
    msg = await update.message.reply_text("📧 Создаю...")
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://api.guerrillamail.com/ajax.php?f=get_email_address") as r:
                d = await r.json()
        await msg.edit_text(f"📧 `{d['email_addr']}`\n⏰ 10 мин", parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📥 Проверить", callback_data=f"gm_check:{d['sid_token']}")]]))
    except: await msg.edit_text("❌ Ошибка.")

async def guerrilla_callback(update, context):
    q = update.callback_query; await q.answer()
    if q.data.startswith("gm_check:"):
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(f"https://api.guerrillamail.com/ajax.php?f=get_email_list&offset=0&sid_token={q.data.split(':',1)[1]}") as r:
                    emails = (await r.json()).get("list",[])
            if not emails: await q.answer("📭 Пусто.",show_alert=True); return
            text = "📥 *Входящие:*\n\n"
            for m in emails[:5]: text += f"📨 `{m.get('mail_from','?')}`\n   {m.get('mail_subject','(без темы)')}\n\n"
            await q.message.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Обновить", callback_data=f"gm_check:{q.data.split(':',1)[1]}")]]))
        except: await q.answer("❌ Ошибка.",show_alert=True)

# ═══════════════ ПРЕДЛОЖЕНИЯ ═══════════════
async def flash_idea_start(update, context):
    pending_idea.add(update.effective_user.id)
    await update.message.reply_text("💡 *Жду идею!*", parse_mode=ParseMode.MARKDOWN)

async def flash_idea_receive(update, context):
    uid, text = update.effective_user.id, update.message.text.strip()
    if text.lower() == "отмена": pending_idea.discard(uid); await update.message.reply_text("❌ Отменено."); return
    try:
        with open("ideas.txt","a",encoding="utf-8") as f: f.write(f"\n{'='*50}\n💡 {update.effective_user.full_name} | {uid}\n{text}\n")
        if OWNER_ID: await context.bot.send_message(OWNER_ID, f"💡 *Идея*\n{text}", parse_mode=ParseMode.MARKDOWN)
    except: pass
    pending_idea.discard(uid)
    await update.message.reply_text("✅ *Спасибо!*", parse_mode=ParseMode.MARKDOWN)

# ═══════════════ СКАЧАТЬ ВИДЕО ═══════════════
async def download_video(update, context, url):
    msg = await update.message.reply_text("⬇️ Скачиваю...")
    tmpdir = None
    try:
        tmpdir = tempfile.mkdtemp()
        import yt_dlp
        is_sc = "soundcloud.com" in url
        opts = {
            "format": "bestaudio/best" if is_sc else "bestvideo[height<=720]+bestaudio/best",
            "outtmpl": os.path.join(tmpdir, "%(title)s.%(ext)s"),
            "quiet": True, "merge_output_format": "mp4", "max_filesize": 48*1024*1024,
            "http_headers": {"User-Agent": "Mozilla/5.0"}
        }
        if is_sc: opts["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3"}]
        def dl():
            with yt_dlp.YoutubeDL(opts) as y: return y.extract_info(url, download=True)
        info = await asyncio.get_event_loop().run_in_executor(None, dl)
        if info and "entries" in info: info = info["entries"][0]
        title = info.get("title","Файл") if info else "Файл"
        dur = int(info.get("duration") or 0) if info else 0
        await msg.edit_text("📤 Отправляю...")
        files = list(Path(tmpdir).glob("*.mp3")) if is_sc else list(Path(tmpdir).glob("*.mp4"))
        if not files: files = [f for f in Path(tmpdir).iterdir() if f.suffix.lower() in (".mp4",".mkv",".webm",".mov",".mp3",".m4a",".opus",".ogg")]
        if not files: raise FileNotFoundError("Файл не найден")
        if files[0].stat().st_size > 50*1024*1024: await msg.edit_text("⚠️ > 50 МБ."); return
        async with aiofiles.open(files[0],"rb") as f: data = await f.read()
        if is_sc: await update.message.reply_audio(audio=data, title=title, duration=dur)
        else: await update.message.reply_video(video=data, caption=f"🎬 {title}", duration=dur, supports_streaming=True)
        await msg.delete()
    except: await msg.edit_text("❌ Ошибка.")
    finally:
        if tmpdir: shutil.rmtree(tmpdir, ignore_errors=True); gc.collect()

# ═══════════════ АНОНИМНЫЙ ЧАТ ═══════════════
async def exit_anon_chat(user_id, context):
    if user_id in anon_chat_pairs:
        partner_id = anon_chat_pairs[user_id]
        del anon_chat_pairs[user_id]
        del anon_chat_pairs[partner_id]
        anon_chat_users.discard(user_id)
        anon_chat_users.discard(partner_id)
        try:
            await context.bot.send_message(partner_id, "👋 Собеседник покинул чат.\n`флеш чат` — найти нового!", reply_markup=MAIN_KEYBOARD)
        except: pass
    if user_id in anon_chat_queue:
        anon_chat_queue.remove(user_id)
    anon_chat_users.discard(user_id)

async def find_new_partner(user_id, context):
    await exit_anon_chat(user_id, context)
    if anon_chat_queue:
        pid = anon_chat_queue.pop(0)
        anon_chat_pairs[user_id] = pid
        anon_chat_pairs[pid] = user_id
        anon_chat_users.add(user_id)
        anon_chat_users.add(pid)
        await context.bot.send_message(user_id, "💬 *Собеседник найден!*", parse_mode=ParseMode.MARKDOWN, reply_markup=ANON_CHAT_KEYBOARD)
        await context.bot.send_message(pid, "💬 *Собеседник найден!*", parse_mode=ParseMode.MARKDOWN, reply_markup=ANON_CHAT_KEYBOARD)
    else:
        anon_chat_queue.append(user_id)
        anon_chat_users.add(user_id)
        await context.bot.send_message(user_id, "⏳ *Ищу собеседника...*", parse_mode=ParseMode.MARKDOWN, reply_markup=ANON_CHAT_KEYBOARD)

async def flash_anon_chat_start(update, context):
    if not is_private(update): await update.message.reply_text("💬 Только в личке."); return
    uid = update.effective_user.id
    if uid in anon_chat_pairs: await update.message.reply_text("💬 Ты уже в чате!", reply_markup=ANON_CHAT_KEYBOARD); return
    await find_new_partner(uid, context)

async def flash_anon_chat_stop(update, context):
    uid = update.effective_user.id
    await exit_anon_chat(uid, context)
    await update.message.reply_text("👋 Вышел из чата.", reply_markup=MAIN_KEYBOARD)

async def anon_chat_next(update, context):
    uid = update.effective_user.id
    if uid in anon_chat_pairs:
        pid = anon_chat_pairs[uid]
        try: await context.bot.send_message(pid, "👋 Собеседник ушёл.", reply_markup=ANON_CHAT_KEYBOARD)
        except: pass
        del anon_chat_pairs[uid], anon_chat_pairs[pid]
        anon_chat_users.discard(uid)
        anon_chat_users.discard(pid)
    await find_new_partner(uid, context)

async def anon_chat_message(update, context):
    if not update.message or not update.message.text: return
    uid = update.effective_user.id
    if uid not in anon_chat_pairs: return
    text = update.message.text.strip()
    if text == "➡️ Следующий": await anon_chat_next(update, context); return
    elif text == "🚪 Выйти": await flash_anon_chat_stop(update, context); return
    elif text.lower() in ["стоп", "/stop_chat"]: await flash_anon_chat_stop(update, context); return
    pid = anon_chat_pairs[uid]
    try: await context.bot.send_message(pid, f"💬 *Аноним:* {text}", parse_mode=ParseMode.MARKDOWN)
    except:
        await update.message.reply_text("❌ Собеседник отключился.", reply_markup=ANON_CHAT_KEYBOARD)
        await exit_anon_chat(uid, context)

# ═══════════════ КУРС ВАЛЮТ ═══════════════
async def flash_rate(update, context):
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://open.er-api.com/v6/latest/USD") as r: data = await r.json()
        rates = data.get("rates",{})
        await update.message.reply_text(f"💱 *Курс к USD:*\n🇷🇺 RUB: *{rates.get('RUB','?'):.2f}*\n🇰🇿 KZT: *{rates.get('KZT','?'):.2f}*\n🇺🇦 UAH: *{rates.get('UAH','?'):.2f}*\n🇪🇺 EUR: *{rates.get('EUR','?'):.4f}*\n🇬🇧 GBP: *{rates.get('GBP','?'):.4f}*", parse_mode=ParseMode.MARKDOWN)
    except: await update.message.reply_text("❌ Ошибка.")

# ═══════════════ ПОИСК ФИЛЬМОВ ═══════════════
async def search_movie_tv(update, query, media_type):
    msg = await update.message.reply_text("🔍 Ищу...", parse_mode=ParseMode.MARKDOWN)
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(f"https://api.themoviedb.org/3/search/{media_type}", params={"api_key":TMDB_KEY,"query":query,"language":"ru-RU"}) as r:
                results = (await r.json()).get("results",[])
        if not results: await msg.edit_text("❌ Не найдено."); return
        btns = []
        for i, item in enumerate(results[:5]):
            title = item.get("title") if media_type == "movie" else item.get("name","?")
            year = (item.get("release_date") if media_type == "movie" else item.get("first_air_date") or "")[:4]
            btns.append([InlineKeyboardButton(f"{i+1}. {title[:35]} ({year}) ⭐{item.get('vote_average',0):.1f}", callback_data=f"movie_info:{media_type}:{item['id']}:{title.replace(':','：')}:{year}")])
        await msg.edit_text(f"{'🎬 Фильмы' if media_type=='movie' else '📺 Сериалы'}:", parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(btns))
    except: await msg.edit_text("❌ Ошибка.")

async def movie_info_callback(update, context):
    q = update.callback_query; await q.answer()
    try: _, media, tid, tc, yc = q.data.split(":",4)
    except: await q.message.edit_text("❌ Ошибка."); return
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(f"https://api.themoviedb.org/3/{media}/{tid}", params={"api_key":TMDB_KEY,"language":"ru-RU"}) as r:
                d = await r.json()
        title = d.get("title") if media == "movie" else d.get("name", tc or "?")
        year = (d.get("release_date") if media == "movie" else d.get("first_air_date") or yc or "")[:4]
        rating, genres = d.get("vote_average",0), ", ".join([g["name"] for g in d.get("genres",[])][:3])
        overview, poster = d.get("overview","Нет описания"), d.get("poster_path","")
        if media == "movie":
            rt = d.get("runtime",0)
            extra = f"\n⏱ *{rt} мин*" if rt else ""
            text = f"🎬 *{title}* ({year})\n\n⭐ *{rating:.1f}/10*\n🎭 {genres}{extra}\n\n📖 {overview[:500]}"
        else:
            s, e = d.get("number_of_seasons","?"), d.get("number_of_episodes","?")
            er = d.get("episode_run_time",[])
            extra = f"\n📅 *Сезонов: {s} | Серий: {e}*"
            if er: extra += f"\n⏱ *Серия: ~{er[0]} мин*"
            text = f"📺 *{title}* ({year})\n\n⭐ *{rating:.1f}/10*\n🎭 {genres}{extra}\n\n📖 {overview[:500]}"
        if poster: await q.message.reply_photo(photo=f"https://image.tmdb.org/t/p/w500{poster}", caption=text, parse_mode=ParseMode.MARKDOWN)
        else: await q.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
        await q.message.delete()
    except: await q.message.edit_text("❌ Ошибка.")

async def flash_movie(update, context, query=None):
    if not query: await update.message.reply_text("❗ `флеш кино Интерстеллар`", parse_mode=ParseMode.MARKDOWN); return
    if any(w in query.lower() for w in BAD_WORDS): await update.message.reply_text(random.choice(SHAME_RESPONSES)); return
    await search_movie_tv(update, query, "movie")

async def flash_series(update, context, query=None):
    if not query: await update.message.reply_text("❗ `флеш сериал Мистер Робот`", parse_mode=ParseMode.MARKDOWN); return
    if any(w in query.lower() for w in BAD_WORDS): await update.message.reply_text(random.choice(SHAME_RESPONSES)); return
    await search_movie_tv(update, query, "tv")

async def flash_short(update, context, url=None):
    if not url: await update.message.reply_text("❗ `флеш сократить https://...`", parse_mode=ParseMode.MARKDOWN); return
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(f"https://tinyurl.com/api-create.php?url={url}") as r: await update.message.reply_text(f"🔗 `{await r.text()}`", parse_mode=ParseMode.MARKDOWN)
    except: await update.message.reply_text("❌ Ошибка.")

async def flash_translate(update, context, query=None):
    if not query: await update.message.reply_text("❗ `флеш перевод hello`", parse_mode=ParseMode.MARKDOWN); return
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://translate.googleapis.com/translate_a/single", params={"client":"gtx","sl":"auto","tl":"ru","dt":"t","q":query}) as r: data = await r.json()
        await update.message.reply_text(f"🌍 *Перевод:*\n{''.join([item[0] for item in data[0] if item[0]])}", parse_mode=ParseMode.MARKDOWN)
    except: await update.message.reply_text("❌ Ошибка.")

async def flash_meme(update, context):
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://www.reddit.com/r/memes/random/.json", headers={"User-Agent": "Mozilla/5.0"}) as r:
                if r.status == 200:
                    post = (await r.json())[0]["data"]["children"][0]["data"]
                    url = post.get("url_overridden_by_dest") or post.get("url", "")
                    if url and any(url.endswith(ext) for ext in [".jpg",".png",".jpeg",".gif"]):
                        await update.message.reply_photo(photo=url, caption=f"😂 {post.get('title','Мем')}")
                        return
    except: pass
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://meme-api.com/gimme") as r:
                d = await r.json()
                if d.get("url"): await update.message.reply_photo(photo=d["url"], caption=d.get("title","😂")); return
    except: pass
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://api.imgflip.com/get_memes") as r:
                memes = (await r.json()).get("data",{}).get("memes",[])
                if memes:
                    m = random.choice(memes)
                    await update.message.reply_photo(photo=m["url"], caption=f"😂 {m['name']}")
                    return
    except: pass
    await update.message.reply_text("😅 Мемы временно недоступны.")

# ═══════════════ ОБРАБОТЧИК ═══════════════
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    uid = update.effective_user.id
    if uid in anon_chat_pairs: await anon_chat_message(update, context); return
    raw, text = update.message.text.strip(), update.message.text.lower().strip()
    if uid in pending_idea: await flash_idea_receive(update, context); return
    
    if text == "🎲 ролл": await flash_roll(update, context); return
    elif text == "🪙 монетка": await flash_coin(update, context); return
    elif text == "⚡ флеш": await flash_help(update, context); return
    elif text == "🌤 погода": await update.message.reply_text("🌤 `флеш погода Город`", parse_mode=ParseMode.MARKDOWN); return
    elif text == "🎵 музыка": await update.message.reply_text("🎵 `флеш музыка название`", parse_mode=ParseMode.MARKDOWN); return
    elif text == "📧 почта (5 мин)": await flash_mail(update, context); return
    elif text == "💡 предложить": await flash_idea_start(update, context); return
    elif text == "😂 мем": await flash_meme(update, context); return
    elif text == "💬 анонимный чат": await flash_anon_chat_start(update, context); return
    
    url = extract_url(raw)
    if url:
        if is_tg_url(url):
            try:
                m = TG_PATTERN.search(url)
                cid, mid = m.groups()
                cids = [f"@{cid}"] if not cid.lstrip('-').isdigit() else [int(cid)] + ([int(f"-100{cid}")] if not cid.startswith("-100") else [])
                for c in cids:
                    try: await context.bot.copy_message(chat_id=update.effective_chat.id, from_chat_id=c, message_id=int(mid)); return
                    except: continue
            except: pass
        if is_supported_url(url): await download_video(update, context, url); return
    
    if not text.startswith("флеш"): return
    parts = text.split(None, 2)
    if len(parts) == 1: await flash_help(update, context); return
    cmd, arg = parts[1], parts[2].strip() if len(parts) > 2 else ""
    
    if cmd == "ролл": await flash_roll(update, context)
    elif cmd == "монетка": await flash_coin(update, context)
    elif cmd == "погода": await flash_weather(update, context, city=arg or None)
    elif cmd == "голос": await flash_voice(update, context)
    elif cmd == "музыка": await flash_music_search(update, context, arg)
    elif cmd == "почта": await flash_mail(update, context)
    elif cmd == "курс": await flash_rate(update, context)
    elif cmd == "крипта": await flash_crypto(update, context)
    elif cmd == "шар": await flash_magic_ball(update, context, question=arg or None)
    elif cmd == "таймер": await flash_timer(update, context, minutes_str=arg or None)
    elif cmd == "кино": await flash_movie(update, context, query=arg or None)
    elif cmd == "сериал": await flash_series(update, context, query=arg or None)
    elif cmd == "сократить": await flash_short(update, context, url=arg or None)
    elif cmd == "перевод": await flash_translate(update, context, query=arg or None)
    elif cmd == "мем": await flash_meme(update, context)
    elif cmd == "чат": await flash_anon_chat_start(update, context)
    elif cmd == "тг":
        if arg:
            try:
                m = TG_PATTERN.search(arg)
                if m:
                    cid, mid = m.groups()
                    cids = [f"@{cid}"] if not cid.lstrip('-').isdigit() else [int(cid)] + ([int(f"-100{cid}")] if not cid.startswith("-100") else [])
                    for c in cids:
                        try: await context.bot.copy_message(chat_id=update.effective_chat.id, from_chat_id=c, message_id=int(mid)); return
                        except: continue
            except: pass
            await update.message.reply_text("❌ Не удалось.")
        else: await update.message.reply_text("❗ `флеш тг [ссылка]`", parse_mode=ParseMode.MARKDOWN)
    elif cmd in ("предложить", "идея"): await flash_idea_start(update, context)
    else: await flash_help(update, context)

# ═══════════════ MAIN ═══════════════
def main():
    import requests
    try: requests.post(f"https://api.telegram.org/bot{TOKEN}/deleteWebhook", timeout=5)
    except: pass
    time.sleep(1)
    cleanup_temp()
    
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop_chat", flash_anon_chat_stop))
    app.add_handler(CallbackQueryHandler(download_music_callback, pattern="^dl_music:"))
    app.add_handler(CallbackQueryHandler(guerrilla_callback, pattern="^gm_"))
    app.add_handler(CallbackQueryHandler(movie_info_callback, pattern="^movie_info:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    async def err(update, context):
        if "Conflict" in str(context.error): await asyncio.sleep(5)
    app.add_error_handler(err)
    logger.info("⚡ Flash Bot запущен!")
    
    webhook_url = os.environ.get("WEBHOOK_URL")
    port = int(os.environ.get("PORT", "8443"))
    if webhook_url: app.run_webhook(listen="0.0.0.0", port=port, webhook_url=webhook_url, drop_pending_updates=True)
    else: app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
