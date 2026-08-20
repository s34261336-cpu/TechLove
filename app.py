import os
import re
import asyncio
import logging
import json
import tempfile
import shutil
import threading
from datetime import datetime, timedelta
from collections import defaultdict
import time
import uuid
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo
import aiohttp
from urllib.parse import parse_qs, quote as url_quote, unquote, urlparse
from io import BytesIO
import base64
from html.parser import HTMLParser

from typing import Any, Awaitable, Callable
from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    BotCommand, ReplyKeyboardMarkup, KeyboardButton, TelegramObject, FSInputFile,
    BufferedInputFile,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.dispatcher.middlewares.base import BaseMiddleware
from aiogram.exceptions import TelegramBadRequest

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ["BOT_TOKEN"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
SAMBANOVA_API_KEY = os.environ.get("SAMBANOVA_API_KEY", "")
SAMBANOVA_API_URL = "https://api.sambanova.ai/v1/chat/completions"
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

# Local speech-to-text settings. The model is downloaded only on the first
# voice message and then reused for the lifetime of the bot process.
WHISPER_MODEL_SIZE = os.environ.get("WHISPER_MODEL_SIZE", "base")
_whisper_model = None
_whisper_model_lock = threading.Lock()

ADMIN_ID = 5814345235
USERS_FILE = "users_data.json"
MODELS_FILE = "models_data.json"
CASES_FILE = "cases_data.json"
REMINDERS_FILE = "reminders_data.json"
MOSCOW_TZ = ZoneInfo("Europe/Moscow")
REMINDERS_LOCK = threading.Lock()


# ─── Premium emoji helper ─────────────────────────────────────────────────────

def pe(emoji_id: str, fallback: str) -> str:
    return f'<tg-emoji emoji-id="{emoji_id}">{fallback}</tg-emoji>'


# Emoji IDs shown on model buttons depending on restriction state
EMOJI_RESTRICTED_PERM = "5278578973595427038"
EMOJI_RESTRICTED_TEMP = "5276240711795107620"


def get_model_emoji_id(model_key: str) -> str:
    """Return the emoji_id to display for a model based on its restriction state."""
    r = get_model_restriction(model_key)
    if r:
        if r["type"] == "temporary":
            return EMOJI_RESTRICTED_TEMP
        return EMOJI_RESTRICTED_PERM
    return MODELS[model_key]["emoji_id"]


def is_admin(user_id: int) -> bool:
    """Return True if user has admin privileges (not in test mode)."""
    return user_id == ADMIN_ID and not admin_test_mode


# ─── Models & Roles ──────────────────────────────────────────────────────────

MODELS = {
    "gpt_oss_120b": {
        "name": "GPT-OSS 120B",
        "model_id": "openai/gpt-oss-120b",
        "description": "Мощная 120B модель с открытыми весами от OpenAI. Топовое качество ответов.",
        "emoji": "🦙",
        "emoji_html": pe("5926783847453692661", "🦙"),
        "emoji_id": "5926783847453692661",
    },
    "gpt_oss_20b": {
        "name": "GPT-OSS 20B",
        "model_id": "openai/gpt-oss-20b",
        "description": "Быстрая 20B модель от OpenAI с открытыми весами. Молниеносные ответы.",
        "emoji": "⚡",
        "emoji_html": pe("5323761960829862762", "⚡️"),
        "emoji_id": "5323761960829862762",
    },
    "qwen3_27b": {
        "name": "Qwen3.6 27B",
        "model_id": "qwen/qwen3.6-27b",
        "description": "Новейшая Qwen3.6. Отличный баланс скорости и интеллекта.",
        "emoji": "🔮",
        "emoji_html": pe("5776233299424843260", "🔮"),
        "emoji_id": "5776233299424843260",
    },
    "compound": {
        "name": "Groq Compound",
        "model_id": "groq/compound",
        "description": "Составная модель от Groq. Объединяет несколько ИИ для лучшего результата.",
        "emoji": "⚗️",
        "emoji_html": pe("5913787972200698358", "⚗️"),
        "emoji_id": "5913787972200698358",
    },
    "qwen3_32b": {
        "name": "Groq Compound Mini",
        "model_id": "groq/compound-mini",
        "description": "Компактная составная модель Groq. Быстрая и умная — лучший баланс скорости и качества.",
        "emoji": "🌀",
        "emoji_html": pe("5388957777676745182", "🌀"),
        "emoji_id": "5388957777676745182",
    },
    "gpt_oss_safeguard": {
        "name": "GPT-OSS Safeguard 20B",
        "model_id": "openai/gpt-oss-safeguard-20b",
        "description": "Актуальная защитная модель Groq для безопасных и аккуратных ответов.",
        "emoji": "🛡️",
        "emoji_html": pe("5314536790874230525", "🛡️"),
        "emoji_id": "5314536790874230525",
    },
    "sn_deepseek_v3_1": {
        "name": "DeepSeek V3.1",
        "model_id": "DeepSeek-V3.1",
        "description": "Новейший DeepSeek V3.1 — один из сильнейших открытых ИИ. Логика, код, анализ.",
        "emoji": "🧠",
        "emoji_html": pe("5805553606635559688", "🧠"),
        "emoji_id": "5805553606635559688",
        "provider": "sambanova",
        "max_tokens": 1024,
        "no_thinking": True,
    },
    "sn_deepseek_v3_2": {
        "name": "DeepSeek V3.2",
        "model_id": "DeepSeek-V3.2",
        "description": "Самый свежий DeepSeek V3.2. Улучшенная точность и рассуждения.",
        "emoji": "🔭",
        "emoji_html": pe("5776233299424843260", "🔭"),
        "emoji_id": "5776233299424843260",
        "provider": "sambanova",
        "max_tokens": 1024,
        "no_thinking": True,
    },

    "sn_gemma4_31b": {
        "name": "Gemma 4 31B",
        "model_id": "gemma-4-31B-it",
        "description": "Google Gemma 4 31B на SambaNova. Многомодальная, умная, быстрая.",
        "emoji": "💎",
        "emoji_html": pe("5258093637450866522", "💎"),
        "emoji_id": "5258093637450866522",
        "provider": "sambanova",
        "max_tokens": 1024,
    },
    "sn_gpt_oss_120b": {
        "name": "GPT-OSS 120B",
        "model_id": "gpt-oss-120b",
        "description": "OpenAI GPT-OSS 120B с открытыми весами на SambaNova. Топовое качество.",
        "emoji": "🦙",
        "emoji_html": pe("5926783847453692661", "🦙"),
        "emoji_id": "5926783847453692661",
        "provider": "sambanova",
    },
    "sn_minimax_m27": {
        "name": "MiniMax M2.7",
        "model_id": "MiniMax-M2.7",
        "description": "Новая производственная модель MiniMax на SambaNova. Большой контекст и сильная логика.",
        "emoji": "🚀",
        "emoji_html": pe("5314536790874230525", "🚀"),
        "emoji_id": "5314536790874230525",
        "provider": "sambanova",
    },
    "sn_llama_33_70b": {
        "name": "Llama 3.3 70B",
        "model_id": "Meta-Llama-3.3-70B-Instruct",
        "description": "Надёжная производственная модель Meta на SambaNova.",
        "emoji": "🦙",
        "emoji_html": pe("5926783847453692661", "🦙"),
        "emoji_id": "5926783847453692661",
        "provider": "sambanova",
    },
    "or_nemotron_550b": {
        "name": "Nemotron Ultra 550B",
        "model_id": "nvidia/nemotron-3-ultra-550b-a55b:free",
        "description": "Гигантская 550B модель от NVIDIA. Один из самых мощных открытых ИИ в мире.",
        "emoji": "🚀",
        "emoji_html": pe("5314536790874230525", "🚀"),
        "emoji_id": "5314536790874230525",
        "provider": "openrouter",
    },
    "or_nemotron_120b": {
        "name": "Nemotron Super 120B",
        "model_id": "nvidia/nemotron-3-super-120b-a12b:free",
        "description": "120B модель NVIDIA. Умная, быстрая, отлично справляется со сложными задачами.",
        "emoji": "⚡",
        "emoji_html": pe("5323761960829862762", "⚡️"),
        "emoji_id": "5323761960829862762",
        "provider": "openrouter",
    },
    "or_nemotron_30b": {
        "name": "Nemotron Nano 30B",
        "model_id": "nvidia/nemotron-3-nano-30b-a3b:free",
        "description": "Компактная 30B модель NVIDIA. Быстрые ответы при хорошем качестве.",
        "emoji": "🌀",
        "emoji_html": pe("5388957777676745182", "🌀"),
        "emoji_id": "5388957777676745182",
        "provider": "openrouter",
    },
    "or_gemma4_26b": {
        "name": "Gemma 4 26B",
        "model_id": "google/gemma-4-26b-a4b-it:free",
        "description": "Google Gemma 4 26B — многомодальная модель с поддержкой изображений.",
        "emoji": "💎",
        "emoji_html": pe("5776233299424843260", "💎"),
        "emoji_id": "5776233299424843260",
        "provider": "openrouter",
    },
    "or_ling_flash": {
        "name": "Nemotron 3.5 Lightning",
        "model_id": "nvidia/nemotron-3.5-lightning:free",
        "description": "Новая быстрая бесплатная модель NVIDIA для повседневных задач.",
        "emoji": "🔮",
        "emoji_html": pe("5258093637450866522", "🔮"),
        "emoji_id": "5258093637450866522",
        "provider": "openrouter",
    },
    "or_gemma4_31b": {
        "name": "Gemma 4 31B",
        "model_id": "google/gemma-4-31b-it:free",
        "description": "Мультимодальная модель Google с поддержкой изображений.",
        "emoji": "💎",
        "emoji_html": pe("5258093637450866522", "💎"),
        "emoji_id": "5258093637450866522",
        "provider": "openrouter",
    },
    "or_nemotron_omni": {
        "name": "Nemotron Nano Omni",
        "model_id": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
        "description": "Новая бесплатная reasoning-модель NVIDIA для сложных задач.",
        "emoji": "🧩",
        "emoji_html": pe("5388957777676745182", "🧩"),
        "emoji_id": "5388957777676745182",
        "provider": "openrouter",
    },
    "or_gpt_oss_20b": {
        "name": "GPT-OSS 20B",
        "model_id": "openai/gpt-oss-20b:free",
        "description": "OpenAI GPT-OSS 20B с открытыми весами. Молниеносный и бесплатный.",
        "emoji": "🧠",
        "emoji_html": pe("5805553606635559688", "🧠"),
        "emoji_id": "5805553606635559688",
        "provider": "openrouter",
    },
    "or_nemotron_9b": {
        "name": "Nemotron Nano 9B",
        "model_id": "nvidia/nemotron-nano-9b-v2:free",
        "description": "Лёгкая 9B модель NVIDIA. Максимально быстрая для простых задач.",
        "emoji": "⚡",
        "emoji_html": pe("5323761960829862762", "⚡️"),
        "emoji_id": "5323761960829862762",
        "provider": "openrouter",
    },
}

SYSTEM_PROMPTS = {
    "default": "Ты умный, дружелюбный и полезный ИИ-ассистент. Веди естественный диалог, "
                "чувствуй контекст и отвечай как внимательный собеседник, а не как шаблонный бот. "
                "Отвечай чётко, структурировано и по делу. Используй Markdown для форматирования когда уместно.",
    "coder": "Ты опытный программист и архитектор ПО. Помогаешь писать чистый, эффективный код с подробными объяснениями. Всегда используй блоки кода с указанием языка.",
    "writer": "Ты талантливый писатель и редактор. Помогаешь с текстами, статьями, историями и копирайтингом. Пишешь живо, грамотно и увлекательно.",
    "analyst": "Ты аналитик данных и бизнес-консультант. Помогаешь анализировать информацию, строить стратегии и принимать взвешенные решения.",
    "translator": "Ты профессиональный переводчик и лингвист. Переводи точно и естественно, сохраняя стиль и смысл оригинала. После перевода можешь дать короткий комментарий если нужно.",
    "tutor": "Ты терпеливый и опытный преподаватель. Объясняешь сложные темы простым языком, используешь примеры и аналогии. Проверяешь понимание.",
}

COMMON_INSTRUCTIONS = (
    "Эти правила обязательны для каждого ответа, независимо от выбранной модели, провайдера и роли. "
    "Общайся как живой собеседник, а не как безликий справочник: учитывай предыдущие сообщения, "
    "подстраивай тон под человека и отвечай естественным русским языком. Не повторяй вопрос и не "
    "используй шаблонные заготовки вроде «Конечно, вот ответ», «Хорошо, объясняю», «Рад помочь» "
    "или «Как ИИ». Не начинай каждый ответ одинаково, чередуй длину предложений и формулировки. "
    "Будь тёплым и внимательным. Добавляй 1–3 подходящих эмодзи, когда они усиливают смысл или "
    "передают настроение, но не превращай каждый ответ в гирлянду. Лёгкая шутка или дружеская "
    "ирония уместны в бытовом и весёлом разговоре, но не в грустных, тревожных, медицинских, "
    "финансовых или других серьёзных темах. "
    "Отвечай прямо на просьбу: не ограничивайся общим согласием или пересказом запроса, добавляй "
    "полезный ответ. Подбирай длину под сообщение: на короткий вопрос отвечай коротко, а сложную "
    "тему объясняй с нужными деталями. Если запрос неоднозначный или для хорошего ответа не хватает "
    "контекста, задай один короткий встречный вопрос. Если задача ясна, не устраивай анкету: "
    "сначала помоги, а вопрос добавляй только если он естественно продолжает диалог. "
    "Используй списки и Markdown только когда они действительно улучшают читаемость. "
    "На короткое приветствие отвечай тоже коротко и естественно: на «Привет» достаточно «привет» "
    "или «привет!», без фраз «есть задача?» и без анкеты."
)


SIMPLE_GREETINGS = {
    "привет": "привет",
    "здравствуй": "здравствуй",
    "здравствуйте": "здравствуйте",
    "хай": "хай",
    "хелло": "хелло",
    "доброе утро": "доброе утро",
    "добрый день": "добрый день",
    "добрый вечер": "добрый вечер",
}


def get_simple_greeting(text: str) -> str | None:
    normalized = " ".join(re.findall(r"[a-zа-яё]+", text.casefold()))
    greeting = SIMPLE_GREETINGS.get(normalized)
    if not greeting:
        return None
    if normalized in {"доброе утро"}:
        return f"{greeting}! ☀️"
    if normalized in {"добрый день"}:
        return f"{greeting}! 👋"
    if normalized in {"добрый вечер"}:
        return f"{greeting}! 🌙"
    return f"{greeting}! 👋"


def detect_mood(text: str) -> str:
    """Return a small mood hint for the model without pretending to diagnose emotions."""
    normalized = text.casefold()
    sad_markers = (
        "грустно", "грущу", "плачу", "плакать", "тяжело", "одиноко", "одиночество",
        "устал", "устала", "усталость", "тревожно", "тревога", "страшно", "плохо",
        "разочарован", "разочарована", "ненавижу себя", "не хочу жить",
    )
    happy_markers = (
        "ура", "счастлив", "счастлива", "радуюсь", "весело", "смешно", "классно",
        "отлично", "победа", "получилось", "люблю", "хаха", "ахаха", "😂", "🤣", "🎉",
    )
    angry_markers = (
        "бесит", "злит", "злюсь", "раздражает", "ненавижу", "достало", "ужас",
        "кошмар", "чёрт", "чертовски",
    )
    if any(marker in normalized for marker in sad_markers):
        return (
            "Похоже, человеку сейчас может быть тяжело. Ответь бережно и по-человечески: "
            "признай его чувства, не обесценивай и не шути. Предложи посильный следующий шаг "
            "или просто побудь рядом; если есть признаки опасности, мягко уточни, в безопасности "
            "ли человек сейчас."
        )
    if any(marker in normalized for marker in angry_markers):
        return (
            "Человек может быть раздражён или зол. Не спорь с эмоцией и не отвечай холодно: "
            "сначала признай причину недовольства, затем спокойно предложи решение."
        )
    if any(marker in normalized for marker in happy_markers):
        return (
            "Человек, похоже, в хорошем настроении. Поддержи его энергию, можешь ответить живее "
            "и добавить лёгкую уместную шутку или праздничный эмодзи."
        )
    return (
        "Настроение неочевидно. Сохраняй дружелюбный естественный тон и не приписывай человеку "
        "эмоции без оснований."
    )


ROLES = {
    "default":    {"name": "Ассистент",    "emoji": "🤖",  "emoji_html": pe("5258093637450866522", "🤖"),  "emoji_id": "5258093637450866522"},
    "coder":      {"name": "Программист",  "emoji": "👨‍💻", "emoji_html": pe("5444965061749644170", "👨‍💻"), "emoji_id": "5444965061749644170"},
    "writer":     {"name": "Писатель",     "emoji": "✍️",  "emoji_html": pe("5879841310902324730", "✍️"),  "emoji_id": "5879841310902324730"},
    "analyst":    {"name": "Аналитик",     "emoji": "📊",  "emoji_html": pe("5870921681735781843", "📊"),  "emoji_id": "5870921681735781843"},
    "translator": {"name": "Переводчик",   "emoji": "🌐",  "emoji_html": pe("5972247240217988372", "🌐"),  "emoji_id": "5972247240217988372"},
    "tutor":      {"name": "Преподаватель","emoji": "🎓",  "emoji_html": pe("5206402318769076760", "🎓"),  "emoji_id": "5206402318769076760"},
}


# ─── Communication styles ─────────────────────────────────────────────────────

STYLES = {
    "calm": {
        "name": "Спокойный",
        "emoji": "😌",
        "description": "Вежливо, нейтрально, по делу.",
        "instruction": "Общайся спокойно, вежливо и нейтрально. Без эмоциональных крайностей.",
    },
    "fun": {
        "name": "Весёлый",
        "emoji": "😄",
        "description": "С юмором, шутками и позитивом.",
        "instruction": "Общайся весело и с юмором, шути, используй позитивные эмоции, будь непосредственным и живым.",
    },
    "bold": {
        "name": "Дерзкий",
        "emoji": "😏",
        "description": "Прямой, уверенный, без лишних слов.",
        "instruction": "Общайся дерзко и уверенно: говори прямо, без лишних слов и политесов, чётко и по существу.",
    },
    "rude": {
        "name": "Грубый",
        "emoji": "😤",
        "description": "Резко, без сентиментов, жёстко.",
        "instruction": "Общайся грубо и резко: без сочувствия, без мягкости, максимально жёстко и прямолинейно.",
    },
    "swear": {
        "name": "С матами",
        "emoji": "🤬",
        "description": "Максимально неформально, с матерными словами.",
        "instruction": "Общайся максимально неформально и используй русский мат естественно в речи, как это делают в разговоре друзья. Не стесняйся крепких выражений.",
    },
}


# ─── User data (profiles + Zenotoken) ────────────────────────────────────────

def load_users() -> dict:
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_users(data: dict):
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_user_profile(user_id: int, first_name: str = "", username: str = "") -> dict:
    data = load_users()
    uid = str(user_id)
    if uid not in data:
        data[uid] = {
            "user_id": user_id,
            "first_name": first_name,
            "username": username,
            "zenotoken": 0,
            "joined_at": datetime.now().strftime("%d.%m.%Y %H:%M"),
            "last_seen": datetime.now().strftime("%d.%m.%Y %H:%M"),
            "messages_count": 0,
        }
        save_users(data)
    else:
        # update name fields if provided
        changed = False
        if first_name and data[uid]["first_name"] != first_name:
            data[uid]["first_name"] = first_name
            changed = True
        if username and data[uid]["username"] != username:
            data[uid]["username"] = username
            changed = True
        if changed:
            save_users(data)
    return data[uid]

def update_user_field(user_id: int, field: str, value):
    data = load_users()
    uid = str(user_id)
    if uid in data:
        data[uid][field] = value
        save_users(data)

def touch_user(user_id: int, first_name: str = "", username: str = ""):
    """Register/update user and increment message count."""
    data = load_users()
    uid = str(user_id)
    if uid not in data:
        data[uid] = {
            "user_id": user_id,
            "first_name": first_name or "",
            "username": username or "",
            "zenotoken": 0,
            "joined_at": datetime.now().strftime("%d.%m.%Y %H:%M"),
            "last_seen": datetime.now().strftime("%d.%m.%Y %H:%M"),
            "messages_count": 1,
        }
    else:
        data[uid]["last_seen"] = datetime.now().strftime("%d.%m.%Y %H:%M")
        data[uid]["messages_count"] = data[uid].get("messages_count", 0) + 1
        if first_name:
            data[uid]["first_name"] = first_name
        if username:
            data[uid]["username"] = username
    save_users(data)

def give_tokens(user_id: int, amount: int) -> int:
    data = load_users()
    uid = str(user_id)
    if uid not in data:
        return -1  # user not found
    data[uid]["zenotoken"] = data[uid].get("zenotoken", 0) + amount
    save_users(data)
    return data[uid]["zenotoken"]

def deduct_tokens(user_id: int, amount: int) -> tuple[bool, int]:
    """Deduct tokens from user balance.
    Returns (success, new_balance). success=False means insufficient funds.
    """
    data = load_users()
    uid = str(user_id)
    if uid not in data:
        return False, 0
    current = data[uid].get("zenotoken", 0)
    if current < amount:
        return False, current
    data[uid]["zenotoken"] = current - amount
    save_users(data)
    return True, data[uid]["zenotoken"]

def get_all_users() -> list:
    data = load_users()
    return list(data.values())


# ─── Persistent reminders (Europe/Moscow) ─────────────────────────────────────

REMINDER_TRIGGER_RE = re.compile(
    r"\b(?:(?:поставь|поставить|создай|создать|добавь|добавить|установи|установить)\s+)?"
    r"(?:(?:мне)\s+)?(?:напоминание|напомни|напомнить)"
    r"(?:\s+мне)?\b",
    re.IGNORECASE,
)
REMINDER_TIME_RE = re.compile(
    r"\b(?:в|к)\s*([01]?\d|2[0-3])(?:[:.]([0-5]\d))?\b",
    re.IGNORECASE,
)
REMINDER_RELATIVE_RE = re.compile(
    r"\bчерез\s+(\d+)\s*(мин(?:уту|уты|ут)?|час(?:а|ов)?|д(?:ень|ня|ней))\b",
    re.IGNORECASE,
)
REMINDER_NUMERIC_DATE_RE = re.compile(
    r"\b([0-3]?\d)[./]([01]?\d)(?:[./](\d{2,4}))?\b"
)
REMINDER_MONTHS = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}
REMINDER_MONTH_DATE_RE = re.compile(
    r"\b([0-3]?\d)\s+("
    + "|".join(REMINDER_MONTHS)
    + r")(?:\s+(\d{4}))?\b",
    re.IGNORECASE,
)


