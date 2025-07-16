#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LESLI45BOT - Персональный Telegram-ассистент по соблазнению
Основан на GPT-4o с базой знаний из книг Алекса Лесли
TELEBOT VERSION - простая и надежная
"""

import asyncio
import logging
import os
import sys
import traceback
import threading
import time
from typing import Optional, List, Dict, Any

# Telegram Bot API (простая библиотека)
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, Message

# OpenAI API
from openai import AsyncOpenAI

# Database
import asyncpg
import sqlite3

# File processing
import PyPDF2
import docx
import ebooklib
from ebooklib import epub
from io import BytesIO
import re

# Image processing
from PIL import Image
import base64
import requests

# Configuration
class Config:
    def __init__(self):
        self.TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
        self.OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
        self.DATABASE_URL = os.getenv('DATABASE_URL')
        self.MODEL = "gpt-4o"
        self.MAX_TOKENS = 2000
        self.TEMPERATURE = 0.7

config = Config()

# Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Создаем бота
bot = telebot.TeleBot(config.TELEGRAM_TOKEN)

class KnowledgeBase:
    """Класс для работы с базой знаний из книг"""
    
    def __init__(self, db_connection=None):
        self.db = db_connection
        self.create_tables()
        
    def create_tables(self):
        """Создание таблиц базы знаний"""
        try:
            if isinstance(self.db, sqlite3.Connection):
                cursor = self.db.cursor()
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS knowledge_base (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        book_name TEXT NOT NULL,
                        content TEXT NOT NULL,
                        keywords TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                cursor.execute('''
                    CREATE INDEX IF NOT EXISTS idx_keywords ON knowledge_base(keywords)
                ''')
                self.db.commit()
                logger.info("✅ SQLite таблицы созданы")
            else:
                # PostgreSQL - создаем в отдельном потоке
                threading.Thread(target=self._create_postgres_tables_sync).start()
        except Exception as e:
            logger.error(f"Ошибка создания таблиц: {e}")
    
    def _create_postgres_tables_sync(self):
        """Создание таблиц PostgreSQL синхронно"""
        try:
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._create_postgres_tables())
            loop.close()
        except Exception as e:
            logger.error(f"Ошибка создания PostgreSQL таблиц: {e}")
    
    async def _create_postgres_tables(self):
        """Создание таблиц в PostgreSQL"""
        try:
            await self.db.execute('''
                CREATE TABLE IF NOT EXISTS knowledge_base (
                    id SERIAL PRIMARY KEY,
                    book_name TEXT NOT NULL,
                    content TEXT NOT NULL,
                    keywords TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            await self.db.execute('''
                CREATE INDEX IF NOT EXISTS idx_keywords ON knowledge_base(keywords)
            ''')
            logger.info("✅ PostgreSQL таблицы созданы")
        except Exception as e:
            logger.error(f"Ошибка создания PostgreSQL таблиц: {e}")
    
    def search_knowledge_sync(self, query: str, limit: int = 5) -> List[Dict]:
        """Синхронный поиск в базе знаний"""
        try:
            keywords = query.lower().split()
            
            if isinstance(self.db, sqlite3.Connection):
                cursor = self.db.cursor()
                placeholders = ' OR '.join(['content LIKE ?' for _ in keywords])
                search_terms = [f'%{keyword}%' for keyword in keywords]
                
                cursor.execute(f'''
                    SELECT book_name, content FROM knowledge_base 
                    WHERE {placeholders}
                    ORDER BY created_at DESC
                    LIMIT ?
                ''', search_terms + [limit])
                
                results = cursor.fetchall()
                return [{'book': row[0], 'content': row[1]} for row in results]
            else:
                # PostgreSQL - используем синхронную обертку
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    result = loop.run_until_complete(self.search_knowledge_async(query, limit))
                    return result
                finally:
                    loop.close()
                
        except Exception as e:
            logger.error(f"Ошибка поиска в базе знаний: {e}")
            return []
    
    async def search_knowledge_async(self, query: str, limit: int = 5) -> List[Dict]:
        """Асинхронный поиск в PostgreSQL"""
        try:
            keywords = query.lower().split()
            placeholders = ' OR '.join(['content ILIKE $' + str(i+1) for i in range(len(keywords))])
            search_terms = [f'%{keyword}%' for keyword in keywords]
            
            query_sql = f'''
                SELECT book_name, content FROM knowledge_base 
                WHERE {placeholders}
                ORDER BY created_at DESC
                LIMIT ${len(keywords)+1}
            '''
            
            results = await self.db.fetch(query_sql, *search_terms, limit)
            return [{'book': row['book_name'], 'content': row['content']} for row in results]
        except Exception as e:
            logger.error(f"Ошибка поиска в PostgreSQL: {e}")
            return []
    
    def force_load_all_books_sync(self):
        """Синхронная загрузка книг"""
        try:
            logger.info("🚀 НАЧИНАЮ ПРИНУДИТЕЛЬНУЮ ОБРАБОТКУ КНИГ")
            
            # Проверяем есть ли уже книги
            count = 0
            if isinstance(self.db, sqlite3.Connection):
                cursor = self.db.cursor()
                cursor.execute("SELECT COUNT(*) FROM knowledge_base")
                count = cursor.fetchone()[0]
            else:
                # PostgreSQL
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    result = loop.run_until_complete(self.db.fetchrow("SELECT COUNT(*) FROM knowledge_base"))
                    count = result[0] if result else 0
                finally:
                    loop.close()
            
            logger.info(f"📊 В базе знаний уже есть {count} записей")
            
            # Если записей больше 100, считаем что книги уже загружены
            if count > 100:
                logger.info("✅ Книги уже обработаны ранее")
                return
            
            # Ищем книги в разных папках
            possible_paths = [
                "/opt/render/project/src/books/",
                "./books/",
                "/books/",
                "/opt/render/project/src/",
                "./",
                os.path.join(os.getcwd(), "books")
            ]
            
            books_processed = 0
            
            for path in possible_paths:
                if os.path.exists(path):
                    logger.info(f"🔍 Ищу книги в: {path}")
                    files = [f for f in os.listdir(path) if f.lower().endswith(('.pdf', '.docx', '.txt', '.epub'))]
                    
                    if files:
                        logger.info(f"📚 Найдено {len(files)} книг в {path}")
                        
                        for file in files:
                            try:
                                file_path = os.path.join(path, file)
                                content = self.extract_text_from_file(file_path)
                                
                                if content:
                                    self.save_book_content_sync(file, content)
                                    books_processed += 1
                                    logger.info(f"✅ Книга {file} обработана успешно")
                                    
                            except Exception as e:
                                logger.error(f"❌ Ошибка обработки {file}: {e}")
                        
                        if books_processed > 0:
                            break
            
            if books_processed == 0:
                logger.warning("⚠️ Книги не найдены ни в одной папке")
            else:
                logger.info(f"🎉 Обработано {books_processed} книг!")
                
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки книг: {e}")
    
    def extract_text_from_file(self, file_path: str) -> str:
        """Извлечение текста из файла"""
        try:
            if file_path.lower().endswith('.pdf'):
                return self.extract_from_pdf(file_path)
            elif file_path.lower().endswith('.docx'):
                return self.extract_from_docx(file_path)
            elif file_path.lower().endswith('.txt'):
                return self.extract_from_txt(file_path)
            elif file_path.lower().endswith('.epub'):
                return self.extract_from_epub(file_path)
            else:
                return ""
        except Exception as e:
            logger.error(f"Ошибка извлечения текста из {file_path}: {e}")
            return ""
    
    def extract_from_pdf(self, file_path: str) -> str:
        """Извлечение текста из PDF"""
        try:
            text = ""
            with open(file_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                for page in pdf_reader.pages:
                    text += page.extract_text()
            return text
        except Exception as e:
            logger.error(f"Ошибка PDF {file_path}: {e}")
            return ""
    
    def extract_from_docx(self, file_path: str) -> str:
        """Извлечение текста из DOCX"""
        try:
            doc = docx.Document(file_path)
            text = "\n".join([paragraph.text for paragraph in doc.paragraphs])
            return text
        except Exception as e:
            logger.error(f"Ошибка DOCX {file_path}: {e}")
            return ""
    
    def extract_from_txt(self, file_path: str) -> str:
        """Извлечение текста из TXT"""
        try:
            with open(file_path, 'r', encoding='utf-8') as file:
                return file.read()
        except Exception as e:
            logger.error(f"Ошибка TXT {file_path}: {e}")
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
            logger.error(f"Ошибка EPUB {file_path}: {e}")
            return ""
    
    def save_book_content_sync(self, book_name: str, content: str):
        """Синхронное сохранение содержимого книги"""
        try:
            # Разбиваем на части по ~1000 символов
            chunk_size = 1000
            chunks = [content[i:i+chunk_size] for i in range(0, len(content), chunk_size)]
            
            for chunk in chunks:
                if len(chunk.strip()) > 50:  # Пропускаем очень короткие части
                    keywords = self.extract_keywords(chunk)
                    
                    if isinstance(self.db, sqlite3.Connection):
                        cursor = self.db.cursor()
                        cursor.execute('''
                            INSERT INTO knowledge_base (book_name, content, keywords)
                            VALUES (?, ?, ?)
                        ''', (book_name, chunk, keywords))
                        self.db.commit()
                    else:
                        # PostgreSQL
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        try:
                            loop.run_until_complete(self.db.execute('''
                                INSERT INTO knowledge_base (book_name, content, keywords)
                                VALUES ($1, $2, $3)
                            ''', book_name, chunk, keywords))
                        finally:
                            loop.close()
            
            logger.info(f"📚 Книга {book_name} разбита на {len(chunks)} частей и сохранена")
                        
        except Exception as e:
            logger.error(f"Ошибка сохранения книги {book_name}: {e}")
    
    def extract_keywords(self, text: str) -> str:
        """Извлечение ключевых слов из текста"""
        try:
            words = re.findall(r'\b\w+\b', text.lower())
            keywords = [word for word in words if len(word) > 3]
            return ' '.join(keywords[:20])
        except Exception as e:
            logger.error(f"Ошибка извлечения ключевых слов: {e}")
            return ""

class ConversationMemory:
    """Класс для работы с памятью разговоров"""
    
    def __init__(self, db_connection=None):
        self.db = db_connection
        self.create_tables()
    
    def create_tables(self):
        """Создание таблиц для памяти"""
        try:
            if isinstance(self.db, sqlite3.Connection):
                cursor = self.db.cursor()
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS conversations (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        role TEXT NOT NULL,
                        message TEXT NOT NULL,
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                self.db.commit()
                logger.info("✅ Таблицы памяти созданы")
            else:
                # PostgreSQL
                threading.Thread(target=self._create_postgres_memory_tables_sync).start()
        except Exception as e:
            logger.error(f"Ошибка создания таблиц памяти: {e}")
    
    def _create_postgres_memory_tables_sync(self):
        """Создание таблиц памяти PostgreSQL синхронно"""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._create_postgres_memory_tables())
            loop.close()
        except Exception as e:
            logger.error(f"Ошибка создания таблиц памяти: {e}")
    
    async def _create_postgres_memory_tables(self):
        """Создание таблиц памяти в PostgreSQL"""
        try:
            await self.db.execute('''
                CREATE TABLE IF NOT EXISTS conversations (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    role TEXT NOT NULL,
                    message TEXT NOT NULL,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            logger.info("✅ Таблицы памяти PostgreSQL созданы")
        except Exception as e:
            logger.error(f"Ошибка создания таблиц памяти PostgreSQL: {e}")
    
    def save_message_sync(self, user_id: int, role: str, message: str):
        """Синхронное сохранение сообщения"""
        try:
            if isinstance(self.db, sqlite3.Connection):
                cursor = self.db.cursor()
                cursor.execute('''
                    INSERT INTO conversations (user_id, role, message)
                    VALUES (?, ?, ?)
                ''', (user_id, role, message))
                self.db.commit()
            else:
                # PostgreSQL
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(self.db.execute('''
                        INSERT INTO conversations (user_id, role, message)
                        VALUES ($1, $2, $3)
                    ''', user_id, role, message))
                finally:
                    loop.close()
        except Exception as e:
            logger.error(f"Ошибка сохранения сообщения: {e}")
    
    def get_conversation_history_sync(self, user_id: int, limit: int = 10) -> List[Dict]:
        """Синхронное получение истории разговора"""
        try:
            if isinstance(self.db, sqlite3.Connection):
                cursor = self.db.cursor()
                cursor.execute('''
                    SELECT role, message FROM conversations 
                    WHERE user_id = ? 
                    ORDER BY timestamp DESC 
                    LIMIT ?
                ''', (user_id, limit))
                
                results = cursor.fetchall()
                return [{'role': row[0], 'content': row[1]} for row in reversed(results)]
            else:
                # PostgreSQL
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    results = loop.run_until_complete(self.db.fetch('''
                        SELECT role, message FROM conversations 
                        WHERE user_id = $1 
                        ORDER BY timestamp DESC 
                        LIMIT $2
                    ''', user_id, limit))
                    
                    return [{'role': row['role'], 'content': row['message']} for row in reversed(results)]
                finally:
                    loop.close()
        except Exception as e:
            logger.error(f"Ошибка получения истории: {e}")
            return []

class LesliAssistant:
    """Главный класс бота-ассистента"""
    
    def __init__(self):
        self.openai_client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
        self.db = None
        self.knowledge = None
        self.memory = None
        self.initialize_database()
    
    def initialize_database(self):
        """Синхронная инициализация базы данных"""
        try:
            if config.DATABASE_URL and config.DATABASE_URL.startswith('postgresql'):
                logger.info("🔗 Подключаюсь к PostgreSQL...")
                # Создаем подключение в отдельном потоке
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                self.db = loop.run_until_complete(asyncpg.connect(config.DATABASE_URL))
                logger.info("✅ Подключение к PostgreSQL успешно")
            else:
                logger.info("🔗 Использую SQLite базу данных")
                self.db = sqlite3.connect('lesli_bot.db', check_same_thread=False)
                
            self.knowledge = KnowledgeBase(self.db)
            self.memory = ConversationMemory(self.db)
            
            # Загружаем книги
            self.initialize_knowledge_base()
            
        except Exception as e:
            logger.error(f"❌ Ошибка подключения к базе данных: {e}")
            # Fallback к SQLite
            self.db = sqlite3.connect('lesli_bot.db', check_same_thread=False)
            self.knowledge = KnowledgeBase(self.db)
            self.memory = ConversationMemory(self.db)
    
    def initialize_knowledge_base(self):
        """Инициализация базы знаний"""
        logger.info("📚 Инициализация базы знаний...")
        threading.Thread(target=self.knowledge.force_load_all_books_sync).start()
    
    def get_gpt_response_sync(self, messages: List[Dict]) -> str:
        """Синхронное получение ответа от GPT"""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                response = loop.run_until_complete(self.openai_client.chat.completions.create(
                    model=config.MODEL,
                    messages=messages,
                    max_tokens=config.MAX_TOKENS,
                    temperature=config.TEMPERATURE
                ))
                return response.choices[0].message.content
            finally:
                loop.close()
        except Exception as e:
            logger.error(f"Ошибка GPT: {e}")
            return "Извините, произошла ошибка при получении ответа. Попробуйте еще раз."
    
    def process_message(self, user_message: str, user_id: int) -> str:
        """Обработка сообщения пользователя"""
        try:
            # Поиск в базе знаний
            knowledge_results = self.knowledge.search_knowledge_sync(user_message, limit=3)
            
            # Получаем историю разговора
            conversation_history = self.memory.get_conversation_history_sync(user_id, limit=5)
            
            # Формируем контекст
            knowledge_context = ""
            if knowledge_results:
                knowledge_context = "\n".join([
                    f"Из книги '{result['book']}': {result['content'][:300]}..."
                    for result in knowledge_results
                ])
            
            # Системный промпт
            system_prompt = f"""Ты LESLI45BOT - персональный наставник по соблазнению на основе методов Алекса Лесли.

