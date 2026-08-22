#!/usr/bin/env bash

set -Eeuo pipefail

log() {
  printf '[bot-start] %s\n' "$*"
}

if git rev-parse --show-toplevel >/dev/null 2>&1; then
  repo_root="$(git rev-parse --show-toplevel)"
  cd "$repo_root"

  if git remote get-url origin >/dev/null 2>&1; then
    if git fetch --quiet --prune origin main; then
      if [[ "$(git rev-parse HEAD)" != "$(git rev-parse origin/main)" ]]; then
        # Never overwrite local changes. BotHost can restart and retry after
        # the working tree has been made clean.
        if git diff --quiet -- . \
          ':(exclude)users_data.json' \
          ':(exclude)models_data.json' \
          ':(exclude)cases_data.json' \
          ':(exclude)reminders_data.json' \
          && git diff --cached --quiet -- . \
          ':(exclude)users_data.json' \
          ':(exclude)models_data.json' \
          ':(exclude)cases_data.json' \
          ':(exclude)reminders_data.json'; then
          git merge --ff-only origin/main
          log "Код обновлён до $(git rev-parse --short HEAD)."
        else
          log "Обновление пропущено: есть локальные изменения."
          log "Сначала сохраните их коммитом, затем перезапустите бота."
        fi
      else
        log "Код уже актуален: $(git rev-parse --short HEAD)."
      fi
    else
      log "Не удалось проверить GitHub; запускаю текущую версию."
    fi
  fi
fi

exec python app.py