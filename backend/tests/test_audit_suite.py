"""
Полный набор тестов (17 обязательных проверок Этапа 3.6).
Каждый тест строго проверяет одно ключевое требование безопасности и логики.
"""

from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from fastapi.testclient import TestClient
from aiogram.types import Message, User, Chat, Voice
from aiogram.filters import CommandObject

from main import app, get_current_user
from repo import set_repo
from repo.in_memory_repo import InMemoryRepo
from repo.postgres_repo import PostgresRepo
from repo.base import Repository
from bot import handle_start, handle_conflict_input
from schemas import (
    PartnerResponse,
    SharedSummary,
    ActionScriptItem,
    AgreedRitual,
    AnalyzerOutput,
    PartnerAnalysis,
    SharedAnalysis,
    ToneAnalysis,
    HypothesisForOther,
)
from validators import (
    validate_ritual_action_scripts_consistency,
    align_action_scripts_with_ritual,
)
from config.safety_messages import get_high_risk_message
from leak_guard import check_card_lemma_leaks
from ai_service import analyze_session
from providers.base import LLMProvider
import crypto


class FakeLLM(LLMProvider):
    provider_name: str = "gigachat"
    supports_audio: bool = False

    def __init__(self, high_risk: bool = False):
        self.high_risk = high_risk

    async def generate_json(self, *args, **kwargs):
        tag = kwargs.get("tag") or kwargs.get("role") or ""
        pydantic_model = kwargs.get("pydantic_model")
        if tag == "analyzer" or pydantic_model == AnalyzerOutput or "analyzer" in str(tag) or "Анализатор" in str(args):
            risk = "high" if self.high_risk else "none"
            out = AnalyzerOutput(
                risk_level=risk,
                risk_reasons=["Тестовая угроза"] if self.high_risk else [],
                partner_1=PartnerAnalysis(
                    topic="Тема", key_facts=[], feelings=[], unmet_needs=[], own_contribution="",
                    tone=ToneAnalysis(register="formal", swearing=False, length="medium"),
                    hypothesis_for_other=HypothesisForOther(likely_feelings=[], likely_needs=[]),
                    sparse=False,
                ),
                partner_2=PartnerAnalysis(
                    topic="Тема", key_facts=[], feelings=[], unmet_needs=[], own_contribution="",
                    tone=ToneAnalysis(register="formal", swearing=False, length="medium"),
                    hypothesis_for_other=HypothesisForOther(likely_feelings=[], likely_needs=[]),
                    sparse=False,
                ),
                shared=SharedAnalysis(
                    pattern="Паттерн", common_need="Потребность", neutral_topic=None, ritual_ideas=[], agreed_ritual=None,
                ),
            )
            return out, {"finish_reason": "stop", "usage_tokens": 100, "blocked": False}
        return {}, {"finish_reason": "stop", "usage_tokens": 100, "blocked": False}

    async def transcribe(self, audio_bytes: bytes) -> str:
        raise NotImplementedError

    async def check_model(self) -> bool:
        return True

    async def get_available_models(self):
        return ["GigaChat-3-Ultra"]


# 1. test_dev_endpoints_absent
def test_dev_endpoints_absent():
    client = TestClient(app)
    assert client.get("/api/dev/init-data").status_code == 404
    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404
    assert client.get("/openapi.json").status_code == 404


# 2. test_idor_conflict_card
def test_idor_conflict_card():
    test_repo = InMemoryRepo()
    set_repo(test_repo)
    u1 = test_repo.upsert_user(1201, "Партнер А")
    u2 = test_repo.upsert_user(1202, "Партнер Б")
    test_repo.accept_legal(1201)
    test_repo.accept_legal(1202)
    couple = test_repo.create_couple(1201, "INV1201")
    test_repo.join_couple(couple["id"], 1202)
    session = test_repo.create_conflict_session(couple["id"], 1201)
    test_repo.save_analysis_results(
        session_id=session["id"],
        results={
            "partner_1_card": {"validation": "Секретный совет для А", "action_scripts": []},
            "partner_2_card": {"validation": "Совет для Б", "action_scripts": []},
            "shared_summary": {"situation_overview": "Общий итог"},
        },
        risk_level="none",
        completed_at="2026-10-31T12:00:00Z",
    )

    # Партнер Б запрашивает сессию
    app.dependency_overrides[get_current_user] = lambda: u2
    try:
        client = TestClient(app)
        resp = client.get(f"/conflict/{session['id']}")
        assert resp.status_code == 200
        data = resp.json()
        assert "Секретный совет для А" not in str(data)
        assert data["personal_advice"]["validation"] == "Совет для Б"
    finally:
        app.dependency_overrides.clear()