ТВОИ СПЕЦИАЛИЗАЦИИ:
🎯 Анализ кейсов и ситуаций
💬 Помощь с перепиской
🥂 Стратегии для свиданий
🧠 Психологический анализ
🆘 SOS техники экстренного влияния
🎭 Стили соблазнения (Подонок, Романтик, Провокатор, Структурный, Мастер)
👩 Работа с разными типажами девушек
💡 Распознавание сигналов интереса
📖 Создание убедительных историй
💬 Темы для первых свиданий

БАЗА ЗНАНИЙ ЛЕСЛИ:
{knowledge_context}

ПРИНЦИПЫ РАБОТЫ:
- Всегда используй методы и техники из книг Лесли
- Давай конкретные практические советы
- Учитывай психотип и контекст ситуации
- Будь прямым и честным
- Помни о согласии и этике

Отвечай как опытный наставник - кратко, по делу, с конкретными техниками."""

            # Формируем сообщения для GPT
            messages = [{"role": "system", "content": system_prompt}]
            
            # Добавляем историю разговора
            messages.extend(conversation_history)
            
            # Добавляем текущее сообщение
            messages.append({"role": "user", "content": user_message})
            
            # Получаем ответ
            response = self.get_gpt_response_sync(messages)
            
            # Сохраняем в память
            self.memory.save_message_sync(user_id, "user", user_message)
            self.memory.save_message_sync(user_id, "assistant", response)
            
            return response
            
        except Exception as e:
            logger.error(f"Ошибка обработки сообщения: {e}")
            return "Извините, произошла ошибка. Попробуйте еще раз."

# Создаем экземпляр бота-ассистента
assistant = LesliAssistant()

def create_main_menu_keyboard():
    """Создание обновленной клавиатуры меню"""
    keyboard = InlineKeyboardMarkup()
    
    # Базовые функции анализа
    keyboard.row(
        InlineKeyboardButton("🧠 Кейс", callback_data="menu_keis"),
        InlineKeyboardButton("💬 Переписка", callback_data="menu_perepiska")
    )
    keyboard.row(
        InlineKeyboardButton("💡 Ответ", callback_data="menu_otvet"),
        InlineKeyboardButton("📸 Скрин", callback_data="menu_skrin")
    )
    
    # Свидания
    keyboard.row(
        InlineKeyboardButton("🥂 Свидание 1", callback_data="menu_svidanie1"),
        InlineKeyboardButton("💑 Свидание 2", callback_data="menu_svidanie2")
    )
    keyboard.row(
        InlineKeyboardButton("📊 Анализ 1", callback_data="menu_analiz1"),
        InlineKeyboardButton("📈 Анализ 2", callback_data="menu_analiz2")
    )
    
    # Новые функции
    keyboard.row(
        InlineKeyboardButton("🆘 SOS Сигналы", callback_data="menu_sos"),
        InlineKeyboardButton("🎭 Стили соблазнения", callback_data="menu_styles")
    )
    keyboard.row(
        InlineKeyboardButton("📖 Истории", callback_data="menu_stories"),
        InlineKeyboardButton("💡 Сигналы интереса", callback_data="menu_signals")
    )
    keyboard.row(
        InlineKeyboardButton("👩 Типажи девушек", callback_data="menu_types"),
        InlineKeyboardButton("💬 Темы для свиданий", callback_data="menu_topics")
    )
    
    # Знания
    keyboard.row(
        InlineKeyboardButton("🧬 Психотип", callback_data="menu_psihotip"),
        InlineKeyboardButton("📚 Знание", callback_data="menu_znanie")
    )
    keyboard.row(
        InlineKeyboardButton("🔬 Наука", callback_data="menu_nauka"),
        InlineKeyboardButton("👨‍🏫 Наставник", callback_data="menu_nastavnik")
    )
    
    return keyboard

def show_main_menu(message):
    """Показать основное меню"""
    menu_text = """
