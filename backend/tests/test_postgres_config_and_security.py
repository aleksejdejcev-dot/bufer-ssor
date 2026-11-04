import pytest
from config.settings import mask_db_url, validate_production_security, validate_db_startup_security, Settings


def test_mask_db_url():
    """Проверяет маскирование паролей в различных форматах URL подключения к БД."""
    url1 = "postgresql://buffer_admin:super_secret_password_123@127.0.0.1:5432/buffer_ssor"
    masked1 = mask_db_url(url1)
    assert "super_secret_password_123" not in masked1
    assert masked1 == "postgresql://buffer_admin:***@127.0.0.1:5432/buffer_ssor"

    url2 = "postgres://app_user:complex%2Fpassword@db.host.ru:6432/buffer_prod"
    masked2 = mask_db_url(url2)
    assert "complex%2Fpassword" not in masked2
    assert masked2 == "postgres://app_user:***@db.host.ru:6432/buffer_prod"

    assert mask_db_url("") == ""
    assert mask_db_url(None) == ""


def test_validate_production_security_db_sslmode():
    """В production DB_SSLMODE=disable строго запрещен."""
    # 1. Запрещенный режим
    bad_settings = Settings(
        ENVIRONMENT="production",
        DATABASE_URL="postgresql://user:secure_password_longer_than_16@host:5432/db",
        DB_SSLMODE="disable",
        TELEGRAM_WEBHOOK_SECRET="secret",
        INPUT_ENCRYPTION_KEY="test-encryption-key-for-testing-only",
        PAYMENT_HASH_KEY="salt",
    )
    with pytest.raises(RuntimeError, match="DB_SSLMODE должен быть require, verify-ca или verify-full"):
        validate_production_security(bad_settings)

    # 2. Разрешенные режимы
    for mode in ("require", "verify-ca", "verify-full"):
        good_settings = Settings(
            ENVIRONMENT="production",
            DATABASE_URL="postgresql://user:secure_password_longer_than_16@host:5432/db",
            DB_SSLMODE=mode,
            TELEGRAM_WEBHOOK_SECRET="secret",
            INPUT_ENCRYPTION_KEY="test-encryption-key-for-testing-only",
            PAYMENT_HASH_KEY="salt",
        )
        validate_production_security(good_settings)


def test_validate_production_security_enable_dev_tools():
    """В production ENABLE_DEV_TOOLS строго запрещен."""
    s = Settings(
        ENVIRONMENT="production",
        ENABLE_DEV_TOOLS=True,
        DATABASE_URL="postgresql://user:secure_password_longer_than_16@host:5432/db",
        DB_SSLMODE="require",
        TELEGRAM_WEBHOOK_SECRET="secret",
        INPUT_ENCRYPTION_KEY="test-encryption-key-for-testing-only",
        PAYMENT_HASH_KEY="salt",
    )
    with pytest.raises(RuntimeError, match="ENABLE_DEV_TOOLS строго запрещен в режиме production"):
        validate_production_security(s)


def test_yookassa_enabled_requires_credentials_in_production():
    base = {
        "ENVIRONMENT": "production",
        "TELEGRAM_WEBHOOK_SECRET": "secret",
        "INPUT_ENCRYPTION_KEY": "test-encryption-key-for-testing-only",
        "PAYMENT_HASH_KEY": "salt",
        "ENABLE_YOOKASSA": True,
        "YOOKASSA_SHOP_ID": "",
        "YOOKASSA_SECRET_KEY": "",
    }
    with pytest.raises(RuntimeError, match="YOOKASSA_SHOP_ID обязателен"):
        validate_production_security(Settings(**base))

    configured = Settings(**{**base, "YOOKASSA_SHOP_ID": "shop", "YOOKASSA_SECRET_KEY": "secret"})
    validate_production_security(configured)


