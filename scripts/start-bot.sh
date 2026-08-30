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
        runtime_backup_dir="$(mktemp -d)"
        runtime_files=(
          "users_data.json"
          "models_data.json"
          "cases_data.json"
          "reminders_data.json"
          "media_data.json"
        )
        for runtime_file in "${runtime_files[@]}"; do
          if [[ -f "$runtime_file" ]]; then
            cp -p "$runtime_file" "$runtime_backup_dir/$runtime_file"
          fi
        done

        # Never overwrite local changes. BotHost can restart and retry after
        # the working tree has been made clean.
        if git diff --quiet -- . \
          ':(exclude)users_data.json' \
          ':(exclude)models_data.json' \
          ':(exclude)cases_data.json' \
          ':(exclude)reminders_data.json' \
          ':(exclude)media_data.json' \
          && git diff --cached --quiet -- . \
          ':(exclude)users_data.json' \
          ':(exclude)models_data.json' \
          ':(exclude)cases_data.json' \
          ':(exclude)reminders_data.json' \
          ':(exclude)media_data.json'; then
          if git merge --ff-only origin/main; then
            for runtime_file in "${runtime_files[@]}"; do
              if [[ -f "$runtime_backup_dir/$runtime_file" ]]; then
                cp -p "$runtime_backup_dir/$runtime_file" "$runtime_file"
              fi
            done
            log "Код обновлён до $(git rev-parse --short HEAD); локальные данные сохранены."
          else
            log "Автосинхронизация пропущена: локальная ветка содержит отдельные изменения."
          fi
        else
          log "Обновление пропущено: есть локальные изменения."
          log "Сначала сохраните их коммитом, затем перезапустите бота."
        fi
        rm -rf "$runtime_backup_dir"
      else
        log "Код уже актуален: $(git rev-parse --short HEAD)."
      fi
    else
      log "Не удалось проверить GitHub; запускаю текущую версию."
    fi
  fi
fi

if ! python -c "import imageio_ffmpeg" >/dev/null 2>&1; then
  log "Не найден imageio-ffmpeg; устанавливаю зависимость для генерации видео."
  if ! python -m pip install --user --quiet --disable-pip-version-check imageio-ffmpeg; then
    log "Не удалось установить imageio-ffmpeg; бот будет запущен без генерации видео."
  fi
fi

exec python app.py