import logging
import random
import os
import re
import asyncio
import aiohttp
import aiofiles
import tempfile
import string
import json
import shutil
import subprocess
import sys
import signal
import time
import gc
from pathlib import Path
from datetime import datetime, timedelta
from urllib.parse import quote

time.sleep(3)

# Убиваем старые процессы
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
    print("✅ yt-dlp обновлён")
except: pass

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ContextTypes, CallbackQueryHandler
)
from telegram.constants import ChatType, ParseMode

# ─── КЛЮЧИ ────────────────────────────────────────────────────────────────────
TOKEN = os.environ.get("BOT_TOKEN", "8638601182:AAHAOf2wvybOOyhyt_PNijYkKkljJwGnN-g").strip()
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
user_languages = {}

BAD_WORDS = ["порно", "porn", "секс", "sex", "xxx", "18+", "эротика", "хентай", "hentai"]
SHAME_RESPONSES = [
    "🫣 АЙ-АЙ-АЙ! Иди лучше Машу и Медведя смотри!",
    "😤 ЧТО ЭТО ТАКОЕ?! Марш смотреть Смешариков!",
    "🙈 КАКОЙ СТЫД! Лунтик ждёт тебя, немедленно!",
    "👀 Я ЧТО ВИЖУ?! Иди Фиксиков пересматривай!",
    "😱 АЙ-АЙ-АЙ КАКОЙ(АЯ)! Телепузики обидятся!",
    "🚫 НЕТ-НЕТ-НЕТ! Иди Губку Боба смотри давай!",
]

def is_private(u): return u.effective_chat.type == ChatType.PRIVATE
def extract_url(t):
    m = URL_REGEX.search(t)
    return m.group(0) if m else None
def is_supported_url(url): return any(d in url.lower() for d in SUPPORTED_DOMAINS)
def is_audio_url(url): return "soundcloud.com" in url.lower()
def is_tg_url(url): return bool(TG_PATTERN.search(url))

def cleanup_temp():
    try:
        tmp = tempfile.gettempdir()
        for item in os.listdir(tmp):
            path = os.path.join(tmp, item)
            if os.path.isdir(path) and item.startswith('tmp'):
                shutil.rmtree(path, ignore_errors=True)
    except: pass
    gc.collect()

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [[KeyboardButton("🎲 Ролл"), KeyboardButton("🪙 Монетка")],
     [KeyboardButton("🌤 Погода"), KeyboardButton("🎵 Музыка")],
     [KeyboardButton("📧 Почта (10 мин)"), KeyboardButton("⚡ Флеш")],
     [KeyboardButton("💡 Предложить"), KeyboardButton("😂 Мем")]],
    resize_keyboard=True, is_persistent=True
)

MAGIC_BALL_ANSWERS = [
    "✅ Бесспорно", "🎯 Предрешено", "💯 Никаких сомнений", "👍 Определённо да",
    "🔮 Можешь быть уверен", "😏 Мне кажется — да", "🤔 Вероятнее всего",
    "🌟 Хорошие перспективы", "✨ Знаки говорят — да", "💤 Пока не ясно",
    "⏳ Спроси позже", "🤐 Лучше не рассказывать", "❓ Сейчас нельзя предсказать",
    "🔍 Сконцентрируйся и спроси опять", "🙅 Даже не думай", "👎 Мой ответ — нет",
    "🔮 По моим данным — нет", "😬 Перспективы не очень", "💀 Весьма сомнительно"
]

# ─── СТАРТ ────────────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = (
        f"⚡ *Привет, {user.first_name or 'друг'}!*\n\n"
        "🎲 *Развлечения:*\n"
        "  `флеш ролл` — бросок 1-100\n"
        "  `флеш монетка` — орёл или решка\n"
        "  `флеш шар [вопрос]` — шар судьбы\n"
        "  `флеш таймер [мин]` — таймер\n\n"
        "🌤 *Инфо:*\n"
        "  `флеш погода [город]` — подробная погода\n"
        "  `флеш курс` — курс валют\n"
        "  `флеш крипта` — курс BTC и ETH\n\n"
        "🎬 *Поиск:*\n"
        "  `флеш кино [название]` — инфо о фильме\n"
        "  `флеш сериал [название]` — инфо о сериале\n\n"
        "🛠 *Инструменты:*\n"
        "  `флеш музыка [запрос]` — найти и скачать\n"
        "  `флеш голос` (ответом) — речь в текст\n"
        "  `флеш перевод [текст]` — на русский\n"
        "  `флеш сократить [url]` — короткая ссылка\n"
        "  `флеш почта` — временная почта\n"
        "  `флеш тг [ссылка]` — из ТГ канала\n\n"
        "📥 *Скинь ссылку* из YouTube/TikTok/Instagram — скачаю!\n"
        "💡 `флеш предложить` — идея для бота\n"
        "⚡ `флеш` — это меню"
    )
    kb = MAIN_KEYBOARD if is_private(update) else None
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)

async def flash_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

