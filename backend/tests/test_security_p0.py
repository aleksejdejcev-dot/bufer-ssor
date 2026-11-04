import pytest
from httpx import AsyncClient, ASGITransport
from main import app
from config.settings import Settings, validate_production_security


@pytest.mark.asyncio
async def test_dev_endpoints_absent_in_production():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # 1. /api/dev/init-data must be completely gone (404)
        r = await ac.get("/api/dev/init-data")
        assert r.status_code == 404

        # 2. /docs and /openapi.json must be disabled in production (404)
        r_docs = await ac.get("/docs")
        assert r_docs.status_code == 404
        r_openapi = await ac.get("/openapi.json")
        assert r_openapi.status_code == 404

        # 3. /health must ONLY return status and llm_provider without model names
        r_health = await ac.get("/health")
        assert r_health.status_code == 200
        data = r_health.json()
        assert data == {"status": "ok", "llm_provider": data.get("llm_provider")}
        assert "gigachat_model" not in data
        assert "timestamp" not in data


def test_production_security_validation():
    # 1. GIGACHAT_INSECURE=True in production must raise RuntimeError
    bad_settings_1 = Settings(
        ENVIRONMENT="production",
        GIGACHAT_INSECURE=True,
        TELEGRAM_WEBHOOK_SECRET="secret",
        INPUT_ENCRYPTION_KEY="key",
        PAYMENT_HASH_KEY="hash",
    )
    with pytest.raises(RuntimeError) as exc_1:
        validate_production_security(bad_settings_1)
    assert "GIGACHAT_INSECURE=1" in str(exc_1.value)

    # 2. Missing TELEGRAM_WEBHOOK_SECRET in production must raise RuntimeError
    bad_settings_2 = Settings(
        ENVIRONMENT="production",
        TELEGRAM_WEBHOOK_SECRET="",
        INPUT_ENCRYPTION_KEY="key",
        PAYMENT_HASH_KEY="hash",
    )
    with pytest.raises(RuntimeError) as exc_2:
        validate_production_security(bad_settings_2)
    assert "TELEGRAM_WEBHOOK_SECRET" in str(exc_2.value)

    # 3. Missing PAYMENT_HASH_KEY in production must raise RuntimeError
    bad_settings_3 = Settings(
        ENVIRONMENT="production",
        TELEGRAM_WEBHOOK_SECRET="secret",
        INPUT_ENCRYPTION_KEY="key",
        PAYMENT_HASH_KEY="",
    )
    with pytest.raises(RuntimeError) as exc_3:
        validate_production_security(bad_settings_3)
    assert "PAYMENT_HASH_KEY" in str(exc_3.value)
