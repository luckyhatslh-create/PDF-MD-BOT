"""
Тестовый скрипт - создание тестового PDF и проверка парсинга
"""

import os
import sys

# Добавляем текущую директорию в path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import cm


def create_test_pdf(output_path: str = "test_book.pdf"):
    """Создание тестового PDF для проверки парсера"""
    
    doc = SimpleDocTemplate(output_path, pagesize=A4)
    styles = getSampleStyleSheet()
    
    # Кастомные стили
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Title'],
        fontSize=24,
        spaceAfter=30
    )
    
    chapter_style = ParagraphStyle(
        'Chapter',
        parent=styles['Heading1'],
        fontSize=18,
        spaceBefore=20,
        spaceAfter=15
    )
    
    section_style = ParagraphStyle(
        'Section',
        parent=styles['Heading2'],
        fontSize=14,
        spaceBefore=15,
        spaceAfter=10
    )
    
    story = []
    
    # Титульная страница
    story.append(Paragraph("Введение в машинное обучение", title_style))
    story.append(Spacer(1, 20))
    story.append(Paragraph("Учебное пособие", styles['Normal']))
    story.append(Spacer(1, 10))
    story.append(Paragraph("Автор: Иван Петров", styles['Normal']))
    story.append(PageBreak())
    
    # Глава 1
    story.append(Paragraph("Глава 1. Основы машинного обучения", chapter_style))
    story.append(Paragraph(
        """Машинное обучение (Machine Learning) — это подраздел искусственного 
        интеллекта, изучающий методы построения алгоритмов, способных обучаться 
        на данных. Основная идея заключается в том, что система может автоматически 
        улучшать свою производительность на основе опыта без явного программирования.""",
        styles['Normal']
    ))
    story.append(Spacer(1, 15))
    
    # 1.1
    story.append(Paragraph("1.1 Типы машинного обучения", section_style))
    story.append(Paragraph(
        """Существует три основных типа машинного обучения: обучение с учителем 
        (supervised learning), обучение без учителя (unsupervised learning) и 
        обучение с подкреплением (reinforcement learning). Каждый тип применяется 
        для решения различных классов задач.""",
        styles['Normal']
    ))
    story.append(Spacer(1, 10))
    
    # Таблица
    story.append(Paragraph("Сравнение типов машинного обучения:", styles['Normal']))
    story.append(Spacer(1, 10))
    
    table_data = [
        ['Тип', 'Данные', 'Применение'],
        ['С учителем', 'Размеченные', 'Классификация, регрессия'],
        ['Без учителя', 'Неразмеченные', 'Кластеризация, снижение размерности'],
        ['С подкреплением', 'Награды/штрафы', 'Игры, робототехника'],
    ]
    
    table = Table(table_data, colWidths=[4*cm, 4*cm, 6*cm])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
    ]))
    story.append(table)
    story.append(PageBreak())
    
    # Глава 2
    story.append(Paragraph("Глава 2. Нейронные сети", chapter_style))
    story.append(Paragraph(
        """Искусственные нейронные сети — это вычислительные системы, вдохновленные 
        биологическими нейронными сетями мозга. Они состоят из искусственных 
        нейронов, соединенных между собой и способных передавать сигналы.""",
        styles['Normal']
    ))
    story.append(Spacer(1, 15))
    
    # 2.1
    story.append(Paragraph("2.1 Архитектура нейронной сети", section_style))
    story.append(Paragraph(
        """Типичная нейронная сеть состоит из входного слоя, одного или нескольких 
        скрытых слоев и выходного слоя. Каждый нейрон в слое связан с нейронами 
        соседних слоев через взвешенные связи. Процесс обучения заключается в 
        подборе оптимальных весов для минимизации функции ошибки.""",
        styles['Normal']
    ))
    story.append(Spacer(1, 15))
    
    # 2.2
    story.append(Paragraph("2.2 Функции активации", section_style))
    story.append(Paragraph(
        """Функция активации определяет выход нейрона на основе его входов. 
        Популярные функции включают: сигмоиду, гиперболический тангенс (tanh), 
        ReLU (Rectified Linear Unit) и его модификации.""",
        styles['Normal']
    ))
    
    # Собираем документ
    doc.build(story)
    print(f"✅ Тестовый PDF создан: {output_path}")
    return output_path


