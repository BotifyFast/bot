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
    print("❌ ОШИБКА: BOT_TOKEN не задан в переменных окружения!")
    sys.exit(1)

try:
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-q", "--upgrade",
         "yt-dlp", "python-telegram-bot==21.9", "SpeechRecognition", "pydub"],
        check=True, timeout=90
    )
except Exception as e:
    print(f"⚠️ pip upgrade failed: {e}")

def _ensure_ffmpeg():
    import stat as stat_mod, urllib.request

    for candidate in ["ffmpeg", "/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/app/ffmpeg"]:
        try:
            r = subprocess.run([candidate, "-version"], capture_output=True, timeout=5)
            if r.returncode == 0:
                print(f"ffmpeg OK: {candidate}")
                return
        except Exception:
            pass

    env = {**os.environ, "DEBIAN_FRONTEND": "noninteractive"}
    try:
        subprocess.run(["apt-get", "update", "-qq"], timeout=60, env=env)
        subprocess.run(["apt-get", "install", "-y", "-q", "ffmpeg"], check=True, timeout=180, env=env)
        print("ffmpeg installed via apt")
        return
    except Exception:
        pass

    print("Downloading static ffmpeg binary...")
    url = "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"
    tar_path = "/tmp/ffmpeg_static.tar.xz"
    dest_dir = "/tmp/ffmpeg_bin"
    dest_bin = "/usr/local/bin/ffmpeg"

    try:
        urllib.request.urlretrieve(url, tar_path)
        os.makedirs(dest_dir, exist_ok=True)
        subprocess.run(["tar", "-xf", tar_path, "-C", dest_dir, "--strip-components=1"],
                       check=True, timeout=120)
        ffmpeg_src = os.path.join(dest_dir, "ffmpeg")
        if os.path.exists(ffmpeg_src):
            shutil.copy2(ffmpeg_src, dest_bin)
            st = os.stat(dest_bin)
            os.chmod(dest_bin, st.st_mode | stat_mod.S_IEXEC | stat_mod.S_IXGRP | stat_mod.S_IXOTH)
            print(f"Static ffmpeg installed: {dest_bin}")
            return
    except Exception as e:
        print(f"johnvansickle download failed: {e}")

    try:
        url2 = "https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz"
        urllib.request.urlretrieve(url2, tar_path)
        os.makedirs(dest_dir, exist_ok=True)
        subprocess.run(["tar", "-xf", tar_path, "-C", dest_dir, "--strip-components=1"],
                       check=True, timeout=120)
        for root, dirs, files in os.walk(dest_dir):
            if "ffmpeg" in files:
                src = os.path.join(root, "ffmpeg")
                shutil.copy2(src, dest_bin)
                st = os.stat(dest_bin)
                os.chmod(dest_bin, st.st_mode | stat_mod.S_IEXEC | stat_mod.S_IXGRP | stat_mod.S_IXOTH)
                print(f"yt-dlp ffmpeg installed: {dest_bin}")
                return
    except Exception as e:
        print(f"yt-dlp ffmpeg download failed: {e}")

    print("WARNING: ffmpeg could not be installed. Music/voice features won't work.")

_ensure_ffmpeg()

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

def get_ffmpeg_path():
    paths = [
        "ffmpeg",
        "/usr/bin/ffmpeg",
        "/usr/local/bin/ffmpeg",
        "/nix/var/nix/profiles/default/bin/ffmpeg",
    ]
    for p in paths:
        try:
            result = subprocess.run([p, "-version"], capture_output=True, timeout=5)
            if result.returncode == 0:
                return p
        except:
            pass
    return None

FFMPEG_PATH = get_ffmpeg_path()
logger.info(f"ffmpeg path: {FFMPEG_PATH}")

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

