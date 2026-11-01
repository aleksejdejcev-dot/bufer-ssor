import pytest
import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

import crypto
from repo.in_memory_repo import InMemoryRepo
from repo import set_repo
from ai_service import analyze_session
from main import app, require_legal_accepted
from providers.base import LLMProvider
from schemas import (
    AnalyzerOutput,
    PartnerAnalysis,
    SharedAnalysis,
    ToneAnalysis,
    HypothesisForOther,
    PartnerResponse,
    ActionScriptItem,
    SharedSummary,
    LeakCheckOutput,
)


class DummyLLMProvider(LLMProvider):
    provider_name: str = "fake"
    default_model: str = "fake-model"
    supports_audio: bool = False

    async def generate_json(
        self,
        system_prompt: str,
        user_content,
        json_schema: dict,
        pydantic_model,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        model=None,
        tag="llm",
        **kwargs,
    ):
        name = pydantic_model.__name__
        if name == "AnalyzerOutput":
            obj = AnalyzerOutput(
                risk_level="none",
                risk_reasons=[],
                partner_1=PartnerAnalysis(
                    topic="Быт",
                    key_facts=["Факт 1"],
                    feelings=["усталость"],
                    unmet_needs=["отдых"],
                    own_contribution="не выспался",
                    tone=ToneAnalysis(register="neutral", swearing=False, length="medium"),
                    secrets=[],
                    hypothesis_for_other=HypothesisForOther(likely_feelings=["растерянность"], likely_needs=["покой"]),
                ),
                partner_2=PartnerAnalysis(
                    topic="Быт",
                    key_facts=["Факт 2"],
                    feelings=["обида"],
                    unmet_needs=["внимание"],
                    own_contribution="",
                    tone=ToneAnalysis(register="neutral", swearing=False, length="medium"),
                    secrets=[],
                    hypothesis_for_other=HypothesisForOther(likely_feelings=["напряжение"], likely_needs=["принятие"]),
                ),
                shared=SharedAnalysis(
                    pattern="Усталость и взаимное недопонимание",
                    common_need="спокойствие и контакт",
                    neutral_topic="распределение вечернего времени",
                    ritual_ideas=["10 минут тишины", "вечерняя прогулка"],
                ),
            )
            return obj, {"finish_reason": "stop", "usage_tokens": 100, "blocked": False}

        elif name == "PartnerResponse":
            obj = PartnerResponse(
                validation="Понимаю ваше напряжение.",
                partner_perspective="Партнер чувствует перегруз.",
                blind_spot="Возможно, ожидания не были озвучены.",
                action_scripts=[
                    ActionScriptItem(label="Сказать спокойно", text="Давай распределим дела на вечер.", why="Снижает напряжение"),
                    ActionScriptItem(label="Сделать паузу", text="Возьмем 10 минут тишины.", why="Дает восстановиться"),
                ],
            )
            return obj, {"finish_reason": "stop", "usage_tokens": 100, "blocked": False}

        elif name == "SharedSummary":
            obj = SharedSummary(
                situation_overview="Оба партнера чувствуют напряжение в конце дня.",
                shared_advice="Договоритесь о коротком отдыхе перед обсуждением.",
                conversation_starter="Как прошел твой день?",
            )
            return obj, {"finish_reason": "stop", "usage_tokens": 100, "blocked": False}

        elif name == "LeakCheckOutput":
            obj = LeakCheckOutput(leak=False, reason=None, location=None)
            return obj, {"finish_reason": "stop", "usage_tokens": 50, "blocked": False}

        raise ValueError(f"Unknown model: {name}")

    async def transcribe(self, audio_bytes: bytes) -> str:
        raise NotImplementedError("Audio not supported")

    async def get_available_models(self):
        return ["fake-model"]

    async def check_model(self, model_name: str) -> bool:
        return True


import os
from repo.postgres_repo import PostgresRepo

def make_postgres_test_repo(url_env_var: str = "DATABASE_URL_TEST"):
    default_url = (
        "postgresql://app_user:app_user_dev_pass@127.0.0.1:5432/buffer_ssor_test"
        if url_env_var == "DATABASE_URL_APP_TEST"
        else "postgresql://buffer_admin:buffer_dev_pass@127.0.0.1:5432/buffer_ssor_test"
    )
    test_db_url = os.environ.get(url_env_var, default_url)
    if not any(h in test_db_url for h in ("localhost", "127.0.0.1")):
        raise ValueError(f"{url_env_var} должен быть на localhost/127.0.0.1")
    if not test_db_url.split("/")[-1].split("?")[0].endswith("_test"):
        raise ValueError(f"Имя тестовой базы обязано заканчиваться на _test: {test_db_url}")
    return PostgresRepo(database_url=test_db_url)


