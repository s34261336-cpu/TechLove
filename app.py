import os
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
    BotCommand, ReplyKeyboardMarkup, KeyboardButton, TelegramObject,
)
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.dispatcher.middlewares.base import BaseMiddleware

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ["BOT_TOKEN"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

def pe(emoji_id: str, fallback: str) -> str:
    return f'<tg-emoji emoji-id="{emoji_id}">{fallback}</tg-emoji>'

MODELS = {
    "llama4_scout": {
        "name": "Llama 4 Scout",
        "model_id": "meta-llama/llama-4-scout-17b-16e-instruct",
        "description": "Новейшая Llama 4 от Meta. Умная, быстрая, бесплатная.",
        "emoji": "🦙",
        "emoji_html": pe("5926783847453692661", "🦙"),
        "emoji_id": "5926783847453692661",
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
    "qwen3_32b": {
        "name": "Qwen3 32B",
        "model_id": "qwen/qwen3-32b",
        "description": "Флагманская модель Alibaba. Глубокое мышление и высокое качество.",
        "emoji": "🌀",
        "emoji_html": pe("5388957777676745182", "🌀"),
        "emoji_id": "5388957777676745182",
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

user_sessions: dict[int, dict] = {}

SPAM_LIMIT = 5
SPAM_WINDOW = 10
SPAM_COOLDOWN = 30

user_message_times: dict[int, list] = defaultdict(list)
user_spam_warned: dict[int, float] = {}


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


def get_session(user_id: int) -> dict:
    if user_id not in user_sessions:
        user_sessions[user_id] = {
            "model": "llama3_70b",
            "role": "default",
            "history": [],
            "temperature": 0.7,
        }
    return user_sessions[user_id]


def main_keyboard() -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(text="🤖 Модель"), KeyboardButton(text="🎭 Роль")],
        [KeyboardButton(text="⚙️ Настройки"), KeyboardButton(text="🗑 Новый диалог")],
        [KeyboardButton(text="ℹ️ Помощь")],
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


MODEL_STYLES = {
    "llama4_scout": "danger",
    "llama3_70b": "success",
    "llama3_8b": "primary",
    "qwen3_32b": "success",
    "qwen3_27b": "primary",
    "compound": "danger",
}

def models_keyboard(current: str) -> InlineKeyboardMarkup:
    buttons = []
    for key, model in MODELS.items():
        check = "✅ " if key == current else ""
        style = MODEL_STYLES[key]
        btn = InlineKeyboardButton(
            text=f"{check}{model['name']}",
            callback_data=f"model:{key}",
            icon_custom_emoji_id=model["emoji_id"],
        )
        if style:
            btn.style = style
        buttons.append([btn])
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


router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message):
    user = message.from_user
    session = get_session(user.id)
    model = MODELS[session["model"]]
    role = ROLES[session["role"]]
    text = (
        f"👋 Привет, <b>{user.first_name}</b>!\n\n"
        f"Я — ИИ-ассистент с доступом к лучшим <b>бесплатным</b> языковым моделям (Groq).\n\n"
        f"📌 <b>Текущие настройки:</b>\n"
        f"• Модель: {model['emoji_html']} {model['name']}\n"
        f"• Роль: {role['emoji_html']} {role['name']}\n\n"
        f"Просто напиши мне сообщение — и я отвечу!"
    )
    await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=main_keyboard())


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
        "🗑 <b>Новый диалог</b> — сбросить историю\n\n"
        "📝 <b>Команды:</b>\n"
        "/start — главное меню\n"
        "/new — новый диалог\n"
        "/model — сменить модель\n"
        "/role — сменить роль\n"
        "/status — текущие настройки\n"
        "/help — помощь"
    )
    await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=main_keyboard())


@router.message(Command("model"))
@router.message(F.text == "🤖 Модель")
async def cmd_model(message: Message):
    session = get_session(message.from_user.id)
    await message.answer(
        f"{pe('5258093637450866522', '🤖')} <b>Выберите модель ИИ:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=models_keyboard(session["model"])
    )


