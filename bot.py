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

# Ждём перед запуском
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
                    print(f"Убит старый процесс: {proc.info['pid']}")
        except: pass
except ImportError: pass

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

TOKEN = "8638601182:AAHAOf2wvybOOyhyt_PNijYkKkljJwGnN-g"
WEATHER_API_KEY = "c2b2631749aead62cfdc86b394e6399f"
OWNER_ID = 1202730193
TMDB_KEY = "8265bd1679663a7ea12ac168da84d2e8"

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

SUPPORTED_DOMAINS = ["youtube.com","youtu.be","tiktok.com","vm.tiktok.com","instagram.com","instagr.am","soundcloud.com","twitter.com","x.com","vk.com","facebook.com","fb.watch"]
TG_PATTERN = re.compile(r'https?://t\.me/(?:c/)?([^/]+)/(\d+)')
URL_REGEX = re.compile(r'https?://[^\s<>"{}|\\^`\[\]]+')

pending_music = {}
pending_idea = set()
active_timers = {}

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
    """Очищает все временные папки бота"""
    try:
        tmp = tempfile.gettempdir()
        for item in os.listdir(tmp):
            path = os.path.join(tmp, item)
            if os.path.isdir(path) and item.startswith('tmp'):
                try:
                    shutil.rmtree(path, ignore_errors=True)
                except: pass
    except: pass
    gc.collect()

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [[KeyboardButton("🎲 Ролл"), KeyboardButton("🪙 Монетка")],
     [KeyboardButton("🌤 Погода"), KeyboardButton("🎵 Музыка")],
     [KeyboardButton("📧 Почта (5 мин)"), KeyboardButton("⚡ Флеш")],
     [KeyboardButton("💡 Предложить")]],
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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "⚡ *Привет! Я Flash Bot!*\n\n"
        "🎲 `флеш ролл` — бросок 1-100\n"
        "🌤 `флеш погода [город]` — погода\n"
        "🪙 `флеш монетка` — орёл или решка\n"
        "🎙 `флеш голос` — голосовое → текст\n"
        "🎵 `флеш музыка [название]` — выбрать из 5 треков\n"
        "📧 `флеш почта` — временная почта 10 мин\n"
        "💱 `флеш курс` — курс валют\n"
        "🪙 `флеш крипта` — курс BTC и ETH\n"
        "🎱 `флеш шар [вопрос]` — шар судьбы\n"
        "⏰ `флеш таймер [минуты]` — таймер\n"
        "🎬 `флеш кино [название]` — поиск фильма\n"
        "📺 `флеш сериал [название]` — поиск сериала\n"
        "🔗 `флеш сократить [ссылка]` — короткая ссылка\n"
        "📝 `флеш перевод [текст]` — перевод на русский\n"
        "😂 `флеш мем` — случайный мем\n"
        "📥 `флеш тг [ссылка]` — скачать из ТГ канала\n"
        "💡 `флеш предложить` — идея для бота\n"
        "⚡ `флеш` — список команд\n\n"
        "🔗 *Скинь ссылку* из YouTube/TikTok/Instagram — скачаю!"
    )
    kb = MAIN_KEYBOARD if is_private(update) else None
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)

async def flash_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

