#!/usr/bin/env python3
"""
ЭКСТРЕННАЯ ВЕРСИЯ LESLI45BOT
Минимальный код для проверки
"""

import os
import sys
import logging

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def main():
    logger.info("🚀 ЭКСТРЕННАЯ ВЕРСИЯ ЗАПУСКАЕТСЯ...")
    
    # Проверка переменных
    token = os.getenv('TELEGRAM_TOKEN')
    if not token:
        logger.error("❌ TELEGRAM_TOKEN не найден!")
        sys.exit(1)
    
    logger.info(f"✅ Токен найден: {token[:10]}...")
    
    try:
        import telebot
        logger.info("✅ Библиотека telebot импортирована")
        
        bot = telebot.TeleBot(token)
        logger.info("✅ Бот создан успешно")
        
        @bot.message_handler(commands=['start'])
        def start_handler(message):
            bot.reply_to(message, "🚨 Экстренная версия работает!")
            logger.info(f"✅ Получено сообщение от {message.from_user.first_name}")
        
        @bot.message_handler(func=lambda message: True)
        def echo_handler(message):
            bot.reply_to(message, f"Эхо: {message.text}")
        
        logger.info("✅ Обработчики зарегистрированы")
        logger.info("🤖 Запускаю polling...")
        
        bot.polling(none_stop=True)
        
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")
        sys.exit(1)

if __name__ == "__main__":  # ✅ ИСПРАВЛЕНО!
    main()