@router.message(Command("role"))
@router.message(F.text == "🎭 Роль")
async def cmd_role(message: Message):
    session = get_session(message.from_user.id)
    await message.answer(
        f"{pe('6032625495328165724', '🎭')} <b>Выберите роль ассистента:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=roles_keyboard(session["role"])
    )


@router.message(Command("new"))
@router.message(F.text == "🗑 Новый диалог")
async def cmd_new(message: Message):
    session = get_session(message.from_user.id)
    session["history"] = []
    await message.answer(
        "🗑 <b>История очищена.</b> Начинаем новый диалог!",
        parse_mode=ParseMode.HTML,
        reply_markup=main_keyboard()
    )


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


@router.callback_query(F.data.startswith("model:"))
async def cb_model(callback: CallbackQuery):
    model_key = callback.data.split(":")[1]
    session = get_session(callback.from_user.id)
    session["model"] = model_key
    model = MODELS[model_key]
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


async def call_groq(session: dict, user_message: str) -> str:
    model_id = MODELS[session["model"]]["model_id"]
    today = datetime.now().strftime("%d.%m.%Y")
    system_prompt = (
        f"Сегодняшняя дата: {today}. Используй эту дату как актуальную текущую дату и год, "
        f"а не дату из своих обучающих данных.\n\n"
        f"{SYSTEM_PROMPTS[session['role']]}\n\n{COMMON_INSTRUCTIONS}"
    )

    session["history"].append({"role": "user", "content": user_message})
    if len(session["history"]) > 20:
        session["history"] = session["history"][-20:]

    messages = [{"role": "system", "content": system_prompt}] + session["history"]

    payload = {
        "model": model_id,
        "messages": messages,
        "temperature": session["temperature"],
        "max_tokens": 2048,
    }
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    async with aiohttp.ClientSession() as http:
        async with http.post(GROQ_API_URL, json=payload, headers=headers) as resp:
            data = await resp.json()
    reply = data["choices"][0]["message"]["content"]
    session["history"].append({"role": "assistant", "content": reply})
    return reply


def escape_md(text: str) -> str:
    chars = r"_*[]()~`>#+-=|{}.!"
    for ch in chars:
        text = text.replace(ch, f"\\{ch}")
    return text


@router.message(F.text)
async def handle_message(message: Message):
    user_id = message.from_user.id

    text = message.text.strip()
    session = get_session(user_id)
    model = MODELS[session["model"]]
    role = ROLES[session["role"]]

    thinking_msg = await message.answer(
        f"⏳ <i>{model['emoji_html']} {model['name']} думает...</i>",
        parse_mode=ParseMode.HTML
    )

    try:
        reply = await call_groq(session, text)

        header = f"<i>{role['emoji_html']} {role['name']} · {model['name']}</i>"

        await thinking_msg.edit_text(header, parse_mode=ParseMode.HTML)

        chunks = [reply[i:i + 4096] for i in range(0, len(reply), 4096)]
        for chunk in chunks:
            await message.answer(chunk, parse_mode=ParseMode.MARKDOWN)

    except Exception as e:
        logger.error(f"Groq error for user {user_id}: {e}")
        err = str(e)[:300]
        await thinking_msg.edit_text(
            f"❌ <b>Ошибка:</b> <code>{err}</code>\n\nПопробуйте:\n• Сменить модель /model\n• Новый диалог /new",
            parse_mode=ParseMode.HTML
        )


async def set_commands(bot: Bot):
    await bot.set_my_commands([
        BotCommand(command="start",  description="Главное меню"),
        BotCommand(command="new",    description="Новый диалог"),
        BotCommand(command="model",  description="Выбрать модель ИИ"),
        BotCommand(command="role",   description="Выбрать роль ассистента"),
        BotCommand(command="status", description="Текущие настройки"),
        BotCommand(command="help",   description="Помощь"),
    ])


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
