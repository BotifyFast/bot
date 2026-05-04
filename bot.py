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
import gc
from pathlib import Path
from datetime import datetime, timedelta, timezone

# ═══════════════ КОНФИГ ═══════════════
TOKEN = os.environ.get("BOT_TOKEN", "").strip()
WEATHER_API_KEY = os.environ.get("WEATHER_API_KEY", "").strip()
OWNER_ID_STR = os.environ.get("OWNER_ID", "0").strip()
OWNER_ID = int(OWNER_ID_STR) if OWNER_ID_STR.isdigit() else 0
TMDB_KEY = os.environ.get("TMDB_KEY", "").strip()
OPENAI_KEY = os.environ.get("OPENAI_API_KEY", "").strip()

if not TOKEN:
    print("❌ ОШИБКА: BOT_TOKEN не задан!")
    sys.exit(1)

# Установка зависимостей
try:
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-q", "--upgrade",
         "yt-dlp", "python-telegram-bot==21.9", "SpeechRecognition", "pydub"],
        check=True, timeout=90
    )
except Exception as e:
    print(f"⚠️ pip upgrade failed: {e}")

# ═══════════════ FFMPEG - ЖЕСТКАЯ УСТАНОВКА ═══════════════
def install_ffmpeg():
    """Установка ffmpeg и получение путей"""
    
    # Сначала пробуем apt
    try:
        env = {**os.environ, "DEBIAN_FRONTEND": "noninteractive"}
        subprocess.run(["apt-get", "update", "-qq"], timeout=60, env=env, capture_output=True)
        subprocess.run(["apt-get", "install", "-y", "-qq", "ffmpeg"], timeout=180, env=env, capture_output=True)
        
        # Проверяем что установилось
        ffmpeg_result = subprocess.run(["which", "ffmpeg"], capture_output=True, text=True)
        ffprobe_result = subprocess.run(["which", "ffprobe"], capture_output=True, text=True)
        
        if ffmpeg_result.returncode == 0 and ffprobe_result.returncode == 0:
            ffmpeg_path = ffmpeg_result.stdout.strip()
            ffprobe_path = ffprobe_result.stdout.strip()
            print(f"✅ ffmpeg: {ffmpeg_path}")
            print(f"✅ ffprobe: {ffprobe_path}")
            return ffmpeg_path, ffprobe_path
    except Exception as e:
        print(f"⚠️ apt install failed: {e}")

    # Если apt не сработал - качаем статический бинарник
    print("📦 Скачиваю статический ffmpeg...")
    import urllib.request, stat
    
    tar_path = "/tmp/ffmpeg.tar.xz"
    dest_dir = "/tmp/ffmpeg_extracted"
    ffmpeg_dest = "/usr/local/bin/ffmpeg"
    ffprobe_dest = "/usr/local/bin/ffprobe"
    
    urls = [
        "https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz",
        "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"
    ]
    
    for url in urls:
        try:
            urllib.request.urlretrieve(url, tar_path)
            os.makedirs(dest_dir, exist_ok=True)
            subprocess.run(["tar", "-xf", tar_path, "-C", dest_dir], check=True, timeout=120)
            
            # Ищем ffmpeg и ffprobe
            for root, dirs, files in os.walk(dest_dir):
                if "ffmpeg" in files:
                    src = os.path.join(root, "ffmpeg")
                    shutil.copy2(src, ffmpeg_dest)
                    os.chmod(ffmpeg_dest, 0o755)
                    print(f"✅ ffmpeg скопирован: {ffmpeg_dest}")
                    
                if "ffprobe" in files:
                    src = os.path.join(root, "ffprobe")
                    shutil.copy2(src, ffprobe_dest)
                    os.chmod(ffprobe_dest, 0o755)
                    print(f"✅ ffprobe скопирован: {ffprobe_dest}")
            
            if os.path.exists(ffmpeg_dest) and os.path.exists(ffprobe_dest):
                return ffmpeg_dest, ffprobe_dest
        except Exception as e:
            print(f"⚠️ Ошибка с {url}: {e}")
            continue
    
    return None, None

FFMPEG_PATH, FFPROBE_PATH = install_ffmpeg()

