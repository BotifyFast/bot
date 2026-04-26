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
from datetime import datetime, timedelta, timezone
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
                    print(f"Убит старый процесс: {proc.info['pid']}")
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

# ═══════════════════════════════════════════════════════════════════════════════
# КОНФИГУРАЦИЯ
# ═══════════════════════════════════════════════════════════════════════════════

TOKEN = os.environ.get("BOT_TOKEN", "8638601182:AAHAOf2wvybOOyhyt_PNijYkKkljJwGnN-g").strip()
WEATHER_API_KEY = os.environ.get("WEATHER_API_KEY", "c2b2631749aead62cfdc86b394e6399f").strip()
OWNER_ID = int(os.environ.get("OWNER_ID", "1202730193"))
TMDB_KEY = os.environ.get("TMDB_KEY", "8265bd1679663a7ea12ac168da84d2e8").strip()

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
    "💀 ТЫ ЧЁ ТВОРИШЬ?! Волк из Ну погоди осуждает!",
    "😤 ПОЗОР! Даже Чебурашка бы покраснел!",
]

# ═══════════════════════════════════════════════════════════════════════════════
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ═══════════════════════════════════════════════════════════════════════════════

def is_private(u): return u.effective_chat.type == ChatType.PRIVATE

def extract_url(t):
    m = URL_REGEX.search(t)
    return m.group(0) if m else None

def is_supported_url(url): return any(d in url.lower() for d in SUPPORTED_DOMAINS)

def is_audio_url(url): return "soundcloud.com" in url.lower()

def is_tg_url(url): return bool(TG_PATTERN.search(url))

def cleanup_temp():
    """Очищает временные файлы"""
    try:
        tmp = tempfile.gettempdir()
        for item in os.listdir(tmp):
            path = os.path.join(tmp, item)
            if os.path.isdir(path) and item.startswith('tmp'):
                shutil.rmtree(path, ignore_errors=True)
    except: pass
    gc.collect()

def get_wind_direction(degrees):
    """Возвращает направление ветра по градусам"""
    if degrees is None:
        return "?"
    directions = ["⬆️ С", "↗️ СВ", "➡️ В", "↘️ ЮВ", "⬇️ Ю", "↙️ ЮЗ", "⬅️ З", "↖️ СЗ"]
    index = round(degrees / 45) % 8
    return directions[index]

def get_uv_index(uvi):
    """Возвращает описание УФ-индекса"""
    if uvi is None:
        return "?"
    if uvi <= 2: return f"{uvi} (низкий)"
    elif uvi <= 5: return f"{uvi} (средний)"
    elif uvi <= 7: return f"{uvi} (высокий)"
    elif uvi <= 10: return f"{uvi} (очень высокий)"
    else: return f"{uvi} (экстремальный)"

def format_unix_time(timestamp, offset_seconds):
    """Форматирует UNIX timestamp с учётом часового пояса"""
    if not timestamp:
        return "?"
    tz = timezone(timedelta(seconds=offset_seconds))
    dt = datetime.fromtimestamp(timestamp, tz=tz)
    return dt.strftime("%H:%M")

def get_local_time(offset_seconds):
    """Возвращает текущее местное время с учётом смещения"""
    tz = timezone(timedelta(seconds=offset_seconds))
    now_utc = datetime.now(timezone.utc)
    now_local = now_utc.astimezone(tz)
    return now_local.strftime("%H:%M:%S, %d.%m.%Y")

# ═══════════════════════════════════════════════════════════════════════════════
# КЛАВИАТУРА
# ═══════════════════════════════════════════════════════════════════════════════

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("🎲 Ролл"), KeyboardButton("🪙 Монетка")],
        [KeyboardButton("🌤 Погода"), KeyboardButton("🎵 Музыка")],
        [KeyboardButton("📧 Почта (10 мин)"), KeyboardButton("⚡ Флеш")],
        [KeyboardButton("💡 Предложить"), KeyboardButton("😂 Мем")],
    ],
    resize_keyboard=True,
    is_persistent=True
)

MAGIC_BALL_ANSWERS = [
    "✅ Бесспорно",
    "🎯 Предрешено",
    "💯 Никаких сомнений",
    "👍 Определённо да",
    "🔮 Можешь быть уверен в этом",
    "😏 Мне кажется — да",
    "🤔 Вероятнее всего",
    "🌟 Хорошие перспективы",
    "✨ Знаки говорят — да",
    "💤 Пока не ясно, попробуй снова",
    "⏳ Спроси позже",
    "🤐 Лучше не рассказывать",
    "❓ Сейчас нельзя предсказать",
    "🔍 Сконцентрируйся и спроси опять",
    "🙅 Даже не думай",
    "👎 Мой ответ — нет",
    "🔮 По моим данным — нет",
    "😬 Перспективы не очень",
    "💀 Весьма сомнительно",
    "🤷 Шансы 50/50",
]