async def flash_roll(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    roll = random.randint(1, 100)
    name = user.first_name or "Игрок"
    if roll == 100: c = "🏆 МАКСИМУМ!"
    elif roll >= 80: c = "🔥 Отлично!"
    elif roll >= 50: c = "😎 Неплохо!"
    elif roll >= 20: c = "😅 Так себе..."
    else: c = "💀 Провал!"
    await update.message.reply_text(f"🎲 *{name}* бросает кости...\n\nВыпало: *{roll}/100*\n{c}", parse_mode=ParseMode.MARKDOWN)

async def flash_coin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Подбрасываю...\n\n{random.choice(['🦅 Орёл!', '🪙 Решка!'])}")

async def flash_magic_ball(update: Update, context: ContextTypes.DEFAULT_TYPE, question: str = None):
    if not question:
        await update.message.reply_text("🎱 Задай вопрос: `флеш шар я выиграю?`", parse_mode=ParseMode.MARKDOWN)
        return
    await update.message.reply_text(f"🎱 *Вопрос:* {question}\n\n🔮 *Ответ:* {random.choice(MAGIC_BALL_ANSWERS)}", parse_mode=ParseMode.MARKDOWN)

async def flash_timer(update: Update, context: ContextTypes.DEFAULT_TYPE, minutes_str: str = None):
    if not minutes_str:
        await update.message.reply_text("⏰ Укажи время: `флеш таймер 5`", parse_mode=ParseMode.MARKDOWN)
        return
    try:
        minutes = int(minutes_str)
        if minutes <= 0 or minutes > 120:
            await update.message.reply_text("⏰ От 1 до 120 минут.")
            return
    except:
        await update.message.reply_text("⏰ Укажи число.")
        return
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    finish_time = datetime.now() + timedelta(minutes=minutes)
    active_timers[user_id] = finish_time
    await update.message.reply_text(f"⏰ *Таймер на {minutes} мин.*\nЗакончится в {finish_time.strftime('%H:%M:%S')}", parse_mode=ParseMode.MARKDOWN)
    await asyncio.sleep(minutes * 60)
    if user_id in active_timers:
        try:
            await context.bot.send_message(chat_id, f"⏰ *Время вышло!*\nПрошло {minutes} мин.", parse_mode=ParseMode.MARKDOWN)
        except: pass
        del active_timers[user_id]

async def flash_crypto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum&vs_currencies=usd&include_24hr_change=true") as r:
                data = await r.json()
        btc, eth = data.get("bitcoin", {}), data.get("ethereum", {})
        btc_change, eth_change = btc.get("usd_24h_change", 0), eth.get("usd_24h_change", 0)
        await update.message.reply_text(
            f"🪙 *Криптовалюта (USD):*\n\n"
            f"₿ Bitcoin: *${btc.get('usd', '?'):,.0f}*\n  {'📈' if btc_change > 0 else '📉'} 24ч: {btc_change:+.2f}%\n\n"
            f"♦️ Ethereum: *${eth.get('usd', '?'):,.0f}*\n  {'📈' if eth_change > 0 else '📉'} 24ч: {eth_change:+.2f}%",
            parse_mode=ParseMode.MARKDOWN
        )
    except: await update.message.reply_text("❌ Ошибка.")

async def flash_weather(update: Update, context: ContextTypes.DEFAULT_TYPE, city=None):
    if not city:
        await update.message.reply_text("❗ Укажи город: `флеш погода Алматы`", parse_mode=ParseMode.MARKDOWN)
        return
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(f"https://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_API_KEY}&units=metric&lang=ru") as r:
                if r.status != 200:
                    await update.message.reply_text(f"❌ Город *{city}* не найден.", parse_mode=ParseMode.MARKDOWN)
                    return
                d = await r.json()
        icons = {"Clear":"☀️","Clouds":"☁️","Rain":"🌧","Snow":"❄️","Thunderstorm":"⛈","Drizzle":"🌦","Mist":"🌫","Fog":"🌫"}
        icon = icons.get(d["weather"][0]["main"], "🌡")
        await update.message.reply_text(
            f"{icon} *Погода в {d['name']}*\n\n"
            f"🌡 *{d['main']['temp']:.0f}°C* (ощущается {d['main']['feels_like']:.0f}°C)\n"
            f"💧 Влажность: {d['main']['humidity']}%\n💨 Ветер: {d['wind']['speed']} м/с\n"
            f"📋 {d['weather'][0]['description'].capitalize()}",
            parse_mode=ParseMode.MARKDOWN
        )
    except: await update.message.reply_text("❌ Ошибка погоды.")

async def flash_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg.reply_to_message:
        await msg.reply_text("❗ Ответь на голосовое `флеш голос`", parse_mode=ParseMode.MARKDOWN)
        return
    target = msg.reply_to_message.voice or msg.reply_to_message.video_note
    if not target:
        await msg.reply_text("❗ Ответь на голосовое или кружок.")
        return
    status = await msg.reply_text("🎙 Распознаю...")
    tmpdir = None
    try:
        tmpdir = tempfile.mkdtemp()
        file = await context.bot.get_file(target.file_id)
        ogg = os.path.join(tmpdir, "v.ogg")
        wav = os.path.join(tmpdir, "v.wav")
        await file.download_to_drive(ogg)
        global _FFMPEG
        p = await asyncio.create_subprocess_exec(
            _FFMPEG, "-y", "-i", ogg, "-ar", "16000", "-ac", "1", "-f", "wav", wav,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
        )
        await p.wait()
        import requests as _requests
        loop = asyncio.get_event_loop()
        def do_recognize():
            with open(wav, "rb") as f:
                wav_data = f.read()
            resp = _requests.post(
                "https://www.google.com/speech-api/v2/recognize?output=json&lang=ru-RU&key=AIzaSyBOti4mM-6x9WDnZIjIeyEU21OpBXqWBgw",
                data=wav_data, headers={"Content-Type": "audio/l16; rate=16000"}
            )
            result = ""
            for line in resp.text.strip().split("\n"):
                if not line.strip(): continue
                try:
                    d = json.loads(line)
                    for r in d.get("result", []):
                        for alt in r.get("alternative", []):
                            result += alt.get("transcript", "") + " "
                except: continue
            return result.strip()
        text = await loop.run_in_executor(None, do_recognize)
        if text: await status.edit_text(f"🎙 *Расшифровка:*\n\n{text}", parse_mode=ParseMode.MARKDOWN)
        else: await status.edit_text("🎙 Речь не распознана.")
    except: await status.edit_text("❌ Ошибка.")
    finally:
        if tmpdir: shutil.rmtree(tmpdir, ignore_errors=True)

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
        for f in _glob.glob(f"{path}/**/ffmpeg", recursive=True): return f
    return "ffmpeg"
_FFMPEG = _find_ffmpeg()
logger.info(f"FFMPEG: {_FFMPEG}")

SC_OPTS_BASE = {
    "quiet": True, "ffmpeg_location": _FFMPEG, "no_warnings": True,
    "http_headers": {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36", "Referer": "https://soundcloud.com/"},
    "extractor_args": {"soundcloud": {"client_id": [""]}},
}

async def flash_music_search(update: Update, context: ContextTypes.DEFAULT_TYPE, query: str):
    msg = await update.message.reply_text(f"🔍 Ищу *{query}*...", parse_mode=ParseMode.MARKDOWN)
    try:
        import yt_dlp
        def do_search():
            opts = {**SC_OPTS_BASE, "extract_flat": "in_playlist"}
            with yt_dlp.YoutubeDL(opts) as ydl:
                try:
                    info = ydl.extract_info(f"scsearch5:{query}", download=False)
                    if info and info.get("entries"): return info, "sc"
                except: pass
                return ydl.extract_info(f"ytsearch5:{query}", download=False), "yt"
        loop = asyncio.get_event_loop()
        info, source = await loop.run_in_executor(None, do_search)
        entries = info.get("entries", []) if info else []
        entries = [e for e in entries if e]
        if not entries:
            await msg.edit_text("❌ Ничего не найдено.")
            return
        uid = update.effective_user.id
        results, buttons = [], []
        src_icon = "🔊" if source == "sc" else "▶️"
        for i, e in enumerate(entries[:5]):
            title = e.get("title") or f"Трек {i+1}"
            url = e.get("webpage_url") or e.get("url") or ""
            dur = int(e.get("duration") or 0)
            mins, secs = divmod(dur, 60)
            results.append({"title": title, "url": url, "duration": dur})
            buttons.append([InlineKeyboardButton(f"{src_icon} {i+1}. {title[:38]} ({mins}:{secs:02d})", callback_data=f"dl_music:{uid}:{i}")])
        pending_music[uid] = results
        await msg.edit_text(f"🎵 Найдено на *{'SoundCloud' if source == 'sc' else 'YouTube'}*:\n\nВыбери трек:", parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(buttons))
    except Exception as e:
        logger.error(f"Music search: {e}")
        await msg.edit_text("❌ Ошибка поиска.")

async def download_music_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if not data.startswith("dl_music:"): return
    parts = data.split(":")
    uid, idx = int(parts[1]), int(parts[2])
    tracks = pending_music.get(uid)
    if not tracks or idx >= len(tracks):
        await query.message.edit_text("❌ Сессия устарела.")
        return
    track = tracks[idx]
    await query.message.edit_text(f"⬇️ Скачиваю *{track['title']}*...", parse_mode=ParseMode.MARKDOWN)
    tmpdir = None
    try:
        tmpdir = tempfile.mkdtemp()
        import yt_dlp
        ydl_opts = {
            **SC_OPTS_BASE,
            "format": "bestaudio/best",
            "outtmpl": os.path.join(tmpdir, "%(title)s.%(ext)s"),
            "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}],
            "max_filesize": 48 * 1024 * 1024,
        }
        def do_dl():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([track["url"]])
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, do_dl)
        mp3_files = list(Path(tmpdir).glob("*.mp3"))
        if not mp3_files:
            # Попытка найти любой аудиофайл
            for ext in ["*.m4a", "*.webm", "*.opus", "*.ogg"]:
                mp3_files = list(Path(tmpdir).glob(ext))
                if mp3_files: break
        if not mp3_files: raise FileNotFoundError("Аудио не найдено")
        await query.message.edit_text("📤 Отправляю...")
        async with aiofiles.open(mp3_files[0], "rb") as f:
            audio_data = await f.read()
        await query.message.reply_audio(
            audio=audio_data,
            title=track["title"],
            duration=track["duration"],
            caption=f"🎵 {track['title']}"
        )
        await query.message.delete()
    except Exception as e:
        logger.error(f"Music dl: {e}")
        await query.message.edit_text("❌ Не удалось скачать. Попробуй другой трек.")
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)
            del audio_data
        gc.collect()

