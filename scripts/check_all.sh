#!/usr/bin/env bash
# ==============================================================================
# scripts/check_all.sh
# Единый скрипт автоматизированной проверки качества и безопасности проекта.
# ==============================================================================
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

# Ensure docker CLI is in PATH if installed in user's ~/.docker/bin
if [ -d "$HOME/.docker/bin" ]; then
    export PATH="$HOME/.docker/bin:$PATH"
fi

IS_FRESH=false
for arg in "$@"; do
    if [ "$arg" = "--fresh" ]; then
        IS_FRESH=true
    fi
done

# Проверка доступности Docker для PostgreSQL тестов (D7)
if ! command -v docker &> /dev/null || ! docker info &> /dev/null; then
    echo "❌ Ошибка: Docker недоступен в системе. Запуск тестов PostgreSQL невозможен." >&2
    exit 1
fi

echo "🐳 Проверка и запуск локального контейнера PostgreSQL..."
./scripts/db_up.sh

export DATABASE_URL_TEST="postgresql://buffer_admin:buffer_dev_pass@127.0.0.1:5432/buffer_ssor_test"
export DATABASE_URL_APP_TEST="postgresql://app_user:app_user_dev_pass@127.0.0.1:5432/buffer_ssor_test"

if [ "$IS_FRESH" = true ]; then
    echo "========================================================================"
    echo "▶ Режим --fresh: создание временного изолированного окружения (Python 3.12)"
    echo "========================================================================"
    TMP_DIR=$(mktemp -d)
    cleanup() {
        echo "🧹 Очистка временного окружения ($TMP_DIR)..."
        rm -rf "$TMP_DIR"
    }
    trap cleanup EXIT INT TERM
    python3.12 -m venv "$TMP_DIR"
    source "$TMP_DIR/bin/activate"
    pip install --upgrade pip --quiet
    pip install -r backend/requirements.txt -r requirements-dev.txt --quiet
    
    echo "Проверка импортов backend зависимостей..."
    python -c "
import fastapi
import uvicorn
import pydantic
import pydantic_settings
import aiogram
import cryptography
import python_multipart
import gigachat
import pymorphy3
import snowballstemmer
import asyncpg
import httpx
print('✅ Все обязательные зависимости успешно импортированы')
"
else
    if [ -f ".venv/bin/activate" ]; then
        # shellcheck disable=SC1091
        source ".venv/bin/activate"
    fi
fi

PYTHON_VER=$(python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
if [ "$PYTHON_VER" != "3.12" ]; then
    echo "❌ Ошибка: ожидается Python 3.12, используется $PYTHON_VER"
    exit 1
fi
echo "🐍 Python версия: $PYTHON_VER"

echo ""
echo "========================================================================"
echo "▶ 1. Проверка линтером (Ruff)"
echo "========================================================================"
ruff check backend/
echo "✅ Ruff: проверка пройдена"

echo ""
echo "========================================================================"
echo "▶ 2. Статическая типизация (Mypy)"
echo "========================================================================"
if command -v mypy &> /dev/null; then
    mypy backend/
    echo "✅ Mypy: проверка типов пройдена"
else
    echo "❌ Ошибка: mypy не установлен"
    exit 1
fi

echo ""
echo "========================================================================"
echo "▶ 3. Тестовый набор (Pytest)"
echo "========================================================================"
pytest -v
echo "✅ Pytest: все тесты успешно пройдены"

echo ""
echo "========================================================================"
echo "▶ 4. Сканирование секретов (Gitleaks)"
echo "========================================================================"
if command -v gitleaks &> /dev/null; then
    DIR_OUTPUT=$(gitleaks dir . --redact -v 2>&1 || gitleaks detect --no-git --redact -v 2>&1)
    echo "$DIR_OUTPUT"
    DIR_BYTES=$(echo "$DIR_OUTPUT" | grep -oE "scanned ~[0-9]+ bytes" | grep -oE "[0-9]+" || echo "0")
    if [ "$DIR_BYTES" -le 0 ]; then
        echo "❌ Ошибка Gitleaks: сканирование директорий не обработало байты (scanned: $DIR_BYTES)"
        exit 1
    fi
    echo "✅ Gitleaks (dir): просканировано ~${DIR_BYTES} байт, утечек не обнаружено"

    if git rev-parse --verify HEAD >/dev/null 2>&1; then
        GIT_OUTPUT=$(gitleaks git . --redact -v 2>&1)
        echo "$GIT_OUTPUT"
        GIT_BYTES=$(echo "$GIT_OUTPUT" | grep -oE "scanned ~[0-9]+ bytes" | grep -oE "[0-9]+" || echo "0")
        if [ "$GIT_BYTES" -le 0 ]; then
            echo "❌ Ошибка Gitleaks: сканирование git не обработало байты (scanned: $GIT_BYTES)"
            exit 1
        fi
        echo "✅ Gitleaks (git): просканировано ~${GIT_BYTES} байт, утечек не обнаружено"
    fi
else
    python3 scripts/check_secrets_no_gitleaks.py
fi

echo ""
echo "========================================================================"
echo "▶ 5. Проверка отсутствия запрещённых юридических утверждений (Grep)"
echo "========================================================================"
# Ищем формулировки о '152-ФЗ', 'гарантиях' и 'хранении в РФ' во всех файлах кроме тестов
FORBIDDEN_FOUND=$(grep -rnEi "152-фз|строгом соответствии|хранится в рф|полностью защищ|гарантирует" \
    --exclude="test_legal_claims.py" \
    --exclude="LEGAL_CHECKLIST.md" \
    README.md backend/ frontend/src/ docs/ || true)

if [ -n "$FORBIDDEN_FOUND" ]; then
    echo "❌ Ошибка: найдены запрещённые формулировки:"
    echo "$FORBIDDEN_FOUND"
    exit 1
fi
echo "✅ Запрещённых формулировок не обнаружено"

echo ""
echo "========================================================================"
echo "▶ 6. Сборка фронтенда (Frontend build)"
echo "========================================================================"
if [ -d "frontend" ]; then
    echo "📦 Проверка и установка зависимостей фронтенда..."
    (cd frontend && (npm ci --prefer-offline 2>/dev/null || npm install --quiet))
    echo "🔨 Сборка Vite..."
    (cd frontend && npm run build)
    echo "✅ Frontend: сборка успешно завершена"
fi

echo ""
echo "========================================================================"
echo "🎉 ВСЕ ПРОВЕРКИ УСПЕШНО ПРОЙДЕНЫ (scripts/check_all.sh)"
echo "========================================================================"
