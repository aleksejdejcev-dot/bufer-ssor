"""
backend/tests/test_yookassa_payments.py
Тесты интеграции с платежным шлюзом ЮKassa:
1. Создание платежа в БД со статусом pending.
2. Идемпотентность активации подписки (повторные вебхуки не продлевают подписку дважды).
3. Корректность продления subscription_until:
   - от текущей даты (если подписки не было или она истекла);
   - от даты действующей подписки (если подписка еще активна).
4. Эндпоинты API /payment/create и /api/webhook/yookassa с верификацией статуса.
"""

import os
import json
import time
import uuid
import hmac
import hashlib
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, AsyncMock

import pytest
from httpx import AsyncClient, ASGITransport

from config import settings
from repo import set_repo, get_repo
from repo.in_memory_repo import InMemoryRepo
from repo.postgres_repo import PostgresRepo
from main import app


def make_postgres_test_repo(url_env_var: str = "DATABASE_URL_TEST"):
    default_url = (
        "postgresql://app_user:app_user_dev_pass@127.0.0.1:5432/buffer_ssor_test"
        if url_env_var == "DATABASE_URL_APP_TEST"
        else "postgresql://buffer_admin:buffer_dev_pass@127.0.0.1:5432/buffer_ssor_test"
    )
    test_db_url = os.environ.get(url_env_var, default_url)
    if not any(h in test_db_url for h in ("localhost", "127.0.0.1")):
        raise ValueError(f"{url_env_var} должен указывать исключительно на localhost / 127.0.0.1")
    dbname = test_db_url.split("/")[-1].split("?")[0]
    if not dbname.endswith("_test"):
        raise ValueError(f"Имя тестовой базы обязано заканчиваться на _test, получено: {dbname}")
    return PostgresRepo(database_url=test_db_url)


@pytest.fixture(params=[
    pytest.param("in_memory", id="in_memory"),
    pytest.param("postgres", id="postgres", marks=pytest.mark.postgres),
])
def payment_repo(request):
    if request.param == "in_memory":
        r = InMemoryRepo()
        r.reset_state()
        set_repo(r)
        yield r
    else:
        r = make_postgres_test_repo("DATABASE_URL_TEST")
        r.reset_state()
        set_repo(r)
        yield r
        r.reset_state()
        r.close()


def make_auth_header(telegram_id: int, first_name: str = "Тестер") -> str:
    auth_date = str(int(time.time()))
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
# 1. Тест создания и получения платежа в репозитории
# ==============================================================================

def test_repo_create_and_get_payment(payment_repo):
    payment_repo.upsert_user(9001, "Партнер 1")
    payment_repo.upsert_user(9002, "Партнер 2")
    c = payment_repo.create_couple(9001, "INVITE9001")
    payment_repo.join_couple(c["id"], 9002)

    pay_id = f"pay_{uuid.uuid4().hex[:12]}"
    res = payment_repo.create_payment(
        couple_id=c["id"],
        user_id=9001,
        payment_id=pay_id,
        amount=Decimal("199.00"),
        currency="RUB",
        product="month_sub",
    )

    assert res is not None
    assert res["provider_charge_id"] == pay_id
    assert res["status"] == "pending"
    assert float(res["amount"]) == 199.0

    fetched = payment_repo.get_payment(pay_id)
    assert fetched is not None
    assert fetched["provider_charge_id"] == pay_id
    assert fetched["status"] == "pending"


# ==============================================================================
# 2. Тест идемпотентности активации подписки
# ==============================================================================

def test_activate_subscription_idempotency(payment_repo):
    payment_repo.upsert_user(9011, "Партнер 1")
    payment_repo.upsert_user(9012, "Партнер 2")
    c = payment_repo.create_couple(9011, "INVITE9011")
    payment_repo.join_couple(c["id"], 9012)

    pay_id = f"pay_{uuid.uuid4().hex[:12]}"
    payment_repo.create_payment(
        couple_id=c["id"],
        user_id=9011,
        payment_id=pay_id,
        amount=Decimal("199.00"),
    )

    # Первый вызов активации — успех
    act1 = payment_repo.activate_subscription_for_couple(
        couple_id=c["id"],
        payment_id=pay_id,
        days=30,
    )
    assert act1 is not None
    first_until = act1["subscription_until"]
    assert first_until is not None

    # Проверяем, что статус платежа в БД стал succeeded
    pay_record = payment_repo.get_payment(pay_id)
    assert pay_record["status"] == "succeeded"

    # Второй вызов активации с тем же payment_id (повторный вебхук) — должен вернуть None
    act2 = payment_repo.activate_subscription_for_couple(
        couple_id=c["id"],
        payment_id=pay_id,
        days=30,
    )
    assert act2 is None, "Повторный вебхук с тем же payment_id не должен повторно продлевать подписку"

    # Дата подписки в паре не должна измениться
    updated_couple = payment_repo.get_couple_by_id(c["id"])
    assert updated_couple["subscription_until"] == first_until


# ==============================================================================
# 3. Тест логики продления (от now или от активной даты)
# ==============================================================================