def test_parser():
    """Тестирование парсера"""
    from pdf_parser import parse_pdf_to_markdown
    
    # Создаем тестовый PDF
    pdf_path = create_test_pdf()
    
    # Парсим
    print("\n📖 Парсинг PDF...")
    result = parse_pdf_to_markdown(pdf_path)
    
    # Выводим результаты
    print(f"\n📊 Метаданные:")
    print(f"  Title: {result.metadata.title}")
    print(f"  Author: {result.metadata.author}")
    print(f"  Pages: {result.metadata.page_count}")
    
    print(f"\n📑 Чанки: {len(result.chunks)}")
    for i, chunk in enumerate(result.chunks[:3]):
        print(f"\n  Chunk {i+1}:")
        print(f"    Page: {chunk.page_number}")
        print(f"    Heading: {chunk.heading}")
        print(f"    Length: {len(chunk.content)} chars")
        print(f"    Preview: {chunk.content[:100]}...")
    
    print(f"\n📋 Оглавление:")
    for item in result.table_of_contents[:10]:
        print(f"  {item}")
    
    # Сохраняем MD
    md_path = "test_book.md"
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(result.full_markdown)
    print(f"\n✅ MD сохранен: {md_path}")
    
    # Генерируем SQL
    from supabase_manager import create_sql_migration_file
    sql = create_sql_migration_file(result, include_setup=False)
    sql_path = "test_book_supabase.sql"
    with open(sql_path, 'w', encoding='utf-8') as f:
        f.write(sql)
    print(f"✅ SQL сохранен: {sql_path}")
    
    return result


def test_broken_table_detection():
    """Тест детектирования сломанных таблиц"""
    from pdf_parser import PDFParser

    parser = PDFParser()

    print("\n🧪 Test: Broken Table Detection")

    # Тест 1: Фрагментированная таблица (должна быть отклонена)
    broken_table = [
        ['И', 'нструкция', 'по'],
        ['уст', 'ановке', 'де'],
    ]
    is_broken, reason = parser._is_broken_table(broken_table)
    assert is_broken, f"Failed to detect broken table: {reason}"
    assert 'fragmentation' in reason.lower() or 'split' in reason.lower()
    print(f"  ✅ Broken table detected: {reason}")

    # Тест 2: Нормальная таблица (должна быть принята)
    good_table = [
        ['Name', 'Age', 'City'],
        ['Alice', '25', 'Moscow'],
        ['Bob', '30', 'London'],
    ]
    is_broken, reason = parser._is_broken_table(good_table)
    assert not is_broken, f"False positive on good table: {reason}"
    print(f"  ✅ Good table accepted: {reason}")

    # Тест 3: Таблица с фрагментами предложений (должна быть отклонена)
    sentence_table = [
        ['n', 'n', 'n', 'n'],
        ['n', 'n', 'n', '.'],
        ['Machine', 'learning', 'is', 'great.'],
    ]
    is_broken, reason = parser._is_broken_table(sentence_table)
    print(f"  📊 Sentence table: {is_broken} - {reason}")

    print("  ✅ All broken table detection tests passed!")


def test_garbage_filtering():
    """Тест фильтрации мусорных строк"""
    from pdf_parser import PDFParser

    parser = PDFParser()

    print("\n🧪 Test: Garbage Line Filtering")

    # Тест паттернов мусора
    garbage_patterns = [
        ("5 44 3 88 66 2 77 99 1", "numeric noise"),
        ("n n n n n n n n n", "single char repetition"),
        ("--- ___ === ---", "symbol line"),
        ("bcdfghjklmnp qrst vwx", "no vowels"),
    ]

    for line, description in garbage_patterns:
        is_garbage = parser._is_garbage_line(line)
        assert is_garbage, f"Failed to detect {description}: '{line}'"
        print(f"  ✅ Detected {description}: '{line[:30]}'")

    # Тест нормального текста
    normal_lines = [
        "Это нормальный текст на русском языке.",
        "This is normal English text.",
        "1. Машинное обучение — это подраздел искусственного интеллекта.",
    ]

    for line in normal_lines:
        is_garbage = parser._is_garbage_line(line)
        assert not is_garbage, f"False positive on normal text: '{line}'"
        print(f"  ✅ Accepted normal text: '{line[:40]}'")

    print("  ✅ All garbage filtering tests passed!")


