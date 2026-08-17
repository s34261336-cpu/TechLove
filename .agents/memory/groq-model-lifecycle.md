---
name: Groq model lifecycle
description: Availability and fallback behavior for Groq chat models used by the bot.
---

Groq can reject older Llama model IDs with a “does not exist or you do not have access” response even when authentication and the API endpoint are working. Current bot paths should prefer the active GPT-OSS model IDs and keep a second active model as fallback.

**Why:** Search was successfully returning web pages, but the final summary failed because it still requested a retired Llama ID; the same issue also broke ordinary chat when an old default model was selected.

**How to apply:** When changing model configuration, verify the provider’s current model IDs and never make a single model ID a hard dependency for search summaries or the default conversation flow.