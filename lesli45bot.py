#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LESLI45BOT - Персональный Telegram-ассистент по соблазнению
Основан на GPT-4o с базой знаний из книг Алекса Лесли
"""

import asyncio
import logging
from datetime import datetime, timedelta
import json
import os
import sqlite3
from typing import Dict, List, Optional
import PyPDF2
import docx
import ebooklib
from ebooklib import epub
import re
from PIL import Image
import io
import base64

from openai import AsyncOpenAI
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, PhotoSize
from telegram.ext import (
    Application, CommandHandler, MessageHandler, 
    CallbackQueryHandler, filters, ContextTypes
)

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Конфигурация
from config import config

class KnowledgeBase:
    """Класс для работы с базой знаний из книг"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.init_knowledge_db()
    
    def init_knowledge_db(self):
        """Инициализация базы знаний"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS knowledge_base (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_name TEXT,
                chapter TEXT,
                content TEXT,
                keywords TEXT,
                category TEXT
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def extract_text_from_pdf(self, file_path: str) -> str:
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
    
    def extract_text_from_docx(self, file_path: str) -> str:
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
    
    def extract_text_from_epub(self, file_path: str) -> str:
        """Извлечение текста из EPUB"""
        try:
            book = epub.read_epub(file_path)
            text = ""
            for item in book.get_items():
                if item.get_type() == ebooklib.ITEM_DOCUMENT:
                    content = item.get_content().decode('utf-8')
                    clean_text = re.sub('<[^<]+?>', '', content)
                    text += clean_text + "\n"
            return text
        except Exception as e:
            logger.error(f"Ошибка чтения EPUB {file_path}: {e}")
            return ""
    
    def load_books_from_directory(self, books_dir: str = "books"):
        """Загрузка всех книг из директории"""
        if not os.path.exists(books_dir):
            os.makedirs(books_dir)
            logger.info(f"Создана директория {books_dir}. Поместите туда ваши книги.")
            return
        
        book_files = [f for f in os.listdir(books_dir) 
                     if f.lower().endswith(('.pdf', '.docx', '.epub', '.txt'))]
        
        if not book_files:
            logger.info(f"В директории {books_dir} нет файлов книг")
            return
        
        for book_file in book_files:
            file_path = os.path.join(books_dir, book_file)
            self.process_book(file_path, book_file)
    
    def process_book(self, file_path: str, book_name: str):
        """Обработка одной книги"""
        logger.info(f"Обрабатываю книгу: {book_name}")
        
        if file_path.lower().endswith('.pdf'):
            text = self.extract_text_from_pdf(file_path)
        elif file_path.lower().endswith('.docx'):
            text = self.extract_text_from_docx(file_path)
        elif file_path.lower().endswith('.epub'):
            text = self.extract_text_from_epub(file_path)
        elif file_path.lower().endswith('.txt'):
            with open(file_path, 'r', encoding='utf-8') as f:
                text = f.read()
        else:
            logger.warning(f"Неподдерживаемый формат файла: {book_name}")
            return
        
        if not text.strip():
            logger.warning(f"Не удалось извлечь текст из {book_name}")
            return
        
        chunks = self.split_text_into_chunks(text, chunk_size=1000)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT COUNT(*) FROM knowledge_base WHERE book_name = ?', (book_name,))
        if cursor.fetchone()[0] > 0:
            logger.info(f"Книга {book_name} уже в базе знаний")
            conn.close()
            return
        
        for i, chunk in enumerate(chunks):
            keywords = self.extract_keywords(chunk)
            category = self.categorize_content(chunk, book_name)
            
            cursor.execute('''
                INSERT INTO knowledge_base (book_name, chapter, content, keywords, category)
                VALUES (?, ?, ?, ?, ?)
            ''', (book_name, f"Часть {i+1}", chunk, keywords, category))
        
        conn.commit()
        conn.close()
        logger.info(f"Книга {book_name} успешно загружена в базу знаний")
    
    def split_text_into_chunks(self, text: str, chunk_size: int = 1000) -> List[str]:
        """Разбивка текста на части"""
        words = text.split()
        chunks = []
        current_chunk = []
        current_length = 0
        
        for word in words:
            if current_length + len(word) > chunk_size and current_chunk:
                chunks.append(' '.join(current_chunk))
                current_chunk = [word]
                current_length = len(word)
            else:
                current_chunk.append(word)
                current_length += len(word) + 1
        
        if current_chunk:
            chunks.append(' '.join(current_chunk))
        
        return chunks
    
    def extract_keywords(self, text: str) -> str:
        """Извлечение ключевых слов"""
        keywords = []
        
        seduction_terms = [
            'соблазнение', 'флирт', 'свидание', 'привлечение', 'харизма',
            'доминирование', 'фрейм', 'тест', 'комфорт', 'притяжение',
            'психология', 'мотивация', 'страх', 'доверие', 'близость',
            'секс', 'отношения', 'общение', 'невербалика', 'эмоции'
        ]
        
        text_lower = text.lower()
        for term in seduction_terms:
            if term in text_lower:
                keywords.append(term)
        
        return ', '.join(keywords[:10])
    
    def categorize_content(self, text: str, book_name: str) -> str:
        """Категоризация контента"""
        text_lower = text.lower()
        
        if any(word in text_lower for word in ['свидание', 'встреча', 'ресторан']):
            return 'свидания'
        elif any(word in text_lower for word in ['переписка', 'сообщение', 'текст', 'чат']):
            return 'переписка'
        elif any(word in text_lower for word in ['первый', 'знакомство', 'подход']):
            return 'знакомство'
        elif any(word in text_lower for word in ['секс', 'близость', 'интимность']):
            return 'близость'
        elif any(word in text_lower for word in ['психология', 'мотивация', 'страх']):
            return 'психология'
        else:
            return 'общее'
    
    def search_knowledge(self, query: str, limit: int = 5) -> List[Dict]:
        """Поиск по базе знаний"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        search_terms = query.lower().split()
        
        results = []
        for term in search_terms:
            cursor.execute('''
                SELECT book_name, chapter, content, category 
                FROM knowledge_base 
                WHERE LOWER(content) LIKE ? OR LOWER(keywords) LIKE ?
                LIMIT ?
            ''', (f'%{term}%', f'%{term}%', limit))
            
            results.extend(cursor.fetchall())
        
        conn.close()
        
        unique_results = []
        seen = set()
        for result in results:
            if result[2] not in seen:
                unique_results.append({
                    'book_name': result[0],
                    'chapter': result[1],
                    'content': result[2],
                    'category': result[3]
                })
                seen.add(result[2])
        
        return unique_results[:limit]

