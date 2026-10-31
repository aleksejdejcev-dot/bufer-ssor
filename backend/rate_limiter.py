"""
Единый модуль rate-limiter и генерации инвайт-кодов Crockford Base32.
"""

import time
import secrets
from collections import deque
from typing import Dict, Tuple, Optional
from fastapi import HTTPException, status

# Алфавит Crockford Base32 (исключены I, L, O, U во избежание неоднозначности чтения)
CROCKFORD_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def generate_crockford_code(length: int = 8, formatted: bool = True) -> str:
    """
    Генерирует криптографически стойкий инвайт-код формата XXXX-XXXX
    из алфавита Crockford Base32.
    """
    chars = [secrets.choice(CROCKFORD_ALPHABET) for _ in range(length)]
    raw = "".join(chars)
    if formatted and length == 8:
        return f"{raw[:4]}-{raw[4:]}"
    return raw


def normalize_invite_code(code: str) -> str:
    """
    Нормализует инвайт-код:
    - приводит к верхнему регистру;
    - удаляет дефисы и пробелы;
    - заменяет похожие символы: I/L -> 1, O -> 0.
    """
    clean = code.strip().upper().replace("-", "").replace(" ", "")
    clean = clean.replace("I", "1").replace("L", "1").replace("O", "0")
    if len(clean) == 8:
        return f"{clean[:4]}-{clean[4:]}"
    return clean


class RateLimiter:
    """
    Хранилище скользящих окон запросов в памяти (для dev / in-memory).
    В проде для распределенного кластера может быть подключен Redis или Postgres-таблица.
    """
    def __init__(self):
        self._history: Dict[str, deque[float]] = {}

    def check(self, key: str, max_requests: int, window_seconds: int) -> Tuple[bool, int]:
        """
        Проверяет лимит запросов для ключа key.
        Возвращает (allowed, retry_after_seconds).
        Если allowed == True, текущий запрос регистрируется.
        """
        now = time.time()
        requests = self._history.setdefault(str(key), deque())

        # Удаляем запросы, вышедшие за пределы скользящего окна
        while requests and requests[0] <= now - window_seconds:
            requests.popleft()

        if len(requests) >= max_requests:
            retry_after = int(window_seconds - (now - requests[0])) + 1
            return False, retry_after

        requests.append(now)
        return True, 0

    def peek(self, key: str, max_requests: int, window_seconds: int) -> Tuple[bool, int]:
        """
        Только проверяет статус лимита без регистрации нового запроса.
        """
        now = time.time()
        requests = self._history.get(str(key))
        if not requests:
            return True, 0

        while requests and requests[0] <= now - window_seconds:
            requests.popleft()

        if len(requests) >= max_requests:
            retry_after = int(window_seconds - (now - requests[0])) + 1
            return False, retry_after

        return True, 0

    def record_hit(self, key: str) -> None:
        """Регистрирует факт события (например, неудачной попытки)."""
        now = time.time()
        requests = self._history.setdefault(str(key), deque())
        requests.append(now)

    def reset(self, key: str) -> None:
        """Сбрасывает историю для ключа."""
        if str(key) in self._history:
            del self._history[str(key)]

    def clear(self) -> None:
        self._history.clear()


# Глобальный инстанс rate-лимитера
limiter = RateLimiter()