# ─── РАЗВЛЕЧЕНИЯ ──────────────────────────────────────────────────────────────
async def flash_roll(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    roll = random.randint(1, 100)
    name = user.first_name or "Игрок"
    
    if roll == 100:
        emoji, comment = "🏆", "ЛЕГЕНДАРНЫЙ БРОСОК! Максимум!"
    elif roll >= 90:
        emoji, comment = "🔥", "Потрясающе! Почти идеально!"
    elif roll >= 80:
        emoji, comment = "🌟", "Отличный результат!"
    elif roll >= 65:
        emoji, comment = "😎", "Хороший бросок!"
    elif roll >= 50:
        emoji, comment = "👍", "Неплохо, середнячок!"
    elif roll >= 35:
        emoji, comment = "😐", "Так себе, бывает и лучше..."
    elif roll >= 20:
        emoji, comment = "😅", "Слабо... Повезёт в другой раз!"
    elif roll >= 5:
        emoji, comment = "💀", "Почти провал..."
    else:
        emoji, comment = "☠️", "ЭПИЧЕСКИЙ ПРОВАЛ!"
    
    await update.message.reply_text(
        f"{emoji} *{name}* бросает кости...\n\n"
        f"🎯 Выпало: *{roll}/100*\n"
        f"📢 {comment}",
        parse_mode=ParseMode.MARKDOWN
    )

async def flash_coin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = random.choice(['🦅 Орёл!', '🪙 Решка!'])
    emoji = "🦅" if "Орёл" in result else "🪙"
    await update.message.reply_text(
        f"{emoji} Подбрасываю монетку...\n\n"
        f"Выпало: *{result}*",
        parse_mode=ParseMode.MARKDOWN
    )

async def flash_magic_ball(update: Update, context: ContextTypes.DEFAULT_TYPE, question: str = None):
    if not question:
        await update.message.reply_text(
            "🎱 *Шар судьбы*\n\nЗадай вопрос:\n`флеш шар я выиграю в лотерею?`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    answer = random.choice(MAGIC_BALL_ANSWERS)
    await update.message.reply_text(
        f"🎱 *Шар судьбы*\n\n"
        f"❓ *Вопрос:* {question}\n\n"
        f"🔮 *Ответ:* {answer}",
        parse_mode=ParseMode.MARKDOWN
    )

async def flash_timer(update: Update, context: ContextTypes.DEFAULT_TYPE, minutes_str: str = None):
    if not minutes_str:
        await update.message.reply_text("⏰ Укажи время:\n`флеш таймер 5` (минут)", parse_mode=ParseMode.MARKDOWN)
        return
    try:
        minutes = int(minutes_str)
        if not 1 <= minutes <= 120:
            await update.message.reply_text("⏰ Укажи от 1 до 120 минут.")
            return
    except:
        await update.message.reply_text("⏰ Нужно число! `флеш таймер 5`")
        return
    
    user_id, chat_id = update.effective_user.id, update.effective_chat.id
    finish = datetime.now() + timedelta(minutes=minutes)
    active_timers[user_id] = finish
    
    await update.message.reply_text(
        f"⏰ *Таймер запущен!*\n\n"
        f"⏱ Длительность: *{minutes} мин.*\n"
        f"🏁 Закончится: *{finish.strftime('%H:%M:%S')}*\n\n"
        f"Я напишу когда время выйдет!",
        parse_mode=ParseMode.MARKDOWN
    )
    
    await asyncio.sleep(minutes * 60)
    if user_id in active_timers:
        try:
            await context.bot.send_message(
                chat_id,
                f"⏰ *ВРЕМЯ ВЫШЛО!*\n\nПрошло ровно *{minutes} минут* с момента запуска таймера.",
                parse_mode=ParseMode.MARKDOWN
            )
        except: pass
        del active_timers[user_id]

# ─── ПОГОДА (РАСШИРЕННАЯ) ────────────────────────────────────────────────────
async def flash_weather(update: Update, context: ContextTypes.DEFAULT_TYPE, city=None):
    if not city:
        await update.message.reply_text(
            "🌤 *Погода*\n\nУкажи город:\n`флеш погода Алматы`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    msg = await update.message.reply_text(f"🌤 Ищу погоду в *{city}*...", parse_mode=ParseMode.MARKDOWN)
    
    try:
        # Текущая погода
        async with aiohttp.ClientSession() as s:
            async with s.get(
                f"https://api.openweathermap.org/data/2.5/weather",
                params={"q": city, "appid": WEATHER_API_KEY, "units": "metric", "lang": "ru"}
            ) as r:
                if r.status != 200:
                    await msg.edit_text(f"❌ Город *{city}* не найден.", parse_mode=ParseMode.MARKDOWN)
                    return
                current = await r.json()
            
            # Прогноз на 3 часа
            lat, lon = current["coord"]["lat"], current["coord"]["lon"]
            async with s.get(
                f"https://api.openweathermap.org/data/2.5/forecast",
                params={"lat": lat, "lon": lon, "appid": WEATHER_API_KEY, "units": "metric", "lang": "ru", "cnt": 4}
            ) as r:
                forecast = await r.json() if r.status == 200 else None
        
        # Иконки
        icons = {
            "Clear": "☀️", "Clouds": "☁️", "Rain": "🌧", "Snow": "❄️",
            "Thunderstorm": "⛈", "Drizzle": "🌦", "Mist": "🌫", "Fog": "🌫"
        }
        weather_main = current["weather"][0]["main"]
        icon = icons.get(weather_main, "🌡")
        desc = current["weather"][0]["description"].capitalize()
        
        # Текущая погода
        temp = current["main"]["temp"]
        feels = current["main"]["feels_like"]
        humidity = current["main"]["humidity"]
        pressure = current["main"]["pressure"]
        wind_speed = current["wind"]["speed"]
        wind_deg = current["wind"].get("deg", 0)
        visibility = current.get("visibility", 0) / 1000
        
        # Направление ветра
        wind_dirs = ["⬆️ С", "↗️ СВ", "➡️ В", "↘️ ЮВ", "⬇️ Ю", "↙️ ЮЗ", "⬅️ З", "↖️ СЗ"]
        wind_dir = wind_dirs[round(wind_deg / 45) % 8] if wind_deg else "?"
        
        # Восход/закат
        sunrise = datetime.fromtimestamp(current["sys"]["sunrise"]).strftime("%H:%M")
        sunset = datetime.fromtimestamp(current["sys"]["sunset"]).strftime("%H:%M")
        
        text = (
            f"{icon} *Погода в {current['name']}, {current['sys']['country']}*\n\n"
            f"🌡 *Температура:* `{temp:.0f}°C` (ощущается `{feels:.0f}°C`)\n"
            f"📋 *Состояние:* {desc}\n\n"
            f"💧 *Влажность:* `{humidity}%`\n"
            f"🔵 *Давление:* `{pressure} гПа`\n"
            f"💨 *Ветер:* `{wind_speed} м/с` {wind_dir}\n"
            f"👁 *Видимость:* `{visibility:.1f} км`\n\n"
            f"🌅 *Восход:* `{sunrise}`\n"
            f"🌇 *Закат:* `{sunset}`"
        )
        
        # Прогноз на ближайшие часы
        if forecast and forecast.get("list"):
            text += "\n\n📊 *Прогноз на 9 часов:*\n"
            for item in forecast["list"][:4]:
                time_str = item["dt_txt"].split()[1][:5]
                temp_f = item["main"]["temp"]
                desc_f = item["weather"][0]["description"].capitalize()
                icon_f = icons.get(item["weather"][0]["main"], "🌡")
                text += f"  {icon_f} `{time_str}` — *{temp_f:.0f}°C* ({desc_f})\n"
        
        await msg.edit_text(text, parse_mode=ParseMode.MARKDOWN)
        
    except Exception as e:
        logger.error(f"Weather: {e}")
        await msg.edit_text("❌ Ошибка получения погоды.")

# ─── РАСПОЗНАВАНИЕ ГОЛОСА ────────────────────────────────────────────────────
async def flash_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg.reply_to_message:
        await msg.reply_text("❗ Ответь на голосовое сообщение:\n`флеш голос`", parse_mode=ParseMode.MARKDOWN)
        return
    
    target = msg.reply_to_message.voice or msg.reply_to_message.video_note
    if not target:
        await msg.reply_text("❗ Это не голосовое сообщение!")
        return
    
    status = await msg.reply_text("🎙 *Распознаю речь...*", parse_mode=ParseMode.MARKDOWN)
    tmpdir = None
    
    try:
        tmpdir = tempfile.mkdtemp()
        file = await context.bot.get_file(target.file_id)
        ogg_path = os.path.join(tmpdir, "voice.ogg")
        wav_path = os.path.join(tmpdir, "voice.wav")
        await file.download_to_drive(ogg_path)
        
        # Конвертация через ffmpeg
        import shutil as _sh
        ffmpeg = _sh.which("ffmpeg") or "ffmpeg"
        proc = await asyncio.create_subprocess_exec(
            ffmpeg, "-y", "-i", ogg_path, "-ar", "16000", "-ac", "1", "-f", "wav", wav_path,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
        )
        await proc.wait()
        
        # Отправка в Google Speech API
        import requests as _rq
        loop = asyncio.get_event_loop()
        
        def recognize():
            with open(wav_path, "rb") as f:
                wav_data = f.read()
            resp = _rq.post(
                "https://www.google.com/speech-api/v2/recognize?output=json&lang=ru-RU&key=AIzaSyBOti4mM-6x9WDnZIjIeyEU21OpBXqWBgw",
                data=wav_data,
                headers={"Content-Type": "audio/l16; rate=16000"}
            )
            result = ""
            for line in resp.text.strip().split("\n"):
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    for r in data.get("result", []):
                        for alt in r.get("alternative", []):
                            result += alt.get("transcript", "") + " "
                except:
                    continue
            return result.strip()
        
        text = await loop.run_in_executor(None, recognize)
        
        if text:
            await status.edit_text(
                f"🎙 *Расшифровка голосового:*\n\n"
                f"📝 {text}\n\n"
                f"📊 *Символов:* {len(text)}",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await status.edit_text("🎙 Речь не распознана. Попробуй говорить чётче.")
            
    except Exception as e:
        logger.error(f"Voice: {e}")
        await status.edit_text("❌ Ошибка распознавания.")
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)

# ─── МУЗЫКА ───────────────────────────────────────────────────────────────────
import shutil as _shutil

def _find_ffmpeg():
    p = _shutil.which("ffmpeg")
    if p: return p
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except: pass
    for path in ["/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/nix/store"]:
        import glob as _glob
        if os.path.exists(path): return path
        matches = _glob.glob(f"{path}/**/ffmpeg", recursive=True)
        if matches: return matches[0]
    return "ffmpeg"

_FFMPEG = _find_ffmpeg()

SC_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "ffmpeg_location": _FFMPEG,
    "http_headers": {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://soundcloud.com/"
    }
}

async def flash_music_search(update: Update, context: ContextTypes.DEFAULT_TYPE, query: str):
    msg = await update.message.reply_text(f"🔍 Ищу *{query}*...", parse_mode=ParseMode.MARKDOWN)
    
    try:
        import yt_dlp
        
        def search():
            opts = {**SC_OPTS, "extract_flat": "in_playlist"}
            with yt_dlp.YoutubeDL(opts) as ydl:
                # Пробуем SoundCloud
                try:
                    info = ydl.extract_info(f"scsearch5:{query}", download=False)
                    if info and info.get("entries"):
                        return info, "sc"
                except: pass
                # Fallback на YouTube
                info = ydl.extract_info(f"ytsearch5:{query}", download=False)
                return info, "yt"
        
        loop = asyncio.get_event_loop()
        info, source = await loop.run_in_executor(None, search)
        
        entries = [e for e in info.get("entries", []) if e]
        if not entries:
            await msg.edit_text("❌ Ничего не найдено. Попробуй другой запрос.")
            return
        
        uid = update.effective_user.id
        results = []
        buttons = []
        src_icon = "🔊" if source == "sc" else "▶️"
        src_name = "SoundCloud" if source == "sc" else "YouTube"
        
        for i, entry in enumerate(entries[:5]):
            title = entry.get("title") or f"Трек {i+1}"
            url = entry.get("webpage_url") or entry.get("url") or ""
            duration = int(entry.get("duration") or 0)
            mins, secs = divmod(duration, 60)
            
            results.append({
                "title": title,
                "url": url,
                "duration": duration
            })
            
            label = f"{src_icon} {i+1}. {title[:40]}"
            if duration > 0:
                label += f" ({mins}:{secs:02d})"
            buttons.append([InlineKeyboardButton(label, callback_data=f"dl_music:{uid}:{i}")])
        
        pending_music[uid] = results
        
        await msg.edit_text(
            f"🎵 *Найдено на {src_name}:*\n\n"
            f"🔍 Запрос: `{query}`\n"
            f"📊 Результатов: {len(entries)}\n\n"
            f"*Выбери трек для скачивания:*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        
    except Exception as e:
        logger.error(f"Music search: {e}")
        await msg.edit_text("❌ Ошибка поиска. Попробуй позже.")

async def download_music_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if not query.data.startswith("dl_music:"):
        return
    
    _, uid_str, idx_str = query.data.split(":")
    uid, idx = int(uid_str), int(idx_str)
    
    tracks = pending_music.get(uid, [])
    if idx >= len(tracks):
        await query.message.edit_text("❌ Сессия устарела. Повтори поиск.")
        return
    
    track = tracks[idx]
    await query.message.edit_text(
        f"⬇️ *Скачиваю:* {track['title']}\n\nПожалуйста подожди...",
        parse_mode=ParseMode.MARKDOWN
    )
    
    tmpdir = None
    try:
        tmpdir = tempfile.mkdtemp()
        import yt_dlp
        
        ydl_opts = {
            **SC_OPTS,
            "format": "bestaudio/best",
            "outtmpl": os.path.join(tmpdir, "%(title)s.%(ext)s"),
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192"
            }],
            "max_filesize": 48 * 1024 * 1024,
        }
        
        def download():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([track["url"]])
        
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, download)
        
        # Ищем скачанный файл
        files = list(Path(tmpdir).glob("*.mp3"))
        if not files:
            files = list(Path(tmpdir).glob("*.*"))
        if not files:
            raise FileNotFoundError("Аудиофайл не найден")
        
        await query.message.edit_text("📤 *Отправляю трек...*", parse_mode=ParseMode.MARKDOWN)
        
        async with aiofiles.open(files[0], "rb") as f:
            audio_data = await f.read()
        
        await query.message.reply_audio(
            audio=audio_data,
            title=track["title"],
            duration=track["duration"],
            caption=f"🎵 *{track['title']}*",
            parse_mode=ParseMode.MARKDOWN
        )
        await query.message.delete()
        
    except Exception as e:
        logger.error(f"Music download: {e}")
        await query.message.edit_text("❌ Не удалось скачать трек. Возможно он недоступен.")
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)
            gc.collect()