if not FFMPEG_PATH or not FFPROBE_PATH:
    print("❌ КРИТИЧЕСКАЯ ОШИБКА: ffmpeg/ffprobe не найдены!")
    print("Музыка и скачивание видео НЕ БУДУТ РАБОТАТЬ!")
else:
    print(f"🎬 FFmpeg настроен:")
    print(f"   ffmpeg:  {FFMPEG_PATH}")
    print(f"   ffprobe: {FFPROBE_PATH}")

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from telegram.constants import ChatType, ParseMode

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

SUPPORTED_DOMAINS = [
    "youtube.com", "youtu.be", "tiktok.com", "vm.tiktok.com",
    "instagram.com", "instagr.am", "soundcloud.com",
    "twitter.com", "x.com", "vk.com", "facebook.com", "fb.watch"
]
TG_PATTERN = re.compile(r'https?://t\.me/(?:c/)?([^/]+)/(\d+)')
URL_REGEX = re.compile(r'https?://[^\s<>"{}|\\^`\[\]]+')

pending_music = {}
pending_idea = set()
active_timers = {}
anon_chat_queue = []
anon_chat_pairs = {}
anon_chat_users = set()
anon_waiting_users = set()

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
    except:
        pass
    gc.collect()

# Клавиатуры
MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [[KeyboardButton("🎲 Ролл"), KeyboardButton("🪙 Монетка")],
     [KeyboardButton("🌤 Погода"), KeyboardButton("🎵 Музыка")],
     [KeyboardButton("📧 Почта (5 мин)"), KeyboardButton("⚡ Флеш")],
     [KeyboardButton("💡 Предложить"), KeyboardButton("😂 Мем")],
     [KeyboardButton("💬 Анонимный чат")]],
    resize_keyboard=True, is_persistent=True
)

WAITING_KEYBOARD = ReplyKeyboardMarkup(
    [[KeyboardButton("🚪 Выйти из поиска")]],
    resize_keyboard=True
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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in anon_chat_pairs:
        await exit_anon_chat(user_id, context)
    if user_id in anon_waiting_users:
        anon_waiting_users.discard(user_id)
        if user_id in anon_chat_queue:
            anon_chat_queue.remove(user_id)

    text = (
        "⚡ *Привет! Я Flash Bot!*\n\n"
        "🎲 `флеш ролл` — бросок 1-100\n"
        "🎵 `флеш музыка [название]` — найти трек\n"
        "🎙 `флеш голос` — голосовое → текст\n"
        "💬 `флеш чат` — анонимный чат\n\n"
        "🔗 *Скинь ссылку* из YouTube/TikTok — скачаю!"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=MAIN_KEYBOARD)

async def flash_help(update, context): await start(update, context)

async def flash_roll(update, context):
    user = update.effective_user
    roll = random.randint(1, 100)
    name = user.first_name or "Игрок"
    if roll == 100:   c = "🏆 МАКСИМУМ!"
    elif roll >= 80:  c = "🔥 Отлично!"
    elif roll >= 50:  c = "😎 Неплохо!"
    elif roll >= 20:  c = "😅 Так себе..."
    else:             c = "💀 Провал!"
    await update.message.reply_text(
        f"🎲 *{name}* бросает кости...\n\nВыпало: *{roll}/100*\n{c}",
        parse_mode=ParseMode.MARKDOWN
    )

async def flash_coin(update, context):
    await update.message.reply_text(f"Подбрасываю...\n\n{random.choice(['🦅 Орёл!', '🪙 Решка!'])}")

async def flash_magic_ball(update, context, question=None):
    if not question:
        await update.message.reply_text("🎱 Задай вопрос: `флеш шар я выиграю?`", parse_mode=ParseMode.MARKDOWN)
        return
    await update.message.reply_text(
        f"🎱 *Вопрос:* {question}\n\n🔮 *Ответ:* {random.choice(MAGIC_BALL_ANSWERS)}",
        parse_mode=ParseMode.MARKDOWN
    )

async def flash_timer(update, context, minutes_str=None):
    if not minutes_str:
        await update.message.reply_text("⏰ Укажи: `флеш таймер 5`", parse_mode=ParseMode.MARKDOWN)
        return
    try:
        minutes = int(minutes_str)
        if not 1 <= minutes <= 120:
            await update.message.reply_text("⏰ 1-120 мин.")
            return
    except:
        await update.message.reply_text("⏰ Число.")
        return
    uid, cid = update.effective_user.id, update.effective_chat.id
    finish = datetime.now() + timedelta(minutes=minutes)
    active_timers[uid] = finish
    await update.message.reply_text(
        f"⏰ *Таймер {minutes} мин.*\nЗакончится в {finish.strftime('%H:%M:%S')}",
        parse_mode=ParseMode.MARKDOWN
    )
    await asyncio.sleep(minutes * 60)
    if uid in active_timers:
        try:
            await context.bot.send_message(cid, "⏰ *Время вышло!*", parse_mode=ParseMode.MARKDOWN)
        except:
            pass
        del active_timers[uid]

async def flash_crypto(update, context):
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                "https://api.coingecko.com/api/v3/simple/price"
                "?ids=bitcoin,ethereum&vs_currencies=usd&include_24hr_change=true"
            ) as r:
                data = await r.json()
        btc, eth = data.get("bitcoin", {}), data.get("ethereum", {})
        await update.message.reply_text(
            f"🪙 *Крипта:*\n"
            f"₿ BTC: *${btc.get('usd', '?'):,.0f}* ({btc.get('usd_24h_change', 0):+.2f}%)\n"
            f"♦️ ETH: *${eth.get('usd', '?'):,.0f}* ({eth.get('usd_24h_change', 0):+.2f}%)",
            parse_mode=ParseMode.MARKDOWN
        )
    except:
        await update.message.reply_text("❌ Ошибка.")