# ═══════════════ ПОГОДА ═══════════════
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
            lat, lon = c["coord"]["lat"], c["coord"]["lon"]
            tzo = c["timezone"]
            async with s.get(
                "https://api.openweathermap.org/data/2.5/forecast",
                params={"lat": lat, "lon": lon, "appid": WEATHER_API_KEY, "units": "metric", "lang": "ru", "cnt": 4}
            ) as r:
                fc = await r.json() if r.status == 200 else None

        icons = {
            "Clear": "☀️", "Clouds": "☁️", "Rain": "🌧", "Snow": "❄️",
            "Thunderstorm": "⛈", "Drizzle": "🌦", "Mist": "🌫", "Fog": "🌫"
        }
        icon = icons.get(c["weather"][0]["main"], "🌡")
        tz = timezone(timedelta(seconds=tzo))
        lt = datetime.now(timezone.utc).astimezone(tz).strftime("%H:%M")
        sr = datetime.fromtimestamp(c["sys"]["sunrise"], tz=tz).strftime("%H:%M")
        ss = datetime.fromtimestamp(c["sys"]["sunset"], tz=tz).strftime("%H:%M")
        text = (
            f"{icon} *Погода в {c['name']}*\n🕐 {lt}\n\n"
            f"🌡 *{c['main']['temp']:.0f}°C* (ощущается {c['main']['feels_like']:.0f}°C)\n"
            f"💧 {c['main']['humidity']}%\n"
            f"💨 {c['wind']['speed']} м/с\n"
            f"📋 {c['weather'][0]['description'].capitalize()}\n"
            f"🌅 {sr}\n🌇 {ss}"
        )
        if fc and fc.get("list"):
            text += "\n\n📊 *Прогноз:*\n"
            for item in fc["list"][:4]:
                ft = datetime.fromtimestamp(item["dt"], tz=tz).strftime("%H:%M")
                fi = icons.get(item["weather"][0]["main"], "🌡")
                text += f"{fi} {ft} — *{item['main']['temp']:.0f}°C*\n"
        await msg.edit_text(text, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"Weather error: {e}")
        await msg.edit_text("❌ Ошибка.")

