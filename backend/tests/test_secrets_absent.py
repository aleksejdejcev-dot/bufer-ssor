import os
import re
from pathlib import Path

# Directories and files to exclude from secret scanning
EXCLUDE_DIRS = {
    ".git",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "pgdata",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".cache",
}

EXCLUDE_FILES = {
    ".env",
    ".env.local",
    ".local_db.json",
    "test_secrets_absent.py",
}

# Known safe placeholders that are NOT real secrets
KNOWN_PLACEHOLDERS = {
    "<password>",
    "<пароль>",
    "[PASSWORD]",
    "[пароль]",
    "password",
    "pass",
    "secret",
    "your_password",
    "test_password",
    "***",
    "...",
    "<твой_ключ_авторизации>",
    "<токен_бота>",
    "<secret>",
    "placeholder",
    "dummy",
    "changeme",
    "change_me",
}

# Regex patterns
RE_TELEGRAM_TOKEN = re.compile(r"\b[0-9]{8,10}:[a-zA-Z0-9_-]{35}\b")
RE_GIGACHAT_B64 = re.compile(r"GIGACHAT_CREDENTIALS\s*=\s*['\"]?([A-Za-z0-9+/=]{40,})['\"]?")
RE_DB_URL_PASS = re.compile(r"postgres(?:ql)?://([^:]+):([^@]+)@")
RE_PASSWORD_ASSIGN = re.compile(
    r"(?:POSTGRES_PASSWORD|DB_PASSWORD|PASSWORD)\s*=\s*['\"]?([^\s'\"\n]+)['\"]?"
)


def is_placeholder(val: str) -> bool:
    val_clean = val.strip().lower()
    if val_clean in KNOWN_PLACEHOLDERS:
        return True
    if any(
        mark in val_clean
        for mark in ["<", ">", "[", "]", "placeholder", "xxx", "secret", "password", "pass", "$", "change_me", "test", "..."]
    ):
        return True
    if val_clean.startswith("your_") or val_clean.startswith("my_"):
        return True
    return False


def test_secrets_absent():
    """Проверяет отсутствие открытых боевых секретов, токенов и паролей в файлах репозитория."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    violations = []

    for root, dirs, files in os.walk(repo_root):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for fname in files:
            if fname in EXCLUDE_FILES or fname.endswith((".pyc", ".log", ".png", ".jpg", ".jpeg", ".ico", ".svg")):
                continue
            fpath = Path(root) / fname
            rel_path = fpath.relative_to(repo_root)

            try:
                content = fpath.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue

            for line_no, line in enumerate(content.splitlines(), start=1):
                # 1. Telegram bot token pattern
                if RE_TELEGRAM_TOKEN.search(line):
                    violations.append(f"{rel_path}:{line_no} - найден формат токена Telegram-бота")

                # 2. GigaChat credentials base64 pattern (>40 chars)
                m_giga = RE_GIGACHAT_B64.search(line)
                if m_giga:
                    val = m_giga.group(1)
                    if not is_placeholder(val):
                        violations.append(f"{rel_path}:{line_no} - найден Base64 ключ GigaChat")

                # 3. DATABASE_URL with non-placeholder password
                m_db = RE_DB_URL_PASS.search(line)
                if m_db:
                    pwd = m_db.group(2)
                    if not is_placeholder(pwd):
                        violations.append(f"{rel_path}:{line_no} - найден пароль в DATABASE_URL")

                # 4. Strings like PASSWORD=<не плейсхолдер>
                m_pwd = RE_PASSWORD_ASSIGN.search(line)
                if m_pwd:
                    pwd = m_pwd.group(1)
                    if not is_placeholder(pwd):
                        violations.append(f"{rel_path}:{line_no} - найдено присваивание пароля PASSWORD=...")

    assert not violations, "Обнаружены потенциальные секреты в репозитории:\n" + "\n".join(violations)