def moscow_now() -> datetime:
    return datetime.now(MOSCOW_TZ)


def load_reminders() -> list[dict]:
    if not os.path.exists(REMINDERS_FILE):
        return []
    try:
        with open(REMINDERS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        logger.exception("Не удалось загрузить напоминания")
        return []


def save_reminders(data: list[dict]):
    with open(REMINDERS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _remove_reminder_metadata(text: str) -> str:
    """Leave only the user's reminder text after removing date/time wording."""
    result = REMINDER_TRIGGER_RE.sub(" ", text, count=1)
    result = REMINDER_RELATIVE_RE.sub(" ", result, count=1)
    result = REMINDER_TIME_RE.sub(" ", result, count=1)
    result = REMINDER_NUMERIC_DATE_RE.sub(" ", result, count=1)
    result = REMINDER_MONTH_DATE_RE.sub(" ", result, count=1)
    result = re.sub(r"\b(?:сегодня|завтра|послезавтра)\b", " ", result, count=1, flags=re.IGNORECASE)
    result = re.sub(r"^\s*(?:на|в|к|пожалуйста)\s+", "", result, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", result).strip(" ,.!?—-")


def parse_reminder_request(text: str) -> tuple[dict | None, str | None]:
    """Parse a Russian reminder request and return (payload, error)."""
    trigger = REMINDER_TRIGGER_RE.search(text)
    if not trigger:
        return None, None

    lower_text = text.lower()
    now = moscow_now()
    relative = REMINDER_RELATIVE_RE.search(lower_text)
    time_match = REMINDER_TIME_RE.search(lower_text)

    try:
        if relative:
            amount = int(relative.group(1))
            unit = relative.group(2).lower()
            if unit.startswith("мин"):
                due_at = now + timedelta(minutes=amount)
            elif unit.startswith("час"):
                due_at = now + timedelta(hours=amount)
            else:
                due_at = now + timedelta(days=amount)
        else:
            if not time_match:
                return None, "Укажите время, например: «сегодня в 14:00»."

            hour = int(time_match.group(1))
            minute = int(time_match.group(2) or 0)
            today_match = re.search(r"\bсегодня\b", lower_text)
            tomorrow_match = re.search(r"\bзавтра\b", lower_text)
            day_after_match = re.search(r"\bпослезавтра\b", lower_text)
            numeric_date = REMINDER_NUMERIC_DATE_RE.search(lower_text)
            month_date = REMINDER_MONTH_DATE_RE.search(lower_text)

            if today_match:
                due_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if due_at <= now:
                    return None, "Это время сегодня уже прошло. Укажите более позднее время."
            elif tomorrow_match:
                due_at = (now + timedelta(days=1)).replace(
                    hour=hour, minute=minute, second=0, microsecond=0
                )
            elif day_after_match:
                due_at = (now + timedelta(days=2)).replace(
                    hour=hour, minute=minute, second=0, microsecond=0
                )
            elif numeric_date or month_date:
                if numeric_date:
                    day = int(numeric_date.group(1))
                    month = int(numeric_date.group(2))
                    year_value = numeric_date.group(3)
                else:
                    day = int(month_date.group(1))
                    month = REMINDER_MONTHS[month_date.group(2).lower()]
                    year_value = month_date.group(3)
                year = int(year_value) if year_value else now.year
                if year < 100:
                    year += 2000
                due_at = datetime(year, month, day, hour, minute, tzinfo=MOSCOW_TZ)
                if not year_value and due_at <= now:
                    due_at = due_at.replace(year=year + 1)
            else:
                due_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if due_at <= now:
                    due_at += timedelta(days=1)
    except (ValueError, OverflowError):
        return None, "Не удалось понять дату. Пример: «завтра в 09:30 позвонить маме»."

    reminder_text = _remove_reminder_metadata(text)
    if not reminder_text:
        return None, "Напишите, что именно напомнить после даты и времени."

    return {
        "text": reminder_text,
        "due_at": due_at.isoformat(),
    }, None


def create_reminder(user_id: int, text: str, due_at: str) -> dict:
    reminder = {
        "id": uuid.uuid4().hex[:8],
        "user_id": user_id,
        "text": text,
        "due_at": due_at,
        "status": "pending",
        "created_at": moscow_now().isoformat(),
    }
    with REMINDERS_LOCK:
        reminders = load_reminders()
        reminders.append(reminder)
        save_reminders(reminders)
    return reminder


def get_user_reminders(user_id: int) -> list[dict]:
    with REMINDERS_LOCK:
        reminders = load_reminders()
    return sorted(
        [
            reminder
            for reminder in reminders
            if reminder.get("user_id") == user_id and reminder.get("status") == "pending"
        ],
        key=lambda reminder: reminder.get("due_at", ""),
    )


def delete_user_reminder(user_id: int, reminder_id: str) -> bool:
    with REMINDERS_LOCK:
        reminders = load_reminders()
        for reminder in reminders:
            if (
                reminder.get("id") == reminder_id
                and reminder.get("user_id") == user_id
                and reminder.get("status") == "pending"
            ):
                reminder["status"] = "cancelled"
                reminder["cancelled_at"] = moscow_now().isoformat()
                save_reminders(reminders)
                return True
    return False


def format_reminder_datetime(iso_value: str) -> str:
    due_at = datetime.fromisoformat(iso_value).astimezone(MOSCOW_TZ)
    return due_at.strftime("%d.%m.%Y в %H:%M")


async def reminder_worker(bot: Bot):
    """Deliver due reminders and keep them persistent across bot restarts."""
    while True:
        try:
            now = moscow_now()
            with REMINDERS_LOCK:
                reminders = load_reminders()
            due_reminders = []
            for reminder in reminders:
                if reminder.get("status") != "pending":
                    continue
                try:
                    due_at = datetime.fromisoformat(reminder["due_at"]).astimezone(MOSCOW_TZ)
                except (KeyError, TypeError, ValueError):
                    logger.warning("Пропускаю напоминание с неверной датой: %s", reminder)
                    continue
                if due_at <= now:
                    due_reminders.append(reminder)

            for reminder in due_reminders:
                try:
                    await bot.send_message(
                        reminder["user_id"],
                        f"⏰ <b>Напоминание</b>\n\n{reminder['text']}",
                        parse_mode=ParseMode.HTML,
                    )
                except Exception:
                    logger.exception("Не удалось отправить напоминание %s", reminder.get("id"))
                    continue

                with REMINDERS_LOCK:
                    current = load_reminders()
                    for stored in current:
                        if stored.get("id") == reminder.get("id"):
                            stored["status"] = "sent"
                            stored["sent_at"] = moscow_now().isoformat()
                            break
                    save_reminders(current)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Ошибка фонового обработчика напоминаний")

        await asyncio.sleep(15)


# ─── Model restrictions storage ───────────────────────────────────────────────

def load_restrictions() -> dict:
    if os.path.exists(MODELS_FILE):
        try:
            with open(MODELS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_restrictions(data: dict):
    with open(MODELS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_model_restriction(model_key: str) -> dict | None:
    """Returns restriction dict if model is currently restricted, else None."""
    data = load_restrictions()
    r = data.get(model_key)
    if not r:
        return None
    if r.get("type") == "temporary" and r.get("until"):
        if time.time() > r["until"]:
            # expired — auto-lift
            data.pop(model_key, None)
            save_restrictions(data)
            return None
    return r

def restrict_model(model_key: str, reason: str, until_ts: float | None = None):
    data = load_restrictions()
    data[model_key] = {
        "restricted": True,
        "type": "temporary" if until_ts else "permanent",
        "reason": reason,
        "until": until_ts,
        "restricted_at": datetime.now().strftime("%d.%m.%Y %H:%M"),
    }
    save_restrictions(data)

def unrestrict_model(model_key: str):
    data = load_restrictions()
    data.pop(model_key, None)
    save_restrictions(data)


# ─── Model pricing ────────────────────────────────────────────────────────────

def get_model_price(model_key: str) -> int:
    """Returns cost in ZenoTokens per request (0 = free)."""
    data = load_restrictions()
    return data.get("_prices", {}).get(model_key, 0)

def set_model_price(model_key: str, price: int):
    data = load_restrictions()
    if "_prices" not in data:
        data["_prices"] = {}
    if price <= 0:
        data["_prices"].pop(model_key, None)
    else:
        data["_prices"][model_key] = price
    save_restrictions(data)


# ─── Cases storage ────────────────────────────────────────────────────────────

def load_cases() -> dict:
    if os.path.exists(CASES_FILE):
        try:
            with open(CASES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_cases(data: dict):
    with open(CASES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_all_cases() -> list:
    """Return list of all case dicts."""
    return list(load_cases().values())

def get_available_cases() -> list:
    """Return cases that still have remaining opens."""
    cases = load_cases()
    result = []
    for c in cases.values():
        remaining = c["total_count"] - c["opened_count"]
        if remaining > 0:
            result.append(c)
    return result

def create_case(name: str, total_count: int, per_user_limit: int) -> dict:
    data = load_cases()
    case_id = f"case_{int(time.time())}"
    data[case_id] = {
        "id": case_id,
        "name": name,
        "total_count": total_count,
        "per_user_limit": per_user_limit,
        "opened_count": 0,
        "opened_by": {},
    }
    save_cases(data)
    return data[case_id]

def delete_case(case_id: str):
    data = load_cases()
    data.pop(case_id, None)
    save_cases(data)

def update_case(case_id: str, **kwargs):
    data = load_cases()
    if case_id not in data:
        return
    for k, v in kwargs.items():
        data[case_id][k] = v
    save_cases(data)

def can_user_open_case(case_id: str, user_id: int) -> tuple[bool, str]:
    """Returns (allowed, reason). reason is '' when allowed."""
    data = load_cases()
    c = data.get(case_id)
    if not c:
        return False, "Кейс не найден."
    remaining = c["total_count"] - c["opened_count"]
    if remaining <= 0:
        return False, "Все кейсы уже разобраны. Следи за обновлениями!"
    uid = str(user_id)
    user_opens = c["opened_by"].get(uid, 0)
    if user_opens >= c["per_user_limit"]:
        return False, f"Ты уже открывал этот кейс {user_opens} раз(а). Лимит: {c['per_user_limit']}."
    return True, ""

def record_case_open(case_id: str, user_id: int):
    data = load_cases()
    if case_id not in data:
        return
    uid = str(user_id)
    data[case_id]["opened_count"] += 1
    data[case_id]["opened_by"][uid] = data[case_id]["opened_by"].get(uid, 0) + 1
    save_cases(data)


# ─── Cases: prizes ────────────────────────────────────────────────────────────

import random

CASE_PRIZES = [
    # (weight, prize_type, value, display_name, emoji)
    (40, "nothing",   0,   "Пусто — не повезло",         "💨"),
    (8,  "zenotoken", 10,  "10 ZenoToken",               "🪙"),
    (4,  "zenotoken", 25,  "25 ZenoToken",               "🪙"),
    (2,  "zenotoken", 50,  "50 ZenoToken",               "🪙"),
    (1,  "zenotoken", 100, "100 ZenoToken",              "💎"),
    (5,  "free_gens", 3,   "3 бесплатные генерации",     "🎟"),
    (2,  "free_gens", 5,   "5 бесплатных генераций",     "🎟"),
    (1,  "free_gens", 10,  "10 бесплатных генераций",    "🎟"),
    (2,  "vip",       1,   "VIP-статус на 24 часа",      "👑"),
]

def get_prize_weights() -> list[int]:
    """Return active prize weights — custom overrides fall back to CASE_PRIZES defaults."""
    data = load_cases()
    custom = data.get("_prize_weights", {})
    return [custom.get(str(i), CASE_PRIZES[i][0]) for i in range(len(CASE_PRIZES))]

def set_prize_weight(idx: int, weight: int):
    data = load_cases()
    if "_prize_weights" not in data:
        data["_prize_weights"] = {}
    data["_prize_weights"][str(idx)] = max(0, weight)
    save_cases(data)

def reset_prize_weights():
    data = load_cases()
    data.pop("_prize_weights", None)
    save_cases(data)

def pick_prize() -> dict:
    weights = get_prize_weights()
    chosen = random.choices(CASE_PRIZES, weights=weights, k=1)[0]
    return {"type": chosen[1], "value": chosen[2], "name": chosen[3], "emoji": chosen[4]}

def apply_prize(user_id: int, prize: dict):
    """Apply the won prize to the user's profile."""
    if prize["type"] == "nothing":
        return  # no prize to apply
    data = load_users()
    uid = str(user_id)
    if uid not in data:
        return
    if prize["type"] == "zenotoken":
        data[uid]["zenotoken"] = data[uid].get("zenotoken", 0) + prize["value"]
    elif prize["type"] == "free_gens":
        data[uid]["free_gens"] = data[uid].get("free_gens", 0) + prize["value"]
    elif prize["type"] == "vip":
        data[uid]["vip_until"] = time.time() + 86400  # 24 hours
    save_users(data)

def is_vip(user_id: int) -> bool:
    data = load_users()
    uid = str(user_id)
    if uid not in data:
        return False
    vip_until = data[uid].get("vip_until", 0)
    return vip_until > time.time()

def get_vip_remaining(user_id: int) -> int:
    """Returns seconds remaining on VIP, or 0."""
    data = load_users()
    uid = str(user_id)
    vip_until = data.get(uid, {}).get("vip_until", 0)
    remaining = int(vip_until - time.time())
    return max(0, remaining)


# ─── Image generation pricing ─────────────────────────────────────────────────

def get_img_gen_price() -> int:
    """Returns how many free_gens one image generation costs. 0 = free for all."""
    data = load_restrictions()
    return data.get("_img_gen_price", 1)

def set_img_gen_price(price: int):
    data = load_restrictions()
    data["_img_gen_price"] = max(0, price)
    save_restrictions(data)

def get_user_free_gens(user_id: int) -> int:
    data = load_users()
    return data.get(str(user_id), {}).get("free_gens", 0)

def deduct_user_free_gens(user_id: int, amount: int) -> tuple[bool, int]:
    """Returns (success, new_balance)."""
    if amount <= 0:
        return True, get_user_free_gens(user_id)
    data = load_users()
    uid = str(user_id)
    if uid not in data:
        return False, 0
    current = data[uid].get("free_gens", 0)
    if current < amount:
        return False, current
    data[uid]["free_gens"] = current - amount
    save_users(data)
    return True, data[uid]["free_gens"]


def refund_user_free_gens(user_id: int, amount: int) -> tuple[bool, int]:
    """Return reserved image generations after a failed generation."""
    if amount <= 0:
        return True, get_user_free_gens(user_id)
    data = load_users()
    uid = str(user_id)
    if uid not in data:
        return False, 0
    data[uid]["free_gens"] = data[uid].get("free_gens", 0) + amount
    save_users(data)
    return True, data[uid]["free_gens"]

def img_gen_info_text(user_id: int) -> str:
    """Status line shown in the image generator UI."""
    if is_vip(user_id):
        rem = get_vip_remaining(user_id)
        h = rem // 3600
        m = (rem % 3600) // 60
        return f"\n\n👑 <b>VIP:</b> генерации бесплатны! (истекает через {h}ч {m}м)"
    price = get_img_gen_price()
    if price == 0:
        return "\n\n🎟 Генерации сейчас бесплатны."
    gens = get_user_free_gens(user_id)
    return f"\n\n🎟 Стоимость: <b>{price} генерац.</b> | Ваш баланс: <b>{gens} 🎟</b>"


# ─── Sessions ─────────────────────────────────────────────────────────────────

user_sessions: dict[int, dict] = {}

admin_test_mode: bool = False  # When True, admin is treated as a regular user

# ─── Maintenance mode ─────────────────────────────────────────────────────────
maintenance: dict = {"active": False, "until_ts": None, "reason": ""}

def is_maintenance() -> bool:
    """Returns True if maintenance mode is currently active."""
    if not maintenance["active"]:
        return False
    if maintenance["until_ts"] and time.time() > maintenance["until_ts"]:
        maintenance["active"] = False
        maintenance["until_ts"] = None
        maintenance["reason"] = ""
        return False
    return True

def maintenance_text() -> str:
    until_ts = maintenance.get("until_ts")
    reason = maintenance.get("reason", "")
    if until_ts:
        until_str = datetime.fromtimestamp(until_ts).strftime("%d.%m.%Y в %H:%M")
        time_line = f"⏱ Ориентировочное время окончания: <b>{until_str}</b>"
    else:
        time_line = "⏱ Время окончания пока неизвестно."
    reason_line = f"📌 Причина: <i>{reason}</i>" if reason else ""
    return (
        f"🔧 <b>Бот на технических работах</b>\n\n"
        f"Мы уже всё чиним — скоро вернёмся!\n\n"
        f"{time_line}\n"
        f"{reason_line}\n\n"
        f"Приносим извинения за неудобства 🙏"
    )

SPAM_LIMIT = 5
SPAM_WINDOW = 10
SPAM_COOLDOWN = 30

user_message_times: dict[int, list] = defaultdict(list)
user_spam_warned: dict[int, float] = {}


# ─── Custom exceptions ───────────────────────────────────────────────────────

class RateLimitError(Exception):
    """Raised when the upstream provider returns a 429 rate-limit error."""
    pass


# ─── FSM States ──────────────────────────────────────────────────────────────

class AdminStates(StatesGroup):
    waiting_broadcast = State()
    waiting_give_user = State()
    waiting_give_amount = State()
    waiting_restrict_reason = State()
    waiting_temp_duration = State()
    waiting_temp_reason = State()
    waiting_maintenance_duration = State()
    waiting_maintenance_reason = State()
    waiting_set_price = State()
    waiting_img_gen_price = State()
    waiting_prize_weight = State()


class ImgStates(StatesGroup):
    waiting_prompt = State()
    has_prompt = State()


class CaseStates(StatesGroup):
    waiting_case_name = State()
    waiting_case_total = State()
    waiting_case_limit = State()


class SearchStates(StatesGroup):
    waiting_query = State()


# ─── Anti-spam middleware ─────────────────────────────────────────────────────

class AntiSpamMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Message):
            user_id = event.from_user.id
        elif isinstance(event, CallbackQuery):
            user_id = event.from_user.id
        else:
            return await handler(event, data)

        # admin bypasses all restrictions (full bypass when not in test mode)
        if is_admin(user_id):
            return await handler(event, data)

        # real admin in test mode: always allow admin panel access so they can switch back
        if user_id == ADMIN_ID and admin_test_mode:
            is_admin_panel_action = (
                isinstance(event, Message) and event.text == "🛡 Админ панель"
            ) or (
                isinstance(event, CallbackQuery)
                and event.data is not None
                and (event.data.startswith("admin:") or event.data.startswith("mctrl:"))
            )
            if is_admin_panel_action:
                return await handler(event, data)

        # maintenance mode — block everyone except admin
        if is_maintenance():
            if isinstance(event, Message):
                await event.answer(maintenance_text(), parse_mode=ParseMode.HTML)
            elif isinstance(event, CallbackQuery):
                await event.answer("🔧 Бот на технических работах. Подождите!", show_alert=True)
            return

        now = time.time()

        # VIP users get relaxed anti-spam limits
        vip = is_vip(user_id)
        spam_limit = SPAM_LIMIT * 2 if vip else SPAM_LIMIT
        spam_cooldown = SPAM_COOLDOWN // 2 if vip else SPAM_COOLDOWN

        warned_at = user_spam_warned.get(user_id)
        if warned_at:
            remaining = int(spam_cooldown - (now - warned_at))
            if remaining > 0:
                if isinstance(event, Message):
                    await event.answer(
                        f"⏱ <b>Подожди ещё {remaining} сек.</b>",
                        parse_mode=ParseMode.HTML,
                    )
                elif isinstance(event, CallbackQuery):
                    await event.answer(f"⏱ Подожди ещё {remaining} сек.", show_alert=True)
                return
            else:
                del user_spam_warned[user_id]

        times = user_message_times[user_id]
        times = [t for t in times if now - t < SPAM_WINDOW]
        times.append(now)
        user_message_times[user_id] = times

        if len(times) >= spam_limit:
            user_spam_warned[user_id] = now
            user_message_times[user_id] = []
            if isinstance(event, Message):
                await event.answer(
                    f"🚫 <b>Слишком много запросов!</b>\n\nНе спамь — подожди <b>{spam_cooldown} сек.</b>",
                    parse_mode=ParseMode.HTML,
                )
            elif isinstance(event, CallbackQuery):
                await event.answer(
                    f"🚫 Слишком много запросов! Подожди {spam_cooldown} сек.",
                    show_alert=True,
                )
            return

        return await handler(event, data)


# ─── Session helper ───────────────────────────────────────────────────────────

def get_session(user_id: int) -> dict:
    if user_id not in user_sessions:
        user_sessions[user_id] = {
            "model": "gpt_oss_120b",
            "role": "default",
            "style": "calm",
            "history": [],
            "temperature": 0.7,
            "models_filter": "all",
        }
    else:
        # Ensure older sessions have the style key
        user_sessions[user_id].setdefault("style", "calm")
        user_sessions[user_id].setdefault("models_filter", "all")
    return user_sessions[user_id]


# ─── Keyboards ───────────────────────────────────────────────────────────────

def main_keyboard(user_id: int = 0) -> ReplyKeyboardMarkup:
    def button(text: str, style: str) -> KeyboardButton:
        return KeyboardButton(text=text, style=style)

    buttons = [
        [button("🤖 Модель", "primary"), button("🎭 Роль", "success")],
        [button("⚙️ Настройки", "primary"), button("🗑 Новый диалог", "danger")],
        [button("✨ Генерация", "success"), button("👤 Профиль", "primary")],
        [button("🔎 Найди в интернете", "primary")],
    ]
    if user_id == ADMIN_ID:
        buttons.append([button("🛡 Админ панель", "danger")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


MODEL_STYLES = {
    "gpt_oss_120b": "danger",
    "gpt_oss_20b": "primary",
    "qwen3_27b": "primary",
    "compound": "danger",
    "qwen3_32b": "success",
    "gpt_oss_safeguard": "success",
    "sn_deepseek_v3_1": "danger",
    "sn_deepseek_v3_2": "danger",

    "sn_gemma4_31b": "success",
    "sn_gpt_oss_120b": "danger",
    "sn_minimax_m27": "danger",
    "sn_llama_33_70b": "success",
    "or_nemotron_550b": "danger",
    "or_nemotron_120b": "success",
    "or_nemotron_30b": "primary",
    "or_gemma4_26b": "success",
    "or_gemma4_31b": "success",
    "or_ling_flash": "primary",
    "or_gpt_oss_20b": "primary",
    "or_nemotron_9b": "primary",
    "or_nemotron_omni": "danger",
}


def is_model_available(model: dict) -> bool:
    """Only show models whose provider credentials are configured."""
    provider = model.get("provider", "groq")
    if provider == "sambanova":
        return bool(SAMBANOVA_API_KEY)
    if provider == "openrouter":
        return bool(OPENROUTER_API_KEY)
    return True


def models_keyboard(current: str, filter_mode: str = "all") -> InlineKeyboardMarkup:
    # ── Filter row at the top ──────────────────────────────────────────────────
    FILTER_STYLES = {"all": "primary", "free": "success", "paid": "danger"}
    filter_row = []
    for key, label in [("all", "📋 Все"), ("free", "🆓 Бесплатные"), ("paid", "🪙 Платные")]:
        active = filter_mode == key
        btn = InlineKeyboardButton(
            text=f"✅ {label}" if active else label,
            callback_data=f"mfilter:{key}",
        )
        btn.style = FILTER_STYLES[key]
        filter_row.append(btn)

    # ── Models grouped by provider ────────────────────────────────────────────
    PROVIDER_GROUPS = [
        ("groq",       "⚡️ GROQ"),
        ("sambanova",  "🔥 SAMBANOVA"),
        ("openrouter", "🌐 OPENROUTER"),
    ]

    rows: list[list[InlineKeyboardButton]] = [filter_row]
    any_model = False

    for provider_key, provider_label in PROVIDER_GROUPS:
        group_btns: list[InlineKeyboardButton] = []
        for key, model in MODELS.items():
            if model.get("provider", "groq") != provider_key:
                continue
            if not is_model_available(model):
                continue
            price = get_model_price(key)
            is_paid = price > 0
            if filter_mode == "free" and is_paid:
                continue
            if filter_mode == "paid" and not is_paid:
                continue

            check = "✅ " if key == current else ""
            price_tag = f" · 🪙{price}" if is_paid else ""
            btn = InlineKeyboardButton(
                text=f"{check}{model['name']}{price_tag}",
                callback_data=f"model:{key}",
                icon_custom_emoji_id=get_model_emoji_id(key),
            )
            btn.style = MODEL_STYLES.get(key, "primary")
            group_btns.append(btn)

        if not group_btns:
            continue

        any_model = True
        # Section divider (full-width, non-clickable label)
        rows.append([InlineKeyboardButton(text=f"━━━ {provider_label} ━━━", callback_data="noop")])
        # 2 models per row
        rows += [group_btns[i:i + 2] for i in range(0, len(group_btns), 2)]

    if not any_model:
        rows.append([InlineKeyboardButton(text="— В этой категории нет моделей —", callback_data="noop")])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def roles_keyboard(current: str) -> InlineKeyboardMarkup:
    buttons = []
    for key, role in ROLES.items():
        check = "✅ " if key == current else ""
        btn = InlineKeyboardButton(
            text=f"{check}{role['name']}",
            callback_data=f"role:{key}",
            icon_custom_emoji_id=role["emoji_id"],
        )
        btn.style = "success" if key == current else "primary"
        buttons.append([btn])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def settings_keyboard(user_id: int) -> InlineKeyboardMarkup:
    session = get_session(user_id)
    temp = session["temperature"]
    btn_down = InlineKeyboardButton(text="➖", callback_data="temp:down")
    btn_down.style = "danger"
    btn_val = InlineKeyboardButton(text=f"{temp:.1f}", callback_data="noop")
    btn_up = InlineKeyboardButton(text="➕", callback_data="temp:up")
    btn_up.style = "success"
    btn_close = InlineKeyboardButton(text="✅ Закрыть", callback_data="settings:close")
    btn_close.style = "primary"
    buttons = [
        [InlineKeyboardButton(text=f"🌡 Температура: {temp:.1f}  (точно ←→ креативно)", callback_data="noop")],
        [btn_down, btn_val, btn_up],
        [btn_close],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def admin_keyboard() -> InlineKeyboardMarkup:
    test_label = "🧪 Тест как пользователь: 🟢 ВКЛ" if admin_test_mode else "🧪 Тест как пользователь: ⭕ ВЫКЛ"
    maint_label = "🔧 Тех. работы: 🟢 ВКЛ" if is_maintenance() else "🔧 Тех. работы: ⭕ ВЫКЛ"

    def _btn(text, cb, style="primary"):
        b = InlineKeyboardButton(text=text, callback_data=cb)
        b.style = style
        return b

    test_style = "success" if admin_test_mode else "danger"
    maint_style = "danger" if is_maintenance() else "success"

    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("📢 Рассылка", "admin:broadcast")],
        [_btn("🪙 Выдать ZenoToken", "admin:give", "success")],
        [_btn("📊 Статистика", "admin:stats")],
        [_btn("👥 Список пользователей", "admin:users")],
        [_btn("🔍 Найти пользователя", "admin:find")],
        [_btn("🤖 Управление моделями", "admin:models")],
        [_btn("💰 Цена за запрос", "admin:prices")],
        [_btn("🎟 Цена за генерацию", "admin:imgprice")],
        [_btn("🎁 Управление кейсами", "admin:cases")],
        [_btn(test_label, "admin:testmode", test_style)],
        [_btn(maint_label, "admin:maintenance", maint_style)],
    ])


def admin_models_keyboard() -> InlineKeyboardMarkup:
    """List of all models with restriction status indicator and matching emoji."""
    buttons = []
    for key, model in MODELS.items():
        r = get_model_restriction(key)
        if r:
            if r["type"] == "temporary":
                status = "⏳"
            else:
                status = "🔴"
        else:
            status = "🟢"
        buttons.append([InlineKeyboardButton(
            text=f"{status} {model['name']}",
            callback_data=f"mctrl:info:{key}",
            icon_custom_emoji_id=get_model_emoji_id(key),
        )])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin:back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def model_actions_keyboard(model_key: str) -> InlineKeyboardMarkup:
    r = get_model_restriction(model_key)
    rows = []
    if r:
        btn_resume = InlineKeyboardButton(text="✅ Возобновить", callback_data=f"mctrl:resume:{model_key}")
        btn_resume.style = "success"
        rows.append([btn_resume])
    btn_restrict = InlineKeyboardButton(text="🔴 Ограничить", callback_data=f"mctrl:restrict:{model_key}")
    btn_restrict.style = "danger"
    btn_temp = InlineKeyboardButton(text="⏳ Временно ограничить", callback_data=f"mctrl:temp:{model_key}")
    btn_temp.style = "danger"
    btn_back = InlineKeyboardButton(text="◀️ К моделям", callback_data="admin:models")
    btn_back.style = "primary"
    rows.append([btn_restrict])
    rows.append([btn_temp])
    rows.append([btn_back])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_cancel_keyboard() -> InlineKeyboardMarkup:
    btn = InlineKeyboardButton(text="❌ Отмена", callback_data="admin:cancel")
    btn.style = "danger"
    return InlineKeyboardMarkup(inline_keyboard=[[btn]])


def styles_keyboard(current: str) -> InlineKeyboardMarkup:
    buttons = []
    for key, style in STYLES.items():
        check = "✅ " if key == current else ""
        btn = InlineKeyboardButton(
            text=f"{check}{style['emoji']} {style['name']} — {style['description']}",
            callback_data=f"style:{key}",
        )
        btn.style = "success" if key == current else "primary"
        buttons.append([btn])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def start_inline_keyboard() -> InlineKeyboardMarkup:
    btn_style = InlineKeyboardButton(text="🗣 Стиль общения", callback_data="style:menu")
    btn_style.style = "primary"
    btn_cases = InlineKeyboardButton(text="🎁 Кейсы", callback_data="cases:list")
    btn_cases.style = "success"
    return InlineKeyboardMarkup(inline_keyboard=[[btn_style, btn_cases]])


# ─── Router ───────────────────────────────────────────────────────────────────

router = Router()


# ─── /start ───────────────────────────────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(message: Message):
    user = message.from_user
    touch_user(user.id, user.first_name, user.username or "")
    session = get_session(user.id)
    model = MODELS[session["model"]]
    role = ROLES[session["role"]]
    style = STYLES[session["style"]]
    caption = (
        f"👋 Привет, <b>{user.first_name}</b>!\n\n"
        f"Я — <b>Zeno AI</b> — твой личный ИИ-ассистент с доступом к мощным языковым моделям.\n\n"
        f"🤖 Отвечаю на любые вопросы\n"
        f"🎨 Рисую картинки по описанию\n"
        f"👁 Анализирую фотографии\n"
        f"🎭 Меняю роли и стиль общения\n\n"
        f"📌 <b>Сейчас активно:</b>\n"
        f"• Модель: {model['emoji_html']} {model['name']}\n"
        f"• Роль: {role['emoji_html']} {role['name']}\n"
        f"• Стиль: {style['emoji']} {style['name']}\n\n"
        f"✍️ Просто напиши сообщение — и я отвечу!"
    )
    photo = FSInputFile("attached_assets/IMG_20260810_101608_213_1787023992393.jpg")
    await message.answer_photo(
        photo,
        caption=caption,
        parse_mode=ParseMode.HTML,
        reply_markup=start_inline_keyboard(),
    )
    await message.answer(
        "👇 Выбери раздел:",
        parse_mode=ParseMode.HTML,
        reply_markup=main_keyboard(user.id),
    )


# ─── /help ────────────────────────────────────────────────────────────────────

@router.message(Command("help"))
@router.message(F.text == "ℹ️ Помощь")
async def cmd_help(message: Message):
    models_text = "\n".join(
        f"• {m['emoji_html']} <b>{m['name']}</b> — {m['description']}" for m in MODELS.values()
    )
    roles_text = "\n".join(
        f"• {r['emoji_html']} <b>{r['name']}</b>" for r in ROLES.values()
    )
    text = (
        "📖 <b>Как пользоваться:</b>\n\n"
        "Просто пишите сообщение — бот отвечает с учётом истории разговора.\n\n"
        f"{pe('5258093637450866522', '🤖')} <b>Модели:</b>\n{models_text}\n\n"
        f"{pe('6032625495328165724', '🎭')} <b>Роли:</b>\n{roles_text}\n\n"
        "⚙️ <b>Настройки</b> — регулировка температуры ответа\n"
        "🗑 <b>Новый диалог</b> — сбросить историю\n"
        "✨ <b>Генерация</b> — бесплатные видео и фото по описанию\n"
        "🔎 <b>Найди в интернете</b> — поиск актуальной информации с коротким ответом\n"
        "👁 <b>Анализ фото</b> — отправь фото и я его опишу\n"
        "👤 <b>Профиль</b> — ваш профиль и баланс ZenoToken\n"
        "🎁 <b>Кейсы</b> — открывай кейсы и выигрывай призы\n\n"
        "📝 <b>Команды:</b>\n"
        "/start — главное меню\n"
        "/new — новый диалог\n"
        "/model — сменить модель\n"
        "/role — сменить роль\n"
        "/img — генератор изображений\n"
        "/search — поиск в интернете\n"
        "/status — текущие настройки\n"
        "/profile — мой профиль\n"
        "/help — помощь"
    )
    kb = main_keyboard(message.from_user.id)
    try:
        await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=kb)
    except TelegramBadRequest as e:
        if "DOCUMENT_INVALID" in str(e):
            await message.answer(strip_tg_emoji(text), parse_mode=ParseMode.HTML, reply_markup=kb)
        else:
            raise


# ─── /model ───────────────────────────────────────────────────────────────────

@router.message(Command("model"))
@router.message(F.text == "🤖 Модель")
async def cmd_model(message: Message):
    session = get_session(message.from_user.id)
    filter_mode = session.get("models_filter", "all")
    await message.answer(
        f"{pe('5258093637450866522', '🤖')} <b>Выберите модель ИИ:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=models_keyboard(session["model"], filter_mode)
    )


# ─── /role ────────────────────────────────────────────────────────────────────

@router.message(Command("role"))
@router.message(F.text == "🎭 Роль")
async def cmd_role(message: Message):
    session = get_session(message.from_user.id)
    await message.answer(
        f"{pe('6032625495328165724', '🎭')} <b>Выберите роль ассистента:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=roles_keyboard(session["role"])
    )


# ─── /new ─────────────────────────────────────────────────────────────────────

@router.message(Command("new"))
@router.message(F.text == "🗑 Новый диалог")
async def cmd_new(message: Message):
    session = get_session(message.from_user.id)
    session["history"] = []
    await message.answer(
        "🗑 <b>История очищена.</b> Начинаем новый диалог!",
        parse_mode=ParseMode.HTML,
        reply_markup=main_keyboard(message.from_user.id)
    )


# ─── /status ──────────────────────────────────────────────────────────────────

@router.message(Command("status"))
@router.message(F.text == "⚙️ Настройки")
async def cmd_status(message: Message):
    session = get_session(message.from_user.id)
    model = MODELS[session["model"]]
    role = ROLES[session["role"]]
    text = (
        f"⚙️ <b>Текущие настройки:</b>\n\n"
        f"{pe('5258093637450866522', '🤖')} Модель: {model['emoji_html']} <b>{model['name']}</b>\n"
        f"🎭 Роль: {role['emoji_html']} <b>{role['name']}</b>\n"
        f"🌡 Температура: <b>{session['temperature']:.1f}</b>\n"
        f"💬 Сообщений в истории: <b>{len(session['history'])}</b>"
    )
    kb = settings_keyboard(message.from_user.id)
    try:
        await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=kb)
    except TelegramBadRequest as e:
        if "DOCUMENT_INVALID" in str(e):
            await message.answer(strip_tg_emoji(text), parse_mode=ParseMode.HTML, reply_markup=kb)
        else:
            raise


# ─── /profile ─────────────────────────────────────────────────────────────────

@router.message(Command("profile"))
@router.message(F.text == "👤 Профиль")
async def cmd_profile(message: Message):
    user = message.from_user
    profile = get_user_profile(user.id, user.first_name, user.username or "")
    username_str = f"@{profile['username']}" if profile.get("username") else "—"
    session = get_session(user.id)
    model = MODELS[session["model"]]
    role = ROLES[session["role"]]
    vip = is_vip(user.id)
    vip_line = ""
    if vip:
        rem = get_vip_remaining(user.id)
        h, m = rem // 3600, (rem % 3600) // 60
        vip_line = f"\n👑 <b>VIP-статус активен</b> — истекает через {h}ч {m}м"
    free_gens = profile.get("free_gens", 0)
    text = (
        f"{'👑' if vip else '👤'} <b>Профиль</b>{vip_line}\n\n"
        f"👤 Имя: <b>{profile['first_name']}</b>\n"
        f"🔗 Username: <b>{username_str}</b>\n"
        f"🆔 ID: <code>{profile['user_id']}</code>\n\n"
        f"🪙 <b>ZenoToken: {profile.get('zenotoken', 0)}</b>\n"
        f"🎟 <b>Генерации: {free_gens}</b>\n\n"
        f"💬 Сообщений отправлено: <b>{profile.get('messages_count', 0)}</b>\n"
        f"📅 Дата регистрации: <b>{profile.get('joined_at', '—')}</b>\n"
        f"🕐 Последняя активность: <b>{profile.get('last_seen', '—')}</b>\n\n"
        f"🤖 Текущая модель: {model['emoji_html']} <b>{model['name']}</b>\n"
        f"🎭 Текущая роль: {role['emoji_html']} <b>{role['name']}</b>"
    )
    if vip:
        text += (
            "\n\n👑 <b>VIP-привилегии:</b>\n"
            "• 🎨 Генерации изображений бесплатны\n"
            "• 🤖 Все платные модели бесплатны\n"
            "• ⚡ Антиспам вдвое мягче"
        )
    await message.answer(text, parse_mode=ParseMode.HTML)


# ─── Admin panel ──────────────────────────────────────────────────────────────

def admin_panel_text() -> str:
    users = get_all_users()
    test_note = "\n⚠️ <b>Режим теста активен</b> — вы как обычный пользователь." if admin_test_mode else ""
    return (
        f"🛡 <b>Админ панель</b>\n\n"
        f"👥 Пользователей в базе: <b>{len(users)}</b>{test_note}\n\n"
        f"Выберите действие:"
    )


@router.message(F.text == "🛡 Админ панель")
async def cmd_admin(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ У вас нет доступа к этой команде.")
        return
    await message.answer(admin_panel_text(), parse_mode=ParseMode.HTML, reply_markup=admin_keyboard())


@router.callback_query(F.data == "admin:broadcast")
async def cb_admin_broadcast(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    await state.set_state(AdminStates.waiting_broadcast)
    await callback.message.edit_text(
        "📢 <b>Рассылка</b>\n\nНапишите сообщение для рассылки всем пользователям.\n"
        "Поддерживается HTML-форматирование.",
        parse_mode=ParseMode.HTML,
        reply_markup=admin_cancel_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data == "admin:give")
async def cb_admin_give(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    await state.set_state(AdminStates.waiting_give_user)
    await callback.message.edit_text(
        "🪙 <b>Выдача ZenoToken</b>\n\nВведите ID пользователя или @username:",
        parse_mode=ParseMode.HTML,
        reply_markup=admin_cancel_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data == "admin:stats")
async def cb_admin_stats(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    users = get_all_users()
    total_tokens = sum(u.get("zenotoken", 0) for u in users)
    total_msgs = sum(u.get("messages_count", 0) for u in users)
    top_users = sorted(users, key=lambda u: u.get("zenotoken", 0), reverse=True)[:5]
    top_text = "\n".join(
        f"{i+1}. <b>{u['first_name']}</b> — 🪙 {u.get('zenotoken', 0)}"
        for i, u in enumerate(top_users)
    )
    text = (
        f"📊 <b>Статистика бота</b>\n\n"
        f"👥 Всего пользователей: <b>{len(users)}</b>\n"
        f"💬 Всего сообщений: <b>{total_msgs}</b>\n"
        f"🪙 Всего ZenoToken выдано: <b>{total_tokens}</b>\n\n"
        f"🏆 <b>Топ по ZenoToken:</b>\n{top_text or '—'}"
    )
    back_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin:back")]
    ])
    await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=back_kb)
    await callback.answer()


@router.callback_query(F.data == "admin:users")
async def cb_admin_users(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    users = get_all_users()
    if not users:
        await callback.answer("Пользователей нет", show_alert=True)
        return
    # Show last 20 by last_seen
    recent = sorted(users, key=lambda u: u.get("last_seen", ""), reverse=True)[:20]
    lines = []
    for u in recent:
        uname = f"@{u['username']}" if u.get("username") else f"id{u['user_id']}"
        lines.append(
            f"• <b>{u['first_name']}</b> ({uname})\n"
            f"  🪙 {u.get('zenotoken', 0)} | 💬 {u.get('messages_count', 0)} | 🕐 {u.get('last_seen', '—')}"
        )
    text = f"👥 <b>Последние {len(recent)} пользователей:</b>\n\n" + "\n\n".join(lines)
    back_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin:back")]
    ])
    # Telegram message limit
    if len(text) > 4000:
        text = text[:4000] + "\n\n<i>...список обрезан</i>"
    await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=back_kb)
    await callback.answer()


@router.callback_query(F.data == "admin:find")
async def cb_admin_find(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    await state.set_state(AdminStates.waiting_give_user)
    await state.update_data(find_only=True)
    await callback.message.edit_text(
        "🔍 <b>Поиск пользователя</b>\n\nВведите ID или @username:",
        parse_mode=ParseMode.HTML,
        reply_markup=admin_cancel_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data == "admin:back")
async def cb_admin_back(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer()
        return
    await callback.message.edit_text(admin_panel_text(), parse_mode=ParseMode.HTML, reply_markup=admin_keyboard())
    await callback.answer()


@router.callback_query(F.data == "admin:cancel")
async def cb_admin_cancel(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer()
        return
    await state.clear()
    await callback.message.edit_text(admin_panel_text(), parse_mode=ParseMode.HTML, reply_markup=admin_keyboard())
    await callback.answer("Отменено")


# ─── Admin: Price management ──────────────────────────────────────────────────

def admin_prices_keyboard() -> InlineKeyboardMarkup:
    buttons = []
    for key, model in MODELS.items():
        price = get_model_price(key)
        price_label = f"🆓 Бесплатно" if price == 0 else f"🪙 {price}"
        buttons.append([InlineKeyboardButton(
            text=f"{model['name']} — {price_label}",
            callback_data=f"aprice:pick:{key}",
            icon_custom_emoji_id=model["emoji_id"],
        )])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin:back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@router.callback_query(F.data == "admin:prices")
async def cb_admin_prices(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    await callback.message.edit_text(
        "💰 <b>Цена за запрос</b>\n\n"
        "Нажмите на модель, чтобы изменить стоимость одного запроса в ZenoToken.\n"
        "<i>0 = бесплатная модель</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=admin_prices_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data.startswith("aprice:pick:"))
async def cb_aprice_pick(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    model_key = callback.data.split(":", 2)[2]
    model = MODELS[model_key]
    current_price = get_model_price(model_key)
    await state.set_state(AdminStates.waiting_set_price)
    await state.update_data(price_model_key=model_key)
    await callback.message.edit_text(
        f"💰 <b>Цена за запрос — {model['name']}</b>\n\n"
        f"Текущая цена: <b>{'🆓 Бесплатно' if current_price == 0 else f'🪙 {current_price}'}</b>\n\n"
        f"Введите новую цену (целое число, 0 = бесплатно):",
        parse_mode=ParseMode.HTML,
        reply_markup=admin_cancel_keyboard()
    )
    await callback.answer()


@router.message(AdminStates.waiting_set_price)
async def fsm_set_price(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        price = int(message.text.strip())
        if price < 0:
            raise ValueError
    except ValueError:
        await message.answer(
            "❌ Введите целое число ≥ 0 (например: 0, 5, 10)",
            reply_markup=admin_cancel_keyboard()
        )
        return
    data = await state.get_data()
    model_key = data["price_model_key"]
    model = MODELS[model_key]
    set_model_price(model_key, price)
    await state.clear()
    price_str = "🆓 Бесплатно" if price == 0 else f"🪙 {price} ZenoToken за запрос"
    await message.answer(
        f"✅ <b>Цена обновлена!</b>\n\n"
        f"Модель: <b>{model['name']}</b>\n"
        f"Новая цена: <b>{price_str}</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💰 К ценам", callback_data="admin:prices")],
            [InlineKeyboardButton(text="◀️ В панель", callback_data="admin:back")],
        ])
    )


@router.callback_query(F.data == "admin:imgprice")
async def cb_admin_imgprice(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    current = get_img_gen_price()
    price_str = "🆓 Бесплатно" if current == 0 else f"{current} 🎟 за генерацию"
    await state.set_state(AdminStates.waiting_img_gen_price)
    await callback.message.edit_text(
        f"🎟 <b>Цена за генерацию изображения</b>\n\n"
        f"Текущая цена: <b>{price_str}</b>\n\n"
        f"Введите новую цену в генерациях (0 = бесплатно для всех):",
        parse_mode=ParseMode.HTML,
        reply_markup=admin_cancel_keyboard(),
    )
    await callback.answer()


@router.message(AdminStates.waiting_img_gen_price)
async def fsm_img_gen_price(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        price = int(message.text.strip())
        if price < 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите целое число ≥ 0 (например: 0, 1, 2)", reply_markup=admin_cancel_keyboard())
        return
    set_img_gen_price(price)
    await state.clear()
    price_str = "🆓 Бесплатно для всех" if price == 0 else f"{price} 🎟 за генерацию"
    await message.answer(
        f"✅ <b>Цена обновлена!</b>\n\nГенерация изображения: <b>{price_str}</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ В панель", callback_data="admin:back")],
        ]),
    )


@router.callback_query(F.data == "admin:testmode")
async def cb_admin_testmode(callback: CallbackQuery):
    global admin_test_mode
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    admin_test_mode = not admin_test_mode
    status = "🟢 включён" if admin_test_mode else "⭕ выключен"
    await callback.message.edit_text(admin_panel_text(), parse_mode=ParseMode.HTML, reply_markup=admin_keyboard())
    await callback.answer(f"Режим теста {status}", show_alert=True)


# ─── Admin: Maintenance mode ──────────────────────────────────────────────────

@router.callback_query(F.data == "admin:maintenance")
async def cb_admin_maintenance(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    # If already active — offer to turn off
    if is_maintenance():
        maintenance["active"] = False
        maintenance["until_ts"] = None
        maintenance["reason"] = ""
        await callback.message.edit_text(
            admin_panel_text(), parse_mode=ParseMode.HTML, reply_markup=admin_keyboard()
        )
        await callback.answer("✅ Тех. работы завершены. Бот снова доступен!", show_alert=True)
        return
    # Start setup flow: ask duration
    await state.set_state(AdminStates.waiting_maintenance_duration)
    await callback.message.edit_text(
        "🔧 <b>Технические работы</b>\n\n"
        "Введите продолжительность работ в часах.\n"
        "Например: <code>1</code>, <code>2.5</code>, <code>0.5</code>\n\n"
        "Или напишите <code>0</code>, если время неизвестно.",
        parse_mode=ParseMode.HTML,
        reply_markup=admin_cancel_keyboard(),
    )
    await callback.answer()


@router.message(AdminStates.waiting_maintenance_duration)
async def fsm_maintenance_duration(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    text = message.text.strip().replace(",", ".")
    try:
        hours = float(text)
        if hours < 0:
            raise ValueError
    except ValueError:
        await message.answer(
            "❌ Введите число ≥ 0 (например: <code>1</code>, <code>2.5</code>, <code>0</code>)",
            parse_mode=ParseMode.HTML,
            reply_markup=admin_cancel_keyboard(),
        )
        return
    await state.update_data(maintenance_hours=hours)
    await state.set_state(AdminStates.waiting_maintenance_reason)
    await message.answer(
        "📝 Теперь введите причину технических работ\n"
        "(она будет показана пользователям):",
        parse_mode=ParseMode.HTML,
        reply_markup=admin_cancel_keyboard(),
    )


@router.message(AdminStates.waiting_maintenance_reason)
async def fsm_maintenance_reason(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    data = await state.get_data()
    hours = data.get("maintenance_hours", 0)
    reason = message.text.strip()

    maintenance["active"] = True
    maintenance["reason"] = reason
    maintenance["until_ts"] = time.time() + hours * 3600 if hours > 0 else None

    await state.clear()

    if hours > 0:
        until_str = datetime.fromtimestamp(maintenance["until_ts"]).strftime("%d.%m.%Y в %H:%M")
        time_info = f"⏱ До: <b>{until_str}</b>"
    else:
        time_info = "⏱ Время окончания: неизвестно"

    await message.answer(
        f"🔧 <b>Тех. работы включены!</b>\n\n"
        f"{time_info}\n"
        f"📌 Причина: <i>{reason}</i>\n\n"
        f"Все пользователи будут получать сообщение о работах.\n"
        f"Чтобы выключить — нажми <b>🔧 Тех. работы</b> в админ панели ещё раз.",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ В панель", callback_data="admin:back")]
        ]),
    )


# ─── Admin: Model management ─────────────────────────────────────────────────

@router.callback_query(F.data == "admin:models")
async def cb_admin_models(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    await callback.message.edit_text(
        "🤖 <b>Управление моделями</b>\n\n"
        "🟢 — доступна  |  🔴 — отключена  |  ⏳ — временно отключена\n\n"
        "Выберите модель для управления:",
        parse_mode=ParseMode.HTML,
        reply_markup=admin_models_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data.startswith("mctrl:info:"))
async def cb_mctrl_info(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    model_key = callback.data.split(":", 2)[2]
    model = MODELS[model_key]
    r = get_model_restriction(model_key)
    if r:
        if r["type"] == "temporary":
            until_str = datetime.fromtimestamp(r["until"]).strftime("%d.%m.%Y %H:%M")
            status_text = (
                f"⏳ <b>Временно ограничена</b>\n"
                f"До: <b>{until_str}</b>\n"
                f"Причина: <i>{r['reason']}</i>\n"
                f"Ограничена с: {r['restricted_at']}"
            )
        else:
            status_text = (
                f"🔴 <b>Ограничена</b>\n"
                f"Причина: <i>{r['reason']}</i>\n"
                f"Ограничена с: {r['restricted_at']}"
            )
    else:
        status_text = "🟢 <b>Доступна</b>"

    text = (
        f"{model['emoji_html']} <b>{model['name']}</b>\n\n"
        f"{status_text}\n\n"
        f"Выберите действие:"
    )
    await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=model_actions_keyboard(model_key))
    await callback.answer()


@router.callback_query(F.data.startswith("mctrl:resume:"))
async def cb_mctrl_resume(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    await callback.answer()
    try:
        model_key = callback.data.split(":", 2)[2]
        model = MODELS[model_key]
        unrestrict_model(model_key)
        await callback.message.edit_text(
            f"✅ <b>Модель возобновлена!</b>\n\n"
            f"<b>{model['name']}</b> снова доступна для всех пользователей.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ К моделям", callback_data="admin:models")]
            ])
        )
    except Exception as e:
        logger.error(f"mctrl:resume error: {e}")
        await callback.message.answer(f"❌ Ошибка: {e}", parse_mode=ParseMode.HTML)


@router.callback_query(F.data.startswith("mctrl:restrict:"))
async def cb_mctrl_restrict(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    await callback.answer()
    try:
        model_key = callback.data.split(":", 2)[2]
        model = MODELS[model_key]
        await state.set_state(AdminStates.waiting_restrict_reason)
        await state.update_data(restrict_model_key=model_key)
        await callback.message.edit_text(
            f"🔴 <b>Ограничение модели</b>\n\n"
            f"Модель: <b>{model['name']}</b>\n\n"
            f"Введите причину ограничения (будет показана пользователям):",
            parse_mode=ParseMode.HTML,
            reply_markup=admin_cancel_keyboard()
        )
    except Exception as e:
        logger.error(f"mctrl:restrict error: {e}")
        await state.clear()
        await callback.message.answer(f"❌ Ошибка: {e}", parse_mode=ParseMode.HTML)


@router.callback_query(F.data.startswith("mctrl:temp:"))
async def cb_mctrl_temp(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    await callback.answer()
    try:
        model_key = callback.data.split(":", 2)[2]
        model = MODELS[model_key]
        await state.set_state(AdminStates.waiting_temp_duration)
        await state.update_data(restrict_model_key=model_key)
        await callback.message.edit_text(
            f"⏳ <b>Временное ограничение</b>\n\n"
            f"Модель: <b>{model['name']}</b>\n\n"
            f"Введите длительность в часах (например: 2, 24, 0.5):",
            parse_mode=ParseMode.HTML,
            reply_markup=admin_cancel_keyboard()
        )
    except Exception as e:
        logger.error(f"mctrl:temp error: {e}")
        await state.clear()
        await callback.message.answer(f"❌ Ошибка: {e}", parse_mode=ParseMode.HTML)


# ─── FSM: Restrict model (permanent) ─────────────────────────────────────────

@router.message(AdminStates.waiting_restrict_reason)
async def fsm_restrict_reason(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    data = await state.get_data()
    model_key = data["restrict_model_key"]
    model = MODELS[model_key]
    reason = message.text.strip()
    restrict_model(model_key, reason)
    await state.clear()
    await message.answer(
        f"🔴 <b>Модель ограничена!</b>\n\n"
        f"<b>{model['name']}</b>\n"
        f"Причина: <i>{reason}</i>\n\n"
        f"Пользователи увидят это при попытке использования.",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ К моделям", callback_data="admin:models")]
        ])
    )


# ─── FSM: Restrict model (temporary) — step 1: duration ──────────────────────

@router.message(AdminStates.waiting_temp_duration)
async def fsm_temp_duration(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        hours = float(message.text.strip())
        if hours <= 0:
            raise ValueError
    except ValueError:
        await message.answer(
            "❌ Введите положительное число (например: 1, 2.5, 24)",
            reply_markup=admin_cancel_keyboard()
        )
        return
    await state.set_state(AdminStates.waiting_temp_reason)
    await state.update_data(restrict_hours=hours)
    data = await state.get_data()
    model = MODELS[data["restrict_model_key"]]
    await message.answer(
        f"⏳ Длительность: <b>{hours} ч.</b>\n\n"
        f"Модель: <b>{model['name']}</b>\n\n"
        f"Теперь введите причину (будет показана пользователям):",
        parse_mode=ParseMode.HTML,
        reply_markup=admin_cancel_keyboard()
    )


# ─── FSM: Restrict model (temporary) — step 2: reason ────────────────────────

@router.message(AdminStates.waiting_temp_reason)
async def fsm_temp_reason(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    data = await state.get_data()
    model_key = data["restrict_model_key"]
    hours = data["restrict_hours"]
    model = MODELS[model_key]
    reason = message.text.strip()
    until_ts = time.time() + hours * 3600
    restrict_model(model_key, reason, until_ts=until_ts)
    await state.clear()
    until_str = datetime.fromtimestamp(until_ts).strftime("%d.%m.%Y %H:%M")
    await message.answer(
        f"⏳ <b>Модель временно ограничена!</b>\n\n"
        f"<b>{model['name']}</b>\n"
        f"До: <b>{until_str}</b>\n"
        f"Причина: <i>{reason}</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ К моделям", callback_data="admin:models")]
        ])
    )


# ─── FSM: Broadcast ───────────────────────────────────────────────────────────

@router.message(AdminStates.waiting_broadcast)
async def fsm_broadcast_text(message: Message, state: FSMContext, bot: Bot):
    if message.from_user.id != ADMIN_ID:
        return
    await state.clear()
    broadcast_text = message.text or message.caption or ""
    users = get_all_users()
    sent = 0
    failed = 0
    status_msg = await message.answer(
        f"📢 Начинаю рассылку для <b>{len(users)}</b> пользователей...",
        parse_mode=ParseMode.HTML
    )
    for user in users:
        try:
            await bot.send_message(
                chat_id=user["user_id"],
                text=f"📢 <b>Сообщение от администратора:</b>\n\n{broadcast_text}",
                parse_mode=ParseMode.HTML
            )
            sent += 1
            await asyncio.sleep(0.05)  # avoid flood
        except Exception:
            failed += 1
    await status_msg.edit_text(
        f"✅ <b>Рассылка завершена!</b>\n\n"
        f"📤 Отправлено: <b>{sent}</b>\n"
        f"❌ Не доставлено: <b>{failed}</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ В панель", callback_data="admin:back")]
        ])
    )