# ═══════════════ ГОЛОС → ТЕКСТ (ИСПРАВЛЕНО) ═══════════════
async def flash_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg.reply_to_message:
        await msg.reply_text("❗ Ответь на голосовое сообщение командой `флеш голос`", parse_mode=ParseMode.MARKDOWN)
        return

    target = (
        msg.reply_to_message.voice
        or msg.reply_to_message.video_note
        or msg.reply_to_message.audio
    )
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

        # Проверяем размер файла
        file_size = os.path.getsize(input_path)
        if file_size == 0:
            await status.edit_text("❌ Ошибка: файл пустой.")
            return

        # Пробуем OpenAI Whisper если есть ключ
        if OPENAI_KEY:
            await status.edit_text("🎙 Распознаю через Whisper (OpenAI)...")
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
                            data=form,
                            timeout=aiohttp.ClientTimeout(total=30)
                        ) as r:
                            if r.status == 200:
                                result = await r.json()
                                text = result.get("text", "").strip()
                                if text:
                                    await status.edit_text(f"🎙 *Расшифровка:*\n\n{text}", parse_mode=ParseMode.MARKDOWN)
                                else:
                                    await status.edit_text("🎙 Не удалось распознать речь.")
                                return
                            else:
                                err = await r.text()
                                logger.error(f"Whisper API error {r.status}: {err}")
            except Exception as e:
                logger.error(f"Whisper error: {e}")

        # Запасной вариант: Google Speech Recognition
        if not FFMPEG_PATH:
            await status.edit_text(
                "❌ ffmpeg не найден на сервере.\n\n"
                "Добавь в Railway nixpacks.toml:\n`[phases.setup]\nnixPkgs = [\"ffmpeg\"]`"
            )
            return

        await status.edit_text("🎙 Конвертирую аудио в WAV...")
        wav_path = os.path.join(tmpdir, "output.wav")
        
        # Конвертация через ffmpeg
        proc = await asyncio.create_subprocess_exec(
            FFMPEG_PATH, "-y", "-i", input_path,
            "-ar", "16000", "-ac", "1", "-f", "wav", wav_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        
        if proc.returncode != 0:
            logger.error(f"FFmpeg conversion failed: {stderr.decode()}")
            await status.edit_text("❌ Ошибка конвертации аудио.")
            return

        if not os.path.exists(wav_path) or os.path.getsize(wav_path) == 0:
            await status.edit_text("❌ Ошибка: сконвертированный файл пустой.")
            return

        await status.edit_text("🎙 Распознаю речь через Google...")
        try:
            import speech_recognition as sr
            
            def recognize():
                recognizer = sr.Recognizer()
                with sr.AudioFile(wav_path) as source:
                    audio = recognizer.record(source)
                try:
                    # Пробуем Google с русским языком
                    return recognizer.recognize_google(audio, language="ru-RU")
                except sr.UnknownValueError:
                    return None
                except sr.RequestError as e:
                    logger.error(f"Google SR error: {e}")
                    return None

            loop = asyncio.get_event_loop()
            text = await loop.run_in_executor(None, recognize)

            if text:
                await status.edit_text(f"🎙 *Расшифровка:*\n\n{text}", parse_mode=ParseMode.MARKDOWN)
            else:
                await status.edit_text(
                    "🎙 Не удалось распознать речь.\n"
                    "Попробуй:\n"
                    "• Говорить чётче и громче\n"
                    "• Записать в тихом месте\n"
                    "• Использовать текст вместо голосового"
                )
        except ImportError:
            await status.edit_text(
                "❌ Библиотека `SpeechRecognition` не установлена.\n"
                "Добавь `SpeechRecognition` и `pydub` в requirements.txt\n"
                "Или задай `OPENAI_API_KEY` для Whisper.",
                parse_mode=ParseMode.MARKDOWN
            )

    except Exception as e:
        logger.error(f"Voice error: {e}")
        await status.edit_text(f"❌ Ошибка распознавания: {str(e)[:100]}")
    finally:
        if tmpdir and os.path.exists(tmpdir):
            shutil.rmtree(tmpdir, ignore_errors=True)

# ═══════════════ МУЗЫКА (ИСПРАВЛЕНО ДЛЯ SOUNDCLOUD) ═══════════════
async def flash_music_search(update: Update, context: ContextTypes.DEFAULT_TYPE, query: str):
    if not query:
        await update.message.reply_text("🎵 Укажи название: `флеш музыка Imagine Dragons`", parse_mode=ParseMode.MARKDOWN)
        return

    if not FFMPEG_PATH:
        await update.message.reply_text(
            "❌ ffmpeg не найден. Музыка недоступна.\n\n"
            "Добавь в корень проекта файл `nixpacks.toml`:\n"
            "```\n[phases.setup]\nnixPkgs = [\"ffmpeg\"]\n```",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    msg = await update.message.reply_text(f"🔍 Ищу *{query}*...", parse_mode=ParseMode.MARKDOWN)

    try:
        import yt_dlp

        def search_sc():
            opts = {
                "quiet": True,
                "no_warnings": True,
                "extract_flat": "in_playlist",
                "http_headers": {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.5",
                    "Referer": "https://soundcloud.com/",
                    "Origin": "https://soundcloud.com"
                }
            }
            with yt_dlp.YoutubeDL(opts) as ydl:
                return ydl.extract_info(f"scsearch10:{query}", download=False)

        def search_yt():
            opts = {"quiet": True, "no_warnings": True, "extract_flat": "in_playlist"}
            with yt_dlp.YoutubeDL(opts) as ydl:
                return ydl.extract_info(f"ytsearch5:{query}", download=False)

        loop = asyncio.get_event_loop()

        # Пробуем SoundCloud
        source = "SoundCloud"
        info = None
        try:
            info = await asyncio.wait_for(loop.run_in_executor(None, search_sc), timeout=25)
            if not (info and info.get("entries")):
                raise ValueError("no SoundCloud results")
        except Exception as e:
            logger.warning(f"SoundCloud search failed: {e}")
            source = "YouTube"
            try:
                info = await asyncio.wait_for(loop.run_in_executor(None, search_yt), timeout=20)
            except Exception as e2:
                logger.error(f"YouTube search also failed: {e2}")
                info = None

        entries = [e for e in (info.get("entries", []) if info else []) if e]

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
            mins, secs = divmod(duration, 60) if duration > 0 else (0, 0)
            dur_str = f"{mins}:{secs:02d}" if duration > 0 else "??:??"
            results.append({"title": title, "url": url, "duration": duration, "source": source})
            buttons.append([InlineKeyboardButton(
                f"{src_icon} {i+1}. {title[:40]} [{dur_str}]",
                callback_data=f"dl_music:{uid}:{i}"
            )])

        pending_music[uid] = results
        await msg.edit_text(
            f"🎵 *Найдено на {source}*\n🔍 `{query}`\n\nВыбери трек:",
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
    source = track.get("source", "")

    if not FFMPEG_PATH:
        await q.message.edit_text(
            "❌ ffmpeg не найден. Без него конвертация невозможна.\n"
            "Добавь `nixpacks.toml` с ffmpeg в Railway."
        )
        return

    await q.message.edit_text(
        f"⬇️ Скачиваю с *{source}*:\n*{track['title'][:50]}*",
        parse_mode=ParseMode.MARKDOWN
    )

    tmpdir = None
    try:
        tmpdir = tempfile.mkdtemp()
        import yt_dlp

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
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "*/*",
                "Accept-Language": "en-US,en;q=0.9",
            },
            "max_filesize": 48 * 1024 * 1024,
        }

        # Для SoundCloud добавляем специальные параметры
        if source == "SoundCloud":
            ydl_opts["http_headers"]["Referer"] = "https://soundcloud.com/"
            ydl_opts["http_headers"]["Origin"] = "https://soundcloud.com"
            ydl_opts["extractor_args"] = {
                "soundcloud": {
                    "client_id": "iZIs9mchVcX5lhVRyQGGAYlNPVldzAoX"
                }
            }

        def dl():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([track["url"]])

        await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(None, dl),
            timeout=120
        )

        files = list(Path(tmpdir).glob("*.mp3"))
        if not files:
            files = [
                f for f in Path(tmpdir).iterdir()
                if f.suffix.lower() in (".mp3", ".m4a", ".opus", ".ogg", ".webm")
            ]

        if not files:
            raise FileNotFoundError("Файл не найден после скачивания")

        file_size = files[0].stat().st_size
        if file_size > 50 * 1024 * 1024:
            await q.message.edit_text("⚠️ Файл > 50 МБ, Telegram не примет.")
            return
        if file_size == 0:
            await q.message.edit_text("❌ Ошибка: скачанный файл пустой.")
            return

        await q.message.edit_text("📤 Отправляю...")
        async with aiofiles.open(files[0], "rb") as f:
            data = await f.read()

        await q.message.reply_audio(
            audio=data,
            title=track["title"],
            duration=track.get("duration", 0),
            performer=source
        )
        await q.message.delete()

    except asyncio.TimeoutError:
        await q.message.edit_text("❌ Скачивание слишком долгое. Попробуй другой трек.")
    except Exception as e:
        logger.error(f"Music DL error: {e}")
        await q.message.edit_text(f"❌ Не удалось скачать трек. {str(e)[:50]}")
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)
        gc.collect()

