#!/usr/bin/env bash
# Оборудыш — ЧИСТЫЙ СТАРТ (VPS/systemd). Бэкап и снос базы/загрузок перед прод-релизом.
# ВНИМАНИЕ: стирает ВСЕ заявки, брони 626, сообщения и пользователей.
# Запуск:  bash reset.sh [имя-systemd-сервиса]   (по умолчанию: oborudka)
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="$HERE/backup/$STAMP"
SERVICE="${1:-oborudka}"

echo "1) Останавливаю сервис $SERVICE…"
sudo systemctl stop "$SERVICE" || true
sleep 1

echo "2) Бэкап в $BACKUP"
mkdir -p "$BACKUP"
[ -f "$HERE/oborudka.db" ] && cp "$HERE/oborudka.db" "$BACKUP/" && echo "   БД сохранена"
[ -d "$HERE/uploads" ]     && cp -r "$HERE/uploads" "$BACKUP/" && echo "   uploads сохранены"

echo "3) Удаляю базу и uploads"
rm -f "$HERE/oborudka.db"
rm -rf "$HERE/uploads"

echo "4) Запускаю сервис $SERVICE…"
sudo systemctl start "$SERVICE"
echo "Готово. Схема создастся с нуля при старте — заявок ни у кого нет."