@pytest.fixture(params=[
    pytest.param("in_memory", id="in_memory"),
    pytest.param("postgres_admin", id="postgres_admin", marks=pytest.mark.postgres),
    pytest.param("postgres_app_user", id="postgres_app_user", marks=pytest.mark.postgres),
])
def lifecycle_repo(request):
    if request.param == "in_memory":
        r = InMemoryRepo()
        r.reset_state()
        set_repo(r)
        yield r
    elif request.param == "postgres_admin":
        r = make_postgres_test_repo("DATABASE_URL_TEST")
        r.reset_state()
        set_repo(r)
        yield r
        r.reset_state()
        r.close()
    elif request.param == "postgres_app_user":
        r = make_postgres_test_repo("DATABASE_URL_APP_TEST")
        r.reset_state()
        set_repo(r)
        yield r
        r.reset_state()
        r.close()



@pytest.mark.asyncio
async def test_free_sessions(lifecycle_repo):
    """
    C1: Бесплатный разбор списывается ровно один раз и только при completed;
    при failed и expired не списывается; при активной подписке не списывается.
    """
    repo = lifecycle_repo
    repo.upsert_user(1001, "Партнер 1")
    repo.upsert_user(1002, "Партнер 2")
    repo.accept_legal(1001)
    repo.accept_legal(1002)

    couple = repo.create_couple(1001, "INV_C1")
    repo.join_couple(couple["id"], 1002)
    initial_free = couple["free_sessions_left"]
    assert initial_free == 3

    # 1. Сценарий: failed - бесплатный разбор НЕ списывается
    session_failed = repo.create_conflict_session(couple["id"], 1001)
    repo.update_session_status(session_failed["id"], status="failed", completed_at=datetime.now(timezone.utc).isoformat())
    assert repo.get_couple_by_id(couple["id"])["free_sessions_left"] == initial_free

    # 2. Сценарий: expired - бесплатный разбор НЕ списывается
    session_expired = repo.create_conflict_session(couple["id"], 1001)
    repo.expire_session(session_expired["id"])
    assert repo.get_session_by_id(session_expired["id"])["status"] == "expired"
    assert repo.get_couple_by_id(couple["id"])["free_sessions_left"] == initial_free

    # 3. Сценарий: completed без подписки - бесплатный разбор списывается РОВНО 1 раз
    session_ok = repo.create_conflict_session(couple["id"], 1001)
    repo.save_pending_input(session_ok["id"], 1001, "text", crypto.encrypt_text("Позиция 1"))
    repo.save_pending_input(session_ok["id"], 1002, "text", crypto.encrypt_text("Позиция 2"))

    with patch("ai_service.get_provider", return_value=DummyLLMProvider()), \
         patch("bot.bot.send_message", new_callable=AsyncMock):
        await analyze_session(session_ok["id"])

    assert repo.get_session_by_id(session_ok["id"])["status"] == "completed"
    assert repo.get_couple_by_id(couple["id"])["free_sessions_left"] == initial_free - 1

    # 4. Сценарий: completed при активной подписке - бесплатный разбор НЕ списывается
    sub_dt = datetime.now(timezone.utc) + timedelta(days=30)
    if isinstance(repo, PostgresRepo):
        import uuid
        async def _set_sub():
            pool = await repo._get_pool()
            async with pool.acquire() as conn:
                await conn.execute("UPDATE couples SET subscription_until = $2 WHERE id = $1;", uuid.UUID(couple["id"]), sub_dt)
        repo._run_async(_set_sub())
    else:
        couple_updated = repo.get_couple_by_id(couple["id"])
        couple_updated["subscription_until"] = sub_dt.isoformat()

    session_sub = repo.create_conflict_session(couple["id"], 1001)
    repo.save_pending_input(session_sub["id"], 1001, "text", crypto.encrypt_text("Позиция 1"))
    repo.save_pending_input(session_sub["id"], 1002, "text", crypto.encrypt_text("Позиция 2"))

    free_before_sub_session = repo.get_couple_by_id(couple["id"])["free_sessions_left"]
    with patch("ai_service.get_provider", return_value=DummyLLMProvider()), \
         patch("bot.bot.send_message", new_callable=AsyncMock):
        await analyze_session(session_sub["id"])

    assert repo.get_session_by_id(session_sub["id"])["status"] == "completed"
    assert repo.get_couple_by_id(couple["id"])["free_sessions_left"] == free_before_sub_session


