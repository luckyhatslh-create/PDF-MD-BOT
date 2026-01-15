"""
PDF Parser - конвертация PDF в структурированный Markdown

Ключевые особенности:
- Извлечение текста с сохранением структуры
- Распознавание заголовков по размеру шрифта
- Извлечение таблиц в MD формат (с дедупликацией)
- Разбиение на чанки для RAG
- OCR для сканов (опционально)
- Анализ изображений через Vision AI (опционально)
"""

import re
import os
import base64
import unicodedata
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Any
from itertools import groupby
import pdfplumber
from pypdf import PdfReader

# Опциональные импорты
try:
    import fitz  # PyMuPDF
    PYMUPDF_AVAILABLE = True
except ImportError:
    PYMUPDF_AVAILABLE = False

try:
    import pytesseract
    from pdf2image import convert_from_path
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False


@dataclass
class PDFMetadata:
    """Метаданные PDF документа"""
    title: str = ""
    author: str = ""
    subject: str = ""
    page_count: int = 0
    file_name: str = ""
    has_images: bool = False
    is_scanned: bool = False


@dataclass
class ParsedChunk:
    """Чанк для RAG"""
    content: str
    page_number: int
    chunk_index: int
    heading: str = ""  # Заголовок раздела
    metadata: dict = field(default_factory=dict)


@dataclass
class ParsedDocument:
    """Результат парсинга"""
    metadata: PDFMetadata
    full_markdown: str
    chunks: list[ParsedChunk]
    table_of_contents: list[str]
    images: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class HeadingTracker:
    """Отслеживание иерархии заголовков для обеспечения консистентности"""

    def __init__(self):
        self.last_level = 0
        self.heading_stack = []

    def determine_level(self, detected_level: int, text: str = "") -> int:
        """Определяет уровень заголовка с учётом иерархии"""
        # Не пропускать уровни (например, H1 -> H3 недопустимо)
        if detected_level > self.last_level + 1:
            detected_level = self.last_level + 1

        self.last_level = detected_level
        return detected_level

    def reset(self):
        """Сброс трекера"""
        self.last_level = 0
        self.heading_stack = []


class ImageAnalyzer:
    """Анализ изображений через Vision API"""

    def __init__(self, provider: str = "openai", api_key: str = None):
        self.provider = provider
        self.api_key = api_key
        self._client = None

    @property
    def client(self):
        if self._client is None and self.provider == "openai" and OPENAI_AVAILABLE:
            self._client = OpenAI(api_key=self.api_key)
        return self._client

    def analyze(self, image_bytes: bytes, context: str = "") -> dict:
        """Анализирует изображение и возвращает текстовое описание"""
        if not self.client:
            return {'type': 'unknown', 'description': '[Изображение - Vision API недоступен]'}

        image_b64 = base64.b64encode(image_bytes).decode('utf-8')

        if self.provider == "openai":
            return self._analyze_openai(image_b64, context)

        return {'type': 'unknown', 'description': '[Изображение]'}

    def _analyze_openai(self, image_b64: str, context: str) -> dict:
        """Анализ через OpenAI Vision API"""
        prompt = """Проанализируй изображение из технической документации.

Если это ФОРМУЛА или УРАВНЕНИЕ:
- Распиши формулу в текстовом/LaTeX формате
- Кратко объясни переменные

Если это СХЕМА или ДИАГРАММА:
- Кратко опиши что изображено (1-3 предложения)
- Перечисли ключевые элементы если они подписаны

Если это ИЛЛЮСТРАЦИЯ (например, части устройства):
- Опиши что показано
- Перечисли пронумерованные/подписанные части

Отвечай на русском языке. Контекст документа: """ + context

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o",
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {
                            "url": f"data:image/png;base64,{image_b64}"
                        }}
                    ]
                }],
                max_tokens=500
            )

            description = response.choices[0].message.content
            return {
                'type': self._classify_image_type(description),
                'description': description
            }
        except Exception as e:
            return {'type': 'error', 'description': f'[Ошибка анализа изображения: {str(e)}]'}

    def _classify_image_type(self, description: str) -> str:
        """Определяет тип изображения по описанию"""
        desc_lower = description.lower()
        if any(w in desc_lower for w in ['формула', 'уравнение', 'equation', '=']):
            return 'formula'
        elif any(w in desc_lower for w in ['схема', 'диаграмма', 'diagram', 'flowchart']):
            return 'diagram'
        else:
            return 'illustration'


