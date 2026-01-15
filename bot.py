"""
Telegram Bot для PDF → MD → Supabase

Команды:
/start - Начало работы
/help - Справка
/list - Список загруженных документов
/search <запрос> - Поиск по документам

Отправьте PDF файл для конвертации.
"""

import os
import asyncio
import logging
from pathlib import Path
from enum import Enum, auto
from dataclasses import dataclass
from typing import Optional

from telegram import (
    Update, 
    InlineKeyboardButton, 
    InlineKeyboardMarkup,
    Document
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)

from config import config
from pdf_parser import parse_pdf_to_markdown, ParsedDocument
from supabase_manager import (
    SupabaseManager, 
    create_sql_migration_file,
    generate_setup_sql
)

# Логирование
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


class OutputMode(Enum):
    """Режимы вывода"""
    MD_ONLY = auto()      # Только MD файл
    SUPABASE_SQL = auto() # MD + SQL для Supabase
    SUPABASE_API = auto() # Прямая загрузка в Supabase


@dataclass
class UserSession:
    """Сессия пользователя"""
    pdf_path: Optional[str] = None
    parsed_doc: Optional[ParsedDocument] = None
    mode: OutputMode = OutputMode.MD_ONLY


# Хранилище сессий (в продакшене использовать Redis)
user_sessions: dict[int, UserSession] = {}


# Клавиатуры
def get_output_mode_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора режима вывода"""
    keyboard = [
        [InlineKeyboardButton("📝 Только MD файл", callback_data="mode_md")],
        [InlineKeyboardButton("📊 MD + SQL для Supabase", callback_data="mode_sql")],
    ]
    
    # Добавляем прямую загрузку если настроен Supabase
    if config.SUPABASE_URL and config.SUPABASE_KEY:
        keyboard.append([
            InlineKeyboardButton("🚀 Загрузить в Supabase", callback_data="mode_api")
        ])
    
    return InlineKeyboardMarkup(keyboard)


def get_confirm_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура подтверждения"""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Да", callback_data="confirm_yes"),
            InlineKeyboardButton("❌ Нет", callback_data="confirm_no")
        ]
    ])


# Команды
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start"""
    welcome_text = """
🔄 **PDF → Markdown → Supabase Bot**

Конвертирую PDF книги и методички в структурированный Markdown для работы с нейросетями.

**Возможности:**
• Извлечение текста с сохранением структуры
• Распознавание заголовков и оглавления
• Извлечение таблиц в MD формат
• Разбиение на чанки для RAG
• Интеграция с Supabase (векторный поиск)

**Как использовать:**
1. Отправьте PDF файл
2. Выберите формат выгрузки
3. Получите результат!

📎 Лимит: до {max_size} МБ, до {max_pages} страниц
""".format(max_size=config.MAX_FILE_SIZE_MB, max_pages=config.MAX_PAGES)
    
    await update.message.reply_text(
        welcome_text,
        parse_mode='Markdown'
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /help"""
    help_text = """
📖 **Справка по боту**

**Команды:**
/start - Начало работы
/help - Эта справка
/list - Список документов в Supabase
/search <запрос> - Поиск по документам
/setup - SQL для настройки Supabase

**Форматы вывода:**

1. **Только MD** - получите .md файл документа

2. **MD + SQL** - получите:
   • .md файл документа
   • .sql файл для загрузки в Supabase

3. **Прямая загрузка** - документ сразу загружается в вашу БД Supabase

**Почему MD лучше для AI?**
• Четкая иерархия заголовков
• Размеченные таблицы
• Меньше мусорных символов
• Семантическая структура
• Компактнее чем исходный PDF
"""
    await update.message.reply_text(help_text, parse_mode='Markdown')


async def setup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /setup - получить SQL для настройки Supabase"""
    await update.message.reply_text(
        "📤 Отправляю SQL скрипт для настройки Supabase...",
    )
    
    sql_content = generate_setup_sql()
    
    # Создаем временный файл
    os.makedirs(config.TEMP_DIR, exist_ok=True)
    sql_path = Path(config.TEMP_DIR) / "supabase_setup.sql"
    sql_path.write_text(sql_content, encoding='utf-8')
    
    await update.message.reply_document(
        document=open(sql_path, 'rb'),
        filename="supabase_setup.sql",
        caption="""