def test_payments_survive_delete(lifecycle_repo):
    """
    C2: После DELETE /couple строки payments остаются, couple_id NULL,
    открытого telegram_id в них нет.
    """
    repo = lifecycle_repo
    repo.upsert_user(2001, "Партнер 1")
    repo.upsert_user(2002, "Партнер 2")
    repo.accept_legal(2001)
    repo.accept_legal(2002)

    couple = repo.create_couple(2001, "INV_C2")
    repo.join_couple(couple["id"], 2002)

    payer_hash = crypto.hash_payer_id(2001, "secret_salt")
    pay = repo.save_payment(
        product="test_pack",
        amount=500,
        currency="RUB",
        provider_charge_id="charge_123",
        payer_hash=payer_hash,
        couple_id=couple["id"],
    )
    assert pay["couple_id"] == couple["id"]

    # Удаление пары
    repo.delete_couple_data(couple["id"])

    # Проверка выживания платежа
    payments = repo.get_payments_by_payer_hash(payer_hash)
    assert len(payments) == 1
    survived_pay = payments[0]

    assert survived_pay["id"] == pay["id"]
    assert survived_pay["couple_id"] is None
    # Проверка отсутствия открытого telegram_id в полях платежа
    for key, val in survived_pay.items():
        assert "2001" not in str(val), f"Открытый telegram_id обнаружен в поле {key}: {val}"
        assert "telegram_id" not in key.lower()


def test_no_push_to_partner_on_delete(lifecycle_repo):
    """
    C3: При удалении пары второму партнёру ничего не отправляется.
    """
    repo = lifecycle_repo
    p1 = repo.upsert_user(3001, "Партнер 1")
    p2 = repo.upsert_user(3002, "Партнер 2")
    repo.accept_legal(3001)
    repo.accept_legal(3002)

    couple = repo.create_couple(3001, "INV_C3")
    repo.join_couple(couple["id"], 3002)

    client = TestClient(app)
    app.dependency_overrides[require_legal_accepted] = lambda: p1

    with patch("bot.bot.send_message", new_callable=AsyncMock) as mock_send:
        resp = client.delete("/couple")
        assert resp.status_code == 200
        assert resp.json() == {"status": "deleted"}
        # Проверяем, что никаких push/уведомлений партнеру не отправлено
        mock_send.assert_not_called()

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_single_analysis_per_session(lifecycle_repo):
    """
    C4: При двух одновременных запусках analyze_session для одной сессии
    обработка выполняется один раз (атомарная смена статуса или блокировка строки);
    списание бесплатного разбора не удваивается.
    """
    repo = lifecycle_repo
    repo.upsert_user(4001, "Партнер 1")
    repo.upsert_user(4002, "Партнер 2")
    repo.accept_legal(4001)
    repo.accept_legal(4002)

    couple = repo.create_couple(4001, "INV_C4")
    repo.join_couple(couple["id"], 4002)
    free_before = couple["free_sessions_left"]

    session = repo.create_conflict_session(couple["id"], 4001)
    session_id = session["id"]

    repo.save_pending_input(session_id, 4001, "text", crypto.encrypt_text("Позиция 1"))
    repo.save_pending_input(session_id, 4002, "text", crypto.encrypt_text("Позиция 2"))

    analyzer_calls = 0

    class TrackingLLMProvider(DummyLLMProvider):
        async def generate_json(self, system_prompt, user_content, json_schema, pydantic_model, **kwargs):
            nonlocal analyzer_calls
            if pydantic_model.__name__ == "AnalyzerOutput":
                analyzer_calls += 1
                # Пауза для проверки гонки
                await asyncio.sleep(0.05)
            return await super().generate_json(system_prompt, user_content, json_schema, pydantic_model, **kwargs)

    provider = TrackingLLMProvider()

    with patch("ai_service.get_provider", return_value=provider), \
         patch("bot.bot.send_message", new_callable=AsyncMock):
        # Одновременный запуск двух задач анализа для одной и той же сессии
        await asyncio.gather(
            analyze_session(session_id),
            analyze_session(session_id),
        )

    # Проверка:
    # 1. Сессия перешла в completed
    assert repo.get_session_by_id(session_id)["status"] == "completed"
    # 2. Бесплатный разбор списался ровно один раз
    free_after = repo.get_couple_by_id(couple["id"])["free_sessions_left"]
    assert free_after == free_before - 1
    # 3. Анализатор был вызван ровно ОДИН раз (вторая задача была отклонена атомарным замком)
    assert analyzer_calls == 1
