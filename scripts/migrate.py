#!/usr/bin/env python3
"""
scripts/migrate.py
Идемпотентный раннер миграций базы данных PostgreSQL для проекта «Буфер Ссор».
Использует таблицу schema_migrations для фиксации примененных файлов миграций.
Каждая миграция выполняется в отдельной транзакции.
"""

import os
import sys
import asyncio
import re
import argparse
from pathlib import Path
import asyncpg


def mask_db_url(url: str) -> str:
    """Маскирует пароль в строке подключения к БД."""
    if not url:
        return ""
    return re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", url)


async def run_migrations(db_url: str, migrations_dir: Path) -> int:
    masked_url = mask_db_url(db_url)
    print(f"🔄 Подключение к базе данных: {masked_url}")

    try:
        conn = await asyncpg.connect(db_url)
    except Exception as e:
        print(f"❌ Не удалось подключиться к базе данных ({masked_url}): {e}", file=sys.stderr)
        return 1

    try:
        # Создаем таблицу schema_migrations, если еще не создана
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version text PRIMARY KEY,
                applied_at timestamptz NOT NULL DEFAULT now()
            );
        """)

        # Получаем список уже примененных миграций
        applied_rows = await conn.fetch("SELECT version FROM schema_migrations;")
        applied_versions = {r["version"] for r in applied_rows}

        # Находим и сортируем все SQL файлы миграций
        sql_files = sorted(migrations_dir.glob("*.sql"))
        if not sql_files:
            print("⚠️ Файлы миграций не найдены в директории:", migrations_dir)
            return 0

        applied_count = 0
        for sql_path in sql_files:
            version_name = sql_path.name
            if version_name in applied_versions:
                print(f"  [ПРОПУСК] {version_name} (уже применена)")
                continue

            print(f"  [ПРИМЕНЕНИЕ] {version_name} ...", end=" ", flush=True)
            sql_content = sql_path.read_text(encoding="utf-8")

            try:
                async with conn.transaction():
                    await conn.execute(sql_content)
                    await conn.execute(
                        "INSERT INTO schema_migrations (version) VALUES ($1);",
                        version_name,
                    )
                print("✅ УСПЕШНО")
                applied_count += 1
            except Exception as err:
                print("❌ ОШИБКА")
                print(f"Ошибка при выполнении миграции {version_name}:\n{err}", file=sys.stderr)
                return 1

        print(f"🎉 Миграции завершены успешно. Новых применено: {applied_count}")
        return 0

    finally:
        await conn.close()


def main():
    parser = argparse.ArgumentParser(description="PostgreSQL migration runner for Buffer Ssor")
    parser.add_argument("--database-url", default=None, help="Database connection URL")
    parser.add_argument(
        "--dir",
        default=str(Path(__file__).resolve().parent.parent / "db" / "migrations"),
        help="Path to migrations directory",
    )
    args = parser.parse_args()

    db_url = args.database_url or os.environ.get("DATABASE_URL")
    if not db_url:
        print("❌ Ошибка: DATABASE_URL не задан (укажите через аргумент --database-url или переменную окружения).", file=sys.stderr)
        sys.exit(1)

    migrations_dir = Path(args.dir)
    if not migrations_dir.is_dir():
        print(f"❌ Ошибка: директория миграций не существует: {migrations_dir}", file=sys.stderr)
        sys.exit(1)

    exit_code = asyncio.run(run_migrations(db_url, migrations_dir))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
