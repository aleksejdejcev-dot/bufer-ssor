"""
Конфигурация приложения «Буфер Ссор».
Все параметры загружаются из переменных окружения или файла .env.
"""

import re
from typing import List, Union, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


def mask_db_url(url: str) -> str:
    """Маскирует пароль в строке подключения к БД."""
    if not url:
        return ""
    return re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", url)


class Settings(BaseSettings):
    # База данных PostgreSQL
    DATABASE_URL: str = ""
    DATABASE_URL_TEST: str = ""
    DATABASE_URL_APP_TEST: str = ""
    DB_SSLMODE: str = "disable"  # "disable" для локального Docker; в production: "require", "verify-ca", "verify-full"
    DB_SSL_ROOT_CERT: Optional[str] = None
    DB_POOL_MIN: int = 2
    DB_POOL_MAX: int = 10

    # Telegram Bot & Webhook
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_WEBHOOK_SECRET: str = ""
    WEBHOOK_BASE_URL: str = ""
    TELEGRAM_API_BASE_URL: Optional[str] = None

    # Выбор LLM-провайдера (gigachat | gemini)
    LLM_PROVIDER: str = "gigachat"

    # Google Gemini AI
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-3.5-flash-lite"
    GEMINI_CONCURRENCY: int = 2

    # Sber GigaChat AI
    GIGACHAT_CREDENTIALS: str = ""
    GIGACHAT_SCOPE: str = "GIGACHAT_API_PERS"
    GIGACHAT_MODEL: str = "GigaChat-3-Ultra"
    GIGACHAT_CA_BUNDLE: Optional[str] = "backend/certs/russian_trusted_root_ca.pem"
    GIGACHAT_INSECURE: bool = False
    GIGACHAT_CONCURRENCY: int = 2
    GIGACHAT_PROMPT_MODE: str = "standard"  # "standard" | "compact"

    # Модели для конкретных ролей
    ANALYZER_MODEL: Optional[str] = None
    CARD_MODEL: Optional[str] = None
    SHARED_MODEL: Optional[str] = None
    CHECKER_MODEL: Optional[str] = None

    # Параметры генерации
    ANALYZER_TEMPERATURE: float = 0.3
    CARD_WRITER_TEMPERATURE: float = 0.8
    SHARED_WRITER_TEMPERATURE: float = 0.7
    LEAK_CHECKER_TEMPERATURE: float = 0.0
    MEDIATOR_TEMPERATURE: float = 0.7
    GEMINI_THINKING_BUDGET: Optional[int] = None

    # Окружение (production | development)
    ENVIRONMENT: str = "production"
    ENABLE_DEV_TOOLS: bool = False
    RETENTION_INTERVAL_SECONDS: int = 3600

    # Криптография (Fernet 32-байтный base64 ключ)
    INPUT_ENCRYPTION_KEY: str = ""

    # Секретный ключ для хэширования идентификаторов плательщиков (HMAC-SHA256)
    PAYMENT_HASH_KEY: str = ""

    # Telegram Mini App
    MINIAPP_URL: str = "https://t.me/BufferSsorBot/app"

    # Панель администратора в Telegram-боте
    ADMIN_TELEGRAM_IDS: str = ""
    ADMIN_SECRET_KEY: str = ""

    # Платежи (Yookassa)
    ENABLE_YOOKASSA: bool = False
    YOOKASSA_SHOP_ID: str = ""
    YOOKASSA_SECRET_KEY: str = ""
    YOOKASSA_RETURN_URL: str = "https://t.me/BufferSsorBot"

    # Ограничения на голосовые сообщения
    MAX_VOICE_DURATION_SECONDS: int = 300  # 5 минут
    MAX_VOICE_SIZE_BYTES: int = 10 * 1024 * 1024  # 10 МБ

    # Сроки хранения данных
    EXPIRATION_HOURS: int = 48
    RAW_INPUT_TTL_HOURS: int = 48
    RESULTS_RETENTION_DAYS: int = 30
    PAYMENT_RETENTION_YEARS: Optional[int] = None

    # Настройки сервера
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Опциональный прокси для Gemini API
    HTTPS_PROXY: str = ""
    HTTP_PROXY: str = ""

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()


def validate_production_security(s: Settings) -> None:
    """
    Запрет запуска в production при небезопасной конфигурации.
    """
    if s.ENVIRONMENT == "production":
        errors = []
        if s.ENABLE_DEV_TOOLS:
            errors.append("ENABLE_DEV_TOOLS строго запрещен в режиме production")
        if s.GIGACHAT_INSECURE:
            errors.append("GIGACHAT_INSECURE=1 строго запрещен в режиме production")
        if not s.TELEGRAM_WEBHOOK_SECRET:
            errors.append("TELEGRAM_WEBHOOK_SECRET обязателен в режиме production")
        if not s.INPUT_ENCRYPTION_KEY:
            errors.append("INPUT_ENCRYPTION_KEY обязателен в режиме production")
        if not s.PAYMENT_HASH_KEY:
            errors.append("PAYMENT_HASH_KEY обязателен в режиме production")
        if s.DATABASE_URL:
            import urllib.parse
            parsed_db = urllib.parse.urlparse(s.DATABASE_URL)
            is_local = parsed_db.hostname in ("localhost", "127.0.0.1", "postgres", "host.docker.internal")

            # D2: disable допустим только для локального Docker; в production (на удаленном хосте) допустимы require, verify-ca, verify-full
            if is_local:
                if s.DB_SSLMODE not in ("disable", "require", "verify-ca", "verify-full"):
                    errors.append(f"Недопустимый DB_SSLMODE: {s.DB_SSLMODE}")
            else:
                if s.DB_SSLMODE not in ("require", "verify-ca", "verify-full"):
                    errors.append(f"В режиме production DB_SSLMODE должен быть require, verify-ca или verify-full (текущий: {s.DB_SSLMODE})")

            # Валидация стойкости пароля БД в production (для боевых удаленных БД)
            db_password = parsed_db.password or ""
            forbidden_dev_passwords = {"buffer_dev_pass", "migrator_dev_pass", "app_user_dev_pass"}
            if not is_local:
                if db_password in forbidden_dev_passwords:
                    errors.append(f"В режиме production запрещено использовать dev-пароль '{db_password}' в DATABASE_URL")
                if len(db_password) < 16:
                    errors.append("В режиме production пароль в DATABASE_URL должен быть не короче 16 символов")
        if errors:
            raise RuntimeError(
                "КРИТИЧЕСКАЯ ОШИБКА БЕЗОПАСНОСТИ: Запуск в production заблокирован из-за небезопасной конфигурации:\n - "
                + "\n - ".join(errors)
            )


def validate_db_startup_security(s: Settings, is_superuser: bool, is_tls: bool) -> None:
    """
    Проверки подключения к БД при старте приложения в production (D9).
    Запрещает запуск под суперпользователем и без TLS.
    """
    if s.ENVIRONMENT == "production":
        if is_superuser:
            raise RuntimeError("КРИТИЧЕСКАЯ ОШИБКА БЕЗОПАСНОСТИ: Запуск в production под суперпользователем PostgreSQL строго запрещен.")
        if not is_tls:
            raise RuntimeError("КРИТИЧЕСКАЯ ОШИБКА БЕЗОПАСНОСТИ: Подключение к PostgreSQL в production допустимо только по зашифрованному каналу TLS.")


validate_production_security(settings)

if settings.HTTPS_PROXY:
    import os
    os.environ["HTTPS_PROXY"] = settings.HTTPS_PROXY
    os.environ["HTTP_PROXY"] = settings.HTTP_PROXY or settings.HTTPS_PROXY
