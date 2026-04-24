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
from pathlib import Path

# Автообновление yt-dlp при каждом запуске
try:
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--upgrade", "yt-dlp"], check=True)
    print("✅ yt-dlp обновлён")
except Exception as e:
    print(f"⚠️ Не удалось обновить yt-dlp: {e}")

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ContextTypes, CallbackQueryHandler
)
from telegram.constants import ChatType, ParseMode

TOKEN = "8638601182:AAHAOf2wvybOOyhyt_PNijYkKkljJwGnN-g"
WEATHER_API_KEY = "c2b2631749aead62cfdc86b394e6399f"
OWNER_ID = 123456789  # ← ЗАМЕНИ НА СВОЙ TELEGRAM ID!

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

SUPPORTED_DOMAINS = ["youtube.com","youtu.be","tiktok.com","vm.tiktok.com","instagram.com","instagr.am","soundcloud.com","twitter.com","x.com","vk.com","facebook.com","fb.watch"]
URL_REGEX = re.compile(r'https?://[^\s<>"{}|\\^`\[\]]+')

pending_music = {}
pending_idea = set()

BAD_WORDS = ["порно", "porn", "секс", "sex", "xxx", "18+", "эротика", "хентай", "hentai"]
SHAME_RESPONSES = [
    "🫣 АЙ-АЙ-АЙ! Иди лучше Машу и Медведя смотри!",
    "😤 ЧТО ЭТО ТАКОЕ?! Марш смотреть Смешариков!",
    "🙈 КАКОЙ СТЫД! Лунтик ждёт тебя, немедленно!",
    "👀 Я ЧТО ВИЖУ?! Иди Фиксиков пересматривай!",
    "😱 АЙ-АЙ-АЙ КАКОЙ(АЯ)! Телепузики обидятся!",
    "🚫 НЕТ-НЕТ-НЕТ! Иди Губку Боба смотри давай!",
    "😠 ТЫ СЕРЬЁЗНО?! Назад к Трём богатырям!",
    "🫵 СТЫДОБА! Дед Мороз всё видит между прочим...",
    "🙊 ОЙ ВСЁ! Иди лучше Простоквашино пересмотри!",
    "😡 КТО ТАК ДЕЛАЕТ?! Ну-ка быстро включил Мультики!",
    "🤦 Я В ШОКЕ! Барбоскины расстроились бы...",
    "👮 СТОП! Дядя Стёпа уже едет разбираться!",
]

def is_private(u): return u.effective_chat.type == ChatType.PRIVATE
def extract_url(t):
    m = URL_REGEX.search(t)
    return m.group(0) if m else None
def is_supported_url(url): return any(d in url.lower() for d in SUPPORTED_DOMAINS)
def is_audio_url(url): return "soundcloud.com" in url.lower()

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [[KeyboardButton("🎲 Ролл"), KeyboardButton("🪙 Монетка")],
     [KeyboardButton("🌤 Погода"), KeyboardButton("🎵 Музыка")],
     [KeyboardButton("📧 Почта (5 мин)"), KeyboardButton("⚡ Флеш")],
     [KeyboardButton("💡 Предложить")]],
    resize_keyboard=True, is_persistent=True
)

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
        "🎬 `флеш кино [название]` — поиск фильма\n"
        "📺 `флеш сериал [название]` — поиск сериала\n"
        "🔗 `флеш сократить [ссылка]` — короткая ссылка\n"
        "📝 `флеш перевод [текст]` — перевод на русский\n"
        "😂 `флеш мем` — случайный мем\n"
        "💡 `флеш предложить` или кнопка — идея для бота\n"
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