# ═══════════════ ВРЕМЕННАЯ ПОЧТА ═══════════════
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
                async with s.get(
                    f"https://api.guerrillamail.com/ajax.php?f=get_email_list&offset=0&sid_token={token}"
                ) as r:
                    emails = (await r.json()).get("list", [])
            if not emails:
                await q.answer("📭 Пустой ящик.", show_alert=True)
                return
            text = "📥 *Входящие:*\n\n"
            for m in emails[:5]:
                text += f"📨 `{m.get('mail_from', '?')}`\n   {m.get('mail_subject', '(без темы)')}\n\n"
            await q.message.edit_text(
                text, parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔄 Обновить", callback_data=f"gm_check:{token}")
                ]])
            )
        except:
            await q.answer("❌ Ошибка.", show_alert=True)

# ═══════════════ ПРЕДЛОЖЕНИЯ ═══════════════
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

# ═══════════════ СКАЧАТЬ ВИДЕО ═══════════════
async def download_video(update, context, url):
    if not FFMPEG_PATH:
        await update.message.reply_text(
            "❌ ffmpeg не найден. Скачивание видео недоступно.\n"
            "Добавь `nixpacks.toml` в проект."
        )
        return

    msg = await update.message.reply_text("⬇️ Скачиваю видео...")
    tmpdir = None
    try:
        tmpdir = tempfile.mkdtemp()
        import yt_dlp
        is_sc = "soundcloud.com" in url
        opts = {
            "format": "bestaudio/best" if is_sc else "bestvideo[height<=720]+bestaudio/best[ext=m4a]/bestvideo[height<=720]+bestaudio/best/best[height<=720]",
            "outtmpl": os.path.join(tmpdir, "%(title)s.%(ext)s"),
            "quiet": True,
            "merge_output_format": "mp4",
            "max_filesize": 48 * 1024 * 1024,
            "ffmpeg_location": FFMPEG_PATH,
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "*/*",
                "Accept-Language": "en-US,en;q=0.9",
            },
        }
        if is_sc:
            opts["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3"}]
            opts["http_headers"]["Referer"] = "https://soundcloud.com/"
            opts["http_headers"]["Origin"] = "https://soundcloud.com"

        def dl():
            with yt_dlp.YoutubeDL(opts) as y:
                return y.extract_info(url, download=True)

        info = await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(None, dl),
            timeout=120
        )
        if info and "entries" in info:
            info = info["entries"][0]
        title = info.get("title", "Файл") if info else "Файл"
        dur = int(info.get("duration") or 0) if info else 0

        await msg.edit_text("📤 Отправляю...")
        files = list(Path(tmpdir).glob("*.mp3")) if is_sc else list(Path(tmpdir).glob("*.mp4"))
        if not files:
            files = [
                f for f in Path(tmpdir).iterdir()
                if f.suffix.lower() in (".mp4", ".mkv", ".webm", ".mov", ".mp3", ".m4a", ".opus", ".ogg")
            ]
        if not files:
            raise FileNotFoundError("Файл не найден")
        if files[0].stat().st_size > 50 * 1024 * 1024:
            await msg.edit_text("⚠️ Файл > 50 МБ, Telegram не примет.")
            return

        async with aiofiles.open(files[0], "rb") as f:
            data = await f.read()
        if is_sc:
            await update.message.reply_audio(audio=data, title=title, duration=dur)
        else:
            await update.message.reply_video(video=data, caption=f"🎬 {title}", duration=dur, supports_streaming=True)
        await msg.delete()

    except asyncio.TimeoutError:
        await msg.edit_text("❌ Скачивание слишком долгое.")
    except Exception as e:
        logger.error(f"Video DL error: {e}")
        await msg.edit_text("❌ Не удалось скачать. Возможно, видео недоступно или слишком большое.")
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)
        gc.collect()

