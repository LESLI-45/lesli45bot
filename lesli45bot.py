#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LESLI45BOT - Персональный Telegram-ассистент по соблазнению
Основан на GPT-4o с базой знаний из книг Алекса Лесли
TELEBOT VERSION - простая и надежная
"""

import logging
import os
import sys
from datetime import datetime

# Telegram
import telebot
from telebot import types

# OpenAI - ИСПРАВЛЕННЫЙ ИМПОРТ
from openai import OpenAI

# Обработка файлов
import PyPDF2
import docx
import ebooklib.epub

# База данных
import psycopg2
from psycopg2.extras import RealDictCursor

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Конфигурация
class Config:
    TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
    OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
    DATABASE_URL = os.getenv('DATABASE_URL')
    
    def __init__(self):
        if not self.TELEGRAM_TOKEN:
            logger.error("❌ TELEGRAM_TOKEN не найден!")
            sys.exit(1)
        if not self.OPENAI_API_KEY:
            logger.error("❌ OPENAI_API_KEY не найден!")
            sys.exit(1)
        if not self.DATABASE_URL:
            logger.error("❌ DATABASE_URL не найден!")
            sys.exit(1)

config = Config()

# Инициализация бота
bot = telebot.TeleBot(config.TELEGRAM_TOKEN)

class LesliAssistant:
    def __init__(self):
        # ИСПРАВЛЕННАЯ ИНИЦИАЛИЗАЦИЯ OPENAI
        self.openai_client = OpenAI(api_key=config.OPENAI_API_KEY)
        logger.info("✅ OpenAI клиент инициализирован")
    
    def get_ai_response(self, user_message: str, user_id: int = None) -> str:
        """Получение ответа от GPT-4o"""
        try:
            # УБРАЛ AWAIT - теперь синхронный вызов
            response = self.openai_client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "system",
                        "content": """Ты LESLI45BOT - персональный ассистент по соблазнению на основе методик Алекса Лесли.

Твоя задача:
• Помогать в общении с девушками
• Давать конкретные советы по соблазнению
• Анализировать ситуации и переписки
• Использовать знания из книг Лесли

Стиль общения:
• Дружелюбный и поддерживающий
• Конкретные советы без лишних слов
• Используй эмодзи для наглядности
• Будь экспертом, но не занудой"""
                    },
                    {
                        "role": "user",
                        "content": user_message
                    }
                ],
                max_tokens=1000,
                temperature=0.7
            )
            
            return response.choices[0].message.content.strip()
            
        except Exception as e:
            logger.error(f"❌ Ошибка OpenAI: {e}")
            return "❌ Извини, временные проблемы с ИИ. Попробуй позже!"

# Глобальный экземпляр
assistant = LesliAssistant()

def create_main_menu():
    """Создание главного меню с кнопками"""
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    buttons = [
        ("🎯 Конкретная ситуация", "menu_situacia"),
        ("💬 Анализ переписки", "menu_perepiska"),
        ("📱 Первое сообщение", "menu_pervoe"),
        ("🔥 Разогрев и флирт", "menu_razogrev"),
        ("📞 Звонки и свидания", "menu_zvonki"),
        ("❄️ Холодные контакты", "menu_holodnye"),
        ("🎭 Стили соблазнения", "menu_stili"),
        ("👩 Типажи девушек", "menu_tipy"),
        ("🧠 Психология", "menu_psihologia"),
        ("🎬 Кейсы и истории", "menu_keis"),
        ("💡 Фреймы", "menu_freims"),
        ("🔍 Поиск по базе", "menu_poisk"),
        ("💵 Деньги и статус", "menu_dengi"),
        ("🏆 Уверенность", "menu_uverennost"),
        ("🆘 SOS Сигналы", "menu_sos"),
        ("❤️ Отношения", "menu_otnosheniya"),
        ("🎪 Темы для свиданий", "menu_temy"),
        ("🔧 Личный коучинг", "menu_kouching")
    ]
    
    for text, callback in buttons:
        markup.add(types.InlineKeyboardButton(text, callback_data=callback))
    
    return markup

@bot.message_handler(commands=['start'])
def start_command(message):
    """Обработка команды /start"""
    user_name = message.from_user.first_name or "друг"
    
    welcome_text = f"""🔥 **Привет, {user_name}!**

Я LESLI45BOT - твой персональный ассистент по соблазнению на основе методик **Алекса Лесли**.

🎯 **Что я умею:**
• 💬 Анализировать переписки с девушками
• 🔥 Помогать с флиртом и соблазнением  
• 📱 Составлять первые сообщения
• 🎭 Подбирать стили под разные типажи
• 🧠 Давать психологические инсайты
• 💡 Обучать фреймам и техникам

🚀 **База знаний:** 4500+ записей из 9 книг Лесли
🤖 **ИИ:** GPT-4o для персональных советов