🔥 **LESLI45BOT 2.0 - Главное меню**

Выбери нужную функцию:

🧠 **Анализ** - разбор ситуаций и кейсов
💬 **Общение** - помощь с перепиской и ответами
🥂 **Свидания** - стратегии для встреч
🆘 **SOS** - экстренные техники влияния
🎭 **Стили** - методы соблазнения
👩 **Типажи** - работа с разными девушками
🧬 **Психология** - научный анализ

Используй кнопки ниже для быстрого доступа к функциям! 👇
"""
    
    try:
        bot.send_message(
            message.chat.id,
            menu_text,
            reply_markup=create_main_menu_keyboard(),
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Ошибка показа меню: {e}")

@bot.message_handler(commands=['start'])
def start_command(message):
    """Команда /start"""
    show_main_menu(message)

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    """Обработка нажатий кнопок"""
    try:
        menu_type = call.data.replace("menu_", "")
        user_id = call.from_user.id
        
        if menu_type == "keis":
            bot.edit_message_text(
                "🧠 **Анализ кейса**\n\n"
                "Опиши ситуацию с девушкой:\n"
                "• Где познакомились?\n"
                "• Как общались?\n"
                "• Что пошло не так?\n\n"
                "Дам конкретные советы по исправлению!",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                parse_mode='Markdown'
            )
        elif menu_type == "perepiska":
            bot.edit_message_text(
                "💬 **Анализ переписки**\n\n"
                "Пришли скрин переписки или опиши диалог.\n\n"
                "Проанализирую:\n"
                "• Её интерес и настроение\n"
                "• Твои ошибки\n"
        elif menu_type == "perepiska":
            bot.edit_message_text(
                "💬 **Анализ переписки**\n\n"
                "Пришли скрин переписки или опиши диалог.\n\n"
                "Проанализирую:\n"
                "• Её интерес и настроение\n"
                "• Твои ошибки\n"
                "• Как продолжить общение\n\n"
                "Можешь прислать фото переписки!",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                parse_mode='Markdown'
            )
        elif menu_type == "otvet":
            bot.edit_message_text(
                "💡 **Помощь с ответом**\n\n"
                "Опиши ситуацию:\n"
                "• Что она написала?\n"
                "• Контекст общения\n"
                "• Твоя цель\n\n"
                "Дам варианты ответов с объяснением!",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                parse_mode='Markdown'
            )
        elif menu_type == "styles":
            keyboard = InlineKeyboardMarkup()
            keyboard.add(InlineKeyboardButton("😈 Подонок", callback_data="style_podonok"))
            keyboard.add(InlineKeyboardButton("🌹 Романтик", callback_data="style_romantic"))
            keyboard.add(InlineKeyboardButton("🔥 Провокатор", callback_data="style_provokator"))
            keyboard.add(InlineKeyboardButton("📋 Структурный", callback_data="style_structural"))
            keyboard.add(InlineKeyboardButton("👑 Мастер", callback_data="style_master"))
            keyboard.add(InlineKeyboardButton("⬅️ Назад", callback_data="menu_main"))
            
            bot.edit_message_text(
                "🎭 **Стили соблазнения**\n\n"
                "Выбери стиль для изучения:\n\n"
                "😈 **Подонок** - доминирование и вызов\n"
                "🌹 **Романтик** - эмоции и чувства\n"
                "🔥 **Провокатор** - интрига и загадочность\n"
                "📋 **Структурный** - логика и планирование\n"
                "👑 **Мастер** - комбинация всех стилей",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=keyboard,
                parse_mode='Markdown'
            )
        elif menu_type == "types":
            keyboard = InlineKeyboardMarkup()
            keyboard.add(InlineKeyboardButton("👸 Контролирующая", callback_data="type_control"))
            keyboard.add(InlineKeyboardButton("🔥 Чувственная", callback_data="type_sensual"))
            keyboard.add(InlineKeyboardButton("🎭 Эмоциональная", callback_data="type_emotional"))
            keyboard.add(InlineKeyboardButton("🌙 Замкнутая", callback_data="type_closed"))
            keyboard.add(InlineKeyboardButton("🌸 Молодые", callback_data="type_young"))
            keyboard.add(InlineKeyboardButton("⬅️ Назад", callback_data="menu_main"))
            
            bot.edit_message_text(
                "👩 **Типажи девушек**\n\n"
                "Выбери тип для изучения:\n\n"
                "👸 **Контролирующая** - доминантная, властная\n"
                "🔥 **Чувственная** - эмоциональная, страстная\n"
                "🎭 **Эмоциональная** - импульсивная, яркая\n"
                "🌙 **Замкнутая** - скрытная, недоступная\n"
                "🌸 **Молодые** - неопытные, открытые",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=keyboard,
                parse_mode='Markdown'
            )
        elif menu_type == "znanie":
            bot.edit_message_text(
                "📚 **База знаний**\n\n"
                "О чем хочешь узнать из теории?\n\n"
                "Например: 'как создать доверие перед сексом'",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                parse_mode='Markdown'
            )
        elif menu_type == "main":
            menu_text = """