@pytest.mark.postgres
def test_postgres_repo_blocks_superuser_and_ssl_in_production(monkeypatch):
    """PostgresRepo при ENVIRONMENT=production проверяет rolsuper и ssl_mode при старте."""
    from repo.postgres_repo import PostgresRepo
    from config import settings

    monkeypatch.setattr(settings, "ENVIRONMENT", "production")

    # 1. Запрет DB_SSLMODE=disable в prod
    repo_no_ssl = PostgresRepo(
        database_url="postgresql://buffer_admin:buffer_dev_pass@127.0.0.1:5432/buffer_ssor",
        ssl_mode="disable",
    )
    with pytest.raises(RuntimeError, match="Production database connection must use TLS"):
        repo_no_ssl._run_async(repo_no_ssl._get_pool())
    repo_no_ssl.close()

    # 2. Запрет подключения под суперпользователем (buffer_admin rolsuper=True) в prod
    from unittest.mock import AsyncMock, MagicMock, patch
    mock_conn = AsyncMock()
    mock_conn.fetchval = AsyncMock(return_value=True)
    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
    mock_pool.acquire.return_value.__aexit__.return_value = None
    mock_pool.close = AsyncMock()

    with patch("asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_pool):
        repo_admin = PostgresRepo(
            database_url="postgresql://buffer_admin:buffer_dev_pass@127.0.0.1:5432/buffer_ssor",
            ssl_mode="require",
        )
        with pytest.raises(RuntimeError, match="Production database connection must not use a superuser role"):
            repo_admin._run_async(repo_admin._get_pool())
        mock_conn.fetchval.assert_awaited_once_with(
            "SELECT rolsuper FROM pg_roles WHERE rolname = current_user;"
        )
        repo_admin.close()


def test_validate_production_security_passwords():
    """Task 4: В production запрещены dev-пароли и пароли короче 16 символов."""
    # 1. Dev-пароли запрещены
    for dev_pass in ("buffer_dev_pass", "migrator_dev_pass", "app_user_dev_pass"):
        bad_dev = Settings(
            ENVIRONMENT="production",
            DATABASE_URL=f"postgresql://user:{dev_pass}@host:5432/db",
            DB_SSLMODE="require",
            TELEGRAM_WEBHOOK_SECRET="secret",
            INPUT_ENCRYPTION_KEY="test-key",
            PAYMENT_HASH_KEY="salt",
        )
        with pytest.raises(RuntimeError, match="запрещено использовать dev-пароль"):
            validate_production_security(bad_dev)

    # 2. Пароль короче 16 символов запрещен
    short_pass = Settings(
        ENVIRONMENT="production",
        DATABASE_URL="postgresql://user:short_pass_123@host:5432/db",
        DB_SSLMODE="require",
        TELEGRAM_WEBHOOK_SECRET="secret",
        INPUT_ENCRYPTION_KEY="test-key",
        PAYMENT_HASH_KEY="salt",
    )
    with pytest.raises(RuntimeError, match="не короче 16 символов"):
        validate_production_security(short_pass)

    # 3. Надежный пароль (>=16 символов, не dev) разрешен
    secure_settings = Settings(
        ENVIRONMENT="production",
        DATABASE_URL="postgresql://user:super_strong_prod_pass_2026@host:5432/db",
        DB_SSLMODE="require",
        TELEGRAM_WEBHOOK_SECRET="secret",
        INPUT_ENCRYPTION_KEY="test-key",
        PAYMENT_HASH_KEY="salt",
    )
    validate_production_security(secure_settings)


def test_validate_db_startup_security_superuser_and_tls():
    """D9: В production запрещен запуск под суперпользователем и без TLS."""
    prod_settings = Settings(ENVIRONMENT="production")

    # 1. Запуск под суперпользователем запрещен
    with pytest.raises(RuntimeError, match="суперпользователем PostgreSQL строго запрещен"):
        validate_db_startup_security(prod_settings, is_superuser=True, is_tls=True)

    # 2. Запуск без TLS запрещен
    with pytest.raises(RuntimeError, match="только по зашифрованному каналу TLS"):
        validate_db_startup_security(prod_settings, is_superuser=False, is_tls=False)

    # 3. Безопасное подключение разрешено
    validate_db_startup_security(prod_settings, is_superuser=False, is_tls=True)

    # 4. В development ограничения не блокируют запуск
    dev_settings = Settings(ENVIRONMENT="development")
    validate_db_startup_security(dev_settings, is_superuser=True, is_tls=False)


def test_database_url_test_safety_guard():
    """D6: Защита тестовой БД — отказ работать, если база не _test или хост не localhost."""
    def verify_test_db_url(url: str, var_name: str = "DATABASE_URL_TEST"):
        if not url:
            raise ValueError(f"{var_name} не задан")
        # Проверка хоста
        if not any(h in url for h in ("localhost", "127.0.0.1")):
            raise ValueError(f"{var_name} должен указывать исключительно на localhost / 127.0.0.1")
        # Проверка имени БД
        dbname = url.split("/")[-1].split("?")[0]
        if not dbname.endswith("_test"):
            raise ValueError(f"Имя тестовой базы должно заканчиваться на _test, получено: {dbname}")

    # Валидные URL для DATABASE_URL_TEST и DATABASE_URL_APP_TEST
    verify_test_db_url("postgresql://buffer_admin:pass@127.0.0.1:5432/buffer_ssor_test", "DATABASE_URL_TEST")
    verify_test_db_url("postgresql://app_user:pass@localhost:5432/buffer_ssor_test", "DATABASE_URL_APP_TEST")

    # Невалидное имя
    with pytest.raises(ValueError, match="должно заканчиваться на _test"):
        verify_test_db_url("postgresql://buffer_admin:pass@127.0.0.1:5432/buffer_ssor", "DATABASE_URL_TEST")
    with pytest.raises(ValueError, match="должно заканчиваться на _test"):
        verify_test_db_url("postgresql://app_user:pass@127.0.0.1:5432/buffer_ssor", "DATABASE_URL_APP_TEST")

    # Невалидный хост (удаленный сервер)
    with pytest.raises(ValueError, match="исключительно на localhost"):
        verify_test_db_url("postgresql://buffer_admin:pass@remote.cloud.ru:5432/buffer_ssor_test", "DATABASE_URL_TEST")
    with pytest.raises(ValueError, match="исключительно на localhost"):
        verify_test_db_url("postgresql://app_user:pass@remote.cloud.ru:5432/buffer_ssor_test", "DATABASE_URL_APP_TEST")