📋 **SQL для настройки Supabase**

1. Откройте SQL Editor в Supabase Dashboard
2. Выполните этот скрипт
3. Таблицы `documents` и `document_chunks` будут созданы

⚠️ Убедитесь, что расширение `vector` включено!
        """
    )


async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /list - список документов"""
    if not config.SUPABASE_URL or not config.SUPABASE_KEY:
        await update.message.reply_text(
            "❌ Supabase не настроен. Задайте SUPABASE_URL и SUPABASE_KEY."
        )
        return
    
    try:
        manager = SupabaseManager(config.SUPABASE_URL, config.SUPABASE_KEY)
        docs = manager.list_documents(limit=20)
        
        if not docs:
            await update.message.reply_text("📚 Документов пока нет.")
            return
        
        text = "📚 **Загруженные документы:**\n\n"
        for doc in docs:
            text += f"• **{doc['title']}**\n"
            text += f"  Автор: {doc.get('author', 'N/A')}\n"
            text += f"  Страниц: {doc.get('page_count', 'N/A')}\n\n"
        
        await update.message.reply_text(text, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Ошибка list: {e}")
        await update.message.reply_text(f"❌ Ошибка: {e}")


async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /search - поиск по документам"""
    if not context.args:
        await update.message.reply_text("Использование: /search <поисковый запрос>")
        return
    
    query = ' '.join(context.args)
    
    if not config.SUPABASE_URL or not config.SUPABASE_KEY:
        await update.message.reply_text("❌ Supabase не настроен.")
        return
    
    try:
        manager = SupabaseManager(config.SUPABASE_URL, config.SUPABASE_KEY)
        results = manager.search_text(query, limit=5)
        
        if not results:
            await update.message.reply_text(f"🔍 По запросу «{query}» ничего не найдено.")
            return
        
        text = f"🔍 **Результаты по запросу «{query}»:**\n\n"
        for i, r in enumerate(results, 1):
            content_preview = r['content'][:200] + "..." if len(r['content']) > 200 else r['content']
            text += f"**{i}. {r.get('heading', 'Без заголовка')}**\n"
            text += f"Страница: {r.get('page_number', 'N/A')}\n"
            text += f"```\n{content_preview}\n```\n\n"
        
        await update.message.reply_text(text, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Ошибка search: {e}")
        await update.message.reply_text(f"❌ Ошибка поиска: {e}")


# Обработка PDF
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка входящего документа"""
    document: Document = update.message.document
    user_id = update.effective_user.id
    
    # Проверка типа файла
    if not document.file_name.lower().endswith('.pdf'):
        await update.message.reply_text(
            "❌ Пожалуйста, отправьте PDF файл."
        )
        return
    
    # Проверка размера
    size_mb = document.file_size / (1024 * 1024)
    if size_mb > config.MAX_FILE_SIZE_MB:
        await update.message.reply_text(
            f"❌ Файл слишком большой ({size_mb:.1f} МБ). Лимит: {config.MAX_FILE_SIZE_MB} МБ."
        )
        return
    
    # Сообщение о загрузке
    status_msg = await update.message.reply_text(
        "📥 Загружаю файл..."
    )
    
    try:
        # Скачиваем файл
        os.makedirs(config.TEMP_DIR, exist_ok=True)
        pdf_path = Path(config.TEMP_DIR) / f"{user_id}_{document.file_name}"
        
        file = await document.get_file()
        await file.download_to_drive(str(pdf_path))
        
        # Сохраняем в сессию
        user_sessions[user_id] = UserSession(pdf_path=str(pdf_path))
        
        await status_msg.edit_text(
            f"✅ Файл загружен: **{document.file_name}**\n"
            f"📄 Размер: {size_mb:.1f} МБ\n\n"
            "Выберите формат выгрузки:",
            parse_mode='Markdown',
            reply_markup=get_output_mode_keyboard()
        )
        
    except Exception as e:
        logger.error(f"Ошибка загрузки: {e}")
        await status_msg.edit_text(f"❌ Ошибка загрузки: {e}")


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка нажатий кнопок"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    session = user_sessions.get(user_id)
    
    if not session or not session.pdf_path:
        await query.edit_message_text("❌ Сессия истекла. Отправьте PDF заново.")
        return
    
    data = query.data
    
    # Выбор режима
    if data.startswith("mode_"):
        mode_map = {
            "mode_md": OutputMode.MD_ONLY,
            "mode_sql": OutputMode.SUPABASE_SQL,
            "mode_api": OutputMode.SUPABASE_API
        }
        session.mode = mode_map.get(data, OutputMode.MD_ONLY)
        await process_pdf(query, session)
    
    # Подтверждение
    elif data == "confirm_yes":
        await upload_to_supabase(query, session)
    
    elif data == "confirm_no":
        await query.edit_message_text("❌ Отменено.")


async def process_pdf(query, session: UserSession):
    """Обработка PDF файла"""
    await query.edit_message_text("⏳ Обрабатываю PDF... Это может занять минуту.")
    
    try:
        # Парсим PDF
        parsed = parse_pdf_to_markdown(
            session.pdf_path,
            chunk_size=config.CHUNK_SIZE,
            chunk_overlap=config.CHUNK_OVERLAP
        )
        session.parsed_doc = parsed
        
        # Создаем MD файл
        md_filename = Path(session.pdf_path).stem + ".md"
        md_path = Path(config.TEMP_DIR) / md_filename
        md_path.write_text(parsed.full_markdown, encoding='utf-8')
        
        # Статистика
        stats = (
            f"📊 **Обработано:**\n"
            f"• Название: {parsed.metadata.title}\n"
            f"• Страниц: {parsed.metadata.page_count}\n"
            f"• Чанков: {len(parsed.chunks)}\n"
            f"• Размер MD: {len(parsed.full_markdown) / 1024:.1f} КБ\n"
        )
        
        # Отправляем MD
        await query.message.reply_document(
            document=open(md_path, 'rb'),
            filename=md_filename,
            caption=stats,
            parse_mode='Markdown'
        )
        
        # SQL режим
        if session.mode == OutputMode.SUPABASE_SQL:
            sql_content = create_sql_migration_file(parsed, include_setup=False)
            sql_filename = Path(session.pdf_path).stem + "_supabase.sql"
            sql_path = Path(config.TEMP_DIR) / sql_filename
            sql_path.write_text(sql_content, encoding='utf-8')
            
            await query.message.reply_document(
                document=open(sql_path, 'rb'),
                filename=sql_filename,
                caption=(
                    "📋 **SQL для Supabase**\n\n"
                    "Выполните этот скрипт в SQL Editor.\n"
                    "Таблицы должны быть созданы (/setup)."
                ),
                parse_mode='Markdown'
            )
        
        # API режим
        elif session.mode == OutputMode.SUPABASE_API:
            await query.message.reply_text(
                "🚀 Загрузить документ в Supabase?",
                reply_markup=get_confirm_keyboard()
            )
            return
        
        await query.edit_message_text("✅ Готово!")
        
    except Exception as e:
        logger.error(f"Ошибка обработки: {e}")
        await query.edit_message_text(f"❌ Ошибка обработки: {e}")


async def upload_to_supabase(query, session: UserSession):
    """Загрузка в Supabase через API"""
    if not session.parsed_doc:
        await query.edit_message_text("❌ Документ не обработан.")
        return
    
    await query.edit_message_text("⏳ Загружаю в Supabase...")
    
    try:
        manager = SupabaseManager(config.SUPABASE_URL, config.SUPABASE_KEY)
        doc_id = manager.upload_document(session.parsed_doc)
        
        await query.edit_message_text(
            f"✅ **Загружено в Supabase!**\n\n"
            f"Document ID: `{doc_id}`\n"
            f"Чанков: {len(session.parsed_doc.chunks)}\n\n"
            f"Используйте /search для поиска.",
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"Ошибка Supabase: {e}")
        await query.edit_message_text(f"❌ Ошибка загрузки: {e}")


def main():
    """Запуск бота"""
    if not config.TELEGRAM_BOT_TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN не задан!")
        print("Установите переменную окружения:")
        print("export TELEGRAM_BOT_TOKEN='your_token_here'")
        return
    
    # Создаем приложение
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    
    # Регистрируем обработчики
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("setup", setup_command))
    app.add_handler(CommandHandler("list", list_command))
    app.add_handler(CommandHandler("search", search_command))
    
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(CallbackQueryHandler(handle_callback))
    
    # Запускаем
    print("🤖 Бот запущен!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