class ConversationMemory:
    """Класс для работы с памятью разговоров"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """Инициализация базы данных"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                role TEXT,
                content TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_profiles (
                user_id INTEGER PRIMARY KEY,
                name TEXT,
                preferences TEXT,
                context TEXT,
                mentor_mode INTEGER DEFAULT 1,
                user_type TEXT,
                statistics TEXT
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                date DATE,
                interactions INTEGER DEFAULT 0,
                approaches INTEGER DEFAULT 0,
                dates INTEGER DEFAULT 0,
                successes INTEGER DEFAULT 0,
                notes TEXT
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS girl_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                girl_name TEXT,
                psychotype TEXT,
                attachment_style TEXT,
                notes TEXT,
                created_date DATE,
                status TEXT
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def save_message(self, user_id: int, role: str, content: str):
        """Сохранение сообщения в память"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO conversations (user_id, role, content)
            VALUES (?, ?, ?)
        ''', (user_id, role, content))
        
        conn.commit()
        conn.close()
    
    def get_conversation_history(self, user_id: int, limit: int = 10) -> List[Dict]:
        """Получение истории разговора"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT role, content FROM conversations 
            WHERE user_id = ? 
            ORDER BY timestamp DESC 
            LIMIT ?
        ''', (user_id, limit))
        
        messages = cursor.fetchall()
        conn.close()
        
        return [{"role": role, "content": content} for role, content in reversed(messages)]
    
    def get_mentor_mode(self, user_id: int) -> bool:
        """Проверка включен ли режим наставника"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT mentor_mode FROM user_profiles WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        conn.close()
        
        return result[0] if result else True
    
    def set_mentor_mode(self, user_id: int, enabled: bool):
        """Установка режима наставника"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT OR REPLACE INTO user_profiles (user_id, mentor_mode)
            VALUES (?, ?)
        ''', (user_id, 1 if enabled else 0))
        
        conn.commit()
        conn.close()
    
    def update_user_stats(self, user_id: int, stat_type: str, value: int = 1):
        """Обновление статистики пользователя"""
        today = datetime.now().date()
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT id FROM user_stats WHERE user_id = ? AND date = ?', (user_id, today))
        if cursor.fetchone():
            cursor.execute(f'''
                UPDATE user_stats 
                SET {stat_type} = {stat_type} + ? 
                WHERE user_id = ? AND date = ?
            ''', (value, user_id, today))
        else:
            cursor.execute(f'''
                INSERT INTO user_stats (user_id, date, {stat_type})
                VALUES (?, ?, ?)
            ''', (user_id, today, value))
        
        conn.commit()
        conn.close()
    
    def get_user_stats(self, user_id: int, days: int = 30) -> Dict:
        """Получение статистики пользователя"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        start_date = datetime.now().date() - timedelta(days=days)
        
        cursor.execute('''
            SELECT 
                SUM(interactions) as total_interactions,
                SUM(approaches) as total_approaches,
                SUM(dates) as total_dates,
                SUM(successes) as total_successes
            FROM user_stats 
            WHERE user_id = ? AND date >= ?
        ''', (user_id, start_date))
        
        result = cursor.fetchone()
        conn.close()
        
        return {
            'interactions': result[0] or 0,
            'approaches': result[1] or 0,
            'dates': result[2] or 0,
            'successes': result[3] or 0
        }

class ImageAnalyzer:
    """Класс для анализа изображений"""
    
    def __init__(self):
        self.openai_client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
    
    async def analyze_photo(self, photo_data: bytes, analysis_type: str = "general") -> str:
        """Анализ фото с помощью GPT-4V"""
        try:
            base64_image = base64.b64encode(photo_data).decode('utf-8')
            
            if analysis_type == "selfie":
                prompt = """
                Проанализируй это селфи девушки с точки зрения психологии и соблазнения:
                
                1. ЭМОЦИОНАЛЬНОЕ СОСТОЯНИЕ:
                - Настроение по выражению лица
                - Уровень уверенности в себе
                - Открытость к общению
                
                2. НЕВЕРБАЛЬНЫЕ СИГНАЛЫ:
                - Поза и положение тела
                - Взгляд (прямой/отведенный)
                - Микроэмоции
                
                3. ПСИХОЛОГИЧЕСКИЙ ПРОФИЛЬ:
                - Возможный тип личности
                - Стиль привязанности
                - Самооценка
                
                4. СТРАТЕГИЯ ОБЩЕНИЯ:
                - Как лучше начать разговор
                - Какой тон использовать
                - На что обратить внимание
                
                Дай конкретные практические советы для знакомства.
                """
            elif analysis_type == "profile":
                prompt = """
                Проанализируй фото профиля для dating app:
                
                1. ПОДАЧА СЕБЯ:
                - Что она хочет транслировать
                - Какой образ создает
                - Целевая аудитория
                
                2. ПСИХОТИП:
                - Экстраверсия/интроверсия
                - Стиль жизни
                - Ценности и интересы
                
                3. СТРАТЕГИЯ ПОДХОДА:
                - Лучший opener
                - Темы для разговора
                - Стиль общения
                
                Дай рекомендации для первого сообщения.
                """
            else:
                prompt = "Проанализируй это изображение и дай психологическую оценку для целей знакомства и общения."
            
            response = await self.openai_client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{base64_image}"
                                }
                            }
                        ]
                    }
                ],
                max_tokens=800
            )
            
            return response.choices[0].message.content
            
        except Exception as e:
            logger.error(f"Ошибка анализа изображения: {e}")
            return "Извините, не удалось проанализировать изображение. Попробуйте позже."

class PsychoAnalyzer:
    """Класс для психологического анализа"""
    
    def __init__(self):
        pass
    
    def analyze_attachment_style(self, behavior_description: str) -> Dict:
        """Анализ стиля привязанности"""
        if any(word in behavior_description.lower() for word in ['тревожится', 'переживает', 'часто пишет']):
            return {
                'style': 'тревожная',
                'description': 'Нуждается в постоянном подтверждении',
                'strategy': 'Давай стабильность и предсказуемость'
            }
        elif any(word in behavior_description.lower() for word in ['дистанция', 'холодная', 'редко']):
            return {
                'style': 'избегающая', 
                'description': 'Боится близости и зависимости',
                'strategy': 'Не дави, давай пространство'
            }
        else:
            return {
                'style': 'надежная',
                'description': 'Здоровое отношение к близости',
                'strategy': 'Будь прямым и честным'
            }

class LesliAssistant:
    """Основной класс ассистента"""
    
    def __init__(self):
        self.memory = ConversationMemory(config.DATABASE_PATH)
        self.knowledge = KnowledgeBase(config.DATABASE_PATH)
        self.image_analyzer = ImageAnalyzer()
        self.psycho_analyzer = PsychoAnalyzer()
        self.openai_client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
        
        self.knowledge.load_books_from_directory()
        self.system_prompt = self._create_system_prompt()
    
    def _create_system_prompt(self) -> str:
        """Создание системного промпта с базой знаний"""
        return """
