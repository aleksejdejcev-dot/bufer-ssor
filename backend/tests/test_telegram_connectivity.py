import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from httpx import AsyncClient, ASGITransport

from config import settings
from main import app, _telegram_startup_worker


def test_telegram_api_base_url_configuration(monkeypatch):
    from aiogram import Bot
    from aiogram.client.session.aiohttp import AiohttpSession
    from aiogram.client.telegram import TelegramAPIServer

    monkeypatch.setattr(settings, "TELEGRAM_API_BASE_URL", "https://tg-proxy.aleksejdejcev62.workers.dev")
    api_server = TelegramAPIServer.from_base(settings.TELEGRAM_API_BASE_URL)
    session = AiohttpSession(api=api_server, timeout=15.0)
    test_bot = Bot(token="123456789:dummy_token", session=session)

    assert test_bot.session.api.base == "https://tg-proxy.aleksejdejcev62.workers.dev/bot{token}/{method}"
    assert test_bot.token == "123456789:dummy_token"


@pytest.mark.asyncio
async def test_telegram_startup_worker_success(monkeypatch):
    mock_bot = MagicMock()
    mock_me = MagicMock()
    mock_me.username = "TestBufferBot"
    mock_bot.get_me = AsyncMock(return_value=mock_me)
    mock_bot.delete_webhook = AsyncMock(return_value=True)
    mock_start_polling = AsyncMock(return_value=None)

    monkeypatch.setattr("main.bot", mock_bot)
    monkeypatch.setattr("main.dp.start_polling", mock_start_polling)

    worker_task = asyncio.create_task(_telegram_startup_worker())
    await asyncio.sleep(0.05)
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass

    assert mock_bot.get_me.called
    assert mock_bot.delete_webhook.called
    mock_bot.delete_webhook.assert_called_with(drop_pending_updates=True)
    assert mock_start_polling.called


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
async def test_webhook_endpoints_disabled():
    """Проверка, что эндпоинты вебхуков отключены в пользу Long Polling"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r1 = await ac.post("/api/webhook", json={"update_id": 1})
        assert r1.status_code in (404, 405)

        r2 = await ac.post("/api/telegram/setup-webhook")
        assert r2.status_code in (404, 405)


def test_safe_admin_stats_formatting(monkeypatch):
    """Проверка безопасного парсинга статистики без KeyError: 'total_users'"""
    from bot import format_admin_stats_text

    # Пустой словарь статистики от БД
    monkeypatch.setattr("bot.db.get_admin_stats", lambda: {})
    text = format_admin_stats_text()
    assert "Всего зарегистрировано: <b>0</b>" in text
    assert "Активных пользователей: <b>0</b>" in text
    assert "Всего создано пар: <b>0</b>" in text
    assert "Всего запущено: <b>0</b>" in text

    # Неполный словарь статистики
    monkeypatch.setattr("bot.db.get_admin_stats", lambda: {"total_couples": 5})
    text2 = format_admin_stats_text()
    assert "Всего зарегистрировано: <b>0</b>" in text2
    assert "Всего создано пар: <b>5</b>" in text2
