# Moto Bot — Telegram/MAX бот для мотоциклистов

Бот мото-сообщества Екатеринбурга. Платформы: Telegram, MAX (в разработке).

## Функции

- **SOS** — экстренные уведомления (ДТП, сломался, обсох)
- **Мотопара** — поиск пилотов и двоек, лайки
- **Полезные контакты** — магазины, сервисы, эвакуаторы
- **Мероприятия** — создание, просмотр, запись
- **Подписка** — платная подписка через ЮKassa

## Требования

- Python 3.12+
- PostgreSQL
- Redis

## Установка

```bash
cd moto_bot
uv sync  # или pip install -e .
cp .env.example .env
# Заполнить .env
```

## Настройка

1. Создать бота в [@BotFather](https://t.me/botfather)
2. Получить токен → `TELEGRAM_BOT_TOKEN`
3. PostgreSQL: создать БД `moto_bot`
4. Redis: запущен на localhost:6379

## Миграции

```bash
alembic upgrade head
```

## Запуск

```bash
PLATFORM=telegram python -m src.main
```

## Роли и права

Матрица прав Суперадмин / Админ города / Пилот / Двойка: [docs/ROLES_AND_PERMISSIONS.md](docs/ROLES_AND_PERMISSIONS.md)

Два суперадмина задаются в `.env`: `SUPERADMIN_IDS=123456789,987654321`

## Деплой на VPS

См. [deploy/README.md](deploy/README.md) — Docker Compose или systemd.

## Структура

```
src/
├── main.py
├── config.py
├── platforms/     # Telegram, MAX адаптеры
├── handlers/      # Обработчики команд
├── services/      # Бизнес-логика
├── models/        # SQLAlchemy модели
└── keyboards/
```
