#!/usr/bin/env bash
# ==============================================================================
# scripts/db_down.sh
# Остановка локального контейнера PostgreSQL.
# ==============================================================================
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

if [ -d "$HOME/.docker/bin" ]; then
    export PATH="$HOME/.docker/bin:$PATH"
fi

echo "🛑 Остановка PostgreSQL контейнера..."
docker compose down
echo "✅ Контейнеры остановлены."