# ─── ВРЕМЕННАЯ ПОЧТА ─────────────────────────────────────────────────────────
async def flash_mail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_private(update):
        await update.message.reply_text("📧 Временная почта работает только в личных сообщениях.")
        return
    
    msg = await update.message.reply_text("📧 *Создаю почтовый ящик...*", parse_mode=ParseMode.MARKDOWN)
    
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://api.guerrillamail.com/ajax.php?f=get_email_address") as r:
                data = await r.json()
        
        email = data["email_addr"]
        sid_token = data["sid_token"]
        
        await msg.edit_text(
            f"📧 *Временная почта готова!*\n\n"
            f"📮 *Адрес:* `{email}`\n"
            f"⏰ *Срок:* 10 минут\n\n"
            f"Нажми кнопку чтобы проверить входящие:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📥 Проверить письма", callback_data=f"gm_check:{sid_token}")],
                [InlineKeyboardButton("🔄 Новый ящик", callback_data="gm_new")],
                [InlineKeyboardButton("🗑 Закрыть", callback_data="gm_delete")]
            ])
        )
        
    except Exception as e:
        logger.error(f"Mail: {e}")
        await msg.edit_text("❌ Ошибка создания почты.")

async def guerrilla_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data == "gm_new":
        await flash_mail(update, context)
        return
    
    if data == "gm_delete":
        await query.message.edit_text("🗑 Почтовая сессия закрыта.")
        return
    
    if data.startswith("gm_check:"):
        sid = data.split(":", 1)[1]
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(
                    f"https://api.guerrillamail.com/ajax.php?f=get_email_list&offset=0&sid_token={sid}"
                ) as r:
                    result = await r.json()
                    emails = result.get("list", [])
            
            if not emails:
                await query.answer("📭 Входящих писем пока нет.", show_alert=True)
                return
            
            text = "📥 *Входящие письма:*\n\n"
            for i, mail in enumerate(emails[:5], 1):
                from_addr = mail.get("mail_from", "Неизвестно")
                subject = mail.get("mail_subject", "(без темы)")
                date = mail.get("mail_date", "")
                text += f"{i}️⃣ 📨 *От:* `{from_addr}`\n"
                text += f"   📋 *Тема:* {subject}\n"
                if date:
                    text += f"   🕐 {date}\n"
                text += "\n"
            
            await query.message.edit_text(
                text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Обновить", callback_data=f"gm_check:{sid}")],
                    [InlineKeyboardButton("🗑 Закрыть", callback_data="gm_delete")]
                ])
            )
        except Exception as e:
            logger.error(f"Mail check: {e}")
            await query.answer("❌ Ошибка проверки.", show_alert=True)

