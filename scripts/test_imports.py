"""Проверка импортов и конфигурации без запуска бота."""
import sys

def main():
    errors = []
    print("1. Проверка импортов...")
    try:
        from src.config import get_settings
        print("   OK: config")
    except Exception as e:
        errors.append(f"config: {e}")
        print(f"   FAIL: config - {e}")

    try:
        from src.models.base import init_db
        from src.models import City, User
        print("   OK: models")
    except Exception as e:
        errors.append(f"models: {e}")
        print(f"   FAIL: models - {e}")

    try:
        from src.handlers import start, registration, sos, motopair, events, contacts, profile, about, admin
        print("   OK: handlers")
    except Exception as e:
        errors.append(f"handlers: {e}")
        print(f"   FAIL: handlers - {e}")

    print("\n2. Проверка конфигурации...")
    try:
        s = get_settings()
        if not s.telegram_bot_token:
            print("   WARN: TELEGRAM_BOT_TOKEN не задан (добавь в .env)")
        else:
            print("   OK: TELEGRAM_BOT_TOKEN задан")
        print(f"   DATABASE_URL: {s.database_url[:50]}...")
        print(f"   REDIS_URL: {s.redis_url}")
    except Exception as e:
        errors.append(f"settings: {e}")
        print(f"   FAIL: {e}")

    if errors:
        print("\n--- Ошибки ---")
        for e in errors:
            print(e)
        sys.exit(1)
    print("\n--- Все проверки пройдены ---")

if __name__ == "__main__":
    main()