def test_numbered_list_vs_header():
    """Тест различения нумерованных списков и заголовков"""
    from pdf_parser import PDFParser

    parser = PDFParser()

    print("\n🧪 Test: Numbered List vs Header")

    # Должны распознаваться как элементы списка (НЕ заголовки)
    list_items = [
        "1. Машинное обучение — это подраздел искусственного интеллекта.",
        "2. Нейронные сети состоят из множества связанных нейронов.",
        "3. Обучение происходит путем корректировки весов связей.",
    ]

    for item in list_items:
        is_header = parser._looks_like_header(item)
        assert not is_header, f"List item mistaken for header: '{item}'"
        print(f"  ✅ Correctly identified as list item: '{item[:50]}'")

    # Должны распознаваться как заголовки
    headers = [
        "1. Введение",
        "2. Основные понятия",
        "Глава 1",
        "ЗАКЛЮЧЕНИЕ",
    ]

    for header in headers:
        is_header = parser._looks_like_header(header)
        assert is_header, f"Header not recognized: '{header}'"
        print(f"  ✅ Correctly identified as header: '{header}'")

    print("  ✅ All numbered list detection tests passed!")


def test_quality_improvements_e2e():
    """End-to-end тест улучшений качества"""
    from pdf_parser import parse_pdf_to_markdown

    print("\n🧪 Test: Quality Improvements E2E")

    # Создаем тестовый PDF
    pdf_path = create_test_pdf("test_quality.pdf")

    # Парсим с новыми улучшениями
    result = parse_pdf_to_markdown(pdf_path)

    # Проверяем наличие метрик качества
    assert 'tables_detected' in result.quality_metrics, "Missing quality metrics"
    print(f"  📊 Tables detected: {result.quality_metrics['tables_detected']}")
    print(f"  📊 Tables rejected: {result.quality_metrics['tables_rejected']}")
    print(f"  📊 Garbage filtered: {result.quality_metrics['garbage_lines_filtered']}")
    print(f"  📊 Duplicate tables: {result.quality_metrics['duplicate_tables_skipped']}")

    # Проверяем, что нет сломанных таблиц в выводе
    assert '| И | нструкция |' not in result.full_markdown, "Found broken table in output"
    print("  ✅ No broken tables in output")

    # Проверяем, что нет мусорных строк
    assert '5 44 3 88 66 2 77 99 1' not in result.full_markdown, "Found garbage in output"
    print("  ✅ No garbage lines in output")

    # Проверяем, что нумерованные списки не как H3
    import re
    for line in result.full_markdown.split('\n'):
        if re.match(r'^###\s+\d+\.\s+\w{30,}', line):
            raise AssertionError(f"Found numbered list as H3: {line}")
    print("  ✅ No numbered lists as headers")

    # Сохраняем результат
    with open("test_quality.md", 'w', encoding='utf-8') as f:
        f.write(result.full_markdown)
    print("  ✅ Quality test output saved to test_quality.md")

    print("  ✅ All E2E quality tests passed!")

    return result


def run_all_tests():
    """Запуск всех тестов"""
    print("=" * 60)
    print("🧪 RUNNING ALL TESTS")
    print("=" * 60)

    try:
        test_broken_table_detection()
        test_garbage_filtering()
        test_numbered_list_vs_header()
        test_quality_improvements_e2e()

        print("\n" + "=" * 60)
        print("✅ ALL TESTS PASSED!")
        print("=" * 60)
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        raise
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        raise


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        run_all_tests()
    else:
        test_parser()