# ═══════════════ АНОНИМНЫЙ ЧАТ ═══════════════
async def exit_anon_chat(user_id, context):
    if user_id in anon_chat_pairs:
        partner_id = anon_chat_pairs[user_id]
        del anon_chat_pairs[user_id]
        if partner_id in anon_chat_pairs:
            del anon_chat_pairs[partner_id]
        anon_chat_users.discard(user_id)
        anon_chat_users.discard(partner_id)
        try:
            await context.bot.send_message(
                partner_id,
                "👋 Собеседник покинул чат.\nНапиши `флеш чат` чтобы найти нового!",
                reply_markup=MAIN_KEYBOARD
            )
        except:
            pass
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
        await context.bot.send_message(user_id, "💬 *Собеседник найден!* Начинайте общаться.", parse_mode=ParseMode.MARKDOWN, reply_markup=ANON_CHAT_KEYBOARD)
        await context.bot.send_message(pid, "💬 *Собеседник найден!* Начинайте общаться.", parse_mode=ParseMode.MARKDOWN, reply_markup=ANON_CHAT_KEYBOARD)
    else:
        anon_chat_queue.append(user_id)
        anon_chat_users.add(user_id)
        await context.bot.send_message(user_id, "⏳ *Ищу собеседника...*\nПодожди немного.", parse_mode=ParseMode.MARKDOWN, reply_markup=ANON_CHAT_KEYBOARD)

async def flash_anon_chat_start(update, context):
    if not is_private(update):
        await update.message.reply_text("💬 Анонимный чат работает только в личке.")
        return
    uid = update.effective_user.id
    if uid in anon_chat_pairs:
        await update.message.reply_text("💬 Ты уже в чате!", reply_markup=ANON_CHAT_KEYBOARD)
        return
    await find_new_partner(uid, context)

async def flash_anon_chat_stop(update, context):
    uid = update.effective_user.id
    await exit_anon_chat(uid, context)
    await update.message.reply_text("👋 Вышел из анонимного чата.", reply_markup=MAIN_KEYBOARD)