async def flash_weather(update: Update, context: ContextTypes.DEFAULT_TYPE, city=None):
    if not city:
        await update.message.reply_text("❗ Укажи город: `флеш погода Алматы`", parse_mode=ParseMode.MARKDOWN)
        return
    url = f"https://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_API_KEY}&units=metric&lang=ru"
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url) as r:
                if r.status != 200:
                    await update.message.reply_text(f"❌ Город *{city}* не найден.", parse_mode=ParseMode.MARKDOWN)
                    return
                d = await r.json()
        icons = {"Clear":"☀️","Clouds":"☁️","Rain":"🌧","Snow":"❄️","Thunderstorm":"⛈","Drizzle":"🌦","Mist":"🌫","Fog":"🌫"}
        icon = icons.get(d["weather"][0]["main"], "🌡")
        await update.message.reply_text(
            f"{icon} *Погода в {d['name']}*\n\n"
            f"🌡 *{d['main']['temp']:.0f}°C* (ощущается {d['main']['feels_like']:.0f}°C)\n"
            f"💧 Влажность: {d['main']['humidity']}%\n"
            f"💨 Ветер: {d['wind']['speed']} м/с\n"
            f"📋 {d['weather'][0]['description'].capitalize()}",
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.error(f"Weather: {e}")
        await update.message.reply_text("❌ Ошибка погоды.")

async def flash_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg.reply_to_message:
        await msg.reply_text("❗ Ответь на голосовое командой `флеш голос`", parse_mode=ParseMode.MARKDOWN)
        return
    target = msg.reply_to_message.voice or msg.reply_to_message.video_note
    if not target:
        await msg.reply_text("❗ Ответь на голосовое или кружок.")
        return
    status = await msg.reply_text("🎙 Распознаю...")
    tmpdir = tempfile.mkdtemp()
    try:
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
                data=wav_data,
                headers={"Content-Type": "audio/l16; rate=16000"}
            )
            result = ""
            for line in resp.text.strip().split("\n"):
                if not line.strip(): continue
                try:
                    d = json.loads(line)
                    for r in d.get("result", []):
                        alts = r.get("alternative", [])
                        if alts:
                            result += alts[0].get("transcript", "") + " "
                except: continue
            return result.strip()
        text = await loop.run_in_executor(None, do_recognize)
        if text:
            await status.edit_text(f"🎙 *Расшифровка:*\n\n{text}", parse_mode=ParseMode.MARKDOWN)
        else:
            await status.edit_text("🎙 Речь не распознана.")
    except Exception as e:
        logger.error(f"Voice: {e}")
        await status.edit_text(f"❌ Ошибка: {str(e)[:150]}")
    finally:
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
print(f"ffmpeg path: {_FFMPEG}")