# ─── FSM: Give tokens — step 1 (user lookup) ─────────────────────────────────

@router.message(AdminStates.waiting_give_user)
async def fsm_give_user(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    query = message.text.strip().lstrip("@")
    data = await state.get_data()
    find_only = data.get("find_only", False)

    users = load_users()
    found = None
    # Try by numeric ID first
    if query.isdigit():
        uid = query
        if uid in users:
            found = users[uid]
    else:
        # Search by username (case-insensitive)
        for u in users.values():
            if u.get("username", "").lower() == query.lower():
                found = u
                break

    if not found:
        await message.answer(
            f"❌ Пользователь <code>{query}</code> не найден в базе.",
            parse_mode=ParseMode.HTML,
            reply_markup=admin_cancel_keyboard()
        )
        return

    if find_only:
        await state.clear()
        uname = f"@{found['username']}" if found.get("username") else "—"
        text = (
            f"🔍 <b>Профиль пользователя</b>\n\n"
            f"👤 Имя: <b>{found['first_name']}</b>\n"
            f"🔗 Username: <b>{uname}</b>\n"
            f"🆔 ID: <code>{found['user_id']}</code>\n"
            f"🪙 ZenoToken: <b>{found.get('zenotoken', 0)}</b>\n"
            f"💬 Сообщений: <b>{found.get('messages_count', 0)}</b>\n"
            f"📅 Регистрация: <b>{found.get('joined_at', '—')}</b>\n"
            f"🕐 Последняя активность: <b>{found.get('last_seen', '—')}</b>"
        )
        give_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🪙 Выдать токены", callback_data=f"admin:give_to:{found['user_id']}")],
            [InlineKeyboardButton(text="◀️ В панель", callback_data="admin:back")],
        ])
        await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=give_kb)
        return

    await state.set_state(AdminStates.waiting_give_amount)
    await state.update_data(target_user_id=found["user_id"], target_name=found["first_name"])
    await message.answer(
        f"🪙 Выдача токенов для <b>{found['first_name']}</b> (текущий баланс: {found.get('zenotoken', 0)})\n\n"
        f"Введите количество ZenoToken (можно отрицательное для снятия):",
        parse_mode=ParseMode.HTML,
        reply_markup=admin_cancel_keyboard()
    )


