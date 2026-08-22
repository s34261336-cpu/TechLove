"""Compatibility entry point for hosts that start ``python main.py``.

The bot implementation lives in ``app.py`` because that is the Replit
workflow entry point. Some external hosts default to ``main.py`` instead, so
delegate to the real asynchronous bot entry point here.
"""

import asyncio
import subprocess


def update_from_origin() -> None:
    """Refresh a clean checkout before hosts that start main.py run the bot."""
    try:
        root = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        subprocess.run(
            ["git", "fetch", "--quiet", "--prune", "origin", "main"],
            cwd=root,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        current = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True
        ).strip()
        remote = subprocess.check_output(
            ["git", "rev-parse", "origin/main"], cwd=root, text=True
        ).strip()
        if current == remote:
            return
        runtime_data = [
            ":(exclude)users_data.json",
            ":(exclude)models_data.json",
            ":(exclude)cases_data.json",
            ":(exclude)reminders_data.json",
        ]
        clean = subprocess.run(
            ["git", "diff", "--quiet", "--", ".", *runtime_data],
            cwd=root,
            check=False,
        ).returncode == 0
        staged_clean = subprocess.run(
            ["git", "diff", "--cached", "--quiet", "--", ".", *runtime_data],
            cwd=root,
            check=False,
        ).returncode == 0
        if clean and staged_clean:
            subprocess.run(
                ["git", "merge", "--ff-only", "origin/main"], cwd=root, check=True
            )
            print(f"[bot-start] Код обновлён до {remote[:7]}.")
        else:
            print("[bot-start] Обновление пропущено: есть локальные изменения.")
    except (OSError, subprocess.CalledProcessError):
        # Git is optional for copied deployments; the current checkout remains runnable.
        print("[bot-start] Git update unavailable; запускаю текущую версию.")

if __name__ == "__main__":
    try:
        update_from_origin()
        # Import only after the checkout has been refreshed.
        from app import main as run_bot

        asyncio.run(run_bot())
    except (KeyboardInterrupt, SystemExit):
        pass