🔥 **LESLI45BOT 2.0 - Главное меню**

Выбери нужную функцию:

🧠 **Анализ** - разбор ситуаций и кейсов
💬 **Общение** - помощь с перепиской и ответами
🥂 **Свидания** - стратегии для встреч
🆘 **SOS** - экстренные техники влияния
🎭 **Стили** - методы соблазнения
👩 **Типажи** - работа с разными девушками
🧬 **Психология** - научный анализ

Используй кнопки ниже для быстрого доступа к функциям! 👇
"""
            bot.edit_message_text(
                menu_text,
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=create_main_menu_keyboard(),
                parse_mode='Markdown'
            )
        
        # Обработка стилей
        elif call.data.startswith("style_"):
            style = call.data.replace("style_", "")
            response = assistant.process_message(f"Расскажи подробно о стиле соблазнения {style}", user_id)
            bot.edit_message_text(
                response,
                chat_id=call.message.chat.id,
                message_id=call.message.message_id
            )
        
        # Обработка типажей
        elif call.data.startswith("type_"):
            type_name = call.data.replace("type_", "")
            response = assistant.process_message(f"Расскажи как работать с типажом девушки {type_name}", user_id)
            bot.edit_message_text(
                response,
                chat_id=call.message.chat.id,
                message_id=call.message.message_id
            )
        
        # Все остальные кнопки меню
        else:
            menu_responses = {
                "skrin": "📸 **Анализ скрина**\n\nПришли скрин переписки, профиля или истории для анализа!",
                "svidanie1": "🥂 **Первое свидание**\n\nРасскажи о девушке и что планируешь - дам стратегию!",
                "svidanie2": "💑 **Второе свидание**\n\nКак прошло первое? Составлю план для второго!",
                "analiz1": "📊 **Анализ первого свидания**\n\nОпиши как прошло - дам рекомендации!",
                "analiz2": "📈 **Анализ второго свидания**\n\nРасскажи детали - оценю прогресс!",
                "sos": "🆘 **SOS Сигналы**\n\nОпиши критическую ситуацию - дам экстренные техники!",
                "stories": "📖 **Создание историй**\n\nОпиши психотип девушки - создам убедительную историю!",
                "signals": "💡 **Сигналы интереса**\n\nОпиши ситуацию - научу распознавать её интерес!",
                "topics": "💬 **Темы для свиданий**\n\nОпиши девушку - дам темы для разговора!",
                "psihotip": "🧬 **Психотип**\n\nОпиши поведение девушки - определю её психотип!",
                "nauka": "🔬 **Научная база**\n\nО какой теории хочешь узнать? (привязанность, влияние, притяжение)",
                "nastavnik": "👨‍🏫 **Наставник**\n\nРасскажи о ситуации - дам персональный план!"
            }
            
            if menu_type in menu_responses:
                bot.edit_message_text(
                    menu_responses[menu_type],
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    parse_mode='Markdown'
                )
        
        bot.answer_callback_query(call.id)
        
    except Exception as e:
        logger.error(f"Ошибка обработки callback: {e}")
        bot.answer_callback_query(call.id, "Произошла ошибка")

@bot.message_handler(content_types=['text'])
def handle_message(message):
    """Обработка текстовых сообщений"""
    try:
        user_message = message.text
        user_id = message.from_user.id
        
        # Обрабатываем сообщение через ассистента
        response = assistant.process_message(user_message, user_id)
        
        # Отправляем ответ
        bot.reply_to(message, response)
        
    except Exception as e:
        logger.error(f"Ошибка обработки сообщения: {e}")
        bot.reply_to(message, "Произошла ошибка. Попробуйте еще раз или используйте /start для перезапуска.")

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    """Обработка фотографий"""
    try:
        user_id = message.from_user.id
        
        # Получаем фото
        photo = message.photo[-1]  # Берем самое большое разрешение
        file_info = bot.get_file(photo.file_id)
        
        # Скачиваем изображение
        file_url = f"https://api.telegram.org/file/bot{config.TELEGRAM_TOKEN}/{file_info.file_path}"
        response = requests.get(file_url)
        image_data = response.content
        
        # Простой анализ фото (без GPT Vision для упрощения)
        caption = message.caption or ""
        analysis = f"📸 **Анализ фото:**\n\n"
        analysis += f"Получил фото для анализа"
        if caption:
            analysis += f" с подписью: '{caption}'"
        analysis += f"\n\nДля подробного анализа опиши что видишь на фото текстом, и я дам рекомендации по соблазнению!"
        
        # Сохраняем в память
        assistant.memory.save_message_sync(user_id, "user", f"[Фото] {caption}")
        assistant.memory.save_message_sync(user_id, "assistant", analysis)
        
        # Отправляем результат
        bot.reply_to(message, analysis, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Ошибка обработки фото: {e}")
        bot.reply_to(message, "Не могу проанализировать фото. Опиши что на нем изображено текстом!")

def main():
    """Главная функция"""
    try:
        # Проверяем наличие токенов
        if not config.TELEGRAM_TOKEN:
            logger.error("❌ TELEGRAM_TOKEN не найден!")
            return
        
        if not config.OPENAI_API_KEY:
            logger.error("❌ OPENAI_API_KEY не найден!")
            return
        
        logger.info("🚀 Запускаю LESLI45BOT 2.0...")
        logger.info("✅ Обработчики добавлены")
        logger.info("🎉 LESLI45BOT 2.0 запущен и готов к работе!")
        
        # Запускаем бота через polling
        bot.polling(none_stop=True, interval=0, timeout=30)
        
    except Exception as e:
        logger.error(f"❌ Критическая ошибка запуска: {e}")
        logger.error(traceback.format_exc())

if __name__ == '__main__':
    main()
