import os
import re
import asyncio
import logging
import json
from datetime import datetime
from collections import defaultdict
import time
import aiohttp

from typing import Any, Awaitable, Callable
from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    BotCommand, ReplyKeyboardMarkup, KeyboardButton, TelegramObject, FSInputFile,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.dispatcher.middlewares.base import BaseMiddleware

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ["BOT_TOKEN"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
SAMBANOVA_API_KEY = os.environ.get("SAMBANOVA_API_KEY", "")
SAMBANOVA_API_URL = "https://api.sambanova.ai/v1/chat/completions"

ADMIN_ID = 5814345235
USERS_FILE = "users_data.json"
MODELS_FILE = "models_data.json"


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
    "llama3_70b": {
        "name": "Llama 3.3 70B",
        "model_id": "llama-3.3-70b-versatile",
        "description": "Мощная универсальная модель. Отлично справляется с любыми задачами.",
        "emoji": "🧠",
        "emoji_html": pe("5805553606635559688", "🧠"),
        "emoji_id": "5805553606635559688",
    },
    "llama3_8b": {
        "name": "Llama 3.1 8B",
        "model_id": "llama-3.1-8b-instant",
        "description": "Молниеносная лёгкая модель. Идеальна для быстрых ответов.",
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
        "model_id": "compound-beta",
        "description": "Составная модель от Groq. Объединяет несколько ИИ для лучшего результата.",
        "emoji": "⚗️",
        "emoji_html": pe("5913787972200698358", "⚗️"),
        "emoji_id": "5913787972200698358",
    },
    "qwen3_32b": {
        "name": "Groq Compound Mini",
        "model_id": "compound-beta-mini",
        "description": "Компактная составная модель Groq. Быстрая и умная — лучший баланс скорости и качества.",
        "emoji": "🌀",
        "emoji_html": pe("5388957777676745182", "🌀"),
        "emoji_id": "5388957777676745182",
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
}

SYSTEM_PROMPTS = {
    "default": "Ты умный, дружелюбный и полезный ИИ-ассистент. Отвечай чётко, структурировано и по делу. Используй Markdown для форматирования когда уместно.",
    "coder": "Ты опытный программист и архитектор ПО. Помогаешь писать чистый, эффективный код с подробными объяснениями. Всегда используй блоки кода с указанием языка.",
    "writer": "Ты талантливый писатель и редактор. Помогаешь с текстами, статьями, историями и копирайтингом. Пишешь живо, грамотно и увлекательно.",
    "analyst": "Ты аналитик данных и бизнес-консультант. Помогаешь анализировать информацию, строить стратегии и принимать взвешенные решения.",
    "translator": "Ты профессиональный переводчик и лингвист. Переводи точно и естественно, сохраняя стиль и смысл оригинала. После перевода можешь дать короткий комментарий если нужно.",
    "tutor": "Ты терпеливый и опытный преподаватель. Объясняешь сложные темы простым языком, используешь примеры и аналогии. Проверяешь понимание.",
}

COMMON_INSTRUCTIONS = (
    "Отвечай сразу по существу, без вступительных фраз и разъяснений о том, что ты сейчас будешь делать "
    "(не пиши фразы вроде 'Конечно, вот ответ' или 'Хорошо, объясняю'). "
    "Давай только сам ответ."
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

def get_all_users() -> list:
    data = load_users()
    return list(data.values())


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

        warned_at = user_spam_warned.get(user_id)
        if warned_at:
            remaining = int(SPAM_COOLDOWN - (now - warned_at))
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

        if len(times) >= SPAM_LIMIT:
            user_spam_warned[user_id] = now
            user_message_times[user_id] = []
            if isinstance(event, Message):
                await event.answer(
                    f"🚫 <b>Слишком много запросов!</b>\n\nНе спамь — подожди <b>{SPAM_COOLDOWN} сек.</b>",
                    parse_mode=ParseMode.HTML,
                )
            elif isinstance(event, CallbackQuery):
                await event.answer(
                    f"🚫 Слишком много запросов! Подожди {SPAM_COOLDOWN} сек.",
                    show_alert=True,
                )
            return

        return await handler(event, data)


# ─── Session helper ───────────────────────────────────────────────────────────

def get_session(user_id: int) -> dict:
    if user_id not in user_sessions:
        user_sessions[user_id] = {
            "model": "llama3_70b",
            "role": "default",
            "style": "calm",
            "history": [],
            "temperature": 0.7,
        }
    else:
        # Ensure older sessions have the style key
        user_sessions[user_id].setdefault("style", "calm")
    return user_sessions[user_id]


# ─── Keyboards ───────────────────────────────────────────────────────────────

def main_keyboard(user_id: int = 0) -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(text="🤖 Модель"), KeyboardButton(text="🎭 Роль")],
        [KeyboardButton(text="⚙️ Настройки"), KeyboardButton(text="🗑 Новый диалог")],
        [KeyboardButton(text="👤 Профиль"), KeyboardButton(text="ℹ️ Помощь")],
    ]
    if user_id == ADMIN_ID:
        buttons.append([KeyboardButton(text="🛡 Админ панель")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


MODEL_STYLES = {
    "gpt_oss_120b": "danger",
    "gpt_oss_20b": "primary",
    "llama3_70b": "success",
    "llama3_8b": "primary",
    "qwen3_27b": "primary",
    "compound": "danger",
    "qwen3_32b": "success",
    "sn_deepseek_v3_1": "danger",
    "sn_deepseek_v3_2": "danger",

    "sn_gemma4_31b": "success",
    "sn_gpt_oss_120b": "danger",
}

def models_keyboard(current: str) -> InlineKeyboardMarkup:
    all_btns = []
    for key, model in MODELS.items():
        check = "✅ " if key == current else ""
        style = MODEL_STYLES[key]
        btn = InlineKeyboardButton(
            text=f"{check}{model['name']}",
            callback_data=f"model:{key}",
            icon_custom_emoji_id=get_model_emoji_id(key),
        )
        if style:
            btn.style = style
        all_btns.append(btn)
    # 2 buttons per row
    buttons = [all_btns[i:i+2] for i in range(0, len(all_btns), 2)]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def roles_keyboard(current: str) -> InlineKeyboardMarkup:
    buttons = []
    for key, role in ROLES.items():
        check = "✅ " if key == current else ""
        btn = InlineKeyboardButton(
            text=f"{check}{role['name']}",
            callback_data=f"role:{key}",
            icon_custom_emoji_id=role["emoji_id"],
        )
        buttons.append([btn])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def settings_keyboard(user_id: int) -> InlineKeyboardMarkup:
    session = get_session(user_id)
    temp = session["temperature"]
    buttons = [
        [InlineKeyboardButton(text=f"🌡 Температура: {temp:.1f}  (точно ←→ креативно)", callback_data="noop")],
        [
            InlineKeyboardButton(text="➖", callback_data="temp:down"),
            InlineKeyboardButton(text=f"{temp:.1f}", callback_data="noop"),
            InlineKeyboardButton(text="➕", callback_data="temp:up"),
        ],
        [InlineKeyboardButton(text="✅ Закрыть", callback_data="settings:close")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def admin_keyboard() -> InlineKeyboardMarkup:
    test_label = "🧪 Тест как пользователь: 🟢 ВКЛ" if admin_test_mode else "🧪 Тест как пользователь: ⭕ ВЫКЛ"
    maint_label = "🔧 Тех. работы: 🟢 ВКЛ" if is_maintenance() else "🔧 Тех. работы: ⭕ ВЫКЛ"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin:broadcast")],
        [InlineKeyboardButton(text="🪙 Выдать ZenoToken", callback_data="admin:give")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin:stats")],
        [InlineKeyboardButton(text="👥 Список пользователей", callback_data="admin:users")],
        [InlineKeyboardButton(text="🔍 Найти пользователя", callback_data="admin:find")],
        [InlineKeyboardButton(text="🤖 Управление моделями", callback_data="admin:models")],
        [InlineKeyboardButton(text=test_label, callback_data="admin:testmode")],
        [InlineKeyboardButton(text=maint_label, callback_data="admin:maintenance")],
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
        rows.append([InlineKeyboardButton(text="✅ Возобновить", callback_data=f"mctrl:resume:{model_key}")])
    rows.append([InlineKeyboardButton(text="🔴 Ограничить", callback_data=f"mctrl:restrict:{model_key}")])
    rows.append([InlineKeyboardButton(text="⏳ Временно ограничить", callback_data=f"mctrl:temp:{model_key}")])
    rows.append([InlineKeyboardButton(text="◀️ К моделям", callback_data="admin:models")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="admin:cancel")]
    ])


def styles_keyboard(current: str) -> InlineKeyboardMarkup:
    buttons = []
    for key, style in STYLES.items():
        check = "✅ " if key == current else ""
        buttons.append([InlineKeyboardButton(
            text=f"{check}{style['emoji']} {style['name']} — {style['description']}",
            callback_data=f"style:{key}",
        )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def start_inline_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗣 Стиль общения", callback_data="style:menu")]
    ])


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
        f"Я — ИИ-ассистент с доступом к лучшим <b>бесплатным</b> языковым моделям (Groq).\n\n"
        f"📌 <b>Текущие настройки:</b>\n"
        f"• Модель: {model['emoji_html']} {model['name']}\n"
        f"• Роль: {role['emoji_html']} {role['name']}\n"
        f"• Стиль: {style['emoji']} {style['name']}\n\n"
        f"Просто напиши мне сообщение — и я отвечу!"
    )
    photo = FSInputFile("welcome_photo.jpg")
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
        f"{pe('5258093637450866522', '🤖')} <b>Модели (все бесплатные):</b>\n{models_text}\n\n"
        f"{pe('6032625495328165724', '🎭')} <b>Роли:</b>\n{roles_text}\n\n"
        "⚙️ <b>Настройки</b> — регулировка температуры ответа\n"
        "🗑 <b>Новый диалог</b> — сбросить историю\n"
        "👤 <b>Профиль</b> — ваш профиль и баланс ZenoToken\n\n"
        "📝 <b>Команды:</b>\n"
        "/start — главное меню\n"
        "/new — новый диалог\n"
        "/model — сменить модель\n"
        "/role — сменить роль\n"
        "/status — текущие настройки\n"
        "/profile — мой профиль\n"
        "/help — помощь"
    )
    await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=main_keyboard(message.from_user.id))


