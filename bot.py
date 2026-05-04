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

# ═══════════════ КОНФИГ И ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ ═══════════════
TOKEN = os.environ.get("BOT_TOKEN", "").strip()
WEATHER_API_KEY = os.environ.get("WEATHER_API_KEY", "").strip()
OWNER_ID_STR = os.environ.get("OWNER_ID", "0").strip()
OWNER_ID = int(OWNER_ID_STR) if OWNER_ID_STR.isdigit() else 0
TMDB_KEY = os.environ.get("TMDB_KEY", "").strip()
OPENAI_KEY = os.environ.get("OPENAI_API_KEY", "").strip()

if not TOKEN:
    print("❌ ОШИБКА: BOT_TOKEN не задан в переменных окружения!")
    sys.exit(1)

# ═══════════════ ПОИСК И ПРОВЕРКА FFMPEG ═══════════════
def get_ffmpeg_path():
    """Ищет ffmpeg в системе, включая пути Railway/Nixpacks."""
    paths = [
        "ffmpeg",
        "/usr/bin/ffmpeg",
        "/usr/local/bin/ffmpeg",
        "/nix/var/nix/profiles/default/bin/ffmpeg",
        "/app/ffmpeg"
    ]
    for p in paths:
        try:
            result = subprocess.run([p, "-version"], capture_output=True, timeout=5)
            if result.returncode == 0:
                return p
        except:
            pass
    return shutil.which("ffmpeg")

FFMPEG_PATH = get_ffmpeg_path()

if FFMPEG_PATH:
    print(f"✅ FFmpeg найден: {FFMPEG_PATH}")
else:
    print("❌ FFmpeg НЕ НАЙДЕН! Функции музыки и видео могут не работать.")

# ═══════════════ ИМПОРТЫ TELEGRAM ═══════════════
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from telegram.constants import ChatType, ParseMode

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ═══════════════ ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ ═══════════════
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

# ═══════════════ ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ═══════════════
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

# ═══════════════ КОМАНДЫ БОТА ═══════════════
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

async def flash_roll(update, context):
    user = update.effective_user
    roll = random.randint(1, 100)
    name = user.first_name or "Игрок"
    status = "🏆 МАКСИМУМ!" if roll == 100 else "🔥 Отлично!" if roll >= 80 else "😎 Неплохо!" if roll >= 50 else "😅 Так себе..." if roll >= 20 else "💀 Провал!"
    await update.message.reply_text(f"🎲 *{name}* бросает кости...\n\nВыпало: *{roll}/100*\n{status}", parse_mode=ParseMode.MARKDOWN)

async def flash_coin(update, context):
    await update.message.reply_text(f"Подбрасываю...\n\n{random.choice(['🦅 Орёл!', '🪙 Решка!'])}")

async def flash_weather(update, context, city=None):
    if not city:
        await update.message.reply_text("❗ Укажи город: `флеш погода Алматы`", parse_mode=ParseMode.MARKDOWN)
        return
    city = resolve_city(city)
    msg = await update.message.reply_text(f"🌤 Ищу погоду в *{city}*...", parse_mode=ParseMode.MARKDOWN)
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://api.openweathermap.org/data/2.5/weather", params={"q": city, "appid": WEATHER_API_KEY, "units": "metric", "lang": "ru"}) as r:
                if r.status != 200:
                    await msg.edit_text(f"❌ Город *{city}* не найден.")
                    return
                c = await r.json()
            tz = timezone(timedelta(seconds=c["timezone"]))
            lt = datetime.now(timezone.utc).astimezone(tz).strftime("%H:%M")
            text = f"🌡 *Погода в {c['name']}*\n🕐 Время: {lt}\n\n🌡 Температура: *{c['main']['temp']:.0f}°C*\n📋 Описание: {c['weather'][0]['description'].capitalize()}"
            await msg.edit_text(text, parse_mode=ParseMode.MARKDOWN)
    except:
        await msg.edit_text("❌ Ошибка получения погоды.")