# Quick give from find profile
@router.callback_query(F.data.startswith("admin:give_to:"))
async def cb_give_to(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    uid = int(callback.data.split(":")[2])
    users = load_users()
    found = users.get(str(uid))
    if not found:
        await callback.answer("Пользователь не найден", show_alert=True)
        return
    await state.set_state(AdminStates.waiting_give_amount)
    await state.update_data(target_user_id=uid, target_name=found["first_name"])
    await callback.message.edit_text(
        f"🪙 Выдача токенов для <b>{found['first_name']}</b> (баланс: {found.get('zenotoken', 0)})\n\n"
        f"Введите количество ZenoToken:",
        parse_mode=ParseMode.HTML,
        reply_markup=admin_cancel_keyboard()
    )
    await callback.answer()


# ─── FSM: Give tokens — step 2 (amount) ─────────────────────────────────────

@router.message(AdminStates.waiting_give_amount)
async def fsm_give_amount(message: Message, state: FSMContext, bot: Bot):
    if message.from_user.id != ADMIN_ID:
        return
    data = await state.get_data()
    target_id = data["target_user_id"]
    target_name = data["target_name"]

    try:
        amount = int(message.text.strip())
    except ValueError:
        await message.answer(
            "❌ Введите целое число (например: 100 или -50)",
            reply_markup=admin_cancel_keyboard()
        )
        return

    new_balance = give_tokens(target_id, amount)
    if new_balance == -1:
        await message.answer("❌ Пользователь не найден в базе.")
        await state.clear()
        return

    await state.clear()

    # Notify target user
    try:
        sign = "+" if amount >= 0 else ""
        await bot.send_message(
            chat_id=target_id,
            text=(
                f"🪙 <b>Вам начислены ZenoToken!</b>\n\n"
                f"{sign}{amount} ZenoToken\n"
                f"Новый баланс: <b>{new_balance} ZenoToken</b>"
            ),
            parse_mode=ParseMode.HTML
        )
        notified = "✅ Пользователь уведомлён."
    except Exception:
        notified = "⚠️ Не удалось уведомить пользователя."

    await message.answer(
        f"🪙 <b>Готово!</b>\n\n"
        f"Пользователь: <b>{target_name}</b>\n"
        f"Начислено: <b>{'+' if amount >= 0 else ''}{amount}</b> ZenoToken\n"
        f"Новый баланс: <b>{new_balance}</b> ZenoToken\n\n"
        f"{notified}",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ В панель", callback_data="admin:back")]
        ])
    )