# ═══════════════════════════════════════════════════════════════════════════════
# КОМАНДА СТАРТ
# ═══════════════════════════════════════════════════════════════════════════════

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Приветственное сообщение"""
    user = update.effective_user
    name = user.first_name or "друг"

    text = (
        f"⚡ *Привет, {name}!*\n\n"
        f"Я *Flash Bot* — твой карманный помощник.\n"
        f"Умею скачивать видео, показывать погоду, искать фильмы и многое другое!\n\n"
        f"╔══════════════════╗\n"
        f"║  🎲 *РАЗВЛЕЧЕНИЯ*  ║\n"
        f"╚══════════════════╝\n"
        f"🎲 `флеш ролл` — бросок кубика 1-100\n"
        f"🪙 `флеш монетка` — орёл или решка\n"
        f"🎱 `флеш шар вопрос` — шар судьбы\n"
        f"⏰ `флеш таймер 5` — таймер на 5 мин\n\n"
        f"╔══════════════════╗\n"
        f"║  🌤 *ИНФОРМАЦИЯ*  ║\n"
        f"╚══════════════════╝\n"
        f"🌤 `флеш погода Город` — подробная погода\n"
        f"💱 `флеш курс` — курсы валют\n"
        f"🪙 `флеш крипта` — BTC, ETH, TON\n\n"
        f"╔══════════════════╗\n"
        f"║  🎬 *ПОИСК*       ║\n"
        f"╚══════════════════╝\n"
        f"🎬 `флеш кино Название` — инфо о фильме\n"
        f"📺 `флеш сериал Название` — инфо о сериале\n\n"
        f"╔══════════════════╗\n"
        f"║  🛠 *ИНСТРУМЕНТЫ*  ║\n"
        f"╚══════════════════╝\n"
        f"🎵 `флеш музыка запрос` — найти трек\n"
        f"🎙 `флеш голос` — речь в текст\n"
        f"📝 `флеш перевод текст` — перевод на русский\n"
        f"🔗 `флеш сократить url` — короткая ссылка\n"
        f"📧 `флеш почта` — временная почта\n"
        f"📥 `флеш тг ссылка` — из ТГ канала\n\n"
        f"📌 *Просто кинь ссылку* из YouTube/TikTok/Instagram — я скачаю!\n\n"
        f"💡 `флеш предложить` — предложить идею\n"
        f"⚡ `флеш` — показать это меню\n\n"
        f"🤖 *Бот создан @Forest_orderly*"
    )
    kb = MAIN_KEYBOARD if is_private(update) else None
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)

async def flash_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

# ═══════════════════════════════════════════════════════════════════════════════
# РАЗВЛЕЧЕНИЯ
# ═══════════════════════════════════════════════════════════════════════════════

async def flash_roll(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Бросок кубика 1-100"""
    user = update.effective_user
    roll = random.randint(1, 100)
    name = user.first_name or "Игрок"

    if roll == 100:
        emoji, comment = "🏆", "ЛЕГЕНДАРНЫЙ БРОСОК! Абсолютный максимум! Ты везунчик!"
    elif roll >= 95:
        emoji, comment = "💎", "ЭПИЧЕСКИ! Почти невозможно! 95+!"
    elif roll >= 90:
        emoji, comment = "🔥", "Потрясающий бросок! Ты в топе!"
    elif roll >= 80:
        emoji, comment = "🌟", "Отличный результат! Выше среднего!"
    elif roll >= 65:
        emoji, comment = "😎", "Хороший бросок! Достойно!"
    elif roll >= 50:
        emoji, comment = "👍", "Неплохо! Золотая середина."
    elif roll >= 35:
        emoji, comment = "😐", "Так себе... Бывает и лучше."
    elif roll >= 20:
        emoji, comment = "😅", "Слабовато... Повезёт в другой раз!"
    elif roll >= 5:
        emoji, comment = "💀", "Почти провал... Сочувствую."
    else:
        emoji, comment = "☠️", "ЭПИЧЕСКИЙ ПРОВАЛ! 5 или меньше! Легендарно плохо!"

    # Визуальная шкала
    bar = "█" * (roll // 5) + "░" * (20 - roll // 5)

    await update.message.reply_text(
        f"{emoji} *{name}* бросает кости...\n\n"
        f"🎯 *Результат:* `{roll}/100`\n"
        f"📊 [{bar}]\n\n"
        f"📢 {comment}",
        parse_mode=ParseMode.MARKDOWN
    )

async def flash_coin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подбрасывание монетки"""
    result = random.choice(["🦅 Орёл!", "🪙 Решка!"])
    emoji = "🦅" if "Орёл" in result else "🪙"

    # Анимация подбрасывания
    await update.message.reply_text(
        f"🪙 Подбрасываю монетку...\n\n"
        f"🌀 *В воздухе...*\n"
        f"✨ *Приземляется...*\n\n"
        f"{emoji} Выпало: *{result}*",
        parse_mode=ParseMode.MARKDOWN
    )

async def flash_magic_ball(update: Update, context: ContextTypes.DEFAULT_TYPE, question: str = None):
    """Шар судьбы"""
    if not question:
        await update.message.reply_text(
            "🎱 *Магический шар судьбы*\n\n"
            "Задай любой вопрос и я дам ответ!\n\n"
            "📝 *Пример:*\n`флеш шар я выиграю в лотерею?`\n`флеш шар стоит ли мне сегодня идти гулять?`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    answer = random.choice(MAGIC_BALL_ANSWERS)
    await update.message.reply_text(
        f"🎱 *Магический шар activated*\n\n"
        f"❓ *Твой вопрос:*\n{question}\n\n"
        f"🔮 *Мой ответ:*\n{answer}\n\n"
        f"✨ Шар сказал — так и будет!",
        parse_mode=ParseMode.MARKDOWN
    )

async def flash_timer(update: Update, context: ContextTypes.DEFAULT_TYPE, minutes_str: str = None):
    """Таймер с уведомлением"""
    if not minutes_str:
        await update.message.reply_text(
            "⏰ *Таймер*\n\n"
            "Укажи количество минут:\n`флеш таймер 5`\n\n"
            "📌 *Максимум:* 120 минут (2 часа)",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    try:
        minutes = int(minutes_str)
        if not 1 <= minutes <= 120:
            await update.message.reply_text("⏰ Укажи от 1 до 120 минут!")
            return
    except:
        await update.message.reply_text("⏰ Нужно число! Например: `флеш таймер 10`", parse_mode=ParseMode.MARKDOWN)
        return

    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    finish_time = datetime.now() + timedelta(minutes=minutes)
    active_timers[user_id] = finish_time

    hours = minutes // 60
    mins = minutes % 60
    duration_str = f"{hours} ч {mins} мин" if hours > 0 else f"{mins} мин"

    await update.message.reply_text(
        f"⏰ *Таймер запущен!*\n\n"
        f"⏱ *Длительность:* {duration_str}\n"
        f"🏁 *Закончится в:* {finish_time.strftime('%H:%M:%S')}\n\n"
        f"Я пришлю уведомление когда время выйдет! 🔔",
        parse_mode=ParseMode.MARKDOWN
    )

    # Ждём и отправляем уведомление
    await asyncio.sleep(minutes * 60)

    if user_id in active_timers:
        try:
            await context.bot.send_message(
                chat_id,
                f"⏰ *ВРЕМЯ ВЫШЛО!*\n\n"
                f"⏱ Прошло ровно: *{duration_str}*\n"
                f"🕐 Текущее время: {datetime.now().strftime('%H:%M:%S')}\n\n"
                f"Не забудь про свои дела! 😊",
                parse_mode=ParseMode.MARKDOWN
            )
        except: pass
        del active_timers[user_id]

# ═══════════════════════════════════════════════════════════════════════════════
# ПОГОДА (С МЕСТНЫМ ВРЕМЕНЕМ ГОРОДА)
# ═══════════════════════════════════════════════════════════════════════════════

async def flash_weather(update: Update, context: ContextTypes.DEFAULT_TYPE, city=None):
    """Подробная погода с местным временем города"""
    if not city:
        await update.message.reply_text(
            "🌤 *Погода*\n\n"
            "Укажи название города:\n"
            "`флеш погода Алматы`\n"
            "`флеш погода Москва`\n"
            "`флеш погода London`\n\n"
            "🌍 Можно на русском или английском.",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    msg = await update.message.reply_text(f"🌤 Ищу погоду в *{city}*...", parse_mode=ParseMode.MARKDOWN)

    try:
        # Текущая погода
        async with aiohttp.ClientSession() as s:
            async with s.get(
                "https://api.openweathermap.org/data/2.5/weather",
                params={
                    "q": city,
                    "appid": WEATHER_API_KEY,
                    "units": "metric",
                    "lang": "ru"
                }
            ) as r:
                if r.status != 200:
                    await msg.edit_text(
                        f"❌ Город *{city}* не найден.\n\n"
                        f"🔍 Проверь правильность названия.\n"
                        f"💡 Попробуй на английском: `флеш погода Moscow`",
                        parse_mode=ParseMode.MARKDOWN
                    )
                    return
                current = await r.json()

            # Координаты для прогноза
            lat = current["coord"]["lat"]
            lon = current["coord"]["lon"]

            # Прогноз на 24 часа (8 отрезков по 3 часа)
            async with s.get(
                "https://api.openweathermap.org/data/2.5/forecast",
                params={
                    "lat": lat,
                    "lon": lon,
                    "appid": WEATHER_API_KEY,
                    "units": "metric",
                    "lang": "ru",
                    "cnt": 8
                }
            ) as r:
                forecast_data = await r.json() if r.status == 200 else None

        # Данные текущей погоды
        city_name = current["name"]
        country = current["sys"]["country"]
        weather_main = current["weather"][0]["main"]
        weather_desc = current["weather"][0]["description"].capitalize()
        weather_icon_code = current["weather"][0]["icon"]

        temp = current["main"]["temp"]
        feels_like = current["main"]["feels_like"]
        temp_min = current["main"]["temp_min"]
        temp_max = current["main"]["temp_max"]
        humidity = current["main"]["humidity"]
        pressure = current["main"]["pressure"]
        pressure_mmhg = round(pressure * 0.75006)

        wind_speed = current["wind"]["speed"]
        wind_deg = current["wind"].get("deg", 0)
        wind_dir = get_wind_direction(wind_deg)
        wind_gust = current["wind"].get("gust", 0)

        visibility = current.get("visibility", 0) / 1000  # км
        cloudiness = current["clouds"]["all"]

        # Часовой пояс города (секунды смещения от UTC)
        timezone_offset = current["timezone"]

        # Восход и закат с учётом местного времени
        sunrise = format_unix_time(current["sys"]["sunrise"], timezone_offset)
        sunset = format_unix_time(current["sys"]["sunset"], timezone_offset)

        # Текущее местное время в городе
        local_time = get_local_time(timezone_offset)

        # Иконки погоды
        icons = {
            "Clear": "☀️",
            "Clouds": "☁️",
            "Rain": "🌧",
            "Snow": "❄️",
            "Thunderstorm": "⛈",
            "Drizzle": "🌦",
            "Mist": "🌫",
            "Fog": "🌫",
            "Haze": "🌫",
            "Dust": "🌪",
            "Sand": "🌪",
            "Squall": "💨",
            "Tornado": "🌪"
        }
        icon = icons.get(weather_main, "🌡")

        # Эмодзи для влажности
        if humidity < 30: humidity_emoji = "🏜"
        elif humidity < 60: humidity_emoji = "💧"
        else: humidity_emoji = "💦"

        # Эмодзи для облачности
        if cloudiness < 10: cloud_emoji = "☀️"
        elif cloudiness < 50: cloud_emoji = "🌤"
        elif cloudiness < 90: cloud_emoji = "⛅"
        else: cloud_emoji = "☁️"

        # Текст текущей погоды
        text = (
            f"{icon} *Погода в {city_name}, {country}*\n\n"
            f"🕐 *Местное время:* `{local_time}`\n"
            f"📋 *Состояние:* {weather_desc}\n\n"
            f"╔══════════════════╗\n"
            f"║  🌡 *ТЕМПЕРАТУРА*  ║\n"
            f"╚══════════════════╝\n"
            f"🌡 *Сейчас:* `{temp:.0f}°C`\n"
            f"🤔 *Ощущается:* `{feels_like:.0f}°C`\n"
            f"📈 *Макс:* `{temp_max:.0f}°C`\n"
            f"📉 *Мин:* `{temp_min:.0f}°C`\n\n"
            f"╔══════════════════╗\n"
            f"║  📊 *ПОКАЗАТЕЛИ*  ║\n"
            f"╚══════════════════╝\n"
            f"{humidity_emoji} *Влажность:* `{humidity}%`\n"
            f"🔵 *Давление:* `{pressure} гПа` ({pressure_mmhg} мм рт. ст.)\n"
            f"💨 *Ветер:* `{wind_speed} м/с` {wind_dir}\n"
        )

        if wind_gust > 0:
            text += f"🌪 *Порывы:* `{wind_gust} м/с`\n"

        text += (
            f"👁 *Видимость:* `{visibility:.1f} км`\n"
            f"{cloud_emoji} *Облачность:* `{cloudiness}%`\n\n"
            f"╔══════════════════╗\n"
            f"║  🌅 *СОЛНЦЕ*      ║\n"
            f"╚══════════════════╝\n"
            f"🌅 *Восход:* `{sunrise}`\n"
            f"🌇 *Закат:* `{sunset}`\n"
        )

        # Длительность светового дня
        if current["sys"]["sunrise"] and current["sys"]["sunset"]:
            day_length_sec = current["sys"]["sunset"] - current["sys"]["sunrise"]
            day_hours = day_length_sec // 3600
            day_mins = (day_length_sec % 3600) // 60
            text += f"☀️ *Световой день:* `{int(day_hours)} ч {int(day_mins)} мин`\n"

        # Прогноз
        if forecast_data and forecast_data.get("list"):
            text += f"\n╔══════════════════╗\n║  📊 *ПРОГНОЗ*     ║\n╚══════════════════╝\n"

            for item in forecast_data["list"][:6]:
                # Время прогноза с учётом часового пояса
                forecast_time = format_unix_time(item["dt"], timezone_offset)
                forecast_temp = item["main"]["temp"]
                forecast_desc = item["weather"][0]["description"].capitalize()
                forecast_icon = icons.get(item["weather"][0]["main"], "🌡")
                forecast_wind = item["wind"]["speed"]
                forecast_humidity = item["main"]["humidity"]

                text += (
                    f"{forecast_icon} *{forecast_time}* — "
                    f"`{forecast_temp:.0f}°C`, {forecast_desc}\n"
                    f"   💨 `{forecast_wind} м/с` | 💧 `{forecast_humidity}%`\n"
                )

        # Футер
        text += (
            f"\n╔══════════════════╗\n"
            f"║  📌 *ИНФО*        ║\n"
            f"╚══════════════════╝\n"
            f"🌍 Координаты: `{lat:.2f}, {lon:.2f}`\n"
            f"🕐 Часовой пояс: UTC{timezone_offset//3600:+d}\n"
            f"📡 Данные: OpenWeatherMap"
        )

        await msg.edit_text(text, parse_mode=ParseMode.MARKDOWN)

    except Exception as e:
        logger.error(f"Weather error: {e}")
        await msg.edit_text(
            "❌ *Ошибка получения погоды.*\n\n"
            "Попробуй позже или проверь название города.",
            parse_mode=ParseMode.MARKDOWN
        )

# ═══════════════════════════════════════════════════════════════════════════════
# РАСПОЗНАВАНИЕ ГОЛОСА
# ═══════════════════════════════════════════════════════════════════════════════

async def flash_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Распознавание голосовых сообщений"""
    msg = update.message

    if not msg.reply_to_message:
        await msg.reply_text(
            "🎙 *Распознавание речи*\n\n"
            "Чтобы перевести голосовое в текст:\n"
            "1. Нажми на голосовое сообщение\n"
            "2. Выбери «Ответить»\n"
            "3. Напиши `флеш голос`\n\n"
            "Я распознаю русскую речь.",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    target = msg.reply_to_message.voice or msg.reply_to_message.video_note
    if not target:
        await msg.reply_text("❗ Это не голосовое сообщение! Ответь на голосовое или видеосообщение.")
        return

    status = await msg.reply_text(
        "🎙 *Распознаю речь...*\n\n"
        "⏳ Это займёт несколько секунд...",
        parse_mode=ParseMode.MARKDOWN
    )

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
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL
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
                f"🎙 *Распознанный текст:*\n\n"
                f"📝 {text}\n\n"
                f"📊 *Символов:* {len(text)}\n"
                f"🔤 *Слов:* {len(text.split())}",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await status.edit_text(
                "🎙 *Речь не распознана.*\n\n"
                "Возможные причины:\n"
                "• Слишком тихо или шумно\n"
                "• Неразборчивая речь\n"
                "• Не русский язык\n\n"
                "Попробуй ещё раз, говори чётче!",
                parse_mode=ParseMode.MARKDOWN
            )

    except Exception as e:
        logger.error(f"Voice error: {e}")
        await status.edit_text("❌ Ошибка распознавания. Попробуй позже.")
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)

# ═══════════════════════════════════════════════════════════════════════════════
# МУЗЫКА
# ═══════════════════════════════════════════════════════════════════════════════

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
logger.info(f"FFMPEG: {_FFMPEG}")

SC_OPTS_BASE = {
    "quiet": True,
    "no_warnings": True,
    "ffmpeg_location": _FFMPEG,
    "http_headers": {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://soundcloud.com/"
    },
    "extractor_args": {"soundcloud": {"client_id": [""]}},
}

async def flash_music_search(update: Update, context: ContextTypes.DEFAULT_TYPE, query: str):
    """Поиск 5 треков на SoundCloud / YouTube"""
    if not query:
        await update.message.reply_text(
            "🎵 *Поиск музыки*\n\n"
            "Укажи название трека или исполнителя:\n"
            "`флеш музыка imagine dragons bones`\n"
            "`флеш музыка моргенштерн`\n\n"
            "🔍 Я найду 5 треков на выбор.",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    msg = await update.message.reply_text(
        f"🔍 *Поиск:* `{query}`\n\nИщу на SoundCloud и YouTube...",
        parse_mode=ParseMode.MARKDOWN
    )

    try:
        import yt_dlp

        def do_search():
            opts = {**SC_OPTS_BASE, "extract_flat": "in_playlist"}
            with yt_dlp.YoutubeDL(opts) as ydl:
                # Сначала SoundCloud
                try:
                    info = ydl.extract_info(f"scsearch5:{query}", download=False)
                    if info and info.get("entries"):
                        return info, "SoundCloud"
                except: pass
                # Потом YouTube
                info = ydl.extract_info(f"ytsearch5:{query}", download=False)
                return info, "YouTube"

        loop = asyncio.get_event_loop()
        info, source = await loop.run_in_executor(None, do_search)

        entries = info.get("entries", []) if info else []
        entries = [e for e in entries if e]

        if not entries:
            await msg.edit_text(
                f"❌ По запросу *{query}* ничего не найдено.\n\n"
                f"Попробуй изменить запрос.",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        uid = update.effective_user.id
        results = []
        buttons = []
        src_icon = "🔊" if "SoundCloud" in source else "▶️"

        for i, entry in enumerate(entries[:5]):
            title = entry.get("title") or f"Трек {i+1}"
            url = entry.get("webpage_url") or entry.get("url") or ""
            duration = int(entry.get("duration") or 0)
            mins, secs = divmod(duration, 60)
            uploader = entry.get("uploader") or entry.get("channel") or "Неизвестно"

            results.append({
                "title": title,
                "url": url,
                "duration": duration,
                "uploader": uploader
            })

            label = f"{src_icon} {i+1}. {title[:40]}"
            if duration > 0:
                label += f" ({mins}:{secs:02d})"
            buttons.append([InlineKeyboardButton(label, callback_data=f"dl_music:{uid}:{i}")])

        pending_music[uid] = results

        await msg.edit_text(
            f"🎵 *Найдено на {source}*\n\n"
            f"🔍 Запрос: `{query}`\n"
            f"📊 Треков: {len(entries)}\n\n"
            f"*Выбери трек для скачивания:*\n"
            f"{src_icon} — {source}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(buttons)
        )

    except Exception as e:
        logger.error(f"Music search error: {e}")
        await msg.edit_text("❌ Ошибка поиска. Попробуй другой запрос или позже.")

async def download_music_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Скачивание выбранного трека"""
    query = update.callback_query
    await query.answer()

    if not query.data.startswith("dl_music:"):
        return

    _, uid_str, idx_str = query.data.split(":")
    uid, idx = int(uid_str), int(idx_str)

    tracks = pending_music.get(uid, [])
    if idx >= len(tracks):
        await query.message.edit_text("❌ Сессия поиска устарела. Повтори поиск командой `флеш музыка`.")
        return

    track = tracks[idx]
    title = track["title"]
    uploader = track["uploader"]

    await query.message.edit_text(
        f"⬇️ *Скачиваю:* {title[:50]}\n"
        f"🎤 {uploader}\n\n"
        f"⏳ Пожалуйста подожди...",
        parse_mode=ParseMode.MARKDOWN
    )

    tmpdir = None
    try:
        tmpdir = tempfile.mkdtemp()
        import yt_dlp

        ydl_opts = {
            **SC_OPTS_BASE,
            "format": "bestaudio/best",
            "outtmpl": os.path.join(tmpdir, "%(title)s.%(ext)s"),
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192"
            }],
            "max_filesize": 48 * 1024 * 1024,
        }

        def do_download():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([track["url"]])

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, do_download)

        # Ищем скачанный файл
        audio_files = list(Path(tmpdir).glob("*.mp3"))
        if not audio_files:
            audio_files = list(Path(tmpdir).glob("*.*"))
        if not audio_files:
            raise FileNotFoundError("Аудиофайл не найден")

        file_size = audio_files[0].stat().st_size
        await query.message.edit_text(
            f"📤 *Отправляю:* {title[:50]}\n"
            f"📦 Размер: {file_size / 1024 / 1024:.1f} МБ",
            parse_mode=ParseMode.MARKDOWN
        )

        async with aiofiles.open(audio_files[0], "rb") as f:
            audio_data = await f.read()

        caption = f"🎵 *{title}*\n🎤 {uploader}"
        if len(caption) > 1024:
            caption = caption[:1020] + "..."

        await query.message.reply_audio(
            audio=audio_data,
            title=title,
            duration=track["duration"],
            performer=uploader,
            caption=caption,
            parse_mode=ParseMode.MARKDOWN
        )
        await query.message.delete()

    except Exception as e:
        logger.error(f"Music download error: {e}")
        await query.message.edit_text(
            "❌ *Не удалось скачать трек.*\n\n"
            "Возможные причины:\n"
            "• Трек недоступен в твоём регионе\n"
            "• Трек удалён\n"
            "• Слишком большой файл\n\n"
            "Попробуй другой трек.",
            parse_mode=ParseMode.MARKDOWN
        )
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)
            gc.collect()

# ═══════════════════════════════════════════════════════════════════════════════
# ВРЕМЕННАЯ ПОЧТА
# ═══════════════════════════════════════════════════════════════════════════════

async def flash_mail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Создание временной почты"""
    if not is_private(update):
        await update.message.reply_text(
            "📧 *Временная почта*\n\n"
            "Работает только в личных сообщениях боту.\n"
            "Напиши мне в личку @flashcombine_bot",
            parse_mode=ParseMode.MARKDOWN
        )
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
            f"⏰ *Срок действия:* 10 минут\n"
            f"🔒 *Приватность:* полная анонимность\n\n"
            f"Нажми кнопку чтобы проверить входящие письма:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📥 Проверить входящие", callback_data=f"gm_check:{sid_token}")],
                [InlineKeyboardButton("🔄 Создать новый ящик", callback_data="gm_new")],
                [InlineKeyboardButton("🗑 Закрыть почту", callback_data="gm_delete")]
            ])
        )

    except Exception as e:
        logger.error(f"Mail error: {e}")
        await msg.edit_text("❌ Ошибка создания почты. Попробуй позже.")

