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

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

SUPPORTED_DOMAINS = ["youtube.com","youtu.be","tiktok.com","vm.tiktok.com","instagram.com","instagr.am","soundcloud.com","twitter.com","x.com","vk.com","facebook.com","fb.watch"]
URL_REGEX = re.compile(r'https?://[^\s<>"{}|\\^`\[\]]+')

# Хранилище: pending_music[user_id] = [(title, url, duration), ...]
pending_music = {}

def is_private(u): return u.effective_chat.type == ChatType.PRIVATE
def extract_url(t):
    m = URL_REGEX.search(t)
    return m.group(0) if m else None
def is_supported_url(url): return any(d in url.lower() for d in SUPPORTED_DOMAINS)
def is_audio_url(url): return "soundcloud.com" in url.lower()

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [[KeyboardButton("🎲 Ролл"), KeyboardButton("🪙 Монетка")],
     [KeyboardButton("🌤 Погода"), KeyboardButton("🎵 Музыка")],
     [KeyboardButton("📧 Почта (5 мин)"), KeyboardButton("⚡ Флеш")]],
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
    try:
        file = await context.bot.get_file(target.file_id)
        with tempfile.TemporaryDirectory() as tmpdir:
            ogg = os.path.join(tmpdir, "v.ogg")
            wav = os.path.join(tmpdir, "v.wav")
            await file.download_to_drive(ogg)
            p = await asyncio.create_subprocess_exec("ffmpeg","-y","-i",ogg,wav, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
            await p.wait()
            import speech_recognition as sr
            r = sr.Recognizer()
            with sr.AudioFile(wav) as src:
                audio = r.record(src)
            text = r.recognize_google(audio, language="ru-RU")
            await status.edit_text(f"🎙 *Расшифровка:*\n\n{text}", parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"Voice: {e}")
        await status.edit_text("❌ Не удалось распознать речь.")

# ─── МУЗЫКА: ПОИСК 5 ТРЕКОВ ───────────────────────────────────────────────────
SC_OPTS_BASE = {
    "quiet": True,
    "no_warnings": True,
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
            opts = {
                **SC_OPTS_BASE,
                "extract_flat": "in_playlist",
            }
            with yt_dlp.YoutubeDL(opts) as ydl:
                # Пробуем сначала SoundCloud, при ошибке — YouTube
                try:
                    info = ydl.extract_info(f"scsearch5:{query}", download=False)
                    if info and info.get("entries"):
                        return info, "sc"
                except Exception:
                    pass
                # Fallback на YouTube
                info = ydl.extract_info(f"ytsearch5:{query}", download=False)
                return info, "yt"

        loop = asyncio.get_event_loop()
        info, source = await loop.run_in_executor(None, do_search)

        entries = info.get("entries", []) if info else []
        entries = [e for e in entries if e]  # убираем None
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

# ─── СКАЧАТЬ ВЫБРАННЫЙ ТРЕК ───────────────────────────────────────────────────
async def download_music_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    # ── МУЗЫКА ──
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
                **SC_OPTS_BASE,
                "format": "bestaudio/best",
                "outtmpl": output_template,
                "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}],
            }

            def do_dl():
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([url])

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, do_dl)

            mp3_files = list(Path(tmpdir).glob("*.mp3"))
            if not mp3_files:
                raise FileNotFoundError("MP3 не найден")

            await query.message.edit_text(f"📤 Отправляю *{title}*...", parse_mode=ParseMode.MARKDOWN)

            async with aiofiles.open(mp3_files[0], "rb") as f:
                audio_data = await f.read()

            await query.message.reply_audio(audio=audio_data, title=title, duration=duration, caption=f"🎵 {title}")
            await query.message.delete()

        except Exception as e:
            logger.error(f"Music dl: {e}")
            await query.message.edit_text("❌ Не удалось скачать трек.")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)  # удаляем файлы с сервера

        return

    # ── ПОЧТА ──
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

# ─── ВРЕМЕННАЯ ПОЧТА через guerrillamail ──────────────────────────────────────
async def flash_mail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_private(update):
        await update.message.reply_text("📧 Временная почта — только в личке.")
        return
    msg = await update.message.reply_text("📧 Создаю адрес...")
    try:
        async with aiohttp.ClientSession() as s:
            # Используем guerrillamail — не требует регистрации
            async with s.get("https://api.guerrillamail.com/ajax.php?f=get_email_address") as r:
                data = await r.json()
                email = data["email_addr"]
                sid_token = data["sid_token"]

        await msg.edit_text(
            f"📧 *Временная почта готова!*\n\n"
            f"📮 Адрес: `{email}`\n"
            f"⏰ Работает 10 минут\n\n"
            f"Нажми кнопку чтобы проверить письма:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📥 Проверить письма", callback_data=f"gm_check:{sid_token}")],
                [InlineKeyboardButton("🗑 Закрыть", callback_data="gm_delete")]
            ])
        )

        async def auto_expire():
            await asyncio.sleep(600)
            try:
                await msg.edit_text(f"⏰ *Почта истекла*\n\n`{email}`", parse_mode=ParseMode.MARKDOWN)
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

# ─── СКАЧАТЬ ВИДЕО ПО ССЫЛКЕ ──────────────────────────────────────────────────
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
                "quiet": True, "no_warnings": True,
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
        shutil.rmtree(tmpdir, ignore_errors=True)  # ВСЕГДА удаляем файлы с сервера

# ─── ОБРАБОТЧИК ТЕКСТА ────────────────────────────────────────────────────────
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    raw = update.message.text.strip()
    text = raw.lower()

    if text == "🎲 ролл":        await flash_roll(update, context); return
    elif text == "🪙 монетка":   await flash_coin(update, context); return
    elif text == "⚡ флеш":      await flash_help(update, context); return
    elif text == "🌤 погода":    await update.message.reply_text("🌤 Укажи город: `флеш погода Алматы`", parse_mode=ParseMode.MARKDOWN); return
    elif text == "🎵 музыка":    await update.message.reply_text("🎵 Укажи: `флеш музыка Imagine Dragons`", parse_mode=ParseMode.MARKDOWN); return
    elif text == "📧 почта (5 мин)": await flash_mail(update, context); return

    # Авто-скачивание ссылки
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
    elif cmd == "почта":    await flash_mail(update, context)
    else:                   await flash_help(update, context)

# ─── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(download_music_callback, pattern="^dl_music:"))
    app.add_handler(CallbackQueryHandler(download_music_callback, pattern="^check_mail:"))
    app.add_handler(CallbackQueryHandler(download_music_callback, pattern="^delete_mail:"))
    app.add_handler(CallbackQueryHandler(guerrilla_callback, pattern="^gm_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    logger.info("⚡ Flash Bot запущен!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
