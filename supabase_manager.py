"""
Supabase Integration - хранение документов с векторным поиском

Возможности:
- Создание таблиц и индексов
- Загрузка чанков с эмбеддингами
- Семантический поиск по документам
- Управление документами
"""

import json
import hashlib
from dataclasses import dataclass
from typing import Optional
from datetime import datetime

try:
    from supabase import create_client, Client
    SUPABASE_AVAILABLE = True
except ImportError:
    SUPABASE_AVAILABLE = False

from pdf_parser import ParsedDocument, ParsedChunk


# SQL для создания структуры БД
SETUP_SQL = """
-- Включаем расширение для векторов (если еще не включено)
create extension if not exists vector;

-- Таблица документов
CREATE TABLE IF NOT EXISTS documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT NOT NULL,
    author TEXT,
    source_file TEXT NOT NULL,
    page_count INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    metadata JSONB DEFAULT '{}'::jsonb,
    file_hash TEXT UNIQUE  -- Для предотвращения дублей
);

-- Индекс для поиска по заголовку
CREATE INDEX IF NOT EXISTS idx_documents_title ON documents USING gin(to_tsvector('russian', title));

-- Таблица чанков с векторами
CREATE TABLE IF NOT EXISTS document_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    page_number INTEGER,
    chunk_index INTEGER,
    heading TEXT,
    embedding vector(1536),  -- OpenAI ada-002 размерность
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Индексы для чанков
CREATE INDEX IF NOT EXISTS idx_chunks_document ON document_chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_chunks_embedding ON document_chunks 
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- Полнотекстовый поиск по контенту
CREATE INDEX IF NOT EXISTS idx_chunks_content ON document_chunks 
    USING gin(to_tsvector('russian', content));

-- Функция семантического поиска
CREATE OR REPLACE FUNCTION match_documents(
    query_embedding vector(1536),
    match_threshold float DEFAULT 0.7,
    match_count int DEFAULT 10,
    filter_document_id uuid DEFAULT NULL
)
RETURNS TABLE (
    id uuid,
    document_id uuid,
    content text,
    heading text,
    page_number int,
    similarity float,
    metadata jsonb
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT
        dc.id,
        dc.document_id,
        dc.content,
        dc.heading,
        dc.page_number,
        1 - (dc.embedding <=> query_embedding) as similarity,
        dc.metadata
    FROM document_chunks dc
    WHERE 
        (filter_document_id IS NULL OR dc.document_id = filter_document_id)
        AND 1 - (dc.embedding <=> query_embedding) > match_threshold
    ORDER BY dc.embedding <=> query_embedding
    LIMIT match_count;
END;
$$;

-- Функция полнотекстового поиска
CREATE OR REPLACE FUNCTION search_documents_text(
    search_query text,
    match_count int DEFAULT 20
)
RETURNS TABLE (
    id uuid,
    document_id uuid,
    content text,
    heading text,
    page_number int,
    rank real
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT
        dc.id,
        dc.document_id,
        dc.content,
        dc.heading,
        dc.page_number,
        ts_rank(to_tsvector('russian', dc.content), plainto_tsquery('russian', search_query)) as rank
    FROM document_chunks dc
    WHERE to_tsvector('russian', dc.content) @@ plainto_tsquery('russian', search_query)
    ORDER BY rank DESC
    LIMIT match_count;
END;
$$;

-- RLS политики (опционально, для многопользовательского режима)
-- ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE document_chunks ENABLE ROW LEVEL SECURITY;

-- Триггер обновления updated_at
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER documents_updated_at
    BEFORE UPDATE ON documents
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();
"""


