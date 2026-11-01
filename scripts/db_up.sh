#!/usr/bin/env bash
# ==============================================================================
# scripts/db_up.sh
# Запуск локальной базы данных PostgreSQL в Docker и применение миграций.
# ==============================================================================
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

if [ -d "$HOME/.docker/bin" ]; then
    export PATH="$HOME/.docker/bin:$PATH"
fi

if ! command -v docker &> /dev/null; then
    echo "❌ Ошибка: docker не найден в системе." >&2
    exit 1
fi

if ! docker info &> /dev/null; then
    echo "❌ Ошибка: демон Docker не запущен." >&2
    exit 1
fi

if [ -f ".venv/bin/activate" ]; then
    # shellcheck disable=SC1091
    source ".venv/bin/activate"
fi

if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
fi

export POSTGRES_USER="${POSTGRES_USER:-buffer_admin}"
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-buffer_dev_pass}"
export POSTGRES_DB="${POSTGRES_DB:-buffer_ssor}"
export MIGRATOR_PASSWORD="${MIGRATOR_PASSWORD:-migrator_dev_pass}"
export APP_USER_PASSWORD="${APP_USER_PASSWORD:-app_user_dev_pass}"

echo "🚀 Запуск PostgreSQL в Docker Compose..."
docker compose up -d postgres

echo "⏳ Ожидание готовности PostgreSQL..."
for i in {1..30}; do
    if docker compose exec -T postgres pg_isready -U "${POSTGRES_USER:-buffer_admin}" -d "${POSTGRES_DB:-buffer_ssor}" &> /dev/null; then
        echo "✅ PostgreSQL готов к приему соединений."
        break
    fi
    sleep 1
    if [ "$i" -eq 30 ]; then
        echo "❌ Ошибка: PostgreSQL не запустился за 30 секунд." >&2
        exit 1
    fi
done

# Применяем миграции к основной и тестовой БД
ADMIN_USER="${POSTGRES_USER:-buffer_admin}"
ADMIN_PASS="${POSTGRES_PASSWORD:-buffer_dev_pass}"
DB_MAIN="${POSTGRES_DB:-buffer_ssor}"
DB_TEST="${POSTGRES_DB:-buffer_ssor}_test"

echo "📦 Применение миграций к $DB_MAIN..."
python3 scripts/migrate.py --database-url "postgresql://${ADMIN_USER}:${ADMIN_PASS}@127.0.0.1:5432/${DB_MAIN}"

echo "📦 Применение миграций к $DB_TEST..."
python3 scripts/migrate.py --database-url "postgresql://${ADMIN_USER}:${ADMIN_PASS}@127.0.0.1:5432/${DB_TEST}"

echo "🎉 База данных PostgreSQL готова к работе!"
