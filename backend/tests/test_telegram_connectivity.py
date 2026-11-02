import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from httpx import AsyncClient, ASGITransport

from config import settings
from bot import _get_telegram_proxy, _resolve_proxy_for_env
from main import app, _telegram_startup_worker


@pytest.mark.asyncio
async def test_telegram_proxy_resolution(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_PROXY", "socks5://proxy.example.com:1080")
    assert _get_telegram_proxy() == "socks5://proxy.example.com:1080"

    monkeypatch.setattr(settings, "TELEGRAM_PROXY", "")
    monkeypatch.setattr(settings, "HTTPS_PROXY", "http://proxy.https:8080")
    assert _get_telegram_proxy() == "http://proxy.https:8080"


@pytest.mark.asyncio
async def test_telegram_proxy_docker_resolution(monkeypatch):
    monkeypatch.setattr("os.path.exists", lambda path: path == "/.dockerenv")
    with patch("socket.gethostbyname", return_value="192.168.65.2"):
        res = _resolve_proxy_for_env("http://127.0.0.1:10808")
        assert res == "http://host.docker.internal:10808"


@pytest.mark.asyncio
async def test_telegram_startup_worker_success(monkeypatch):
    mock_bot = MagicMock()
    mock_me = MagicMock()
    mock_me.username = "TestBufferBot"
    mock_bot.get_me = AsyncMock(return_value=mock_me)
    mock_bot.set_webhook = AsyncMock(return_value=True)
    mock_bot.delete_webhook = AsyncMock(return_value=True)

    monkeypatch.setattr("main.bot", mock_bot)
    monkeypatch.setattr(settings, "WEBHOOK_BASE_URL", "https://prod.mybot.ru")

    worker_task = asyncio.create_task(_telegram_startup_worker())
    await asyncio.sleep(0.05)
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass

    assert mock_bot.get_me.called
    assert mock_bot.set_webhook.called


@pytest.mark.asyncio
async def test_telegram_startup_worker_error_resilience(monkeypatch):
    mock_bot = MagicMock()
    mock_bot.get_me = AsyncMock(side_effect=TimeoutError("Request timeout error"))

    monkeypatch.setattr("main.bot", mock_bot)
    # Reset global bot_username_cache
    monkeypatch.setattr("main.bot_username_cache", None)

    real_sleep = asyncio.sleep

    async def fake_sleep(duration):
        await real_sleep(0)  # yield control

    monkeypatch.setattr("main.asyncio.sleep", fake_sleep)

    worker_task = asyncio.create_task(_telegram_startup_worker())
    await asyncio.sleep(0.01)
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass

    assert mock_bot.get_me.call_count >= 1


@pytest.mark.asyncio
async def test_manual_setup_webhook_endpoint(monkeypatch):
    mock_bot = MagicMock()
    mock_bot.set_webhook = AsyncMock(return_value=True)
    monkeypatch.setattr("main.bot", mock_bot)
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", "super_secret_val")
    monkeypatch.setattr(settings, "WEBHOOK_BASE_URL", "https://domain.ru")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # 1. Invalid secret token -> 403 Forbidden
        r_bad = await ac.post(
            "/api/telegram/setup-webhook",
            headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
        )
        assert r_bad.status_code == 403

        # 2. Valid secret token -> 200 OK
        r_ok = await ac.post(
            "/api/telegram/setup-webhook",
            headers={"X-Telegram-Bot-Api-Secret-Token": "super_secret_val"},
        )
        assert r_ok.status_code == 200
        assert r_ok.json()["status"] == "ok"
        assert r_ok.json()["webhook_url"] == "https://domain.ru/api/webhook"