Ты - персональный ассистент LESLI45BOT, эксперт по соблазнению и психологии общения с женщинами.

ТВОЙ СТИЛЬ И ХАРАКТЕР:
- Свободный, уверенный, опытный наставник
- Говоришь от лица мужчины, который понимает женскую психологию
- Используешь юмор, но без клоунады
- Базируешься на НАУКЕ и практической психологии, а не на фантазиях пикаперов
- Знаешь современные реалии общения (соцсети, тиндер, быстрые знакомства)

НАУЧНАЯ БАЗА ЗНАНИЙ (приоритет):
1. ТЕОРИЯ ПРИВЯЗАННОСТИ (Боулби, Ainsworth):
   - Тревожная привязанность: нужда в постоянном подтверждении
   - Избегающая: страх близости и зависимости
   - Дезорганизованная: противоречивое поведение
   - Влияние на взрослые отношения

2. ЭВОЛЮЦИОННАЯ ПСИХОЛОГИЯ:
   - Парентальные инвестиции (Trivers)
   - Сексуальные стратегии (Buss)
   - Выбор партнера: краткосрочные vs долгосрочные стратегии
   - Индикаторы генетического качества

3. СОЦИАЛЬНАЯ ПСИХОЛОГИЯ:
   - Эффект простого воздействия (Zajonc)
   - Теория самоопределения (Deci & Ryan)
   - Когнитивный диссонанс (Festinger)
   - Социальное влияние и убеждение (Cialdini)