# ─── ВРЕМЕННАЯ ПОЧТА ─────────────────────────────────────────────────────────
async def flash_mail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_private(update):
        await update.message.reply_text("📧 Только в личке.")
        return
    msg = await update.message.reply_text("📧 Создаю...")
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://api.guerrillamail.com/ajax.php?f=get_email_address") as r:
                data = await r.json()
        await msg.edit_text(
            f"📧 *Почта:* `{data['email_addr']}`\n⏰ 10 мин",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📥 Проверить", callback_data=f"gm_check:{data['sid_token']}")],
                [InlineKeyboardButton("🗑 Закрыть", callback_data="gm_delete")]
            ])
        )
    except: await msg.edit_text("❌ Ошибка.")

async def guerrilla_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data.startswith("gm_check:"):
        sid = data.split(":", 1)[1]
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(f"https://api.guerrillamail.com/ajax.php?f=get_email_list&offset=0&sid_token={sid}") as r:
                    emails = (await r.json()).get("list", [])
            if not emails: await query.answer("📭 Пусто.", show_alert=True); return
            text = "📥 *Входящие:*\n\n"
            for m in emails[:5]:
                text += f"📨 `{m.get('mail_from', '?')}`\n   {m.get('mail_subject', '(без темы)')}\n\n"
            await query.message.edit_text(text, parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Обновить", callback_data=f"gm_check:{sid}")],
                    [InlineKeyboardButton("🗑 Закрыть", callback_data="gm_delete")]
                ]))
        except: await query.answer("❌ Ошибка.", show_alert=True)
    elif data == "gm_delete":
        await query.message.edit_text("🗑 Закрыта.")