# ─── ПРЕДЛОЖЕНИЯ ─────────────────────────────────────────────────────────────
async def flash_idea_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    pending_idea.add(user_id)
    await update.message.reply_text(
        "💡 *Режим предложений*\n\n"
        "Напиши свою идею для бота одним сообщением.\n"
        "Что добавить? Что улучшить?\n\n"
        "Для отмены напиши `отмена`.",
        parse_mode=ParseMode.MARKDOWN
    )

async def flash_idea_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = update.effective_user
    text = update.message.text.strip()
    
    if text.lower() == "отмена":
        pending_idea.discard(user_id)
        await update.message.reply_text("❌ Отправка идеи отменена.")
        return
    
    name = user.full_name
    username = f"@{user.username}" if user.username else "нет"
    date_str = update.message.date.strftime("%d.%m.%Y %H:%M")
    
    # Сохраняем в файл
    try:
        with open("ideas.txt", "a", encoding="utf-8") as f:
            f.write(f"\n{'='*50}\n")
            f.write(f"💡 Идея от: {name} ({username}) | ID: {user_id}\n")
            f.write(f"📅 Дата: {date_str}\n")
            f.write(f"{'='*50}\n")
            f.write(f"{text}\n")
    except: pass
    
    # Отправляем владельцу
    if OWNER_ID:
        try:
            await context.bot.send_message(
                OWNER_ID,
                f"💡 *Новая идея!*\n\n"
                f"👤 *От:* {name} (`{user_id}`)\n"
                f"📅 *Дата:* {date_str}\n\n"
                f"📝 *Текст:* {text}",
                parse_mode=ParseMode.MARKDOWN
            )
        except: pass
    
    pending_idea.discard(user_id)
    await update.message.reply_text(
        "✅ *Спасибо за идею!*\n\n"
        "Я передал её владельцу бота. Возможно именно твоя идея появится в следующем обновлении!",
        parse_mode=ParseMode.MARKDOWN
    )