4. НЕЙРОПСИХОЛОГИЯ И ГОРМОНЫ:
   - Роль окситоцина в привязанности
   - Дофамин и система вознаграждения
   - Тестостерон и доминирование
   - Кортизол и стресс в отношениях

ТВОЯ БАЗА ЗНАНИЙ (Алекс Лесли + современность):
- Жизнь без трусов: основы соблазнения, структура, мужская сила
- Мастерство соблазнения: продвинутые техники
- Волшебная таблетка: уникальные фишки и стили общения
- Угнать за 60 секунд: скоростные подходы
- Охота на самца: женская психология
- Как проснуться в гостях: стратегии свиданий
- Игра Мастера и Охотницы: глубинная психология
- Евротрэш: работа с высокоуровневыми целями

НОВЫЕ СПЕЦИАЛИЗАЦИИ:
- SOS СИГНАЛЫ: влияние через образы, истории и жесты (база Лесли)
- СТИЛИ СОБЛАЗНЕНИЯ: Подонок, Романтик, Провокатор, Структурный, Мастер
- ИСТОРИИ: создание персональных историй под психотипы девушек
- ТИПАЖИ ДЕВУШЕК: Контролирующая, Чувственная, Эмоциональная, Замкнутая, Молодые
- ТЕМЫ ДЛЯ СВИДАНИЙ: оптимальные вопросы и темы для первого свидания
- СИГНАЛЫ ЗАИНТЕРЕСОВАННОСТИ: распознавание интереса в переписке и на свиданиях