# 3. test_idor_foreign_session
def test_idor_foreign_session():
    test_repo = InMemoryRepo()
    set_repo(test_repo)
    u1 = test_repo.upsert_user(1203, "Партнер 1")
    u2 = test_repo.upsert_user(1204, "Партнер 2")
    u3 = test_repo.upsert_user(1205, "Посторонний")
    test_repo.accept_legal(1203)
    test_repo.accept_legal(1204)
    test_repo.accept_legal(1205)
    couple = test_repo.create_couple(1203, "INV1203")
    test_repo.join_couple(couple["id"], 1204)
    session = test_repo.create_conflict_session(couple["id"], 1203)

    app.dependency_overrides[get_current_user] = lambda: u3
    try:
        client = TestClient(app)
        resp = client.get(f"/conflict/{session['id']}")
        assert resp.status_code == 403
        assert "запрещен" in resp.json()["detail"].lower()
    finally:
        app.dependency_overrides.clear()


# 4. test_raw_input_purged_after_analysis
@pytest.mark.asyncio
async def test_raw_input_purged_after_analysis():
    test_repo = InMemoryRepo()
    set_repo(test_repo)
    u1 = test_repo.upsert_user(1206, "P1")
    u2 = test_repo.upsert_user(1207, "P2")
    test_repo.accept_legal(1206)
    test_repo.accept_legal(1207)
    couple = test_repo.create_couple(1206, "INV1206")
    test_repo.join_couple(couple["id"], 1207)
    session = test_repo.create_conflict_session(couple["id"], 1206)

    test_repo.save_pending_input(session["id"], 1206, "text", crypto.encrypt_text("Текст 1"))
    test_repo.save_pending_input(session["id"], 1207, "text", crypto.encrypt_text("Текст 2"))
    assert test_repo.count_pending_inputs(session["id"]) == 2

    fake = FakeLLM(high_risk=True)
    with patch("ai_service.get_provider", return_value=fake), \
         patch("bot.bot.send_message", new_callable=AsyncMock):
        await analyze_session(session["id"])

    # После завершения в pending_inputs 0 записей
    assert test_repo.count_pending_inputs(session["id"]) == 0


# 5. test_consent_gate_all_endpoints
def test_consent_gate_all_endpoints():
    test_repo = InMemoryRepo()
    set_repo(test_repo)
    u = test_repo.upsert_user(1208, "NoConsent")
    assert u["accepted_legal_at"] is None

    app.dependency_overrides[get_current_user] = lambda: u
    try:
        client = TestClient(app)
        assert client.post("/couple/invite").status_code == 403
        assert client.post("/conflict/start").status_code == 403
        assert client.post("/mood", json={"mood": 5}).status_code == 403
        assert client.post("/signal/white-flag").status_code == 403
        assert client.post("/signal/hint", json={"hint_type": "hug"}).status_code == 403
        assert client.delete("/couple").status_code == 403
        assert client.delete("/history").status_code == 403
    finally:
        app.dependency_overrides.clear()


# 6. test_high_risk_same_text
def test_high_risk_same_text():
    m1 = get_high_risk_message()
    m2 = get_high_risk_message()
    assert m1 == m2
    assert "112" in m1
    assert "8-800-7000-600" in m1


# 7. test_high_risk_no_downgrade
@pytest.mark.asyncio
async def test_high_risk_no_downgrade():
    test_repo = InMemoryRepo()
    set_repo(test_repo)
    u1 = test_repo.upsert_user(1209, "A")
    u2 = test_repo.upsert_user(1210, "B")
    test_repo.accept_legal(1209)
    test_repo.accept_legal(1210)
    couple = test_repo.create_couple(1209, "INV1209")
    test_repo.join_couple(couple["id"], 1210)
    session = test_repo.create_conflict_session(couple["id"], 1209)

    test_repo.save_pending_input(session["id"], 1209, "text", crypto.encrypt_text("Угрозы насилием"))
    test_repo.save_pending_input(session["id"], 1210, "text", crypto.encrypt_text("Страх за жизнь"))

    fake = FakeLLM(high_risk=True)
    with patch("ai_service.get_provider", return_value=fake), \
         patch("bot.bot.send_message", new_callable=AsyncMock):
        await analyze_session(session["id"])

    s = test_repo.get_session_by_id(session["id"])
    assert s["status"] == "completed"
    assert s["risk_level"] == "high"
    assert s["ai_advice_p1"]["validation"] == get_high_risk_message()
    assert s["ai_advice_p2"]["validation"] == get_high_risk_message()