async def flash_music_search(update, context, query):
    if not query:
        await update.message.reply_text("🎵 Укажи название.")
        return
    msg = await update.message.reply_text(f"🔍 Ищу *{query}*...", parse_mode=ParseMode.MARKDOWN)
    try:
        import yt_dlp
        def search():
            with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "extract_flat": "in_playlist"}) as ydl:
                return ydl.extract_info(f"ytsearch5:{query}", download=False)
        loop = asyncio.get_event_loop()
        info = await loop.run_in_executor(None, search)
        entries = info.get("entries", [])
        if not entries:
            await msg.edit_text("❌ Ничего не найдено.")
            return
        uid = update.effective_user.id
        results, buttons = [], []
        for i, e in enumerate(entries[:5]):
            results.append({"title": e["title"], "url": e["url"], "duration": e.get("duration")})
            buttons.append([InlineKeyboardButton(f"▶️ {i+1}. {e['title'][:35]}", callback_data=f"dl_music:{uid}:{i}")])
        pending_music[uid] = results
        await msg.edit_text(f"🎵 Найдено для: `{query}`", reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await msg.edit_text(f"❌ Ошибка: {e}")

async def download_music_callback(update, context):
    q = update.callback_query
    await q.answer()
    _, uid, idx = q.data.split(":")
    uid, idx = int(uid), int(idx)
    track = pending_music.get(uid, [])[idx]
    await q.message.edit_text(f"⬇️ Скачиваю: {track['title']}")
    tmpdir = tempfile.mkdtemp()
    try:
        import yt_dlp
        opts = {"format": "bestaudio/best", "outtmpl": f"{tmpdir}/%(title)s.%(ext)s", "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3"}], "ffmpeg_location": FFMPEG_PATH}
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([track["url"]])
        file = list(Path(tmpdir).glob("*.mp3"))[0]
        await q.message.reply_audio(audio=open(file, "rb"), title=track["title"])
        await q.message.delete()
    except Exception as e:
        await q.message.edit_text(f"❌ Ошибка скачивания: {e}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

# ═══════════════ АНОНИМНЫЙ ЧАТ (ЛОГИКА) ═══════════════
async def exit_anon_chat(user_id, context):
    if user_id in anon_chat_pairs:
        pid = anon_chat_pairs[user_id]
        del anon_chat_pairs[user_id]
        if pid in anon_chat_pairs: del anon_chat_pairs[pid]
        try: await context.bot.send_message(pid, "👋 Собеседник покинул чат.", reply_markup=MAIN_KEYBOARD)
        except: pass
    if user_id in anon_chat_queue: anon_chat_queue.remove(user_id)
    anon_chat_users.discard(user_id)

async def find_new_partner(user_id, context):
    await exit_anon_chat(user_id, context)
    if anon_chat_queue:
        pid = anon_chat_queue.pop(0)
        anon_chat_pairs[user_id], anon_chat_pairs[pid] = pid, user_id
        await context.bot.send_message(user_id, "💬 Собеседник найден!", reply_markup=ANON_CHAT_KEYBOARD)
        await context.bot.send_message(pid, "💬 Собеседник найден!", reply_markup=ANON_CHAT_KEYBOARD)
    else:
        anon_chat_queue.append(user_id)
        await context.bot.send_message(user_id, "⏳ Ищу собеседника...", reply_markup=ANON_CHAT_KEYBOARD)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text.strip()
    
    if uid in anon_chat_pairs:
        if text == "➡️ Следующий": await find_new_partner(uid, context)
        elif text == "🚪 Выйти": await exit_anon_chat(uid, context)
        else: await context.bot.send_message(anon_chat_pairs[uid], f"💬 *Аноним:* {text}", parse_mode=ParseMode.MARKDOWN)
        return

    low_text = text.lower()
    if low_text == "🎲 ролл": await flash_roll(update, context)
    elif low_text == "🪙 монетка": await flash_coin(update, context)
    elif low_text == "💬 анонимный чат": await find_new_partner(uid, context)
    elif low_text.startswith("флеш погода"): await flash_weather(update, context, city=text[12:].strip())
    elif low_text.startswith("флеш музыка"): await flash_music_search(update, context, text[12:].strip())
    elif low_text == "⚡ флеш": await start(update, context)

# ═══════════════ ЗАПУСК ═══════════════
def main():
    cleanup_temp()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(download_music_callback, pattern="^dl_music:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    print("⚡ Flash Bot запущен!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