# SQL миграция для управления документами
MIGRATION_DOCUMENT_MANAGEMENT = """
-- MIGRATION: Document management enhancements

-- Добавить новые поля в таблицу documents
ALTER TABLE documents
ADD COLUMN IF NOT EXISTS user_custom_title TEXT,
ADD COLUMN IF NOT EXISTS processing_profile TEXT DEFAULT 'universal',
ADD COLUMN IF NOT EXISTS user_id BIGINT,  -- Telegram user ID
ADD COLUMN IF NOT EXISTS tags TEXT[],     -- Теги для поиска
ADD COLUMN IF NOT EXISTS description TEXT;

-- Индексы для быстрого поиска
CREATE INDEX IF NOT EXISTS idx_documents_user_id ON documents(user_id);
CREATE INDEX IF NOT EXISTS idx_documents_profile ON documents(processing_profile);
CREATE INDEX IF NOT EXISTS idx_documents_tags ON documents USING GIN(tags);
CREATE INDEX IF NOT EXISTS idx_documents_custom_title ON documents
    USING GIN(to_tsvector('russian', COALESCE(user_custom_title, '')));

-- Функция для поиска по пользователю с фильтрами
CREATE OR REPLACE FUNCTION search_user_documents(
    p_user_id BIGINT,
    p_search_query TEXT DEFAULT NULL,
    p_profile TEXT DEFAULT NULL,
    p_date_from TIMESTAMPTZ DEFAULT NULL,
    p_date_to TIMESTAMPTZ DEFAULT NULL,
    p_limit INT DEFAULT 20,
    p_offset INT DEFAULT 0
)
RETURNS TABLE (
    id UUID,
    title TEXT,
    user_custom_title TEXT,
    author TEXT,
    page_count INTEGER,
    processing_profile TEXT,
    created_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ,
    tags TEXT[],
    match_rank REAL
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        d.id,
        d.title,
        d.user_custom_title,
        d.author,
        d.page_count,
        d.processing_profile,
        d.created_at,
        d.updated_at,
        d.tags,
        CASE
            WHEN p_search_query IS NOT NULL THEN
                ts_rank(
                    to_tsvector('russian', COALESCE(d.user_custom_title, d.title)),
                    plainto_tsquery('russian', p_search_query)
                )
            ELSE 0.0
        END AS match_rank
    FROM documents d
    WHERE
        (p_user_id IS NULL OR d.user_id = p_user_id)
        AND (p_profile IS NULL OR d.processing_profile = p_profile)
        AND (p_date_from IS NULL OR d.created_at >= p_date_from)
        AND (p_date_to IS NULL OR d.created_at <= p_date_to)
        AND (
            p_search_query IS NULL OR
            to_tsvector('russian', COALESCE(d.user_custom_title, d.title))
            @@ plainto_tsquery('russian', p_search_query)
        )
    ORDER BY
        CASE WHEN p_search_query IS NOT NULL THEN match_rank ELSE 0.0 END DESC,
        d.created_at DESC
    LIMIT p_limit
    OFFSET p_offset;
END;
$$ LANGUAGE plpgsql;

-- Обновить функцию match_documents для поддержки фильтрации по пользователю
CREATE OR REPLACE FUNCTION match_documents(
    query_embedding vector(1536),
    match_threshold float DEFAULT 0.7,
    match_count int DEFAULT 10,
    filter_document_id uuid DEFAULT NULL,
    filter_user_id BIGINT DEFAULT NULL
)
RETURNS TABLE (
    id uuid,
    document_id uuid,
    content text,
    heading text,
    page_number int,
    similarity float,
    metadata jsonb
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT
        dc.id,
        dc.document_id,
        dc.content,
        dc.heading,
        dc.page_number,
        1 - (dc.embedding <=> query_embedding) as similarity,
        dc.metadata
    FROM document_chunks dc
    JOIN documents d ON dc.document_id = d.id
    WHERE
        (filter_document_id IS NULL OR dc.document_id = filter_document_id)
        AND (filter_user_id IS NULL OR d.user_id = filter_user_id)
        AND 1 - (dc.embedding <=> query_embedding) > match_threshold
    ORDER BY dc.embedding <=> query_embedding
    LIMIT match_count;
END;
$$;

-- ======================================================================
-- KEEPALIVE: Предотвращение паузы Supabase Free Tier
-- ======================================================================

-- Таблица для keepalive пингов
CREATE TABLE IF NOT EXISTS keepalive_pings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    source TEXT DEFAULT 'telegram_bot',
    metadata JSONB DEFAULT '{}'::jsonb
);

-- Индекс для быстрого удаления старых записей
CREATE INDEX IF NOT EXISTS idx_keepalive_timestamp ON keepalive_pings(timestamp DESC);

-- Функция автоочистки старых записей (>30 дней)
CREATE OR REPLACE FUNCTION cleanup_old_keepalive_pings()
RETURNS void AS $$
BEGIN
    DELETE FROM keepalive_pings
    WHERE timestamp < NOW() - INTERVAL '30 days';
END;
$$ LANGUAGE plpgsql;

-- Комментарий для документации
COMMENT ON TABLE keepalive_pings IS 'Keepalive пинги для предотвращения паузы Supabase Free Tier (7 дней неактивности)';
"""