async def anon_chat_next(update, context):
    uid = update.effective_user.id
    if uid in anon_chat_pairs:
        pid = anon_chat_pairs[uid]
        try:
            await context.bot.send_message(pid, "👋 Собеседник перешёл к следующему.", reply_markup=ANON_CHAT_KEYBOARD)
        except:
            pass
        del anon_chat_pairs[uid]
        if pid in anon_chat_pairs:
            del anon_chat_pairs[pid]
        anon_chat_users.discard(uid)
        anon_chat_users.discard(pid)
    await find_new_partner(uid, context)

async def anon_chat_message(update, context):
    if not update.message or not update.message.text:
        return
    uid = update.effective_user.id
    if uid not in anon_chat_pairs:
        return
    text = update.message.text.strip()
    if text == "➡️ Следующий":
        await anon_chat_next(update, context)
        return
    elif text in ("🚪 Выйти", "стоп", "/stop_chat"):
        await flash_anon_chat_stop(update, context)
        return
    pid = anon_chat_pairs[uid]
    try:
        await context.bot.send_message(pid, f"💬 *Аноним:* {text}", parse_mode=ParseMode.MARKDOWN)
    except:
        await update.message.reply_text("❌ Собеседник отключился.", reply_markup=ANON_CHAT_KEYBOARD)
        await exit_anon_chat(uid, context)

# ═══════════════ КУРС ВАЛЮТ ═══════════════
async def flash_rate(update, context):
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://open.er-api.com/v6/latest/USD") as r:
                data = await r.json()
        rates = data.get("rates", {})
        await update.message.reply_text(
            f"💱 *Курс к USD:*\n"
            f"🇷🇺 RUB: *{rates.get('RUB', '?'):.2f}*\n"
            f"🇰🇿 KZT: *{rates.get('KZT', '?'):.2f}*\n"
            f"🇺🇦 UAH: *{rates.get('UAH', '?'):.2f}*\n"
            f"🇪🇺 EUR: *{rates.get('EUR', '?'):.4f}*\n"
            f"🇬🇧 GBP: *{rates.get('GBP', '?'):.4f}*",
            parse_mode=ParseMode.MARKDOWN
        )
    except:
        await update.message.reply_text("❌ Ошибка получения курса.")

# ═══════════════ ПОИСК ФИЛЬМОВ ═══════════════
async def search_movie_tv(update, query, media_type):
    msg = await update.message.reply_text("🔍 Ищу...")
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                f"https://api.themoviedb.org/3/search/{media_type}",
                params={"api_key": TMDB_KEY, "query": query, "language": "ru-RU"}
            ) as r:
                results = (await r.json()).get("results", [])
        if not results:
            await msg.edit_text("❌ Ничего не найдено.")
            return
        btns = []
        for i, item in enumerate(results[:5]):
            title = item.get("title") if media_type == "movie" else item.get("name", "?")
            year = (item.get("release_date") if media_type == "movie" else item.get("first_air_date") or "")[:4]
            btns.append([InlineKeyboardButton(
                f"{i+1}. {title[:35]} ({year}) ⭐{item.get('vote_average', 0):.1f}",
                callback_data=f"movie_info:{media_type}:{item['id']}:{title.replace(':', '：')[:30]}:{year}"
            )])
        await msg.edit_text(
            f"{'🎬 Фильмы' if media_type == 'movie' else '📺 Сериалы'}:",
            reply_markup=InlineKeyboardMarkup(btns)
        )
    except Exception as e:
        logger.error(f"Movie search error: {e}")
        await msg.edit_text("❌ Ошибка.")

