---
name: BotHost entry point
description: External hosts may default to main.py even when the Replit workflow uses app.py.
---

For this bot, `app.py` is the real asynchronous entry point. Hosts that default to `main.py` must either be configured with `python app.py` or use a compatibility launcher in `main.py`.

**Why:** A generated `main.py` can silently print the workspace template greeting while the real bot never starts.

**How to apply:** When logs show repeated `Hello from repl-nix-workspace!`, change the host command to `python app.py` or deploy the compatibility entrypoint commit.