async def flash_weather(update, context, city=None):
    if not city:
        await update.message.reply_text("❗ Укажи город: `флеш погода Алматы`", parse_mode=ParseMode.MARKDOWN)
        return
    city = resolve_city(city)
    msg = await update.message.reply_text(f"🌤 Ищу погоду в *{city}*...", parse_mode=ParseMode.MARKDOWN)
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                "https://api.openweathermap.org/data/2.5/weather",
                params={"q": city, "appid": WEATHER_API_KEY, "units": "metric", "lang": "ru"}
            ) as r:
                if r.status != 200:
                    await msg.edit_text(f"❌ Город *{city}* не найден.", parse_mode=ParseMode.MARKDOWN)
                    return
                c = await r.json()
        icon = {"Clear": "☀️", "Clouds": "☁️", "Rain": "🌧", "Snow": "❄️"}.get(c["weather"][0]["main"], "🌡")
        text = (
            f"{icon} *Погода в {c['name']}*\n\n"
            f"🌡 *{c['main']['temp']:.0f}°C* (ощущается {c['main']['feels_like']:.0f}°C)\n"
            f"💧 {c['main']['humidity']}%\n💨 {c['wind']['speed']} м/с\n"
            f"📋 {c['weather'][0]['description'].capitalize()}"
        )
        await msg.edit_text(text, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"Weather error: {e}")
        await msg.edit_text("❌ Ошибка.")

