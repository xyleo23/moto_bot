# Инструкция по тестированию бота

## Шаг 1. Получить токен бота

1. Открой [@BotFather](https://t.me/botfather) в Telegram
2. Отправь `/newbot`
3. Введи имя и username бота
4. Скопируй токен (формат `1234567890:ABCdefGHI...`)

## Шаг 2. Заполнить .env

Открой `moto_bot/.env` и добавь:

```
TELEGRAM_BOT_TOKEN=твой_токен_от_BotFather
SUPERADMIN_IDS=твой_telegram_user_id
```

Узнать свой user ID: напиши [@userinfobot](https://t.me/userinfobot) в Telegram.

## Шаг 3. Запустить PostgreSQL и Redis

Вариант A — через Docker:
```bash
cd moto_bot
docker-compose up -d
```

Вариант B — если уже установлены локально, убедись что работают на localhost:5432 и 6379.

## Шаг 4. Миграции БД

```bash
cd moto_bot
alembic upgrade head
```

## Шаг 5. Запуск бота

```bash
cd moto_bot
set PLATFORM=telegram
py -m src.main
```

Если Redis недоступен — бот переключится на MemoryStorage (FSM в памяти).

## Проверка

1. Открой бота в Telegram
2. Отправь `/start`
3. Выбери «Екатеринбург»
4. Выбери «Я Пилот» или «Я Двойка»
5. Заполни анкету
6. Проверь главное меню: SOS, Мотопара, Полезные контакты и т.д.

Если ты в SUPERADMIN_IDS — команда `/admin` откроет админ-панель.
