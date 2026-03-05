#!/bin/bash
# Первоначальная настройка проекта на VPS (выполнить один раз)
set -e

PROJECT_DIR="${1:-/opt/moto_bot}"
cd "$PROJECT_DIR"

echo "=== Setup moto_bot in $PROJECT_DIR ==="

# 1. Создать виртуальное окружение
if [ ! -d "venv" ]; then
    echo "Creating venv..."
    python3 -m venv venv
fi
source venv/bin/activate

# 2. Установить зависимости
echo "Installing dependencies..."
pip install -e .

# 3. Миграции
echo "Running migrations..."
alembic upgrade head

# 4. Создать .env если нет
if [ ! -f ".env" ]; then
    echo "WARNING: .env not found! Copy from .env.example and fill:"
    echo "  cp .env.example .env"
    echo "  nano .env"
fi

# 5. Systemd unit
echo ""
echo "=== Systemd unit ==="
echo "Copy and enable:"
echo "  sudo cp deploy/moto-bot.service /etc/systemd/system/"
echo "  sudo systemctl daemon-reload"
echo "  sudo systemctl enable moto-bot"
echo "  sudo systemctl start moto-bot"
echo ""
echo "Edit /etc/systemd/system/moto-bot.service if User/WorkingDirectory differ."