class SupabaseManager:
    """Менеджер для работы с Supabase"""
    
    def __init__(self, url: str, key: str):
        """
        Инициализация клиента Supabase
        
        Args:
            url: URL проекта Supabase
            key: API ключ (anon или service)
        """
        if not SUPABASE_AVAILABLE:
            raise ImportError("supabase-py не установлен. pip install supabase")
        
        self.client: Client = create_client(url, key)
        
    def upload_document(
        self,
        parsed_doc: ParsedDocument,
        embeddings: Optional[list[list[float]]] = None,
        user_id: Optional[int] = None,
        custom_title: Optional[str] = None,
        processing_profile: Optional[str] = None,
        tags: Optional[list[str]] = None
    ) -> str:
        """
        Загрузка документа в Supabase

        Args:
            parsed_doc: Распарсенный документ
            embeddings: Опционально - готовые эмбеддинги для чанков
            user_id: Telegram user ID
            custom_title: Пользовательское название документа
            processing_profile: Профиль обработки (fiction, technical, diagrams, universal)
            tags: Теги для поиска

        Returns:
            ID документа в БД
        """
        # Создаем хеш файла для предотвращения дублей
        content_hash = hashlib.sha256(
            parsed_doc.full_markdown.encode()
        ).hexdigest()[:32]
        
        # Проверяем существование
        existing = self.client.table('documents').select('id').eq(
            'file_hash', content_hash
        ).execute()
        
        if existing.data:
            print(f"Документ уже существует: {existing.data[0]['id']}")
            return existing.data[0]['id']
        
        # Создаем запись документа
        doc_data = {
            'title': parsed_doc.metadata.title,
            'author': parsed_doc.metadata.author,
            'source_file': parsed_doc.metadata.file_name,
            'page_count': parsed_doc.metadata.page_count,
            'file_hash': content_hash,
            'metadata': {
                'toc': parsed_doc.table_of_contents[:50],  # Первые 50 пунктов
                'subject': parsed_doc.metadata.subject,
                'has_images': parsed_doc.metadata.has_images,
                'is_scanned': parsed_doc.metadata.is_scanned,
                'quality_metrics': parsed_doc.quality_metrics
            },
            'user_id': user_id,
            'user_custom_title': custom_title,
            'processing_profile': processing_profile or 'universal',
            'tags': tags or []
        }
        
        result = self.client.table('documents').insert(doc_data).execute()
        document_id = result.data[0]['id']
        
        # Загружаем чанки
        chunks_data = []
        for i, chunk in enumerate(parsed_doc.chunks):
            chunk_record = {
                'document_id': document_id,
                'content': chunk.content,
                'page_number': chunk.page_number,
                'chunk_index': chunk.chunk_index,
                'heading': chunk.heading,
                'metadata': chunk.metadata
            }
            
            # Добавляем эмбеддинг если есть
            if embeddings and i < len(embeddings):
                chunk_record['embedding'] = embeddings[i]
            
            chunks_data.append(chunk_record)
        
        # Пакетная вставка чанков
        batch_size = 100
        for i in range(0, len(chunks_data), batch_size):
            batch = chunks_data[i:i + batch_size]
            self.client.table('document_chunks').insert(batch).execute()
        
        return document_id
    
    def search_semantic(
        self,
        query_embedding: list[float],
        threshold: float = 0.7,
        limit: int = 10,
        document_id: Optional[str] = None,
        user_id: Optional[int] = None
    ) -> list[dict]:
        """
        Семантический поиск по документам

        Args:
            query_embedding: Вектор запроса
            threshold: Минимальный порог схожести
            limit: Максимум результатов
            document_id: Опционально - поиск в конкретном документе
            user_id: Опционально - поиск только в документах пользователя

        Returns:
            Список найденных чанков
        """
        result = self.client.rpc(
            'match_documents',
            {
                'query_embedding': query_embedding,
                'match_threshold': threshold,
                'match_count': limit,
                'filter_document_id': document_id,
                'filter_user_id': user_id
            }
        ).execute()
        
        return result.data
    
    def search_text(self, query: str, limit: int = 20) -> list[dict]:
        """
        Полнотекстовый поиск
        
        Args:
            query: Поисковый запрос
            limit: Максимум результатов
            
        Returns:
            Список найденных чанков
        """
        result = self.client.rpc(
            'search_documents_text',
            {
                'search_query': query,
                'match_count': limit
            }
        ).execute()
        
        return result.data
    
    def get_document(self, document_id: str) -> Optional[dict]:
        """Получение информации о документе"""
        result = self.client.table('documents').select('*').eq(
            'id', document_id
        ).execute()
        
        return result.data[0] if result.data else None
    
    def list_documents(self, limit: int = 50) -> list[dict]:
        """Список всех документов"""
        result = self.client.table('documents').select(
            'id, title, author, page_count, created_at'
        ).order('created_at', desc=True).limit(limit).execute()
        
        return result.data
    
    def delete_document(self, document_id: str) -> bool:
        """Удаление документа и всех его чанков"""
        try:
            self.client.table('documents').delete().eq('id', document_id).execute()
            return True
        except Exception as e:
            print(f"Ошибка удаления: {e}")
            return False

    def rename_document(self, document_id: str, new_title: str) -> bool:
        """Переименование документа"""
        try:
            self.client.table('documents').update({
                'user_custom_title': new_title,
                'updated_at': datetime.now().isoformat()
            }).eq('id', document_id).execute()
            return True
        except Exception as e:
            print(f"Ошибка переименования: {e}")
            return False

    def search_user_documents(
        self,
        user_id: Optional[int] = None,
        search_query: Optional[str] = None,
        profile: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        limit: int = 20,
        offset: int = 0
    ) -> list[dict]:
        """Поиск документов пользователя с фильтрами"""
        result = self.client.rpc('search_user_documents', {
            'p_user_id': user_id,
            'p_search_query': search_query,
            'p_profile': profile,
            'p_date_from': date_from,
            'p_date_to': date_to,
            'p_limit': limit,
            'p_offset': offset
        }).execute()

        return result.data

    def get_user_documents_count(self, user_id: int) -> int:
        """Количество документов пользователя"""
        result = self.client.table('documents').select(
            'id', count='exact'
        ).eq('user_id', user_id).execute()

        return result.count if result.count else 0

    def ping_keepalive(self) -> dict:
        """
        Keepalive пинг для предотвращения паузы Supabase Free Tier

        Вставляет запись в keepalive_pings таблицу каждые 3 дня.
        Supabase Free Tier засыпает после 7 дней неактивности.

        Returns:
            dict: {
                'success': bool,
                'timestamp': str,
                'ping_id': str,
                'error': str (если success=False)
            }
        """
        try:
            # INSERT запрос - минимальная активность БД
            result = self.client.table('keepalive_pings').insert({
                'source': 'telegram_bot',
                'metadata': {
                    'bot_version': '2.0',
                    'keepalive_interval_days': 3
                }
            }).execute()

            ping_id = result.data[0]['id']
            timestamp = result.data[0]['timestamp']

            # Опционально: очистка старых записей (>30 дней)
            try:
                self.client.rpc('cleanup_old_keepalive_pings').execute()
            except Exception as cleanup_err:
                # Не критично если cleanup не сработал
                print(f"Warning: cleanup failed: {cleanup_err}")

            return {
                'success': True,
                'timestamp': timestamp,
                'ping_id': ping_id
            }

        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'timestamp': None,
                'ping_id': None
            }