# ─── ПРЕДЛОЖЕНИЯ ─────────────────────────────────────────────────────────────
async def flash_idea_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pending_idea.add(update.effective_user.id)
    await update.message.reply_text("💡 *Жду идею!*\nДля отмены — `отмена`.", parse_mode=ParseMode.MARKDOWN)

async def flash_idea_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    if text.lower() == "отмена":
        pending_idea.discard(user_id)
        await update.message.reply_text("❌ Отменено.")
        return
    name = update.effective_user.full_name
    try:
        with open("ideas.txt", "a", encoding="utf-8") as f:
            f.write(f"\n{'='*50}\n💡 {name} | {user_id}\n{text}\n")
        await context.bot.send_message(OWNER_ID, f"💡 *Идея от {name}*\n{text}", parse_mode=ParseMode.MARKDOWN)
    except: pass
    pending_idea.discard(user_id)
    await update.message.reply_text("✅ *Спасибо!*", parse_mode=ParseMode.MARKDOWN)

# ─── СКАЧАТЬ ВИДЕО С САЙТОВ ─────────────────────────────────────────────────
async def download_video(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str):
    audio_only = is_audio_url(url)
    msg = await update.message.reply_text("⬇️ Скачиваю...")
    tmpdir = None
    try:
        tmpdir = tempfile.mkdtemp()
        import yt_dlp
        if audio_only:
            ydl_opts = {
                "format": "bestaudio/best", "outtmpl": os.path.join(tmpdir, "%(title)s.%(ext)s"),
                "quiet": True, "ffmpeg_location": _FFMPEG,
                "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3"}],
                "max_filesize": 48 * 1024 * 1024,
            }
        else:
            ydl_opts = {
                "format": "bestvideo[height<=720]+bestaudio/best[height<=720]/best",
                "outtmpl": os.path.join(tmpdir, "%(title)s.%(ext)s"),
                "quiet": True, "merge_output_format": "mp4", "max_filesize": 48 * 1024 * 1024,
            }
        def do_dl():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl: return ydl.extract_info(url, download=True)
        loop = asyncio.get_event_loop()
        info = await loop.run_in_executor(None, do_dl)
        if info and "entries" in info: info = info["entries"][0]
        title = info.get("title", "Файл") if info else "Файл"
        duration = int(info.get("duration") or 0) if info else 0
        await msg.edit_text("📤 Отправляю...")
        if audio_only:
            files = list(Path(tmpdir).glob("*.mp3"))
            if not files: files = list(Path(tmpdir).glob("*.*"))
            if not files: raise FileNotFoundError("Файл не найден")
            async with aiofiles.open(files[0], "rb") as f:
                file_data = await f.read()
            await update.message.reply_audio(audio=file_data, title=title, duration=duration)
        else:
            files = list(Path(tmpdir).glob("*.mp4"))
            if not files: files = [f for f in Path(tmpdir).iterdir() if f.suffix in (".mp4",".mkv",".webm",".mov")]
            if not files: raise FileNotFoundError("Видео не найдено")
            if files[0].stat().st_size > 50 * 1024 * 1024:
                await msg.edit_text("⚠️ > 50 МБ.")
                return
            async with aiofiles.open(files[0], "rb") as f:
                file_data = await f.read()
            await update.message.reply_video(
                video=file_data, caption=f"🎬 {title}",
                duration=duration, supports_streaming=True
            )
        await msg.delete()
    except Exception as e:
        logger.error(f"Video dl: {e}")
        await msg.edit_text("❌ Ошибка скачивания.")
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)
            if 'file_data' in locals(): del file_data
        gc.collect()

