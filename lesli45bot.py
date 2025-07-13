#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LESLI45BOT - Персональный Telegram-ассистент по соблазнению
Основан на GPT-4o с базой знаний из книг Алекса Лесли

УСТАНОВКА ЗАВИСИМОСТЕЙ:
pip install openai python-telegram-bot PyPDF2 python-docx ebooklib Pillow

СТРУКТУРА ФАЙЛОВ:
lesli45bot.py       - основной файл бота
books/              - папка с вашими книгами (PDF, DOCX, EPUB, TXT)
lesli_bot.db        - база данных (создается автоматически)

КАК ЗАГРУЗИТЬ МАТЕРИАЛЫ:
1. Создайте папку "books" рядом с файлом бота
2. Поместите туда ваши книги в форматах: PDF, DOCX, EPUB, TXT
3. Запустите бота - он автоматически обработает все книги
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
                    # Простая очистка HTML тегов
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
        
        # Определяем тип файла и извлекаем текст
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
        
        # Разбиваем текст на части для лучшего поиска
        chunks = self.split_text_into_chunks(text, chunk_size=1000)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Проверяем, есть ли уже эта книга в базе
        cursor.execute('SELECT COUNT(*) FROM knowledge_base WHERE book_name = ?', (book_name,))
        if cursor.fetchone()[0] > 0:
            logger.info(f"Книга {book_name} уже в базе знаний")
            conn.close()
            return
        
        # Сохраняем части книги в базу
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
        
        # Основные термины соблазнения
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
        
        return ', '.join(keywords[:10])  # Максимум 10 ключевых слов
    
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
        
        # Поиск по ключевым словам и содержимому
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
        
        # Удаляем дубликаты и возвращаем
        unique_results = []
        seen = set()
        for result in results:
            if result[2] not in seen:  # content as identifier
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
        
        # Проверяем есть ли запись за сегодня
        cursor.execute('SELECT id FROM user_stats WHERE user_id = ? AND date = ?', (user_id, today))
        if cursor.fetchone():
            # Обновляем существующую запись
            cursor.execute(f'''
                UPDATE user_stats 
                SET {stat_type} = {stat_type} + ? 
                WHERE user_id = ? AND date = ?
            ''', (value, user_id, today))
        else:
            # Создаем новую запись
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
            # Конвертируем фото в base64
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
        # Упрощенная логика для демонстрации
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
        
        # Загружаем книги при инициализации
        self.knowledge.load_books_from_directory()
        
        # Системный промпт с встроенной базой знаний
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
   - Социальное влияние и убеждение (Cialdини)

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

КОМАНДЫ КОТОРЫЕ ТЫ ОБРАБАТЫВАЕШЬ:
/кейс - разбор с научной точки зрения
/переписка - анализ на основе психологии коммуникации
/ответ - помощь с учетом принципов влияния
/свидание1 - подготовка с научным обоснованием
/свидание2 - стратегия на основе теории привязанности
/анализ1 - разбор с точки зрения невербалики и психологии
/анализ2 - анализ интимности и границ
/знание - теория из научных источников + база Лесли
/наука - объяснение научных основ поведения

РЕЖИМ НАСТАВНИКА:
Когда включен, задаешь научно обоснованные вопросы:
- "Какой тип привязанности у этой девушки?"
- "Какие невербальные сигналы ты заметил?"
- "Как она реагировала на твое доминирование/уязвимость?"

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
        # Ищем релевантную информацию в базе знаний
        knowledge_results = self.knowledge.search_knowledge(user_message)
        
        # Получаем историю разговора
        history = self.memory.get_conversation_history(user_id)
        
        # Формируем контекст из базы знаний
        knowledge_context = ""
        if knowledge_results:
            knowledge_context = "\n\nРЕЛЕВАНТНАЯ ИНФОРМАЦИЯ ИЗ БАЗЫ ЗНАНИЙ:\n"
            for result in knowledge_results[:3]:  # Берем топ-3 результата
                knowledge_context += f"\nИз книги '{result['book_name']}':\n{result['content'][:500]}...\n"
        
        # Формируем сообщения для GPT
        enhanced_system_prompt = self.system_prompt + knowledge_context
        
        messages = [
            {"role": "system", "content": enhanced_system_prompt},
            *history,
            {"role": "user", "content": user_message}
        ]
        
        # Получаем ответ
        response = await self.get_gpt_response(messages)
        
        # Сохраняем в память
        self.memory.save_message(user_id, "user", user_message)
        self.memory.save_message(user_id, "assistant", response)
        
        return response