async def flash_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg.reply_to_message:
        await msg.reply_text("❗ Ответь на голосовое сообщение командой `флеш голос`", parse_mode=ParseMode.MARKDOWN)
        return
    target = msg.reply_to_message.voice or msg.reply_to_message.video_note or msg.reply_to_message.audio
    if not target:
        await msg.reply_text("❗ Ответь на голосовое, кружок или аудио.")
        return
    status = await msg.reply_text("🎙 Скачиваю аудио...")
    tmpdir = None
    try:
        tmpdir = tempfile.mkdtemp()
        file = await context.bot.get_file(target.file_id)
        input_path = os.path.join(tmpdir, "input.oga")
        await file.download_to_drive(input_path)
        if OPENAI_KEY:
            await status.edit_text("🎙 Распознаю через Whisper...")
            try:
                async with aiohttp.ClientSession() as s:
                    with open(input_path, "rb") as audio_file:
                        form = aiohttp.FormData()
                        form.add_field("file", audio_file, filename="audio.oga", content_type="audio/ogg")
                        form.add_field("model", "whisper-1")
                        form.add_field("language", "ru")
                        async with s.post(
                            "https://api.openai.com/v1/audio/transcriptions",
                            headers={"Authorization": f"Bearer {OPENAI_KEY}"},
                            data=form, timeout=aiohttp.ClientTimeout(total=30)
                        ) as r:
                            if r.status == 200:
                                result = await r.json()
                                text = result.get("text", "").strip()
                                if text:
                                    await status.edit_text(f"🎙 *Расшифровка:*\n\n{text}", parse_mode=ParseMode.MARKDOWN)
                                    return
            except:
                pass
        if not FFMPEG_PATH:
            await status.edit_text("❌ ffmpeg не найден.")
            return
        await status.edit_text("🎙 Конвертирую...")
        wav_path = os.path.join(tmpdir, "output.wav")
        proc = await asyncio.create_subprocess_exec(
            FFMPEG_PATH, "-y", "-i", input_path, "-ar", "16000", "-ac", "1", "-f", "wav", wav_path,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        await proc.communicate()
        if not os.path.exists(wav_path) or os.path.getsize(wav_path) == 0:
            await status.edit_text("❌ Ошибка конвертации.")
            return
        await status.edit_text("🎙 Распознаю...")
        try:
            import speech_recognition as sr
            def recognize():
                r = sr.Recognizer()
                with sr.AudioFile(wav_path) as source:
                    audio = r.record(source)
                try:
                    return r.recognize_google(audio, language="ru-RU")
                except:
                    return None
            loop = asyncio.get_event_loop()
            text = await loop.run_in_executor(None, recognize)
            if text:
                await status.edit_text(f"🎙 *Расшифровка:*\n\n{text}", parse_mode=ParseMode.MARKDOWN)
            else:
                await status.edit_text("🎙 Не удалось распознать речь.")
        except ImportError:
            await status.edit_text("❌ SpeechRecognition не установлен.")
    except Exception as e:
        logger.error(f"Voice error: {e}")
        await status.edit_text("❌ Ошибка распознавания.")
    finally:
        if tmpdir and os.path.exists(tmpdir):
            shutil.rmtree(tmpdir, ignore_errors=True)

# ═══════════════ МУЗЫКА - ГЛАВНЫЙ ФИКС ═══════════════
async def flash_music_search(update: Update, context: ContextTypes.DEFAULT_TYPE, query: str):
    if not query:
        await update.message.reply_text("🎵 Укажи название: `флеш музыка Imagine Dragons`", parse_mode=ParseMode.MARKDOWN)
        return

    if not FFMPEG_PATH or not FFPROBE_PATH:
        await update.message.reply_text(
            "❌ ffmpeg/ffprobe не найдены. Музыка недоступна.\n"
            "Администратор должен установить ffmpeg на сервер."
        )
        return

    msg = await update.message.reply_text(f"🔍 Ищу *{query}*...", parse_mode=ParseMode.MARKDOWN)
    try:
        import yt_dlp
        
        def search_yt():
            opts = {"quiet": True, "no_warnings": True, "extract_flat": "in_playlist"}
            with yt_dlp.YoutubeDL(opts) as ydl:
                return ydl.extract_info(f"ytsearch5:{query}", download=False)

        loop = asyncio.get_event_loop()
        info = await asyncio.wait_for(loop.run_in_executor(None, search_yt), timeout=20)
        
        entries = [e for e in (info.get("entries", []) if info else []) if e]
        if not entries:
            await msg.edit_text(f"❌ По запросу *{query}* ничего не найдено.", parse_mode=ParseMode.MARKDOWN)
            return

        uid = update.effective_user.id
        results = []
        buttons = []
        
        for i, entry in enumerate(entries[:5]):
            title = entry.get("title") or f"Трек {i+1}"
            url = entry.get("webpage_url") or entry.get("url") or ""
            duration = int(entry.get("duration") or 0)
            mins, secs = divmod(duration, 60) if duration > 0 else (0, 0)
            dur_str = f"{mins}:{secs:02d}" if duration > 0 else "??:??"
            results.append({"title": title, "url": url, "duration": duration})
            buttons.append([InlineKeyboardButton(
                f"▶️ {i+1}. {title[:40]} [{dur_str}]",
                callback_data=f"dl_music:{uid}:{i}"
            )])

        pending_music[uid] = results
        await msg.edit_text(
            f"🎵 *Найдено на YouTube*\n🔍 `{query}`\n\nВыбери трек:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(buttons)
        )
    except Exception as e:
        logger.error(f"Music search error: {e}")
        await msg.edit_text("❌ Ошибка поиска.")

async def download_music_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if not q.data.startswith("dl_music:"):
        return
    _, uid_str, idx_str = q.data.split(":")
    uid, idx = int(uid_str), int(idx_str)

    tracks = pending_music.get(uid, [])
    if idx >= len(tracks):
        await q.message.edit_text("❌ Сессия устарела. Ищи снова.")
        return

    track = tracks[idx]

    if not FFMPEG_PATH or not FFPROBE_PATH:
        await q.message.edit_text("❌ ffmpeg/ffprobe не найдены.")
        return

    await q.message.edit_text(f"⬇️ Скачиваю *{track['title'][:50]}*...", parse_mode=ParseMode.MARKDOWN)

    tmpdir = None
    try:
        tmpdir = tempfile.mkdtemp()
        import yt_dlp

        # ВАЖНО: Явно указываем пути к ffmpeg и ffprobe
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": os.path.join(tmpdir, "%(title)s.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
            "ffmpeg_location": FFMPEG_PATH,
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192"
            }],
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            },
            "max_filesize": 48 * 1024 * 1024,
        }

        # КОСТЫЛЬ: Прокидываем пути через переменные окружения
        env = os.environ.copy()
        env["PATH"] = f"{os.path.dirname(FFMPEG_PATH)}:{env.get('PATH', '')}"
        
        def dl():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([track["url"]])

        # Запускаем с правильным окружением
        loop = asyncio.get_event_loop()
        await asyncio.wait_for(
            loop.run_in_executor(None, dl),
            timeout=120
        )

        # Ищем mp3
        files = list(Path(tmpdir).glob("*.mp3"))
        if not files:
            files = [f for f in Path(tmpdir).iterdir() if f.suffix.lower() in (".mp3", ".m4a", ".opus", ".ogg", ".webm")]

        if not files:
            raise FileNotFoundError("Файл не найден после скачивания")

        file_path = files[0]
        file_size = file_path.stat().st_size
        
        if file_size > 50 * 1024 * 1024:
            await q.message.edit_text("⚠️ Файл > 50 МБ.")
            return
        if file_size == 0:
            await q.message.edit_text("❌ Файл пустой.")
            return

        await q.message.edit_text("📤 Отправляю...")
        async with aiofiles.open(file_path, "rb") as f:
            data = await f.read()

        await q.message.reply_audio(
            audio=data,
            title=track["title"],
            duration=track.get("duration", 0)
        )
        await q.message.delete()

    except asyncio.TimeoutError:
        await q.message.edit_text("❌ Скачивание слишком долгое.")
    except Exception as e:
        logger.error(f"Music DL error: {e}")
        await q.message.edit_text(f"❌ Ошибка: {str(e)[:80]}")
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)
        gc.collect()

