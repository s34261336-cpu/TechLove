---
name: Web search provider
description: Environment-specific behavior of the bot's public web search sources.
---

Use Bing HTML search as the primary public search source and DuckDuckGo HTML as a fallback. DuckDuckGo can return HTTP 200 with a valid-looking HTML page but no usable result blocks in this environment.

**Why:** The initial DuckDuckGo-only implementation passed the network request but returned an empty result list for ordinary Russian queries, so the bot could not answer search requests.

**How to apply:** Keep search provider parsing isolated behind the existing search function and preserve a second provider fallback when changing the search feature.