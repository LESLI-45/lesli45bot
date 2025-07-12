#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Безопасная конфигурация для LESLI45BOT
Все API ключи загружаются из переменных окружения
"""

import os
from dotenv import load_dotenv

# Загружаем переменные из .env файла (для локальной разработки)
load_dotenv()

class Config:
    def __init__(self):
        # ✅ БЕЗОПАСНО: API ключи из переменных окружения
        self.TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
        self.OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
        
        # База данных (Railway автоматически создает PostgreSQL)
        self.DATABASE_URL = os.getenv('DATABASE_URL')
        if self.DATABASE_URL and self.DATABASE_URL.startswith('postgres://'):
            # Railway требует postgresql:// вместо postgres://
            self.DATABASE_URL = self.DATABASE_URL.replace('postgres://', 'postgresql://', 1)
        
        # Локальная SQLite для разработки (если нет PostgreSQL)
        self.DATABASE_PATH = os.getenv('DATABASE_PATH', 'lesli_bot.db')
        
        # OpenAI настройки
        self.MAX_CONTEXT_LENGTH = int(os.getenv('MAX_CONTEXT_LENGTH', '4000'))
        self.MODEL = os.getenv('OPENAI_MODEL', 'gpt-4o')
        
        # Railway специфичные настройки
        self.PORT = int(os.getenv('PORT', '8000'))
        self.RAILWAY_ENVIRONMENT = os.getenv('RAILWAY_ENVIRONMENT_NAME')
        
        # Проверяем обязательные переменные
        if not self.TELEGRAM_TOKEN:
            raise ValueError("❌ TELEGRAM_TOKEN не найден в переменных окружения!")
        if not self.OPENAI_API_KEY:
            raise ValueError("❌ OPENAI_API_KEY не найден в переменных окружения!")
        
        print("✅ Конфигурация загружена успешно")
        
    @property
    def is_production(self):
        """Проверка, запущено ли в продакшене Railway"""
        return self.RAILWAY_ENVIRONMENT == 'production'
    
    @property
    def use_postgresql(self):
        """Использовать ли PostgreSQL вместо SQLite"""
        return bool(self.DATABASE_URL)

# Создаем глобальный объект конфигурации
config = Config()