# ─── Callbacks: model / role / temp / settings ───────────────────────────────

# ─── Callbacks: communication style ──────────────────────────────────────────

@router.callback_query(F.data == "style:menu")
async def cb_style_menu(callback: CallbackQuery, bot: Bot):
    session = get_session(callback.from_user.id)
    current = session.get("style", "calm")
    styles_text = "\n".join(
        f"{s['emoji']} <b>{s['name']}</b> — {s['description']}"
        for s in STYLES.values()
    )
    await bot.send_message(
        chat_id=callback.message.chat.id,
        text=(
            f"🗣 <b>Стиль общения нейросети</b>\n\n"
            f"Выбери, как именно ИИ будет с тобой общаться:\n\n"
            f"{styles_text}\n\n"
            f"👇 Выбери стиль:"
        ),
        parse_mode=ParseMode.HTML,
        reply_markup=styles_keyboard(current),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("style:"))
async def cb_style(callback: CallbackQuery):
    style_key = callback.data.split(":", 1)[1]
    if style_key == "menu" or style_key not in STYLES:
        await callback.answer()
        return
    session = get_session(callback.from_user.id)
    session["style"] = style_key
    session["history"] = []  # reset history so new style applies cleanly
    style = STYLES[style_key]
    await callback.message.edit_text(
        f"{style['emoji']} <b>Стиль общения изменён: {style['name']}</b>\n\n"
        f"<i>{style['description']}</i>\n\n"
        f"История диалога сброшена, чтобы стиль применился сразу.\n\n"
        f"👇 Хочешь поменять ещё раз?",
        parse_mode=ParseMode.HTML,
        reply_markup=styles_keyboard(style_key),
    )
    await callback.answer(f"Стиль: {style['emoji']} {style['name']}")


@router.callback_query(F.data.startswith("mfilter:"))
async def cb_mfilter(callback: CallbackQuery):
    filter_mode = callback.data.split(":")[1]
    session = get_session(callback.from_user.id)
    session["models_filter"] = filter_mode
    await callback.message.edit_reply_markup(
        reply_markup=models_keyboard(session["model"], filter_mode)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("model:"))
async def cb_model(callback: CallbackQuery):
    model_key = callback.data.split(":")[1]
    model = MODELS[model_key]

    if not is_model_available(model):
        await callback.answer(
            "Эта модель временно скрыта: для её провайдера не настроен API-ключ.",
            show_alert=True,
        )
        return

    # Check if model is restricted (admin can always select any model, unless in test mode)
    if not is_admin(callback.from_user.id):
        r = get_model_restriction(model_key)
        if r:
            if r["type"] == "temporary":
                until_str = datetime.fromtimestamp(r["until"]).strftime("%d.%m.%Y %H:%M")
                notice = f"⏳ Временно недоступна до <b>{until_str}</b>"
            else:
                notice = "🔴 Модель недоступна"
            await callback.answer(
                f"❌ {model['name']} недоступна\n\nПричина: {r['reason']}",
                show_alert=True
            )
            return

    session = get_session(callback.from_user.id)
    session["model"] = model_key
    filter_mode = session.get("models_filter", "all")

    price = get_model_price(model_key)
    price_line = f"\n\n🪙 <b>Стоимость запроса: {price} ZenoToken</b>" if price > 0 else ""

    try:
        await callback.message.edit_text(
            f"{pe('5370893703575511656', '✅')} Модель: {model['emoji_html']} <b>{model['name']}</b>\n\n"
            f"<i>{model['description']}</i>{price_line}",
            parse_mode=ParseMode.HTML,
            reply_markup=models_keyboard(model_key, filter_mode)
        )
    except TelegramBadRequest:
        pass
    await callback.answer(f"Выбрана: {model['name']}")


@router.callback_query(F.data.startswith("role:"))
async def cb_role(callback: CallbackQuery):
    role_key = callback.data.split(":")[1]
    session = get_session(callback.from_user.id)
    session["role"] = role_key
    session["history"] = []
    role = ROLES[role_key]
    await callback.message.edit_text(
        f"{pe('5370893703575511656', '✅')} Роль: {role['emoji_html']} <b>{role['name']}</b>\n\n<i>История очищена для применения новой роли.</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=roles_keyboard(role_key)
    )
    await callback.answer(f"Роль: {role['name']}")


@router.callback_query(F.data.startswith("temp:"))
async def cb_temp(callback: CallbackQuery):
    action = callback.data.split(":")[1]
    session = get_session(callback.from_user.id)
    if action == "up":
        session["temperature"] = min(1.0, round(session["temperature"] + 0.1, 1))
    elif action == "down":
        session["temperature"] = max(0.0, round(session["temperature"] - 0.1, 1))
    await callback.message.edit_reply_markup(reply_markup=settings_keyboard(callback.from_user.id))
    await callback.answer(f"Температура: {session['temperature']:.1f}")


@router.callback_query(F.data == "settings:close")
async def cb_settings_close(callback: CallbackQuery):
    await callback.message.delete()
    await callback.answer()


@router.callback_query(F.data == "noop")
async def cb_noop(callback: CallbackQuery):
    await callback.answer()


@router.callback_query(F.data == "open:model")
async def cb_open_model(callback: CallbackQuery):
    session = get_session(callback.from_user.id)
    filter_mode = session.get("models_filter", "all")
    await callback.message.answer(
        f"{pe('5258093637450866522', '🤖')} <b>Выберите модель ИИ:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=models_keyboard(session["model"], filter_mode)
    )
    await callback.answer()


# ─── /img — Image generation ──────────────────────────────────────────────────

IMG_WELCOME_TEXT = (
    "🎨 <b>Генератор изображений</b>\n\n"
    "Я создам картинку по вашему описанию с помощью нейросети Pollinations AI.\n\n"
    "✦ Чем подробнее описание — тем лучше результат.\n"
    "✦ Можно писать на русском или английском."
)


@router.message(Command("img"))
@router.message(F.text == "🎨 Нейро-фото")
@router.message(F.text == "✨ Генерация")
async def cmd_img(message: Message, state: FSMContext):
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🖼 Фото", callback_data="img:mode:photo", style="primary"),
         InlineKeyboardButton(text="🎬 Видео", callback_data="img:mode:video", style="success")],
    ])
    text = (
        "✨ <b>Генерация по описанию</b>\n\n"
        "Выберите, что создать:\n"
        "🖼 <b>Фото</b> — изображение по вашему описанию.\n"
        "🎬 <b>Видео</b> — бесплатный короткий клип с плавной анимацией.\n\n"
        f"🖼 Фото: {('🆓 Бесплатно' if get_img_gen_price() == 0 else f'{get_img_gen_price()} 🎟 за генерацию')}\n"
        "🎬 Видео: 🆓 <b>Бесплатно</b>"
        + img_gen_info_text(message.from_user.id)
    )
    await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=kb)


@router.callback_query(F.data.startswith("img:mode:"))
async def cb_img_mode(callback: CallbackQuery, state: FSMContext):
    media_type = callback.data.split(":")[-1]
    await state.update_data(media_type=media_type, img_msg_id=callback.message.message_id)
    await state.set_state(ImgStates.waiting_prompt)
    title = "фото" if media_type == "photo" else "видео"
    await callback.message.edit_text(
        f"✏️ <b>Опишите {title}</b>\n\n"
        "Чем подробнее описание — тем лучше результат.\n\n"
        "<i>Пример: закат над горами, лёгкое движение облаков, яркие цвета</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="img:cancel", style="danger")]
        ])
    )
    await callback.answer()


@router.callback_query(F.data == "img:prompt")
async def cb_img_prompt(callback: CallbackQuery, state: FSMContext):
    await state.update_data(media_type="photo")
    await state.set_state(ImgStates.waiting_prompt)
    await state.update_data(img_msg_id=callback.message.message_id)
    await callback.message.edit_text(
        "✏️ <b>Что рисуем?</b>\n\n"
        "Напишите описание картинки — чем подробнее, тем лучше результат.\n\n"
        "<i>Пример: закат над горами, в стиле аниме, яркие цвета</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="img:cancel", style="danger")]
        ])
    )
    await callback.answer()


@router.message(ImgStates.waiting_prompt, F.text)
async def fsm_img_prompt(message: Message, state: FSMContext):
    prompt = message.text.strip()
    data = await state.get_data()
    await state.update_data(current_prompt=prompt)
    await state.set_state(ImgStates.has_prompt)

    try:
        await message.delete()
    except TelegramBadRequest:
        pass

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=("🎬 Создать видео" if data.get("media_type") == "video" else "🖼 Создать фото"),
            callback_data="img:generate", style="success"
        )],
        [InlineKeyboardButton(text="✏️ Промт", callback_data="img:prompt")],
    ])
    text = (
        f"{IMG_WELCOME_TEXT}\n\n"
        f"<b>Ваш промт:</b>\n<i>{prompt}</i>"
    )

    img_msg_id = data.get("img_msg_id")
    if img_msg_id:
        try:
            await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=img_msg_id,
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=kb
            )
            return
        except TelegramBadRequest:
            pass
    await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=kb)


async def translate_prompt(prompt: str) -> str:
    """Translate prompt to English using Groq for better image generation results."""
    payload = {
        "model": "openai/gpt-oss-20b",
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a prompt translator for image generation. "
                    "Translate the user's description into a detailed English image generation prompt. "
                    "Keep all visual details. Output ONLY the English prompt, nothing else."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.3,
        "max_tokens": 300,
    }
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    async with aiohttp.ClientSession() as session:
        async with session.post(
            GROQ_API_URL, json=payload, headers=headers,
            timeout=aiohttp.ClientTimeout(total=15)
        ) as resp:
            data = await resp.json()
            return data["choices"][0]["message"]["content"].strip()


async def generate_pollinations_image(prompt: str) -> bytes:
    """Generate an image through Pollinations' public image endpoint."""
    encoded_prompt = url_quote(prompt, safe="")
    image_url = (
        f"https://image.pollinations.ai/prompt/{encoded_prompt}"
        "?width=512&height=512&nologo=true"
    )
    async with aiohttp.ClientSession() as session:
        async with session.get(
            image_url,
            headers={"User-Agent": "ZenoAI:1.0:telegram-bot"},
            timeout=aiohttp.ClientTimeout(total=90),
        ) as response:
            if response.status != 200:
                body = await response.text()
                raise ValueError(
                    f"Pollinations HTTP {response.status}: {body[:200]}"
                )
            image_bytes = await response.read()
            if not image_bytes:
                raise ValueError("Pollinations: пустое изображение")
            return image_bytes


async def render_free_video(image_bytes: bytes) -> bytes:
    """Turn a generated image into a short animated MP4 without paid APIs."""
    temp_dir = tempfile.mkdtemp(prefix="zeno-video-")
    image_path = os.path.join(temp_dir, "source.png")
    video_path = os.path.join(temp_dir, "result.mp4")
    try:
        with open(image_path, "wb") as image_file:
            image_file.write(image_bytes)
        process = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-loglevel", "error",
            "-loop", "1", "-i", image_path,
            "-vf",
            "scale=720:720:force_original_aspect_ratio=decrease,"
            "pad=720:720:(ow-iw)/2:(oh-ih)/2,"
            "zoompan=z='min(zoom+0.0015,1.08)':d=150:s=720x720:fps=25,"
            "format=yuv420p",
            "-t", "6", "-an", "-movflags", "+faststart", video_path,
        )
        return_code = await process.wait()
        if return_code != 0 or not os.path.exists(video_path):
            raise ValueError("Не удалось собрать видео")
        with open(video_path, "rb") as video_file:
            return video_file.read()
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


