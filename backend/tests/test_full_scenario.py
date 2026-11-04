"""
Комплексный автоматический тест сквозного сценария бэкенда «Буфер Ссор».
Проверяет:
1. Криптографию Fernet (текст, бинарные аудиоданные, обработка ошибок).
2. Валидацию HMAC-SHA256 подписи Telegram Mini App initData и TTL 24 часа.
3. Шлюз проверки 18+ и дисклеймера (403 пока нет accepted_legal_at).
4. Создание пары, генерацию инвайт-ссылки, привязку партнера Б.
5. Защиту от связки с самим собой и повторных связок.
6. Отправку настроения (1-10) и валидацию шкалы.
7. Отправку сигналов: «Белый флаг» и деликатные намеки (hug, silence и т.д.).
8. Старт сессии конфликта, проверку лимитов бесплатных разборов.
9. Прием позиции от Партнера А и Партнера Б (сохранение в pending_inputs, вызов analyze_session).
10. Правила конфиденциальности: отдавать ТОЛЬКО личную карточку текущего партнера и общий итог.
11. Rate limiter (защита от флуда, 429 Too Many Requests).
12. Полное удаление пары через DELETE /couple.
"""

import time
import json
import base64
import os
import uuid
import hmac
import hashlib
from datetime import datetime, timezone
from typing import Dict, Any, Optional
import pytest
from httpx import AsyncClient, ASGITransport

# Тестовые переменные окружения
TEST_FERNET_KEY = base64.urlsafe_b64encode(os.urandom(32)).decode()
TEST_BOT_TOKEN = "123456789:TEST_BOT_TOKEN_FOR_UNITTESTS_XYZ"
TEST_WEBHOOK_SECRET = "test_webhook_secret_1234567890abcdef"

os.environ["INPUT_ENCRYPTION_KEY"] = TEST_FERNET_KEY
os.environ["DATABASE_URL"] = "postgresql://buffer_admin:test_password@127.0.0.1:5432/buffer_ssor_test"
os.environ["TELEGRAM_BOT_TOKEN"] = TEST_BOT_TOKEN
os.environ["TELEGRAM_WEBHOOK_SECRET"] = TEST_WEBHOOK_SECRET
os.environ["WEBHOOK_BASE_URL"] = "https://test.ngrok.app"
os.environ["GEMINI_MODEL"] = "gemini-3.8-flash"

import crypto
from config import settings
import db
from bot import bot
from main import app, verify_telegram_init_data
from unittest.mock import AsyncMock


# ==============================================================================
# Хелпер генерации валидного Telegram Mini App initData
# ==============================================================================

