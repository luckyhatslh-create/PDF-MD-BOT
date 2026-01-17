# Развертывание бота на VPS сервере

## Сервер: 77.73.233.13

## Шаг 1: Подключение к серверу

```bash
ssh root@77.73.233.13
# или с пользователем:
# ssh username@77.73.233.13
```

## Шаг 2: Установка зависимостей

```bash
# Обновить систему
sudo apt update && sudo apt upgrade -y

# Установить Python 3.11+ и pip
sudo apt install python3 python3-pip python3-venv -y

# Установить системные зависимости для PDF и OCR
sudo apt install -y \
    tesseract-ocr \
    tesseract-ocr-rus \
    tesseract-ocr-eng \
    poppler-utils \
    git

# Проверить версии
python3 --version  # должно быть >= 3.11
tesseract --version
```

## Шаг 3: Клонировать репозиторий

```bash
# Создать директорию для проектов
mkdir -p /opt/bots
cd /opt/bots

# Клонировать из GitHub
git clone https://github.com/luckyhatslh-create/PDF-MD-BOT.git
cd PDF-MD-BOT

# Или загрузить с локального компьютера через scp:
# scp -r /Users/stanislavstruckov/Documents/Progects/pdf_md_supabase root@77.73.233.13:/opt/bots/PDF-MD-BOT
```

## Шаг 4: Создать виртуальное окружение

```bash
cd /opt/bots/PDF-MD-BOT

# Создать venv
python3 -m venv venv

# Активировать
source venv/bin/activate

# Установить зависимости
pip install --upgrade pip
pip install -r requirements.txt
```

## Шаг 5: Настроить .env файл

```bash
# Создать .env из примера
cp .env.example .env

# Отредактировать (используй nano или vim)
nano .env
```

**Заполни переменные:**
```env
# Telegram Bot
TELEGRAM_BOT_TOKEN=your_bot_token_from_@BotFather

# Supabase
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your_anon_key
SUPABASE_SERVICE_KEY=your_service_role_key

# OpenAI (для эмбеддингов и Vision AI)
OPENAI_API_KEY=sk-...

# OCR и Vision AI
ENABLE_OCR=false
ANALYZE_IMAGES=false

# Keepalive
KEEPALIVE_INTERVAL_DAYS=3
KEEPALIVE_ADMIN_USER_ID=your_telegram_user_id
KEEPALIVE_LOG_FILE=keepalive.log

# Пути
TEMP_DIR=/tmp/pdf_processor
```

**Узнать свой Telegram User ID:**
```
Напиши боту @userinfobot в Telegram
```

## Шаг 6: Применить SQL миграцию в Supabase

1. Открой Supabase Dashboard: https://supabase.com/dashboard
2. Выбери проект
3. SQL Editor → New Query
4. Скопируй содержимое файла `migration_document_management.sql`
5. Выполни (Run)

Или используй Python:
```bash
# Активировать venv
source venv/bin/activate

# Запустить генерацию SQL
python3 -c "
from supabase_manager import SupabaseManager
manager = SupabaseManager()
sql = manager.generate_migration_sql()
print(sql)
"
```

## Шаг 7: Тестовый запуск

```bash
# Активировать venv
source venv/bin/activate

# Запустить бота
python3 bot.py
```

**Проверь:**
- Логи в консоли: `✅ Keepalive job зарегистрирован`
- Через 10 секунд: первый keepalive ping
- Отправь `/start` боту в Telegram
- Проверь `/keepalive_status`

**Остановка:** `Ctrl + C`

## Шаг 8: Настроить автозапуск через systemd

Создай systemd service файл:

```bash
sudo nano /etc/systemd/system/pdf-md-bot.service
```

**Содержимое:**
```ini
[Unit]
Description=PDF-MD Telegram Bot with Supabase
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/bots/PDF-MD-BOT
Environment="PATH=/opt/bots/PDF-MD-BOT/venv/bin"
ExecStart=/opt/bots/PDF-MD-BOT/venv/bin/python3 /opt/bots/PDF-MD-BOT/bot.py
Restart=always
RestartSec=10

# Логи
StandardOutput=append:/opt/bots/PDF-MD-BOT/logs/bot.log
StandardError=append:/opt/bots/PDF-MD-BOT/logs/bot_error.log

[Install]
WantedBy=multi-user.target
```

**Создать директорию для логов:**
```bash
mkdir -p /opt/bots/PDF-MD-BOT/logs
```

**Включить и запустить сервис:**
```bash
# Перезагрузить systemd
sudo systemctl daemon-reload

# Включить автозапуск
sudo systemctl enable pdf-md-bot

# Запустить
sudo systemctl start pdf-md-bot

# Проверить статус
sudo systemctl status pdf-md-bot
```

## Шаг 9: Управление ботом

**Проверка статуса:**
```bash
sudo systemctl status pdf-md-bot
```

**Просмотр логов:**
```bash
# Логи systemd
sudo journalctl -u pdf-md-bot -f

# Логи бота
tail -f /opt/bots/PDF-MD-BOT/logs/bot.log

# Логи keepalive
tail -f /opt/bots/PDF-MD-BOT/keepalive.log
```

