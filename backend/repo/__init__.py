"""
Модуль репозитория: выбор и предоставление активной реализации хранилища данных.
В зависимости от конфигурации окружения инициализирует PostgresRepo или InMemoryRepo.
"""

from typing import Optional
from config import settings
from repo.base import Repository
from repo.in_memory_repo import InMemoryRepo
from repo.postgres_repo import PostgresRepo

_active_repo: Optional[Repository] = None


def is_postgres_configured() -> bool:
    url = settings.DATABASE_URL
    if not url:
        return False
    url_lower = url.lower()
    if any(p in url_lower for p in ("dummy", "example", "placeholder", "your_")):
        return False
    return url.startswith("postgresql://") or url.startswith("postgres://")


def get_repo() -> Repository:
    global _active_repo
    if _active_repo is not None:
        return _active_repo

    if is_postgres_configured():
        try:
            _active_repo = PostgresRepo(database_url=settings.DATABASE_URL)
        except Exception:
            _active_repo = InMemoryRepo()
    else:
        _active_repo = InMemoryRepo()

    return _active_repo


def set_repo(repo: Repository) -> None:
    global _active_repo
    _active_repo = repo