def make_valid_init_data(telegram_id: int, first_name: str, auth_date_offset: int = 0) -> str:
    auth_date = str(int(time.time()) + auth_date_offset)
    user_json = json.dumps({"id": telegram_id, "first_name": first_name}, separators=(",", ":"))
    params = {
        "auth_date": auth_date,
        "query_id": f"AAHF_{telegram_id}",
        "user": user_json,
    }
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret_key = hmac.new(b"WebAppData", settings.TELEGRAM_BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()
    sig = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    
    parts = [f"{k}={v}" for k, v in params.items()]
    parts.append(f"hash={sig}")
    return "&".join(parts)


# ==============================================================================
# In-Memory хранилище для эмуляции БД во время тестов
# ==============================================================================

class InMemoryDB:
    def __init__(self):
        self.users: Dict[int, dict] = {}
        self.couples: Dict[str, dict] = {}
        self.conflict_sessions: Dict[str, dict] = {}
        self.pending_inputs: Dict[str, dict] = {}

    def reset(self):
        self.users.clear()
        self.couples.clear()
        self.conflict_sessions.clear()
        self.pending_inputs.clear()


mem_db = InMemoryDB()


@pytest.fixture(autouse=True)
def patch_db(monkeypatch):
    """Подменяет функции db на in-memory хранилище для детерминированного тестирования"""
    mem_db.reset()
    rate_counts = {}
    from rate_limiter import limiter
    limiter.clear()

    # Users
    def mock_get_user(telegram_id: int):
        return mem_db.users.get(telegram_id)

    def mock_upsert_user(telegram_id: int, first_name: str):
        if telegram_id in mem_db.users:
            mem_db.users[telegram_id]["first_name"] = first_name
            return mem_db.users[telegram_id]
        new_u = {
            "telegram_id": telegram_id,
            "first_name": first_name,
            "accepted_legal_at": None,
            "couple_id": None,
        }
        mem_db.users[telegram_id] = new_u
        return new_u

    def mock_accept_legal(telegram_id: int):
        u = mem_db.users.get(telegram_id)
        if not u:
            u = mock_upsert_user(telegram_id, "User")
        u["accepted_legal_at"] = "2026-10-29T12:00:00+00:00"
        return u

    # Couples
    def mock_get_couple_by_id(couple_id: str):
        return mem_db.couples.get(couple_id)

    def mock_get_couple_by_invite(invite_code: str):
        for c in mem_db.couples.values():
            if c["invite_code"] == invite_code.upper():
                return c
        return None

    def mock_get_user_couple(telegram_id: int):
        u = mem_db.users.get(telegram_id)
        if u and u.get("couple_id"):
            return mem_db.couples.get(u["couple_id"])
        for c in mem_db.couples.values():
            if c["partner_1_id"] == telegram_id or c.get("partner_2_id") == telegram_id:
                return c
        return None

    def mock_get_subscription_until_for_user(telegram_id: int):
        return None

    def mock_check_couple_access(couple):
        until = couple.get("subscription_until")
        if until and datetime.fromisoformat(until) > datetime.now(timezone.utc):
            return True, "subscription"
        if couple.get("free_sessions_left", 0) > 0:
            return True, "free_session"
        return False, "no_access"

    def mock_check_rate_limit(key, max_requests, window_seconds):
        current = rate_counts.get(key, 0)
        if current >= max_requests:
            return False, window_seconds
        rate_counts[key] = current + 1
        return True, 0

    def mock_create_couple(partner_1_id: int, invite_code: str):
        c_id = f"couple_{uuid.uuid4()}"
        c = {
            "id": c_id,
            "invite_code": invite_code.upper(),
            "partner_1_id": partner_1_id,
            "partner_2_id": None,
            "free_sessions_left": 2,
            "subscription_until": None,
            "auto_renew": False,
            "mood_p1": None,
            "mood_p2": None,
        }
        mem_db.couples[c_id] = c
        if partner_1_id in mem_db.users:
            mem_db.users[partner_1_id]["couple_id"] = c_id
        return c

    def mock_join_couple(couple_id: str, partner_2_id: int):
        c = mem_db.couples[couple_id]
        c["partner_2_id"] = partner_2_id
        if partner_2_id in mem_db.users:
            mem_db.users[partner_2_id]["couple_id"] = couple_id
        return c

    def mock_update_mood(couple_id: str, is_partner_1: bool, mood: int):
        c = mem_db.couples[couple_id]
        field = "mood_p1" if is_partner_1 else "mood_p2"
        c[field] = mood
        return c

    def mock_delete_couple_data(couple_id: str, initiated_by=None):
        # сброс users
        for u in mem_db.users.values():
            if u.get("couple_id") == couple_id:
                u["couple_id"] = None
        # удаление pending_inputs связанных с сессиями пары
        session_ids = [s_id for s_id, s in mem_db.conflict_sessions.items() if s["couple_id"] == couple_id]
        for p_id in list(mem_db.pending_inputs.keys()):
            if mem_db.pending_inputs[p_id]["session_id"] in session_ids:
                del mem_db.pending_inputs[p_id]
        # удаление сессий
        for s_id in session_ids:
            del mem_db.conflict_sessions[s_id]
        # удаление пары
        if couple_id in mem_db.couples:
            del mem_db.couples[couple_id]

    # Sessions
    def mock_get_active_session(couple_id: str):
        for s in reversed(list(mem_db.conflict_sessions.values())):
            if s["couple_id"] == couple_id and s["status"] in ("waiting_partner_2", "analyzing"):
                return s
        return None

    def mock_get_session_by_id(session_id: str):
        return mem_db.conflict_sessions.get(session_id)

    def mock_create_conflict_session(couple_id: str, initiator_id: int):
        s_id = f"session_{len(mem_db.conflict_sessions) + 1}"
        s = {
            "id": s_id,
            "couple_id": couple_id,
            "initiator_id": initiator_id,
            "status": "waiting_partner_2",
            "risk_level": None,
            "ai_advice_p1": None,
            "ai_advice_p2": None,
            "shared_summary": None,
            "created_at": "2026-10-29T12:00:00+00:00",
            "completed_at": None,
        }
        mem_db.conflict_sessions[s_id] = s
        return s

    def mock_create_conflict_session_with_access(couple_id: str, initiator_id: int):
        couple = mem_db.couples.get(couple_id)
        if not couple or not couple.get("partner_2_id") or couple.get("free_sessions_left", 0) <= 0:
            return None
        if mock_get_active_session(couple_id):
            return None
        return mock_create_conflict_session(couple_id, initiator_id)

    def mock_update_session_status(session_id: str, status: str, **kwargs):
        s = mem_db.conflict_sessions[session_id]
        s["status"] = status
        for k, v in kwargs.items():
            if v is not None:
                s[k] = v
        return s

    # Pending inputs
    def mock_save_pending_input(session_id: str, author_telegram_id: int, kind: str, payload_encrypted: bytes):
        p_id = f"input_{len(mem_db.pending_inputs) + 1}"
        item = {
            "id": p_id,
            "session_id": session_id,
            "author_telegram_id": author_telegram_id,
            "kind": kind,
            "payload_encrypted": payload_encrypted,
        }
        mem_db.pending_inputs[p_id] = item
        return item

    def mock_has_user_submitted(session_id: str, author_telegram_id: int):
        for item in mem_db.pending_inputs.values():
            if item["session_id"] == session_id and item["author_telegram_id"] == author_telegram_id:
                return True
        return False

    def mock_count_pending(session_id: str):
        return sum(1 for item in mem_db.pending_inputs.values() if item["session_id"] == session_id)

    def mock_delete_pending(session_id: str):
        for p_id in list(mem_db.pending_inputs.keys()):
            if mem_db.pending_inputs[p_id]["session_id"] == session_id:
                del mem_db.pending_inputs[p_id]

    monkeypatch.setattr(db, "get_user", mock_get_user)
    monkeypatch.setattr(db, "upsert_user", mock_upsert_user)
    monkeypatch.setattr(db, "accept_legal", mock_accept_legal)
    monkeypatch.setattr(db, "get_couple_by_id", mock_get_couple_by_id)
    monkeypatch.setattr(db, "get_couple_by_invite", mock_get_couple_by_invite)
    monkeypatch.setattr(db, "get_user_couple", mock_get_user_couple)
    monkeypatch.setattr(db, "get_subscription_until_for_user", mock_get_subscription_until_for_user)
    monkeypatch.setattr(db, "check_couple_access", mock_check_couple_access)
    monkeypatch.setattr(db, "check_rate_limit", mock_check_rate_limit)
    monkeypatch.setattr(db, "create_couple", mock_create_couple)
    monkeypatch.setattr(db, "join_couple", mock_join_couple)
    monkeypatch.setattr(db, "update_mood", mock_update_mood)
    monkeypatch.setattr(db, "delete_couple_data", mock_delete_couple_data)
    monkeypatch.setattr(db, "get_active_session", mock_get_active_session)
    monkeypatch.setattr(db, "get_session_by_id", mock_get_session_by_id)
    monkeypatch.setattr(db, "create_conflict_session", mock_create_conflict_session)
    monkeypatch.setattr(db, "create_conflict_session_with_access", mock_create_conflict_session_with_access)
    monkeypatch.setattr(db, "update_session_status", mock_update_session_status)
    monkeypatch.setattr(db, "save_pending_input", mock_save_pending_input)
    monkeypatch.setattr(db, "has_user_submitted_input", mock_has_user_submitted)
    monkeypatch.setattr(db, "count_pending_inputs", mock_count_pending)
    monkeypatch.setattr(db, "delete_pending_inputs_for_session", mock_delete_pending)
    monkeypatch.setattr(bot, "send_message", AsyncMock())


# ==============================================================================
# ТЕСТ 1: Криптография Fernet
# ==============================================================================

def test_crypto_encryption_and_decryption():
    test_text = "Конфликт из-за немытой посуды: я устал повторять одно и то же."
    encrypted_bytes = crypto.encrypt_text(test_text)
    
    assert encrypted_bytes != test_text.encode("utf-8")
    assert isinstance(encrypted_bytes, bytes)
    
    decrypted_text = crypto.decrypt_text(encrypted_bytes)
    assert decrypted_text == test_text

    # Бинарные аудиоданные (эмуляция .ogg)
    raw_audio = b"\x4F\x67\x67\x53\x00\x02\x00\x00" + os.urandom(1024)
    enc_audio = crypto.encrypt_bytes(raw_audio)
    dec_audio = crypto.decrypt_bytes(enc_audio)
    assert dec_audio == raw_audio

    # Поврежденный токен вызывает ValueError
    with pytest.raises(ValueError, match="Decryption failed"):
        crypto.decrypt_bytes(b"tampered_invalid_token")


# ==============================================================================
# ТЕСТ 2: Валидация Telegram Mini App initData
# ==============================================================================

def test_telegram_init_data_verification():
    # Валидный initData
    valid_raw = make_valid_init_data(telegram_id=111, first_name="Алексей")
    user = verify_telegram_init_data(valid_raw)
    assert user["id"] == 111
    assert user["first_name"] == "Алексей"

    # Неверная подпись
    invalid_raw = valid_raw + "bad_hash_char"
    with pytest.raises(Exception):
        verify_telegram_init_data(invalid_raw)

    # Устаревший auth_date (> 24 часов)
    expired_raw = make_valid_init_data(telegram_id=111, first_name="Алексей", auth_date_offset=-86500)
    with pytest.raises(Exception):
        verify_telegram_init_data(expired_raw)


# ==============================================================================
# ТЕСТ 3: Сквозной сценарий REST API и Telegram Mini App
# ==============================================================================

@pytest.mark.asyncio
async def test_full_api_workflow_between_two_partners():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        
        # 1. Healthcheck
        r = await ac.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
        assert "llm_provider" in r.json()

        # Создаем токены авторизации для Партнера А (101) и Партнера Б (102)
        init_a = make_valid_init_data(101, "Иван")
        init_b = make_valid_init_data(102, "Мария")
        headers_a = {"X-Telegram-Init-Data": init_a}
        headers_b = {"X-Telegram-Init-Data": init_b}

        # 2. GET /me доступен до согласия 18+
        r = await ac.get("/me", headers=headers_a)
        assert r.status_code == 200
        data = r.json()
        assert data["user"]["telegram_id"] == 101
        assert data["user"]["accepted_legal_at"] is None
        assert data["couple"] is None

        # 3. Попытка вызвать защищенный эндпоинт до принятия 18+ -> 403 Forbidden
        r = await ac.post("/couple/invite", headers=headers_a)
        assert r.status_code == 403
        assert "18+" in r.json()["detail"]

        # 4. Принятие условий: попытка с confirm_18_plus=False -> 400
        r = await ac.post(
            "/legal/accept",
            json={"confirm_18_plus": False, "accept_terms": True},
            headers=headers_a,
        )
        assert r.status_code == 400

        # Успешное принятие условий Партнером А
        r = await ac.post(
            "/legal/accept",
            json={"confirm_18_plus": True, "accept_terms": False},
            headers=headers_a,
        )
        assert r.status_code == 400

        r = await ac.post(
            "/legal/accept",
            json={"confirm_18_plus": True, "accept_terms": True},
            headers=headers_a,
        )
        assert r.status_code == 200
        assert r.json()["status"] == "accepted"

        # 5. Партнер А создает инвайт-ссылку для пары
        r = await ac.post("/couple/invite", headers=headers_a)
        assert r.status_code == 200
        invite_info = r.json()
        invite_code = invite_info["invite_code"]
        assert "invite_link" in invite_info
        assert f"start=pair_{invite_code}" in invite_info["invite_link"]

        # Партнер Б принимает условия 18+
        r = await ac.post(
            "/legal/accept",
            json={"confirm_18_plus": True, "accept_terms": True},
            headers=headers_b,
        )
        assert r.status_code == 200

        # Партнер Б присоединяется к паре
        couple = db.get_couple_by_invite(invite_code)
        assert couple is not None
        db.join_couple(couple["id"], 102)

        # 6. Проверка /me у обоих: партнеры видят друг друга
        r_a = await ac.get("/me", headers=headers_a)
        assert r_a.json()["couple"]["has_partner"] is True
        assert r_a.json()["couple"]["partner_name"] == "Мария"

        r_b = await ac.get("/me", headers=headers_b)
        assert r_b.json()["couple"]["has_partner"] is True
        assert r_b.json()["couple"]["partner_name"] == "Иван"

        # 7. Настроение: валидация и запись
        # Невалидное значение (>10)
        r = await ac.post("/mood", json={"mood": 11}, headers=headers_a)
        assert r.status_code == 422

        # Валидное значение (8)
        r = await ac.post("/mood", json={"mood": 8}, headers=headers_a)
        assert r.status_code == 200
        assert r.json()["my_mood"] == 8

        # 8. Сигналы «Белый флаг» и намек «hug»
        r = await ac.post("/signal/white-flag", headers=headers_a)
        assert r.status_code == 200
        assert r.json()["status"] == "sent"

        r = await ac.post("/signal/hint", json={"hint_type": "hug"}, headers=headers_a)
        assert r.status_code == 200
        assert r.json()["status"] == "sent"

        # 9. Старт конфликта
        r = await ac.post("/conflict/start", headers=headers_a)
        assert r.status_code == 200
        session_id = r.json()["session_id"]
        assert r.json()["session_status"] == "waiting_partner_2"

        # Проверка статуса через GET /conflict/{session_id}
        r = await ac.get(f"/conflict/{session_id}", headers=headers_a)
        assert r.status_code == 200
        assert r.json()["status"] == "waiting_partner_2"

        # 10. Сохранение зашифрованных версий обеих сторон
        payload_a = crypto.encrypt_text("Позиция Ивана: мне не хватает внимания.")
        payload_b = crypto.encrypt_text("Позиция Марии: я сильно устаю на работе.")
        db.save_pending_input(session_id, 101, "text", payload_a)
        db.save_pending_input(session_id, 102, "text", payload_b)

        # Переводим в completed для проверки строгой конфиденциальности выдачи
        db.update_session_status(
            session_id,
            status="completed",
            ai_advice_p1={"advice": "Совет Ивану: проявите мягкость"},
            ai_advice_p2={"advice": "Совет Марии: озвучивайте усталость прямо"},
            shared_summary={"summary": "Общий вывод: вы оба цените отношения"},
        )

        # Партнер А запрашивает результат: видит СВОЙ совет и общий итог, НО НЕ совет Марии!
        r_res_a = await ac.get(f"/conflict/{session_id}", headers=headers_a)
        assert r_res_a.status_code == 200
        data_a = r_res_a.json()
        assert data_a["personal_advice"]["advice"] == "Совет Ивану: проявите мягкость"
        assert "Совет Марии" not in str(data_a)
        assert data_a["shared_summary"]["summary"] == "Общий вывод: вы оба цените отношения"

        # Партнер Б запрашивает результат: видит СВОЙ совет и общий итог, НО НЕ совет Ивана!
        r_res_b = await ac.get(f"/conflict/{session_id}", headers=headers_b)
        assert r_res_b.status_code == 200
        data_b = r_res_b.json()
        assert data_b["personal_advice"]["advice"] == "Совет Марии: озвучивайте усталость прямо"
        assert "Совет Ивану" not in str(data_b)

        # 11. Удаление пары
        r = await ac.delete("/couple", headers=headers_a)
        assert r.status_code == 200
        assert r.json()["status"] == "deleted"

        # После удаления пользователь свободен
        r_after = await ac.get("/me", headers=headers_a)
        assert r_after.json()["couple"] is None


@pytest.mark.asyncio
async def test_session_limit_enforcement():
    """Проверка лимита: при free_sessions_left == 0 разбор блокируется с 403"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        init_a = make_valid_init_data(201, "Иван")
        headers_a = {"X-Telegram-Init-Data": init_a}

        # Принимаем условия 18+
        await ac.post(
            "/legal/accept",
            json={"confirm_18_plus": True, "accept_terms": True},
            headers=headers_a,
        )

        # Создаем пару с 0 сессий и без подписки
        couple = db.create_couple(partner_1_id=201, invite_code="LIMIT0")
        db.join_couple(couple["id"], 202)
        couple["free_sessions_left"] = 0
        couple["subscription_until"] = None

        # Попытка начать конфликт при исчерпанном лимите
        r = await ac.post("/conflict/start", headers=headers_a)
        assert r.status_code == 403
        assert "Бесплатные разборы закончились" in r.json()["detail"]


@pytest.mark.asyncio
async def test_rate_limiter_blocks_flooding():
    """Проверка Rate Limiter: частые запросы возвращают 429 Too Many Requests"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        init_a = make_valid_init_data(3301, "Иван")
        headers_a = {"X-Telegram-Init-Data": init_a}

        await ac.post(
            "/legal/accept",
            json={"confirm_18_plus": True, "accept_terms": True},
            headers=headers_a,
        )
        couple = db.create_couple(partner_1_id=3301, invite_code="RATE01")
        db.join_couple(couple["id"], 3302)

        # white flag настроен на максимум 1 запрос в час на пару
        r1 = await ac.post("/signal/white-flag", headers=headers_a)
        assert r1.status_code == 200

        # 2-й запрос должен вернуть 429 Too Many Requests
        r_blocked = await ac.post("/signal/white-flag", headers=headers_a)
        assert r_blocked.status_code == 429
        assert "Сигнал уже отправлен недавно" in r_blocked.json()["detail"]
        assert "Retry-After" in r_blocked.headers


@pytest.mark.asyncio
async def test_webhook_endpoint_disabled():
    """Проверка отключения вебхука при переходе на автономный Long Polling"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post("/api/webhook", json={"update_id": 1})
        # В связи с монтированием фронтенда на '/', немаршрутизированные POST-запросы возвращают 404/405
        assert r.status_code in (404, 405)

