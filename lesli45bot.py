print("Hello World - сервис работает!")

import time
import os

# Показываем переменные окружения
print("=== ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ ===")
for key in ['TELEGRAM_TOKEN', 'DATABASE_URL', 'OPENAI_API_KEY']:
    value = os.getenv(key)
    if value:
        print(f"{key}: {value[:20]}...")
    else:
        print(f"{key}: НЕ НАЙДЕНА")

print("=== ДЕРЖУ СЕРВИС ЖИВЫМ ===")

# Бесконечный цикл
counter = 0
while True:
    counter += 1
    print(f"Работаю... итерация {counter}")
    time.sleep(10)
