from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from fastapi.testclient import TestClient
from aiogram.types import Message, User, Chat
from aiogram.filters import CommandObject

from main import app, get_current_user
from repo import set_repo
from repo.in_memory_repo import InMemoryRepo
from rate_limiter import generate_crockford_code, CROCKFORD_ALPHABET, normalize_invite_code
from bot import handle_start, handle_conflict_input


def test_crockford_format():
    """Проверка генерации инвайт-кода Crockford Base32 (нет I, L, O, U; формат XXXX-XXXX)."""
    code = generate_crockford_code(length=8, formatted=True)
    assert len(code) == 9  # 8 символов + дефис
    assert code[4] == "-"
    for ch in code.replace("-", ""):
        assert ch in CROCKFORD_ALPHABET
        assert ch not in ("I", "L", "O", "U")

    # Проверка нормализации
    assert normalize_invite_code("abcd-efgh") == "ABCD-EFGH"
    assert normalize_invite_code("ABIO") == "AB10"


def test_conflict_start_rate_limit():
    """Тест rate limit на /conflict/start: 3 запроса в час на пару, 4-й дает 429."""
    test_repo = InMemoryRepo()
    set_repo(test_repo)

    u1 = test_repo.upsert_user(901, "Партнер 1")
    u2 = test_repo.upsert_user(902, "Партнер 2")
    test_repo.accept_legal(901)
    test_repo.accept_legal(902)

    couple = test_repo.create_couple(901, "INV901")
    test_repo.join_couple(couple["id"], 902)

    app.dependency_overrides[get_current_user] = lambda: u1
    try:
        client = TestClient(app)

        # 3 успешных запроса лимитера (завершаем сессию, чтобы не упираться в active_session)
        for i in range(3):
            resp = client.post("/conflict/start")
            assert resp.status_code == 200, f"Запрос #{i+1} завершился с ошибкой: {resp.text}"
            s_id = resp.json()["session_id"]
            # Завершаем сессию для возможности создания следующей
            test_repo.update_session_status(s_id, status="completed")

        # 4-й запрос превышает лимит (3 в час)
        resp4 = client.post("/conflict/start")
        assert resp4.status_code == 429
        assert "Не более 3 сессий в час на пару" in resp4.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_signal_rate_limit():
    """Тест rate limit на сигналы: не чаще 1 раза в час на пару."""
    test_repo = InMemoryRepo()
    set_repo(test_repo)

    u1 = test_repo.upsert_user(911, "Партнер 1")
    u2 = test_repo.upsert_user(912, "Партнер 2")
    test_repo.accept_legal(911)
    test_repo.accept_legal(912)

    couple = test_repo.create_couple(911, "INV911")
    test_repo.join_couple(couple["id"], 912)

    app.dependency_overrides[get_current_user] = lambda: u1
    try:
        client = TestClient(app)

        with patch("main.send_white_flag", new_callable=AsyncMock), \
             patch("main.send_hint_message", new_callable=AsyncMock):

            # 1. Белый флаг: 1-й запрос проходит, 2-й дает 429
            r1 = client.post("/signal/white-flag")
            assert r1.status_code == 200

            r2 = client.post("/signal/white-flag")
            assert r2.status_code == 429
            assert "Сигнал уже отправлен недавно" in r2.json()["detail"]

            # 2. Намек: 1-й запрос hug проходит, 2-й hug дает 429, но silence проходит
            h1 = client.post("/signal/hint", json={"hint_type": "hug"})
            assert h1.status_code == 200

            h2 = client.post("/signal/hint", json={"hint_type": "hug"})
            assert h2.status_code == 429

            h3 = client.post("/signal/hint", json={"hint_type": "silence"})
            assert h3.status_code == 200
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_invite_expiration_in_bot():
    """Тест срока жизни инвайта: просроченный инвайт (> 7 дней) отклоняется ботом."""
    test_repo = InMemoryRepo()
    set_repo(test_repo)

    u1 = test_repo.upsert_user(921, "Создатель")
    u2 = test_repo.upsert_user(922, "Второй")
    test_repo.accept_legal(921)
    test_repo.accept_legal(922)

    # Создаем пару с просроченным сроком жизни инвайта
    couple = test_repo.create_couple(921, "EXPIRED1")
    past_time = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    couple["invite_expires_at"] = past_time

    # Бот: пользователь u2 пытается присоединиться
    message = MagicMock(spec=Message)
    message.from_user = User(id=922, is_bot=False, first_name="Второй")
    message.chat = Chat(id=922, type="private")
    message.answer = AsyncMock()

    cmd = CommandObject(prefix="/", command="start", args="pair_EXPIRED1")
    await handle_start(message, cmd)

    message.answer.assert_called_once()
    reply = message.answer.call_args[0][0]
    assert "Срок действия инвайта истёк" in reply

    # Проверяем, что партнер 2 не присоединился
    c_check = test_repo.get_couple_by_id(couple["id"])
    assert c_check["partner_2_id"] is None


@pytest.mark.asyncio
async def test_invite_bruteforce_protection_in_bot():
    """Тест защиты от брутфорса инвайтов: 5 неверных попыток -> блокировка ввода на 1 час."""
    test_repo = InMemoryRepo()
    set_repo(test_repo)

    u1 = test_repo.upsert_user(931, "Создатель")
    u2 = test_repo.upsert_user(932, "Второй")
    test_repo.accept_legal(931)
    test_repo.accept_legal(932)

    valid_couple = test_repo.create_couple(931, "VALID123")

    # u2 совершает 5 неверных попыток
    for i in range(5):
        message = MagicMock(spec=Message)
        message.from_user = User(id=932, is_bot=False, first_name="Второй")
        message.chat = Chat(id=932, type="private")
        message.answer = AsyncMock()

        cmd = CommandObject(prefix="/", command="start", args=f"pair_WRONG{i}")
        await handle_start(message, cmd)
        reply = message.answer.call_args[0][0]
        assert "Приглашение не найдено" in reply

    # 6-я попытка (даже с правильным кодом) блокируется!
    msg6 = MagicMock(spec=Message)
    msg6.from_user = User(id=932, is_bot=False, first_name="Второй")
    msg6.chat = Chat(id=932, type="private")
    msg6.answer = AsyncMock()

    cmd_valid = CommandObject(prefix="/", command="start", args="pair_VALID123")
    await handle_start(msg6, cmd_valid)

    reply6 = msg6.answer.call_args[0][0]
    assert "Ввод заблокирован" in reply6

    # Партнер 2 не присоединился
    c_check = test_repo.get_couple_by_id(valid_couple["id"])
    assert c_check["partner_2_id"] is None
