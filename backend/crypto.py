"""
Модуль симметричного шифрования исходных материалов (текст, аудио) жалоб.
Использует алгоритм Fernet (AES-128-CBC + HMAC-SHA256).

ПРАВИЛО БЕЗОПАСНОСТИ:
Сырые тексты и аудио существуют ТОЛЬКО в таблице pending_inputs в зашифрованном виде.
В логи не писать, в API-ответах не отдавать, удалять сразу после завершения анализа.
"""

import logging
from cryptography.fernet import Fernet, InvalidToken
from config import settings

logger = logging.getLogger(__name__)


def _get_fernet() -> Fernet:
    """Инициализирует шифратор Fernet с валидацией ключа из env."""
    raw_key = settings.INPUT_ENCRYPTION_KEY.strip()
    try:
        return Fernet(raw_key.encode("utf-8"))
    except Exception as e:
        logger.critical("Неверный формат INPUT_ENCRYPTION_KEY. Ключ должен быть URL-safe base64 32 байт.")
        raise ValueError("Invalid INPUT_ENCRYPTION_KEY configuration") from e


_fernet_instance = None


def get_fernet_instance() -> Fernet:
    global _fernet_instance
    if _fernet_instance is None:
        _fernet_instance = _get_fernet()
    return _fernet_instance


def encrypt_bytes(data: bytes) -> bytes:
    """
    Шифрует байты (голосовое сообщение или бинарные данные).
    Возвращает зашифрованный токен Fernet (байты).
    """
    f = get_fernet_instance()
    return f.encrypt(data)


def decrypt_bytes(token: bytes) -> bytes:
    """
    Расшифровывает байты. При повреждении или неверном ключе вызывает ValueError.
    ВНИМАНИЕ: результат запрещено логировать!
    """
    f = get_fernet_instance()
    try:
        return f.decrypt(token)
    except InvalidToken as e:
        logger.error("Ошибка расшифровки: неверный ключ или поврежденные данные (Fernet InvalidToken)")
        raise ValueError("Decryption failed: invalid token") from e


def encrypt_text(text: str) -> bytes:
    """Шифрует строку UTF-8 и возвращает зашифрованные байты."""
    return encrypt_bytes(text.encode("utf-8"))


def decrypt_text(token: bytes) -> str:
    """
    Расшифровывает байты обратно в UTF-8 строку.
    ВНИМАНИЕ: расшифрованный текст запрещено логировать!
    """
    raw_bytes = decrypt_bytes(token)
    return raw_bytes.decode("utf-8", errors="replace")
