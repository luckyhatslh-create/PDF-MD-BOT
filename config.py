"""
Конфигурация PDF-MD-Supabase бота
"""
import os
from dataclasses import dataclass
from typing import Optional
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    """Настройки приложения"""

    # Telegram Bot
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")

    # Supabase
    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
    SUPABASE_KEY: str = os.getenv("SUPABASE_KEY", "")  # anon key для клиента
    SUPABASE_SERVICE_KEY: str = os.getenv("SUPABASE_SERVICE_KEY", "")  # для серверных операций

    # OpenAI для эмбеддингов и Vision API
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")

    # Настройки парсинга
    CHUNK_SIZE: int = int(os.getenv("CHUNK_SIZE", "1500"))  # Оптимальный размер чанка для LLM
    CHUNK_OVERLAP: int = int(os.getenv("CHUNK_OVERLAP", "200"))  # Перекрытие чанков

    # OCR настройки
    ENABLE_OCR: bool = os.getenv("ENABLE_OCR", "false").lower() == "true"
    OCR_LANGUAGES: str = os.getenv("OCR_LANGUAGES", "rus+eng")

    # Vision API настройки (для анализа изображений)
    ANALYZE_IMAGES: bool = os.getenv("ANALYZE_IMAGES", "false").lower() == "true"
    VISION_PROVIDER: str = os.getenv("VISION_PROVIDER", "openai")  # openai | anthropic
    VISION_MODEL: str = os.getenv("VISION_MODEL", "gpt-4o")

    # Пути
    TEMP_DIR: str = os.getenv("TEMP_DIR", "/tmp/pdf_processor")

    # Лимиты
    MAX_FILE_SIZE_MB: int = int(os.getenv("MAX_FILE_SIZE_MB", "50"))
    MAX_PAGES: int = int(os.getenv("MAX_PAGES", "500"))


config = Config()