КАК ТЫ ОТВЕЧАЕШЬ:
- Анализируешь ситуацию с точки зрения НАУКИ и психологии
- Объясняешь ПОЧЕМУ происходит определенное поведение
- Даешь конкретные пошаговые советы на основе исследований
- Предлагаешь готовые фразы с объяснением психологического воздействия
- Учитываешь этические аспекты и согласие

ВАЖНО: Всегда помни о согласии, границах и этике. Помогай становиться лучшим мужчиной, а не манипулятором.
"""

    async def get_gpt_response(self, messages: List[Dict]) -> str:
        """Получение ответа от GPT-4o"""
        try:
            response = await self.openai_client.chat.completions.create(
                model=config.MODEL,
                messages=messages,
                max_tokens=1000,
                temperature=0.7
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"Ошибка OpenAI: {e}")
            return "Извините, произошла ошибка при обращении к ИИ. Попробуйте позже."

    async def process_message(self, user_id: int, user_message: str) -> str:
        """Обработка сообщения пользователя"""
        knowledge_results = self.knowledge.search_knowledge(user_message)
        history = self.memory.get_conversation_history(user_id)
        
        knowledge_context = ""
        if knowledge_results:
            knowledge_context = "\n\nРЕЛЕВАНТНАЯ ИНФОРМАЦИЯ ИЗ БАЗЫ ЗНАНИЙ:\n"
            for result in knowledge_results[:3]:
                knowledge_context += f"\nИз книги '{result['book_name']}':\n{result['content'][:500]}...\n"
        
        enhanced_system_prompt = self.system_prompt + knowledge_context
        
        messages = [
            {"role": "system", "content": enhanced_system_prompt},
            *history,
            {"role": "user", "content": user_message}
        ]
        
        response = await self.get_gpt_response(messages)
        
        self.memory.save_message(user_id, "user", user_message)
        self.memory.save_message(user_id, "assistant", response)
        
        return response

def create_main_menu_keyboard():
    """Создание обновленной клавиатуры меню"""
    keyboard = [
        [InlineKeyboardButton("🧠 Кейс", callback_data="menu_keis"),
         InlineKeyboardButton("💬 Переписка", callback_data="menu_perepisca")],
        [InlineKeyboardButton("🎯 Ответ", callback_data="menu_otvet"),
         InlineKeyboardButton("📸 Скрин", callback_data="menu_skrin")],
        
        [InlineKeyboardButton("🥂 Свидание 1", callback_data="menu_svidanie1"),
         InlineKeyboardButton("🔥 Свидание 2", callback_data="menu_svidanie2")],
        [InlineKeyboardButton("🧠 Анализ 1", callback_data="menu_analiz1"),
         InlineKeyboardButton("🧠 Анализ 2", callback_data="menu_analiz2")],
        
        [InlineKeyboardButton("🆘 SOS Сигналы", callback_data="menu_sos"),
         InlineKeyboardButton("🎭 Стили соблазнения", callback_data="menu_styles")],
        [InlineKeyboardButton("📖 Истории", callback_data="menu_stories"),
         InlineKeyboardButton("💡 Сигналы интереса", callback_data="menu_signals")],
        [InlineKeyboardButton("👩 Типажи девушек", callback_data="menu_types"),
         InlineKeyboardButton("💬 Темы для свиданий", callback_data="menu_topics")],
        
        [InlineKeyboardButton("🧠 Психотип", callback_data="menu_psycho"),
         InlineKeyboardButton("📚 Знание", callback_data="menu_znanie")],
        [InlineKeyboardButton("🧬 Наука", callback_data="menu_nauka"),
         InlineKeyboardButton("🤖 Наставник", callback_data="menu_mentor")]
    ]
    return InlineKeyboardMarkup(keyboard)

def create_back_button():
    """Создание кнопки возврата"""
    keyboard = [[InlineKeyboardButton("🔙 Назад в меню", callback_data="back_to_menu")]]
    return InlineKeyboardMarkup(keyboard)

assistant = LesliAssistant()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start"""
    user_id = update.effective_user.id
    
    welcome_text = """
🔥 **Привет! Я LESLI45BOT 2.0**

Твой продвинутый наставник по соблазнению с ИИ анализом фото, персональными стилями и научной базой.

🎓 **База:** Лесли + современная психология + нейронаука

Выбери функцию или просто пиши мне - я отвечу! 💪
"""
    
    await update.message.reply_text(
        welcome_text, 
        reply_markup=create_main_menu_keyboard()
    )

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать основное меню"""
    menu_text = """