SC_OPTS_BASE = {
    "quiet": True, "ffmpeg_location": _FFMPEG, "no_warnings": True,
    "http_headers": {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://soundcloud.com/",
    },
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
                info = ydl.extract_info(f"ytsearch5:{query}", download=False)
                return info, "yt"
        loop = asyncio.get_event_loop()
        info, source = await loop.run_in_executor(None, do_search)
        entries = info.get("entries", []) if info else []
        entries = [e for e in entries if e]
        if not entries:
            await msg.edit_text("❌ Ничего не найдено.")
            return
        uid = update.effective_user.id
        results = []
        buttons = []
        src_icon = "🔊" if source == "sc" else "▶️"
        for i, e in enumerate(entries[:5]):
            title = e.get("title") or f"Трек {i+1}"
            url = e.get("webpage_url") or e.get("url") or ""
            dur = int(e.get("duration") or 0)
            mins, secs = divmod(dur, 60)
            results.append({"title": title, "url": url, "duration": dur})
            label = f"{src_icon} {i+1}. {title[:38]} ({mins}:{secs:02d})"
            buttons.append([InlineKeyboardButton(label, callback_data=f"dl_music:{uid}:{i}")])
        pending_music[uid] = results
        src_name = "SoundCloud" if source == "sc" else "YouTube"
        await msg.edit_text(
            f"🎵 Найдено на *{src_name}* по запросу *{query}*:\n\nВыбери трек:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(buttons)
        )
    except Exception as e:
        logger.error(f"Music search: {e}")
        await msg.edit_text("❌ Ошибка поиска. Попробуй позже.")

async def download_music_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("dl_music:"):
        parts = data.split(":")
        uid = int(parts[1])
        idx = int(parts[2])
        tracks = pending_music.get(uid)
        if not tracks or idx >= len(tracks):
            await query.message.edit_text("❌ Сессия устарела. Повтори поиск.")
            return
        track = tracks[idx]
        title = track["title"]
        url = track["url"]
        duration = track["duration"]
        await query.message.edit_text(f"⬇️ Скачиваю *{title}*...", parse_mode=ParseMode.MARKDOWN)
        tmpdir = tempfile.mkdtemp()
        try:
            import yt_dlp
            output_template = os.path.join(tmpdir, "%(title)s.%(ext)s")
            ydl_opts = {
                **SC_OPTS_BASE, "format": "bestaudio/best", "outtmpl": output_template,
                "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}],
            }
            def do_dl():
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([url])
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, do_dl)
            mp3_files = list(Path(tmpdir).glob("*.mp3"))
            if not mp3_files: raise FileNotFoundError("MP3 не найден")
            await query.message.edit_text(f"📤 Отправляю *{title}*...", parse_mode=ParseMode.MARKDOWN)
            async with aiofiles.open(mp3_files[0], "rb") as f:
                audio_data = await f.read()
            await query.message.reply_audio(audio=audio_data, title=title, duration=duration, caption=f"🎵 {title}")
            await query.message.delete()
        except Exception as e:
            logger.error(f"Music dl: {e}")
            await query.message.edit_text("❌ Не удалось скачать трек.")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
        return

    if data.startswith("check_mail:"):
        token = data.split(":", 1)[1]
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get("https://api.mail.tm/messages", headers={"Authorization": f"Bearer {token}"}) as r:
                    result = await r.json()
                    messages = result.get("hydra:member", [])
            if not messages:
                await query.answer("📭 Писем пока нет.", show_alert=True)
                return
            text = "📥 *Входящие:*\n\n"
            for i, m in enumerate(messages[:5], 1):
                from_addr = m.get("from", {}).get("address", "?")
                subject = m.get("subject", "(без темы)")
                text += f"{i}. 📨 `{from_addr}`\n   {subject}\n\n"
            await query.message.edit_text(text, parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Обновить", callback_data=f"check_mail:{token}")],
                    [InlineKeyboardButton("🗑 Удалить", callback_data=f"delete_mail:{token}")]
                ]))
        except Exception as e:
            logger.error(f"Mail check: {e}")
            await query.answer("❌ Ошибка.", show_alert=True)
    elif data.startswith("delete_mail:"):
        await query.message.edit_text("🗑 Почта удалена.")

# ─── ВРЕМЕННАЯ ПОЧТА ─────────────────────────────────────────────────────────
async def flash_mail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_private(update):
        await update.message.reply_text("📧 Временная почта — только в личке.")
        return
    msg = await update.message.reply_text("📧 Создаю адрес...")
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://api.guerrillamail.com/ajax.php?f=get_email_address") as r:
                data = await r.json()
                email = data["email_addr"]
                sid_token = data["sid_token"]
        await msg.edit_text(
            f"📧 *Временная почта готова!*\n\n📮 Адрес: `{email}`\n⏰ Работает 10 минут\n\nНажми кнопку чтобы проверить письма:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📥 Проверить письма", callback_data=f"gm_check:{sid_token}")],
                [InlineKeyboardButton("🗑 Закрыть", callback_data="gm_delete")]
            ])
        )
        async def auto_expire():
            await asyncio.sleep(600)
            try: await msg.edit_text(f"⏰ *Почта истекла*\n\n`{email}`", parse_mode=ParseMode.MARKDOWN)
            except: pass
        asyncio.create_task(auto_expire())
    except Exception as e:
        logger.error(f"Mail: {e}")
        await msg.edit_text("❌ Ошибка создания почты.")

