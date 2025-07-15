#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BOOKS LOADER - Принудительная загрузка всех книг Лесли в PostgreSQL
БЕЗ TELEGRAM BOT - только обработка книг для избежания event loop конфликтов
"""

import asyncio
import logging
import os
import sys
import time
import traceback
import psycopg2
from psycopg2.extras import RealDictCursor
import re
from typing import List, Dict

# Обработка документов
try:
    import PyPDF2
    import docx
    import ebooklib
    from ebooklib import epub
except ImportError as e:
    print(f"Предупреждение: {e}. Некоторые форматы файлов могут не поддерживаться.")

# Конфигурация
try:
    from config import config
except ImportError:
    # Fallback конфигурация
    class Config:
        DATABASE_URL = os.getenv('DATABASE_URL')
    
    config = Config()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

class BooksLoader:
    """Загрузчик книг без Telegram Bot"""
    
    def __init__(self):
        self.setup_database()
        self.create_tables()
    
    def setup_database(self):
        """Настройка подключения к базе данных"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                if config.DATABASE_URL:
                    logger.info("🔗 Подключаюсь к PostgreSQL...")
                    self.db = psycopg2.connect(
                        config.DATABASE_URL,
                        connect_timeout=30,
                        keepalives_idle=30,
                        keepalives_interval=5,
                        keepalives_count=5
                    )
                    logger.info("✅ Подключение к PostgreSQL успешно")
                    return
                else:
                    raise Exception("DATABASE_URL не найден")
                    
            except Exception as e:
                if attempt < max_retries - 1:
                    logger.warning(f"⚠️ Ошибка подключения к базе данных, попытка {attempt+1}: {e}")
                    time.sleep(2)
                else:
                    logger.error(f"❌ Критическая ошибка подключения к базе данных: {e}")
                    raise

    def create_tables(self):
        """Создание таблиц базы знаний"""
        try:
            with self.db.cursor() as cursor:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS knowledge_base (
                        id SERIAL PRIMARY KEY,
                        book_name VARCHAR(255),
                        chapter VARCHAR(255),
                        content TEXT,
                        keywords TEXT,
                        category VARCHAR(100),
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_keywords 
                    ON knowledge_base USING gin(to_tsvector('russian', keywords))
                """)
                
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_content 
                    ON knowledge_base USING gin(to_tsvector('russian', content))
                """)
                
                self.db.commit()
                logger.info("✅ Таблицы базы знаний созданы успешно")
        except Exception as e:
            logger.error(f"❌ Ошибка создания таблиц: {e}")

    def get_books_count(self):
        """Получить количество записей в базе знаний"""
        try:
            with self.db.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM knowledge_base")
                result = cursor.fetchone()
                return result[0] if result else 0
        except Exception as e:
            logger.error(f"Ошибка подсчета записей: {e}")
            return 0

    def get_books_list(self):
        """Получить список загруженных книг"""
        try:
            with self.db.cursor() as cursor:
                cursor.execute("SELECT DISTINCT book_name FROM knowledge_base")
                results = cursor.fetchall()
                return [row[0] for row in results]
        except Exception as e:
            logger.error(f"Ошибка получения списка книг: {e}")
            return []

    def force_load_all_books(self):
        """ПРИНУДИТЕЛЬНАЯ загрузка всех книг"""
        logger.info("🚀 НАЧИНАЮ ПРИНУДИТЕЛЬНУЮ ОБРАБОТКУ ВСЕХ КНИГ")
        
        try:
            # Проверяем текущее состояние базы
            book_count = self.get_books_count()
            existing_books = self.get_books_list()
            logger.info(f"📊 В базе знаний уже есть {book_count} записей")
            logger.info(f"📚 Загружено книг: {len(existing_books)}")
            
            # Множественные пути поиска
            possible_paths = [
                "/app/books/",
                "./books/", 
                "/books/",
                "/app/",
                "./",
                os.path.join(os.getcwd(), "books"),
                os.path.join(os.path.dirname(__file__), "books")
            ]
            
            books_found = False
            total_processed = 0
            
            for path in possible_paths:
                logger.info(f"🔍 Ищу книги в: {path}")
                
                try:
                    if os.path.exists(path):
                        files = [f for f in os.listdir(path) if f.lower().endswith(('.pdf', '.txt', '.docx', '.epub'))]
                        
                        if files:
                            logger.info(f"📚 Найдено {len(files)} книг в {path}")
                            books_found = True
                            
                            for file in files:
                                file_path = os.path.join(path, file)
                                logger.info(f"📖 Обрабатываю книгу: {file}")
                                
                                try:
                                    # Проверяем не загружена ли уже эта книга
                                    if file in existing_books:
                                        logger.info(f"⏭️ Книга {file} уже загружена, пропускаю")
                                        continue
                                    
                                    success = self.process_book(file_path, file)
                                    if success:
                                        total_processed += 1
                                        logger.info(f"✅ Книга {file} успешно обработана")
                                    else:
                                        logger.warning(f"⚠️ Книга {file} не обработана")
                                        
                                except Exception as e:
                                    logger.error(f"❌ Ошибка обработки {file}: {e}")
                                    continue
                            
                            break
                        else:
                            logger.info(f"📁 Папка {path} пуста")
                    else:
                        logger.info(f"❌ Путь {path} не существует")
                except Exception as e:
                    logger.error(f"❌ Ошибка доступа к {path}: {e}")
            
            if not books_found:
                logger.warning("⚠️ КНИГИ НЕ НАЙДЕНЫ! Проверьте загрузку файлов")
            else:
                final_count = self.get_books_count()
                final_books = self.get_books_list()
                logger.info(f"🎉 ОБРАБОТКА ЗАВЕРШЕНА!")
                logger.info(f"📊 Итого записей в базе: {final_count}")
                logger.info(f"📚 Итого книг: {len(final_books)}")
                logger.info(f"🆕 Новых книг обработано: {total_processed}")
                
                # Список всех книг
                for i, book in enumerate(final_books, 1):
                    logger.info(f"  {i}. {book}")
                
        except Exception as e:
            logger.error(f"❌ Критическая ошибка обработки книг: {e}")
            logger.error(traceback.format_exc())

    def process_book(self, file_path: str, filename: str) -> bool:
        """Обработка одной книги"""
        try:
            # Проверяем не загружена ли уже эта книга
            with self.db.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM knowledge_base WHERE book_name = %s", (filename,))
                existing = cursor.fetchone()[0]
                
                if existing > 0:
                    logger.info(f"📚 Книга {filename} уже в базе знаний ({existing} записей)")
                    return False
            
            text_content = ""
            
            if filename.lower().endswith('.pdf'):
                text_content = self.extract_from_pdf(file_path)
            elif filename.lower().endswith('.txt'):
                with open(file_path, 'r', encoding='utf-8') as f:
                    text_content = f.read()
            elif filename.lower().endswith('.docx'):
                text_content = self.extract_from_docx(file_path)
            elif filename.lower().endswith('.epub'):
                text_content = self.extract_from_epub(file_path)
            
            if text_content and len(text_content) > 100:
                success = self.save_book_content(filename, text_content)
                if success:
                    logger.info(f"💾 Сохранено {len(text_content)} символов из {filename}")
                    return True
                else:
                    logger.warning(f"⚠️ Не удалось сохранить {filename}")
                    return False
            else:
                logger.warning(f"⚠️ Мало текста извлечено из {filename}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Ошибка обработки {filename}: {e}")
            return False

    def extract_from_pdf(self, file_path: str) -> str:
        """Извлечение текста из PDF"""
        try:
            with open(file_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                text = ""
                for page in pdf_reader.pages:
                    text += page.extract_text() + "\n"
                return text
        except Exception as e:
            logger.error(f"Ошибка чтения PDF {file_path}: {e}")
            return ""

    def extract_from_docx(self, file_path: str) -> str:
        """Извлечение текста из DOCX"""
        try:
            doc = docx.Document(file_path)
            text = ""
            for paragraph in doc.paragraphs:
                text += paragraph.text + "\n"
            return text
        except Exception as e:
            logger.error(f"Ошибка чтения DOCX {file_path}: {e}")
            return ""

    def extract_from_epub(self, file_path: str) -> str:
        """Извлечение текста из EPUB"""
        try:
            book = epub.read_epub(file_path)
            text = ""
            for item in book.get_items():
                if item.get_type() == ebooklib.ITEM_DOCUMENT:
                    content = item.get_content().decode('utf-8')
                    # Простое удаление HTML тегов
                    clean_text = re.sub(r'<[^>]+>', '', content)
                    text += clean_text + "\n"
            return text
        except Exception as e:
            logger.error(f"Ошибка чтения EPUB {file_path}: {e}")
            return ""

    def save_book_content(self, book_name: str, content: str) -> bool:
        """Сохранение содержимого книги в базу с retry логикой"""
        try:
            # Разбиваем на части по ~1000 символов
            chunk_size = 1000
            chunks = [content[i:i+chunk_size] for i in range(0, len(content), chunk_size)]
            
            saved_chunks = 0
            
            # Сохраняем порциями для стабильности
            batch_size = 50  # По 50 записей за раз
            
            for batch_start in range(0, len(chunks), batch_size):
                batch_end = min(batch_start + batch_size, len(chunks))
                batch = chunks[batch_start:batch_end]
                
                # Попытка сохранить батч с переподключением
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        with self.db.cursor() as cursor:
                            for i, chunk in enumerate(batch):
                                if len(chunk.strip()) > 50:  # Игнорируем слишком короткие части
                                    keywords = self.extract_keywords(chunk)
                                    category = self.determine_category(chunk)
                                    
                                    cursor.execute("""
                                        INSERT INTO knowledge_base (book_name, chapter, content, keywords, category)
                                        VALUES (%s, %s, %s, %s, %s)
                                    """, (book_name, f"Часть {batch_start + i + 1}", chunk, keywords, category))
                                    saved_chunks += 1
                            
                            self.db.commit()
                            logger.info(f"💾 Сохранен батч {batch_start//batch_size + 1} ({len(batch)} частей)")
                            break  # Успешно сохранено
                            
                    except Exception as e:
                        if attempt < max_retries - 1:
                            logger.warning(f"⚠️ Ошибка сохранения батча, попытка {attempt+1}: {e}")
                            # Переподключаемся к базе
                            try:
                                self.db.close()
                                self.setup_database()
                                time.sleep(1)
                            except:
                                pass
                        else:
                            logger.error(f"❌ Не удалось сохранить батч после {max_retries} попыток: {e}")
                            return False
            
            logger.info(f"📚 Книга {book_name} разбита на {saved_chunks} частей и сохранена")
            return True
                
        except Exception as e:
            logger.error(f"❌ Ошибка сохранения книги {book_name}: {e}")
            return False

    def extract_keywords(self, text: str) -> str:
        """Извлечение ключевых слов"""
        keywords = []
        
        # Ключевые термины Лесли
        lesli_terms = [
            'фрейм', 'доминирование', 'притяжение', 'соблазнение', 'пуш-пул', 
            'кокетство', 'эскалация', 'тест', 'отказ', 'свидание', 'переписка',
            'психология', 'женщина', 'мужчина', 'отношения', 'секс', 'страсть',
            'уверенность', 'харизма', 'статус', 'ценность', 'интерес', 'эмоции'
        ]
        
        text_lower = text.lower()
        for term in lesli_terms:
            if term in text_lower:
                keywords.append(term)
        
        return ', '.join(keywords)

    def determine_category(self, text: str) -> str:
        """Определение категории контента"""
        text_lower = text.lower()
        
        if any(word in text_lower for word in ['свидание', 'встреча', 'ресторан', 'кафе']):
            return 'свидания'
        elif any(word in text_lower for word in ['переписка', 'сообщение', 'текст', 'чат']):
            return 'переписка'
        elif any(word in text_lower for word in ['психология', 'типаж', 'характер', 'личность']):
            return 'психология'
        elif any(word in text_lower for word in ['секс', 'интимность', 'постель', 'близость']):
            return 'интимность'
        else:
            return 'общее'

def main():
    """Главная функция загрузки книг"""
    try:
        logger.info("🚀 ЗАПУСК ЗАГРУЗЧИКА КНИГ ЛЕСЛИ")
        logger.info("📖 Цель: Загрузить все 9 книг в PostgreSQL базу знаний")
        
        # Создаем загрузчик
        loader = BooksLoader()
        
        # Показываем текущее состояние
        current_count = loader.get_books_count()
        current_books = loader.get_books_list()
        
        logger.info(f"📊 Текущее состояние базы:")
        logger.info(f"   • Записей: {current_count}")
        logger.info(f"   • Книг: {len(current_books)}")
        
        if current_books:
            logger.info(f"📚 Уже загружены:")
            for i, book in enumerate(current_books, 1):
                logger.info(f"   {i}. {book}")
        
        # Загружаем все книги
        loader.force_load_all_books()
        
        # Финальный отчет
        final_count = loader.get_books_count()
        final_books = loader.get_books_list()
        
        logger.info("🎉 ЗАГРУЗКА ЗАВЕРШЕНА!")
        logger.info(f"📊 Финальное состояние:")
        logger.info(f"   • Записей: {final_count}")
        logger.info(f"   • Книг: {len(final_books)}")
        logger.info(f"   • Добавлено записей: {final_count - current_count}")
        
        if len(final_books) >= 9:
            logger.info("✅ ВСЕ 9 КНИГ ЛЕСЛИ ЗАГРУЖЕНЫ!")
        else:
            logger.warning(f"⚠️ Загружено {len(final_books)} из 9 книг")
        
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")
        logger.error(traceback.format_exc())
    
    logger.info("🏁 ЗАГРУЗЧИК КНИГ ЗАВЕРШИЛ РАБОТУ")

if __name__ == '__main__':
    main()