# ═══════════════ АНОНИМНЫЙ ЧАТ ═══════════════
async def exit_anon_chat(user_id, context, silent=False):
    if user_id in anon_chat_pairs:
        partner_id = anon_chat_pairs[user_id]
        del anon_chat_pairs[user_id]
        if partner_id in anon_chat_pairs:
            del anon_chat_pairs[partner_id]
        anon_chat_users.discard(user_id)
        anon_chat_users.discard(partner_id)
        if not silent:
            try:
                await context.bot.send_message(partner_id, "👋 Собеседник покинул чат.", reply_markup=MAIN_KEYBOARD)
            except:
                pass
    if user_id in anon_chat_queue:
        anon_chat_queue.remove(user_id)
    anon_waiting_users.discard(user_id)
    anon_chat_users.discard(user_id)
    try:
        await context.bot.send_message(user_id, "👋 Ты вышел из поиска/чата.", reply_markup=MAIN_KEYBOARD)
    except:
        pass

async def find_new_partner(user_id, context):
    await exit_anon_chat(user_id, context, silent=True)
    available = [u for u in anon_chat_queue if u != user_id and u not in anon_chat_pairs]
    if available:
        partner_id = available[0]
        anon_chat_queue.remove(partner_id)
        anon_chat_pairs[user_id] = partner_id
        anon_chat_pairs[partner_id] = user_id
        anon_chat_users.add(user_id)
        anon_chat_users.add(partner_id)
        anon_waiting_users.discard(partner_id)
        await context.bot.send_message(user_id, "💬 *Собеседник найден!* Общайтесь!", parse_mode=ParseMode.MARKDOWN, reply_markup=ANON_CHAT_KEYBOARD)
        await context.bot.send_message(partner_id, "💬 *Собеседник найден!* Общайтесь!", parse_mode=ParseMode.MARKDOWN, reply_markup=ANON_CHAT_KEYBOARD)
    else:
        anon_chat_queue.append(user_id)
        anon_waiting_users.add(user_id)
        await context.bot.send_message(user_id, f"⏳ *Ищу собеседника...*\nВ очереди: {len(anon_chat_queue)} чел.", parse_mode=ParseMode.MARKDOWN, reply_markup=WAITING_KEYBOARD)