async def guerrilla_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка кнопок временной почты"""
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "gm_new":
        await flash_mail(update, context)
        return

    if data == "gm_delete":
        await query.message.edit_text(
            "🗑 *Почта закрыта*\n\nЯщик удалён. Для создания нового напиши `флеш почта`.",
            parse_mode=ParseMode.MARKDOWN
        )
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

            text = f"📥 *Входящие письма ({len(emails)}):*\n\n"
            for i, mail in enumerate(emails[:5], 1):
                from_addr = mail.get("mail_from", "Неизвестно")
                subject = mail.get("mail_subject", "(без темы)")
                date = mail.get("mail_date", "")

                text += f"*{i}.* 📨 *От:* `{from_addr}`\n"
                text += f"   📋 *Тема:* {subject}\n"
                if date:
                    text += f"   🕐 {date}\n"
                text += "\n"

            if len(emails) > 5:
                text += f"📌 Показано 5 из {len(emails)} писем\n"

            await query.message.edit_text(
                text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Обновить", callback_data=f"gm_check:{sid}")],
                    [InlineKeyboardButton("🗑 Закрыть почту", callback_data="gm_delete")]
                ])
            )
        except Exception as e:
            logger.error(f"Mail check error: {e}")
            await query.answer("❌ Ошибка проверки почты.", show_alert=True)

# ═══════════════════════════════════════════════════════════════════════════════
# ПРЕДЛОЖЕНИЯ ИДЕЙ
# ═══════════════════════════════════════════════════════════════════════════════

async def flash_idea_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Активирует режим предложения идеи"""
    user_id = update.effective_user.id
    pending_idea.add(user_id)
    await update.message.reply_text(
        "💡 *Режим предложений активирован!*\n\n"
        "Напиши *одним сообщением* свою идею для бота:\n"
        "• Какую функцию добавить?\n"
        "• Что улучшить?\n"
        "• Что исправить?\n\n"
        "Я передам идею владельцу бота.\n\n"
        "❌ Для отмены напиши `отмена`.",
        parse_mode=ParseMode.MARKDOWN
    )