# ─── СКАЧАТЬ ВИДЕО С САЙТОВ ─────────────────────────────────────────────────
async def download_video(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str):
    audio_only = is_audio_url(url)
    msg = await update.message.reply_text("⬇️ *Скачиваю...*", parse_mode=ParseMode.MARKDOWN)
    tmpdir = None
    
    try:
        tmpdir = tempfile.mkdtemp()
        import yt_dlp
        
        if audio_only:
            ydl_opts = {
                "format": "bestaudio/best",
                "outtmpl": os.path.join(tmpdir, "%(title)s.%(ext)s"),
                "quiet": True,
                "ffmpeg_location": _FFMPEG,
                "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}],
                "max_filesize": 48 * 1024 * 1024,
            }
        else:
            ydl_opts = {
                "format": "bestvideo[height<=720]+bestaudio/best[height<=720]/best",
                "outtmpl": os.path.join(tmpdir, "%(title)s.%(ext)s"),
                "quiet": True,
                "merge_output_format": "mp4",
                "max_filesize": 48 * 1024 * 1024,
                "http_headers": {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            }
        
        def do_download():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(url, download=True)
        
        loop = asyncio.get_event_loop()
        info = await loop.run_in_executor(None, do_download)
        
        if info and "entries" in info:
            info = info["entries"][0]
        
        title = info.get("title", "Файл") if info else "Файл"
        duration = int(info.get("duration") or 0) if info else 0
        
        await msg.edit_text(f"📤 *Отправляю:* {title[:50]}", parse_mode=ParseMode.MARKDOWN)
        
        if audio_only:
            files = list(Path(tmpdir).glob("*.mp3"))
            if not files:
                files = [f for f in Path(tmpdir).iterdir() if f.suffix in (".mp3", ".m4a", ".opus", ".ogg")]
        else:
            files = list(Path(tmpdir).glob("*.mp4"))
            if not files:
                files = [f for f in Path(tmpdir).iterdir() if f.suffix in (".mp4", ".mkv", ".webm", ".mov")]
        
        if not files:
            raise FileNotFoundError("Файл не найден")
        
        file_size = files[0].stat().st_size
        if file_size > 50 * 1024 * 1024:
            await msg.edit_text(f"⚠️ Файл слишком большой ({file_size / 1024 / 1024:.1f} МБ). Лимит 50 МБ.")
            return
        
        async with aiofiles.open(files[0], "rb") as f:
            file_data = await f.read()
        
        if audio_only:
            await update.message.reply_audio(
                audio=file_data,
                title=title,
                duration=duration,
                caption=f"🎵 *{title}*",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_video(
                video=file_data,
                caption=f"🎬 *{title}*",
                duration=duration,
                supports_streaming=True,
                parse_mode=ParseMode.MARKDOWN
            )
        
        await msg.delete()
        
    except Exception as e:
        logger.error(f"Video download: {e}")
        error_msg = str(e).lower()
        if "too large" in error_msg or "filesize" in error_msg:
            await msg.edit_text("❌ Файл слишком большой (лимит 50 МБ).")
        elif "private" in error_msg or "login" in error_msg:
            await msg.edit_text("❌ Контент недоступен (закрытый аккаунт).")
        else:
            await msg.edit_text("❌ Не удалось скачать. Проверь ссылку.")
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)
            gc.collect()

# ─── СКАЧАТЬ ИЗ ТГ ───────────────────────────────────────────────────────────
async def download_tg(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str):
    msg = await update.message.reply_text("📥 *Скачиваю из Telegram...*", parse_mode=ParseMode.MARKDOWN)
    
    match = TG_PATTERN.search(url)
    if not match:
        await msg.edit_text("❌ Неверная ссылка на Telegram сообщение.")
        return
    
    chat_id_str, message_id = match.groups()
    message_id = int(message_id)
    
    # Собираем варианты для перебора
    chat_ids_to_try = []
    
    if not chat_id_str.lstrip('-').isdigit():
        # Это username канала
        chat_ids_to_try.append(f"@{chat_id_str}")
    else:
        # Числовой ID
        chat_ids_to_try.append(int(chat_id_str))
        if not chat_id_str.startswith("-100"):
            chat_ids_to_try.append(int(f"-100{chat_id_str}"))
    
    for chat_id in chat_ids_to_try:
        try:
            await context.bot.copy_message(
                chat_id=update.effective_chat.id,
                from_chat_id=chat_id,
                message_id=message_id
            )
            await msg.delete()
            return
        except Exception as e:
            continue
    
    await msg.edit_text(
        "❌ *Не удалось получить сообщение.*\n\n"
        "Возможные причины:\n"
        "• Канал приватный (нужен доступ)\n"
        "• Бот не добавлен в канал\n"
        "• Неверная ссылка\n\n"
        "Попробуй другую ссылку.",
        parse_mode=ParseMode.MARKDOWN
    )

# ─── КУРС ВАЛЮТ ──────────────────────────────────────────────────────────────
async def flash_rate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("💱 *Загружаю курсы валют...*", parse_mode=ParseMode.MARKDOWN)
    
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://open.er-api.com/v6/latest/USD") as r:
                data = await r.json()
        
        rates = data.get("rates", {})
        update_time = data.get("time_last_update_utc", "?").replace("+0000", "").strip()
        
        text = (
            f"💱 *Курсы валют к USD*\n\n"
            f"🇷🇺 *RUB:* `{rates.get('RUB', '?'):.2f}` ₽\n"
            f"🇰🇿 *KZT:* `{rates.get('KZT', '?'):.2f}` ₸\n"
            f"🇺🇦 *UAH:* `{rates.get('UAH', '?'):.2f}` ₴\n"
            f"🇪🇺 *EUR:* `{rates.get('EUR', '?'):.4f}` €\n"
            f"🇬🇧 *GBP:* `{rates.get('GBP', '?'):.4f}` £\n"
            f"🇨🇳 *CNY:* `{rates.get('CNY', '?'):.2f}` ¥\n"
            f"🇯🇵 *JPY:* `{rates.get('JPY', '?'):.0f}` ¥\n"
            f"🇹🇷 *TRY:* `{rates.get('TRY', '?'):.2f}` ₺\n\n"
            f"📅 *Обновлено:* {update_time}"
        )
        
        await msg.edit_text(text, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"Rate: {e}")
        await msg.edit_text("❌ Ошибка получения курса.")

# ─── КРИПТА ──────────────────────────────────────────────────────────────────
async def flash_crypto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("🪙 *Загружаю курс криптовалют...*", parse_mode=ParseMode.MARKDOWN)
    
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={
                    "ids": "bitcoin,ethereum,toncoin",
                    "vs_currencies": "usd",
                    "include_24hr_change": "true",
                    "include_24hr_vol": "true"
                }
            ) as r:
                data = await r.json()
        
        btc = data.get("bitcoin", {})
        eth = data.get("ethereum", {})
        ton = data.get("toncoin", {})
        
        def fmt(coin):
            price = coin.get("usd", 0)
            change = coin.get("usd_24h_change", 0)
            vol = coin.get("usd_24h_vol", 0)
            emoji = "🟢" if change > 0 else "🔴" if change < 0 else "⚪"
            return price, change, vol, emoji
        
        btc_p, btc_c, btc_v, btc_e = fmt(btc)
        eth_p, eth_c, eth_v, eth_e = fmt(eth)
        ton_p, ton_c, ton_v, ton_e = fmt(ton)
        
        text = (
            f"🪙 *Криптовалюта (USD)*\n\n"
            f"₿ *Bitcoin*\n"
            f"  💰 `${btc_p:,.0f}`\n"
            f"  {btc_e} *24ч:* {btc_c:+.2f}%\n"
            f"  📊 Объём: `${btc_v:,.0f}`\n\n"
            f"♦️ *Ethereum*\n"
            f"  💰 `${eth_p:,.0f}`\n"
            f"  {eth_e} *24ч:* {eth_c:+.2f}%\n"
            f"  📊 Объём: `${eth_v:,.0f}`\n\n"
            f"💎 *Toncoin*\n"
            f"  💰 `${ton_p:,.2f}`\n"
            f"  {ton_e} *24ч:* {ton_c:+.2f}%"
        )
        
        await msg.edit_text(text, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"Crypto: {e}")
        await msg.edit_text("❌ Ошибка загрузки криптовалют.")