**Перезапуск:**
```bash
sudo systemctl restart pdf-md-bot
```

**Остановка:**
```bash
sudo systemctl stop pdf-md-bot
```

**Отключить автозапуск:**
```bash
sudo systemctl disable pdf-md-bot
```

## Шаг 10: Обновление кода

```bash
cd /opt/bots/PDF-MD-BOT

# Остановить бота
sudo systemctl stop pdf-md-bot

# Получить последние изменения
git pull origin main

# Активировать venv
source venv/bin/activate

# Обновить зависимости (если изменились)
pip install -r requirements.txt --upgrade

# Применить новые миграции (если есть)
# ... запустить SQL в Supabase

# Запустить бота
sudo systemctl start pdf-md-bot

# Проверить статус
sudo systemctl status pdf-md-bot
```

## Шаг 11: Мониторинг

**Keepalive статус через Telegram:**
```
/keepalive_status - проверка последних пингов
/keepalive_test - тестовый ping (только админ)
```

**Системные ресурсы:**
```bash
# CPU и память
htop

# Использование диска
df -h

# Размер логов
du -sh /opt/bots/PDF-MD-BOT/logs/*
```

**Очистка старых логов:**
```bash
# Очистить логи старше 7 дней
find /opt/bots/PDF-MD-BOT/logs/ -name "*.log" -mtime +7 -delete
```

## Troubleshooting

**Бот не запускается:**
```bash
# Проверить логи
sudo journalctl -u pdf-md-bot -n 50

# Проверить .env
cat .env | grep -v "^#"

# Проверить права доступа
ls -la /opt/bots/PDF-MD-BOT/

# Тестовый запуск вручную
cd /opt/bots/PDF-MD-BOT
source venv/bin/activate
python3 bot.py
```

**OCR не работает:**
```bash
# Проверить Tesseract
tesseract --list-langs

# Должны быть: rus, eng

# Если нет русского:
sudo apt install tesseract-ocr-rus
```

**Нет памяти для PDF:**
```bash
# Увеличить swap
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile

# Сделать постоянным
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

**Keepalive не работает:**
```bash
# Проверить лог
cat /opt/bots/PDF-MD-BOT/keepalive.log

# Проверить подключение к Supabase
cd /opt/bots/PDF-MD-BOT
source venv/bin/activate
python3 -c "
from supabase_manager import SupabaseManager
from config import config
manager = SupabaseManager(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)
result = manager.ping_keepalive()
print(result)
"
```

## Безопасность

**Файрволл (UFW):**
```bash
# Установить UFW
sudo apt install ufw

# Разрешить SSH
sudo ufw allow 22/tcp

# Включить файрволл
sudo ufw enable

# Проверить статус
sudo ufw status
```

**Ограничить доступ к .env:**
```bash
chmod 600 /opt/bots/PDF-MD-BOT/.env
```

**Создать отдельного пользователя (рекомендуется):**
```bash
# Создать пользователя
sudo adduser botuser --disabled-password

# Дать права на директорию
sudo chown -R botuser:botuser /opt/bots/PDF-MD-BOT

# Изменить User в systemd service
sudo nano /etc/systemd/system/pdf-md-bot.service
# User=botuser

# Перезапустить
sudo systemctl daemon-reload
sudo systemctl restart pdf-md-bot
```

## Backup

**Резервное копирование .env:**
```bash
# Локально на сервере
cp /opt/bots/PDF-MD-BOT/.env /root/pdf-md-bot.env.backup

# Скачать на локальный компьютер
scp root@77.73.233.13:/opt/bots/PDF-MD-BOT/.env ~/Desktop/pdf-md-bot.env.backup
```

**Резервное копирование Supabase:**
- Supabase автоматически делает бэкапы
- Можно экспортировать данные через Dashboard → Database → Backups

## Полезные команды

```bash
# Проверка работы бота
curl -s https://api.telegram.org/bot<YOUR_TOKEN>/getMe | jq

# Размер директории
du -sh /opt/bots/PDF-MD-BOT

# Процессы Python
ps aux | grep python

# Сетевые подключения
sudo netstat -tulpn | grep python

# Использование памяти
free -h
```

---

## Чек-лист деплоя

- [ ] Сервер обновлен (apt update && upgrade)
- [ ] Python 3.11+ установлен
- [ ] Tesseract OCR установлен (rus + eng)
- [ ] Репозиторий склонирован
- [ ] Virtual environment создан
- [ ] Зависимости установлены (pip install -r requirements.txt)
- [ ] .env файл настроен со всеми ключами
- [ ] SQL миграция применена в Supabase
- [ ] Тестовый запуск успешен (python3 bot.py)
- [ ] Systemd service создан и включен
- [ ] Бот автоматически запускается
- [ ] Логи пишутся корректно
- [ ] /keepalive_status работает
- [ ] Первый keepalive ping выполнен
- [ ] Firewall настроен (UFW)
- [ ] .env защищен (chmod 600)
- [ ] Backup .env сделан

---

**Готово!** Бот работает 24/7 с автоматическим перезапуском при сбоях.