async def flash_idea_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Принимает текст идеи"""
    user_id = update.effective_user.id
    user = update.effective_user
    text = update.message.text.strip()

    if text.lower() == "отмена":
        pending_idea.discard(user_id)
        await update.message.reply_text("❌ Отправка идеи отменена.")
        return

    name = user.full_name
    username = f"@{user.username}" if user.username else "нет username"
    date_str = update.message.date.strftime("%d.%m.%Y %H:%M")

    # Сохраняем в файл
    try:
        with open("ideas.txt", "a", encoding="utf-8") as f:
            f.write(f"\n{'='*60}\n")
            f.write(f"💡 НОВАЯ ИДЕЯ\n")
            f.write(f"👤 От: {name} ({username})\n")
            f.write(f"🆔 ID: {user_id}\n")
            f.write(f"📅 Дата: {date_str}\n")
            f.write(f"{'='*60}\n")
            f.write(f"{text}\n")
    except: pass

    # Отправляем владельцу
    if OWNER_ID:
        try:
            owner_msg = (
                f"💡 *Новая идея для бота!*\n\n"
                f"👤 *От:* {name}\n"
                f"🆔 *ID:* `{user_id}`\n"
                f"📅 *Дата:* {date_str}\n\n"
                f"📝 *Текст идеи:*\n{text}"
            )
            await context.bot.send_message(OWNER_ID, owner_msg, parse_mode=ParseMode.MARKDOWN)
        except: pass

    pending_idea.discard(user_id)
    await update.message.reply_text(
        "✅ *Спасибо за идею!*\n\n"
        "Я передал её владельцу бота.\n"
        "Возможно именно твоя идея появится в следующем обновлении! 🚀",
        parse_mode=ParseMode.MARKDOWN
    )

# ═══════════════════════════════════════════════════════════════════════════════
# СКАЧИВАНИЕ ВИДЕО С САЙТОВ
# ═══════════════════════════════════════════════════════════════════════════════

async def download_video(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str):
    """Скачивает видео с популярных сайтов"""
    audio_only = is_audio_url(url)
    site_type = "аудио" if audio_only else "видео"

    msg = await update.message.reply_text(
        f"⬇️ *Обнаружена ссылка!*\n"
        f"🔗 {url[:50]}...\n"
        f"📥 Скачиваю {site_type}...",
        parse_mode=ParseMode.MARKDOWN
    )

    tmpdir = None
    try:
        tmpdir = tempfile.mkdtemp()
        import yt_dlp

        output_template = os.path.join(tmpdir, "%(title)s.%(ext)s")

        if audio_only:
            ydl_opts = {
                "format": "bestaudio/best",
                "outtmpl": output_template,
                "quiet": True,
                "ffmpeg_location": _FFMPEG,
                "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}],
                "max_filesize": 48 * 1024 * 1024,
            }
        else:
            ydl_opts = {
                "format": "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720]/best",
                "outtmpl": output_template,
                "quiet": True,
                "merge_output_format": "mp4",
                "max_filesize": 48 * 1024 * 1024,
                "http_headers": {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
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

        await msg.edit_text(
            f"📤 *Отправляю:* {title[:60]}\n"
            f"⏱ Длительность: {duration//60}:{duration%60:02d}",
            parse_mode=ParseMode.MARKDOWN
        )

        # Ищем скачанный файл
        if audio_only:
            files = list(Path(tmpdir).glob("*.mp3"))
            if not files:
                files = [f for f in Path(tmpdir).iterdir() if f.suffix.lower() in (".mp3", ".m4a", ".opus", ".ogg")]
        else:
            files = list(Path(tmpdir).glob("*.mp4"))
            if not files:
                files = [f for f in Path(tmpdir).iterdir() if f.suffix.lower() in (".mp4", ".mkv", ".webm", ".mov")]

        if not files:
            raise FileNotFoundError("Файл не найден после скачивания")

        file_size = files[0].stat().st_size
        if file_size > 50 * 1024 * 1024:
            await msg.edit_text(
                f"⚠️ *Файл слишком большой!*\n\n"
                f"📦 Размер: {file_size / 1024 / 1024:.1f} МБ\n"
                f"🚫 Лимит Telegram: 50 МБ\n\n"
                f"Попробуй другую ссылку.",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        async with aiofiles.open(files[0], "rb") as f:
            file_data = await f.read()

        caption = f"{'🎵' if audio_only else '🎬'} {title[:500]}"
        if len(caption) > 1024:
            caption = caption[:1020] + "..."

        if audio_only:
            await update.message.reply_audio(
                audio=file_data,
                title=title,
                duration=duration,
                caption=caption,
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_video(
                video=file_data,
                caption=caption,
                duration=duration,
                supports_streaming=True,
                parse_mode=ParseMode.MARKDOWN
            )
        await msg.delete()

    except Exception as e:
        logger.error(f"Download error: {e}")
        error_str = str(e).lower()
        if "too large" in error_str or "filesize" in error_str:
            await msg.edit_text("❌ Файл слишком большой. Лимит 50 МБ.")
        elif "private" in error_str or "login" in error_str:
            await msg.edit_text("❌ Контент недоступен (закрытый аккаунт или приватное видео).")
        elif "copyright" in error_str:
            await msg.edit_text("❌ Контент заблокирован по авторским правам.")
        else:
            await msg.edit_text(
                "❌ *Не удалось скачать.*\n\n"
                "Проверь ссылку или попробуй позже.",
                parse_mode=ParseMode.MARKDOWN
            )
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)
            gc.collect()

# ═══════════════════════════════════════════════════════════════════════════════
# СКАЧИВАНИЕ ИЗ TELEGRAM
# ═══════════════════════════════════════════════════════════════════════════════

async def download_tg(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str):
    """Копирует сообщение из Telegram канала"""
    msg = await update.message.reply_text(
        "📥 *Обнаружена ссылка на Telegram!*\n"
        "Пытаюсь получить контент...",
        parse_mode=ParseMode.MARKDOWN
    )

    match = TG_PATTERN.search(url)
    if not match:
        await msg.edit_text("❌ Неверная ссылка на Telegram сообщение.")
        return

    chat_id_str, message_id = match.groups()
    message_id = int(message_id)

    # Пробуем разные варианты chat_id
    chat_ids = []

    if not chat_id_str.lstrip('-').isdigit():
        # Username канала
        chat_ids.append(f"@{chat_id_str}")
    else:
        # Числовой ID
        chat_ids.append(int(chat_id_str))
        if not chat_id_str.startswith("-100"):
            chat_ids.append(int(f"-100{chat_id_str}"))

    for chat_id in chat_ids:
        try:
            await context.bot.copy_message(
                chat_id=update.effective_chat.id,
                from_chat_id=chat_id,
                message_id=message_id
            )
            await msg.delete()
            return
        except Exception:
            continue

    await msg.edit_text(
        "❌ *Не удалось получить сообщение.*\n\n"
        "📌 *Возможные причины:*\n"
        "• Канал приватный\n"
        "• Бот не в канале\n"
        "• Сообщение удалено\n\n"
        "💡 *Что делать:*\n"
        "• Используй публичный канал\n"
        "• Добавь бота в канал как админа\n"
        "• Проверь правильность ссылки",
        parse_mode=ParseMode.MARKDOWN
    )

# ═══════════════════════════════════════════════════════════════════════════════
# КУРСЫ ВАЛЮТ
# ═══════════════════════════════════════════════════════════════════════════════

async def flash_rate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает курсы валют"""
    msg = await update.message.reply_text("💱 *Загружаю курсы валют...*", parse_mode=ParseMode.MARKDOWN)

    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://open.er-api.com/v6/latest/USD") as r:
                data = await r.json()

        rates = data.get("rates", {})
        update_time = data.get("time_last_update_utc", "?").replace("+0000", "").strip()

        # Дополнительные расчёты
        rub_per_usd = rates.get("RUB", 0)
        kzt_per_usd = rates.get("KZT", 0)
        eur_per_usd = rates.get("EUR", 0)

        rub_per_eur = rub_per_usd / eur_per_usd if eur_per_usd else 0
        kzt_per_eur = kzt_per_usd / eur_per_usd if eur_per_usd else 0

        text = (
            f"💱 *Курсы валют*\n\n"
            f"╔══════════════════╗\n"
            f"║  🇺🇸 К 1 USD      ║\n"
            f"╚══════════════════╝\n"
            f"🇷🇺 *RUB:* `{rates.get('RUB', '?'):.2f}` ₽\n"
            f"🇰🇿 *KZT:* `{rates.get('KZT', '?'):.2f}` ₸\n"
            f"🇺🇦 *UAH:* `{rates.get('UAH', '?'):.2f}` ₴\n"
            f"🇪🇺 *EUR:* `{rates.get('EUR', '?'):.4f}` €\n"
            f"🇬🇧 *GBP:* `{rates.get('GBP', '?'):.4f}` £\n"
            f"🇨🇳 *CNY:* `{rates.get('CNY', '?'):.2f}` ¥\n"
            f"🇯🇵 *JPY:* `{rates.get('JPY', '?'):.0f}` ¥\n"
            f"🇹🇷 *TRY:* `{rates.get('TRY', '?'):.2f}` ₺\n"
            f"🇧🇾 *BYN:* `{rates.get('BYN', '?'):.2f}` Br\n\n"
            f"╔══════════════════╗\n"
            f"║  🇪🇺 К 1 EUR      ║\n"
            f"╚══════════════════╝\n"
            f"🇷🇺 *RUB:* `{rub_per_eur:.2f}` ₽\n"
            f"🇰🇿 *KZT:* `{kzt_per_eur:.2f}` ₸\n\n"
            f"📅 *Обновлено:* {update_time}"
        )

        await msg.edit_text(text, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"Rate error: {e}")
        await msg.edit_text("❌ Ошибка получения курсов валют.")

