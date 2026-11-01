"""
Тест проверки гарантии: боевой код вне tests/ не производит запись на диск (Этап 3.8 / Task 2).
Запрещены: write_text, write_bytes, json.dump (в файл), pickle, shelve, open(..., 'w'/'a'/'x').
"""

import ast
import re
from pathlib import Path

ALLOWED_DIRECTORIES = {
    "tests",
    "backend/tests",
    "scripts",
    "db/migrations",
}

# Регулярные выражения для поиска операций записи на диск
RE_WRITE_TEXT = re.compile(r"\bwrite_text\s*\(")
RE_WRITE_BYTES = re.compile(r"\bwrite_bytes\s*\(")
RE_JSON_DUMP = re.compile(r"\bjson\.dump\s*\(")  # именно json.dump, а не json.dumps
RE_PICKLE = re.compile(r"\bpickle\.(?:dump|Pickler)\s*\(")
RE_SHELVE = re.compile(r"\bshelve\.open\s*\(")
RE_OPEN_WRITE = re.compile(r"\bopen\s*\([^)]*['\"][wax\+][^'\"]*['\"]")


def test_production_code_does_not_write_to_disk():
    """
    Проверяет, что боевой код бэкенда (вне разрешенных директорий)
    не содержит вызовов записи на диск.

    Разрешенные места (явно перечислены):
    - backend/tests/ (и любые тестовые директории)
    - scripts/ (административные скрипты)
    - db/migrations/ (миграции SQL)
    """
    repo_root = Path(__file__).resolve().parent.parent.parent
    backend_dir = repo_root / "backend"

    violations = []

    for py_file in backend_dir.rglob("*.py"):
        rel_path = py_file.relative_to(repo_root)

        # Пропускаем разрешенные директории
        if any(part in ("tests", ".venv", "__pycache__") for part in rel_path.parts):
            continue

        content = py_file.read_text(encoding="utf-8")

        for line_no, line in enumerate(content.splitlines(), start=1):
            stripped = line.strip()
            # Пропускаем комментарии
            if stripped.startswith("#"):
                continue

            if RE_WRITE_TEXT.search(line):
                violations.append(f"{rel_path}:{line_no} - обнаружен вызов .write_text()")
            if RE_WRITE_BYTES.search(line):
                violations.append(f"{rel_path}:{line_no} - обнаружен вызов .write_bytes()")
            if RE_JSON_DUMP.search(line):
                violations.append(f"{rel_path}:{line_no} - обнаружен вызов json.dump() (запись в файл)")
            if RE_PICKLE.search(line):
                violations.append(f"{rel_path}:{line_no} - обнаружен вызов pickle.dump()")
            if RE_SHELVE.search(line):
                violations.append(f"{rel_path}:{line_no} - обнаружен вызов shelve.open()")
            if RE_OPEN_WRITE.search(line):
                violations.append(f"{rel_path}:{line_no} - обнаружен open() в режиме записи/дозаписи")

    assert not violations, (
        f"Обнаружены операции записи на диск в боевом коде:\n"
        + "\n".join(violations)
        + f"\nРазрешенные директории: {sorted(list(ALLOWED_DIRECTORIES))}"
    )