# 8. test_single_use_invite
@pytest.mark.asyncio
async def test_single_use_invite():
    test_repo = InMemoryRepo()
    set_repo(test_repo)
    u1 = test_repo.upsert_user(1211, "A")
    u2 = test_repo.upsert_user(1212, "B")
    u3 = test_repo.upsert_user(1213, "C")
    test_repo.accept_legal(1211)
    test_repo.accept_legal(1212)
    test_repo.accept_legal(1213)

    couple = test_repo.create_couple(1211, "SINGLE12")
    # Первый вход успешен
    test_repo.join_couple(couple["id"], 1212)

    msg = MagicMock(spec=Message)
    msg.from_user = User(id=1213, is_bot=False, first_name="C")
    msg.chat = Chat(id=1213, type="private")
    msg.answer = AsyncMock()
    cmd = CommandObject(prefix="/", command="start", args="pair_SINGLE12")

    await handle_start(msg, cmd)
    reply = msg.answer.call_args[0][0]
    assert "уже был использован" in reply


# 9. test_invite_ttl
@pytest.mark.asyncio
async def test_invite_ttl():
    test_repo = InMemoryRepo()
    set_repo(test_repo)
    u1 = test_repo.upsert_user(1214, "A")
    u2 = test_repo.upsert_user(1215, "B")
    test_repo.accept_legal(1214)
    test_repo.accept_legal(1215)

    couple = test_repo.create_couple(1214, "EXPTTL01")
    couple["invite_expires_at"] = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()

    msg = MagicMock(spec=Message)
    msg.from_user = User(id=1215, is_bot=False, first_name="B")
    msg.chat = Chat(id=1215, type="private")
    msg.answer = AsyncMock()
    cmd = CommandObject(prefix="/", command="start", args="pair_EXPTTL01")

    await handle_start(msg, cmd)
    assert "Срок действия инвайта истёк" in msg.answer.call_args[0][0]


# 10. test_invite_bruteforce_ban
@pytest.mark.asyncio
async def test_invite_bruteforce_ban():
    test_repo = InMemoryRepo()
    set_repo(test_repo)
    u = test_repo.upsert_user(1216, "Attacker")
    test_repo.accept_legal(1216)

    for i in range(5):
        msg = MagicMock(spec=Message)
        msg.from_user = User(id=1216, is_bot=False, first_name="Attacker")
        msg.chat = Chat(id=1216, type="private")
        msg.answer = AsyncMock()
        cmd = CommandObject(prefix="/", command="start", args=f"pair_WRONG{i}")
        await handle_start(msg, cmd)

    # 6-я попытка
    msg6 = MagicMock(spec=Message)
    msg6.from_user = User(id=1216, is_bot=False, first_name="Attacker")
    msg6.chat = Chat(id=1216, type="private")
    msg6.answer = AsyncMock()
    cmd6 = CommandObject(prefix="/", command="start", args="pair_SOMETHING")
    await handle_start(msg6, cmd6)

    assert "Ввод заблокирован" in msg6.answer.call_args[0][0]


# 11. test_rate_limits
def test_rate_limits():
    test_repo = InMemoryRepo()
    set_repo(test_repo)
    u1 = test_repo.upsert_user(1217, "P1")
    u2 = test_repo.upsert_user(1218, "P2")
    test_repo.accept_legal(1217)
    test_repo.accept_legal(1218)
    couple = test_repo.create_couple(1217, "INVRATE1")
    test_repo.join_couple(couple["id"], 1218)

    app.dependency_overrides[get_current_user] = lambda: u1
    try:
        client = TestClient(app)
        with patch("main.send_white_flag", new_callable=AsyncMock):
            # white-flag: 1 per hour
            assert client.post("/signal/white-flag").status_code == 200
            assert client.post("/signal/white-flag").status_code == 429

        # conflict/start: 3 per hour
        for _ in range(3):
            r = client.post("/conflict/start")
            assert r.status_code == 200
            test_repo.update_session_status(r.json()["session_id"], "completed")
        assert client.post("/conflict/start").status_code == 429
    finally:
        app.dependency_overrides.clear()


# 12. test_ritual_consistency
def test_ritual_consistency():
    ritual = AgreedRitual(
        name="Пауза", duration_minutes=15, when="Вечером", format="15 минут",
        serves_partner_1_need="Отдых", serves_partner_2_need="Покой",
    )
    scripts = [
        ActionScriptItem(label="1", text="Давай возьмем 20 минут паузы."),
        ActionScriptItem(label="2", text="Поговорим."),
    ]
    errs = validate_ritual_action_scripts_consistency(scripts, ritual)
    assert len(errs) > 0

    aligned = align_action_scripts_with_ritual(scripts, ritual)
    assert "15 минут" in aligned[0].text
    assert "20 минут" not in aligned[0].text