# ─── ПОИСК ФИЛЬМОВ ──────────────────────────────────────────────────────────
async def search_movie_tv(update, query: str, media_type: str):
    msg = await update.message.reply_text(f"🔍 *Ищу в базе TMDB...*", parse_mode=ParseMode.MARKDOWN)
    
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                f"https://api.themoviedb.org/3/search/{media_type}",
                params={"api_key": TMDB_KEY, "query": query, "language": "ru-RU"}
            ) as r:
                search = await r.json()
        
        results = search.get("results", [])
        if not results:
            await msg.edit_text(f"❌ По запросу *{query}* ничего не найдено.", parse_mode=ParseMode.MARKDOWN)
            return
        
        buttons = []
        for i, item in enumerate(results[:5]):
            if media_type == "movie":
                title = item.get("title", "?")
                year = (item.get("release_date") or "")[:4]
            else:
                title = item.get("name", "?")
                year = (item.get("first_air_date") or "")[:4]
            
            rating = item.get("vote_average", 0)
            safe_title = title.replace(":", "：").replace(",", "，")
            
            label = f"{i+1}. {title[:35]} ({year}) ⭐{rating:.1f}"
            buttons.append([InlineKeyboardButton(
                label,
                callback_data=f"movie_info:{media_type}:{item['id']}:{safe_title}:{year}"
            )])
        
        type_name = "🎬 Фильмы" if media_type == "movie" else "📺 Сериалы"
        total = search.get("total_results", 0)
        
        await msg.edit_text(
            f"{type_name} по запросу *{query}*\n"
            f"📊 Найдено: {total}\n\n"
            f"*Выбери для подробностей:*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(buttons)
        )
    except Exception as e:
        logger.error(f"Search: {e}")
        await msg.edit_text("❌ Ошибка поиска.")

