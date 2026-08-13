#!/usr/bin/env bash

set -Eeuo pipefail

readonly REPO_ROOT="$(git rev-parse --show-toplevel)"
readonly REMOTE="${GIT_SYNC_REMOTE:-gitsafe-backup}"
readonly INTERVAL_SECONDS="${GIT_SYNC_INTERVAL_SECONDS:-120}"

cd "$REPO_ROOT"

log() {
  printf '[git-auto-sync] %s\n' "$*"
}

commit_changes() {
  git add -A -- \
    . \
    ':(exclude)**/.env' \
    ':(exclude)**/.env.*' \
    ':(exclude)**/*.pem' \
    ':(exclude)**/*.key' \
    ':(exclude)**/__pycache__' \
    ':(exclude)**/*.pyc'

  if git diff --cached --quiet; then
    return 1
  fi

  if git commit -m "Auto-sync project changes"; then
    return 0
  fi

  return 2
}

sync_once() {
  local commit_status
  if commit_changes; then
    log "Изменения сохранены в локальный коммит."
  else
    commit_status=$?
    if [[ "$commit_status" -eq 1 ]]; then
      log "Новых изменений нет."
    else
      log "Не удалось создать коммит; изменения оставлены локально."
      return 1
    fi
  fi

  if git push --porcelain "$REMOTE" HEAD; then
    log "Резервная копия отправлена в $REMOTE."
  else
    log "Не удалось отправить резервную копию в $REMOTE; локальный коммит сохранён."
  fi
}

log "Автосинхронизация запущена. Интервал: ${INTERVAL_SECONDS} сек."

while true; do
  sync_once
  sleep "$INTERVAL_SECONDS"
done