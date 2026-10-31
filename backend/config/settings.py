"""
Конфигурация приложения «Буфер Ссор».
Все параметры загружаются из переменных окружения или файла .env.
Имя модели Gemini берется ТОЛЬКО из GEMINI_MODEL (значение: gemini-3.8-flash, не хардкодить в бизнес-коде).
"""

from typing import List, Union, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Supabase (Postgres & Service Role Client)
    SUPABASE_URL: str = ""
    SUPABASE_SERVICE_KEY: str = ""

    # Telegram Bot & Webhook
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_WEBHOOK_SECRET: str = ""
    WEBHOOK_BASE_URL: str = ""

    # Выбор LLM-провайдера (Этап 3.5: gigachat | gemini)
    LLM_PROVIDER: str = "gigachat"

    # Google Gemini AI
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-3.5-flash-lite"
    GEMINI_CONCURRENCY: int = 2

    # Sber GigaChat AI (Этап 3.5)
    GIGACHAT_CREDENTIALS: str = ""
    GIGACHAT_SCOPE: str = "GIGACHAT_API_PERS"
    GIGACHAT_MODEL: str = "GigaChat-3-Ultra"
    GIGACHAT_CA_BUNDLE: Optional[str] = "backend/certs/russian_trusted_root_ca.pem"
    GIGACHAT_INSECURE: bool = False
    GIGACHAT_CONCURRENCY: int = 2
    GIGACHAT_PROMPT_MODE: str = "standard"  # "standard" | "compact"

    # Модели для конкретных ролей (переопределение общей модели провайдера)
    ANALYZER_MODEL: Optional[str] = None
    CARD_MODEL: Optional[str] = None
    SHARED_MODEL: Optional[str] = None
    CHECKER_MODEL: Optional[str] = None

    # Параметры генерации Gemini (Этап 3.1)
    ANALYZER_TEMPERATURE: float = 0.3
    CARD_WRITER_TEMPERATURE: float = 0.8
    SHARED_WRITER_TEMPERATURE: float = 0.7
    LEAK_CHECKER_TEMPERATURE: float = 0.0
    MEDIATOR_TEMPERATURE: float = 0.7
    GEMINI_THINKING_BUDGET: Optional[int] = None

    # Окружение (production | development)
    ENVIRONMENT: str = "production"

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

    # Ограничения на голосовые сообщения
    MAX_VOICE_DURATION_SECONDS: int = 300  # 5 минут
    MAX_VOICE_SIZE_BYTES: int = 10 * 1024 * 1024  # 10 МБ

    # Сроки хранения данных
    EXPIRATION_HOURS: int = 48
    RAW_INPUT_TTL_HOURS: int = 48
    RESULTS_RETENTION_DAYS: int = 30
    PAYMENT_RETENTION_YEARS: Optional[int] = None

    # Использование тестового кэша
    TEST_CACHE: bool = False

    # Настройки сервера
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Опциональный прокси для Gemini API (если требуется в регионе)
    HTTPS_PROXY: str = ""
    HTTP_PROXY: str = ""

    # Загружаем из текущего каталога или родительского
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
        if s.GIGACHAT_INSECURE:
            errors.append("GIGACHAT_INSECURE=1 строго запрещен в режиме production")
        if not s.TELEGRAM_WEBHOOK_SECRET:
            errors.append("TELEGRAM_WEBHOOK_SECRET обязателен в режиме production")
        if not s.INPUT_ENCRYPTION_KEY:
            errors.append("INPUT_ENCRYPTION_KEY обязателен в режиме production")
        if not s.PAYMENT_HASH_KEY:
            errors.append("PAYMENT_HASH_KEY обязателен в режиме production")
        if errors:
            raise RuntimeError(
                "КРИТИЧЕСКАЯ ОШИБКА БЕЗОПАСНОСТИ: Запуск в production заблокирован из-за небезопасной конфигурации:\n - "
                + "\n - ".join(errors)
            )


# Проверяем безопасность при инициализации
validate_production_security(settings)

# Если прокси настроен в .env, экспортируем в системные переменные окружения
if settings.HTTPS_PROXY:
    import os
    os.environ["HTTPS_PROXY"] = settings.HTTPS_PROXY
    os.environ["HTTP_PROXY"] = settings.HTTP_PROXY or settings.HTTPS_PROXY