async def guerrilla_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data.startswith("gm_check:"):
        sid = data.split(":", 1)[1]
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(f"https://api.guerrillamail.com/ajax.php?f=get_email_list&offset=0&sid_token={sid}") as r:
                    result = await r.json()
                    emails = result.get("list", [])
            if not emails:
                await query.answer("📭 Писем пока нет.", show_alert=True)
                return
            text = "📥 *Входящие:*\n\n"
            for i, m in enumerate(emails[:5], 1):
                from_addr = m.get("mail_from", "?")
                subject = m.get("mail_subject", "(без темы)")
                text += f"{i}. 📨 `{from_addr}`\n   {subject}\n\n"
            await query.message.edit_text(text, parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Обновить", callback_data=f"gm_check:{sid}")],
                    [InlineKeyboardButton("🗑 Закрыть", callback_data="gm_delete")]
                ]))
        except Exception as e:
            logger.error(f"Guerrilla check: {e}")
            await query.answer("❌ Ошибка.", show_alert=True)
    elif data == "gm_delete":
        await query.message.edit_text("🗑 Почта закрыта.")

# ─── ПРЕДЛОЖЕНИЯ ─────────────────────────────────────────────────────────────
async def flash_idea_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    pending_idea.add(user_id)
    await update.message.reply_text(
        "💡 *Жду твою идею!*\n\nНапиши одним сообщением, что бы ты хотел добавить или изменить в боте.\nДля отмены напиши `отмена`.",
        parse_mode=ParseMode.MARKDOWN
    )

async def flash_idea_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = update.effective_user
    text = update.message.text.strip()
    if text.lower() == "отмена":
        pending_idea.discard(user_id)
        await update.message.reply_text("❌ Отменено.")
        return
    name = user.full_name
    username = f"@{user.username}" if user.username else "нет username"
    idea_text = f"\n{'='*50}\n💡 НОВАЯ ИДЕЯ\nОт: {name} ({username}) | ID: {user_id}\nДата: {update.message.date}\n{'='*50}\n{text}\n"
    try:
        with open("ideas.txt", "a", encoding="utf-8") as f:
            f.write(idea_text)
    except: pass
    try:
        await context.bot.send_message(OWNER_ID, f"💡 *Новая идея!*\n\n👤 {name} (`{user_id}`)\n📝 {text}", parse_mode=ParseMode.MARKDOWN)
    except: pass
    pending_idea.discard(user_id)
    await update.message.reply_text("✅ *Спасибо! Идея отправлена.*", parse_mode=ParseMode.MARKDOWN)