# 13. test_gigachat_rejects_audio
@pytest.mark.asyncio
async def test_gigachat_rejects_audio():
    test_repo = InMemoryRepo()
    set_repo(test_repo)
    u1 = test_repo.upsert_user(1219, "VoiceUser")
    test_repo.accept_legal(1219)
    couple = test_repo.create_couple(1219, "INVVOICE")
    test_repo.join_couple(couple["id"], 1220)
    session = test_repo.create_conflict_session(couple["id"], 1219)

    msg = MagicMock(spec=Message)
    msg.from_user = User(id=1219, is_bot=False, first_name="VoiceUser")
    msg.chat = Chat(id=1219, type="private")
    msg.voice = Voice(file_id="v1", file_unique_id="vu1", duration=30, file_size=1000)
    msg.text = None
    msg.answer = AsyncMock()

    no_audio_prov = FakeLLM()
    assert no_audio_prov.supports_audio is False

    with patch("bot.get_provider", return_value=no_audio_prov), \
         patch("bot.bot.download", new_callable=AsyncMock) as mock_dl:
        await handle_conflict_input(msg)
        assert "Голосовые пока недоступны, отправь, пожалуйста, текстом" in msg.answer.call_args[0][0]
        mock_dl.assert_not_called()


# 14. test_retention_purge
def test_retention_purge():
    test_repo = InMemoryRepo()
    set_repo(test_repo)
    u1 = test_repo.upsert_user(1221, "P1")
    test_repo.accept_legal(1221)
    couple = test_repo.create_couple(1221, "INVRET1")

    # Сессия старше 30 дней
    s = test_repo.create_conflict_session(couple["id"], 1221)
    old_time = (datetime.now(timezone.utc) - timedelta(days=32)).isoformat()
    test_repo.save_analysis_results(
        session_id=s["id"],
        results={"partner_1_card": {"val": "1"}, "shared_summary": {}},
        risk_level="none",
        completed_at=old_time,
    )

    stats = test_repo.purge_expired_data(days_retention=30, hours_raw_ttl=48)
    assert stats["purged_sessions"] == 1
    assert test_repo.get_session_by_id(s["id"]) is None


# 15. test_delete_flow
def test_delete_flow():
    test_repo = InMemoryRepo()
    set_repo(test_repo)
    u1 = test_repo.upsert_user(1222, "P1")
    u2 = test_repo.upsert_user(1223, "P2")
    test_repo.accept_legal(1222)
    test_repo.accept_legal(1223)
    couple = test_repo.create_couple(1222, "INVDEL1")
    test_repo.join_couple(couple["id"], 1223)

    test_repo.save_payment(
        product="test", amount=100, currency="RUB",
        provider_charge_id="ch_1222", payer_hash="h1222", couple_id=couple["id"]
    )

    app.dependency_overrides[get_current_user] = lambda: u1
    try:
        client = TestClient(app)
        # DELETE /history: сессии стираются, пара остается
        r_hist = client.delete("/history")
        assert r_hist.status_code == 200
        assert test_repo.get_couple_by_id(couple["id"]) is not None

        # DELETE /couple: пара и пользователи удаляются, payments отвязываются
        r_cpl = client.delete("/couple")
        assert r_cpl.status_code == 200
        assert test_repo.get_couple_by_id(couple["id"]) is None
        assert test_repo.get_user(1222) is None
        assert test_repo.get_user(1223) is None
        payments = test_repo.get_payments_by_payer_hash("h1222")
        assert payments[0]["couple_id"] is None
    finally:
        app.dependency_overrides.clear()


# 16. test_repo_contract
def test_repo_contract():
    in_mem_methods = {m for m in dir(InMemoryRepo) if not m.startswith("_")}
    postgres_methods = {m for m in dir(PostgresRepo) if not m.startswith("_")}
    base_methods = {m for m in dir(Repository) if not m.startswith("_")}

    missing_in_mem = base_methods - in_mem_methods
    missing_postgres = base_methods - postgres_methods
    assert not missing_in_mem, f"InMemoryRepo misses: {missing_in_mem}"
    assert not missing_postgres, f"PostgresRepo misses: {missing_postgres}"


# 17. test_leak_guard_lemmas
def test_leak_guard_lemmas():
    card_text = "Партнер говорит, что его коллега Виктория просто знакомая."
    leaks = check_card_lemma_leaks(
        card_text=card_text,
        other_private_facts=["коллега Виктория"],
        other_secrets=["тайная переписка"],
        recipient_raw="Я ничего не знаю",
        recipient_facts=[],
    )
    assert len(leaks) > 0
    assert any("виктория" in item.lower() or "коллега" in item.lower() for item in leaks)
