#!/bin/bash
# Деплой на VPS: git pull -> миграции -> перезапуск
set -e

cd /opt/moto_bot  # или путь к проекту на VPS

echo "Pulling from GitHub..."
git pull origin main

echo "Installing dependencies..."
pip install -e . -q

echo "Running migrations..."
alembic upgrade head

echo "Restarting bot..."
systemctl restart moto-bot  # или: docker compose -f docker-compose.prod.yml up -d --build bot

echo "Done."
