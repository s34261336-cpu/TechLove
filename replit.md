# Zeno AI Telegram Bot

A Telegram AI chatbot powered by Groq's API, built with Python and aiogram 3.

## Stack

- **Language:** Python 3.11
- **Telegram framework:** aiogram 3.7.0
- **AI backend:** Groq API (multiple LLM models)
- **Storage:** JSON files (`users_data.json`, `models_data.json`)

## How to run

The app is started via the **"Start application"** workflow, which runs:

```
python app.py
```

## Required secrets

| Secret | Description |
|--------|-------------|
| `BOT_TOKEN` | Telegram bot token from [@BotFather](https://t.me/BotFather) |
| `GROQ_API_KEY` | Groq API key from [console.groq.com](https://console.groq.com) |

## Features

- Multiple AI models (Llama, Qwen, Groq Compound)
- Switchable assistant roles (coder, writer, analyst, translator, tutor)
- Per-user conversation history with temperature control
- Anti-spam middleware
- Admin panel with broadcast, user management, and model restriction controls
- ZenoToken system for users

## User preferences

<!-- Add any project-specific preferences here -->