async def movie_info_callback(update, context):
    q = update.callback_query
    await q.answer()
    try:
        _, media, tid, tc, yc = q.data.split(":", 4)
    except:
        await q.message.edit_text("❌ Ошибка.")
        return
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                f"https://api.themoviedb.org/3/{media}/{tid}",
                params={"api_key": TMDB_KEY, "language": "ru-RU"}
            ) as r:
                d = await r.json()
        title = d.get("title") if media == "movie" else d.get("name", tc or "?")
        year = (d.get("release_date") if media == "movie" else d.get("first_air_date") or yc or "")[:4]
        rating = d.get("vote_average", 0)
        genres = ", ".join([g["name"] for g in d.get("genres", [])][:3])
        overview = d.get("overview", "Нет описания")
        poster = d.get("poster_path", "")
        if media == "movie":
            rt = d.get("runtime", 0)
            extra = f"\n⏱ *{rt} мин*" if rt else ""
            text = f"🎬 *{title}* ({year})\n\n⭐ *{rating:.1f}/10*\n🎭 {genres}{extra}\n\n📖 {overview[:500]}"
        else:
            s_count = d.get("number_of_seasons", "?")
            e_count = d.get("number_of_episodes", "?")
            er = d.get("episode_run_time", [])
            extra = f"\n📅 *Сезонов: {s_count} | Серий: {e_count}*"
            if er:
                extra += f"\n⏱ *Серия: ~{er[0]} мин*"
            text = f"📺 *{title}* ({year})\n\n⭐ *{rating:.1f}/10*\n🎭 {genres}{extra}\n\n📖 {overview[:500]}"
        if poster:
            await q.message.reply_photo(
                photo=f"https://image.tmdb.org/t/p/w500{poster}",
                caption=text, parse_mode=ParseMode.MARKDOWN
            )
        else:
            await q.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
        await q.message.delete()
    except Exception as e:
        logger.error(f"Movie info error: {e}")
        await q.message.edit_text("❌ Ошибка.")

async def flash_movie(update, context, query=None):
    if not query:
        await update.message.reply_text("❗ `флеш кино Интерстеллар`", parse_mode=ParseMode.MARKDOWN)
        return
    if any(w in query.lower() for w in BAD_WORDS):
        await update.message.reply_text(random.choice(SHAME_RESPONSES))
        return
    await search_movie_tv(update, query, "movie")

async def flash_series(update, context, query=None):
    if not query:
        await update.message.reply_text("❗ `флеш сериал Мистер Робот`", parse_mode=ParseMode.MARKDOWN)
        return
    if any(w in query.lower() for w in BAD_WORDS):
        await update.message.reply_text(random.choice(SHAME_RESPONSES))
        return
    await search_movie_tv(update, query, "tv")

async def flash_short(update, context, url=None):
    if not url:
        await update.message.reply_text("❗ `флеш сократить https://...`", parse_mode=ParseMode.MARKDOWN)
        return
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(f"https://tinyurl.com/api-create.php?url={url}") as r:
                short = await r.text()
        await update.message.reply_text(f"🔗 `{short}`", parse_mode=ParseMode.MARKDOWN)
    except:
        await update.message.reply_text("❌ Ошибка.")

async def flash_translate(update, context, query=None):
    if not query:
        await update.message.reply_text("❗ `флеш перевод hello world`", parse_mode=ParseMode.MARKDOWN)
        return
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                "https://translate.googleapis.com/translate_a/single",
                params={"client": "gtx", "sl": "auto", "tl": "ru", "dt": "t", "q": query}
            ) as r:
                data = await r.json()
        translated = "".join([item[0] for item in data[0] if item[0]])
        await update.message.reply_text(f"🌍 *Перевод:*\n{translated}", parse_mode=ParseMode.MARKDOWN)
    except:
        await update.message.reply_text("❌ Ошибка перевода.")

async def flash_meme(update, context):
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                "https://www.reddit.com/r/memes/random/.json",
                headers={"User-Agent": "Mozilla/5.0"}
            ) as r:
                if r.status == 200:
                    post = (await r.json())[0]["data"]["children"][0]["data"]
                    url = post.get("url_overridden_by_dest") or post.get("url", "")
                    if url and any(url.endswith(ext) for ext in [".jpg", ".png", ".jpeg", ".gif"]):
                        await update.message.reply_photo(photo=url, caption=f"😂 {post.get('title', 'Мем')}")
                        return
    except:
        pass
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://meme-api.com/gimme") as r:
                d = await r.json()
                if d.get("url"):
                    await update.message.reply_photo(photo=d["url"], caption=d.get("title", "😂"))
                    return
    except:
        pass
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://api.imgflip.com/get_memes") as r:
                memes = (await r.json()).get("data", {}).get("memes", [])
                if memes:
                    m = random.choice(memes)
                    await update.message.reply_photo(photo=m["url"], caption=f"😂 {m['name']}")
                    return
    except:
        pass
    await update.message.reply_text("😅 Мемы временно недоступны.")