def test_subscription_extension_logic(payment_repo):
    payment_repo.upsert_user(9021, "Партнер 1")
    payment_repo.upsert_user(9022, "Партнер 2")
    c = payment_repo.create_couple(9021, "INVITE9021")
    payment_repo.join_couple(c["id"], 9022)

    now = datetime.now(timezone.utc)

    # Сценарий A: Подписки еще не было (subscription_until = None)
    pay_1 = f"pay_{uuid.uuid4().hex[:12]}"
    payment_repo.create_payment(c["id"], 9021, pay_1, Decimal("199.00"))
    act_1 = payment_repo.activate_subscription_for_couple(c["id"], pay_1, days=30)
    assert act_1 is not None
    dt_1 = datetime.fromisoformat(act_1["subscription_until"])
    if dt_1.tzinfo is None:
        dt_1 = dt_1.replace(tzinfo=timezone.utc)
    diff_days_1 = (dt_1 - now).total_seconds() / 86400
    assert 29.8 <= diff_days_1 <= 30.2

    # Сценарий B: Подписка уже активна (+30 дней). Второй платеж должен продлить на +30 дней от dt_1 (+60 дней от now)
    pay_2 = f"pay_{uuid.uuid4().hex[:12]}"
    payment_repo.create_payment(c["id"], 9022, pay_2, Decimal("199.00"))
    act_2 = payment_repo.activate_subscription_for_couple(c["id"], pay_2, days=30)
    assert act_2 is not None
    dt_2 = datetime.fromisoformat(act_2["subscription_until"])
    if dt_2.tzinfo is None:
        dt_2 = dt_2.replace(tzinfo=timezone.utc)
    diff_days_2 = (dt_2 - now).total_seconds() / 86400
    assert 59.8 <= diff_days_2 <= 60.2


# ==============================================================================
# 4. Тест эндпоинта POST /payment/create через FastAPI
# ==============================================================================

@pytest.mark.asyncio
async def test_api_payment_create_endpoint():
    test_repo = InMemoryRepo()
    test_repo.reset_state()
    set_repo(test_repo)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        tg_id = 9031
        init_header = make_auth_header(tg_id, "Плательщик")

        # Принимаем соглашение 18+
        await client.post(
            "/legal/accept",
            headers={"X-Telegram-Init-Data": init_header},
            json={"confirm_18_plus": True, "accept_terms": True},
        )

        # Создаем пару
        inv_res = await client.post(
            "/couple/invite",
            headers={"X-Telegram-Init-Data": init_header},
        )
        assert inv_res.status_code == 200

        mock_yoo_resp = {
            "id": "2d9b6a12-000f-5000-8000-1db0f269a9b2",
            "status": "pending",
            "paid": False,
            "amount": {"value": "199.00", "currency": "RUB"},
            "confirmation": {
                "type": "redirect",
                "confirmation_url": "https://yoomoney.ru/checkout/payments/v2/contract?orderId=2d9b6a12",
            },
        }

        with patch("main.create_yookassa_payment", new=AsyncMock(return_value=mock_yoo_resp)):
            resp = await client.post(
                "/payment/create",
                headers={"X-Telegram-Init-Data": init_header},
                json={"plan": "month_sub"},
            )

            assert resp.status_code == 200
            data = resp.json()
            assert data["payment_id"] == "2d9b6a12-000f-5000-8000-1db0f269a9b2"
            assert "https://yoomoney.ru" in data["confirmation_url"]


# ==============================================================================
# 5. Тест эндпоинта вебхука /api/webhook/yookassa с верификацией
# ==============================================================================

@pytest.mark.asyncio
async def test_api_webhook_verification_and_activation():
    test_repo = InMemoryRepo()
    test_repo.reset_state()
    set_repo(test_repo)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        tg_id = 9041
        init_header = make_auth_header(tg_id, "ПартнерВХ")

        await client.post(
            "/legal/accept",
            headers={"X-Telegram-Init-Data": init_header},
            json={"confirm_18_plus": True, "accept_terms": True},
        )

        inv_res = await client.post(
            "/couple/invite",
            headers={"X-Telegram-Init-Data": init_header},
        )
        assert inv_res.status_code == 200

        # Получаем couple_id
        me_res = await client.get("/me", headers={"X-Telegram-Init-Data": init_header})
        couple_id = me_res.json()["couple"]["id"]

        payment_id = f"2d9b6_{uuid.uuid4().hex[:12]}"

        # Создаем pending платеж в БД
        test_repo.create_payment(
            couple_id=couple_id,
            user_id=tg_id,
            payment_id=payment_id,
            amount=Decimal("199.00"),
        )

        # Мокируем ответ YooKassa при прямой проверке GET /v3/payments/{id}
        verified_yoo_obj = {
            "id": payment_id,
            "status": "succeeded",
            "paid": True,
            "amount": {"value": "199.00", "currency": "RUB"},
            "metadata": {
                "couple_id": couple_id,
                "plan": "month_sub",
            },
        }

        webhook_payload = {
            "type": "notification",
            "event": "payment.succeeded",
            "object": {
                "id": payment_id,
                "status": "succeeded",
            },
        }

        with patch("main.get_yookassa_payment", new=AsyncMock(return_value=verified_yoo_obj)):
            with patch("main.send_subscription_success", new=AsyncMock()) as mock_notify:
                # Первый вебхук
                wh_resp1 = await client.post("/api/webhook/yookassa", json=webhook_payload)
                assert wh_resp1.status_code == 200
                assert wh_resp1.json()["status"] == "ok"

                # Проверяем, что вызов уведомления произошел
                mock_notify.assert_called()

                # Повторный вебхук (проверка идемпотентности)
                wh_resp2 = await client.post("/api/webhook/yookassa", json=webhook_payload)
                assert wh_resp2.status_code == 200
                assert wh_resp2.json()["status"] == "ok"

        # Проверяем в /me, что подписка действительно стала активной
        me_after = await client.get("/me", headers={"X-Telegram-Init-Data": init_header})
        c_after = me_after.json()["couple"]
        assert c_after["subscription_until"] is not None
