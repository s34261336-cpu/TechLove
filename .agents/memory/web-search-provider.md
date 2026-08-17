---
name: Web search provider
description: Environment-specific behavior of the bot's public web search sources.
---

Use Bing HTML search with explicit Russian market parameters as the primary public search source, decode provider tracking URLs, and filter unrelated results before using DuckDuckGo HTML as a fallback. Bing RSS is a useful parser fallback; DuckDuckGo can return HTTP 200 with no usable result blocks.

**Why:** Provider responses can be HTTP 200 yet contain empty markup, regional/irrelevant results, or tracking URLs. Russian market parameters and relevance filtering are needed for dependable answers.

**How to apply:** Keep provider parsing and URL normalization isolated behind the existing search function, preserve Bing plus a second-provider fallback, and validate result relevance before summarizing.