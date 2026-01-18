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
from datetime import datetime

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

from config import config, PROCESSING_PROFILES, KEEPALIVE_INTERVAL_DAYS, KEEPALIVE_ADMIN_USER_ID, KEEPALIVE_LOG_FILE
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

# Константы keepalive для предотвращения паузы Supabase Free Tier
KEEPALIVE_INTERVAL_SECONDS = KEEPALIVE_INTERVAL_DAYS * 24 * 60 * 60  # 3 дня = 259200 сек


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
    # Новые поля для расширенного workflow
    processing_profile: Optional[str] = None
    custom_title: Optional[str] = None
    state: str = "idle"  # idle, awaiting_profile, processing, awaiting_name, awaiting_mode, awaiting_doc_action
    selected_doc_id: Optional[str] = None
    tags: Optional[list] = None
    doc_list_page: int = 0


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


def get_profile_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора профиля обработки"""
    keyboard = []
    for profile_id, profile in PROCESSING_PROFILES.items():
        keyboard.append([
            InlineKeyboardButton(
                text=f"{profile['name']}\n{profile['description']}",
                callback_data=f"profile_{profile_id}"
            )
        ])
    return InlineKeyboardMarkup(keyboard)


def get_skip_name_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для пропуска ввода имени"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⏭️ Пропустить", callback_data="skip_name")]
    ])


def get_document_list_keyboard(docs: list, page: int = 0, per_page: int = 5) -> InlineKeyboardMarkup:
    """Клавиатура со списком документов для выбора"""
    keyboard = []
    start_idx = page * per_page
    end_idx = min(start_idx + per_page, len(docs))

    for doc in docs[start_idx:end_idx]:
        display_name = doc.get('user_custom_title') or doc.get('title', 'Без названия')
        display_name = display_name[:35] + "..." if len(display_name) > 35 else display_name
        keyboard.append([
            InlineKeyboardButton(
                text=f"📄 {display_name}",
                callback_data=f"doc_select_{doc['id']}"
            )
        ])

    # Pagination buttons
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("⬅️ Назад", callback_data=f"doc_page_{page-1}"))
    if end_idx < len(docs):
        nav_row.append(InlineKeyboardButton("➡️ Вперёд", callback_data=f"doc_page_{page+1}"))
    if nav_row:
        keyboard.append(nav_row)

    keyboard.append([InlineKeyboardButton("❌ Закрыть", callback_data="cancel")])

    return InlineKeyboardMarkup(keyboard)


def get_document_actions_keyboard(doc_id: str) -> InlineKeyboardMarkup:
    """Клавиатура действий с документом"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Переименовать", callback_data=f"doc_rename_{doc_id}")],
        [InlineKeyboardButton("🏷️ Редактировать теги", callback_data=f"doc_tags_{doc_id}")],
        [InlineKeyboardButton("📤 Экспорт в MD", callback_data=f"doc_export_{doc_id}")],
        [InlineKeyboardButton("🗑️ Удалить", callback_data=f"doc_delete_{doc_id}")],
        [InlineKeyboardButton("⬅️ К списку", callback_data="doc_back_to_list")],
    ])


