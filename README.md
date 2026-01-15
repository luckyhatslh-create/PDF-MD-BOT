# 📄 PDF-MD-Supabase Bot

Telegram бот для конвертации PDF книг и методичек в структурированный Markdown с интеграцией в Supabase для семантического поиска.

## 🎯 Зачем это нужно?

Нейросети работают эффективнее с **Markdown**, чем с PDF. Этот бот не просто извлекает текст, а восстанавливает структуру документа, обрабатывает таблицы и изображения с помощью ИИ.

| Аспект | PDF | Markdown |
|--------|-----|----------|
| Структура | Визуальная (шрифты, позиции) | Семантическая (заголовки, списки) |
| Таблицы | Координаты ячеек | Текстовые `| |` |
| Изображения | Статические блоки | Текстовое описание (Vision AI) |
| Сканы | Текст недоступен | Распознавание через OCR |
| RAG | Проблематично | Идеально |

## ✨ Основные обновления (v2.0)

- **🧠 Vision AI Integration**: Автоматический анализ изображений, формул и диаграмм с помощью OpenAI GPT-4o.
- **👁️ Advanced OCR**: Поддержка сканированных документов через Tesseract OCR (включая русский язык).
- **📐 Intelligent Font Analysis**: Улучшенное определение иерархии заголовков (H1-H3) по размеру шрифта.
- **📑 Enhanced Paragraph Assembly**: Умная сборка абзацев, учитывающая переносы слов и разрывы строк.

## 🏗 Архитектура

```
┌─────────────┐     ┌───────────────────┐     ┌─────────────┐
│  Telegram   │────▶│    PDF Processor  │────▶│  Markdown   │
│    User     │     │ (OCR + Vision AI) │     │   Output    │
└─────────────┘     └───────────────────┘     └──────┬──────┘
                                                     │
                    ┌──────────────────────────┼──────────────────────┐
                    ▼                          ▼                      ▼
            ┌───────────────┐         ┌───────────────┐      ┌────────────────┐
            │   .md файл    │         │   .sql файл   │      │    Supabase    │
            │  (скачать)    │         │  (для вставки)│      │   (API/Vector) │
            └───────────────┘         └───────────────┘      └────────────────┘
```

## 🚀 Быстрый старт

### 1. Системные зависимости

Для работы OCR и обработки изображений требуются `Tesseract` и `Poppler`.

**MacOS:**
```bash
brew install tesseract tesseract-lang poppler
```

**Linux (Ubuntu/Debian):**
```bash
sudo apt-get install tesseract-ocr tesseract-ocr-rus poppler-utils
```

### 2. Установка зависимостей Python

```bash
cd pdf_md_supabase
python -m venv venv
source venv/bin/activate  # или venv\Scripts\activate на Windows
pip install -r requirements.txt
```

### 3. Настройка .env

Создайте файл `.env` на основе `.env.example`:

```env
TELEGRAM_BOT_TOKEN=your_token
OPENAI_API_KEY=your_key  # Для Voice AI и эмбеддингов
ENABLE_OCR=true         # Включить распознавание сканов
ANALYZE_IMAGES=true     # Включить описание картинок через GPT-4o
```

### 4. Запуск

```bash
python bot.py
```

## 📦 Форматы выгрузки

1. **Только MD файл**: Полная структура книги в одном файле.
2. **MD + SQL для Supabase**: Готовый скрипт для импорта в вашу базу данных.
3. **Прямая загрузка**: Мгновенная отправка в Supabase через API.

## 🐳 Docker Deployment

Проект полностью готов к запуску в контейнере (все зависимости уже внутри Dockerfile).

```bash
docker-compose up -d --build
```

## 🗄 Настройка Supabase

1. Включите расширение `vector`: `create extension if not exists vector;`
2. Отправьте боту `/setup`, чтобы получить SQL-скрипт для создания необходимых таблиц.
3. Добавьте `SUPABASE_URL` и `SUPABASE_SERVICE_KEY` в ваш `.env`.

## 📄 License

MIT

---

**Made with ❤️ for better AI understanding of documents**
