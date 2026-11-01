#!/usr/bin/env bash
# ==============================================================================
# scripts/db_reset.sh
# Сброс и перезапуск локальной базы данных с удалением тома pgdata/.
# ==============================================================================
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

if [ -d "$HOME/.docker/bin" ]; then
    export PATH="$HOME/.docker/bin:$PATH"
fi

echo "⚠️ Выполняется сброс базы данных..."
docker compose down -v
rm -rf pgdata/

echo "🔄 Повторный запуск и инициализация..."
./scripts/db_up.sh
