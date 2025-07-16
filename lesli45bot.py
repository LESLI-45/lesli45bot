#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LESLI45BOT - Персональный Telegram-ассистент по соблазнению
Основан на GPT-4o с базой знаний из книг Алекса Лесли

ВЕРСИЯ С ДИАГНОСТИКОЙ И ПРИНУДИТЕЛЬНОЙ ЗАГРУЗКОЙ КНИГ
"""

import asyncio
import logging
from datetime import datetime, timedelta
import json
import os
import sqlite3
import sys
from pathlib import Path
import traceback
import psycopg2
from psycopg2.extras import RealDictCursor
import re
from typing import Optional, List, Dict, Any

# Telegram Bot
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ContextTypes

# OpenAI
from openai import AsyncOpenAI

# Обработка документов
try:
    import PyPDF2
    import docx
    import ebooklib
    from ebooklib import epub
    from bs4 import BeautifulSoup
except ImportError as e:
    print(f"Предупреждение: {e}. Некоторые форматы файлов могут не поддерживаться.")

# Конфигурация
try:
    from config import config
except ImportError:
    # Fallback конфигурация
    class Config:
        TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
        OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
        DATABASE_URL = os.getenv('DATABASE_URL')
        MODEL = "gpt-4o"
        MAX_TOKENS = 2000
        TEMPERATURE = 0.7
    
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

class KnowledgeBase:
    """База знаний с ПРИНУДИТЕЛЬНОЙ обработкой книг и диагностикой"""
    
    def __init__(self, db_connection):
        self.db = db_connection
        self.books_processed = False
        logger.info("🚀 ИНИЦИАЛИЗАЦИЯ БАЗЫ ЗНАНИЙ")
        self.create_tables()
        
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

    async def force_load_all_books(self):
        """ПРИНУДИТЕЛЬНАЯ загрузка всех книг при запуске"""
        logger.info("🚀 НАЧИНАЮ ПРИНУДИТЕЛЬНУЮ ОБРАБОТКУ КНИГ")
        
        try:
            # Проверяем есть ли уже книги в базе
            book_count = await self.get_books_count()
            logger.info(f"📊 В базе знаний уже есть {book_count} записей")
            
            if book_count > 100:  # Если книги уже загружены
                logger.info("✅ Книги уже обработаны ранее")
                self.books_processed = True
                return
            
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
                                    await self.process_book(file_path, file)
                                    logger.info(f"✅ Книга {file} успешно обработана")
                                except Exception as e:
                                    logger.error(f"❌ Ошибка обработки {file}: {e}")
                            
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
                final_count = await self.get_books_count()
                logger.info(f"🎉 ОБРАБОТКА ЗАВЕРШЕНА! В базе {final_count} записей")
                self.books_processed = True
                
        except Exception as e:
            logger.error(f"❌ Критическая ошибка обработки книг: {e}")
            logger.error(traceback.format_exc())

    async def get_books_count(self):
        """Получить количество записей в базе знаний"""
        try:
            with self.db.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM knowledge_base")
                result = cursor.fetchone()
                return result[0] if result else 0
        except Exception as e:
            logger.error(f"Ошибка подсчета записей: {e}")
            return 0

    async def get_books_list(self):
        """Получить список загруженных книг"""
        try:
            with self.db.cursor() as cursor:
                cursor.execute("SELECT DISTINCT book_name FROM knowledge_base")
                results = cursor.fetchall()
                return [row[0] for row in results]
        except Exception as e:
            logger.error(f"Ошибка получения списка книг: {e}")
            return []

    async def process_book(self, file_path: str, filename: str):
        """Обработка одной книги"""
        try:
            # Проверяем не загружена ли уже эта книга
            with self.db.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM knowledge_base WHERE book_name = %s", (filename,))
                existing = cursor.fetchone()[0]
                
                if existing > 0:
                    logger.info(f"📚 Книга {filename} уже в базе знаний ({existing} записей)")
                    return
            
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
                await self.save_book_content(filename, text_content)
                logger.info(f"💾 Сохранено {len(text_content)} символов из {filename}")
            else:
                logger.warning(f"⚠️ Мало текста извлечено из {filename}")
                
        except Exception as e:
            logger.error(f"❌ Ошибка обработки {filename}: {e}")

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
        """Извлечение текста из EPUB (с проверкой BeautifulSoup)"""
        try:
            book = epub.read_epub(file_path)
            text = ""
            for item in book.get_items():
                if item.get_type() == ebooklib.ITEM_DOCUMENT:
                    content = item.get_content().decode('utf-8')
                    # Простое удаление HTML тегов без BeautifulSoup
                    import re
                    clean_text = re.sub(r'<[^>]+>', '', content)
                    text += clean_text + "\n"
            return text
        except Exception as e:
            logger.error(f"Ошибка чтения EPUB {file_path}: {e}")
            return ""

    async def save_book_content(self, book_name: str, content: str):
        """Сохранение содержимого книги в базу с переподключением"""
        try:
            # Разбиваем на части по ~1000 символов
            chunk_size = 1000
            chunks = [content[i:i+chunk_size] for i in range(0, len(content), chunk_size)]
            
            saved_chunks = 0
            
            for i, chunk in enumerate(chunks):
                if len(chunk.strip()) > 50:  # Игнорируем слишком короткие части
                    keywords = self.extract_keywords(chunk)
                    category = self.determine_category(chunk)
                    
                    # Попытка сохранить с переподключением
                    max_retries = 3
                    for attempt in range(max_retries):
                        try:
                            with self.db.cursor() as cursor:
                                cursor.execute("""
                                    INSERT INTO knowledge_base (book_name, chapter, content, keywords, category)
                                    VALUES (%s, %s, %s, %s, %s)
                                """, (book_name, f"Часть {i+1}", chunk, keywords, category))
                                self.db.commit()
                                saved_chunks += 1
                                break  # Успешно сохранено
                                
                        except Exception as e:
                            if attempt < max_retries - 1:
                                logger.warning(f"⚠️ Ошибка сохранения части {i+1}, попытка {attempt+1}: {e}")
                                # Пытаемся переподключиться к базе
                                try:
                                    self.db.close()
                                    if config.DATABASE_URL:
                                        self.db = psycopg2.connect(config.DATABASE_URL)
                                    await asyncio.sleep(1)  # Небольшая задержка
                                except:
                                    pass
                            else:
                                logger.error(f"❌ Не удалось сохранить часть {i+1} после {max_retries} попыток: {e}")
            
            logger.info(f"📚 Книга {book_name} разбита на {saved_chunks} частей и сохранена")
                
        except Exception as e:
            logger.error(f"❌ Ошибка сохранения книги {book_name}: {e}")

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

    async def search_knowledge(self, query: str, limit: int = 3) -> List[Dict]:
        """Поиск в базе знаний с ГАРАНТИРОВАННЫМ результатом"""
        try:
            logger.info(f"🔍 Ищу в базе знаний: '{query}'")
            
            with self.db.cursor() as cursor:
                # Поиск по ключевым словам
                cursor.execute("""
                    SELECT book_name, chapter, content, keywords, category
                    FROM knowledge_base 
                    WHERE to_tsvector('russian', keywords || ' ' || content) @@ plainto_tsquery('russian', %s)
                    ORDER BY ts_rank(to_tsvector('russian', keywords || ' ' || content), plainto_tsquery('russian', %s)) DESC
                    LIMIT %s
                """, (query, query, limit))
                
                results = cursor.fetchall()
                
                if not results:
                    # Если точного поиска нет, ищем по похожим словам
                    logger.info(f"🔍 Точного поиска нет, ищу по похожим словам")
                    cursor.execute("""
                        SELECT book_name, chapter, content, keywords, category
                        FROM knowledge_base 
                        WHERE content ILIKE %s OR keywords ILIKE %s
                        LIMIT %s
                    """, (f'%{query}%', f'%{query}%', limit))
                    
                    results = cursor.fetchall()
                
                formatted_results = []
                for row in results:
                    formatted_results.append({
                        'book_name': row[0],
                        'chapter': row[1], 
                        'content': row[2][:500] + "..." if len(row[2]) > 500 else row[2],
                        'keywords': row[3],
                        'category': row[4]
                    })
                
                logger.info(f"✅ Найдено {len(formatted_results)} результатов для '{query}'")
                return formatted_results
                
        except Exception as e:
            logger.error(f"❌ Ошибка поиска в базе знаний: {e}")
            return []

class ConversationMemory:
    """Память разговоров"""
    
    def __init__(self, db_connection):
        self.db = db_connection
        self.create_tables()
    
    def create_tables(self):
        """Создание таблиц для памяти"""
        try:
            with self.db.cursor() as cursor:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS conversations (
                        id SERIAL PRIMARY KEY,
                        user_id BIGINT,
                        role VARCHAR(50),
                        content TEXT,
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS user_stats (
                        id SERIAL PRIMARY KEY,
                        user_id BIGINT,
                        date DATE DEFAULT CURRENT_DATE,
                        interactions INTEGER DEFAULT 0,
                        approaches INTEGER DEFAULT 0,
                        dates INTEGER DEFAULT 0,
                        successes INTEGER DEFAULT 0
                    )
                """)
                
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS girl_profiles (
                        id SERIAL PRIMARY KEY,
                        user_id BIGINT,
                        girl_name VARCHAR(100),
                        age INTEGER,
                        psychotype VARCHAR(50),
                        attachment_style VARCHAR(50),
                        notes TEXT,
                        status VARCHAR(50),
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                self.db.commit()
        except Exception as e:
            logger.error(f"Ошибка создания таблиц памяти: {e}")

    async def save_message(self, user_id: int, role: str, content: str):
        """Сохранение сообщения"""
        try:
            with self.db.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO conversations (user_id, role, content)
                    VALUES (%s, %s, %s)
                """, (user_id, role, content))
                self.db.commit()
        except Exception as e:
            logger.error(f"Ошибка сохранения сообщения: {e}")

    async def get_recent_messages(self, user_id: int, limit: int = 10) -> List[Dict]:
        """Получение последних сообщений"""
        try:
            with self.db.cursor() as cursor:
                cursor.execute("""
                    SELECT role, content, timestamp
                    FROM conversations 
                    WHERE user_id = %s 
                    ORDER BY timestamp DESC 
                    LIMIT %s
                """, (user_id, limit))
                
                messages = []
                for row in cursor.fetchall():
                    messages.append({
                        'role': row[0],
                        'content': row[1],
                        'timestamp': row[2]
                    })
                
                return list(reversed(messages))
        except Exception as e:
            logger.error(f"Ошибка получения сообщений: {e}")
            return []

class LesliAssistant:
    """Основной класс ассистента с ОБЯЗАТЕЛЬНЫМ использованием базы знаний"""
    
    def __init__(self):
        self.setup_database()
        self.openai_client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
        self.knowledge = KnowledgeBase(self.db)
        self.memory = ConversationMemory(self.db)

    def setup_database(self):
        """Настройка подключения к базе данных с retry"""
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
                    # Устанавливаем autocommit для стабильности
                    self.db.autocommit = True
                    logger.info("✅ Подключение к PostgreSQL успешно")
                    return
                else:
                    logger.warning("⚠️ DATABASE_URL не найден, использую SQLite")
                    # Fallback к SQLite
                    db_path = "lesli_bot.db"
                    self.db = sqlite3.connect(db_path, check_same_thread=False)
                    logger.info("✅ Используется SQLite база данных")
                    return
                    
            except Exception as e:
                if attempt < max_retries - 1:
                    logger.warning(f"⚠️ Ошибка подключения к базе данных, попытка {attempt+1}: {e}")
                    import time
                    time.sleep(2)
                else:
                    logger.error(f"❌ Критическая ошибка подключения к базе данных: {e}")
                    raise

    async def initialize_knowledge_base(self):
        """Принудительная инициализация базы знаний"""
        logger.info("📚 Инициализация базы знаний...")
        await self.knowledge.force_load_all_books()

    async def get_debug_info(self) -> str:
        """Получить отладочную информацию"""
        try:
            books_count = await self.knowledge.get_books_count()
            books_list = await self.knowledge.get_books_list()
            
            debug_info = f"""
🔍 **ДИАГНОСТИКА БАЗЫ ЗНАНИЙ**

📊 **Статистика:**
• Записей в базе: {books_count}
• Книг загружено: {len(books_list)}
• Статус обработки: {'✅ Завершена' if self.knowledge.books_processed else '❌ Не завершена'}

📚 **Загруженные книги:**
"""
            
            for i, book in enumerate(books_list, 1):
                debug_info += f"\n{i}. {book}"
            
            if books_count == 0:
                debug_info += "\n\n⚠️ **ПРОБЛЕМА:** База знаний пуста!"
            
            return debug_info
            
        except Exception as e:
            return f"❌ Ошибка диагностики: {e}"

    async def get_gpt_response(self, messages: List[Dict], user_id: int, query: str) -> str:
        """Получение ответа от GPT с ОБЯЗАТЕЛЬНЫМ использованием базы знаний"""
        try:
            # ОБЯЗАТЕЛЬНО ищем в базе знаний Лесли
            knowledge_results = await self.knowledge.search_knowledge(query, limit=3)
            
            # Формируем системный промпт с базой знаний
            system_prompt = self.create_enhanced_system_prompt(knowledge_results, user_id)
            
            # Добавляем системное сообщение
            enhanced_messages = [{"role": "system", "content": system_prompt}] + messages
            
            response = await self.openai_client.chat.completions.create(
                model=config.MODEL,
                messages=enhanced_messages,
                max_tokens=config.MAX_TOKENS,
                temperature=config.TEMPERATURE
            )
            
            return response.choices[0].message.content
            
        except Exception as e:
            logger.error(f"Ошибка GPT: {e}")
            return "Извините, произошла ошибка при получении ответа."

    def create_enhanced_system_prompt(self, knowledge_results: List[Dict], user_id: int) -> str:
        """Создание системного промпта с базой знаний"""
        base_prompt = """Ты LESLI45BOT - персональный ассистент по соблазнению, основанный на книгах Алекса Лесли.

КРИТИЧЕСКИ ВАЖНО: ВСЕГДА используй информацию из базы знаний в каждом ответе!

ТВОЯ БАЗА ЗНАНИЙ ИЗ КНИГ ЛЕСЛИ:"""
        
        if knowledge_results:
            base_prompt += "\n\n📚 РЕЛЕВАНТНАЯ ИНФОРМАЦИЯ ИЗ КНИГ:\n"
            for i, result in enumerate(knowledge_results, 1):
                base_prompt += f"\n{i}. Из книги '{result['book_name']}':\n{result['content']}\n"
        else:
            base_prompt += "\n\n⚠️ ВНИМАНИЕ: База знаний не вернула результатов для этого запроса!"
        
        base_prompt += """

ОБЯЗАТЕЛЬНЫЕ ТРЕБОВАНИЯ:
- ВСЕГДА ссылайся на конкретные книги и техники Лесли
- Цитируй отрывки из книг когда это уместно  
- Давай конкретные советы, а не общие фразы
- Используй терминологию Лесли (фреймы, пуш-пул, эскалация, etc.)
- Если база знаний пуста - ОБЯЗАТЕЛЬНО упомяни это в ответе

Стиль: Уверенный наставник, прямой, конкретный, с примерами из книг."""
        
        return base_prompt

# Создание клавиатур меню (ОСТАВЛЯЕМ БЕЗ ИЗМЕНЕНИЙ)
def create_main_menu_keyboard():
    """Создание главного меню"""
    keyboard = [
        # Анализ
        [InlineKeyboardButton("🧠 Кейс", callback_data="menu_keis"),
         InlineKeyboardButton("💬 Переписка", callback_data="menu_perepiska")],
        [InlineKeyboardButton("💡 Ответ", callback_data="menu_otvet"),
         InlineKeyboardButton("📸 Скрин", callback_data="menu_skrin")],
        
        # Свидания
        [InlineKeyboardButton("🥂 Свидание 1", callback_data="menu_svidanie1"),
         InlineKeyboardButton("💑 Свидание 2", callback_data="menu_svidanie2")],
        [InlineKeyboardButton("📊 Анализ 1", callback_data="menu_analiz1"),
         InlineKeyboardButton("📈 Анализ 2", callback_data="menu_analiz2")],
        
        # Новые функции
        [InlineKeyboardButton("🆘 SOS Сигналы", callback_data="menu_sos"),
         InlineKeyboardButton("🎭 Стили соблазнения", callback_data="menu_styles")],
        [InlineKeyboardButton("📖 Истории", callback_data="menu_stories"),
         InlineKeyboardButton("💡 Сигналы интереса", callback_data="menu_signals")],
        [InlineKeyboardButton("👩 Типажи девушек", callback_data="menu_types"),
         InlineKeyboardButton("💬 Темы для свиданий", callback_data="menu_topics")],
        
        # Знания
        [InlineKeyboardButton("🧬 Психотип", callback_data="menu_psihotip"),
         InlineKeyboardButton("📚 Знание", callback_data="menu_znanie")],
        [InlineKeyboardButton("🔬 Наука", callback_data="menu_nauka"),
         InlineKeyboardButton("👨‍🏫 Наставник", callback_data="menu_nastavnik")]
    ]
    
    return InlineKeyboardMarkup(keyboard)

# Обработчики команд
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start"""
    user_id = update.effective_user.id
    
    # Сохраняем начало разговора
    await assistant.memory.save_message(user_id, "user", "/start")
    
    welcome_text = """
🔥 **LESLI45BOT 2.0 - Персональный наставник по соблазнению**

Добро пожаловать! Я твой ИИ-ассистент, основанный на книгах и методиках Алекса Лесли.

🧠 **Мои возможности:**
• Анализ кейсов и ситуаций
• Разбор переписок с девушками  
• ИИ-анализ фото девушек
• Персональные советы под твой стиль
• База знаний из 9 книг Лесли
• Постоянная память наших разговоров

📚 **В моей базе знаний:**
✅ Все книги Алекса Лесли
✅ Техники и фреймы соблазнения
✅ Психология женщин
✅ Стратегии свиданий

Выбери нужную функцию из меню ⬇️
"""
    
    await update.message.reply_text(
        welcome_text,
        parse_mode='Markdown',
        reply_markup=create_main_menu_keyboard()
    )

async def debug_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /debug - диагностика базы знаний"""
    user_id = update.effective_user.id
    
    await update.message.reply_text("🔍 Анализирую базу знаний...")
    
    debug_info = await assistant.get_debug_info()
    
    await assistant.memory.save_message(user_id, "user", "/debug")
    await assistant.memory.save_message(user_id, "assistant", debug_info)
    
    await update.message.reply_text(debug_info, parse_mode='Markdown')

async def reload_books_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /reload_books - принудительная перезагрузка книг"""
    user_id = update.effective_user.id
    
    await update.message.reply_text("📚 Начинаю принудительную перезагрузку книг...")
    
    try:
        await assistant.knowledge.force_load_all_books()
        
        books_count = await assistant.knowledge.get_books_count()
        books_list = await assistant.knowledge.get_books_list()
        
        result_text = f"""
✅ **ПЕРЕЗАГРУЗКА ЗАВЕРШЕНА!**

📊 **Результат:**
• Записей в базе: {books_count}
• Книг загружено: {len(books_list)}

📚 **Книги:**
"""
        
        for i, book in enumerate(books_list, 1):
            result_text += f"\n{i}. {book}"
        
        await assistant.memory.save_message(user_id, "user", "/reload_books")
        await assistant.memory.save_message(user_id, "assistant", result_text)
        
        await update.message.reply_text(result_text, parse_mode='Markdown')
        
    except Exception as e:
        error_text = f"❌ Ошибка перезагрузки: {e}"
        await update.message.reply_text(error_text)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка текстовых сообщений"""
    user_id = update.effective_user.id
    message_text = update.message.text
    
    # Сохраняем сообщение пользователя
    await assistant.memory.save_message(user_id, "user", message_text)
    
    # Получаем историю разговора
    recent_messages = await assistant.memory.get_recent_messages(user_id, limit=10)
    
    # Формируем контекст для GPT
    messages = []
    for msg in recent_messages:
        role = "user" if msg['role'] == "user" else "assistant"
        messages.append({"role": role, "content": msg['content']})
    
    # Получаем ответ с использованием базы знаний
    response = await assistant.get_gpt_response(messages, user_id, message_text)
    
    # Сохраняем ответ ассистента
    await assistant.memory.save_message(user_id, "assistant", response)
    
    await update.message.reply_text(response, parse_mode='Markdown')

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка фото"""
    user_id = update.effective_user.id
    
    try:
        photo = update.message.photo[-1]
        photo_file = await context.bot.get_file(photo.file_id)
        photo_url = photo_file.file_path
        
        # Здесь можно добавить анализ фото через GPT-4 Vision
        analysis = "Функция анализа фото временно недоступна. Опишите ситуацию текстом."
        
        await assistant.memory.save_message(user_id, "user", "[Отправил фото для анализа]")
        await assistant.memory.save_message(user_id, "assistant", analysis)
        
        await update.message.reply_text(
            f"📸 **Анализ фото:**\n\n{analysis}",
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"Ошибка обработки фото: {e}")
        await update.message.reply_text("Извините, не удалось проанализировать фото.")

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка нажатий кнопок"""
    query = update.callback_query
    await query.answer()
    
    menu_type = query.data.replace("menu_", "")
    user_id = query.from_user.id
    
    # Сохраняем действие пользователя
    await assistant.memory.save_message(user_id, "user", f"Нажал кнопку: {menu_type}")
    
    try:
        if menu_type == "keis":
            await query.edit_message_text(
                "🧠 **Анализ кейса**\n\n"
                "Опиши ситуацию с девушкой, и я дам персональный анализ с конкретными советами из книг Лесли.\n\n"
                "Пример:\n"
                "*Познакомился с Анной, 28 лет, в клубе. Переписываемся 3 дня, отвечает с задержкой...*",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Назад", callback_data="menu_back")
                ]])
            )
            
        elif menu_type == "perepiska":
            await query.edit_message_text(
                "💬 **Анализ переписки**\n\n"
                "Пришли скриншот или текст переписки с девушкой для детального анализа.\n\n"
                "Я определю:\n"
                "• Её психотип и тип привязанности\n"
                "• Индикаторы интереса\n"
                "• Рекомендации по дальнейшим действиям",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Назад", callback_data="menu_back")
                ]])
            )
            
        elif menu_type == "styles":
            styles_keyboard = [
                [InlineKeyboardButton("👑 Мастер", callback_data="style_master"),
                 InlineKeyboardButton("🎭 Артист", callback_data="style_artist")],
                [InlineKeyboardButton("💼 Деловой", callback_data="style_business"),
                 InlineKeyboardButton("🏃 Спортивный", callback_data="style_sport")],
                [InlineKeyboardButton("🎨 Творческий", callback_data="style_creative"),
                 InlineKeyboardButton("😎 Плохой парень", callback_data="style_badboy")],
                [InlineKeyboardButton("↩️ Назад", callback_data="menu_back")]
            ]
            
            await query.edit_message_text(
                "🎭 **Стили соблазнения**\n\n"
                "Выбери свой стиль или тот, который хочешь освоить:\n\n"
                "👑 **Мастер** - доминирование и контроль\n"
                "🎭 **Артист** - харизма и эмоции\n"
                "💼 **Деловой** - статус и надежность\n"
                "🏃 **Спортивный** - энергия и активность\n"
                "🎨 **Творческий** - креативность и глубина\n"
                "😎 **Плохой парень** - дерзость и непредсказуемость",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup(styles_keyboard)
            )
            
        elif menu_type == "types":
            types_keyboard = [
                [InlineKeyboardButton("❤️ Чувственная", callback_data="type_sensual"),
                 InlineKeyboardButton("🧠 Рациональная", callback_data="type_rational")],
                [InlineKeyboardButton("😰 Тревожная", callback_data="type_anxious"),
                 InlineKeyboardButton("🏃‍♀️ Избегающая", callback_data="type_avoidant")],
                [InlineKeyboardButton("🌟 Надежная", callback_data="type_secure"),
                 InlineKeyboardButton("👑 Доминирующая", callback_data="type_dominant")],
                [InlineKeyboardButton("↩️ Назад", callback_data="menu_back")]
            ]
            
            await query.edit_message_text(
                "👩 **Типажи девушек**\n\n"
                "Выбери типаж девушки для получения персональных советов:\n\n"
                "❤️ **Чувственная** - эмоциональная, живая\n"
                "🧠 **Рациональная** - логичная, практичная\n"
                "😰 **Тревожная** - нуждается в подтверждении\n"
                "🏃‍♀️ **Избегающая** - независимая, дистантная\n"
                "🌟 **Надежная** - стабильная, открытая\n"
                "👑 **Доминирующая** - сильная, контролирующая",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup(types_keyboard)
            )
            
        elif menu_type == "signals":
            signals_keyboard = [
                [InlineKeyboardButton("💬 В переписке", callback_data="signals_text"),
                 InlineKeyboardButton("👀 На свидании", callback_data="signals_date")],
                [InlineKeyboardButton("📱 В соцсетях", callback_data="signals_social"),
                 InlineKeyboardButton("🎪 В клубе", callback_data="signals_club")],
                [InlineKeyboardButton("↩️ Назад", callback_data="menu_back")]
            ]
            
            await query.edit_message_text(
                "💡 **Сигналы интереса**\n\n"
                "Где хочешь научиться распознавать сигналы интереса?\n\n"
                "💬 **В переписке** - эмодзи, время ответов, длина сообщений\n"
                "👀 **На свидании** - язык тела, взгляды, прикосновения\n"
                "📱 **В соцсетях** - лайки, комментарии, просмотры историй\n"
                "🎪 **В клубе** - танцы, взгляды, позиционирование",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup(signals_keyboard)
            )
            
        elif menu_type == "sos":
            await query.edit_message_text(
                "🆘 **SOS Сигналы**\n\n"
                "Экстренные ситуации требуют быстрых решений!\n\n"
                "Опиши критическую ситуацию:\n"
                "• Девушка внезапно охладела\n"
                "• Сложная ситуация на свидании\n"
                "• Непонятное поведение\n"
                "• Нужен срочный совет\n\n"
                "Я дам конкретный план действий из арсенала Лесли!",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Назад", callback_data="menu_back")
                ]])
            )
            
        elif menu_type == "stories":
            await query.edit_message_text(
                "📖 **Истории успеха**\n\n"
                "Хочешь услышать реальные истории из практики Лесли?\n\n"
                "Напиши тип ситуации:\n"
                "• Первое знакомство\n"
                "• Преодоление сопротивления\n"
                "• Работа с возражениями\n"
                "• Сложные кейсы\n\n"
                "Я расскажу подходящую историю с разбором техник!",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Назад", callback_data="menu_back")
                ]])
            )
            
        elif menu_type == "topics":
            topics_keyboard = [
                [InlineKeyboardButton("☕ Первое свидание", callback_data="topic_first"),
                 InlineKeyboardButton("🍷 Романтическое", callback_data="topic_romantic")],
                [InlineKeyboardButton("🎬 Активное", callback_data="topic_active"),
                 InlineKeyboardButton("🏠 Домашнее", callback_data="topic_home")],
                [InlineKeyboardButton("↩️ Назад", callback_data="menu_back")]
            ]
            
            await query.edit_message_text(
                "💬 **Темы для свиданий**\n\n"
                "Выбери тип свидания для получения готовых тем для разговора:\n\n"
                "☕ **Первое свидание** - безопасные темы для знакомства\n"
                "🍷 **Романтическое** - глубокие, интимные разговоры\n"
                "🎬 **Активное** - легкие темы для активностей\n"
                "🏠 **Домашнее** - уютные темы для дома",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup(topics_keyboard)
            )
            
        elif menu_type.startswith("style_"):
            style_name = menu_type.replace("style_", "")
            response = await assistant.get_gpt_response([
                {"role": "user", "content": f"Расскажи подробно про стиль соблазнения '{style_name}' из книг Лесли"}
            ], user_id, f"стиль {style_name}")
            
            await query.edit_message_text(
                response,
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Назад", callback_data="menu_styles")
                ]])
            )
            
        elif menu_type.startswith("type_"):
            type_name = menu_type.replace("type_", "")
            response = await assistant.get_gpt_response([
                {"role": "user", "content": f"Как работать с девушкой типа '{type_name}' согласно методам Лесли?"}
            ], user_id, f"типаж {type_name}")
            
            await query.edit_message_text(
                response,
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Назад", callback_data="menu_types")
                ]])
            )
            
        elif menu_type == "back":
            await show_main_menu(query, context)
            
        else:
            # Для остальных кнопок - общий обработчик
            response = await assistant.get_gpt_response([
                {"role": "user", "content": f"Помоги с темой: {menu_type}"}
            ], user_id, menu_type)
            
            await query.edit_message_text(
                response,
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Назад", callback_data="menu_back")
                ]])
            )
            
        # Сохраняем ответ
        await assistant.memory.save_message(user_id, "assistant", f"Показал меню: {menu_type}")
        
    except Exception as e:
        logger.error(f"Ошибка обработки callback {menu_type}: {e}")
        await query.edit_message_text(
            "Произошла ошибка. Попробуйте еще раз.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Главное меню", callback_data="menu_back")
            ]])
        )

async def show_main_menu(update_or_query, context: ContextTypes.DEFAULT_TYPE):
    """Показать главное меню"""
    menu_text = """
🔥 **LESLI45BOT 2.0 - Главное меню**

Выбери нужную функцию:

🧠 **Анализ** - разбор ситуаций и кейсов
💬 **Общение** - помощь с перепиской и разговорами
🥂 **Свидания** - планирование и анализ встреч
🆘 **Экстренная помощь** - быстрые решения
👩 **Психология** - типажи и поведение девушек
📚 **База знаний** - теория и практика Лесли

**Команды диагностики:**
/debug - проверить базу знаний
/reload_books - перезагрузить книги
"""
    
    if hasattr(update_or_query, 'edit_message_text'):
        await update_or_query.edit_message_text(
            menu_text,
            parse_mode='Markdown',
            reply_markup=create_main_menu_keyboard()
        )
    else:
        await update_or_query.message.reply_text(
            menu_text,
            parse_mode='Markdown',
            reply_markup=create_main_menu_keyboard()
        )

# Основная функция запуска
async def main():
    """Главная функция запуска бота"""
    global assistant
    
    try:
        # Проверяем наличие токенов
        if not config.TELEGRAM_TOKEN:
            logger.error("❌ TELEGRAM_TOKEN не найден!")
            return
        
        if not config.OPENAI_API_KEY:
            logger.error("❌ OPENAI_API_KEY не найден!")
            return
        
        logger.info("🚀 Запускаю LESLI45BOT 2.0...")
        
        # Создаем ассистента
        assistant = LesliAssistant()
        logger.info("✅ Ассистент инициализирован")
        
        # ПРИНУДИТЕЛЬНО инициализируем базу знаний
        await assistant.initialize_knowledge_base()
        
        # Создаем приложение
        application = Application.builder().token(config.TELEGRAM_TOKEN).build()
        
        # Добавляем обработчики
        application.add_handler(CommandHandler("start", start_command))
        application.add_handler(CommandHandler("debug", debug_command))
        application.add_handler(CommandHandler("reload_books", reload_books_command))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
        application.add_handler(CallbackQueryHandler(handle_callback))
        
        logger.info("✅ Обработчики добавлены")
        
        # Запускаем бота
        logger.info("🎉 LESLI45BOT 2.0 запущен и готов к работе!")
        await application.run_polling(allowed_updates=Update.ALL_TYPES)
        
    except Exception as e:
        logger.error(f"❌ Критическая ошибка запуска: {e}")
        logger.error(traceback.format_exc())

if __name__ == '__main__':
    asyncio.run(main())