# ═══════════════ ОБРАБОТЧИК ТЕКСТА ═══════════════
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    uid = update.effective_user.id

    if uid in anon_chat_pairs:
        await anon_chat_message(update, context)
        return

    raw = update.message.text.strip()
    text = raw.lower().strip()

    if uid in pending_idea:
        await flash_idea_receive(update, context)
        return

    btn_map = {
        "🎲 ролл":           flash_roll,
        "🪙 монетка":        flash_coin,
        "⚡ флеш":           flash_help,
        "😂 мем":            flash_meme,
        "💬 анонимный чат":  flash_anon_chat_start,
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
        if is_tg_url(url):
            try:
                m = TG_PATTERN.search(url)
                cid, mid = m.groups()
                cids = (
                    [f"@{cid}"] if not cid.lstrip('-').isdigit()
                    else [int(cid)] + ([int(f"-100{cid}")] if not cid.startswith("-100") else [])
                )
                for c in cids:
                    try:
                        await context.bot.copy_message(
                            chat_id=update.effective_chat.id,
                            from_chat_id=c, message_id=int(mid)
                        )
                        return
                    except:
                        continue
            except:
                pass
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
        "ролл":     lambda: flash_roll(update, context),
        "монетка":  lambda: flash_coin(update, context),
        "погода":   lambda: flash_weather(update, context, city=arg or None),
        "голос":    lambda: flash_voice(update, context),
        "музыка":   lambda: flash_music_search(update, context, arg),
        "почта":    lambda: flash_mail(update, context),
        "курс":     lambda: flash_rate(update, context),
        "крипта":   lambda: flash_crypto(update, context),
        "шар":      lambda: flash_magic_ball(update, context, question=arg or None),
        "таймер":   lambda: flash_timer(update, context, minutes_str=arg or None),
        "кино":     lambda: flash_movie(update, context, query=arg or None),
        "сериал":   lambda: flash_series(update, context, query=arg or None),
        "сократить":lambda: flash_short(update, context, url=arg or None),
        "перевод":  lambda: flash_translate(update, context, query=arg or None),
        "мем":      lambda: flash_meme(update, context),
        "чат":      lambda: flash_anon_chat_start(update, context),
        "предложить": lambda: flash_idea_start(update, context),
        "идея":     lambda: flash_idea_start(update, context),
    }

    if cmd == "тг":
        if arg:
            try:
                m = TG_PATTERN.search(arg)
                if m:
                    cid, mid = m.groups()
                    cids = (
                        [f"@{cid}"] if not cid.lstrip('-').isdigit()
                        else [int(cid)] + ([int(f"-100{cid}")] if not cid.startswith("-100") else [])
                    )
                    for c in cids:
                        try:
                            await context.bot.copy_message(
                                chat_id=update.effective_chat.id,
                                from_chat_id=c, message_id=int(mid)
                            )
                            return
                        except:
                            continue
            except:
                pass
            await update.message.reply_text("❌ Не удалось скачать из Telegram.")
        else:
            await update.message.reply_text("❗ `флеш тг [ссылка]`", parse_mode=ParseMode.MARKDOWN)
        return

    handler = commands.get(cmd)
    if handler:
        await handler()
    else:
        await flash_help(update, context)

# ═══════════════ MAIN ═══════════════
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
    app.add_handler(CallbackQueryHandler(movie_info_callback, pattern="^movie_info:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    async def error_handler(update, context):
        logger.error(f"Error: {context.error}")
        if "Conflict" in str(context.error):
            await asyncio.sleep(5)

    app.add_error_handler(error_handler)

    webhook_url = os.environ.get("WEBHOOK_URL", "").strip()
    port = int(os.environ.get("PORT", "8443"))

    logger.info("⚡ Flash Bot запущен!")

    if webhook_url:
        app.run_webhook(
            listen="0.0.0.0",
            port=port,
            webhook_url=webhook_url,
            drop_pending_updates=True
        )
    else:
        app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
