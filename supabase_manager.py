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
        embeddings: Optional[list[list[float]]] = None
    ) -> str:
        """
        Загрузка документа в Supabase
        
        Args:
            parsed_doc: Распарсенный документ
            embeddings: Опционально - готовые эмбеддинги для чанков
            
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
                'subject': parsed_doc.metadata.subject
            }
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
        document_id: Optional[str] = None
    ) -> list[dict]:
        """
        Семантический поиск по документам
        
        Args:
            query_embedding: Вектор запроса
            threshold: Минимальный порог схожести
            limit: Максимум результатов
            document_id: Опционально - поиск в конкретном документе
            
        Returns:
            Список найденных чанков
        """
        result = self.client.rpc(
            'match_documents',
            {
                'query_embedding': query_embedding,
                'match_threshold': threshold,
                'match_count': limit,
                'filter_document_id': document_id
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


def generate_setup_sql() -> str:
    """Возвращает SQL для настройки базы данных"""
    return SETUP_SQL


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
