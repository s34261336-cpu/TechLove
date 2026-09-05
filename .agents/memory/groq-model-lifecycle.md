---
name: Groq model lifecycle
description: Availability and fallback behavior for Groq chat models used by the bot.
---

Groq can reject older Llama and `compound-beta` model IDs even when authentication and the API endpoint are working. Current bot paths should prefer `openai/gpt-oss-120b`, `openai/gpt-oss-20b`, `qwen/qwen3.6-27b`, `groq/compound`, and `groq/compound-mini`.

**Why:** Live model discovery showed the old aliases were retired or renamed; `groq/compound` succeeds with the standard chat-completions payload, while the old alias can produce tool-choice errors.

**How to apply:** When changing model configuration, verify the provider’s current model IDs and never make a single model ID a hard dependency for search summaries or the default conversation flow. Treat Qwen3.6 27B 429 responses as transient provider throttling first, not as an invalid model ID.