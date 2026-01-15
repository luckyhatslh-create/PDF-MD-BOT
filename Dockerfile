# PDF-MD-Supabase Bot
# Автономный Docker образ с OCR и всеми зависимостями

FROM python:3.11-slim

# Метаданные
LABEL maintainer="PDF-MD-Supabase Bot"
LABEL description="Telegram bot для конвертации PDF в Markdown с OCR"

# Системные зависимости для OCR и обработки PDF
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Tesseract OCR с русским и английским языками
    tesseract-ocr \
    tesseract-ocr-rus \
    tesseract-ocr-eng \
    # Poppler для pdf2image (конвертация PDF в изображения)
    poppler-utils \
    # Библиотеки для Pillow
    libjpeg-dev \
    libpng-dev \
    # Очистка кэша apt
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Рабочая директория
WORKDIR /app

# Копируем requirements первым для кэширования слоя
COPY requirements.txt .

# Устанавливаем Python зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Копируем код приложения
COPY . .

# Создаём директорию для временных файлов
RUN mkdir -p /tmp/pdf_processor

# Переменные окружения по умолчанию
ENV PYTHONUNBUFFERED=1
ENV TEMP_DIR=/tmp/pdf_processor

# Healthcheck (проверяем что Python работает)
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import bot" || exit 1

# Запуск бота
CMD ["python", "bot.py"]