def create_main_menu_keyboard():
    """Создание обновленной клавиатуры меню"""
    keyboard = [
        # Базовые функции анализа
        [InlineKeyboardButton("🧠 Кейс", callback_data="menu_keis"),
         InlineKeyboardButton("💬 Переписка", callback_data="menu_perepisca")],
        [InlineKeyboardButton("🎯 Ответ", callback_data="menu_otvet"),
         InlineKeyboardButton("📸 Скрин", callback_data="menu_skrin")],
        
        # Свидания
        [InlineKeyboardButton("🥂 Свидание 1", callback_data="menu_svidanie1"),
         InlineKeyboardButton("🔥 Свидание 2", callback_data="menu_svidanie2")],
        [InlineKeyboardButton("🧠 Анализ 1", callback_data="menu_analiz1"),
         InlineKeyboardButton("🧠 Анализ 2", callback_data="menu_analiz2")],
        
        # Новые практические функции
        [InlineKeyboardButton("🆘 SOS Сигналы", callback_data="menu_sos"),
         InlineKeyboardButton("🎭 Стили соблазнения", callback_data="menu_styles")],
        [InlineKeyboardButton("📖 Истории", callback_data="menu_stories"),
         InlineKeyboardButton("💡 Сигналы интереса", callback_data="menu_signals")],
        [InlineKeyboardButton("👩 Типажи девушек", callback_data="menu_types"),
         InlineKeyboardButton("💬 Темы для свиданий", callback_data="menu_topics")],
        
        # Психология и знания
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

# Инициализация расширенного ассистента
assistant = LesliAssistant()

# Обработчики команд с меню
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

# Базовые обработчики (остаются без изменений)
async def handle_keis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка команды /кейс"""
    user_id = update.effective_user.id
    text = update.message.text[6:].strip()  # Убираем "/кейс "
    
    if not text:
        await update.message.reply_text(
            "📝 Опиши ситуацию с девушкой, которую нужно разобрать.\n\n"
            "Например: /кейс Поцеловался на свидании, но она слилась"
        )
        return
    
    prompt = f"КЕЙС ДЛЯ РАЗБОРА: {text}\n\nДай глубокий анализ ситуации с психологическими причинами и конкретный план действий."
    response = await assistant.process_message(user_id, prompt)
    await update.message.reply_text(response)

async def handle_perepisca(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка команды /переписка"""
    user_id = update.effective_user.id
    text = update.message.text[11:].strip()  # Убираем "/переписка "
    
    if not text:
        await update.message.reply_text(
            "💬 Пришли текст переписки с девушкой для анализа.\n\n"
            "Я разберу её психологию, мотивы и подскажу стратегию."
        )
        return
    
    prompt = f"АНАЛИЗ ПЕРЕПИСКИ:\n{text}\n\nПроанализируй психологию девушки, её мотивы, страхи, уровень заинтересованности и дай рекомендации."
    response = await assistant.process_message(user_id, prompt)
    await update.message.reply_text(response)

async def handle_otvet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка команды /ответ"""
    user_id = update.effective_user.id
    text = update.message.text[7:].strip()  # Убираем "/ответ "
    
    if not text:
        await update.message.reply_text(
            "🎯 Опиши ситуацию и что она написала.\n\n"
            "Я подскажу идеальный ответ в твоем стиле."
        )
        return
    
    prompt = f"НУЖЕН ОТВЕТ НА: {text}\n\nПридумай идеальный ответ с учетом психологии и фреймов."
    response = await assistant.process_message(user_id, prompt)
    await update.message.reply_text(response)

async def handle_svidanie1(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка команды /свидание1"""
    user_id = update.effective_user.id
    text = update.message.text[10:].strip()  # Убираем "/свидание1 "
    
    prompt = f"ПОДГОТОВКА К ПЕРВОМУ СВИДАНИЮ: {text}\n\nДай полную стратегию: место, поведение, темы, как закрыть свидание."
    response = await assistant.process_message(user_id, prompt)
    await update.message.reply_text(response)

async def handle_svidanie2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка команды /свидание2"""
    user_id = update.effective_user.id
    text = update.message.text[10:].strip()  # Убираем "/свидание2 "
    
    prompt = f"СТРАТЕГИЯ ВТОРОГО СВИДАНИЯ: {text}\n\nКак проверить готовность к близости, тактика сближения, работа с возражениями."
    response = await assistant.process_message(user_id, prompt)
    await update.message.reply_text(response)

async def handle_analiz1(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка команды /анализ1"""
    user_id = update.effective_user.id
    text = update.message.text[9:].strip()  # Убираем "/анализ1 "
    
    prompt = f"АНАЛИЗ ПЕРВОГО СВИДАНИЯ: {text}\n\nПроанализируй что прошло хорошо, где были ошибки, почему такая реакция девушки."
    response = await assistant.process_message(user_id, prompt)
    await update.message.reply_text(response)

async def handle_analiz2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка команды /анализ2"""
    user_id = update.effective_user.id
    text = update.message.text[9:].strip()  # Убираем "/анализ2 "
    
    prompt = f"АНАЛИЗ ВТОРОГО СВИДАНИЯ: {text}\n\nРазбери тактику сближения, причины отказа/согласия, что делать дальше."
    response = await assistant.process_message(user_id, prompt)
    await update.message.reply_text(response)

async def handle_znanie(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка команды /знание"""
    user_id = update.effective_user.id
    text = update.message.text[8:].strip()  # Убираем "/знание "
    
    if not text:
        await update.message.reply_text(
            "📚 О чем хочешь узнать из теории?\n\n"
            "Например: /знание как создать доверие перед сексом"
        )
        return
    
    prompt = f"ТЕОРИЯ ПО ТЕМЕ: {text}\n\nДай глубокое объяснение с примерами из базы знаний Лесли."
    response = await assistant.process_message(user_id, prompt)
    await update.message.reply_text(response)

async def handle_nauka(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка команды /наука"""
    user_id = update.effective_user.id
    text = update.message.text[7:].strip()  # Убираем "/наука "
    
    if not text:
        await update.message.reply_text(
            "🧬 О какой научной теории хочешь узнать?\n\n"
            "Примеры:\n"
            "• /наука теория привязанности\n"
            "• /наука окситоцин и близость\n"
            "• /наука эволюционная психология выбора партнера\n"
            "• /наука невербальная коммуникация\n"
            "• /наука дофамин и влечение"
        )
        return
    
    prompt = f"НАУЧНОЕ ОБЪЯСНЕНИЕ: {text}\n\nДай научно обоснованное объяснение с ссылками на исследования и применение в отношениях."
    response = await assistant.process_message(user_id, prompt)
    await update.message.reply_text(response)

async def handle_nastavnik(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Включение режима наставника"""
    user_id = update.effective_user.id
    assistant.memory.set_mentor_mode(user_id, True)
    
    await update.message.reply_text(
        "🤖 Режим наставника включен!\n\n"
        "Теперь я буду периодически задавать вопросы для твоего развития."
    )

async def handle_psychotype(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка команды /психотип"""
    user_id = update.effective_user.id
    text = update.message.text[10:].strip()  # Убираем "/психотип "
    
    if not text:
        await update.message.reply_text(
            "🧠 Опиши поведение девушки для анализа психотипа:\n\n"
            "Например:\n"
            "/психотип Отвечает быстро, много эмодзи, часто первая пишет, "
            "но на свидание не соглашается"
        )
        return
    
    # Анализируем стиль привязанности
    attachment = assistant.psycho_analyzer.analyze_attachment_style(text)
    
    analysis = f"""
🧠 **Психологический анализ:**

**Стиль привязанности:** {attachment['style']}
**Описание:** {attachment['description']}

**Стратегия общения:** {attachment['strategy']}

**Дополнительные рекомендации:**
Напиши более подробное описание её поведения, и я дам расширенный анализ с конкретными тактиками.
"""
    
    await update.message.reply_text(analysis)

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка фотографий"""
    user_id = update.effective_user.id
    
    if not update.message.photo:
        await update.message.reply_text("Пришли фото для анализа!")
        return
    
    # Получаем фото в наилучшем качестве
    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    
    # Скачиваем фото
    photo_data = await file.download_as_bytearray()
    
    # Определяем тип анализа по подписи
    caption = update.message.caption or ""
    if "селфи" in caption.lower() or "selfie" in caption.lower():
        analysis_type = "selfie"
    elif "профиль" in caption.lower() or "profile" in caption.lower():
        analysis_type = "profile"
    else:
        analysis_type = "general"
    
    await update.message.reply_text("🔍 Анализирую фото... Это может занять минуту.")
    
    # Анализируем фото
    analysis = await assistant.image_analyzer.analyze_photo(photo_data, analysis_type)
    
    # Обновляем статистику
    assistant.memory.update_user_stats(user_id, 'interactions')
    
    await update.message.reply_text(f"📸 **Анализ фото:**\n\n{analysis}")

# Новые обработчики для новых функций
async def handle_sos_signals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка SOS сигналов"""
    user_id = update.effective_user.id
    
    prompt = "Дай мне арсенал SOS сигналов из базы Лесли: влияние через образы, истории и жесты. Нужны техники экстренного воздействия."
    response = await assistant.process_message(user_id, prompt)
    await update.message.reply_text(response)

async def handle_seduction_styles(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка стилей соблазнения"""
    user_id = update.effective_user.id
    
    keyboard = [
        [InlineKeyboardButton("😈 Подонок", callback_data="style_bad_boy")],
        [InlineKeyboardButton("💕 Романтик", callback_data="style_romantic")],
        [InlineKeyboardButton("🔥 Провокатор", callback_data="style_provocateur")],
        [InlineKeyboardButton("📊 Структурный", callback_data="style_structural")],
        [InlineKeyboardButton("👑 Мастер", callback_data="style_master")],
        [InlineKeyboardButton("🔙 Назад в меню", callback_data="back_to_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🎭 **Выбери стиль соблазнения:**\n\n"
        "Каждый стиль имеет свои техники, манеру общения и подходы.",
        reply_markup=reply_markup
    )

async def handle_stories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка создания историй"""
    user_id = update.effective_user.id
    text = update.message.text[8:].strip() if update.message else ""  # Убираем "/истории "
    
    if not text:
        await update.message.reply_text(
            "📖 Опиши психотип девушки или ситуацию:\n\n"
            "Я создам персональную историю, которая её зацепит.\n\n"
            "Например: 'Тревожная девушка, боится отношений'"
        )
        return
    
    prompt = f"СОЗДАНИЕ ИСТОРИИ: {text}\n\nСоздай увлекательную персональную историю под этот психотип девушки. История должна вызывать эмоции и интерес."
    response = await assistant.process_message(user_id, prompt)
    await update.message.reply_text(response)

async def handle_interest_signals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка сигналов заинтересованности"""
    user_id = update.effective_user.id
    
    keyboard = [
        [InlineKeyboardButton("💬 В переписке", callback_data="signals_text")],
        [InlineKeyboardButton("🥂 На свидании", callback_data="signals_date")],
        [InlineKeyboardButton("📱 В соцсетях", callback_data="signals_social")],
        [InlineKeyboardButton("🔙 Назад в меню", callback_data="back_to_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "💡 **Сигналы заинтересованности:**\n\n"
        "Выбери где хочешь научиться распознавать интерес:",
        reply_markup=reply_markup
    )

async def handle_girl_types(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка типажей девушек"""
    user_id = update.effective_user.id
    
    keyboard = [
        [InlineKeyboardButton("👑 Контролирующая", callback_data="type_controlling")],
        [InlineKeyboardButton("🌹 Чувственная", callback_data="type_sensual")],
        [InlineKeyboardButton("😊 Эмоциональная", callback_data="type_emotional")],
        [InlineKeyboardButton("🤐 Замкнутая", callback_data="type_closed")],
        [InlineKeyboardButton("🌸 Молодые", callback_data="type_young")],
        [InlineKeyboardButton("🔙 Назад в меню", callback_data="back_to_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "👩 **Типажи девушек:**\n\n"
        "Выбери типаж для изучения стратегий общения:",
        reply_markup=reply_markup
    )

async def handle_date_topics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка тем для свиданий"""
    user_id = update.effective_user.id
    
    prompt = "ТЕМЫ ДЛЯ ПЕРВОГО СВИДАНИЯ: дай мне список оптимальных вопросов и тем для разговора на первом свидании. Какие темы зацепляют, а каких избегать."
    response = await assistant.process_message(user_id, prompt)
    await update.message.reply_text(response)

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка нажатий на кнопки"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    data = query.data
    
    # Возврат в главное меню
    if data == "back_to_menu":
        await show_main_menu(update, context)
        return
    
    # Основное меню
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
        elif menu_type == "svidanie1":
            await query.edit_message_text(
                "🥂 **Первое свидание**\n\n"
                "Опиши ситуацию для подготовки к первому свиданию.\n\n"
                "Я дам полную стратегию: место, поведение, темы, как закрыть свидание.",
                reply_markup=create_back_button()
            )
        elif menu_type == "svidanie2":
            await query.edit_message_text(
                "🔥 **Второе свидание**\n\n"
                "Опиши как прошло первое свидание.\n\n"
                "Дам стратегию для второго: проверка готовности к близости, тактика сближения.",
                reply_markup=create_back_button()
            )
        elif menu_type == "analiz1":
            await query.edit_message_text(
                "🧠 **Анализ первого свидания**\n\n"
                "Расскажи как прошло первое свидание.\n\n"
                "Проанализирую что прошло хорошо, где были ошибки, почему такая реакция девушки.",
                reply_markup=create_back_button()
            )
        elif menu_type == "analiz2":
            await query.edit_message_text(
                "🧠 **Анализ второго свидания**\n\n"
                "Расскажи как прошло второе свидание.\n\n"
                "Разберу тактику сближения, причины отказа/согласия, что делать дальше.",
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
    
    # Обработка стилей соблазнения
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
    
    # Обработка типажей девушек
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
    
    # Обработка сигналов заинтересованности
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

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка обычных сообщений"""
    user_id = update.effective_user.id
    user_message = update.message.text
    
    # Проверяем ключевые слова для автоматического распознавания команд
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
    
    # Обновляем статистику взаимодействий
    assistant.memory.update_user_stats(user_id, 'interactions')
    
    response = await assistant.process_message(user_id, prompt)
    await update.message.reply_text(response)

def main():
    """Основная функция запуска бота"""
    # Проверяем наличие API ключа
    if not config.OPENAI_API_KEY:
        logger.error("OPENAI_API_KEY не установлен!")
        return
    
    # Создаем приложение
    application = Application.builder().token(config.TELEGRAM_TOKEN).build()
    
    # Добавляем обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", show_main_menu))
    application.add_handler(CommandHandler("case", handle_keis))
    application.add_handler(CommandHandler("chat", handle_perepisca))
    application.add_handler(CommandHandler("reply", handle_otvet))
    application.add_handler(CommandHandler("date1", handle_svidanie1))
    application.add_handler(CommandHandler("date2", handle_svidanie2))
    application.add_handler(CommandHandler("analyze1", handle_analiz1))
    application.add_handler(CommandHandler("analyze2", handle_analiz2))
    application.add_handler(CommandHandler("knowledge", handle_znanie))
    application.add_handler(CommandHandler("наука", handle_nauka))
    application.add_handler(CommandHandler("coach", handle_nastavnik))
    application.add_handler(CommandHandler("психотип", handle_psychotype))
    
    # Новые команды
    application.add_handler(CommandHandler("sos", handle_sos_signals))
    application.add_handler(CommandHandler("стили", handle_seduction_styles))
    application.add_handler(CommandHandler("истории", handle_stories))
    application.add_handler(CommandHandler("сигналы", handle_interest_signals))
    application.add_handler(CommandHandler("типажи", handle_girl_types))
    application.add_handler(CommandHandler("темы", handle_date_topics))
    
    # Обработчики контента
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Запускаем бота
    logger.info("Запуск LESLI45BOT 2.0...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()

from aiogram import types

@dp.message_handler(commands=["start"])
async def cmd_start(message: types.Message):
    await message.answer("Привет! Я Лесли-бот. Готов помогать тебе разбирать кейсы и становиться мастером игры 😉")
