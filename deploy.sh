#!/bin/bash

# Скрипт автоматического развертывания PDF-MD бота на VPS
# Использование: bash deploy.sh

set -e  # Остановка при ошибке

echo "🚀 PDF-MD Bot Deployment Script"
echo "================================"
echo ""

# Цвета для вывода
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Функция для логирования
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Проверка что скрипт запущен от root
if [ "$EUID" -ne 0 ]; then
    log_error "Запусти скрипт с правами root: sudo bash deploy.sh"
    exit 1
fi

# Конфигурация
BOT_DIR="/opt/bots/PDF-MD-BOT"
VENV_DIR="$BOT_DIR/venv"
SERVICE_NAME="pdf-md-bot"
REPO_URL="https://github.com/luckyhatslh-create/PDF-MD-BOT.git"

# Шаг 1: Обновление системы
log_info "Обновление системы..."
apt update && apt upgrade -y

# Шаг 2: Установка системных зависимостей
log_info "Установка системных зависимостей..."
apt install -y \
    python3 \
    python3-pip \
    python3-venv \
    tesseract-ocr \
    tesseract-ocr-rus \
    tesseract-ocr-eng \
    poppler-utils \
    git \
    curl \
    htop

# Проверка версии Python
PYTHON_VERSION=$(python3 --version | cut -d' ' -f2 | cut -d'.' -f1-2)
log_info "Python версия: $PYTHON_VERSION"

if (( $(echo "$PYTHON_VERSION < 3.10" | bc -l) )); then
    log_error "Python должен быть >= 3.10. Текущая версия: $PYTHON_VERSION"
    exit 1
fi

# Шаг 3: Создание директории для бота
log_info "Создание директории $BOT_DIR..."
mkdir -p /opt/bots

# Шаг 4: Клонирование репозитория
if [ -d "$BOT_DIR" ]; then
    log_warn "Директория $BOT_DIR уже существует"
    read -p "Удалить и клонировать заново? (y/n): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        log_info "Удаление старой директории..."
        rm -rf "$BOT_DIR"
        log_info "Клонирование репозитория..."
        git clone "$REPO_URL" "$BOT_DIR"
    else
        log_info "Пропуск клонирования. Используется существующая директория."
    fi
else
    log_info "Клонирование репозитория..."
    git clone "$REPO_URL" "$BOT_DIR"
fi

cd "$BOT_DIR"

# Шаг 5: Создание виртуального окружения
log_info "Создание виртуального окружения..."
python3 -m venv "$VENV_DIR"

# Активация venv
source "$VENV_DIR/bin/activate"

# Шаг 6: Установка Python зависимостей
log_info "Установка Python зависимостей..."
pip install --upgrade pip
pip install -r requirements.txt

# Шаг 7: Создание .env файла
if [ ! -f "$BOT_DIR/.env" ]; then
    log_warn "Файл .env не найден"
    if [ -f "$BOT_DIR/.env.example" ]; then
        log_info "Создание .env из .env.example..."
        cp "$BOT_DIR/.env.example" "$BOT_DIR/.env"
        log_warn "⚠️  ВАЖНО: Отредактируй .env файл перед запуском бота!"
        log_warn "nano $BOT_DIR/.env"
    else
        log_error ".env.example не найден. Создай .env вручную."
    fi
else
    log_info ".env файл уже существует"
fi

# Установить права на .env
chmod 600 "$BOT_DIR/.env"

# Шаг 8: Создание директории для логов
log_info "Создание директории для логов..."
mkdir -p "$BOT_DIR/logs"

# Шаг 9: Установка systemd service
log_info "Установка systemd service..."
if [ -f "$BOT_DIR/pdf-md-bot.service" ]; then
    cp "$BOT_DIR/pdf-md-bot.service" "/etc/systemd/system/$SERVICE_NAME.service"
    log_info "Systemd service установлен: /etc/systemd/system/$SERVICE_NAME.service"
else
    log_warn "pdf-md-bot.service не найден. Создай вручную."
fi

# Шаг 10: Перезагрузка systemd
log_info "Перезагрузка systemd daemon..."
systemctl daemon-reload

# Шаг 11: Включение автозапуска
log_info "Включение автозапуска..."
systemctl enable "$SERVICE_NAME"

# Финальная информация
echo ""
echo "================================"
log_info "✅ Установка завершена!"
echo "================================"
echo ""
log_warn "Перед запуском бота:"
echo "1. Отредактируй .env файл:"
echo "   nano $BOT_DIR/.env"
echo ""
echo "2. Примени SQL миграцию в Supabase Dashboard"
echo "   Файл: $BOT_DIR/migration_document_management.sql"
echo ""
echo "3. Запусти бота:"
echo "   sudo systemctl start $SERVICE_NAME"
echo ""
echo "4. Проверь статус:"
echo "   sudo systemctl status $SERVICE_NAME"
echo ""
echo "5. Просмотр логов:"
echo "   sudo journalctl -u $SERVICE_NAME -f"
echo "   tail -f $BOT_DIR/logs/bot.log"
echo ""
log_info "Директория бота: $BOT_DIR"
log_info "Systemd service: $SERVICE_NAME"
