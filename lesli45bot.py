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

class LesliAssistant:
    """Главный класс бота-ассистента"""
    
    def __init__(self):
        self.openai_client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
        self.db = None
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
                
        except Exception as e:
            logger.error(f"❌ Ошибка подключения к базе данных: {e}")
            # Fallback к SQLite
            self.db = sqlite3.connect('lesli_bot.db', check_same_thread=False)
    
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
            # Системный промпт
            system_prompt = """Ты LESLI45BOT - персональный наставник по соблазнению на основе методов Алекса Лесли.

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

ПРИНЦИПЫ РАБОТЫ:
- Всегда используй методы и техники из книг Лесли
- Давай конкретные практические советы
- Учитывай психотип и контекст ситуации
- Будь прямым и честным
- Помни о согласии и этике

Отвечай как опытный наставник - кратко, по делу, с конкретными техниками."""

            # Формируем сообщения для GPT
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ]
            
            # Получаем ответ
            response = self.get_gpt_response_sync(messages)
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
    menu_text = """🔥 **LESLI45BOT 2.0 - Главное меню**

Выбери нужную функцию:

🧠 **Анализ** - разбор ситуаций и кейсов
💬 **Общение** - помощь с перепиской и ответами
🥂 **Свидания** - стратегии для встреч
🆘 **SOS** - экстренные техники влияния
🎭 **Стили** - методы соблазнения
👩 **Типажи** - работа с разными девушками
🧬 **Психология** - научный анализ

Используй кнопки ниже для быстрого доступа к функциям! 👇"""
    
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
            text = "🧠 **Анализ кейса**\n\nОпиши ситуацию с девушкой и что пошло не так - дам конкретные советы!"
            bot.edit_message_text(
                text,
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                parse_mode='Markdown'
            )
        elif menu_type == "perepiska":
            text = "💬 **Анализ переписки**\n\nПришли скрин переписки или опиши диалог - проанализирую интерес девушки!"
            bot.edit_message_text(
                text,
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                parse_mode='Markdown'
            )
        elif menu_type == "otvet":
            text = "💡 **Помощь с ответом**\n\nОпиши что она написала - дам варианты ответов!"
            bot.edit_message_text(
                text,
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
            
            text = "🎭 **Стили соблазнения**\n\nВыбери стиль для изучения!"
            bot.edit_message_text(
                text,
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
            
            text = "👩 **Типажи девушек**\n\nВыбери тип для изучения!"
            bot.edit_message_text(
                text,
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=keyboard,
                parse_mode='Markdown'
            )
        elif menu_type == "znanie":
            text = "📚 **База знаний**\n\nСпроси о любой технике соблазнения из книг Лесли!"
            bot.edit_message_text(
                text,
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                parse_mode='Markdown'
            )
        elif menu_type == "main":
            menu_text = """🔥 **LESLI45BOT 2.0 - Главное меню**

Выбери нужную функцию:

🧠 **Анализ** - разбор ситуаций и кейсов
💬 **Общение** - помощь с перепиской и ответами
🥂 **Свидания** - стратегии для встреч
🆘 **SOS** - экстренные техники влияния
🎭 **Стили** - методы соблазнения
👩 **Типажи** - работа с разными девушками
🧬 **Психология** - научный анализ

Используй кнопки ниже для быстрого доступа к функциям! 👇"""
            bot.edit_message_text(
                menu_text,
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=create_main_menu_keyboard(),
                parse_mode='Markdown'
            )
        elif call.data.startswith("style_"):
            style = call.data.replace("style_", "")
            response = assistant.process_message(f"Расскажи подробно о стиле соблазнения {style}", user_id)
            bot.edit_message_text(
                response,
                chat_id=call.message.chat.id,
                message_id=call.message.message_id
            )
        elif call.data.startswith("type_"):
            type_name = call.data.replace("type_", "")
            response = assistant.process_message(f"Расскажи как работать с типажом девушки {type_name}", user_id)
            bot.edit_message_text(
                response,
                chat_id=call.message.chat.id,
                message_id=call.message.message_id
            )
        else:
            # Все остальные кнопки меню
            menu_responses = {
                "skrin": "📸 **Анализ скрина**\n\nПришли скрин для анализа!",
                "svidanie1": "🥂 **Первое свидание**\n\nРасскажи о девушке - дам стратегию!",
                "svidanie2": "💑 **Второе свидание**\n\nКак прошло первое? Составлю план!",
                "analiz1": "📊 **Анализ первого свидания**\n\nОпиши как прошло!",
                "analiz2": "📈 **Анализ второго свидания**\n\nРасскажи детали!",
                "sos": "🆘 **SOS Сигналы**\n\nОпиши критическую ситуацию!",
                "stories": "📖 **Создание историй**\n\nОпиши психотип девушки!",
                "signals": "💡 **Сигналы интереса**\n\nОпиши ситуацию!",
                "topics": "💬 **Темы для свиданий**\n\nОпиши девушку!",
                "psihotip": "🧬 **Психотип**\n\nОпиши поведение девушки!",
                "nauka": "🔬 **Научная база**\n\nО какой теории хочешь узнать?",
                "nastavnik": "👨‍🏫 **Наставник**\n\nРасскажи о ситуации!"
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
        bot.reply_to(message, "Произошла ошибка. Попробуйте еще раз или используйте /start.")

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    """Обработка фотографий"""
    try:
        caption = message.caption or ""
        analysis = "📸 **Анализ фото:**\n\nПолучил фото для анализа! Опиши что видишь на фото текстом, и я дам рекомендации по соблазнению!"
        
        bot.reply_to(message, analysis, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Ошибка обработки фото: {e}")
        bot.reply_to(message, "Опиши что на фото текстом!")

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
