# Деплой на VPS

## Вариант 1: Docker Compose (рекомендуется)

### На VPS

```bash
# Клонировать репо
git clone https://github.com/YOUR_USER/moto_bot.git /opt/moto_bot
cd /opt/moto_bot

# Создать .env (не в гите — заполнить токены)
cp .env.example .env
nano .env
# Обязательно: TELEGRAM_BOT_TOKEN, SUPERADMIN_IDS, POSTGRES_PASSWORD

# Запустить
docker compose -f docker-compose.prod.yml up -d

# Миграции выполняются автоматически при старте бота (entrypoint.sh)

# Обновление после git pull
git pull && docker compose -f docker-compose.prod.yml up -d --build bot
```

### .env на сервере

```
TELEGRAM_BOT_TOKEN=xxx
SUPERADMIN_IDS=123456789
POSTGRES_PASSWORD=надёжный_пароль
```

---

## Вариант 2: Без Docker (systemd)

### Подготовка VPS (Ubuntu/Debian)

```bash
sudo apt update
sudo apt install -y python3.12 python3-pip python3-venv postgresql redis-server

# PostgreSQL: создать БД
sudo -u postgres createdb moto_bot
# (при необходимости создать пользователя)

# Redis уже работает как сервис
```

### Установка бота

```bash
sudo mkdir -p /opt/moto_bot
sudo chown $USER:$USER /opt/moto_bot
cd /opt/moto_bot

git clone https://github.com/YOUR_USER/moto_bot.git .

python3 -m venv .venv
source .venv/bin/activate  # или .venv\Scripts\activate на Windows
pip install -e .

cp .env.example .env
nano .env  # заполнить TELEGRAM_BOT_TOKEN и т.д.
```

### DATABASE_URL (PostgreSQL)

```
DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@localhost:5432/moto_bot
```

### systemd

```bash
sudo cp deploy/moto-bot.service /etc/systemd/system/
# Поправить пути в .service если нужно
sudo systemctl daemon-reload
sudo systemctl enable moto-bot
sudo systemctl start moto-bot
```

### Обновление

```bash
cd /opt/moto_bot
./deploy/deploy.sh
# или вручную: git pull && alembic upgrade head && sudo systemctl restart moto-bot
```