# ─── СКАЧАТЬ ИЗ ТГ ───────────────────────────────────────────────────────────
async def download_tg(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str):
    msg = await update.message.reply_text("📥 Скачиваю из ТГ...")
    tmpdir = None
    try:
        match = TG_PATTERN.search(url)
        if not match:
            await msg.edit_text("❌ Неверная ссылка ТГ.")
            return

        chat_id, message_id = match.groups()
        
        # Для приватных каналов ID начинается с -100
        if not chat_id.startswith("-100"):
            chat_id = f"-100{chat_id}"

        # Получаем сообщение из ТГ
        try:
            # Пробуем переслать сообщение боту
            await context.bot.forward_message(
                chat_id=update.effective_chat.id,
                from_chat_id=int(chat_id),
                message_id=int(message_id)
            )
            await msg.edit_text("✅ Переслал сообщение из канала!")
            return
        except Exception as e:
            logger.error(f"TG forward: {e}")
            
        # Если не получилось — пробуем скопировать
        try:
            await context.bot.copy_message(
                chat_id=update.effective_chat.id,
                from_chat_id=int(chat_id),
                message_id=int(message_id)
            )
            await msg.edit_text("✅ Скопировал из канала!")
            return
        except Exception as e:
            logger.error(f"TG copy: {e}")
            await msg.edit_text("❌ Не удалось получить доступ к каналу.\nДобавь бота в канал как админа или убедись что канал публичный.")
    finally:
        if tmpdir: shutil.rmtree(tmpdir, ignore_errors=True)

# ─── КУРС ВАЛЮТ ──────────────────────────────────────────────────────────────
async def flash_rate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://open.er-api.com/v6/latest/USD") as r:
                data = await r.json()
        rates = data.get("rates", {})
        await update.message.reply_text(
            f"💱 *Курс к USD:*\n\n"
            f"🇷🇺 RUB: *{rates.get('RUB','?'):.2f}*\n"
            f"🇰🇿 KZT: *{rates.get('KZT','?'):.2f}*\n"
            f"🇺🇦 UAH: *{rates.get('UAH','?'):.2f}*\n"
            f"🇪🇺 EUR: *{rates.get('EUR','?'):.4f}*\n"
            f"🇬🇧 GBP: *{rates.get('GBP','?'):.4f}*",
            parse_mode=ParseMode.MARKDOWN
        )
    except: await update.message.reply_text("❌ Ошибка.")