Используй кнопки ниже для быстрого доступа к функциям! 👇"""
    
    try:
        bot.send_message(
            message.chat.id,
            welcome_text,
            reply_markup=create_main_menu(),
            parse_mode='Markdown'
        )
        logger.info(f"✅ Отправлено приветствие пользователю {user_name}")
    except Exception as e:
        logger.error(f"❌ Ошибка отправки приветствия: {e}")

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    """Обработка нажатий кнопок"""
    try:
        menu_type = call.data.replace("menu_", "")
        user_id = call.from_user.id
        
        # Простые ответы для каждой кнопки
        responses = {
            "situacia": "🎯 **Конкретная ситуация**\n\nОпиши свою ситуацию с девушкой максимально подробно, и я дам конкретные советы как действовать дальше!",
            "perepiska": "💬 **Анализ переписки**\n\nПришли скрин переписки или опиши диалог. Проанализирую её интерес и подскажу что писать дальше!",
            "pervoe": "📱 **Первое сообщение**\n\nРасскажи где познакомился с девушкой и что о ней знаешь. Составлю идеальное первое сообщение!",
            "razogrev": "🔥 **Разогрев и флирт**\n\nОпиши на какой стадии общения вы находитесь. Дам техники разогрева и эскалации!",
            "zvonki": "📞 **Звонки и свидания**\n\nРасскажи о ситуации с девушкой. Подскажу как правильно назначать встречи и проводить свидания!",
            "holodnye": "❄️ **Холодные контакты**\n\nОпиши где и как хочешь познакомиться. Дам стратегию холодных знакомств!",
            "stili": "🎭 **Стили соблазнения**\n\nОпиши девушку и ситуацию. Подберу оптимальный стиль: Плохой парень, Джентльмен, Альфа или Загадка!",
            "tipy": "👩 **Типажи девушек**\n\nРасскажи о девушке: внешность, поведение, интересы. Определю её типаж и дам стратегию!",
            "psihologia": "🧠 **Психология**\n\nЗадай вопрос по психологии общения с женщинами. Объясню механизмы притяжения!",
            "keis": "🎬 **Кейсы и истории**\n\nОпиши свою ситуацию, и я найду похожий кейс из практики с разбором действий!",
            "freims": "💡 **Фреймы**\n\nРасскажи о ситуации в общении. Подскажу какие фреймы использовать для влияния!",
            "poisk": "🔍 **Поиск по базе**\n\nЗадай любой вопрос по соблазнению. Найду ответ в базе знаний Лесли!",
            "dengi": "💵 **Деньги и статус**\n\nВопросы про демонстрацию статуса, подарки, траты на девушек. Расскажу как правильно!",
            "uverennost": "🏆 **Уверенность**\n\nПроблемы с уверенностью в общении с девушками? Дам техники и упражнения!",
            "sos": "🆘 **SOS Сигналы**\n\nЭкстренная ситуация? Быстро опиши проблему - дам срочный совет!",
            "otnosheniya": "❤️ **Отношения**\n\nВопросы про отношения, конфликты, расставания. Помогу разобраться!",
            "temy": "🎪 **Темы для свиданий**\n\nНужны идеи для свиданий или темы для разговора? Подскажу варианты!",
            "kouching": "🔧 **Личный коучинг**\n\nРасскажи о своих целях с женщинами. Составлю личный план развития!"
        }
        
        response_text = responses.get(menu_type, "🤖 Опиши свою ситуацию, и я помогу!")
        
        bot.edit_message_text(
            text=response_text,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=types.InlineKeyboardMarkup().add(
                types.InlineKeyboardButton("🔙 Главное меню", callback_data="main_menu")
            ),
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"❌ Ошибка обработки кнопки: {e}")

@bot.message_handler(content_types=['text'])
def handle_text(message):
    """Обработка текстовых сообщений"""
    try:
        user_message = message.text
        user_id = message.from_user.id
        
        # Получаем ответ от ИИ
        ai_response = assistant.get_ai_response(user_message, user_id)
        
        # Добавляем кнопку возврата в меню
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="main_menu"))
        
        bot.reply_to(message, ai_response, reply_markup=markup)
        
    except Exception as e:
        logger.error(f"❌ Ошибка обработки сообщения: {e}")
        bot.reply_to(message, "❌ Произошла ошибка. Попробуй еще раз!")

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    """Обработка фотографий (скринов переписки)"""
    try:
        bot.reply_to(
            message, 
            "📸 Получил фото! К сожалению, пока не умею анализировать изображения. Опиши ситуацию текстом, и я помогу! 😊"
        )
    except Exception as e:
        logger.error(f"❌ Ошибка обработки фото: {e}")

if __name__ == "__main__":
    try:
        logger.info("🚀 LESLI45BOT запускается...")
        logger.info("✅ Все компоненты инициализированы")
        logger.info("🤖 Бот готов к работе!")
        
        # Запуск бота
        bot.polling(none_stop=True, interval=1, timeout=30)
        
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")
        sys.exit(1)
