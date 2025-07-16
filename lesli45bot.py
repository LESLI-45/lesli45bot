#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LESLI45BOT - Персональный Telegram-ассистент по соблазнению
Основан на GPT-4o с базой знаний из книг Алекса Лесли
WEBHOOK VERSION для Render
"""

import asyncio
import logging
from datetime import datetime, timedelta
import json
import os
import sys
import traceback
from typing import Optional, List, Dict, Any

# Telegram Bot API
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

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

# Web server для webhook
from flask import Flask, request, jsonify
import threading

# Configuration
try:
    from config import config
except ImportError:
    class Config:
        def __init__(self):
            self.TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
            self.OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
            self.DATABASE_URL = os.getenv('DATABASE_URL')
            self.MODEL = "gpt-4o"
            self.MAX_TOKENS = 2000
            self.TEMPERATURE = 0.7
            
        def __getattr__(self, name):
            return os.getenv(name)
    
    config = Config()

# Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Flask app для webhook
app = Flask(__name__)

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
            else:
                # PostgreSQL
                asyncio.create_task(self._create_postgres_tables())
        except Exception as e:
            logger.error(f"Ошибка создания таблиц: {e}")
    
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
            logger.info("✅ Таблицы базы знаний созданы успешно")
        except Exception as e:
            logger.error(f"Ошибка создания PostgreSQL таблиц: {e}")
    
    async def search_knowledge(self, query: str, limit: int = 5) -> List[Dict]:
        """Поиск в базе знаний"""
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
                # PostgreSQL
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
            logger.error(f"Ошибка поиска в базе знаний: {e}")
            return []
    
    async def force_load_all_books(self):
        """Принудительная загрузка всех книг"""
        logger.info("🚀 НАЧИНАЮ ПРИНУДИТЕЛЬНУЮ ОБРАБОТКУ КНИГ")
        
        try:
            # Проверяем есть ли уже книги
            if isinstance(self.db, sqlite3.Connection):
                cursor = self.db.cursor()
                cursor.execute("SELECT COUNT(*) FROM knowledge_base")
                count = cursor.fetchone()[0]
            else:
                result = await self.db.fetchrow("SELECT COUNT(*) FROM knowledge_base")
                count = result[0] if result else 0
            
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
                                    await self.save_book_content(file, content)
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
    
    async def save_book_content(self, book_name: str, content: str):
        """Сохранение содержимого книги в базу"""
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
                        await self.db.execute('''
                            INSERT INTO knowledge_base (book_name, content, keywords)
                            VALUES ($1, $2, $3)
                        ''', book_name, chunk, keywords)
            
            logger.info(f"📚 Книга {book_name} разбита на {len(chunks)} частей и сохранена")
                        
        except Exception as e:
            logger.error(f"Ошибка сохранения книги {book_name}: {e}")
    
    def extract_keywords(self, text: str) -> str:
        """Извлечение ключевых слов из текста"""
        try:
            # Простое извлечение ключевых слов
            words = re.findall(r'\b\w+\b', text.lower())
            # Фильтруем слова длиннее 3 символов
            keywords = [word for word in words if len(word) > 3]
            return ' '.join(keywords[:20])  # Первые 20 ключевых слов
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
            else:
                # PostgreSQL
                asyncio.create_task(self._create_postgres_memory_tables())
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
            logger.info("✅ Таблицы памяти созданы успешно")
        except Exception as e:
            logger.error(f"Ошибка создания таблиц памяти: {e}")
    
    async def save_message(self, user_id: int, role: str, message: str):
        """Сохранение сообщения в память"""
        try:
            if isinstance(self.db, sqlite3.Connection):
                cursor = self.db.cursor()
                cursor.execute('''
                    INSERT INTO conversations (user_id, role, message)
                    VALUES (?, ?, ?)
                ''', (user_id, role, message))
                self.db.commit()
            else:
                await self.db.execute('''
                    INSERT INTO conversations (user_id, role, message)
                    VALUES ($1, $2, $3)
                ''', user_id, role, message)
        except Exception as e:
            logger.error(f"Ошибка сохранения сообщения: {e}")
    
    async def get_conversation_history(self, user_id: int, limit: int = 10) -> List[Dict]:
        """Получение истории разговора"""
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
                results = await self.db.fetch('''
                    SELECT role, message FROM conversations 
                    WHERE user_id = $1 
                    ORDER BY timestamp DESC 
                    LIMIT $2
                ''', user_id, limit)
                
                return [{'role': row['role'], 'content': row['message']} for row in reversed(results)]
        except Exception as e:
            logger.error(f"Ошибка получения истории: {e}")
            return []

class ImageAnalyzer:
    """Класс для анализа изображений"""
    
    def __init__(self):
        self.openai_client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
    
    async def analyze_image(self, image_data: bytes, context: str = "") -> str:
        """Анализ изображения с помощью GPT-4 Vision"""
        try:
            # Конвертируем изображение в base64
            image = Image.open(BytesIO(image_data))
            
            # Ужимаем изображение если слишком большое
            if image.size[0] > 1024 or image.size[1] > 1024:
                image.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
            
            # Конвертируем в base64
            buffered = BytesIO()
            image.save(buffered, format="JPEG")
            image_base64 = base64.b64encode(buffered.getvalue()).decode()
            
            # Системный промпт для анализа фото
            system_prompt = f"""Ты эксперт по анализу фотографий в контексте соблазнения и психологии.
            
            Анализируй фото девушки с точки зрения:
            1. Психотип личности
            2. Эмоциональное состояние 
            3. Стиль и самопрезентация
            4. Подходящие стратегии общения
            
            Контекст: {context}
            
            Давай конкретные практические советы по соблазнению."""
            
            response = await self.openai_client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{image_base64}"
                                }
                            },
                            {
                                "type": "text",
                                "text": "Проанализируй это фото и дай советы по соблазнению"
                            }
                        ]
                    }
                ],
                max_tokens=1000
            )
            
            return response.choices[0].message.content
            
        except Exception as e:
            logger.error(f"Ошибка анализа изображения: {e}")
            return "Извините, не могу проанализировать изображение. Попробуйте еще раз."

class PsychoAnalyzer:
    """Класс для психологического анализа"""
    
    def __init__(self):
        self.openai_client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
    
    async def analyze_psychology(self, text: str, context: str = "") -> str:
        """Психологический анализ текста/ситуации"""
        try:
            system_prompt = """Ты эксперт психолог с глубокими знаниями в области:
            - Теории привязанности
            - Психотипологии
            - Эмоциональной психологии
            - Социальной динамики
            - Поведенческих паттернов
            
            Анализируй ситуации с научной точки зрения и давай практические рекомендации."""
            
            response = await self.openai_client.chat.completions.create(
                model=config.MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Контекст: {context}\n\nАнализируй: {text}"}
                ],
                max_tokens=config.MAX_TOKENS,
                temperature=config.TEMPERATURE
            )
            
            return response.choices[0].message.content
            
        except Exception as e:
            logger.error(f"Ошибка психологического анализа: {e}")
            return "Извините, произошла ошибка при анализе. Попробуйте еще раз."

class LesliAssistant:
    """Главный класс бота-ассистента"""
    
    def __init__(self):
        self.openai_client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
        self.db = None
        self.knowledge = None
        self.memory = None
        self.image_analyzer = ImageAnalyzer()
        self.psycho_analyzer = PsychoAnalyzer()
    
    async def initialize_database(self):
        """Инициализация базы данных"""
        try:
            if config.DATABASE_URL and config.DATABASE_URL.startswith('postgresql'):
                logger.info("🔗 Подключаюсь к PostgreSQL...")
                self.db = await asyncpg.connect(config.DATABASE_URL)
                logger.info("✅ Подключение к PostgreSQL успешно")
            else:
                logger.info("🔗 Использую SQLite базу данных")
                self.db = sqlite3.connect('lesli_bot.db')
                
            self.knowledge = KnowledgeBase(self.db)
            self.memory = ConversationMemory(self.db)
            
            # Загружаем книги при инициализации
            await self.initialize_knowledge_base()
            
        except Exception as e:
            logger.error(f"❌ Ошибка подключения к базе данных: {e}")
            # Fallback к SQLite
            self.db = sqlite3.connect('lesli_bot.db')
            self.knowledge = KnowledgeBase(self.db)
            self.memory = ConversationMemory(self.db)
    
    async def initialize_knowledge_base(self):
        """Инициализация базы знаний"""
        logger.info("📚 Инициализация базы знаний...")
        await self.knowledge.force_load_all_books()
    
    async def get_gpt_response(self, messages: List[Dict]) -> str:
        """Получение ответа от GPT"""
        try:
            response = await self.openai_client.chat.completions.create(
                model=config.MODEL,
                messages=messages,
                max_tokens=config.MAX_TOKENS,
                temperature=config.TEMPERATURE
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"Ошибка GPT: {e}")
            return "Извините, произошла ошибка при получении ответа. Попробуйте еще раз."
    
    async def process_message(self, user_message: str, user_id: int) -> str:
        """Обработка сообщения пользователя"""
        try:
            # Поиск в базе знаний
            knowledge_results = await self.knowledge.search_knowledge(user_message, limit=3)
            
            # Получаем историю разговора
            conversation_history = await self.memory.get_conversation_history(user_id, limit=5)
            
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
            response = await self.get_gpt_response(messages)
            
            # Сохраняем в память
            await self.memory.save_message(user_id, "user", user_message)
            await self.memory.save_message(user_id, "assistant", response)
            
            return response
            
        except Exception as e:
            logger.error(f"Ошибка обработки сообщения: {e}")
            return "Извините, произошла ошибка. Попробуйте еще раз."

# Создаем экземпляр бота
assistant = LesliAssistant()

def create_main_menu_keyboard():
    """Создание обновленной клавиатуры меню"""
    keyboard = [
        # Базовые функции анализа
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

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start"""
    await show_main_menu(update, context)

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        if update.callback_query:
            await update.callback_query.edit_message_text(
                text=menu_text,
                reply_markup=create_main_menu_keyboard(),
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                text=menu_text,
                reply_markup=create_main_menu_keyboard(),
                parse_mode='Markdown'
            )
    except Exception as e:
        logger.error(f"Ошибка показа меню: {e}")

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка нажатий кнопок"""
    query = update.callback_query
    await query.answer()
    
    menu_type = query.data.replace("menu_", "")
    user_id = query.from_user.id
    
    if menu_type == "keis":
        await query.edit_message_text(
            "🧠 **Анализ кейса**\n\n"
            "Опиши ситуацию с девушкой:\n"
            "• Где познакомились?\n"
            "• Как общались?\n"
            "• Что пошло не так?\n\n"
            "Дам конкретные советы по исправлению!"
        )
    elif menu_type == "perepiska":
        await query.edit_message_text(
            "💬 **Анализ переписки**\n\n"
            "Пришли скрин переписки или опиши диалог.\n\n"
            "Проанализирую:\n"
            "• Её интерес и настроение\n"
            "• Твои ошибки\n"
            "• Как продолжить общение\n\n"
            "Можешь прислать фото переписки!"
        )
    elif menu_type == "otvet":
        await query.edit_message_text(
            "💡 **Помощь с ответом**\n\n"
            "Опиши ситуацию:\n"
            "• Что она написала?\n"
            "• Контекст общения\n"
            "• Твоя цель\n\n"
            "Дам варианты ответов с объяснением!"
        )
    elif menu_type == "skrin":
        await query.edit_message_text(
            "📸 **Анализ скрина**\n\n"
            "Пришли скрин:\n"
            "• Переписки\n"
            "• Профиля девушки\n"
            "• Истории/поста\n\n"
            "Проанализирую и дам рекомендации!"
        )
    elif menu_type == "svidanie1":
        await query.edit_message_text(
            "🥂 **Первое свидание**\n\n"
            "Расскажи о девушке:\n"
            "• Где познакомились?\n"
            "• Её психотип\n"
            "• Что планируешь?\n\n"
            "Дам стратегию для идеального первого свидания!"
        )
    elif menu_type == "svidanie2":
        await query.edit_message_text(
            "💑 **Второе свидание**\n\n"
            "Как прошло первое свидание?\n"
            "• Что делали?\n"
            "• Её реакция\n"
            "• Уровень близости\n\n"
            "Составлю план для второго свидания!"
        )
    elif menu_type == "analiz1":
        await query.edit_message_text(
            "📊 **Анализ первого свидания**\n\n"
            "Опиши как прошло:\n"
            "• Место и активность\n"
            "• Её поведение\n"
            "• Твои действия\n"
            "• Итог встречи\n\n"
            "Проанализирую и дам рекомендации!"
        )
    elif menu_type == "analiz2":
        await query.edit_message_text(
            "📈 **Анализ второго свидания**\n\n"
            "Расскажи детали:\n"
            "• Что изменилось?\n"
            "• Уровень интимности\n"
            "• Её сигналы\n"
            "• Планы на будущее\n\n"
            "Дам оценку прогресса!"
        )
    elif menu_type == "sos":
        await query.edit_message_text(
            "🆘 **SOS Сигналы**\n\n"
            "Экстренные техники влияния:\n"
            "• Через образы и истории\n"
            "• Невербальные сигналы\n"
            "• Эмоциональные якоря\n\n"
            "Опиши критическую ситуацию!"
        )
    elif menu_type == "styles":
        keyboard = [
            [InlineKeyboardButton("😈 Подонок", callback_data="style_podonok")],
            [InlineKeyboardButton("🌹 Романтик", callback_data="style_romantic")],
            [InlineKeyboardButton("🔥 Провокатор", callback_data="style_provokator")],
            [InlineKeyboardButton("📋 Структурный", callback_data="style_structural")],
            [InlineKeyboardButton("👑 Мастер", callback_data="style_master")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="menu_main")]
        ]
        await query.edit_message_text(
            "🎭 **Стили соблазнения**\n\n"
            "Выбери стиль для изучения:\n\n"
            "😈 **Подонок** - доминирование и вызов\n"
            "🌹 **Романтик** - эмоции и чувства\n"
            "🔥 **Провокатор** - интрига и загадочность\n"
            "📋 **Структурный** - логика и планирование\n"
            "👑 **Мастер** - комбинация всех стилей",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    elif menu_type == "stories":
        await query.edit_message_text(
            "📖 **Создание историй**\n\n"
            "Опиши:\n"
            "• Психотип девушки\n"
            "• Ситуация для истории\n"
            "• Цель (впечатлить/заинтриговать/соблазнить)\n\n"
            "Создам убедительную историю под её тип!"
        )
    elif menu_type == "signals":
        keyboard = [
            [InlineKeyboardButton("💬 В переписке", callback_data="signals_chat")],
            [InlineKeyboardButton("🥂 На свидании", callback_data="signals_date")],
            [InlineKeyboardButton("📱 В соцсетях", callback_data="signals_social")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="menu_main")]
        ]
        await query.edit_message_text(
            "💡 **Сигналы интереса**\n\n"
            "Где распознаем сигналы?\n\n"
            "💬 **В переписке** - текст, эмодзи, время ответа\n"
            "🥂 **На свидании** - жесты, взгляды, поведение\n"
            "📱 **В соцсетях** - лайки, просмотры, активность",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    elif menu_type == "types":
        keyboard = [
            [InlineKeyboardButton("👸 Контролирующая", callback_data="type_control")],
            [InlineKeyboardButton("🔥 Чувственная", callback_data="type_sensual")],
            [InlineKeyboardButton("🎭 Эмоциональная", callback_data="type_emotional")],
            [InlineKeyboardButton("🌙 Замкнутая", callback_data="type_closed")],
            [InlineKeyboardButton("🌸 Молодые", callback_data="type_young")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="menu_main")]
        ]
        await query.edit_message_text(
            "👩 **Типажи девушек**\n\n"
            "Выбери тип для изучения:\n\n"
            "👸 **Контролирующая** - доминантная, властная\n"
            "🔥 **Чувственная** - эмоциональная, страстная\n"
            "🎭 **Эмоциональная** - импульсивная, яркая\n"
            "🌙 **Замкнутая** - скрытная, недоступная\n"
            "🌸 **Молодые** - неопытные, открытые",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    elif menu_type == "topics":
        await query.edit_message_text(
            "💬 **Темы для первого свидания**\n\n"
            "Опиши девушку:\n"
            "• Возраст и интересы\n"
            "• Психотип\n"
            "• Место встречи\n\n"
            "Дам список тем и вопросов для поддержания интереса!"
        )
    elif menu_type == "psihotip":
        await query.edit_message_text(
            "🧬 **Определение психотипа**\n\n"
            "Опиши девушку:\n"
            "• Поведение в общении\n"
            "• Реакции на ситуации\n"
            "• Стиль жизни\n"
            "• Что её мотивирует\n\n"
            "Определю психотип и дам рекомендации!"
        )
    elif menu_type == "znanie":
        await query.edit_message_text(
            "📚 **База знаний**\n\n"
            "О чем хочешь узнать из теории?\n\n"
            "Например: 'как создать доверие перед сексом'"
        )
    elif menu_type == "nauka":
        await query.edit_message_text(
            "🔬 **Научная база**\n\n"
            "О какой научной теории хочешь узнать?\n\n"
            "Примеры:\n"
            "• теория привязанности\n"
            "• психология влияния\n"
            "• нейробиология притяжения"
        )
    elif menu_type == "nastavnik":
        await query.edit_message_text(
            "👨‍🏫 **Режим наставника**\n\n"
            "Расскажи о своей текущей ситуации:\n"
            "• Цели в отношениях\n"
            "• Проблемы с девушками\n"
            "• Что хочешь улучшить\n\n"
            "Дам персональный план развития!"
        )
    elif menu_type == "main":
        await show_main_menu(update, context)
    
    # Обработка стилей соблазнения
    elif query.data.startswith("style_"):
        style = query.data.replace("style_", "")
        response = await assistant.process_message(f"Расскажи подробно о стиле соблазнения {style}", user_id)
        await query.edit_message_text(response)
    
    # Обработка типажей
    elif query.data.startswith("type_"):
        type_name = query.data.replace("type_", "")
        response = await assistant.process_message(f"Расскажи как работать с типажом девушки {type_name}", user_id)
        await query.edit_message_text(response)
    
    # Обработка сигналов
    elif query.data.startswith("signals_"):
        signal_type = query.data.replace("signals_", "")
        response = await assistant.process_message(f"Расскажи о сигналах интереса {signal_type}", user_id)
        await query.edit_message_text(response)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка текстовых сообщений"""
    try:
        user_message = update.message.text
        user_id = update.effective_user.id
        
        # Обрабатываем сообщение через ассистента
        response = await assistant.process_message(user_message, user_id)
        
        # Отправляем ответ
        await update.message.reply_text(response)
        
    except Exception as e:
        logger.error(f"Ошибка обработки сообщения: {e}")
        await update.message.reply_text("Произошла ошибка. Попробуйте еще раз или используйте /start для перезапуска.")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка фотографий"""
    try:
        user_id = update.effective_user.id
        
        # Получаем фото
        photo = update.message.photo[-1]  # Берем самое большое разрешение
        file = await context.bot.get_file(photo.file_id)
        
        # Скачиваем изображение
        image_data = await file.download_as_bytearray()
        
        # Анализируем изображение
        caption = update.message.caption or ""
        analysis = await assistant.image_analyzer.analyze_image(bytes(image_data), caption)
        
        # Сохраняем в память
        await assistant.memory.save_message(user_id, "user", f"[Фото] {caption}")
        await assistant.memory.save_message(user_id, "assistant", analysis)
        
        # Отправляем результат
        await update.message.reply_text(f"📸 **Анализ фото:**\n\n{analysis}")
        
    except Exception as e:
        logger.error(f"Ошибка обработки фото: {e}")
        await update.message.reply_text("Не могу проанализировать фото. Попробуйте еще раз.")

# Webhook обработчик
@app.route(f'/webhook/{config.TELEGRAM_TOKEN}', methods=['POST'])
def webhook():
    """Обработка webhook от Telegram"""
    try:
        update = Update.de_json(request.get_json(), telegram_app.bot)
        telegram_app.process_update(update)
        return jsonify({'status': 'ok'})
    except Exception as e:
        logger.error(f"Ошибка webhook: {e}")
        return jsonify({'status': 'error'}), 500

@app.route('/health', methods=['GET'])
def health_check():
    """Health check для Render"""
    return jsonify({'status': 'healthy'})

# Глобальная переменная для Telegram приложения
telegram_app = None

async def setup_telegram_app():
    """Настройка Telegram приложения"""
    global telegram_app
    
    # Создаем приложение
    telegram_app = Application.builder().token(config.TELEGRAM_TOKEN).build()
    
    # Добавляем обработчики
    telegram_app.add_handler(CommandHandler("start", start_command))
    telegram_app.add_handler(CallbackQueryHandler(handle_callback))
    telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    telegram_app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    
    # Инициализируем приложение
    await telegram_app.initialize()
    
    # Устанавливаем webhook
    webhook_url = f"https://lesli45bot.onrender.com/webhook/{config.TELEGRAM_TOKEN}"
    await telegram_app.bot.set_webhook(webhook_url)
    
    logger.info(f"🌐 Webhook установлен: {webhook_url}")

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
        
        # Инициализируем базу данных
        asyncio.run(assistant.initialize_database())
        
        # Настраиваем Telegram приложение
        asyncio.run(setup_telegram_app())
        
        logger.info("✅ Обработчики добавлены")
        logger.info("🎉 LESLI45BOT 2.0 запущен и готов к работе!")
        
        # Запускаем Flask сервер
        port = int(os.environ.get('PORT', 5000))
        app.run(host='0.0.0.0', port=port, debug=False)
        
    except Exception as e:
        logger.error(f"❌ Критическая ошибка запуска: {e}")
        logger.error(traceback.format_exc())

if __name__ == '__main__':
    main()