# ─── ПОИСК ФИЛЬМОВ (без ссылок) ──────────────────────────────────────────────
async def search_movie_tv(update, query: str, media_type: str):
    msg = await update.message.reply_text(f"🔍 Ищу *{query}*...", parse_mode=ParseMode.MARKDOWN)
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(f"https://api.themoviedb.org/3/search/{media_type}", params={"api_key": TMDB_KEY, "query": query, "language": "ru-RU"}) as r:
                search = await r.json()
        results = search.get("results", [])
        if not results:
            await msg.edit_text("❌ Ничего не найдено.")
            return
        buttons = []
        for i, item in enumerate(results[:5]):
            title = item.get("title") if media_type == "movie" else item.get("name", "?")
            year = (item.get("release_date") if media_type == "movie" else item.get("first_air_date") or "")[:4]
            rating = item.get("vote_average", 0)
            safe_title = title.replace(":", "：")
            buttons.append([InlineKeyboardButton(f"{i+1}. {title[:35]} ({year}) ⭐{rating:.1f}", callback_data=f"movie_info:{media_type}:{item['id']}:{safe_title}:{year}")])
        type_name = "🎬 Фильмы" if media_type == "movie" else "📺 Сериалы"
        await msg.edit_text(f"{type_name} по запросу *{query}*:\n\nВыбери:", parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(buttons))
    except: await msg.edit_text("❌ Ошибка.")

async def movie_info_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        parts = query.data.split(":", 4)
        media_type, tmdb_id = parts[1], parts[2]
        title_cb, year_cb = parts[3] if len(parts) > 3 else "", parts[4] if len(parts) > 4 else ""
    except:
        await query.message.edit_text("❌ Ошибка.")
        return
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}", params={"api_key": TMDB_KEY, "language": "ru-RU"}) as r:
                detail = await r.json()
        if media_type == "movie":
            title = detail.get("title", title_cb or "?")
            year_val = (detail.get("release_date") or year_cb or "")[:4]
            icon, extra = "🎬", ""
        else:
            title = detail.get("name", title_cb or "?")
            year_val = (detail.get("first_air_date") or year_cb or "")[:4]
            icon = "📺"
            extra = f"\n📅 Сезонов: {detail.get('number_of_seasons','?')} | Серий: {detail.get('number_of_episodes','?')}"
        orig_title = detail.get("original_title") or detail.get("original_name", "")
        overview = detail.get("overview") or "Описание отсутствует"
        rating = detail.get("vote_average", 0)
        genres = ", ".join([g["name"] for g in detail.get("genres", [])[:3]])
        poster_path = detail.get("poster_path", "")
        text = (
            f"{icon} *{title}*" + (f" / {orig_title}" if orig_title and orig_title != title else "") +
            f" ({year_val})\n\n⭐ *{rating:.1f}/10*\n🎭 {genres}" + extra + f"\n\n📖 {overview[:500]}"
        )
        if poster_path:
            await query.message.reply_photo(photo=f"https://image.tmdb.org/t/p/w500{poster_path}", caption=text, parse_mode=ParseMode.MARKDOWN)
        else:
            await query.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
        await query.message.delete()
    except: await query.message.edit_text("❌ Ошибка.")

async def flash_movie(update: Update, context: ContextTypes.DEFAULT_TYPE, query: str = None):
    if not query:
        await update.message.reply_text("❗ `флеш кино Интерстеллар`", parse_mode=ParseMode.MARKDOWN)
        return
    if any(w in query.lower() for w in BAD_WORDS):
        await update.message.reply_text(random.choice(SHAME_RESPONSES))
        return
    await search_movie_tv(update, query, "movie")

async def flash_series(update: Update, context: ContextTypes.DEFAULT_TYPE, query: str = None):
    if not query:
        await update.message.reply_text("❗ `флеш сериал Мистер Робот`", parse_mode=ParseMode.MARKDOWN)
        return
    if any(w in query.lower() for w in BAD_WORDS):
        await update.message.reply_text(random.choice(SHAME_RESPONSES))
        return
    await search_movie_tv(update, query, "tv")

# ─── СОКРАЩЕНИЕ / ПЕРЕВОД / МЕМ ─────────────────────────────────────────────
async def flash_short(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str = None):
    if not url: await update.message.reply_text("❗ `флеш сократить https://...`", parse_mode=ParseMode.MARKDOWN); return
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(f"https://tinyurl.com/api-create.php?url={url}") as r:
                await update.message.reply_text(f"🔗 `{await r.text()}`", parse_mode=ParseMode.MARKDOWN)
    except: await update.message.reply_text("❌ Ошибка.")

