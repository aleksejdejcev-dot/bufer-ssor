"""
Модуль репозитория: выбор и предоставление реализации хранилища данных.
"""

import os
from typing import Optional
from config import settings
from repo.base import Repository
from repo.in_memory_repo import InMemoryRepo

_active_repo: Optional[Repository] = None


def is_supabase_configured() -> bool:
    url = settings.SUPABASE_URL
    key = settings.SUPABASE_SERVICE_KEY
    if not url or not key:
        return False
    if "dummy" in url.lower() or "example" in url.lower() or "your_" in url.lower():
        return False
    if "dummy" in key.lower() or "example" in key.lower() or "your_" in key.lower():
        return False
    return True


def get_repo() -> Repository:
    global _active_repo
    if _active_repo is not None:
        return _active_repo

    if not is_supabase_configured():
        _active_repo = InMemoryRepo()
    else:
        try:
            from repo.supabase_repo import SupabaseRepo
            _active_repo = SupabaseRepo()
        except Exception:
            _active_repo = InMemoryRepo()

    return _active_repo


def set_repo(repo: Repository) -> None:
    global _active_repo
    _active_repo = repo
