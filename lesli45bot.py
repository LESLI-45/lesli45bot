#!/usr/bin/env python3
"""
ДИАГНОСТИКА ПОДКЛЮЧЕНИЯ К БАЗЕ ДАННЫХ
"""

import os
import logging
import sys

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def debug_database_connection():
    """Детальная диагностика DATABASE_URL"""
    
    logger.info("🔍 === ДИАГНОСТИКА DATABASE_URL ===")
    
    # Проверяем переменную
    database_url = os.getenv('DATABASE_URL')
    
    if not database_url:
        logger.error("❌ DATABASE_URL не найдена!")
        return
    
    logger.info(f"✅ DATABASE_URL найдена")
    logger.info(f"🔍 Тип: {type(database_url)}")
    logger.info(f"🔍 Длина: {len(database_url)}")
    logger.info(f"🔍 Первые 50 символов: {database_url[:50]}...")
    logger.info(f"🔍 Последние 50 символов: ...{database_url[-50:]}")
    
    # Проверяем формат
    if database_url.startswith('postgresql://'):
        logger.info("✅ URL начинается с postgresql://")
    else:
        logger.error(f"❌ URL НЕ начинается с postgresql://! Начинается с: {database_url[:20]}")
    
    # Проверяем на лишние символы
    if 'Name:' in database_url:
        logger.error("❌ ПРОБЛЕМА: В URL есть 'Name:' - Railway добавляет префикс!")
        logger.info("🔧 Решение: Убери 'Name:' из начала строки")
    
    # Проверяем специальные символы
    special_chars = ['@', ':', '/', '?', '&', '=']
    for char in special_chars:
        count = database_url.count(char)
        logger.info(f"🔍 Символ '{char}': {count} раз")
    
    # Пытаемся разобрать URL
    try:
        parts = database_url.replace('postgresql://', '').split('@')
        if len(parts) == 2:
            user_pass = parts[0]
            host_db = parts[1]
            logger.info(f"✅ URL успешно разобран:")
            logger.info(f"  👤 Пользователь:пароль: {user_pass[:20]}...")
            logger.info(f"  🏠 Хост:база: {host_db}")
        else:
            logger.error("❌ Не удалось разобрать URL на части")
    except Exception as e:
        logger.error(f"❌ Ошибка разбора URL: {e}")
    
    # Тестируем подключение
    logger.info("🔧 Тестирую подключение...")
    try:
        import psycopg2
        conn = psycopg2.connect(database_url)
        logger.info("✅ ПОДКЛЮЧЕНИЕ УСПЕШНО!")
        conn.close()
    except Exception as e:
        logger.error(f"❌ ОШИБКА ПОДКЛЮЧЕНИЯ: {e}")
        
        # Дополнительная диагностика
        if "missing" in str(e) and "Name:" in str(e):
            logger.error("🚨 ТОЧНАЯ ПРОБЛЕМА: Railway добавляет 'Name:' к URL!")
            logger.info("🔧 РЕШЕНИЕ: Используй другое имя переменной или убери префикс")

if __name__ == "__main__":
    debug_database_connection()
    
    # Держим скрипт живым
    import time
    logger.info("💤 Скрипт завершен, держу контейнер живым...")
    while True:
        time.sleep(30)