async def flash_translate(update: Update, context: ContextTypes.DEFAULT_TYPE, query: str = None):
    if not query: await update.message.reply_text("❗ `флеш перевод hello`", parse_mode=ParseMode.MARKDOWN); return
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://translate.googleapis.com/translate_a/single", params={"client": "gtx", "sl": "auto", "tl": "ru", "dt": "t", "q": query}) as r:
                data = await r.json()
        await update.message.reply_text(f"🌍 *Перевод:*\n{''.join([item[0] for item in data[0] if item[0]])}", parse_mode=ParseMode.MARKDOWN)
    except: await update.message.reply_text("❌ Ошибка.")

async def flash_meme(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://meme-api.com/gimme/rus") as r:
                data = await r.json()
                if data.get("url"):
                    await update.message.reply_photo(photo=data["url"], caption=data.get("title", "😂"))
                    return
    except: pass
    await update.message.reply_text("😅 Недоступны.")

# ─── ОБРАБОТЧИК ТЕКСТА ───────────────────────────────────────────────────────
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    user_id = update.effective_user.id
    raw, text = update.message.text.strip(), update.message.text.lower().strip()

    if user_id in pending_idea:
        await flash_idea_receive(update, context); return

    if text == "🎲 ролл": await flash_roll(update, context); return
    elif text == "🪙 монетка": await flash_coin(update, context); return
    elif text == "⚡ флеш": await flash_help(update, context); return
    elif text == "🌤 погода": await update.message.reply_text("🌤 `флеш погода Город`", parse_mode=ParseMode.MARKDOWN); return
    elif text == "🎵 музыка": await update.message.reply_text("🎵 `флеш музыка запрос`", parse_mode=ParseMode.MARKDOWN); return
    elif text == "📧 почта (5 мин)": await flash_mail(update, context); return
    elif text == "💡 предложить": await flash_idea_start(update, context); return

    url = extract_url(raw)
    if url:
        if is_tg_url(url):
            await download_tg(update, context, url); return
        if is_supported_url(url):
            await download_video(update, context, url); return

    if not text.startswith("флеш"): return

    parts = text.split(None, 2)
    if len(parts) == 1: await flash_help(update, context); return
    cmd = parts[1] if len(parts) > 1 else ""
    arg = parts[2].strip() if len(parts) > 2 else ""

    if cmd == "ролл": await flash_roll(update, context)
    elif cmd == "монетка": await flash_coin(update, context)
    elif cmd == "погода": await flash_weather(update, context, city=arg or None)
    elif cmd == "голос": await flash_voice(update, context)
    elif cmd == "музыка":
        if arg: await flash_music_search(update, context, arg)
        else: await update.message.reply_text("❗ `флеш музыка запрос`", parse_mode=ParseMode.MARKDOWN)
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
    elif cmd == "тг":
        if arg: await download_tg(update, context, url=arg)
        else: await update.message.reply_text("❗ `флеш тг https://t.me/...`", parse_mode=ParseMode.MARKDOWN)
    elif cmd in ("предложить", "идея"): await flash_idea_start(update, context)
    else: await flash_help(update, context)

# ─── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    # Принудительно удаляем вебхук
    import requests
    try:
        requests.post(f"https://api.telegram.org/bot{TOKEN}/deleteWebhook", timeout=5)
        logger.info("Webhook deleted before start")
    except: pass
    time.sleep(1)

    # Очищаем старые временные файлы
    cleanup_temp()

    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(download_music_callback, pattern="^dl_music:"))
    app.add_handler(CallbackQueryHandler(guerrilla_callback, pattern="^gm_"))
    app.add_handler(CallbackQueryHandler(movie_info_callback, pattern="^movie_info:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # Обработчик ошибок
    async def error_handler(update, context):
        logger.error(f"Error: {context.error}")
        try:
            # При 409 Conflict — просто ждём
            if "Conflict" in str(context.error):
                await asyncio.sleep(5)
        except: pass

    app.add_error_handler(error_handler)
    logger.info("⚡ Flash Bot запущен!")

    webhook_url = os.environ.get("WEBHOOK_URL")
    port = int(os.environ.get("PORT", 8443))
    if webhook_url:
        app.run_webhook(listen="0.0.0.0", port=port, webhook_url=webhook_url, drop_pending_updates=True)
    else:
        app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
