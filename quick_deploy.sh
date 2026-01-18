#!/bin/bash

# Быстрый деплой PDF-MD бота на сервер 77.73.233.13
# Использование: bash quick_deploy.sh

set -e

SERVER="77.73.233.13"
USER="root"
REMOTE_DIR="/opt/bots/PDF-MD-BOT"

echo "🚀 Деплой PDF-MD бота на $SERVER"
echo "================================"
echo ""

# 1. Подключиться к серверу и выполнить деплой
ssh $USER@$SERVER << 'ENDSSH'
    # Скачать и выполнить deploy скрипт
    cd /tmp
    curl -o deploy.sh https://raw.githubusercontent.com/luckyhatslh-create/PDF-MD-BOT/main/deploy.sh
    chmod +x deploy.sh
    bash deploy.sh
ENDSSH

echo ""
echo "✅ Автоматическая установка завершена!"
echo ""
echo "Теперь нужно:"
echo "1. Настроить .env файл на сервере"
echo "2. Применить SQL миграцию в Supabase"
echo "3. Запустить бота"
echo ""
echo "Подключись к серверу для настройки:"
echo "  ssh $USER@$SERVER"