# ─── /model ───────────────────────────────────────────────────────────────────

@router.message(Command("model"))
@router.message(F.text == "🤖 Модель")
async def cmd_model(message: Message):
    session = get_session(message.from_user.id)
    await message.answer(
        f"{pe('5258093637450866522', '🤖')} <b>Выберите модель ИИ:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=models_keyboard(session["model"])
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
    await message.answer(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=settings_keyboard(message.from_user.id)
    )


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
    text = (
        f"👤 <b>Профиль</b>\n\n"
        f"👤 Имя: <b>{profile['first_name']}</b>\n"
        f"🔗 Username: <b>{username_str}</b>\n"
        f"🆔 ID: <code>{profile['user_id']}</code>\n\n"
        f"🪙 <b>ZenoToken: {profile.get('zenotoken', 0)}</b>\n\n"
        f"💬 Сообщений отправлено: <b>{profile.get('messages_count', 0)}</b>\n"
        f"📅 Дата регистрации: <b>{profile.get('joined_at', '—')}</b>\n"
        f"🕐 Последняя активность: <b>{profile.get('last_seen', '—')}</b>\n\n"
        f"🤖 Текущая модель: {model['emoji_html']} <b>{model['name']}</b>\n"
        f"🎭 Текущая роль: {role['emoji_html']} <b>{role['name']}</b>"
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


@router.callback_query(F.data.startswith("model:"))
async def cb_model(callback: CallbackQuery):
    model_key = callback.data.split(":")[1]
    model = MODELS[model_key]

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
    await callback.message.edit_text(
        f"{pe('5370893703575511656', '✅')} Модель: {model['emoji_html']} <b>{model['name']}</b>\n\n<i>{model['description']}</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=models_keyboard(model_key)
    )
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


# ─── Groq API ─────────────────────────────────────────────────────────────────

async def call_ai(session: dict, user_message: str) -> str:
    model_cfg = MODELS[session["model"]]
    model_id = model_cfg["model_id"]

    today = datetime.now().strftime("%d.%m.%Y")
    style_key = session.get("style", "calm")
    style_instruction = STYLES[style_key]["instruction"]
    system_prompt = (
        f"Сегодняшняя дата: {today}. Используй эту дату как актуальную текущую дату и год, "
        f"а не дату из своих обучающих данных.\n\n"
        f"{SYSTEM_PROMPTS[session['role']]}\n\n"
        f"СТИЛЬ ОБЩЕНИЯ: {style_instruction}\n\n"
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


def escape_md(text: str) -> str:
    chars = r"_*[]()~`>#+-=|{}.!"
    for ch in chars:
        text = text.replace(ch, f"\\{ch}")
    return text


# ─── Message handler ──────────────────────────────────────────────────────────

@router.message(F.text)
async def handle_message(message: Message):
    user_id = message.from_user.id
    text = message.text.strip()

    # Track user activity
    touch_user(user_id, message.from_user.first_name, message.from_user.username or "")

    session = get_session(user_id)
    model = MODELS[session["model"]]
    role = ROLES[session["role"]]

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

    thinking_msg = await message.answer(
        f"⏳ <i>{model['emoji_html']} {model['name']} думает...</i>",
        parse_mode=ParseMode.HTML
    )

    try:
        reply = await call_ai(session, text)

        header = f"<i>{role['emoji_html']} {role['name']} · {model['name']}</i>"

        await thinking_msg.edit_text(header, parse_mode=ParseMode.HTML)

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


# ─── Bot commands ─────────────────────────────────────────────────────────────

async def set_commands(bot: Bot):
    await bot.set_my_commands([
        BotCommand(command="start",   description="Главное меню"),
        BotCommand(command="new",     description="Новый диалог"),
        BotCommand(command="model",   description="Выбрать модель ИИ"),
        BotCommand(command="role",    description="Выбрать роль ассистента"),
        BotCommand(command="status",  description="Текущие настройки"),
        BotCommand(command="profile", description="Мой профиль и ZenoToken"),
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

    try:
        await set_commands(bot)
        logger.info("Бот запущен на Groq!")
        await dp.start_polling(bot, allowed_updates=["message", "callback_query"])
    finally:
        logger.info("Останавливаю бота, закрываю сессию...")
        await bot.session.close()
        logger.info("Сессия закрыта.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен.")