class PDFParser:
    """Парсер PDF в Markdown с поддержкой чанкинга"""

    def __init__(
        self,
        chunk_size: int = 1500,
        chunk_overlap: int = 200,
        detect_headers: bool = True,
        enable_ocr: bool = False,
        ocr_languages: str = 'rus+eng',
        analyze_images: bool = False,
        vision_provider: str = 'openai',
        vision_api_key: str = None
    ):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.detect_headers = detect_headers
        self.enable_ocr = enable_ocr and OCR_AVAILABLE
        self.ocr_languages = ocr_languages
        self.analyze_images = analyze_images
        self.vision_provider = vision_provider
        self.vision_api_key = vision_api_key

        # Внутренние объекты
        self._heading_tracker = HeadingTracker()
        self._image_analyzer = None
        self._current_section = ""
        self._warnings = []

        if analyze_images:
            self._image_analyzer = ImageAnalyzer(
                provider=vision_provider,
                api_key=vision_api_key
            )
        
    def parse(self, pdf_path: str) -> ParsedDocument:
        """
        Основной метод парсинга PDF

        Args:
            pdf_path: Путь к PDF файлу

        Returns:
            ParsedDocument с MD контентом и чанками
        """
        pdf_path = Path(pdf_path)

        # Сброс состояния
        self._heading_tracker.reset()
        self._current_section = ""
        self._warnings = []

        # Извлекаем метаданные
        metadata = self._extract_metadata(pdf_path)

        # Извлекаем изображения (если включено)
        images = []
        if self.analyze_images and PYMUPDF_AVAILABLE:
            images = self._extract_images(pdf_path)
            metadata.has_images = len(images) > 0

        # Извлекаем контент
        pages_content = self._extract_content(pdf_path)

        # Проверяем, сканированный ли документ
        if self._is_scanned_document(pages_content):
            metadata.is_scanned = True
            if self.enable_ocr:
                pages_content = self._apply_ocr(pdf_path, pages_content)
            else:
                self._warnings.append("Документ выглядит как скан, но OCR отключён")

        # Собираем полный markdown
        full_md = self._build_markdown(metadata, pages_content, images)

        # Извлекаем оглавление
        toc = self._extract_toc(full_md)

        # Разбиваем на чанки
        chunks = self._create_chunks(pages_content, metadata)

        return ParsedDocument(
            metadata=metadata,
            full_markdown=full_md,
            chunks=chunks,
            table_of_contents=toc,
            images=images,
            warnings=self._warnings
        )
    
    def _extract_metadata(self, pdf_path: Path) -> PDFMetadata:
        """Извлечение метаданных из PDF"""
        reader = PdfReader(str(pdf_path))
        meta = reader.metadata or {}
        
        return PDFMetadata(
            title=meta.get('/Title', '') or pdf_path.stem,
            author=meta.get('/Author', '') or 'Unknown',
            subject=meta.get('/Subject', ''),
            page_count=len(reader.pages),
            file_name=pdf_path.name
        )
    
    def _extract_content(self, pdf_path: Path) -> list[dict]:
        """Извлечение контента постранично с таблицами (без дублирования)"""
        pages_content = []

        with pdfplumber.open(str(pdf_path)) as pdf:
            for page_num, page in enumerate(pdf.pages, 1):
                page_data = {
                    'page_number': page_num,
                    'text': '',
                    'tables': [],
                    'headers': []
                }

                # Находим таблицы и их bounding boxes
                found_tables = page.find_tables()
                table_bboxes = [t.bbox for t in found_tables]

                # Извлекаем текст ВНЕ областей таблиц (предотвращаем дублирование)
                if table_bboxes:
                    text = self._extract_text_outside_tables(page, table_bboxes)
                else:
                    text = page.extract_text() or ''

                # Проверяем и исправляем проблемы с кодировкой
                text = self._extract_text_with_fallback(
                    text, page_num, str(pdf_path)
                )

                # Собираем параграфы
                text = self._assemble_paragraphs(text)
                page_data['text'] = text

                # Извлекаем таблицы с несколькими стратегиями
                tables = self._extract_tables_with_strategies(page)
                for table in tables:
                    if table and len(table) > 0:
                        md_table = self._table_to_markdown(table)
                        if md_table:  # Пропускаем пустые таблицы
                            page_data['tables'].append(md_table)

                # Определяем заголовки (по шрифту или паттернам)
                if self.detect_headers:
                    page_data['headers'] = self._detect_headers_smart(page)

                pages_content.append(page_data)

        return pages_content

    def _extract_text_outside_tables(self, page, table_bboxes: list) -> str:
        """Извлекает текст, исключая области таблиц"""
        if not table_bboxes:
            return page.extract_text() or ''

        # Создаём фильтр для исключения символов внутри таблиц
        def not_within_tables(obj):
            if obj.get('object_type') != 'char':
                return False
            x0, y0, x1, y1 = obj['x0'], obj['top'], obj['x1'], obj['bottom']
            for bbox in table_bboxes:
                t_x0, t_y0, t_x1, t_y1 = bbox
                # Проверяем пересечение
                if (x0 < t_x1 and x1 > t_x0 and y0 < t_y1 and y1 > t_y0):
                    return False
            return True

        # Фильтруем страницу
        filtered = page.filter(not_within_tables)
        return filtered.extract_text() or ''

    def _extract_text_with_fallback(self, text: str, page_num: int, pdf_path: str) -> str:
        """Извлечение текста с fallback на PyMuPDF при проблемах с кодировкой"""
        # Проверяем на проблемы с кодировкой (много replacement characters)
        if text and text.count('\ufffd') / max(len(text), 1) > 0.1:
            if PYMUPDF_AVAILABLE:
                try:
                    doc = fitz.open(pdf_path)
                    text = doc[page_num - 1].get_text("text")
                    doc.close()
                except Exception:
                    pass  # Остаёмся с исходным текстом

        # Нормализуем Unicode
        text = unicodedata.normalize('NFC', text)
        return self._clean_text(text)

    def _assemble_paragraphs(self, text: str) -> str:
        """Объединение разорванных строк в связные параграфы"""
        if not text:
            return ""

        lines = text.split('\n')
        paragraphs = []
        current = []

        for line in lines:
            line = line.strip()
            if not line:
                # Пустая строка = конец параграфа
                if current:
                    paragraphs.append(' '.join(current))
                    current = []
                continue

            # Проверяем, продолжение ли это предыдущей строки
            if current:
                prev = current[-1]
                # Условия для объединения строк:
                # 1. Предыдущая строка заканчивается на строчную букву
                # 2. Предыдущая строка заканчивается на запятую
                # 3. Предыдущая строка заканчивается на дефис (перенос слова)
                # 4. Текущая строка начинается со строчной буквы
                should_join = (
                    (prev and prev[-1:].islower()) or
                    prev.endswith(',') or
                    prev.endswith('-') or
                    (line and line[0:1].islower() and line[0:1].isalpha())
                )

                if should_join:
                    if prev.endswith('-'):
                        # Убираем дефис переноса
                        current[-1] = prev[:-1]
                    current.append(line)
                    continue

            current.append(line)

        # Добавляем последний параграф
        if current:
            paragraphs.append(' '.join(current))

        return '\n\n'.join(paragraphs)

    def _extract_tables_with_strategies(self, page) -> list:
        """Извлечение таблиц с несколькими стратегиями"""
        # Стратегия 1: Стандартные настройки
        tables = page.extract_tables()
        if tables and any(not self._is_empty_table(t) for t in tables):
            return [t for t in tables if not self._is_empty_table(t)]

        # Стратегия 2: Строгие линии
        try:
            tables = page.extract_tables(table_settings={
                "vertical_strategy": "lines_strict",
                "horizontal_strategy": "lines_strict",
                "snap_tolerance": 5,
            })
            if tables and any(not self._is_empty_table(t) for t in tables):
                return [t for t in tables if not self._is_empty_table(t)]
        except Exception:
            pass

        # Стратегия 3: По тексту
        try:
            tables = page.extract_tables(table_settings={
                "vertical_strategy": "text",
                "horizontal_strategy": "text",
                "min_words_vertical": 3,
            })
            if tables and any(not self._is_empty_table(t) for t in tables):
                return [t for t in tables if not self._is_empty_table(t)]
        except Exception:
            pass

        return []

    def _is_empty_table(self, table: list) -> bool:
        """Проверяет, является ли таблица пустой"""
        if not table:
            return True
        total_content = sum(
            len(str(cell or '').strip())
            for row in table
            for cell in row
        )
        return total_content < 10

    def _detect_headers_smart(self, page) -> list[dict]:
        """Умное определение заголовков: по шрифту или паттернам"""
        headers = []

        # Пробуем определение по размеру шрифта
        chars = page.chars
        if chars:
            font_headers = self._detect_headers_by_font(chars)
            if font_headers:
                headers = font_headers

        # Если не нашли по шрифту, используем паттерны
        if not headers:
            text = page.extract_text() or ''
            pattern_headers = self._detect_headers(text)
            headers = [{'level': 3, 'text': h} for h in pattern_headers]

        return headers

    def _detect_headers_by_font(self, chars: list) -> list[dict]:
        """Определение заголовков по размеру шрифта"""
        if not chars:
            return []

        # Группируем символы по строкам (по y-координатам)
        lines = self._group_chars_by_line(chars)
        headers = []

        # Определяем базовый размер шрифта (наиболее частый)
        all_sizes = [c.get('size', 12) for c in chars if c.get('size')]
        if not all_sizes:
            return []
        base_size = max(set(all_sizes), key=all_sizes.count)

        for line_chars in lines:
            if not line_chars:
                continue

            # Вычисляем средний размер шрифта для строки
            sizes = [c.get('size', base_size) for c in line_chars]
            avg_size = sum(sizes) / len(sizes)
            text = ''.join(c.get('text', '') for c in line_chars).strip()

            # Пропускаем слишком короткие или длинные строки
            if len(text) < 3 or len(text) > 200:
                continue

            # Определяем уровень заголовка по размеру шрифта
            if avg_size >= base_size * 1.5:  # H1 - на 50%+ больше
                headers.append({'level': 1, 'text': text, 'size': avg_size})
            elif avg_size >= base_size * 1.2:  # H2 - на 20%+ больше
                headers.append({'level': 2, 'text': text, 'size': avg_size})
            elif avg_size >= base_size * 1.1 and self._looks_like_header(text):
                headers.append({'level': 3, 'text': text, 'size': avg_size})

        return headers

    def _group_chars_by_line(self, chars: list, tolerance: int = 3) -> list[list]:
        """Группировка символов по строкам (по y-координатам)"""
        if not chars:
            return []

        # Сортируем по y, затем по x
        sorted_chars = sorted(chars, key=lambda c: (round(c.get('top', 0) / tolerance), c.get('x0', 0)))

        # Группируем по округлённой y-координате
        lines = []
        for _, group in groupby(sorted_chars, lambda c: round(c.get('top', 0) / tolerance)):
            lines.append(list(group))

        return lines

    def _looks_like_header(self, text: str) -> bool:
        """Эвристика: похожа ли строка на заголовок"""
        if not text:
            return False

        # Короткая строка, начинается с заглавной
        if len(text) < 100 and text[0].isupper():
            # Нумерованный заголовок
            if re.match(r'^\d+[\.\)]\s', text):
                return True
            # Все заглавные
            if text.isupper() and len(text) > 3:
                return True
            # Заканчивается без точки (не обычное предложение)
            if not text.endswith('.'):
                return True

        return False
    
    def _clean_text(self, text: str) -> str:
        """Очистка и нормализация текста"""
        # Удаляем множественные пробелы
        text = re.sub(r' +', ' ', text)
        # Нормализуем переносы строк
        text = re.sub(r'\n{3,}', '\n\n', text)
        # Удаляем висячие дефисы (переносы слов)
        text = re.sub(r'-\n', '', text)
        return text.strip()
    
    def _detect_headers(self, text: str) -> list[str]:
        """Эвристическое определение заголовков"""
        headers = []
        lines = text.split('\n')
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
                
            # Паттерны заголовков
            patterns = [
                # Нумерованные главы: "Глава 1", "Chapter 1", "1. Введение"
                r'^(Глава|Chapter|Раздел|Section)\s+\d+',
                r'^\d+\.\s+[A-ZА-ЯЁ]',
                r'^\d+\.\d+\.?\s+[A-ZА-ЯЁ]',
                # Заглавные строки (короткие)
                r'^[A-ZА-ЯЁ][A-ZА-ЯЁ\s]{5,50}$',
            ]
            
            for pattern in patterns:
                if re.match(pattern, line):
                    headers.append(line)
                    break
                    
        return headers
    
    def _table_to_markdown(self, table: list[list]) -> str:
        """Конвертация таблицы в Markdown формат с фильтрацией пустых"""
        if not table or len(table) == 0:
            return ""

        # Проверяем реальное содержимое таблицы
        total_content = sum(
            len(str(cell or '').strip())
            for row in table
            for cell in row
        )
        if total_content < 10:
            return ""  # Пропускаем пустые таблицы

        # Проверяем, что есть хотя бы одна непустая строка данных
        non_empty_rows = [
            row for row in table
            if any(str(cell or '').strip() for cell in row)
        ]
        if len(non_empty_rows) < 2:  # Только заголовок без данных
            return ""

        md_lines = []

        # Заголовок таблицы
        header = non_empty_rows[0]
        header = [str(cell or '').strip() for cell in header]

        # Если заголовок пустой, пропускаем
        if not any(header):
            return ""

        md_lines.append('| ' + ' | '.join(header) + ' |')

        # Разделитель
        md_lines.append('| ' + ' | '.join(['---'] * len(header)) + ' |')

        # Данные
        for row in non_empty_rows[1:]:
            row = [str(cell or '').strip().replace('\n', ' ') for cell in row]
            # Выравниваем количество колонок
            while len(row) < len(header):
                row.append('')
            md_lines.append('| ' + ' | '.join(row[:len(header)]) + ' |')

        return '\n'.join(md_lines)
    
    def _build_markdown(
        self,
        metadata: PDFMetadata,
        pages_content: list[dict],
        images: list[dict] = None
    ) -> str:
        """Сборка полного Markdown документа с поддержкой изображений"""
        md_parts = []
        images = images or []

        # Группируем изображения по страницам
        images_by_page = {}
        for img in images:
            images_by_page.setdefault(img['page'], []).append(img)

        # Заголовок документа
        md_parts.append(f"# {metadata.title}\n")

        # Метаданные в YAML frontmatter
        md_parts.append("---")
        md_parts.append(f"author: {metadata.author}")
        md_parts.append(f"pages: {metadata.page_count}")
        md_parts.append(f"source: {metadata.file_name}")
        if metadata.has_images:
            md_parts.append(f"has_images: true")
        if metadata.is_scanned:
            md_parts.append(f"is_scanned: true")
        md_parts.append("---\n")

        # Сброс трекера заголовков
        self._heading_tracker.reset()

        # Контент по страницам
        for page in pages_content:
            page_num = page['page_number']

            # Обрабатываем заголовки с учётом иерархии
            headers = page.get('headers', [])
            for header_info in headers:
                # header_info может быть dict или str
                if isinstance(header_info, dict):
                    text = header_info.get('text', '')
                    detected_level = header_info.get('level', 3)
                else:
                    text = header_info
                    detected_level = self._detect_header_level(text)

                # Применяем трекинг иерархии
                level = self._heading_tracker.determine_level(detected_level, text)
                self._current_section = text

                # Добавляем заголовок с правильным уровнем
                md_marker = '#' * (level + 1)  # H1 = ##, H2 = ###, etc.
                md_parts.append(f"\n{md_marker} {text}\n")

            # Текст страницы
            text = page.get('text', '')
            if text:
                # Убираем заголовки из текста (они уже добавлены)
                for header_info in headers:
                    header_text = header_info.get('text', '') if isinstance(header_info, dict) else header_info
                    text = text.replace(header_text, '', 1)
                clean_text = text.strip()
                if clean_text:
                    md_parts.append(clean_text)

            # Таблицы
            for table in page.get('tables', []):
                if table:
                    md_parts.append(f"\n{table}\n")

            # Изображения для этой страницы
            if page_num in images_by_page and self._image_analyzer:
                for img in images_by_page[page_num]:
                    img_md = self._format_image_description(img)
                    if img_md:
                        md_parts.append(img_md)

            # Маркер страницы (для навигации)
            md_parts.append(f"\n<!-- page {page_num} -->\n")

        return '\n'.join(md_parts)

    def _detect_header_level(self, text: str) -> int:
        """Определяет уровень заголовка по паттернам текста"""
        if re.match(r'^(Глава|Chapter)\s+\d+', text):
            return 1
        elif re.match(r'^\d+\.\d+\.\d+', text):
            return 3
        elif re.match(r'^\d+\.\d+', text):
            return 2
        elif re.match(r'^\d+\.', text):
            return 2
        return 3

    def _format_image_description(self, img: dict) -> str:
        """Форматирует описание изображения для Markdown"""
        if not self._image_analyzer or 'bytes' not in img:
            return ""

        try:
            analysis = self._image_analyzer.analyze(
                img['bytes'],
                context=self._current_section
            )

            img_type = analysis.get('type', 'illustration')
            description = analysis.get('description', '[Изображение]')

            if img_type == 'formula':
                return f"\n**Формула:**\n```\n{description}\n```\n"
            elif img_type == 'diagram':
                return f"\n> **Схема:** {description}\n"
            else:
                return f"\n*[Рисунок: {description}]*\n"
        except Exception as e:
            self._warnings.append(f"Ошибка анализа изображения: {str(e)}")
            return ""
    
    def _extract_toc(self, markdown: str) -> list[str]:
        """Извлечение оглавления из markdown заголовков"""
        toc = []
        for line in markdown.split('\n'):
            if line.startswith('#'):
                # Убираем маркеры # и очищаем
                level = len(line) - len(line.lstrip('#'))
                title = line.lstrip('#').strip()
                indent = '  ' * (level - 1)
                toc.append(f"{indent}- {title}")
        return toc

    def _extract_images(self, pdf_path: Path) -> list[dict]:
        """Извлечение изображений из PDF через PyMuPDF"""
        if not PYMUPDF_AVAILABLE:
            self._warnings.append("PyMuPDF не установлен, изображения не будут извлечены")
            return []

        images = []
        try:
            doc = fitz.open(str(pdf_path))

            for page_num, page in enumerate(doc, 1):
                image_list = page.get_images()

                for img_index, img_info in enumerate(image_list):
                    try:
                        xref = img_info[0]
                        base_image = doc.extract_image(xref)

                        if base_image and base_image.get('image'):
                            images.append({
                                'page': page_num,
                                'index': img_index,
                                'bytes': base_image['image'],
                                'ext': base_image.get('ext', 'png'),
                                'width': base_image.get('width', 0),
                                'height': base_image.get('height', 0)
                            })
                    except Exception as e:
                        self._warnings.append(f"Ошибка извлечения изображения {img_index} на стр. {page_num}: {e}")

            doc.close()
        except Exception as e:
            self._warnings.append(f"Ошибка открытия PDF для извлечения изображений: {e}")

        return images

    def _is_scanned_document(self, pages_content: list[dict]) -> bool:
        """Определяет, является ли документ сканом"""
        # Считаем страницы с очень малым количеством текста
        low_text_pages = 0
        for page in pages_content:
            text = page.get('text', '')
            if len(text.strip()) < 100:
                low_text_pages += 1

        # Если более 50% страниц почти без текста — вероятно, скан
        return low_text_pages > len(pages_content) * 0.5

    def _apply_ocr(self, pdf_path: Path, pages_content: list[dict]) -> list[dict]:
        """Применяет OCR к страницам с малым количеством текста"""
        if not OCR_AVAILABLE:
            self._warnings.append("OCR библиотеки не установлены")
            return pages_content

        for page in pages_content:
            page_num = page['page_number']
            text = page.get('text', '')

            # Применяем OCR только к страницам с малым количеством текста
            if len(text.strip()) < 100:
                try:
                    ocr_text = self._ocr_page(page_num, str(pdf_path))
                    if ocr_text:
                        page['text'] = self._assemble_paragraphs(ocr_text)
                        page['ocr_applied'] = True
                except Exception as e:
                    self._warnings.append(f"Ошибка OCR на стр. {page_num}: {e}")

        return pages_content

    def _ocr_page(self, page_num: int, pdf_path: str) -> str:
        """Извлечение текста через OCR для одной страницы"""
        if not OCR_AVAILABLE:
            return ""

        try:
            # Конвертируем страницу PDF в изображение
            images = convert_from_path(
                pdf_path,
                first_page=page_num,
                last_page=page_num,
                dpi=300
            )

            if images:
                # Применяем OCR
                text = pytesseract.image_to_string(
                    images[0],
                    lang=self.ocr_languages,
                    config='--psm 1'  # Automatic page segmentation with OSD
                )
                return text
        except Exception as e:
            self._warnings.append(f"OCR ошибка: {e}")

        return ""
    
    def _create_chunks(
        self,
        pages_content: list[dict],
        metadata: PDFMetadata
    ) -> list[ParsedChunk]:
        """Разбиение на семантические чанки для RAG"""
        chunks = []
        chunk_index = 0
        current_text = ""
        current_page = 1
        current_heading = metadata.title

        for page in pages_content:
            page_num = page['page_number']

            # Обновляем текущий заголовок
            headers = page.get('headers', [])
            if headers:
                # Поддержка нового формата (dict) и старого (str)
                first_header = headers[0]
                if isinstance(first_header, dict):
                    current_heading = first_header.get('text', current_heading)
                else:
                    current_heading = first_header

            # Добавляем текст страницы
            text = page.get('text', '')

            # Добавляем таблицы
            for table in page.get('tables', []):
                if table:
                    text += f"\n\n{table}\n\n"

            current_text += f"\n{text}"

            # Проверяем размер чанка
            while len(current_text) >= self.chunk_size:
                # Ищем хорошую точку разбиения (конец предложения)
                split_point = self._find_split_point(
                    current_text,
                    self.chunk_size
                )

                chunk_content = current_text[:split_point].strip()

                if chunk_content:
                    chunks.append(ParsedChunk(
                        content=chunk_content,
                        page_number=current_page,
                        chunk_index=chunk_index,
                        heading=current_heading,
                        metadata={
                            'source': metadata.file_name,
                            'title': metadata.title
                        }
                    ))
                    chunk_index += 1

                # Оставляем overlap
                overlap_start = max(0, split_point - self.chunk_overlap)
                current_text = current_text[overlap_start:]
                current_page = page_num

        # Последний чанк
        if current_text.strip():
            chunks.append(ParsedChunk(
                content=current_text.strip(),
                page_number=current_page,
                chunk_index=chunk_index,
                heading=current_heading,
                metadata={
                    'source': metadata.file_name,
                    'title': metadata.title
                }
            ))

        return chunks
    
    def _find_split_point(self, text: str, target: int) -> int:
        """Поиск оптимальной точки разбиения текста"""
        if len(text) <= target:
            return len(text)
        
        # Ищем конец предложения вблизи target
        search_start = max(0, target - 200)
        search_end = min(len(text), target + 100)
        search_area = text[search_start:search_end]
        
        # Приоритет: конец абзаца > конец предложения > пробел
        for delimiter in ['\n\n', '.\n', '. ', '? ', '! ', ', ', ' ']:
            pos = search_area.rfind(delimiter)
            if pos != -1:
                return search_start + pos + len(delimiter)
        
        return target