async def flash_anon_chat_start(update, context):
    if not is_private(update):
        await update.message.reply_text("💬 Только в личке.")
        return
    uid = update.effective_user.id
    if uid in anon_chat_pairs:
        await update.message.reply_text("💬 Ты уже в чате!", reply_markup=ANON_CHAT_KEYBOARD)
        return
    if uid in anon_waiting_users:
        await update.message.reply_text("⏳ Ты уже в поиске!", reply_markup=WAITING_KEYBOARD)
        return
    await find_new_partner(uid, context)

async def flash_anon_chat_stop(update, context):
    await exit_anon_chat(update.effective_user.id, context)

async def anon_chat_next(update, context):
    uid = update.effective_user.id
    if uid in anon_chat_pairs:
        partner_id = anon_chat_pairs[uid]
        try:
            await context.bot.send_message(partner_id, "👋 Собеседник перешёл к следующему.", reply_markup=MAIN_KEYBOARD)
        except:
            pass
        del anon_chat_pairs[uid]
        if partner_id in anon_chat_pairs:
            del anon_chat_pairs[partner_id]
        anon_chat_users.discard(uid)
        anon_chat_users.discard(partner_id)
    await find_new_partner(uid, context)

async def anon_chat_message(update, context):
    if not update.message or not update.message.text:
        return
    uid = update.effective_user.id
    text = update.message.text.strip()
    if text == "🚪 Выйти из поиска":
        await flash_anon_chat_stop(update, context)
        return
    elif text == "➡️ Следующий":
        await anon_chat_next(update, context)
        return
    elif text == "🚪 Выйти":
        await flash_anon_chat_stop(update, context)
        return
    if uid in anon_chat_pairs:
        partner_id = anon_chat_pairs[uid]
        try:
            await context.bot.send_message(partner_id, f"💬 {text}", reply_markup=ANON_CHAT_KEYBOARD)
        except:
            await update.message.reply_text("❌ Не удалось отправить.", reply_markup=ANON_CHAT_KEYBOARD)

# Остальные функции (почта, кино, мемы и т.д.)
async def flash_mail(update, context):
    if not is_private(update):
        await update.message.reply_text("📧 Только в личке.")
        return
    msg = await update.message.reply_text("📧 Создаю почту...")
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://api.guerrillamail.com/ajax.php?f=get_email_address") as r:
                d = await r.json()
        await msg.edit_text(
            f"📧 Твоя временная почта:\n\n`{d['email_addr']}`\n\n⏰ Действует ~10 мин",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📥 Проверить входящие", callback_data=f"gm_check:{d['sid_token']}")
            ]])
        )
    except Exception as e:
        logger.error(f"Mail error: {e}")
        await msg.edit_text("❌ Ошибка создания почты.")