# ═══════════════════════════════════════════════════════════════════════════════
# КРИПТОВАЛЮТЫ
# ═══════════════════════════════════════════════════════════════════════════════

async def flash_crypto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает курсы криптовалют"""
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

        def format_crypto(coin_data, name, emoji, precision=0):
            price = coin_data.get("usd", 0)
            change = coin_data.get("usd_24h_change", 0)
            volume = coin_data.get("usd_24h_vol", 0)
            trend = "🟢" if change > 0 else "🔴" if change < 0 else "⚪"

            if precision == 0:
                price_str = f"{price:,.0f}"
            else:
                price_str = f"{price:,.{precision}f}"

            return (
                f"{emoji} *{name}*\n"
                f"  💰 `${price_str}`\n"
                f"  {trend} *24ч:* {change:+.2f}%\n"
                f"  📊 *Объём:* `${volume:,.0f}`\n"
            )

        btc = data.get("bitcoin", {})
        eth = data.get("ethereum", {})
        ton = data.get("toncoin", {})

        text = (
            f"🪙 *Криптовалюта*\n\n"
            f"{format_crypto(btc, 'Bitcoin', '₿')}\n"
            f"{format_crypto(eth, 'Ethereum', '♦️')}\n"
            f"{format_crypto(ton, 'Toncoin', '💎', 2)}\n"
            f"📡 *Данные:* CoinGecko"
        )

        await msg.edit_text(text, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"Crypto error: {e}")
        await msg.edit_text("❌ Ошибка загрузки криптовалют.")

# ═══════════════════════════════════════════════════════════════════════════════
# ПОИСК ФИЛЬМОВ И СЕРИАЛОВ
# ═══════════════════════════════════════════════════════════════════════════════

async def search_movie_tv(update, query: str, media_type: str):
    """Поиск фильмов/сериалов через TMDB"""
    type_emoji = "🎬" if media_type == "movie" else "📺"
    type_name = "фильмов" if media_type == "movie" else "сериалов"

    msg = await update.message.reply_text(
        f"{type_emoji} *Ищу в базе {type_name}...*",
        parse_mode=ParseMode.MARKDOWN
    )

    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                f"https://api.themoviedb.org/3/search/{media_type}",
                params={"api_key": TMDB_KEY, "query": query, "language": "ru-RU"}
            ) as r:
                search = await r.json()

        results = search.get("results", [])
        if not results:
            await msg.edit_text(
                f"❌ По запросу *{query}* ничего не найдено.\n\n"
                f"💡 Попробуй изменить запрос или используй оригинальное название.",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        total = search.get("total_results", 0)
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

            label = f"{i+1}. {title[:40]} ({year}) ⭐{rating:.1f}"
            buttons.append([
                InlineKeyboardButton(
                    label,
                    callback_data=f"movie_info:{media_type}:{item['id']}:{safe_title}:{year}"
                )
            ])

        await msg.edit_text(
            f"{type_emoji} *Результаты поиска*\n\n"
            f"🔍 Запрос: `{query}`\n"
            f"📊 Найдено: {total}\n\n"
            f"*Выбери для подробностей:*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(buttons)
        )
    except Exception as e:
        logger.error(f"Search error: {e}")
        await msg.edit_text("❌ Ошибка поиска. Попробуй позже.")

async def movie_info_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает детальную информацию о фильме/сериале"""
    query = update.callback_query
    await query.answer()

    try:
        _, media_type, tmdb_id, title_cb, year_cb = query.data.split(":", 4)
    except:
        await query.message.edit_text("❌ Ошибка загрузки данных.")
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
            revenue = detail.get("revenue", 0)
            if budget > 0:
                extra += f"\n💰 *Бюджет:* ${budget:,}"
            if revenue > 0:
                extra += f"\n💵 *Сборы:* ${revenue:,}"
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
        overview = detail.get("overview", "Описание отсутствует")
        status = detail.get("status", "")
        tagline = detail.get("tagline", "")

        # Страны производства
        countries = ", ".join([c["name"] for c in detail.get("production_countries", [])[:3]])

        poster_path = detail.get("poster_path", "")

        text = (
            f"{icon} *{title}*\n"
            + (f"💬 *«{tagline}»*\n" if tagline else "")
            + (f"🌍 *Оригинал:* {original}\n" if original and original != title else "")
            + f"📅 *Год:* {year}\n"
            + (f"🌎 *Страна:* {countries}\n" if countries else "")
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
        logger.error(f"Movie info error: {e}")
        await query.message.edit_text("❌ Ошибка загрузки информации.")

async def flash_movie(update, context, query=None):
    """Поиск фильма"""
    if not query:
        await update.message.reply_text(
            "🎬 *Поиск фильмов*\n\n"
            "Укажи название:\n`флеш кино Интерстеллар`\n`флеш кино Начало`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    if any(w in query.lower() for w in BAD_WORDS):
        await update.message.reply_text(random.choice(SHAME_RESPONSES))
        return
    await search_movie_tv(update, query, "movie")

async def flash_series(update, context, query=None):
    """Поиск сериала"""
    if not query:
        await update.message.reply_text(
            "📺 *Поиск сериалов*\n\n"
            "Укажи название:\n`флеш сериал Мистер Робот`\n`флеш сериал Ведьмак`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    if any(w in query.lower() for w in BAD_WORDS):
        await update.message.reply_text(random.choice(SHAME_RESPONSES))
        return
    await search_movie_tv(update, query, "tv")

# ═══════════════════════════════════════════════════════════════════════════════
# ИНСТРУМЕНТЫ
# ═══════════════════════════════════════════════════════════════════════════════

async def flash_short(update, context, url=None):
    """Сокращает ссылку"""
    if not url:
        await update.message.reply_text(
            "🔗 *Сокращение ссылок*\n\n"
            "Укажи ссылку:\n`флеш сократить https://example.com/very-long-link`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(f"https://tinyurl.com/api-create.php?url={url}") as r:
                short = await r.text()

        if short.startswith("http"):
            await update.message.reply_text(
                f"🔗 *Ссылка сокращена!*\n\n"
                f"📥 *Исходная:* `{url[:60]}...`\n"
                f"📤 *Короткая:* `{short}`\n\n"
                f"Нажми на короткую ссылку чтобы перейти.",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            raise Exception("bad response")
    except:
        await update.message.reply_text("❌ Ошибка сокращения. Проверь правильность ссылки.")

async def flash_translate(update, context, query=None):
    """Переводит текст на русский"""
    if not query:
        await update.message.reply_text(
            "📝 *Переводчик*\n\n"
            "Укажи текст для перевода на русский:\n"
            "`флеш перевод Hello world`\n"
            "`флеш перевод How are you doing today?`",
            parse_mode=ParseMode.MARKDOWN
        )
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

        lang_names = {
            "en": "Английский", "de": "Немецкий", "fr": "Французский",
            "es": "Испанский", "it": "Итальянский", "zh": "Китайский",
            "ja": "Японский", "ko": "Корейский", "ar": "Арабский",
            "tr": "Турецкий", "uk": "Украинский", "kk": "Казахский"
        }
        src_lang_name = lang_names.get(src_lang, src_lang.upper())

        await update.message.reply_text(
            f"🌍 *Перевод*\n\n"
            f"🔤 *Исходный язык:* {src_lang_name}\n"
            f"📝 *Результат:*\n{translated}",
            parse_mode=ParseMode.MARKDOWN
        )
    except:
        await update.message.reply_text("❌ Ошибка перевода. Попробуй другой текст.")

async def flash_meme(update, context):
    """Отправляет случайный мем"""
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://meme-api.com/gimme/rus") as r:
                data = await r.json()
                if data.get("url"):
                    await update.message.reply_photo(
                        photo=data["url"],
                        caption=f"😂 *{data.get('title', 'Мем')}*\n📊 👍 {data.get('ups', 0)}",
                        parse_mode=ParseMode.MARKDOWN
                    )
                    return
    except: pass

    # Запасной вариант — imgflip
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

    # Запасной вариант 2 — pikabu
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
                return
    except: pass

    await update.message.reply_text(
        "😅 *Мемы временно недоступны.*\n\n"
        "Все источники мемов не отвечают. Попробуй позже!",
        parse_mode=ParseMode.MARKDOWN
    )

# ═══════════════════════════════════════════════════════════════════════════════
# ГЛАВНЫЙ ОБРАБОТЧИК СООБЩЕНИЙ
# ═══════════════════════════════════════════════════════════════════════════════

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает все текстовые сообщения"""
    if not update.message or not update.message.text:
        return

    user_id = update.effective_user.id
    raw = update.message.text.strip()
    text = raw.lower().strip()

    # Режим предложения идей
    if user_id in pending_idea:
        await flash_idea_receive(update, context)
        return

    # Кнопки клавиатуры
    if text == "🎲 ролл":
        await flash_roll(update, context)
    elif text == "🪙 монетка":
        await flash_coin(update, context)
    elif text == "⚡ флеш":
        await flash_help(update, context)
    elif text == "🌤 погода":
        await update.message.reply_text(
            "🌤 *Погода*\n\nУкажи город:\n`флеш погода Алматы`",
            parse_mode=ParseMode.MARKDOWN
        )
    elif text == "🎵 музыка":
        await update.message.reply_text(
            "🎵 *Музыка*\n\nУкажи запрос:\n`флеш музыка imagine dragons`",
            parse_mode=ParseMode.MARKDOWN
        )
    elif text == "📧 почта (10 мин)":
        await flash_mail(update, context)
    elif text == "💡 предложить":
        await flash_idea_start(update, context)
    elif text == "😂 мем":
        await flash_meme(update, context)
    else:
        # Проверка на ссылки
        url = extract_url(raw)
        if url:
            if is_tg_url(url):
                await download_tg(update, context, url)
                return
            if is_supported_url(url):
                await download_video(update, context, url)
                return

        # Команды флеш
        if text.startswith("флеш"):
            parts = text.split(None, 2)
            if len(parts) == 1:
                await flash_help(update, context)
                return

            cmd = parts[1] if len(parts) > 1 else ""
            arg = parts[2].strip() if len(parts) > 2 else ""

            handlers = {
                "ролл": lambda: flash_roll(update, context),
                "монетка": lambda: flash_coin(update, context),
                "погода": lambda: flash_weather(update, context, city=arg or None),
                "голос": lambda: flash_voice(update, context),
                "музыка": lambda: (
                    flash_music_search(update, context, arg) if arg
                    else update.message.reply_text("❗ `флеш музыка запрос`", parse_mode=ParseMode.MARKDOWN)
                ),
                "почта": lambda: flash_mail(update, context),
                "курс": lambda: flash_rate(update, context),
                "крипта": lambda: flash_crypto(update, context),
                "шар": lambda: flash_magic_ball(update, context, question=arg or None),
                "таймер": lambda: flash_timer(update, context, minutes_str=arg or None),
                "кино": lambda: flash_movie(update, context, query=arg or None),
                "сериал": lambda: flash_series(update, context, query=arg or None),
                "сократить": lambda: flash_short(update, context, url=arg or None),
                "перевод": lambda: flash_translate(update, context, query=arg or None),
                "мем": lambda: flash_meme(update, context),
                "тг": lambda: (
                    download_tg(update, context, url=arg) if arg
                    else update.message.reply_text("❗ `флеш тг ссылка`", parse_mode=ParseMode.MARKDOWN)
                ),
                "предложить": lambda: flash_idea_start(update, context),
                "идея": lambda: flash_idea_start(update, context),
            }

            handler = handlers.get(cmd)
            if handler:
                await handler()
            else:
                await flash_help(update, context)

# ═══════════════════════════════════════════════════════════════════════════════
# ЗАПУСК БОТА
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    """Точка входа"""
    import requests

    # Удаляем вебхук перед запуском
    try:
        requests.post(f"https://api.telegram.org/bot{TOKEN}/deleteWebhook", timeout=5)
    except: pass

    time.sleep(1)
    cleanup_temp()

    # Создаём приложение
    app = Application.builder().token(TOKEN).build()

    # Регистрируем обработчики
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(download_music_callback, pattern="^dl_music:"))
    app.add_handler(CallbackQueryHandler(guerrilla_callback, pattern="^gm_"))
    app.add_handler(CallbackQueryHandler(movie_info_callback, pattern="^movie_info:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # Обработчик ошибок
    async def error_handler(update, context):
        logger.error(f"Update {update} caused error: {context.error}")
        if "Conflict" in str(context.error):
            await asyncio.sleep(5)

    app.add_error_handler(error_handler)

    logger.info("⚡ Flash Bot запущен! Все системы работают.")

    # Запуск
    webhook_url = os.environ.get("WEBHOOK_URL")
    port = int(os.environ.get("PORT", "8443"))

    if webhook_url:
        logger.info(f"Режим Webhook: {webhook_url}")
        app.run_webhook(
            listen="0.0.0.0",
            port=port,
            webhook_url=webhook_url,
            drop_pending_updates=True
        )
    else:
        logger.info("Режим Polling")
        app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