def parse_pdf_to_markdown(
    pdf_path: str,
    chunk_size: int = 1500,
    chunk_overlap: int = 200,
    enable_ocr: bool = False,
    ocr_languages: str = 'rus+eng',
    analyze_images: bool = False,
    vision_api_key: str = None
) -> ParsedDocument:
    """
    Удобная функция для парсинга PDF

    Args:
        pdf_path: Путь к PDF файлу
        chunk_size: Размер чанка в символах
        chunk_overlap: Перекрытие между чанками
        enable_ocr: Включить OCR для сканированных документов
        ocr_languages: Языки для OCR (например, 'rus+eng')
        analyze_images: Анализировать изображения через Vision AI
        vision_api_key: API ключ для Vision AI (OpenAI)

    Returns:
        ParsedDocument с полным markdown и чанками
    """
    parser = PDFParser(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        enable_ocr=enable_ocr,
        ocr_languages=ocr_languages,
        analyze_images=analyze_images,
        vision_api_key=vision_api_key
    )
    return parser.parse(pdf_path)


if __name__ == "__main__":
    # Тест
    import sys
    if len(sys.argv) > 1:
        result = parse_pdf_to_markdown(sys.argv[1])
        print(f"Title: {result.metadata.title}")
        print(f"Author: {result.metadata.author}")
        print(f"Pages: {result.metadata.page_count}")
        print(f"Chunks: {len(result.chunks)}")
        print(f"Images: {len(result.images)}")
        print(f"Is Scanned: {result.metadata.is_scanned}")
        if result.warnings:
            print(f"\nWarnings: {len(result.warnings)}")
            for w in result.warnings[:5]:
                print(f"  - {w}")
        print("\n--- TABLE OF CONTENTS ---")
        print('\n'.join(result.table_of_contents[:20]))