async def guerrilla_callback(update, context):
    q = update.callback_query
    await q.answer()
    if q.data.startswith("gm_check:"):
        try:
            token = q.data.split(":", 1)[1]
            async with aiohttp.ClientSession() as s:
                async with s.get(f"https://api.guerrillamail.com/ajax.php?f=get_email_list&offset=0&sid_token={token}") as r:
                    emails = (await r.json()).get("list", [])
            if not emails:
                await q.answer("📭 Пустой ящик.", show_alert=True)
                return
            text = "📥 *Входящие:*\n\n"
            for m in emails[:5]:
                text += f"📨 `{m.get('mail_from', '?')}`\n   {m.get('mail_subject', '(без темы)')}\n\n"
            await q.message.edit_text(text, parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔄 Обновить", callback_data=f"gm_check:{token}")
                ]]))
        except:
            await q.answer("❌ Ошибка.", show_alert=True)

async def flash_idea_start(update, context):
    pending_idea.add(update.effective_user.id)
    await update.message.reply_text("💡 *Жду твою идею!*\nПиши что хочешь улучшить. `отмена` — отменить.", parse_mode=ParseMode.MARKDOWN)

async def flash_idea_receive(update, context):
    uid, text = update.effective_user.id, update.message.text.strip()
    if text.lower() == "отмена":
        pending_idea.discard(uid)
        await update.message.reply_text("❌ Отменено.")
        return
    try:
        with open("ideas.txt", "a", encoding="utf-8") as f:
            f.write(f"\n{'=' * 50}\n💡 {update.effective_user.full_name} | {uid}\n{text}\n")
        if OWNER_ID:
            await context.bot.send_message(OWNER_ID, f"💡 *Новая идея*\nОт: {update.effective_user.full_name}\n\n{text}", parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"Idea save error: {e}")
    pending_idea.discard(uid)
    await update.message.reply_text("✅ *Спасибо за идею!*", parse_mode=ParseMode.MARKDOWN)

async def download_video(update, context, url):
    if not FFMPEG_PATH:
        await update.message.reply_text("❌ ffmpeg не найден.")
        return
    msg = await update.message.reply_text("⬇️ Скачиваю видео...")
    tmpdir = None
    try:
        tmpdir = tempfile.mkdtemp()
        import yt_dlp
        opts = {
            "format": "bestvideo[height<=720]+bestaudio/best",
            "outtmpl": os.path.join(tmpdir, "%(title)s.%(ext)s"),
            "quiet": True,
            "merge_output_format": "mp4",
            "max_filesize": 48 * 1024 * 1024,
            "ffmpeg_location": FFMPEG_PATH,
            "http_headers": {"User-Agent": "Mozilla/5.0"},
        }
        def dl():
            with yt_dlp.YoutubeDL(opts) as y:
                return y.extract_info(url, download=True)
        info = await asyncio.wait_for(asyncio.get_event_loop().run_in_executor(None, dl), timeout=120)
        if info and "entries" in info:
            info = info["entries"][0]
        title = info.get("title", "Файл") if info else "Файл"
        dur = int(info.get("duration") or 0) if info else 0
        await msg.edit_text("📤 Отправляю...")
        files = list(Path(tmpdir).glob("*.mp4"))
        if not files:
            files = [f for f in Path(tmpdir).iterdir() if f.suffix.lower() in (".mp4", ".mkv", ".webm")]
        if not files:
            raise FileNotFoundError("Файл не найден")
        if files[0].stat().st_size > 50 * 1024 * 1024:
            await msg.edit_text("⚠️ Файл > 50 МБ.")
            return
        async with aiofiles.open(files[0], "rb") as f:
            data = await f.read()
        await update.message.reply_video(video=data, caption=f"🎬 {title}", duration=dur, supports_streaming=True)
        await msg.delete()
    except Exception as e:
        logger.error(f"Video DL error: {e}")
        await msg.edit_text("❌ Не удалось скачать.")
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)
        gc.collect()