🔥 **LESLI45BOT 2.0 - Главное меню**

Выбери нужную функцию:

🧠 **Анализ** - разбор ситуаций и кейсов
💬 **Общение** - помощь с переписками и ответами  
📸 **ИИ-анализ** - анализ фото и скриншотов
🎭 **Стили и сигналы** - персональные стратегии
👩 **Типажи и темы** - работа с разными девушками
🎓 **Знания** - теория и наука

Или просто напиши мне вопрос! 💬
"""
    
    if update.callback_query:
        await update.callback_query.edit_message_text(
            menu_text,
            reply_markup=create_main_menu_keyboard()
        )
    else:
        await update.message.reply_text(
            menu_text,
            reply_markup=create_main_menu_keyboard()
        )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка обычных сообщений"""
    user_id = update.effective_user.id
    user_message = update.message.text
    
    if any(word in user_message.lower() for word in ['кейс', 'ситуация', 'проблема']):
        prompt = f"КЕЙС: {user_message}\n\nРазбери ситуацию и дай конкретные рекомендации."
    elif any(word in user_message.lower() for word in ['переписка', 'диалог', 'чат']):
        prompt = f"АНАЛИЗ ПЕРЕПИСКИ: {user_message}\n\nПроанализируй психологию и дай советы."
    elif any(word in user_message.lower() for word in ['свидание', 'встреча', 'поход']):
        prompt = f"СВИДАНИЕ: {user_message}\n\nДай стратегию и советы."
    elif any(word in user_message.lower() for word in ['стиль', 'подонок', 'романтик', 'провокатор']):
        prompt = f"СТИЛИ СОБЛАЗНЕНИЯ: {user_message}\n\nРасскажи о подходящем стиле и техниках."
    elif any(word in user_message.lower() for word in ['история', 'расскажи про', 'придумай историю']):
        prompt = f"СОЗДАНИЕ ИСТОРИИ: {user_message}\n\nСоздай увлекательную историю под ситуацию."
    elif any(word in user_message.lower() for word in ['типаж', 'тип девушки', 'психотип']):
        prompt = f"ТИПАЖ ДЕВУШКИ: {user_message}\n\nОпредели типаж и дай стратегию общения."
    else:
        prompt = user_message
    
    assistant.memory.update_user_stats(user_id, 'interactions')
    
    response = await assistant.process_message(user_id, prompt)
    await update.message.reply_text(response)

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка фотографий"""
    user_id = update.effective_user.id
    
    if not update.message.photo:
        await update.message.reply_text("Пришли фото для анализа!")
        return
    
    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    photo_data = await file.download_as_bytearray()
    
    caption = update.message.caption or ""
    if "селфи" in caption.lower() or "selfie" in caption.lower():
        analysis_type = "selfie"
    elif "профиль" in caption.lower() or "profile" in caption.lower():
        analysis_type = "profile"
    else:
        analysis_type = "general"
    
    await update.message.reply_text("🔍 Анализирую фото... Это может занять минуту.")
    
    analysis = await assistant.image_analyzer.analyze_photo(photo_data, analysis_type)
    assistant.memory.update_user_stats(user_id, 'interactions')
    
    await update.message.reply_text(f"📸 **Анализ фото:**\n\n{analysis}")

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка нажатий на кнопки"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    data = query.data
    
    if data == "back_to_menu":
        await show_main_menu(update, context)
        return
    
    if data.startswith("menu_"):
        menu_type = data.replace("menu_", "")
        
        if menu_type == "keis":
            await query.edit_message_text(
                "🧠 **Разбор кейса**\n\n"
                "Опиши ситуацию с девушкой, которую нужно разобрать.\n\n"
                "Например: 'Поцеловались на свидании, но она слилась'",
                reply_markup=create_back_button()
            )
        elif menu_type == "perepisca":
            await query.edit_message_text(
                "💬 **Анализ переписки**\n\n"
                "Пришли текст переписки или скриншот для анализа.\n\n"
                "Я разберу её психологию, мотивы и подскажу стратегию.",
                reply_markup=create_back_button()
            )
        elif menu_type == "otvet":
            await query.edit_message_text(
                "🎯 **Помощь с ответом**\n\n"
                "Опиши ситуацию и что она написала.\n\n"
                "Я подскажу идеальный ответ в твоем стиле.",
                reply_markup=create_back_button()
            )
        elif menu_type == "skrin":
            await query.edit_message_text(
                "📸 **Анализ скриншотов**\n\n"
                "Пришли скриншот переписки с девушкой!\n\n"
                "Я проанализирую:\n"
                "• Её психологию и мотивы\n"
                "• Стиль общения\n"
                "• Уровень заинтересованности\n"
                "• Рекомендации по продолжению",
                reply_markup=create_back_button()
            )
        elif menu_type == "sos":
            prompt = "Дай мне арсенал SOS сигналов из базы Лесли: влияние через образы, истории и жесты. Нужны техники экстренного воздействия."
            response = await assistant.process_message(user_id, prompt)
            await query.edit_message_text(
                f"🆘 **SOS Сигналы**\n\n{response}",
                reply_markup=create_back_button()
            )
        elif menu_type == "styles":
            keyboard = [
                [InlineKeyboardButton("😈 Подонок", callback_data="style_bad_boy")],
                [InlineKeyboardButton("💕 Романтик", callback_data="style_romantic")],
                [InlineKeyboardButton("🔥 Провокатор", callback_data="style_provocateur")],
                [InlineKeyboardButton("📊 Структурный", callback_data="style_structural")],
                [InlineKeyboardButton("👑 Мастер", callback_data="style_master")],
                [InlineKeyboardButton("🔙 Назад в меню", callback_data="back_to_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                "🎭 **Стили соблазнения**\n\n"
                "Выбери стиль для изучения техник и манеры общения:",
                reply_markup=reply_markup
            )
        elif menu_type == "stories":
            await query.edit_message_text(
                "📖 **Создание историй**\n\n"
                "Опиши психотип девушки или ситуацию.\n\n"
                "Я создам персональную историю, которая её зацепит.\n\n"
                "Например: 'Тревожная девушка, боится отношений'",
                reply_markup=create_back_button()
            )
        elif menu_type == "signals":
            keyboard = [
                [InlineKeyboardButton("💬 В переписке", callback_data="signals_text")],
                [InlineKeyboardButton("🥂 На свидании", callback_data="signals_date")],
                [InlineKeyboardButton("📱 В соцсетях", callback_data="signals_social")],
                [InlineKeyboardButton("🔙 Назад в меню", callback_data="back_to_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                "💡 **Сигналы заинтересованности**\n\n"
                "Выбери где хочешь научиться распознавать интерес:",
                reply_markup=reply_markup
            )
        elif menu_type == "types":
            keyboard = [
                [InlineKeyboardButton("👑 Контролирующая", callback_data="type_controlling")],
                [InlineKeyboardButton("🌹 Чувственная", callback_data="type_sensual")],
                [InlineKeyboardButton("😊 Эмоциональная", callback_data="type_emotional")],
                [InlineKeyboardButton("🤐 Замкнутая", callback_data="type_closed")],
                [InlineKeyboardButton("🌸 Молодые", callback_data="type_young")],
                [InlineKeyboardButton("🔙 Назад в меню", callback_data="back_to_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                "👩 **Типажи девушек**\n\n"
                "Выбери типаж для изучения стратегий общения:",
                reply_markup=reply_markup
            )
        elif menu_type == "topics":
            prompt = "ТЕМЫ ДЛЯ ПЕРВОГО СВИДАНИЯ: дай мне список оптимальных вопросов и тем для разговора на первом свидании. Какие темы зацепляют, а каких избегать."
            response = await assistant.process_message(user_id, prompt)
            await query.edit_message_text(
                f"💬 **Темы для свиданий**\n\n{response}",
                reply_markup=create_back_button()
            )
        elif menu_type == "psycho":
            await query.edit_message_text(
                "🧠 **Психотипирование**\n\n"
                "Опиши поведение девушки для анализа психотипа:\n\n"
                "Например: 'Отвечает быстро, много эмодзи, часто первая пишет, "
                "но на свидание не соглашается'",
                reply_markup=create_back_button()
            )
        elif menu_type == "znanie":
            await query.edit_message_text(
                "📚 **База знаний**\n\n"
                "О чем хочешь узнать из теории?\n\n"
                "Например: 'как создать доверие перед сексом'",
                reply_markup=create_back_button()
            )
        elif menu_type == "nauka":
            await query.edit_message_text(
                "🧬 **Научная база**\n\n"
                "О какой научной теории хочешь узнать?\n\n"
                "Примеры:\n"
                "• теория привязанности\n"
                "• окситоцин и близость\n"
                "• эволюционная психология выбора партнера",
                reply_markup=create_back_button()
            )
        elif menu_type == "mentor":
            assistant.memory.set_mentor_mode(user_id, True)
            await query.edit_message_text(
                "🤖 **Режим наставника включен!**\n\n"
                "Теперь я буду периодически задавать вопросы для твоего развития.",
                reply_markup=create_back_button()
            )
    
    elif data.startswith("style_"):
        style_type = data.replace("style_", "")
        style_names = {
            'bad_boy': 'Подонок',
            'romantic': 'Романтик', 
            'provocateur': 'Провокатор',
            'structural': 'Структурный',
            'master': 'Мастер'
        }
        
        style_name = style_names.get(style_type, style_type)
        prompt = f"СТИЛЬ СОБЛАЗНЕНИЯ '{style_name.upper()}': расскажи подробно об этом стиле - кому подходит, основные техники, манера общения, примеры фраз и поведения."
        response = await assistant.process_message(user_id, prompt)
        
        await query.edit_message_text(
            f"🎭 **Стиль: {style_name}**\n\n{response}",
            reply_markup=create_back_button()
        )
    
    elif data.startswith("type_"):
        type_name = data.replace("type_", "")
        type_names = {
            'controlling': 'Контролирующая',
            'sensual': 'Чувственная',
            'emotional': 'Эмоциональная', 
            'closed': 'Замкнутая',
            'young': 'Молодые'
        }
        
        girl_type = type_names.get(type_name, type_name)
        prompt = f"ТИПАЖ ДЕВУШКИ '{girl_type.upper()}': дай полное описание - психология, мотивы, страхи, как с ней общаться, какие техники работают, примеры подходов."
        response = await assistant.process_message(user_id, prompt)
        
        await query.edit_message_text(
            f"👩 **Типаж: {girl_type}**\n\n{response}",
            reply_markup=create_back_button()
        )
    
    elif data.startswith("signals_"):
        signal_type = data.replace("signals_", "")
        signal_names = {
            'text': 'в переписке',
            'date': 'на свидании',
            'social': 'в соцсетях'
        }
        
        context = signal_names.get(signal_type, signal_type)
        prompt = f"СИГНАЛЫ ЗАИНТЕРЕСОВАННОСТИ {context.upper()}: дай подробный список признаков интереса девушки {context}. Как понять что она заинтересована, а когда стоит отступить."
        response = await assistant.process_message(user_id, prompt)
        
        await query.edit_message_text(
            f"💡 **Сигналы интереса {context}**\n\n{response}",
            reply_markup=create_back_button()
        )

def main():
    """Основная функция запуска бота"""
    if not config.OPENAI_API_KEY:
        logger.error("OPENAI_API_KEY не установлен!")
        return
    
    application = Application.builder().token(config.TELEGRAM_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", show_main_menu))
    
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("Запуск LESLI45BOT 2.0...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