# ─── СКАЧАТЬ ВИДЕО ───────────────────────────────────────────────────────────
async def download_video(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str):
    audio_only = is_audio_url(url)
    msg = await update.message.reply_text("⬇️ Скачиваю...")
    tmpdir = tempfile.mkdtemp()
    try:
        import yt_dlp
        output_template = os.path.join(tmpdir, "%(title)s.%(ext)s")
        if audio_only:
            ydl_opts = {
                "format": "bestaudio/best", "outtmpl": output_template,
                "quiet": True, "no_warnings": True, "ffmpeg_location": _FFMPEG,
                "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}],
                "max_filesize": 48 * 1024 * 1024,
            }
        else:
            ydl_opts = {
                "format": "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720]/best",
                "outtmpl": output_template, "quiet": True, "no_warnings": True,
                "merge_output_format": "mp4", "max_filesize": 48 * 1024 * 1024,
                "http_headers": {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            }
        def do_dl():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(url, download=True)
        loop = asyncio.get_event_loop()
        info = await loop.run_in_executor(None, do_dl)
        if info and "entries" in info:
            info = info["entries"][0]
        title = info.get("title", "Файл") if info else "Файл"
        duration = int(info.get("duration") or 0) if info else 0
        await msg.edit_text(f"📤 Отправляю *{title}*...", parse_mode=ParseMode.MARKDOWN)
        if audio_only:
            files = list(Path(tmpdir).glob("*.mp3"))
            if not files: raise FileNotFoundError("MP3 не найден")
            async with aiofiles.open(files[0], "rb") as f:
                d = await f.read()
            await update.message.reply_audio(audio=d, title=title, duration=duration, caption=f"🎵 {title}")
        else:
            files = list(Path(tmpdir).glob("*.mp4"))
            if not files:
                files = [f for f in Path(tmpdir).iterdir() if f.suffix.lower() in (".mp4",".mkv",".webm",".mov")]
            if not files: raise FileNotFoundError("Видео не найдено")
            if files[0].stat().st_size > 50 * 1024 * 1024:
                await msg.edit_text("⚠️ Файл больше 50 МБ — Telegram не позволяет.")
                return
            async with aiofiles.open(files[0], "rb") as f:
                d = await f.read()
            await update.message.reply_video(
                video=d, caption=f"🎬 {title}", duration=duration,
                width=info.get("width") if info else None,
                height=info.get("height") if info else None,
                supports_streaming=True
            )
        await msg.delete()
    except Exception as e:
        logger.error(f"Video dl: {e}")
        err = str(e).lower()
        if "too large" in err or "filesize" in err:
            await msg.edit_text("❌ Файл слишком большой (лимит 50 МБ).")
        elif "private" in err or "login" in err:
            await msg.edit_text("❌ Закрытый контент.")
        else:
            await msg.edit_text("❌ Не удалось скачать.")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

# ─── КУРС ВАЛЮТ ──────────────────────────────────────────────────────────────
async def flash_rate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://open.er-api.com/v6/latest/USD") as r:
                data = await r.json()
        rates = data.get("rates", {})
        await update.message.reply_text(
            "💱 *Курс валют (к USD):*\n\n"
            f"🇷🇺 RUB: `{rates.get('RUB', '?'):.2f}` ₽\n"
            f"🇰🇿 KZT: `{rates.get('KZT', '?'):.2f}` ₸\n"
            f"🇺🇦 UAH: `{rates.get('UAH', '?'):.2f}` ₴\n"
            f"🇪🇺 EUR: `{rates.get('EUR', '?'):.4f}` €\n"
            f"🇬🇧 GBP: `{rates.get('GBP', '?'):.4f}` £",
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.error(f"Rate: {e}")
        await update.message.reply_text("❌ Ошибка получения курса.")

# ─── ПОИСК ФИЛЬМОВ / СЕРИАЛОВ (TMDB → парсинг sspoint) ───────────────────────
TMDB_KEY = "8265bd1679663a7ea12ac168da84d2e8"

async def search_sspoint(title: str, year: str, media_type: str) -> str | None:
    """Ищет фильм/сериал на sspoint.ru и возвращает ссылку"""
    try:
        # Очищаем название от спецсимволов для поиска
        clean_title = re.sub(r'[^\w\s]', '', title).strip()
        search_url = f"https://www.sspoisk.ru/search/?q={clean_title}+{year}"

        async with aiohttp.ClientSession() as s:
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            async with s.get(search_url, headers=headers, timeout=10) as r:
                if r.status != 200:
                    return None
                html = await r.text()

        # Ищем ссылки на фильмы/сериалы
        section = "film" if media_type == "movie" else "series"
        pattern = rf'href="(/{section}/\d+/)"'
        matches = re.findall(pattern, html)

        if matches:
            return f"https://www.sspoisk.ru{matches[0]}"

        # Запасной вариант — любые ссылки
        pattern_all = r'href="(/(?:film|series)/\d+/)"'
        matches_all = re.findall(pattern_all, html)
        if matches_all:
            return f"https://www.sspoisk.ru{matches_all[0]}"

        return None
    except Exception as e:
        logger.error(f"sspoint search: {e}")
        return None

async def search_movie_tv(update, query: str, media_type: str):
    """Поиск через TMDB + пытается найти ссылку на sspoint"""
    msg = await update.message.reply_text(f"🔍 Ищу *{query}*...", parse_mode=ParseMode.MARKDOWN)

    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                f"https://api.themoviedb.org/3/search/{media_type}",
                params={"api_key": TMDB_KEY, "query": query, "language": "ru-RU"}
            ) as r:
                search = await r.json()

        results = search.get("results", [])
        if not results:
            await msg.edit_text(f"❌ Ничего не найдено по запросу *{query}*.", parse_mode=ParseMode.MARKDOWN)
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
            label = f"{i+1}. {title[:35]} ({year}) ⭐{rating:.1f}"
            buttons.append([InlineKeyboardButton(label, callback_data=f"movie:{media_type}:{item['id']}:{title}:{year}")])

        type_name = "🎬 Фильмы" if media_type == "movie" else "📺 Сериалы"
        await msg.edit_text(
            f"{type_name} по запросу *{query}*:\n\nВыбери:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(buttons)
        )
    except Exception as e:
        logger.error(f"Search error: {e}")
        await msg.edit_text("❌ Ошибка поиска.")

async def flash_movie(update: Update, context: ContextTypes.DEFAULT_TYPE, query: str = None):
    if not query:
        await update.message.reply_text("❗ Укажи название: `флеш кино Интерстеллар`", parse_mode=ParseMode.MARKDOWN)
        return
    if any(w in query.lower() for w in BAD_WORDS):
        await update.message.reply_text(random.choice(SHAME_RESPONSES))
        return
    await search_movie_tv(update, query, "movie")

async def flash_series(update: Update, context: ContextTypes.DEFAULT_TYPE, query: str = None):
    if not query:
        await update.message.reply_text("❗ Укажи название: `флеш сериал Мистер Робот`", parse_mode=ParseMode.MARKDOWN)
        return
    if any(w in query.lower() for w in BAD_WORDS):
        await update.message.reply_text(random.choice(SHAME_RESPONSES))
        return
    await search_movie_tv(update, query, "tv")

# ─── MOVIE CALLBACK (ДЕТАЛИ + ССЫЛКА SSPOISK) ────────────────────────────────
async def movie_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает детали фильма/сериала + ищет ссылку на sspoint"""
    query = update.callback_query
    await query.answer()
    parts = query.data.split(":", 3)
    media_type, tmdb_id, title_encoded, year = parts[1], parts[2], parts[3], parts[4] if len(parts) > 4 else ""

    # Декодируем название (могло сломаться из-за двоеточий)
    title_from_callback = title_encoded

    try:
        async with aiohttp.ClientSession() as s:
            # Детали из TMDB
            async with s.get(
                f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}",
                params={"api_key": TMDB_KEY, "language": "ru-RU"}
            ) as r:
                detail = await r.json()

        if media_type == "movie":
            title = detail.get("title", title_from_callback or "?")
            year_val = (detail.get("release_date") or year or "")[:4]
            icon = "🎬"
            extra = ""
        else:
            title = detail.get("name", title_from_callback or "?")
            year_val = (detail.get("first_air_date") or year or "")[:4]
            icon = "📺"
            seasons = detail.get("number_of_seasons", "?")
            episodes = detail.get("number_of_episodes", "?")
            extra = f"\n📅 Сезонов: {seasons} | Серий: {episodes}"

        orig_title = detail.get("original_title") or detail.get("original_name", "")
        overview = detail.get("overview") or "Описание отсутствует"
        rating = detail.get("vote_average", 0)
        genres = ", ".join([g["name"] for g in detail.get("genres", [])[:3]])
        poster_path = detail.get("poster_path", "")
        poster_url = f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else ""

        # Ищем ссылку на sspoint
        await query.message.edit_text(f"🔗 Ищу ссылку на sspoint...")
        ss_url = await search_sspoint(title, year_val, media_type)

        if ss_url:
            watch_text = f"\n\n🎥 *Смотреть бесплатно:*\n[{ss_url}]({ss_url})"
        else:
            # Запасной вариант — пробуем заменить kinopoisk → sspoint
            # Может сработать если ID совпадают
            fake_kp_url = f"https://www.kinopoisk.ru/{'film' if media_type == 'movie' else 'series'}/{tmdb_id}/"
            ss_url_fallback = fake_kp_url.replace("kinopoisk", "sspoisk")
            watch_text = f"\n\n🎥 *Смотреть (пробная ссылка):*\n[{ss_url_fallback}]({ss_url_fallback})"

        text = (
            f"{icon} *{title}*"
            + (f" / {orig_title}" if orig_title and orig_title != title else "")
            + f" ({year_val})\n\n"
            f"⭐ Рейтинг: *{rating:.1f}/10*\n"
            f"🎭 Жанр: {genres}"
            + extra
            + f"\n\n📖 {overview[:500]}"
            + watch_text
        )

        if poster_url:
            await query.message.reply_photo(
                photo=poster_url,
                caption=text,
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await query.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
        await query.message.delete()

    except Exception as e:
        logger.error(f"Movie callback: {e}")
        await query.message.edit_text("❌ Ошибка загрузки деталей.")

# ─── СОКРАЩЕНИЕ ССЫЛОК ───────────────────────────────────────────────────────
async def flash_short(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str = None):
    if not url:
        await update.message.reply_text("❗ Укажи ссылку: `флеш сократить https://example.com`", parse_mode=ParseMode.MARKDOWN)
        return
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(f"https://tinyurl.com/api-create.php?url={url}") as r:
                short = await r.text()
        if short.startswith("http"):
            await update.message.reply_text(f"🔗 *Короткая ссылка:*\n\n`{short}`", parse_mode=ParseMode.MARKDOWN)
        else:
            raise Exception("bad response")
    except Exception as e:
        logger.error(f"Short: {e}")
        await update.message.reply_text("❌ Ошибка сокращения ссылки.")

# ─── ПЕРЕВОД ─────────────────────────────────────────────────────────────────
async def flash_translate(update: Update, context: ContextTypes.DEFAULT_TYPE, query: str = None):
    if not query:
        await update.message.reply_text("❗ Укажи текст: `флеш перевод hello world`", parse_mode=ParseMode.MARKDOWN)
        return
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                "https://translate.googleapis.com/translate_a/single",
                params={"client": "gtx", "sl": "auto", "tl": "ru", "dt": "t", "q": query}
            ) as r:
                data = await r.json()
        translated = "".join([item[0] for item in data[0] if item[0]])
        src_lang = data[2] if len(data) > 2 else "?"
        await update.message.reply_text(
            f"🌍 *Перевод* (`{src_lang}` → `ru`):\n\n{translated}",
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.error(f"Translate: {e}")
        await update.message.reply_text("❌ Ошибка перевода.")

# ─── МЕМ ─────────────────────────────────────────────────────────────────────
async def flash_meme(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        async with aiohttp.ClientSession() as s:
            headers = {"User-Agent": "Mozilla/5.0"}
            async with s.get("https://pikabu.ru/tag/%D0%BC%D0%B5%D0%BC%D1%8B/hot", headers=headers) as r:
                html = await r.text()
        imgs = re.findall(r'data-large-image="([^"]+)"', html)
        if not imgs:
            imgs = re.findall(r'src="(https://cs\d+\.pikabu\.ru/post_img/[^"]+\.(?:jpg|png|jpeg))"', html)
        if imgs:
            url = random.choice(imgs[:20])
            await update.message.reply_photo(photo=url, caption="😂 Мем с Пикабу")
        else:
            raise Exception("No images found")
    except Exception as e:
        logger.error(f"Meme: {e}")
        try:
            ru_subs = ["ru_memes", "RusMemes", "Pikabu"]
            async with aiohttp.ClientSession() as s:
                for sub in ru_subs:
                    async with s.get(
                        f"https://www.reddit.com/r/{sub}/random/.json",
                        headers={"User-Agent": "Mozilla/5.0"}
                    ) as r:
                        if r.status != 200: continue
                        data = await r.json()
                        try:
                            post = data[0]["data"]["children"][0]["data"]
                            url = post.get("url", "")
                            title = post.get("title", "Мем")
                            if url and any(url.endswith(ext) for ext in [".jpg",".png",".jpeg",".gif"]):
                                await update.message.reply_photo(photo=url, caption=f"😂 {title}")
                                return
                        except: continue
            await update.message.reply_text("😅 Мемы временно недоступны.")
        except Exception as e2:
            logger.error(f"Meme fallback: {e2}")
            await update.message.reply_text("❌ Не удалось получить мем.")

# ─── ОБРАБОТЧИК ТЕКСТА ───────────────────────────────────────────────────────
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    user_id = update.effective_user.id
    raw = update.message.text.strip()
    text = raw.lower()

    if user_id in pending_idea:
        await flash_idea_receive(update, context)
        return

    if text == "🎲 ролл":        await flash_roll(update, context); return
    elif text == "🪙 монетка":   await flash_coin(update, context); return
    elif text == "⚡ флеш":      await flash_help(update, context); return
    elif text == "🌤 погода":    await update.message.reply_text("🌤 Укажи город: `флеш погода Алматы`", parse_mode=ParseMode.MARKDOWN); return
    elif text == "🎵 музыка":    await update.message.reply_text("🎵 Укажи: `флеш музыка Imagine Dragons`", parse_mode=ParseMode.MARKDOWN); return
    elif text == "📧 почта (5 мин)": await flash_mail(update, context); return
    elif text == "💡 предложить": await flash_idea_start(update, context); return

    url = extract_url(raw)
    if url and is_supported_url(url):
        await download_video(update, context, url)
        return

    if not text.startswith("флеш"):
        return

    parts = text.split(None, 2)
    if len(parts) == 1:
        await flash_help(update, context); return

    cmd = parts[1] if len(parts) > 1 else ""
    arg = parts[2].strip() if len(parts) > 2 else ""

    if cmd == "ролл":       await flash_roll(update, context)
    elif cmd == "монетка":  await flash_coin(update, context)
    elif cmd == "погода":   await flash_weather(update, context, city=arg or None)
    elif cmd == "голос":    await flash_voice(update, context)
    elif cmd == "музыка":
        if arg: await flash_music_search(update, context, arg)
        else: await update.message.reply_text("❗ Укажи: `флеш музыка Imagine Dragons`", parse_mode=ParseMode.MARKDOWN)
    elif cmd == "почта":     await flash_mail(update, context)
    elif cmd == "курс":      await flash_rate(update, context)
    elif cmd == "кино":      await flash_movie(update, context, query=arg or None)
    elif cmd == "сериал":    await flash_series(update, context, query=arg or None)
    elif cmd == "сократить": await flash_short(update, context, url=arg or None)
    elif cmd == "перевод":   await flash_translate(update, context, query=arg or None)
    elif cmd == "мем":       await flash_meme(update, context)
    elif cmd == "предложить" or cmd == "идея":
        await flash_idea_start(update, context)
    else:                    await flash_help(update, context)


# ─── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(download_music_callback, pattern="^dl_music:"))
    app.add_handler(CallbackQueryHandler(download_music_callback, pattern="^check_mail:"))
    app.add_handler(CallbackQueryHandler(download_music_callback, pattern="^delete_mail:"))
    app.add_handler(CallbackQueryHandler(guerrilla_callback, pattern="^gm_"))
    app.add_handler(CallbackQueryHandler(movie_callback, pattern="^movie:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    logger.info("⚡ Flash Bot запущен! (TMDB + sspoint парсинг)")

    webhook_url = os.environ.get("WEBHOOK_URL")
    port = int(os.environ.get("PORT", 8443))

    if webhook_url:
        logger.info(f"Webhook: {webhook_url}")
        app.run_webhook(listen="0.0.0.0", port=port, webhook_url=webhook_url, drop_pending_updates=True)
    else:
        logger.info("Polling (локально)")
        app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