def get_delete_confirm_keyboard(doc_id: str) -> InlineKeyboardMarkup:
    """Клавиатура подтверждения удаления"""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Да, удалить", callback_data=f"delete_confirm_{doc_id}"),
            InlineKeyboardButton("❌ Отмена", callback_data="delete_cancel")
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
    help_text = (
        "📖 Справка по боту\n\n"
        "Команды:\n"
        "/start - Начало работы\n"
        "/help - Эта справка\n"
        "/list - Управление документами\n"
        "/stats - Статистика\n"
        "/search запрос - Поиск\n"
        "/setup - SQL для Supabase\n\n"
        "Как использовать:\n"
        "1. Отправьте PDF\n"
        "2. Выберите профиль\n"
        "3. Введите название\n"
        "4. Выберите формат\n\n"
        "Профили:\n"
        "📖 Худ. лит. - текст\n"
        "📄 Тех. док. - таблицы\n"
        "🔬 Тех. лит. - всё\n"
        "📐 Чертежи - схемы\n"
        "⚙️ Универсал\n\n"
        "Управление (/list):\n"
        "• Переименование\n"
        "• Теги\n"
        "• Экспорт MD\n"
        "• Удаление"
    )
    await update.message.reply_text(help_text)


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
    """Команда /list - интерактивный список документов с управлением"""
    user_id = update.effective_user.id

    if not config.SUPABASE_URL or not config.SUPABASE_KEY:
        await update.message.reply_text(
            "❌ Supabase не настроен. Задайте SUPABASE_URL и SUPABASE_KEY."
        )
        return

    try:
        manager = SupabaseManager(config.SUPABASE_URL, config.SUPABASE_KEY)
        # Используем list_user_documents вместо RPC (работает со старыми документами)
        docs = manager.list_user_documents(user_id=user_id, limit=50)

        if not docs:
            await update.message.reply_text("📚 У вас пока нет документов.")
            return

        # Store docs in context for pagination
        context.user_data['doc_list'] = docs

        # Initialize session for document management
        user_sessions[user_id] = UserSession(state="awaiting_doc_selection", doc_list_page=0)

        await update.message.reply_text(
            f"📚 **Ваши документы ({len(docs)}):**\n"
            "Выберите документ для управления:",
            parse_mode='Markdown',
            reply_markup=get_document_list_keyboard(docs, page=0)
        )

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

        # Сохраняем в сессию с новым состоянием
        user_sessions[user_id] = UserSession(
            pdf_path=str(pdf_path),
            state="awaiting_profile"
        )

        # Показываем выбор профиля ПЕРЕД обработкой
        await status_msg.edit_text(
            f"✅ Файл загружен: **{document.file_name}**\n"
            f"📄 Размер: {size_mb:.1f} МБ\n\n"
            "🎯 **Выберите тип документа для обработки:**",
            parse_mode='Markdown',
            reply_markup=get_profile_keyboard()
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
    data = query.data

    # Cancel / Close
    if data == "cancel":
        if session:
            session.state = "idle"
        await query.edit_message_text("❌ Операция отменена.")
        return

    # Skip custom name
    if data == "skip_name":
        if session and session.state == "awaiting_name":
            session.custom_title = None
            session.state = "awaiting_mode"
            await query.edit_message_text(
                "📦 Выберите формат выгрузки:",
                reply_markup=get_output_mode_keyboard()
            )
        return

    # Profile selection (NEW: первый шаг после загрузки PDF)
    if data.startswith("profile_"):
        if not session or not session.pdf_path:
            await query.edit_message_text("❌ Сессия истекла. Отправьте PDF заново.")
            return

        profile_id = data.replace("profile_", "")
        session.processing_profile = profile_id
        session.state = "processing"

        # Запускаем обработку с выбранным профилем
        await process_pdf_with_profile(query, session, user_id)
        return

    # Output mode selection (после ввода имени)
    if data.startswith("mode_"):
        if not session or session.state != "awaiting_mode":
            await query.edit_message_text("❌ Сессия истекла. Отправьте PDF заново.")
            return

        mode_map = {
            "mode_md": OutputMode.MD_ONLY,
            "mode_sql": OutputMode.SUPABASE_SQL,
            "mode_api": OutputMode.SUPABASE_API
        }
        session.mode = mode_map.get(data, OutputMode.MD_ONLY)
        await finalize_output(query, session, user_id)
        return

    # Document management callbacks
    if data.startswith("doc_"):
        await handle_document_management_callback(query, context, user_id, data)
        return

    # Delete confirmation
    if data.startswith("delete_"):
        await handle_delete_callback(query, user_id, data)
        return

    # Supabase upload confirmation
    if data == "confirm_yes":
        if session and session.state == "awaiting_confirm_upload":
            await upload_to_supabase(query, session, user_id)
        return

    if data == "confirm_no":
        if session:
            session.state = "idle"
        await query.edit_message_text("❌ Отменено.")
        return


async def process_pdf_with_profile(query, session: UserSession, user_id: int):
    """Обработка PDF с выбранным профилем"""
    profile = PROCESSING_PROFILES.get(session.processing_profile, PROCESSING_PROFILES["universal"])

    await query.edit_message_text(
        f"⏳ Обрабатываю PDF...\n"
        f"📋 Профиль: {profile['name']}\n"
        f"Это может занять несколько минут."
    )

    try:
        # Парсим PDF с настройками профиля
        parsed = parse_pdf_to_markdown(
            session.pdf_path,
            chunk_size=profile['chunk_size'],
            chunk_overlap=profile['chunk_overlap'],
            detect_headers=profile.get('detect_headers', True),
            enable_ocr=profile.get('enable_ocr', False),
            ocr_languages=profile.get('ocr_languages', 'rus+eng'),
            analyze_images=profile.get('analyze_images', False),
            extract_tables=profile.get('extract_tables', True)
        )
        session.parsed_doc = parsed

        # Обработка завершена - запрашиваем имя
        session.state = "awaiting_name"

        stats = (
            f"✅ **Обработка завершена!**\n\n"
            f"📊 **Статистика:**\n"
            f"• Название: {parsed.metadata.title}\n"
            f"• Страниц: {parsed.metadata.page_count}\n"
            f"• Чанков: {len(parsed.chunks)}\n"
            f"• Размер MD: {len(parsed.full_markdown) / 1024:.1f} КБ\n"
            f"• Профиль: {profile['name']}\n\n"
            f"📝 **Введите своё название для документа**\n"
            f"(или нажмите кнопку чтобы пропустить):"
        )

        await query.edit_message_text(
            stats,
            parse_mode='Markdown',
            reply_markup=get_skip_name_keyboard()
        )

    except Exception as e:
        logger.error(f"Ошибка обработки: {e}")
        session.state = "idle"
        await query.edit_message_text(f"❌ Ошибка обработки: {e}")


async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка текстового ввода (для имени документа, тегов и т.д.)"""
    user_id = update.effective_user.id
    session = user_sessions.get(user_id)
    text = update.message.text.strip()

    if not session:
        return  # Ignore if no active session

    # Custom name input
    if session.state == "awaiting_name":
        session.custom_title = text
        session.state = "awaiting_mode"

        await update.message.reply_text(
            f"✅ Название: **{text}**\n\n"
            "📦 Выберите формат выгрузки:",
            parse_mode='Markdown',
            reply_markup=get_output_mode_keyboard()
        )
        return

    # Tags input
    if session.state == "awaiting_tags":
        tags = [t.strip() for t in text.split(',') if t.strip()]
        await update_document_tags(update, session, tags)
        return

    # Rename document
    if session.state == "awaiting_rename":
        await rename_document(update, session, text)
        return


async def finalize_output(query, session: UserSession, user_id: int):
    """Финальная отправка результата"""
    parsed = session.parsed_doc
    profile = PROCESSING_PROFILES.get(session.processing_profile, {})

    # Create MD file
    md_filename = Path(session.pdf_path).stem + ".md"
    md_path = Path(config.TEMP_DIR) / md_filename
    md_path.write_text(parsed.full_markdown, encoding='utf-8')

    # Prepare display name
    display_name = session.custom_title or parsed.metadata.title

    # Statistics
    stats = (
        f"📊 **Результат:**\n"
        f"• Название: {display_name}\n"
        f"• Страниц: {parsed.metadata.page_count}\n"
        f"• Чанков: {len(parsed.chunks)}\n"
        f"• Профиль: {profile.get('name', 'Универсальный')}\n"
    )

    # Send MD file
    await query.message.reply_document(
        document=open(md_path, 'rb'),
        filename=md_filename,
        caption=stats,
        parse_mode='Markdown'
    )

    # SQL mode
    if session.mode == OutputMode.SUPABASE_SQL:
        sql_content = create_sql_migration_file(parsed, include_setup=False)
        sql_filename = Path(session.pdf_path).stem + "_supabase.sql"
        sql_path = Path(config.TEMP_DIR) / sql_filename
        sql_path.write_text(sql_content, encoding='utf-8')

        await query.message.reply_document(
            document=open(sql_path, 'rb'),
            filename=sql_filename,
            caption="📋 **SQL для Supabase**\nВыполните в SQL Editor.",
            parse_mode='Markdown'
        )

    # API mode - ask for confirmation
    elif session.mode == OutputMode.SUPABASE_API:
        session.state = "awaiting_confirm_upload"
        await query.message.reply_text(
            f"🚀 Загрузить документ **{display_name}** в Supabase?",
            parse_mode='Markdown',
            reply_markup=get_confirm_keyboard()
        )
        return

    session.state = "idle"
    await query.edit_message_text("✅ Готово!")


async def upload_to_supabase(query, session: UserSession, user_id: int):
    """Загрузка в Supabase через API с custom_title и profile"""
    if not session.parsed_doc:
        await query.edit_message_text("❌ Документ не обработан.")
        return

    await query.edit_message_text("⏳ Загружаю в Supabase...")

    try:
        manager = SupabaseManager(config.SUPABASE_URL, config.SUPABASE_KEY)

        # Upload with all metadata
        doc_id = manager.upload_document(
            session.parsed_doc,
            user_id=user_id,
            custom_title=session.custom_title,
            processing_profile=session.processing_profile,
            tags=session.tags
        )

        display_name = session.custom_title or session.parsed_doc.metadata.title
        profile = PROCESSING_PROFILES.get(session.processing_profile, {})

        await query.edit_message_text(
            f"✅ **Загружено в Supabase!**\n\n"
            f"📄 Название: {display_name}\n"
            f"🆔 Document ID: `{doc_id}`\n"
            f"📊 Чанков: {len(session.parsed_doc.chunks)}\n"
            f"📋 Профиль: {profile.get('name', 'Универсальный')}\n\n"
            f"Используйте /list для просмотра.",
            parse_mode='Markdown'
        )

        session.state = "idle"

    except Exception as e:
        logger.error(f"Ошибка Supabase: {e}")
        await query.edit_message_text(f"❌ Ошибка загрузки: {e}")


# ==================== Document Management ====================

async def handle_document_management_callback(query, context, user_id: int, data: str):
    """Обработка callback'ов управления документами"""
    session = user_sessions.get(user_id)

    # Document selection
    if data.startswith("doc_select_"):
        doc_id = data.replace("doc_select_", "")

        try:
            manager = SupabaseManager(config.SUPABASE_URL, config.SUPABASE_KEY)
            doc = manager.get_document(doc_id)

            if not doc:
                await query.edit_message_text("❌ Документ не найден.")
                return

            # Store selected document
            if session:
                session.selected_doc_id = doc_id
                session.state = "awaiting_doc_action"

            display_name = doc.get('user_custom_title') or doc.get('title', 'Без названия')
            profile_name = PROCESSING_PROFILES.get(
                doc.get('processing_profile', 'universal'), {}
            ).get('name', 'Универсальный')

            tags_str = ', '.join(doc.get('tags', [])) if doc.get('tags') else 'Нет'

            info_text = (
                f"📄 **{display_name}**\n\n"
                f"📖 Оригинал: {doc.get('title', 'N/A')}\n"
                f"✍️ Автор: {doc.get('author', 'N/A')}\n"
                f"📃 Страниц: {doc.get('page_count', 'N/A')}\n"
                f"📋 Профиль: {profile_name}\n"
                f"🏷️ Теги: {tags_str}\n"
                f"📅 Создан: {str(doc.get('created_at', 'N/A'))[:10]}\n\n"
                f"Выберите действие:"
            )

            await query.edit_message_text(
                info_text,
                parse_mode='Markdown',
                reply_markup=get_document_actions_keyboard(doc_id)
            )

        except Exception as e:
            logger.error(f"Ошибка получения документа: {e}")
            await query.edit_message_text(f"❌ Ошибка: {e}")
        return

    # Back to list
    if data == "doc_back_to_list":
        docs = context.user_data.get('doc_list', [])
        page = session.doc_list_page if session else 0

        if not docs:
            await query.edit_message_text("📚 Документы не найдены.")
            return

        await query.edit_message_text(
            f"📚 **Ваши документы ({len(docs)}):**\n"
            f"Выберите документ для управления:",
            parse_mode='Markdown',
            reply_markup=get_document_list_keyboard(docs, page=page)
        )
        return

    # Pagination
    if data.startswith("doc_page_"):
        page = int(data.replace("doc_page_", ""))
        docs = context.user_data.get('doc_list', [])

        if session:
            session.doc_list_page = page

        await query.edit_message_text(
            f"📚 **Ваши документы ({len(docs)}):**\n"
            f"Страница {page + 1}\n"
            f"Выберите документ для управления:",
            parse_mode='Markdown',
            reply_markup=get_document_list_keyboard(docs, page=page)
        )
        return

    # Rename document
    if data.startswith("doc_rename_"):
        doc_id = data.replace("doc_rename_", "")
        if session:
            session.selected_doc_id = doc_id
            session.state = "awaiting_rename"
        await query.edit_message_text(
            "📝 Введите новое название для документа:"
        )
        return

    # Manage tags
    if data.startswith("doc_tags_"):
        doc_id = data.replace("doc_tags_", "")
        if session:
            session.selected_doc_id = doc_id
            session.state = "awaiting_tags"
        await query.edit_message_text(
            "🏷️ Введите теги через запятую:\n"
            "Например: учебник, физика, механика"
        )
        return

    # Export to MD
    if data.startswith("doc_export_"):
        doc_id = data.replace("doc_export_", "")
        await export_document_to_md(query, doc_id)
        return

    # Delete document
    if data.startswith("doc_delete_"):
        doc_id = data.replace("doc_delete_", "")

        try:
            manager = SupabaseManager(config.SUPABASE_URL, config.SUPABASE_KEY)
            doc = manager.get_document(doc_id)
            display_name = doc.get('user_custom_title') or doc.get('title', 'Документ') if doc else 'Документ'

            if session:
                session.selected_doc_id = doc_id
                session.state = "awaiting_delete_confirm"

            await query.edit_message_text(
                f"⚠️ **Вы уверены, что хотите удалить документ?**\n\n"
                f"📄 {display_name}\n\n"
                f"Это действие нельзя отменить!",
                parse_mode='Markdown',
                reply_markup=get_delete_confirm_keyboard(doc_id)
            )
        except Exception as e:
            await query.edit_message_text(f"❌ Ошибка: {e}")
        return


async def handle_delete_callback(query, user_id: int, data: str):
    """Обработка подтверждения удаления"""
    session = user_sessions.get(user_id)

    if data.startswith("delete_confirm_"):
        doc_id = data.replace("delete_confirm_", "")

        try:
            manager = SupabaseManager(config.SUPABASE_URL, config.SUPABASE_KEY)
            success = manager.delete_document(doc_id)

            if success:
                await query.edit_message_text("✅ Документ успешно удалён.")
            else:
                await query.edit_message_text("❌ Не удалось удалить документ.")

            if session:
                session.state = "idle"

        except Exception as e:
            logger.error(f"Ошибка удаления: {e}")
            await query.edit_message_text(f"❌ Ошибка: {e}")
        return

    if data == "delete_cancel":
        if session:
            session.state = "idle"
        await query.edit_message_text("❌ Удаление отменено.")
        return


async def export_document_to_md(query, doc_id: str):
    """Экспорт документа обратно в MD файл"""
    try:
        manager = SupabaseManager(config.SUPABASE_URL, config.SUPABASE_KEY)
        doc = manager.get_document(doc_id)

        if not doc:
            await query.edit_message_text("❌ Документ не найден.")
            return

        # Get all chunks for this document
        chunks_result = manager.client.table('document_chunks').select(
            'content, heading, page_number, chunk_index'
        ).eq('document_id', doc_id).order('chunk_index').execute()

        if not chunks_result.data:
            await query.edit_message_text("❌ Содержимое документа не найдено.")
            return

        # Rebuild markdown
        display_name = doc.get('user_custom_title') or doc.get('title', 'document')
        md_content = f"# {display_name}\n\n"
        md_content += f"---\n"
        md_content += f"Автор: {doc.get('author', 'Unknown')}\n"
        md_content += f"Страниц: {doc.get('page_count', 'N/A')}\n"
        md_content += f"---\n\n"

        current_heading = None
        for chunk in chunks_result.data:
            if chunk.get('heading') and chunk['heading'] != current_heading:
                md_content += f"\n## {chunk['heading']}\n\n"
                current_heading = chunk['heading']
            md_content += chunk['content'] + "\n\n"

        # Save to temp file
        safe_name = "".join(c for c in display_name if c.isalnum() or c in (' ', '-', '_')).rstrip()
        md_filename = f"{safe_name[:50]}.md"
        md_path = Path(config.TEMP_DIR) / md_filename
        os.makedirs(config.TEMP_DIR, exist_ok=True)
        md_path.write_text(md_content, encoding='utf-8')

        await query.message.reply_document(
            document=open(md_path, 'rb'),
            filename=md_filename,
            caption=f"📤 Экспорт: **{display_name}**",
            parse_mode='Markdown'
        )

        await query.edit_message_text("✅ Документ экспортирован!")

    except Exception as e:
        logger.error(f"Ошибка экспорта: {e}")
        await query.edit_message_text(f"❌ Ошибка экспорта: {e}")


async def update_document_tags(update: Update, session: UserSession, tags: list):
    """Обновление тегов документа"""
    try:
        manager = SupabaseManager(config.SUPABASE_URL, config.SUPABASE_KEY)
        success = manager.update_document_tags(session.selected_doc_id, tags)

        if success:
            await update.message.reply_text(
                f"✅ Теги обновлены: {', '.join(tags)}"
            )
        else:
            await update.message.reply_text("❌ Не удалось обновить теги.")

        session.state = "idle"

    except Exception as e:
        logger.error(f"Ошибка обновления тегов: {e}")
        await update.message.reply_text(f"❌ Ошибка: {e}")


async def rename_document(update: Update, session: UserSession, new_title: str):
    """Переименование документа"""
    try:
        manager = SupabaseManager(config.SUPABASE_URL, config.SUPABASE_KEY)
        success = manager.rename_document(session.selected_doc_id, new_title)

        if success:
            await update.message.reply_text(
                f"✅ Документ переименован: **{new_title}**",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text("❌ Не удалось переименовать документ.")

        session.state = "idle"

    except Exception as e:
        logger.error(f"Ошибка переименования: {e}")
        await update.message.reply_text(f"❌ Ошибка: {e}")


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /stats - статистика пользователя"""
    user_id = update.effective_user.id

    if not config.SUPABASE_URL or not config.SUPABASE_KEY:
        await update.message.reply_text("❌ Supabase не настроен.")
        return

    try:
        manager = SupabaseManager(config.SUPABASE_URL, config.SUPABASE_KEY)

        # Get user's documents (используем list_user_documents для совместимости)
        docs = manager.list_user_documents(user_id=user_id, limit=1000)

        if not docs:
            await update.message.reply_text(
                "📊 **Ваша статистика:**\n\n"
                "📚 Документов: 0\n"
                "Отправьте PDF для начала работы!",
                parse_mode='Markdown'
            )
            return

        # Calculate statistics
        total_docs = len(docs)
        total_pages = sum(d.get('page_count', 0) or 0 for d in docs)

        # Profile distribution
        profile_counts = {}
        for doc in docs:
            profile = doc.get('processing_profile', 'universal')
            profile_counts[profile] = profile_counts.get(profile, 0) + 1

        # Tags
        all_tags = set()
        for doc in docs:
            if doc.get('tags'):
                all_tags.update(doc['tags'])

        # Format profile stats
        profile_stats = ""
        for profile_id, count in sorted(profile_counts.items(), key=lambda x: -x[1]):
            profile_name = PROCESSING_PROFILES.get(profile_id, {}).get('name', profile_id)
            profile_stats += f"  • {profile_name}: {count}\n"

        stats_text = (
            f"📊 **Ваша статистика:**\n\n"
            f"📚 Всего документов: {total_docs}\n"
            f"📃 Всего страниц: {total_pages}\n"
            f"🏷️ Уникальных тегов: {len(all_tags)}\n\n"
            f"📋 **По профилям:**\n{profile_stats}\n"
        )

        if all_tags:
            tags_list = ', '.join(sorted(all_tags)[:20])
            stats_text += f"🏷️ **Теги:** {tags_list}"
            if len(all_tags) > 20:
                stats_text += f" и ещё {len(all_tags) - 20}..."

        await update.message.reply_text(stats_text, parse_mode='Markdown')

    except Exception as e:
        logger.error(f"Ошибка stats: {e}")
        await update.message.reply_text(f"❌ Ошибка: {e}")


# ==================== Keepalive ====================

async def keepalive_status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Статус keepalive системы"""
    try:
        manager = SupabaseManager(config.SUPABASE_URL, config.SUPABASE_KEY)

        # Получить последние 5 пингов
        result = manager.client.table('keepalive_pings').select(
            'id, timestamp, source'
        ).order('timestamp', desc=True).limit(5).execute()

        if not result.data:
            await update.message.reply_text(
                "⚠️ Keepalive пинги не найдены\n\n"
                "Возможно миграция не применена или бот только запустился."
            )
            return

        # Форматировать статус
        pings = result.data
        last_ping = pings[0]
        last_timestamp = datetime.fromisoformat(last_ping['timestamp'].replace('Z', '+00:00'))

        # Вычислить время до следующего пинга
        next_ping_time = last_timestamp.timestamp() + KEEPALIVE_INTERVAL_SECONDS
        now = datetime.now().timestamp()
        hours_until_next = (next_ping_time - now) / 3600

        # Проверка здоровья
        days_since_last = (datetime.now().timestamp() - last_timestamp.timestamp()) / 86400

        if days_since_last > 7:
            status = "🚨 КРИТИЧНО: БД могла заснуть!"
        elif days_since_last > 5:
            status = "⚠️ ВНИМАНИЕ: Близко к лимиту"
        elif days_since_last > 3:
            status = "⏰ Просрочен следующий ping"
        else:
            status = "✅ Работает нормально"

        text = (
            f"📊 Статус Keepalive\n\n"
            f"{status}\n\n"
            f"📅 Последний ping:\n"
            f"  {last_timestamp.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"  ({days_since_last:.1f} дней назад)\n\n"
            f"⏭️ Следующий ping через:\n"
            f"  {hours_until_next:.1f} часов\n\n"
            f"📈 История (последние 5):\n"
        )

        for i, ping in enumerate(pings, 1):
            ts = datetime.fromisoformat(ping['timestamp'].replace('Z', '+00:00'))
            text += f"  {i}. {ts.strftime('%Y-%m-%d %H:%M')}\n"

        text += f"\n⚙️ Интервал: {KEEPALIVE_INTERVAL_DAYS} дней"

        await update.message.reply_text(text)

    except Exception as e:
        await update.message.reply_text(
            f"❌ Ошибка проверки статуса:\n{str(e)}"
        )


async def keepalive_test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Принудительный тест keepalive (только для админа)"""
    user_id = update.effective_user.id

    # Проверка прав админа
    if KEEPALIVE_ADMIN_USER_ID and user_id != KEEPALIVE_ADMIN_USER_ID:
        await update.message.reply_text("❌ Доступ запрещён. Только для администратора.")
        return

    await update.message.reply_text("🔄 Выполняю тестовый keepalive ping...")

    try:
        manager = SupabaseManager(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)
        result = manager.ping_keepalive()

        if result['success']:
            await update.message.reply_text(
                f"✅ Тестовый ping успешен!\n\n"
                f"Ping ID: {result['ping_id']}\n"
                f"Timestamp: {result['timestamp']}\n\n"
                f"Система keepalive работает корректно."
            )
        else:
            await update.message.reply_text(
                f"❌ Тестовый ping провалился!\n\n"
                f"Ошибка: {result['error']}\n\n"
                f"Проверьте конфигурацию и SQL миграцию."
            )
    except Exception as e:
        await update.message.reply_text(
            f"💥 Исключение при тесте:\n{type(e).__name__}: {str(e)}"
        )


async def keepalive_job(context: ContextTypes.DEFAULT_TYPE):
    """
    Периодический keepalive пинг в Supabase

    Запускается каждые 3 дня через JobQueue.
    Предотвращает засыпание Supabase Free Tier (7 дней неактивности).
    """
    timestamp = datetime.now().isoformat()

    try:
        # Выполнить ping
        manager = SupabaseManager(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)
        result = manager.ping_keepalive()

        if result['success']:
            # Успешный ping
            log_message = (
                f"[{timestamp}] ✅ Keepalive ping successful\n"
                f"  Ping ID: {result['ping_id']}\n"
                f"  Timestamp: {result['timestamp']}\n"
                f"  Next ping in {KEEPALIVE_INTERVAL_DAYS} days\n"
            )

            logger.info(log_message)

            # Записать в файл
            with open(KEEPALIVE_LOG_FILE, 'a', encoding='utf-8') as f:
                f.write(log_message + "\n")

            # Опционально: уведомить админа (тихо, без спама)
            if KEEPALIVE_ADMIN_USER_ID:
                await context.bot.send_message(
                    chat_id=KEEPALIVE_ADMIN_USER_ID,
                    text=f"✅ Keepalive: БД активна\nСледующий ping через {KEEPALIVE_INTERVAL_DAYS} дня"
                )
        else:
            # Ошибка ping
            error_message = (
                f"[{timestamp}] ❌ Keepalive ping FAILED\n"
                f"  Error: {result['error']}\n"
                f"  ⚠️ БД может заснуть если не исправить!\n"
            )

            logger.error(error_message)

            # Записать в файл
            with open(KEEPALIVE_LOG_FILE, 'a', encoding='utf-8') as f:
                f.write(error_message + "\n")

            # КРИТИЧНО: уведомить админа о сбое
            if KEEPALIVE_ADMIN_USER_ID:
                await context.bot.send_message(
                    chat_id=KEEPALIVE_ADMIN_USER_ID,
                    text=(
                        "🚨 КРИТИЧНО: Keepalive ping FAILED!\n\n"
                        f"Ошибка: {result['error']}\n\n"
                        "БД может заснуть через 7 дней если не исправить.\n"
                        "Проверьте:\n"
                        "1. SUPABASE_URL и SUPABASE_SERVICE_KEY в .env\n"
                        "2. Применена ли SQL миграция (keepalive_pings таблица)\n"
                        "3. Работает ли интернет на сервере"
                    )
                )

    except Exception as e:
        # Критическая ошибка (исключение)
        exception_message = (
            f"[{timestamp}] 💥 EXCEPTION in keepalive_job\n"
            f"  Exception: {type(e).__name__}: {str(e)}\n"
        )

        logger.exception(exception_message)

        with open(KEEPALIVE_LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(exception_message + "\n")

        if KEEPALIVE_ADMIN_USER_ID:
            await context.bot.send_message(
                chat_id=KEEPALIVE_ADMIN_USER_ID,
                text=(
                    f"💥 КРИТИЧЕСКАЯ ОШИБКА в keepalive_job!\n\n"
                    f"{type(e).__name__}: {str(e)}\n\n"
                    "Проверьте логи бота."
                )
            )


def main():
    """Запуск бота"""
    if not config.TELEGRAM_BOT_TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN не задан!")
        print("Установите переменную окружения:")
        print("export TELEGRAM_BOT_TOKEN='your_token_here'")
        return
    
    # Создаем приложение
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()

    # ============ KEEPALIVE JOB ============
    # Запуск keepalive задачи каждые 3 дня
    # Первый запуск через 10 секунд после старта
    app.job_queue.run_repeating(
        callback=keepalive_job,
        interval=KEEPALIVE_INTERVAL_SECONDS,  # 3 дня = 259200 сек
        first=10,  # Первый запуск через 10 сек (для проверки работоспособности)
        name='supabase_keepalive'
    )
    logger.info(f"✅ Keepalive job зарегистрирован: интервал = {KEEPALIVE_INTERVAL_DAYS} дней")
    # ========================================

    # Регистрируем обработчики команд
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("setup", setup_command))
    app.add_handler(CommandHandler("list", list_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("search", search_command))
    app.add_handler(CommandHandler("keepalive_status", keepalive_status_command))
    app.add_handler(CommandHandler("keepalive_test", keepalive_test_command))

    # Text handler for custom input (name, tags) - MUST be before document handler
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_text_input
    ))

    # Document handler
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))

    # Callback handler
    app.add_handler(CallbackQueryHandler(handle_callback))

    # Запускаем
    print("🤖 Бот запущен!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