def generate_setup_sql() -> str:
    """Возвращает SQL для настройки базы данных"""
    return SETUP_SQL


def generate_migration_sql() -> str:
    """Возвращает SQL миграции для управления документами"""
    return MIGRATION_DOCUMENT_MANAGEMENT


def create_sql_migration_file(
    parsed_doc: ParsedDocument, 
    include_setup: bool = True
) -> str:
    """
    Создание SQL файла для ручной загрузки в Supabase
    
    Args:
        parsed_doc: Распарсенный документ
        include_setup: Включить SQL создания таблиц
        
    Returns:
        SQL скрипт как строка
    """
    sql_parts = []
    
    if include_setup:
        sql_parts.append("-- ====== SETUP (выполнить один раз) ======")
        sql_parts.append(SETUP_SQL)
        sql_parts.append("\n-- ====== DATA ======\n")
    
    # Хеш документа
    content_hash = hashlib.sha256(
        parsed_doc.full_markdown.encode()
    ).hexdigest()[:32]
    
    # Экранирование текста для SQL
    def escape_sql(text: str) -> str:
        return text.replace("'", "''").replace("\\", "\\\\")
    
    # INSERT документа
    doc_sql = f"""
-- Вставка документа
INSERT INTO documents (title, author, source_file, page_count, file_hash, metadata)
VALUES (
    '{escape_sql(parsed_doc.metadata.title)}',
    '{escape_sql(parsed_doc.metadata.author)}',
    '{escape_sql(parsed_doc.metadata.file_name)}',
    {parsed_doc.metadata.page_count},
    '{content_hash}',
    '{json.dumps({"subject": parsed_doc.metadata.subject}, ensure_ascii=False)}'::jsonb
)
ON CONFLICT (file_hash) DO NOTHING
RETURNING id;
"""
    sql_parts.append(doc_sql)
    
    # Используем CTE для получения ID документа
    sql_parts.append("""
-- Вставка чанков
WITH doc AS (
    SELECT id FROM documents WHERE file_hash = '""" + content_hash + """'
)
INSERT INTO document_chunks (document_id, content, page_number, chunk_index, heading, metadata)
VALUES""")
    
    # INSERT чанков
    chunk_values = []
    for chunk in parsed_doc.chunks:
        value = f"""
    ((SELECT id FROM doc), 
     '{escape_sql(chunk.content)}', 
     {chunk.page_number}, 
     {chunk.chunk_index}, 
     '{escape_sql(chunk.heading)}',
     '{json.dumps(chunk.metadata, ensure_ascii=False)}'::jsonb)"""
        chunk_values.append(value)
    
    sql_parts.append(','.join(chunk_values) + ';')
    
    return '\n'.join(sql_parts)


if __name__ == "__main__":
    # Печать SQL для создания структуры
    print("-- SQL для настройки Supabase:")
    print(generate_setup_sql())