@router.callback_query(ImgStates.has_prompt, F.data == "img:generate")
async def cb_img_generate(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    data = await state.get_data()
    prompt = data.get("current_prompt", "")
    media_type = data.get("media_type", "photo")
    is_video = media_type == "video"

    # Reserve free_gens before starting the long-running generation. This makes
    # two quick clicks unable to start two jobs while paying for only one.
    price = 0 if is_video else get_img_gen_price()
    generation_charged = False
    generation_delivered = False
    if price > 0 and not is_admin(user_id) and not is_vip(user_id):
        gens = get_user_free_gens(user_id)
        if gens < price:
            await callback.answer(
                f"❌ Недостаточно генераций! Нужно {price} 🎟, у тебя {gens}. Открой кейс — там можно выиграть генерации.",
                show_alert=True,
            )
            return

    await callback.answer("🎨 Создаю...")

    if price > 0 and not is_admin(user_id) and not is_vip(user_id):
        charged, remaining = deduct_user_free_gens(user_id, price)
        if not charged:
            await callback.message.answer(
                f"❌ Недостаточно генераций! Нужно {price} 🎟, у тебя {remaining}.",
            )
            return
        generation_charged = True

    try:
        await callback.message.edit_text(
            f"⏳ <b>Готовлю {'видео' if is_video else 'фото'} по вашему описанию...</b>\n\n<i>{prompt}</i>",
            parse_mode=ParseMode.HTML
        )

        # Send the user's prompt unchanged. Rewriting it through another model
        # can silently replace important subjects, details, and style choices.
        image_prompt = prompt
        logger.info(f"Img prompt used unchanged: '{image_prompt}'")

        await callback.message.edit_text(
            f"{'🎬' if is_video else '🎨'} <b>Готовлю медиа...</b>\n\n<i>{prompt}</i>",
            parse_mode=ParseMode.HTML
        )

        # Pollinations is fast and does not require a provider key. Keep
        # Stable Horde as a fallback because public services can rate-limit.
        try:
            img_bytes = await generate_pollinations_image(image_prompt)
            logger.info("Image generated through Pollinations")
        except Exception as pollinations_error:
            logger.warning(f"Pollinations image generation failed: {pollinations_error}")

            HORDE_URL = "https://stablehorde.net/api/v2"
            horde_headers = {
                "apikey": "0000000000",
                "Content-Type": "application/json",
                "Client-Agent": "ZenoAI:1.0:telegram-bot",
            }
            horde_payload = {
                "prompt": image_prompt,
                "params": {
                    "width": 512,
                    "height": 512,
                    "steps": 20,
                    "n": 1,
                    "sampler_name": "k_euler_a",
                    "cfg_scale": 7.5,
                },
                "nsfw": False,
                "shared": True,
                "trusted_workers": False,
                "slow_workers": True,
            }

            async with aiohttp.ClientSession() as http:
                async with http.post(
                    f"{HORDE_URL}/generate/async",
                    json=horde_payload,
                    headers=horde_headers,
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as resp:
                    if resp.status != 202:
                        body = await resp.text()
                        raise ValueError(f"Horde submit HTTP {resp.status}: {body[:200]}")
                    submit_data = await resp.json()
                    job_id = submit_data["id"]
                    logger.info(f"Horde job submitted: {job_id}")

                for tick in range(48):
                    await asyncio.sleep(5)
                    async with http.get(
                        f"{HORDE_URL}/generate/check/{job_id}",
                        headers=horde_headers,
                        timeout=aiohttp.ClientTimeout(total=10),
                    ) as resp:
                        check = await resp.json()

                    if check.get("faulted"):
                        raise ValueError("Horde: генерация не удалась")
                    if check.get("done"):
                        break

                    wait_time = check.get("wait_time", "?")
                    queue_pos = check.get("queue_position", "?")
                    try:
                        await callback.message.edit_text(
                            f"🎨 <b>Рисую...</b>\n\n"
                            f"<i>{prompt}</i>\n\n"
                            f"⏱ ~{wait_time}с · позиция в очереди: {queue_pos}",
                            parse_mode=ParseMode.HTML,
                        )
                    except TelegramBadRequest:
                        pass
                else:
                    raise ValueError("Horde: таймаут (4 минуты)")

                async with http.get(
                    f"{HORDE_URL}/generate/status/{job_id}",
                    headers=horde_headers,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    result = await resp.json()

                generations = result.get("generations", [])
                if not generations:
                    raise ValueError("Horde: нет результата")
                gen = generations[0]
                img_field = gen.get("img", "")
                if not img_field:
                    raise ValueError("Horde: пустое изображение")

                if gen.get("r2") or img_field.startswith("http"):
                    async with http.get(
                        img_field,
                        timeout=aiohttp.ClientTimeout(total=30),
                    ) as img_resp:
                        if img_resp.status != 200:
                            raise ValueError(
                                f"Horde: не удалось скачать изображение ({img_resp.status})"
                            )
                        img_bytes = await img_resp.read()
                else:
                    img_bytes = base64.b64decode(img_field)

        if is_video:
            await callback.message.edit_text(
                f"🎬 <b>Анимирую видео...</b>\n\n<i>{prompt}</i>",
                parse_mode=ParseMode.HTML,
            )
            video_bytes = await render_free_video(img_bytes)
            await callback.message.answer_video(
                BufferedInputFile(video_bytes, filename="video.mp4"),
                caption=f"🎬 <i>{prompt}</i>\n\n🆓 Бесплатная генерация",
                parse_mode=ParseMode.HTML,
            )
        else:
            photo = BufferedInputFile(img_bytes, filename="image.png")
            await callback.message.answer_photo(
                photo,
                caption=f"🎨 <i>{prompt}</i>",
                parse_mode=ParseMode.HTML,
            )
        generation_delivered = True

        kb_menu = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=("🎬 Создать ещё видео" if is_video else "🖼 Создать ещё фото"),
                callback_data="img:generate", style="success"
            )],
            [InlineKeyboardButton(text="🔁 Выбрать фото/видео", callback_data="img:home")],
            [InlineKeyboardButton(text="✏️ Изменить промт", callback_data="img:prompt", style="primary")],
        ])
        await callback.message.edit_text(
            f"{'🎬 Видео готово' if is_video else IMG_WELCOME_TEXT}{img_gen_info_text(user_id)}\n\n"
            f"<b>Последний промт:</b>\n<i>{prompt}</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=kb_menu
        )

    except Exception as e:
        logger.error(f"Image gen error: {e}")
        if generation_charged and not generation_delivered:
            refunded, balance = refund_user_free_gens(user_id, price)
            if refunded:
                logger.info(
                    "Image generation reservation refunded for user %s; balance=%s",
                    user_id,
                    balance,
                )
            else:
                logger.error(
                    "Could not refund image generation reservation for user %s",
                    user_id,
                )
        kb_err = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Попробовать снова", callback_data="img:generate", style="primary")],
            [InlineKeyboardButton(text="✏️ Новый промт", callback_data="img:prompt")],
        ])
        await callback.message.edit_text(
            f"❌ <b>Не удалось создать {'видео' if is_video else 'фото'}.</b>\n\n"
            "Сервис генерации временно недоступен. Попробуйте позже или измените описание.",
            parse_mode=ParseMode.HTML,
            reply_markup=kb_err
        )


@router.callback_query(F.data == "img:cancel")
async def cb_img_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Промт", callback_data="img:prompt")]
    ])
    await callback.message.edit_text(IMG_WELCOME_TEXT, parse_mode=ParseMode.HTML, reply_markup=kb)
    await callback.answer("Отменено")


@router.callback_query(F.data == "img:home")
async def cb_img_home(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "✨ <b>Генерация по описанию</b>\n\n"
        "🖼 Фото — по текущей цене генерации.\n"
        "🎬 Видео — бесплатно.",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🖼 Фото", callback_data="img:mode:photo", style="primary"),
             InlineKeyboardButton(text="🎬 Видео", callback_data="img:mode:video", style="success")],
        ]),
    )
    await callback.answer()


# ─── Groq API ─────────────────────────────────────────────────────────────────

async def call_ai(session: dict, user_message: str) -> str:
    model_cfg = MODELS[session["model"]]
    model_id = model_cfg["model_id"]

    today = datetime.now().strftime("%d.%m.%Y")
    style_key = session.get("style", "calm")
    style_instruction = STYLES[style_key]["instruction"]
    mood_instruction = detect_mood(user_message)
    system_prompt = (
        f"Сегодняшняя дата: {today}. Используй эту дату как актуальную текущую дату и год, "
        f"а не дату из своих обучающих данных.\n\n"
        f"{SYSTEM_PROMPTS[session['role']]}\n\n"
        f"СТИЛЬ ОБЩЕНИЯ: {style_instruction}\n\n"
        f"СИГНАЛ НАСТРОЕНИЯ В ПОСЛЕДНЕМ СООБЩЕНИИ: {mood_instruction}\n\n"
        f"{COMMON_INSTRUCTIONS}"
    )

    history_snapshot = list(session["history"])
    session["history"].append({"role": "user", "content": user_message})
    if len(session["history"]) > 20:
        session["history"] = session["history"][-20:]

    messages = [{"role": "system", "content": system_prompt}] + session["history"]

    payload = {
        "model": model_id,
        "messages": messages,
        "temperature": session["temperature"],
        "max_tokens": model_cfg.get("max_tokens", 2048),
    }
    if model_cfg.get("no_thinking"):
        payload["thinking"] = {"type": "disabled"}
    provider = model_cfg.get("provider", "groq")
    if provider == "sambanova":
        api_url = SAMBANOVA_API_URL
        api_key = SAMBANOVA_API_KEY
    elif provider == "openrouter":
        api_url = OPENROUTER_API_URL
        api_key = OPENROUTER_API_KEY
    else:
        api_url = GROQ_API_URL
        api_key = GROQ_API_KEY
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    try:
        async with aiohttp.ClientSession() as http:
            async with http.post(api_url, json=payload, headers=headers) as resp:
                data = await resp.json()
        if "choices" not in data:
            err = data.get("error", {})
            code = err.get("code") or data.get("code")
            error_msg = err.get("message", json.dumps(data, ensure_ascii=False))
            # 429 or "high demand" / "overloaded" messages → rate limit
            if code == 429 or any(kw in error_msg.lower() for kw in ("high demand", "overloaded", "try again later", "rate limit")):
                raise RateLimitError(MODELS[session["model"]]["name"])
            raise ValueError(error_msg)
        reply = data["choices"][0]["message"]["content"]
        # compound-beta may return None content when it only emitted tool calls
        # without a final text — treat as a retryable error so history stays clean
        if reply is None:
            raise ValueError("Модель не вернула текстовый ответ. Попробуйте ещё раз или смените модель (/model).")
        # Strip chain-of-thought thinking blocks (DeepSeek R1, Qwen3, Groq Compound, etc.)
        reply = re.sub(r"<think>.*?</think>", "", reply, flags=re.DOTALL).strip()
        session["history"].append({"role": "assistant", "content": reply})
        return reply
    except Exception:
        # Restore history to pre-call state so broken exchange doesn't poison context
        session["history"] = history_snapshot
        raise


def strip_tg_emoji(text: str) -> str:
    """Strip <tg-emoji> tags keeping the fallback character (used when DOCUMENT_INVALID)."""
    return re.sub(r'<tg-emoji[^>]*>(.*?)</tg-emoji>', r'\1', text, flags=re.DOTALL)


def escape_md(text: str) -> str:
    chars = r"_*[]()~`>#+-=|{}.!"
    for ch in chars:
        text = text.replace(ch, f"\\{ch}")
    return text


# ─── Vision: image analysis via OpenRouter ────────────────────────────────────

# Free vision models tried in order until one succeeds
# nemotron confirmed working with base64; gemma as fallback
VISION_MODELS = [
    "nvidia/nemotron-nano-12b-v2-vl:free",
    "google/gemma-4-31b-it:free",
    "google/gemma-4-26b-a4b-it:free",
]

VISION_INTRO = (
    "👁 <b>Анализ изображений</b>\n\n"
    "Просто отправьте мне любое фото — я подробно расскажу, что на нём.\n\n"
    "Можно написать подпись к фото с вопросом, например: <i>«что это за растение?»</i>"
)


async def describe_image(image_bytes: bytes, user_question: str | None = None) -> str:
    """Try each free vision model until one returns a result (uses base64)."""
    question = user_question or "Подробно опиши всё, что видишь на этом изображении. Отвечай на русском языке."
    b64 = base64.b64encode(image_bytes).decode()
    data_url = f"data:image/jpeg;base64,{b64}"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://t.me",
    }
    last_error = "no models available"
    for model in VISION_MODELS:
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": data_url}},
                        {"type": "text", "text": question},
                    ],
                }
            ],
            "temperature": 0.4,
            "max_tokens": 1024,
        }
        try:
            async with aiohttp.ClientSession() as http:
                async with http.post(
                    OPENROUTER_API_URL, json=payload, headers=headers,
                    timeout=aiohttp.ClientTimeout(total=40)
                ) as resp:
                    data = await resp.json()
                    if resp.status == 200:
                        content = data["choices"][0]["message"]["content"]
                        if content and content.strip():
                            logger.info(f"Vision answered by {model}")
                            return content.strip()
                    err_msg = data.get("error", {}).get("message", f"HTTP {resp.status}")
                    logger.warning(f"Vision model {model} failed: {err_msg}")
                    last_error = err_msg
        except Exception as e:
            logger.warning(f"Vision model {model} exception: {e}")
            last_error = str(e)
    raise ValueError(last_error)


@router.message(Command("vision"))
async def cmd_vision(message: Message):
    await message.answer(VISION_INTRO, parse_mode=ParseMode.HTML)


@router.message(F.photo)
async def handle_photo(message: Message):
    """Analyze any photo sent to the bot using free OpenRouter vision models."""
    user_id = message.from_user.id
    touch_user(user_id, message.from_user.first_name, message.from_user.username or "")

    thinking = await message.answer("👁 <i>Смотрю на фото...</i>", parse_mode=ParseMode.HTML)

    try:
        # Download the photo and encode as base64
        photo = message.photo[-1]
        file = await message.bot.get_file(photo.file_id)
        bio = BytesIO()
        await message.bot.download_file(file.file_path, bio)
        image_bytes = bio.getvalue()

        # Use caption as the question if user wrote one
        user_question = None
        if message.caption:
            cap = message.caption.strip()
            user_question = f"{cap}\n\nОтвечай на русском языке."

        description = await describe_image(image_bytes, user_question)
        # Edit the thinking message instead of delete+answer
        # so a network hiccup on answer() can't leave the user with nothing
        try:
            await thinking.edit_text(description)
        except TelegramBadRequest:
            # Message too long or other edit issue — send fresh
            await thinking.delete()
            for chunk in [description[i:i+4096] for i in range(0, len(description), 4096)]:
                await message.answer(chunk)

    except Exception as e:
        logger.error(f"Vision error for user {user_id}: {e}")
        try:
            await thinking.edit_text(
                "❌ <b>Не удалось проанализировать фото.</b>\n\nПопробуйте ещё раз.",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            await message.answer("❌ Не удалось проанализировать фото. Попробуйте ещё раз.")


# ─── Cases: FSM message handlers (must be before generic F.text handler) ─────

@router.message(CaseStates.waiting_case_name)
async def fsm_case_name(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    name = message.text.strip()
    if not name:
        await message.answer("❌ Название не может быть пустым. Введите название кейса:")
        return
    data = await state.get_data()
    # Edit mode: rename existing case
    if data.get("edit_case_field") == "name":
        case_id = data["edit_case_id"]
        update_case(case_id, name=name)
        await state.clear()
        cases_data = load_cases()
        c = cases_data.get(case_id, {})
        await message.answer(
            f"✅ Название обновлено: <b>{name}</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=admin_case_actions_keyboard(case_id) if c else admin_cases_keyboard(),
        )
        return
    # Create mode: step 1/3
    await state.update_data(case_name=name)
    await state.set_state(CaseStates.waiting_case_total)
    await message.answer(
        f"🎁 <b>Создание кейса: «{name}»</b>\n\nШаг 2/3: Введите <b>общее количество</b> кейсов (целое число):",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="admin:cases")]
        ]),
    )


@router.message(CaseStates.waiting_case_total)
async def fsm_case_total(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        total = int(message.text.strip())
        if total <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите целое положительное число:")
        return
    data = await state.get_data()
    # Edit mode: update total_count
    if data.get("edit_case_field") == "total_count":
        case_id = data["edit_case_id"]
        update_case(case_id, total_count=total)
        await state.clear()
        cases_data = load_cases()
        c = cases_data.get(case_id, {})
        await message.answer(
            f"✅ Общее количество обновлено: <b>{total}</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=admin_case_actions_keyboard(case_id) if c else admin_cases_keyboard(),
        )
        return
    # Create mode: step 2/3
    await state.update_data(case_total=total)
    await state.set_state(CaseStates.waiting_case_limit)
    await message.answer(
        f"🎁 <b>Создание кейса: «{data['case_name']}»</b>\n\nШаг 3/3: Введите <b>лимит открытий на одного пользователя</b>:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="admin:cases", style="danger")]
        ]),
    )


@router.message(CaseStates.waiting_case_limit)
async def fsm_case_limit(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        limit = int(message.text.strip())
        if limit <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите целое положительное число:")
        return
    data = await state.get_data()
    # Edit mode: update per_user_limit
    if data.get("edit_case_field") == "per_user_limit":
        case_id = data["edit_case_id"]
        update_case(case_id, per_user_limit=limit)
        await state.clear()
        cases_data = load_cases()
        c = cases_data.get(case_id, {})
        await message.answer(
            f"✅ Лимит на пользователя обновлён: <b>{limit}</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=admin_case_actions_keyboard(case_id) if c else admin_cases_keyboard(),
        )
        return
    # Create mode: step 3/3 — finish creation
    await state.clear()
    case = create_case(data["case_name"], data["case_total"], limit)
    await message.answer(
        f"✅ <b>Кейс создан!</b>\n\n"
        f"🎁 Название: <b>{case['name']}</b>\n"
        f"📦 Количество: <b>{case['total_count']}</b>\n"
        f"👤 Лимит на пользователя: <b>{case['per_user_limit']}</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=admin_cases_keyboard(),
    )


# ─── Internet search ──────────────────────────────────────────────────────────

SEARCH_TRIGGER = "найди в интернете"
SEARCH_MAX_RESULTS = 5
SEARCH_MAX_QUERY_LENGTH = 300
SEARCH_RESULT_CHARS = 900
SEARCH_STOP_WORDS = {
    "а", "без", "бы", "был", "быть", "в", "вам", "вас", "ведь", "во", "вот", "все",
    "вы", "где", "да", "для", "до", "ее", "если", "есть", "же", "за", "и", "из",
    "или", "как", "к", "когда", "кто", "ли", "мне", "мы", "на", "над", "не", "него",
    "нет", "ни", "но", "о", "об", "он", "она", "они", "по", "под", "при", "про",
    "с", "со", "так", "то", "у", "уже", "что", "чем", "это", "эти", "этот", "я",
    "the", "and", "for", "from", "how", "what", "when", "where",
}


def _clean_search_text(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _decode_search_url(value: str) -> str:
    """Turn Bing/DDG tracking links into the actual result URL."""
    value = value.strip()
    if value.startswith("//"):
        value = f"https:{value}"

    try:
        query = parse_qs(urlparse(value).query)
        for key in ("uddg", "u"):
            target = query.get(key, [None])[0]
            if not target:
                continue
            target = unquote(target)
            if key == "u" and target.startswith("a1"):
                encoded = target[2:]
                encoded += "=" * (-len(encoded) % 4)
                target = base64.urlsafe_b64decode(encoded).decode("utf-8", "ignore")
            if target.startswith(("http://", "https://")):
                return target
    except Exception:
        # Keep the original URL if a provider changes its tracking format.
        pass
    return value


def _search_tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-zа-яё0-9]{3,}", value.casefold())
        if token not in SEARCH_STOP_WORDS
    }


