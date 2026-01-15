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


if __name__ == "__main__":
    test_parser()
