"""Compatibility entry point for hosts that start ``python main.py``.

The bot implementation lives in ``app.py`` because that is the Replit
workflow entry point. Some external hosts default to ``main.py`` instead, so
delegate to the real asynchronous bot entry point here.
"""

import asyncio

from app import main as run_bot


if __name__ == "__main__":
    try:
        asyncio.run(run_bot())
    except (KeyboardInterrupt, SystemExit):
        pass