async def movie_info_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    try:
        _, media_type, tmdb_id, title_cb, year_cb = query.data.split(":", 4)
    except:
        await query.message.edit_text("❌ Ошибка данных.")
        return
    
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}",
                params={"api_key": TMDB_KEY, "language": "ru-RU"}
            ) as r:
                detail = await r.json()
        
        if media_type == "movie":
            title = detail.get("title", title_cb or "?")
            original = detail.get("original_title", "")
            year = (detail.get("release_date") or year_cb or "")[:4]
            icon = "🎬"
            runtime = detail.get("runtime", 0)
            extra = f"\n⏱ *Длительность:* {runtime} мин" if runtime else ""
            budget = detail.get("budget", 0)
            if budget > 0:
                extra += f"\n💰 *Бюджет:* ${budget:,}"
        else:
            title = detail.get("name", title_cb or "?")
            original = detail.get("original_name", "")
            year = (detail.get("first_air_date") or year_cb or "")[:4]
            icon = "📺"
            seasons = detail.get("number_of_seasons", "?")
            episodes = detail.get("number_of_episodes", "?")
            extra = f"\n📅 *Сезонов:* {seasons} | *Серий:* {episodes}"
        
        rating = detail.get("vote_average", 0)
        votes = detail.get("vote_count", 0)
        genres_list = detail.get("genres", [])
        genres = ", ".join([g["name"] for g in genres_list[:4]])
        overview = detail.get("overview", "Нет описания")
        status = detail.get("status", "")
        
        poster_path = detail.get("poster_path", "")
        backdrop_path = detail.get("backdrop_path", "")
        
        text = (
            f"{icon} *{title}*\n"
            + (f"🌍 *Оригинал:* {original}\n" if original and original != title else "")
            + f"📅 *Год:* {year}\n"
            + (f"📊 *Статус:* {status}\n" if status else "")
            + f"⭐ *Рейтинг:* {rating:.1f}/10 ({votes:,} голосов)\n"
            + f"🎭 *Жанры:* {genres}\n"
            + extra
            + f"\n\n📖 *Описание:*\n{overview[:800]}"
        )
        
        if poster_path:
            await query.message.reply_photo(
                photo=f"https://image.tmdb.org/t/p/w500{poster_path}",
                caption=text,
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await query.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
        
        await query.message.delete()
        
    except Exception as e:
        logger.error(f"Movie info: {e}")
        await query.message.edit_text("❌ Ошибка загрузки информации.")

async def flash_movie(update, context, query=None):
    if not query:
        await update.message.reply_text("❗ Укажи название:\n`флеш кино Интерстеллар`", parse_mode=ParseMode.MARKDOWN)
        return
    if any(w in query.lower() for w in BAD_WORDS):
        await update.message.reply_text(random.choice(SHAME_RESPONSES))
        return
    await search_movie_tv(update, query, "movie")

async def flash_series(update, context, query=None):
    if not query:
        await update.message.reply_text("❗ Укажи название:\n`флеш сериал Мистер Робот`", parse_mode=ParseMode.MARKDOWN)
        return
    if any(w in query.lower() for w in BAD_WORDS):
        await update.message.reply_text(random.choice(SHAME_RESPONSES))
        return
    await search_movie_tv(update, query, "tv")

# ─── СОКРАЩЕНИЕ ССЫЛОК ───────────────────────────────────────────────────────
async def flash_short(update, context, url=None):
    if not url:
        await update.message.reply_text("❗ Укажи ссылку:\n`флеш сократить https://example.com`", parse_mode=ParseMode.MARKDOWN)
        return
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(f"https://tinyurl.com/api-create.php?url={url}") as r:
                short = await r.text()
        if short.startswith("http"):
            await update.message.reply_text(
                f"🔗 *Короткая ссылка готова!*\n\n"
                f"📥 *Исходная:* `{url[:50]}...`\n"
                f"📤 *Короткая:* `{short}`",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            raise Exception("bad response")
    except:
        await update.message.reply_text("❌ Ошибка сокращения.")

# ─── ПЕРЕВОД ─────────────────────────────────────────────────────────────────
async def flash_translate(update, context, query=None):
    if not query:
        await update.message.reply_text("❗ Укажи текст:\n`флеш перевод Hello world`", parse_mode=ParseMode.MARKDOWN)
        return
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                "https://translate.googleapis.com/translate_a/single",
                params={"client": "gtx", "sl": "auto", "tl": "ru", "dt": "t", "q": query}
            ) as r:
                data = await r.json()
        
        translated = "".join([item[0] for item in data[0] if item[0]])
        src_lang = data[2] if len(data) > 2 else "auto"
        
        await update.message.reply_text(
            f"🌍 *Перевод*\n\n"
            f"🔤 *Исходный язык:* {src_lang}\n"
            f"📝 *Текст:* {translated}",
            parse_mode=ParseMode.MARKDOWN
        )
    except:
        await update.message.reply_text("❌ Ошибка перевода.")

# ─── МЕМЫ ────────────────────────────────────────────────────────────────────
async def flash_meme(update, context):
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://meme-api.com/gimme/rus") as r:
                data = await r.json()
                if data.get("url"):
                    await update.message.reply_photo(
                        photo=data["url"],
                        caption=f"😂 *{data.get('title', 'Мем')}*",
                        parse_mode=ParseMode.MARKDOWN
                    )
                    return
    except: pass
    
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://api.imgflip.com/get_memes") as r:
                data = await r.json()
                memes = data.get("data", {}).get("memes", [])
                if memes:
                    meme = random.choice(memes)
                    await update.message.reply_photo(
                        photo=meme["url"],
                        caption=f"😂 *{meme['name']}*",
                        parse_mode=ParseMode.MARKDOWN
                    )
                    return
    except: pass
    
    await update.message.reply_text("😅 Мемы временно недоступны.")

# ─── ОБРАБОТЧИК ТЕКСТА ───────────────────────────────────────────────────────
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    
    user_id = update.effective_user.id
    raw = update.message.text.strip()
    text = raw.lower().strip()
    
    # Режим предложений
    if user_id in pending_idea:
        await flash_idea_receive(update, context)
        return
    
    # Кнопки клавиатуры
    if text == "🎲 ролл":
        await flash_roll(update, context); return
    elif text == "🪙 монетка":
        await flash_coin(update, context); return
    elif text == "⚡ флеш":
        await flash_help(update, context); return
    elif text == "🌤 погода":
        await update.message.reply_text("🌤 *Погода*\n\nУкажи город:\n`флеш погода Алматы`", parse_mode=ParseMode.MARKDOWN); return
    elif text == "🎵 музыка":
        await update.message.reply_text("🎵 *Музыка*\n\nУкажи запрос:\n`флеш музыка imagine dragons`", parse_mode=ParseMode.MARKDOWN); return
    elif text == "📧 почта (10 мин)":
        await flash_mail(update, context); return
    elif text == "💡 предложить":
        await flash_idea_start(update, context); return
    elif text == "😂 мем":
        await flash_meme(update, context); return
    
    # Авто-скачивание по ссылке
    url = extract_url(raw)
    if url:
        if is_tg_url(url):
            await download_tg(update, context, url); return
        if is_supported_url(url):
            await download_video(update, context, url); return
    
    # Команды флеш
    if not text.startswith("флеш"):
        return
    
    parts = text.split(None, 2)
    if len(parts) == 1:
        await flash_help(update, context); return
    
    cmd = parts[1] if len(parts) > 1 else ""
    arg = parts[2].strip() if len(parts) > 2 else ""
    
    if cmd == "ролл":
        await flash_roll(update, context)
    elif cmd == "монетка":
        await flash_coin(update, context)
    elif cmd == "погода":
        await flash_weather(update, context, city=arg or None)
    elif cmd == "голос":
        await flash_voice(update, context)
    elif cmd == "музыка":
        if arg:
            await flash_music_search(update, context, arg)
        else:
            await update.message.reply_text("❗ Укажи запрос:\n`флеш музыка название трека`", parse_mode=ParseMode.MARKDOWN)
    elif cmd == "почта":
        await flash_mail(update, context)
    elif cmd == "курс":
        await flash_rate(update, context)
    elif cmd == "крипта":
        await flash_crypto(update, context)
    elif cmd == "шар":
        await flash_magic_ball(update, context, question=arg or None)
    elif cmd == "таймер":
        await flash_timer(update, context, minutes_str=arg or None)
    elif cmd == "кино":
        await flash_movie(update, context, query=arg or None)
    elif cmd == "сериал":
        await flash_series(update, context, query=arg or None)
    elif cmd == "сократить":
        await flash_short(update, context, url=arg or None)
    elif cmd == "перевод":
        await flash_translate(update, context, query=arg or None)
    elif cmd == "мем":
        await flash_meme(update, context)
    elif cmd == "тг":
        if arg:
            await download_tg(update, context, url=arg)
        else:
            await update.message.reply_text("❗ Укажи ссылку:\n`флеш тг https://t.me/...`", parse_mode=ParseMode.MARKDOWN)
    elif cmd in ("предложить", "идея"):
        await flash_idea_start(update, context)
    else:
        await flash_help(update, context)

# ─── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    import requests
    try:
        requests.post(f"https://api.telegram.org/bot{TOKEN}/deleteWebhook", timeout=5)
    except: pass
    time.sleep(1)
    cleanup_temp()
    
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(download_music_callback, pattern="^dl_music:"))
    app.add_handler(CallbackQueryHandler(guerrilla_callback, pattern="^gm_"))
    app.add_handler(CallbackQueryHandler(movie_info_callback, pattern="^movie_info:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    async def error_handler(update, context):
        logger.error(f"Error: {context.error}")
        if "Conflict" in str(context.error):
            await asyncio.sleep(5)
    
    app.add_error_handler(error_handler)
    logger.info("⚡ Flash Bot запущен!")
    
    webhook_url = os.environ.get("WEBHOOK_URL")
    port = int(os.environ.get("PORT", "8443"))
    
    if webhook_url:
        app.run_webhook(listen="0.0.0.0", port=port, webhook_url=webhook_url, drop_pending_updates=True)
    else:
        app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