async def flash_rate(update, context):
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://open.er-api.com/v6/latest/USD") as r:
                rates = (await r.json()).get("rates", {})
        await update.message.reply_text(
            f"💱 *Курс к USD:*\n🇷🇺 RUB: *{rates.get('RUB', '?'):.2f}*\n🇰🇿 KZT: *{rates.get('KZT', '?'):.2f}*",
            parse_mode=ParseMode.MARKDOWN
        )
    except:
        await update.message.reply_text("❌ Ошибка.")

async def flash_meme(update, context):
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://meme-api.com/gimme") as r:
                d = await r.json()
                if d.get("url"):
                    await update.message.reply_photo(photo=d["url"], caption=d.get("title", "😂"))
                    return
    except:
        pass
    await update.message.reply_text("😅 Мемы временно недоступны.")

# Главный обработчик
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    uid = update.effective_user.id
    if uid in anon_chat_pairs or uid in anon_waiting_users:
        await anon_chat_message(update, context)
        return
    raw = update.message.text.strip()
    text = raw.lower().strip()
    if uid in pending_idea:
        await flash_idea_receive(update, context)
        return
    btn_map = {
        "🎲 ролл": flash_roll, "🪙 монетка": flash_coin,
        "⚡ флеш": flash_help, "😂 мем": flash_meme,
        "💬 анонимный чат": flash_anon_chat_start,
    }
    if text in btn_map:
        await btn_map[text](update, context)
        return
    if text == "🌤 погода":
        await update.message.reply_text("🌤 Укажи город: `флеш погода Москва`", parse_mode=ParseMode.MARKDOWN)
        return
    if text == "🎵 музыка":
        await update.message.reply_text("🎵 Укажи название: `флеш музыка Imagine Dragons`", parse_mode=ParseMode.MARKDOWN)
        return
    if text == "📧 почта (5 мин)":
        await flash_mail(update, context)
        return
    if text == "💡 предложить":
        await flash_idea_start(update, context)
        return
    url = extract_url(raw)
    if url:
        if is_supported_url(url):
            await download_video(update, context, url)
            return
    if not text.startswith("флеш"):
        return
    parts = text.split(None, 2)
    if len(parts) == 1:
        await flash_help(update, context)
        return
    cmd = parts[1]
    arg = parts[2].strip() if len(parts) > 2 else ""
    commands = {
        "ролл": lambda: flash_roll(update, context),
        "монетка": lambda: flash_coin(update, context),
        "погода": lambda: flash_weather(update, context, city=arg or None),
        "голос": lambda: flash_voice(update, context),
        "музыка": lambda: flash_music_search(update, context, arg),
        "почта": lambda: flash_mail(update, context),
        "курс": lambda: flash_rate(update, context),
        "крипта": lambda: flash_crypto(update, context),
        "шар": lambda: flash_magic_ball(update, context, question=arg or None),
        "таймер": lambda: flash_timer(update, context, minutes_str=arg or None),
        "мем": lambda: flash_meme(update, context),
        "чат": lambda: flash_anon_chat_start(update, context),
        "предложить": lambda: flash_idea_start(update, context),
    }
    handler = commands.get(cmd)
    if handler:
        await handler()
    else:
        await flash_help(update, context)

def main():
    import requests
    try:
        requests.post(f"https://api.telegram.org/bot{TOKEN}/deleteWebhook", timeout=5)
    except:
        pass
    cleanup_temp()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop_chat", flash_anon_chat_stop))
    app.add_handler(CallbackQueryHandler(download_music_callback, pattern="^dl_music:"))
    app.add_handler(CallbackQueryHandler(guerrilla_callback, pattern="^gm_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    async def error_handler(update, context):
        logger.error(f"Error: {context.error}")
        if "Conflict" in str(context.error):
            await asyncio.sleep(5)
    app.add_error_handler(error_handler)
    webhook_url = os.environ.get("WEBHOOK_URL", "").strip()
    port = int(os.environ.get("PORT", "8443"))
    logger.info("⚡ Flash Bot запущен!")
    logger.info(f"🎬 FFmpeg: {FFMPEG_PATH}")
    logger.info(f"🎬 FFprobe: {FFPROBE_PATH}")
    if webhook_url:
        app.run_webhook(listen="0.0.0.0", port=port, webhook_url=webhook_url, drop_pending_updates=True)
    else:
        app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
