#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LESLI45BOT - ИСПРАВЛЕННАЯ ВЕРСИЯ
Использует POSTGRES_URL вместо DATABASE_URL
"""

import logging
import os
import sys
import psycopg2
from psycopg2.extras import RealDictCursor

# Telegram Bot
import telebot
from telebot import types

# OpenAI
from openai import OpenAI

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# Конфигурация
class Config:
    TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
    OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
    POSTGRES_URL = os.getenv('POSTGRES_URL')  # ИЗМЕНЕНО!
    
    def __init__(self):
        if not self.TELEGRAM_TOKEN:
            logger.error("❌ TELEGRAM_TOKEN не найден!")
            sys.exit(1)
        if not self.OPENAI_API_KEY:
            logger.error("❌ OPENAI_API_KEY не найден!")
            sys.exit(1)

config = Config()

# Инициализация бота
bot = telebot.TeleBot(config.TELEGRAM_TOKEN)

class LesliAssistant:
    """Основной класс ассистента"""
    
    def __init__(self):
        self.setup_database()
        self.openai_client = OpenAI(api_key=config.OPENAI_API_KEY)
        logger.info("✅ Ассистент инициализирован")

    def setup_database(self):
        """Настройка подключения к базе данных"""
        try:
            if config.POSTGRES_URL:  # ИЗМЕНЕНО!
                logger.info("🔗 Подключаюсь к PostgreSQL...")
                logger.info(f"🔍 POSTGRES_URL длина: {len(config.POSTGRES_URL)}")
                logger.info(f"🔍 Начинается с: {config.POSTGRES_URL[:30]}...")
                
                self.db = psycopg2.connect(config.POSTGRES_URL)  # ИЗМЕНЕНО!
                self.db.autocommit = True
                logger.info("✅ Подключение к PostgreSQL успешно!")
                self.create_tables()
            else:
                logger.error("❌ POSTGRES_URL не найден!")
                sys.exit(1)
        except Exception as e:
            logger.error(f"❌ Ошибка подключения к базе: {e}")
            sys.exit(1)

    def create_tables(self):
        """Создание таблиц"""
        try:
            with self.db.cursor() as cursor:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS knowledge_base (
                        id SERIAL PRIMARY KEY,
                        book_name VARCHAR(255),
                        content TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                logger.info("✅ Таблицы созданы")
        except Exception as e:
            logger.error(f"❌ Ошибка создания таблиц: {e}")

    def get_knowledge_count(self):
        """Получить количество записей в базе"""
        try:
            with self.db.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM knowledge_base")
                result = cursor.fetchone()
                return result[0] if result else 0
        except Exception as e:
            logger.error(f"Ошибка подсчета записей: {e}")
            return 0

    def search_knowledge(self, query):
        """Поиск в базе знаний"""
        try:
            with self.db.cursor() as cursor:
                cursor.execute("""
                    SELECT content FROM knowledge_base 
                    WHERE content ILIKE %s 
                    LIMIT 3
                """, (f'%{query}%',))
                
                results = cursor.fetchall()
                return [row[0] for row in results]
        except Exception as e:
            logger.error(f"Ошибка поиска: {e}")
            return []

    def get_ai_response(self, user_message, user_id=None):
        """Получение ответа от OpenAI"""
        try:
            # Ищем в базе знаний
            knowledge = self.search_knowledge(user_message)
            
            # Формируем системный промпт
            system_prompt = """Ты LESLI45BOT - персональный ассистент по соблазнению на основе методик Алекса Лесли.

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

            if knowledge:
                system_prompt += f"\n\nИз базы знаний Лесли:\n{knowledge[0][:500]}..."

            response = self.openai_client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message}
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
    """Создание главного меню"""
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

📚 **База знаний:** {assistant.get_knowledge_count()} записей из книг Лесли
🤖 **ИИ:** GPT-4o для персональных советов

Используй кнопки ниже для быстрого доступа к функциям! 👇"""
    
    bot.send_message(
        message.chat.id,
        welcome_text,
        reply_markup=create_main_menu(),
        parse_mode='Markdown'
    )

@bot.message_handler(commands=['debug'])
def debug_command(message):
    """Диагностика базы знаний"""
    count = assistant.get_knowledge_count()
    debug_text = f"""🔍 **ДИАГНОСТИКА БАЗЫ ЗНАНИЙ**

📊 **Статистика:**
• Записей в базе: {count}
• Статус: {'✅ Готова' if count > 0 else '❌ Пуста'}

🔧 **Система:**
• База данных: PostgreSQL (Render)
• Подключение: POSTGRES_URL
• OpenAI: GPT-4o
• Библиотека: pyTelegramBotAPI"""
    
    bot.reply_to(message, debug_text, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    """Обработка нажатий кнопок"""
    try:
        if call.data == "menu_back":
            bot.edit_message_text(
                "🔥 **LESLI45BOT - Главное меню**\n\nВыбери раздел для получения экспертных советов по соблазнению! 👇",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=create_main_menu(),
                parse_mode='Markdown'
            )
            return

        menu_type = call.data.replace("menu_", "")
        
        # Простые ответы для каждой кнопки
        responses = {
            "situacia": "🎯 **Конкретная ситуация**\n\nОпиши свою ситуацию с девушкой максимально подробно, и я дам конкретные советы как действовать дальше!",
            "perepiska": "💬 **Анализ переписки**\n\nПришли скрин переписки или опиши диалог. Проанализирую её интерес и подскажу что писать дальше!",
            "pervoe": "📱 **Первое сообщение**\n\nРасскажи где познакомился с девушкой и что о ней знаешь. Составлю идеальное первое сообщение!",
            "razogrev": "🔥 **Разогрев и флирт**\n\nОпиши на какой стадии общения вы находитесь. Дам техники разогрева и эскалации!",
            "zvonki": "📞 **Звонки и свидания**\n\nРасскажи о ситуации с девушкой. Подскажу как правильно назначать встречи и проводить свидания!",
            "sos": "🆘 **SOS Сигналы**\n\nЭкстренная ситуация? Быстро опиши проблему - дам срочный совет из арсенала Лесли!"
        }
        
        response_text = responses.get(menu_type, "🤖 Опиши свою ситуацию, и я помогу!")
        
        bot.edit_message_text(
            text=response_text,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=types.InlineKeyboardMarkup().add(
                types.InlineKeyboardButton("🔙 Главное меню", callback_data="menu_back")
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
        markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="menu_back"))
        
        bot.reply_to(message, ai_response, reply_markup=markup, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"❌ Ошибка обработки сообщения: {e}")
        bot.reply_to(message, "❌ Произошла ошибка. Попробуй еще раз!")

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    """Обработка фотографий"""
    response = """📸 **Получил фото!**

Пока не умею анализировать изображения, но могу дать отличные советы по анализу переписки!

🔥 **Опиши текстом:**
• Что она пишет
• Как быстро отвечает  
• Какие эмодзи использует
• Задает ли вопросы

И получишь экспертный анализ! 💪"""
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("💬 Анализ переписки", callback_data="menu_perepiska"))
    
    bot.reply_to(message, response, reply_markup=markup, parse_mode='Markdown')

if __name__ == "__main__":
    try:
        logger.info("🚀 LESLI45BOT запускается...")
        logger.info("📚 База знаний подключена")
        logger.info("✅ Все компоненты инициализированы")
        logger.info("🤖 Бот готов к работе!")
        
        # Запуск бота
        bot.polling(none_stop=True, interval=1, timeout=30)
        
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")
        sys.exit(1)
