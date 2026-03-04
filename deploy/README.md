# Деплой на VPS

## Автодеплой через GitHub Actions

При каждом push в `main` проект автоматически деплоится на VPS.

### Настройка секретов в GitHub

Репозиторий → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

| Секрет | Описание |
|--------|----------|
| `DEPLOY_HOST` | IP или hostname VPS (например `123.45.67.89`) |
| `DEPLOY_USER` | SSH-пользователь (например `root`) |
| `DEPLOY_SSH_KEY` | Приватный SSH-ключ (содержимое `~/.ssh/id_rsa`) |
| `DEPLOY_PATH` | *(опционально)* Путь к проекту на VPS, по умолчанию `/opt/moto_bot` |

### Первоначальная настройка на VPS

1. Клонировать репозиторий:
   ```bash
   sudo mkdir -p /opt && cd /opt
   sudo git clone https://github.com/YOUR_USER/moto_bot.git
   sudo chown -R $USER:$USER /opt/moto_bot
   ```

2. Настроить SSH-доступ по ключу (если ещё не настроен).

3. Убедиться, что `systemctl restart moto-bot` работает (юнит `moto-bot.service` создан).

---

## Ручной деплой

```bash
./deploy/deploy.sh
```

Или выполнить на VPS:

```bash
cd /opt/moto_bot
git pull origin main
pip install -e . -q
alembic upgrade head
systemctl restart moto-bot
```
