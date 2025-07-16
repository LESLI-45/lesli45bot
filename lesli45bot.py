#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LESLI45BOT - МИНИМАЛЬНАЯ ВЕРСИЯ
Гарантированно работает везде!
"""

import logging
import os
import sys
import requests
import time

# Telegram
import telebot
from telebot import types

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Получаем токен
TOKEN = os.getenv('TELEGRAM_TOKEN', '7709233981:AAG87qbebbUt4q4SEx1epBvWySlTDAr8zaI')

if not TOKEN:
    logger.error("❌ TELEGRAM_TOKEN не найден!")
    sys.exit(1)

# Принудительное удаление webhook
def force_delete_webhook():
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/deleteWebhook"
        requests.get(url, timeout=5)
        logger.info("✅ Webhook удален")
    except:
        logger.info("⚠️ Не удалось удалить webhook (не критично)")

# Инициализация бота
bot = telebot.TeleBot(TOKEN)
logger.info("🤖 Бот инициализирован")

@bot.message_handler(commands=['start'])
def start_command(message):
    """Обработка /start"""
    user_name = message.from_user.first_name or "друг"
    
    text = f"""🔥 Привет, {user_name}!

Я LESLI45BOT - твой ассистент по соблазнению!

🎯 Что умею:
• Анализ переписки
• Советы по флирту  
• Первые сообщения
• Стили соблазнения

Просто напиши мне свою ситуацию! 💪"""
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("💬 Анализ переписки", callback_data="perepiska"))
    markup.add(types.InlineKeyboardButton("📱 Первое сообщение", callback_data="pervoe"))
    markup.add(types.InlineKeyboardButton("🔥 Флирт", callback_data="flirt"))
    
    bot.send_message(message.chat.id, text, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    """Обработка кнопок"""
    responses = {
        "perepiska": "💬 **Анализ переписки**\n\nОпиши как она отвечает:\n• Быстро/медленно?\n• Длинные/короткие сообщения?\n• Задает вопросы?\n• Использует эмодзи?\n\nИ я дам анализ её интереса!",
        
        "pervoe": "📱 **Первое сообщение**\n\nРасскажи:\n• Где познакомились?\n• Что о ней знаешь?\n• Что её зацепило?\n\nСоставлю идеальное первое сообщение!",
        
        "flirt": "🔥 **Флирт и разогрев**\n\nОпиши ситуацию:\n• На какой стадии общения?\n• Как она реагирует?\n• Что уже пробовал?\n\nДам техники эскалации!"
    }
    
    response = responses.get(call.data, "🤖 Опиши свою ситуацию!")
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="start"))
    
    bot.edit_message_text(
        response, 
        call.message.chat.id, 
        call.message.message_id,
        reply_markup=markup,
        parse_mode='Markdown'
    )

@bot.message_handler(content_types=['text'])
def handle_text(message):
    """Обработка текста"""
    responses = [
        "🎯 **Совет от Лесли:**\n\nВ любой ситуации помни:\n• Уверенность = привлекательность\n• Эмоции важнее логики\n• Недоступность повышает ценность\n• Действуй, не думай слишком много!",
        
        "💡 **Золотое правило:**\n\nОна должна инвестировать в общение больше тебя:\n• Пусть она больше пишет\n• Задает вопросы\n• Инициирует встречи\n\nТогда её интерес будет расти! 🚀",
        
        "🔥 **Техника качелей:**\n\nЧередуй:\n• Тепло → Прохлада\n• Интерес → Безразличие\n• Близость → Дистанция\n\nОна будет думать о тебе 24/7! 💭"
    ]
    
    import random
    response = random.choice(responses)
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🎯 Главное меню", callback_data="start"))
    
    bot.reply_to(message, response, reply_markup=markup, parse_mode='Markdown')

if __name__ == "__main__":
    try:
        logger.info("🚀 LESLI45BOT запускается...")
        
        # ПРИНУДИТЕЛЬНО удаляем webhook
        force_delete_webhook()
        time.sleep(2)
        
        logger.info("🤖 Запуск polling...")
        
        # Запуск с обработкой ошибок
        bot.polling(none_stop=True, interval=1, timeout=20)
        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        sys.exit(1)