def _is_relevant_search_result(query: str, result: dict[str, str]) -> bool:
    """Reject valid-looking provider pages that are unrelated to the query."""
    query_tokens = _search_tokens(query)
    if not query_tokens:
        return True
    result_text = f"{result['title']} {result['snippet']} {result['url']}"
    return bool(query_tokens & _search_tokens(result_text))


def _parse_bing_rss(page: str) -> list[dict[str, str]]:
    """Parse Bing's small RSS fallback, which survives HTML markup changes."""
    try:
        root = ET.fromstring(page)
    except ET.ParseError:
        return []

    results = []
    for item in root.findall(".//item"):
        title = _clean_search_text(item.findtext("title") or "")
        url = _decode_search_url(item.findtext("link") or "")
        snippet = _clean_search_text(item.findtext("description") or "")
        if title and url.startswith(("http://", "https://")):
            results.append({
                "title": title,
                "url": url,
                "snippet": snippet[:SEARCH_RESULT_CHARS],
            })
    return results


class SearchResultsParser(HTMLParser):
    """Parse the small result blocks used by Bing and DuckDuckGo HTML pages."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.results: list[dict[str, str]] = []
        self.current: dict[str, str] | None = None
        self.block_tag: str | None = None
        self.block_depth = 0
        self.capture: str | None = None
        self.capture_tag: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        attrs_dict = dict(attrs)
        classes = set((attrs_dict.get("class") or "").split())

        if self.current is None:
            if tag == "li" and "b_algo" in classes:
                self.current = {"title": "", "url": "", "snippet": ""}
                self.block_tag = tag
                self.block_depth = 1
                return
            if tag == "div" and "result" in classes:
                self.current = {"title": "", "url": "", "snippet": ""}
                self.block_tag = tag
                self.block_depth = 1
                return

        if self.current is None:
            return

        self.block_depth += 1
        href = attrs_dict.get("href") or ""
        if tag == "a" and href and not self.current["url"]:
            if "result__a" in classes or self.block_tag == "li":
                self.current["url"] = href

        if tag == "h2" and self.block_tag == "li":
            self.capture = "title"
            self.capture_tag = tag
        elif tag == "a" and "result__a" in classes:
            self.capture = "title"
            self.capture_tag = tag
        elif "result__snippet" in classes:
            self.capture = "snippet"
            self.capture_tag = tag
        elif tag == "p" and self.block_tag == "li":
            self.capture = "snippet"
            self.capture_tag = tag

    def handle_data(self, data: str):
        if self.current is not None and self.capture:
            self.current[self.capture] += data

    def handle_endtag(self, tag: str):
        if self.current is None:
            return
        if tag == self.capture_tag:
            self.capture = None
            self.capture_tag = None
        self.block_depth -= 1
        if self.block_depth <= 0 and tag == self.block_tag:
            self._finish_current()

    def _finish_current(self):
        if self.current:
            title = _clean_search_text(self.current["title"])
            url = _decode_search_url(self.current["url"])
            snippet = _clean_search_text(self.current["snippet"])
            if title and url.startswith(("http://", "https://")):
                self.results.append({
                    "title": title,
                    "url": url,
                    "snippet": snippet[:SEARCH_RESULT_CHARS],
                })
        self.current = None
        self.block_tag = None
        self.block_depth = 0
        self.capture = None
        self.capture_tag = None


async def search_web(query: str) -> list[dict[str, str]]:
    """Fetch current web results without requiring another API key."""
    encoded_query = url_quote(query, safe="")
    search_urls = (
        # Explicit Russian market parameters avoid unrelated regional results.
        f"https://www.bing.com/search?q={encoded_query}&count=10&setlang=ru&cc=ru&mkt=ru-RU&form=QBLH",
        f"https://www.bing.com/search?q={encoded_query}&count=10&setlang=ru&cc=ru",
        f"https://www.bing.com/search?format=rss&q={encoded_query}",
        f"https://html.duckduckgo.com/html/?q={encoded_query}&kl=ru-ru",
    )
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "Chrome/124.0 Safari/537.36"
        ),
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.7",
    }
    errors = []

    async with aiohttp.ClientSession(headers=headers) as http:
        for search_url in search_urls:
            try:
                async with http.get(
                    search_url,
                    timeout=aiohttp.ClientTimeout(total=12),
                    allow_redirects=True,
                ) as response:
                    if response.status != 200:
                        errors.append(f"HTTP {response.status}")
                        continue
                    page = await response.text(errors="ignore")

                if "<rss" in page[:500].lower():
                    results = _parse_bing_rss(page)
                else:
                    parser = SearchResultsParser()
                    parser.feed(page)
                    results = parser.results
                results = [
                    item for item in results
                    if _is_relevant_search_result(query, item)
                ][:SEARCH_MAX_RESULTS]
                if results:
                    logger.info("Web search returned %s results", len(results))
                    return results
                errors.append("результаты не найдены")
            except Exception as error:
                logger.warning("Web search provider failed: %s", error)
                errors.append(str(error))

    raise ValueError("Сервисы поиска временно не вернули результаты.")


async def summarize_search_results(query: str, results: list[dict[str, str]]) -> str:
    """Summarize search snippets with the existing Groq key and model."""
    search_summary_models = ("openai/gpt-oss-20b", "openai/gpt-oss-120b")
    sources = "\n\n".join(
        f"[{index}] {item['title']}\n{item['snippet'] or 'Описание отсутствует.'}\n"
        f"Источник: {item['url']}"
        for index, item in enumerate(results, start=1)
    )
    request_payload = {
        "messages": [
            {
                "role": "system",
                "content": (
                    "Ты живой и понятный редактор кратких ответов на русском языке. "
                    "Отвечай только по данным из источников, но пиши естественно, "
                    "будто коротко объясняешь результат человеку. "
                    "Сделай сжатый ответ до 900 символов: 2–4 коротких абзаца "
                    "или маркированных пункта. Не добавляй ссылки, номера источников, "
                    "служебные пометки и непонятные обозначения. Если данных "
                    "недостаточно, честно скажи об этом."
                ),
            },
            {
                "role": "user",
                "content": f"Запрос: {query}\n\nРезультаты поиска:\n{sources}",
            },
        ],
        "temperature": 0.35,
        "max_tokens": 500,
    }
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }

    summary = ""
    last_error = "Groq не вернул ответ"
    async with aiohttp.ClientSession() as http:
        for model_id in search_summary_models:
            payload = {**request_payload, "model": model_id}
            try:
                async with http.post(
                    GROQ_API_URL,
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=25),
                ) as response:
                    data = await response.json(content_type=None)
            except Exception as error:
                last_error = str(error)
                logger.warning("Search summary model %s failed: %s", model_id, error)
                continue

            if "choices" in data:
                summary = data["choices"][0]["message"].get("content", "").strip()
                if summary:
                    break

            last_error = data.get("error", {}).get("message", "Groq не вернул ответ")
            logger.warning("Search summary model %s failed: %s", model_id, last_error)

    if not summary:
        raise ValueError(last_error)

    # Remove citation artifacts or URLs if the model included them despite the prompt.
    summary = re.sub(r"\[\d+\]", "", summary)
    summary = re.sub(r"\[([^\]]+)\]\(https?://[^)]+\)", r"\1", summary)
    summary = re.sub(r"https?://\S+", "", summary)
    summary = re.sub(r"[ \t]{2,}", " ", summary)
    summary = re.sub(r"\n{3,}", "\n\n", summary).strip()
    return summary[:4090]


async def start_search(message: Message, state: FSMContext):
    await state.set_state(SearchStates.waiting_query)
    await message.answer(
        "🔎 Напиши запрос, который нужно найти в интернете.\n"
        "Например: <i>какая погода будет в Москве завтра</i>",
        parse_mode=ParseMode.HTML,
    )


async def run_search(message: Message, state: FSMContext, query: str):
    query = query.strip()
    await state.clear()
    if not query:
        await message.answer("Напиши сам запрос для поиска.")
        return
    if len(query) > SEARCH_MAX_QUERY_LENGTH:
        await message.answer(
            f"Сделай запрос короче {SEARCH_MAX_QUERY_LENGTH} символов."
        )
        return

    status = await message.answer("🔎 Ищу информацию в интернете…")
    try:
        results = await search_web(query)
        answer = await summarize_search_results(query, results)
        await status.edit_text(answer, parse_mode=None)
    except Exception as error:
        logger.error("Web search error for user %s: %s", message.from_user.id, error)
        await status.edit_text(
            "❌ Не удалось выполнить поиск прямо сейчас.\n"
            "Попробуй изменить запрос и повторить позже."
        )


@router.message(Command("search"))
async def cmd_search(message: Message, state: FSMContext):
    await start_search(message, state)


@router.message(F.text == "🔎 Найди в интернете")
@router.message(F.text == "Найди в интернете")
async def search_button(message: Message, state: FSMContext):
    await start_search(message, state)


@router.message(SearchStates.waiting_query, F.text)
async def fsm_search_query(message: Message, state: FSMContext):
    await run_search(message, state, message.text or "")


# ─── Reminders and message handler ────────────────────────────────────────────

@router.message(Command("reminders"))
async def list_reminders(message: Message):
    reminders = get_user_reminders(message.from_user.id)
    if not reminders:
        await message.answer(
            "📅 У вас пока нет активных напоминаний.\n\n"
            "Пример: «Поставь напоминание завтра в 09:30 позвонить маме»"
        )
        return

    lines = [
        f"• <b>{format_reminder_datetime(reminder['due_at'])}</b> — "
        f"{reminder['text']}  <code>{reminder['id']}</code>"
        for reminder in reminders
    ]
    await message.answer(
        "📅 <b>Ваши напоминания (время МСК):</b>\n\n"
        + "\n".join(lines)
        + "\n\nУдалить: <code>/cancel_reminder ID</code>",
        parse_mode=ParseMode.HTML,
    )


@router.message(Command("cancel_reminder"))
async def cancel_reminder(message: Message):
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            "Укажите ID напоминания:\n"
            "<code>/cancel_reminder ID</code>\n\n"
            "Список напоминаний: /reminders",
            parse_mode=ParseMode.HTML,
        )
        return

    reminder_id = parts[1].strip().split()[0]
    if delete_user_reminder(message.from_user.id, reminder_id):
        await message.answer("✅ Напоминание отменено.")
    else:
        await message.answer("Не нашёл активное напоминание с таким ID.")


def transcribe_voice_sync(audio_bytes: bytes) -> str:
    """Transcribe a Telegram voice message locally with free Whisper."""
    global _whisper_model

    # Import lazily so the bot can still start while the speech package is
    # being installed and so model loading never happens during startup.
    from faster_whisper import WhisperModel

    if _whisper_model is None:
        with _whisper_model_lock:
            if _whisper_model is None:
                logger.info(
                    "Loading local Whisper model '%s' for voice transcription...",
                    WHISPER_MODEL_SIZE,
                )
                _whisper_model = WhisperModel(
                    WHISPER_MODEL_SIZE,
                    device="cpu",
                    compute_type="int8",
                )

    audio_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as audio_file:
            audio_file.write(audio_bytes)
            audio_path = audio_file.name

        segments, info = _whisper_model.transcribe(
            audio_path,
            language=None,
            beam_size=5,
            vad_filter=True,
            condition_on_previous_text=False,
        )
        text = " ".join(segment.text.strip() for segment in segments).strip()
        if not text:
            raise ValueError("В голосовом сообщении не удалось разобрать речь.")

        logger.info(
            "Voice message transcribed locally: language=%s, duration=%.1fs",
            info.language,
            info.duration,
        )
        return text
    finally:
        if audio_path:
            try:
                os.remove(audio_path)
            except OSError:
                pass


@router.message(F.voice)
async def handle_voice(message: Message):
    """Turn a Telegram voice message into text without a paid speech API."""
    user_id = message.from_user.id
    touch_user(user_id, message.from_user.first_name, message.from_user.username or "")
    status = await message.answer(
        "🎙️ <i>Распознаю голосовое локально...</i>\n"
        "Первое голосовое может обрабатываться дольше: загружается бесплатная Whisper-модель.",
        parse_mode=ParseMode.HTML,
    )

    try:
        telegram_file = await message.bot.get_file(message.voice.file_id)
        audio = BytesIO()
        await message.bot.download_file(telegram_file.file_path, audio)
        text = await asyncio.to_thread(transcribe_voice_sync, audio.getvalue())

        preview = text
        if len(preview) > 3500:
            preview = preview[:3500].rstrip() + "…"
        await status.edit_text(f"📝 Распознано:\n\n{preview}")

        # Send the transcription through the existing AI conversation flow.
        await process_text_message(message, text)
    except Exception as e:
        logger.error("Voice transcription error for user %s: %s", user_id, e, exc_info=True)
        await status.edit_text(
            "❌ Не удалось распознать голосовое сообщение.\n\n"
            "Попробуйте записать его ещё раз короче и без сильного фонового шума."
        )


@router.message(F.text)
async def handle_message(message: Message, state: FSMContext):
    message_text = (message.text or "").strip()
    lower_text = message_text.casefold()
    if lower_text == SEARCH_TRIGGER:
        await start_search(message, state)
        return
    if lower_text.startswith(f"{SEARCH_TRIGGER} "):
        # Also accept the convenient one-message format:
        # "Найди в интернете последние новости о ..."
        await run_search(message, state, message_text[len(SEARCH_TRIGGER):])
        return
    reminder, parse_error = parse_reminder_request(message.text or "")
    if parse_error:
        await message.answer(f"❌ {parse_error}")
        return
    if reminder:
        created = create_reminder(
            message.from_user.id,
            reminder["text"],
            reminder["due_at"],
        )
        await message.answer(
            "✅ <b>Напоминание поставлено.</b>\n\n"
            f"⏰ {format_reminder_datetime(created['due_at'])} (МСК)\n"
            f"📝 {created['text']}\n\n"
            f"ID: <code>{created['id']}</code>",
            parse_mode=ParseMode.HTML,
        )
        return
    await process_text_message(message, message.text or "")


async def process_text_message(message: Message, text: str):
    user_id = message.from_user.id
    text = text.strip()

    # Track user activity
    touch_user(user_id, message.from_user.first_name, message.from_user.username or "")

    simple_greeting = get_simple_greeting(text)
    if simple_greeting:
        await message.answer(simple_greeting)
        return

    session = get_session(user_id)
    model = MODELS[session["model"]]

    # Block if current model is restricted (admin is exempt, unless in test mode)
    if not is_admin(message.from_user.id):
        r = get_model_restriction(session["model"])
        if r:
            if r["type"] == "temporary":
                until_str = datetime.fromtimestamp(r["until"]).strftime("%d.%m.%Y %H:%M")
                time_note = f"⏳ Временно недоступна до <b>{until_str}</b>"
            else:
                time_note = "🔴 Модель недоступна"
            await message.answer(
                f"⚠️ <b>{model['name']}</b> сейчас недоступна.\n\n"
                f"{time_note}\n"
                f"📌 Причина: <i>{r['reason']}</i>\n\n"
                f"Выберите другую модель через кнопку 🤖 Модель.",
                parse_mode=ParseMode.HTML,
            )
            return

    # ZenoToken check & deduction for paid models (admin and VIP exempt)
    token_price = get_model_price(session["model"])
    if token_price > 0 and not is_admin(user_id) and not is_vip(user_id):
        profile = get_user_profile(user_id)
        balance = profile.get("zenotoken", 0)
        if balance < token_price:
            await message.answer(
                f"🪙 <b>Недостаточно ZenoToken!</b>\n\n"
                f"Модель <b>{model['name']}</b> стоит <b>{token_price} 🪙</b> за запрос.\n"
                f"Ваш баланс: <b>{balance} 🪙</b>\n\n"
                f"Выберите бесплатную модель или обратитесь к администратору для пополнения баланса.",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🤖 Сменить модель", callback_data="open:model")]
                ])
            )
            return
        success, new_balance = deduct_tokens(user_id, token_price)
        if not success:
            await message.answer(
                f"🪙 <b>Недостаточно ZenoToken!</b>\n\n"
                f"Нужно <b>{token_price} 🪙</b>, у вас <b>{balance} 🪙</b>.\n\n"
                f"Выберите бесплатную модель через кнопку 🤖 Модель.",
                parse_mode=ParseMode.HTML,
            )
            return

    thinking_msg = await message.answer(
        f"⏳ <i>{model['emoji_html']} {model['name']} думает...</i>",
        parse_mode=ParseMode.HTML
    )

    # Keep "typing..." indicator alive for the full duration of the AI call
    typing_active = True

    async def keep_typing():
        while typing_active:
            try:
                await message.bot.send_chat_action(message.chat.id, "typing")
            except Exception:
                pass
            await asyncio.sleep(4)

    typing_task = asyncio.create_task(keep_typing())

    try:
        reply = await call_ai(session, text)

        try:
            await thinking_msg.delete()
        except TelegramBadRequest:
            pass

        chunks = [reply[i:i + 4096] for i in range(0, len(reply), 4096)]
        for chunk in chunks:
            try:
                await message.answer(chunk, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                # Fallback: send as plain text if Markdown parsing fails
                await message.answer(chunk)

    except RateLimitError as e:
        logger.warning(f"Rate limit for user {user_id}: {e}")
        await thinking_msg.edit_text(
            f"⏳ <b>Модель {e} перегружена.</b>\n\n"
            f"Бесплатный лимит запросов временно исчерпан у провайдера. "
            f"Подождите минуту и попробуйте снова, или выберите другую модель.\n\n"
            f"🤖 /model — сменить модель",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"AI error for user {user_id}: {e}")
        err = str(e)[:300]
        await thinking_msg.edit_text(
            f"❌ <b>Ошибка:</b> <code>{err}</code>\n\nПопробуйте:\n• Сменить модель /model\n• Новый диалог /new",
            parse_mode=ParseMode.HTML
        )
    finally:
        typing_active = False
        typing_task.cancel()
        try:
            await typing_task
        except asyncio.CancelledError:
            pass


# ─── Cases: keyboards ────────────────────────────────────────────────────────

def progress_bar(current: int, total: int, length: int = 8) -> str:
    if total == 0:
        return "░" * length
    filled = round((current / total) * length)
    filled = max(0, min(filled, length))
    return "█" * filled + "░" * (length - filled)

def cases_list_keyboard(cases: list) -> InlineKeyboardMarkup:
    rows = []
    for c in cases:
        remaining = c["total_count"] - c["opened_count"]
        pct = int(remaining / c["total_count"] * 100) if c["total_count"] else 0
        bar = progress_bar(remaining, c["total_count"], 6)
        rows.append([InlineKeyboardButton(
            text=f"📦 {c['name']}  {bar} {remaining}/{c['total_count']}",
            callback_data=f"case:view:{c['id']}",
        )])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def case_view_keyboard(case_id: str) -> InlineKeyboardMarkup:
    btn_open = InlineKeyboardButton(text="🎰 Открыть кейс", callback_data=f"case:open:{case_id}")
    btn_open.style = "success"
    btn_back = InlineKeyboardButton(text="‹ Все кейсы", callback_data="cases:list")
    btn_back.style = "primary"
    return InlineKeyboardMarkup(inline_keyboard=[[btn_open], [btn_back]])

def admin_cases_keyboard() -> InlineKeyboardMarkup:
    cases = get_all_cases()
    rows = []
    for c in cases:
        remaining = c["total_count"] - c["opened_count"]
        btn = InlineKeyboardButton(
            text=f"🎁 {c['name']} ({remaining}/{c['total_count']})",
            callback_data=f"acase:edit:{c['id']}",
        )
        btn.style = "primary"
        rows.append([btn])
    btn_create = InlineKeyboardButton(text="➕ Создать кейс", callback_data="acase:create")
    btn_create.style = "success"
    btn_prizes = InlineKeyboardButton(text="⚖️ Шансы призов", callback_data="admin:prizes")
    btn_prizes.style = "primary"
    btn_back = InlineKeyboardButton(text="◀️ Назад", callback_data="admin:back")
    btn_back.style = "primary"
    rows.append([btn_create])
    rows.append([btn_prizes])
    rows.append([btn_back])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def prizes_keyboard() -> InlineKeyboardMarkup:
    weights = get_prize_weights()
    total = sum(weights)
    rows = []
    for i, prize in enumerate(CASE_PRIZES):
        w = weights[i]
        pct = round(w / total * 100, 1) if total > 0 else 0
        btn = InlineKeyboardButton(
            text=f"{prize[4]} {prize[3]}  —  вес {w}  ({pct}%)",
            callback_data=f"aprize:edit:{i}",
        )
        btn.style = "primary"
        rows.append([btn])
    btn_reset = InlineKeyboardButton(text="🔄 Сбросить к умолчаниям", callback_data="aprize:reset")
    btn_reset.style = "danger"
    btn_back = InlineKeyboardButton(text="◀️ К кейсам", callback_data="admin:cases")
    btn_back.style = "primary"
    rows.append([btn_reset])
    rows.append([btn_back])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def admin_case_actions_keyboard(case_id: str) -> InlineKeyboardMarkup:
    def _btn(text, cb, style="primary"):
        b = InlineKeyboardButton(text=text, callback_data=cb)
        b.style = style
        return b
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("✏️ Изменить название", f"acase:rename:{case_id}")],
        [_btn("🔢 Изменить количество", f"acase:settotal:{case_id}")],
        [_btn("👤 Изменить лимит на пользователя", f"acase:setlimit:{case_id}")],
        [_btn("🗑 Удалить кейс", f"acase:delete:{case_id}", "danger")],
        [_btn("◀️ К кейсам", "admin:cases")],
    ])


# ─── Cases: user handlers ─────────────────────────────────────────────────────

_REEL_POOL = ["🍒", "🍋", "🍇", "🍊", "🍉", "⭐", "💫", "🔥"]

def _reel(emojis: list[str] | None = None) -> str:
    pool = emojis or _REEL_POOL
    return " │ ".join(random.choices(pool, k=3))

def _slot_frame(row: str, stage: str) -> str:
    return (
        f"╔═══════════════╗\n"
        f"║  {row}  ║\n"
        f"╚═══════════════╝\n\n"
        f"<i>{stage}</i>"
    )

PRIZE_REEL_EMOJI = {
    "nothing":    {0: "💨"},
    "zenotoken": {10: "🪙", 25: "🪙", 50: "💎", 100: "💎"},
    "free_gens":  {3: "🎟", 5: "🎟", 10: "🌟"},
    "vip":        {1: "👑"},
}


@router.callback_query(F.data == "cases:list")
async def cb_cases_list(callback: CallbackQuery, bot: Bot):
    cases = get_available_cases()
    if not cases:
        await bot.send_message(
            chat_id=callback.message.chat.id,
            text=(
                "📦 <b>Зона кейсов</b>\n\n"
                "━━━━━━━━━━━━━━━━━━━\n"
                "😔 Сейчас кейсов нет — все разобрали!\n\n"
                "Загляни позже, скоро появятся новые 👀"
            ),
            parse_mode=ParseMode.HTML,
        )
        await callback.answer()
        return

    lines = ["📦 <b>З О Н А  К Е Й С О В</b>", "", "━━━━━━━━━━━━━━━━━━━"]
    for c in cases:
        remaining = c["total_count"] - c["opened_count"]
        bar = progress_bar(remaining, c["total_count"], 8)
        lines.append(f"  {bar}  <b>{c['name']}</b> — {remaining} шт.")
    lines += [
        "━━━━━━━━━━━━━━━━━━━",
        "",
        "🪙 ZenoToken  •  🎟 Генерации  •  👑 VIP",
        "",
        "👇 Выбери кейс и испытай удачу:",
    ]

    await bot.send_message(
        chat_id=callback.message.chat.id,
        text="\n".join(lines),
        parse_mode=ParseMode.HTML,
        reply_markup=cases_list_keyboard(cases),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("case:view:"))
async def cb_case_view(callback: CallbackQuery, bot: Bot):
    case_id = callback.data.split(":", 2)[2]
    data = load_cases()
    c = data.get(case_id)
    if not c:
        await callback.answer("Кейс не найден.", show_alert=True)
        return
    remaining = c["total_count"] - c["opened_count"]
    uid = str(callback.from_user.id)
    user_opens = c["opened_by"].get(uid, 0)
    opens_left = c["per_user_limit"] - user_opens
    bar = progress_bar(remaining, c["total_count"], 10)

    status_line = (
        f"✅ У тебя есть <b>{opens_left}</b> попыт." if opens_left > 0
        else "🚫 Ты исчерпал все попытки для этого кейса"
    )

    text = (
        f"╔══════════════════╗\n"
        f"  📦  <b>{c['name'].upper()}</b>\n"
        f"╚══════════════════╝\n\n"
        f"<b>Наполненность:</b>\n"
        f"{bar}  <b>{remaining}</b> из {c['total_count']}\n\n"
        f"<b>Твои попытки:</b>  {user_opens} / {c['per_user_limit']}\n"
        f"{status_line}\n\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"💡 <b>Возможные призы:</b>\n"
        f"  💨  Пусто (часто)\n"
        f"  🪙  10 · 25 · 50 · 100 ZenoToken\n"
        f"  🎟  3 · 5 · 10 генераций изображений\n"
        f"  👑  VIP-статус на 24 часа (редко)\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f"Нажми <b>🎰 Открыть кейс</b> и испытай удачу!"
    )
    await bot.send_message(
        chat_id=callback.message.chat.id,
        text=text,
        parse_mode=ParseMode.HTML,
        reply_markup=case_view_keyboard(case_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("case:open:"))
async def cb_case_open(callback: CallbackQuery, bot: Bot):
    case_id = callback.data.split(":", 2)[2]
    user_id = callback.from_user.id

    allowed, reason = can_user_open_case(case_id, user_id)
    if not allowed:
        await callback.answer(reason, show_alert=True)
        return

    # Pick prize BEFORE animation so last frame can match
    prize = pick_prize()
    prize_emoji = PRIZE_REEL_EMOJI.get(prize["type"], {}).get(prize["value"], prize["emoji"])

    await callback.answer("🎰 Крутим барабаны...")

    anim_msg = await bot.send_message(
        chat_id=callback.message.chat.id,
        text=_slot_frame(_reel(), "⏳ Подготовка..."),
        parse_mode=ParseMode.HTML,
    )

    # Stage 1 — fast spin (0.22 s)
    for _ in range(5):
        await asyncio.sleep(0.22)
        try:
            await anim_msg.edit_text(
                _slot_frame(_reel(), "⚡ Барабаны крутятся..."),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass

    # Stage 2 — slowing (0.38 s)
    slow_pool = _REEL_POOL + [prize_emoji]
    for i in range(4):
        await asyncio.sleep(0.38)
        try:
            await anim_msg.edit_text(
                _slot_frame(_reel(slow_pool), "🔄 Замедляемся..."),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass

    # Stage 3 — almost stopped (0.55 s), 2 reels lock
    await asyncio.sleep(0.55)
    try:
        await anim_msg.edit_text(
            _slot_frame(f"{prize_emoji} │ {random.choice(_REEL_POOL)} │ {prize_emoji}", "⏸ Стоп..."),
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        pass

    # Stage 4 — all locked on prize emoji
    await asyncio.sleep(0.65)
    try:
        await anim_msg.edit_text(
            _slot_frame(f"{prize_emoji} │ {prize_emoji} │ {prize_emoji}", "🔒 Результат!"),
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        pass

    # Apply prize & record
    record_case_open(case_id, user_id)
    apply_prize(user_id, prize)

    # Build post-apply balance line
    profile = get_user_profile(user_id)
    if prize["type"] == "nothing":
        await asyncio.sleep(0.5)
        try:
            await anim_msg.edit_text(
                f"╔══════════════════╗\n"
                f"  😔  <b>Н Е  П О В Е З Л О</b>\n"
                f"╚══════════════════╝\n\n"
                f"╔═══════════════╗\n"
                f"║  💨 │ 💨 │ 💨  ║\n"
                f"╚═══════════════╝\n\n"
                f"На этот раз кейс оказался пустым.\n\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"<i>Попробуй ещё раз, удача где-то рядом! 🎁</i>",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
        return

    if prize["type"] == "zenotoken":
        detail = "Начислено прямо на твой баланс."
        balance_line = f"💰 Баланс ZenoToken: <b>{profile.get('zenotoken', 0)} 🪙</b>"
    elif prize["type"] == "free_gens":
        detail = "Добавлено к балансу генераций изображений."
        balance_line = f"🎟 Генерации: <b>{profile.get('free_gens', 0)}</b>"
    else:
        rem = get_vip_remaining(user_id)
        h, m = rem // 3600, (rem % 3600) // 60
        detail = "VIP активен прямо сейчас!"
        balance_line = f"👑 VIP истекает через: <b>{h}ч {m}м</b>"

    await asyncio.sleep(0.5)
    try:
        await anim_msg.edit_text(
            f"╔══════════════════╗\n"
            f"  🎊  <b>П О З Д Р А В Л Я Е М !</b>\n"
            f"╚══════════════════╝\n\n"
            f"╔═══════════════╗\n"
            f"║  {prize_emoji} │ {prize_emoji} │ {prize_emoji}  ║\n"
            f"╚═══════════════╝\n\n"
            f"🏆 <b>Твой приз:</b>  {prize['emoji']} <b>{prize['name']}</b>\n\n"
            f"▸ {detail}\n"
            f"▸ {balance_line}\n\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"<i>Хочешь ещё? Жми 🎁 Кейсы!</i>",
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        pass


# ─── Cases: admin handlers ────────────────────────────────────────────────────

@router.callback_query(F.data == "admin:cases")
async def cb_admin_cases(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    cases = get_all_cases()
    text = f"🎁 <b>Управление кейсами</b>\n\nВсего кейсов: <b>{len(cases)}</b>\n\nВыберите кейс для настройки или создайте новый:"
    await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=admin_cases_keyboard())
    await callback.answer()


@router.callback_query(F.data == "acase:create")
async def cb_acase_create(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    await state.set_state(CaseStates.waiting_case_name)
    await callback.message.edit_text(
        "🎁 <b>Создание кейса</b>\n\nШаг 1/3: Введите <b>название</b> кейса:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="admin:cases", style="danger")]
        ]),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("acase:edit:"))
async def cb_acase_edit(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    case_id = callback.data.split(":", 2)[2]
    data = load_cases()
    c = data.get(case_id)
    if not c:
        await callback.answer("Кейс не найден.", show_alert=True)
        return
    remaining = c["total_count"] - c["opened_count"]
    await callback.message.edit_text(
        f"🎁 <b>{c['name']}</b>\n\n"
        f"📦 Всего: {c['total_count']} | Открыто: {c['opened_count']} | Осталось: {remaining}\n"
        f"👤 Лимит на пользователя: {c['per_user_limit']}\n\n"
        f"Выберите действие:",
        parse_mode=ParseMode.HTML,
        reply_markup=admin_case_actions_keyboard(case_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("acase:delete:"))
async def cb_acase_delete(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    case_id = callback.data.split(":", 2)[2]
    data = load_cases()
    name = data.get(case_id, {}).get("name", case_id)
    delete_case(case_id)
    await callback.message.edit_text(
        f"🗑 Кейс <b>«{name}»</b> удалён.",
        parse_mode=ParseMode.HTML,
        reply_markup=admin_cases_keyboard(),
    )
    await callback.answer("Удалено")


# ─── Cases: admin inline edits (rename / settotal / setlimit) ─────────────────

@router.callback_query(F.data.startswith("acase:rename:"))
async def cb_acase_rename(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    case_id = callback.data.split(":", 2)[2]
    await state.update_data(edit_case_id=case_id, edit_case_field="name")
    await state.set_state(CaseStates.waiting_case_name)
    await callback.message.edit_text(
        "✏️ Введите новое <b>название</b> кейса:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data=f"acase:edit:{case_id}", style="danger")]
        ]),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("acase:settotal:"))
async def cb_acase_settotal(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    case_id = callback.data.split(":", 2)[2]
    await state.update_data(edit_case_id=case_id, edit_case_field="total_count")
    await state.set_state(CaseStates.waiting_case_total)
    await callback.message.edit_text(
        "🔢 Введите новое <b>общее количество</b> кейсов:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data=f"acase:edit:{case_id}", style="danger")]
        ]),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("acase:setlimit:"))
async def cb_acase_setlimit(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    case_id = callback.data.split(":", 2)[2]
    await state.update_data(edit_case_id=case_id, edit_case_field="per_user_limit")
    await state.set_state(CaseStates.waiting_case_limit)
    await callback.message.edit_text(
        "👤 Введите новый <b>лимит открытий на пользователя</b>:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data=f"acase:edit:{case_id}", style="danger")]
        ]),
    )
    await callback.answer()


# ─── Cases: prize weight admin handlers ──────────────────────────────────────

@router.callback_query(F.data == "admin:prizes")
async def cb_admin_prizes(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    await callback.message.edit_text(
        "⚖️ <b>Шансы призов в кейсах</b>\n\n"
        "Нажмите на приз, чтобы изменить его вес.\n"
        "Чем выше вес — тем чаще выпадает. Вес 0 = никогда.",
        parse_mode=ParseMode.HTML,
        reply_markup=prizes_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("aprize:edit:"))
async def cb_aprize_edit(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    idx = int(callback.data.split(":", 2)[2])
    prize = CASE_PRIZES[idx]
    weights = get_prize_weights()
    current_w = weights[idx]
    await state.set_state(AdminStates.waiting_prize_weight)
    await state.update_data(prize_idx=idx)
    await callback.message.edit_text(
        f"⚖️ <b>Изменить вес приза</b>\n\n"
        f"Приз: {prize[4]} <b>{prize[3]}</b>\n"
        f"Текущий вес: <b>{current_w}</b>\n\n"
        f"Введите новый вес (целое число ≥ 0).\n"
        f"<i>Типичные значения: 0 = никогда, 1–5 = редко, 10–20 = часто, 30–50 = очень часто.</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="admin:prizes", style="danger")]
        ]),
    )
    await callback.answer()


@router.callback_query(F.data == "aprize:reset")
async def cb_aprize_reset(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    reset_prize_weights()
    await callback.message.edit_text(
        "🔄 <b>Шансы сброшены к умолчаниям.</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=prizes_keyboard(),
    )
    await callback.answer("Сброшено")


@router.message(AdminStates.waiting_prize_weight)
async def fsm_prize_weight(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        weight = int(message.text.strip())
        if weight < 0:
            raise ValueError
    except ValueError:
        await message.answer(
            "❌ Введите целое число ≥ 0:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отмена", callback_data="admin:prizes", style="danger")]
            ]),
        )
        return
    data = await state.get_data()
    idx = data["prize_idx"]
    prize = CASE_PRIZES[idx]
    set_prize_weight(idx, weight)
    await state.clear()
    await message.answer(
        f"✅ Вес приза {prize[4]} <b>{prize[3]}</b> изменён на <b>{weight}</b>.",
        parse_mode=ParseMode.HTML,
        reply_markup=prizes_keyboard(),
    )


# ─── Global error handler ─────────────────────────────────────────────────────

@router.errors()
async def global_error_handler(event, exception: Exception):
    """Silently ignore 'message is not modified' and similar Telegram edit errors."""
    if isinstance(exception, TelegramBadRequest):
        text = str(exception).lower()
        if any(phrase in text for phrase in (
            "message is not modified",
            "message can't be edited",
            "message to edit not found",
            "query is too old",
        )):
            return True  # suppressed
    logger.error(f"Unhandled error: {exception}", exc_info=exception)
    return False


# ─── Bot commands ─────────────────────────────────────────────────────────────

async def set_commands(bot: Bot):
    await bot.set_my_commands([
        BotCommand(command="start",   description="Главное меню"),
        BotCommand(command="new",     description="Новый диалог"),
        BotCommand(command="model",   description="Выбрать модель ИИ"),
        BotCommand(command="role",    description="Выбрать роль ассистента"),
        BotCommand(command="img",     description="Сгенерировать изображение"),
        BotCommand(command="search",  description="Поиск в интернете"),
        BotCommand(command="vision",  description="Анализ фото — что на нём"),
        BotCommand(command="status",  description="Текущие настройки"),
        BotCommand(command="profile", description="Мой профиль и ZenoToken"),
        BotCommand(command="reminders", description="Мои напоминания"),
        BotCommand(command="cancel_reminder", description="Удалить напоминание"),
        BotCommand(command="help",    description="Помощь"),
    ])


# ─── Main ─────────────────────────────────────────────────────────────────────

async def main():
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp.message.middleware(AntiSpamMiddleware())
    dp.callback_query.middleware(AntiSpamMiddleware())
    dp.include_router(router)
    reminder_task = asyncio.create_task(reminder_worker(bot))

    try:
        await set_commands(bot)
        logger.info("Бот запущен на Groq!")
        await dp.start_polling(bot, allowed_updates=["message", "callback_query"])
    finally:
        reminder_task.cancel()
        try:
            await reminder_task
        except asyncio.CancelledError:
            pass
        logger.info("Останавливаю бота, закрываю сессию...")
        await bot.session.close()
        logger.info("Сессия закрыта.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен.")
