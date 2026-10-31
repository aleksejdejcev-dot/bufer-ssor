from datetime import datetime, timezone, timedelta
import pytest
from fastapi.testclient import TestClient

from main import app, get_current_user
from repo import set_repo
from repo.in_memory_repo import InMemoryRepo
import crypto


def test_retention_purge_flow():
    """Проверка очистки сессий и зависших исходников по политике retention."""
    test_repo = InMemoryRepo()
    set_repo(test_repo)

    now = datetime.now(timezone.utc)
    old_completed_time = (now - timedelta(days=35)).isoformat()
    recent_completed_time = (now - timedelta(days=10)).isoformat()
    old_input_time = (now - timedelta(hours=55)).isoformat()

    # Создаем пару
    u1 = test_repo.upsert_user(601, "Игорь")
    u2 = test_repo.upsert_user(602, "Елена")
    test_repo.accept_legal(601)
    test_repo.accept_legal(602)
    couple = test_repo.create_couple(601, "INV601")
    test_repo.join_couple(couple["id"], 602)

    # 1. Сессия, завершенная 35 дней назад (должна быть очищена)
    s_old = test_repo.create_conflict_session(couple["id"], 601)
    test_repo.save_analysis_results(
        session_id=s_old["id"],
        results={"partner_1_card": {"validation": "Тест"}, "shared_summary": {"overview": "Ок"}},
        risk_level="none",
        completed_at=old_completed_time,
    )

    # 2. Сессия, завершенная 10 дней назад (НЕ должна быть очищена)
    s_recent = test_repo.create_conflict_session(couple["id"], 601)
    test_repo.save_analysis_results(
        session_id=s_recent["id"],
        results={"partner_1_card": {"validation": "Свежая"}, "shared_summary": {"overview": "Свежий"}},
        risk_level="none",
        completed_at=recent_completed_time,
    )

    # 3. Зависший pending_input старше 48 часов
    s_stuck = test_repo.create_conflict_session(couple["id"], 601)
    test_repo.save_pending_input(
        session_id=s_stuck["id"],
        author_telegram_id=601,
        kind="text",
        payload_encrypted=crypto.encrypt_text("Зависший текст"),
    )
    # Искусственно состарим дату создания pending_input
    for inp in test_repo.pending_inputs.values():
        if inp["session_id"] == s_stuck["id"]:
            inp["created_at"] = old_input_time
            inp["expires_at"] = old_input_time

    # Выполняем purge_expired_data
    stats = test_repo.purge_expired_data(days_retention=30, hours_raw_ttl=48)
    assert stats["purged_sessions"] == 1
    assert stats["purged_inputs"] == 1

    # Проверяем старую сессию: статус purged_by_retention, советы обнулены
    purged_s = test_repo.get_session_by_id(s_old["id"])
    assert purged_s["status"] == "purged_by_retention"
    assert purged_s["ai_advice_p1"] is None
    assert purged_s["ai_advice_p2"] is None
    assert purged_s["shared_summary"] is None

    # Проверяем свежую сессию: не затронута
    kept_s = test_repo.get_session_by_id(s_recent["id"])
    assert kept_s["status"] == "completed"
    assert kept_s["ai_advice_p1"] is not None

    # Проверяем, что зависший инпут удален
    assert test_repo.count_pending_inputs(s_stuck["id"]) == 0


def test_delete_history_endpoint():
    """Проверка DELETE /history: сессии удаляются, пользователи и пара остаются."""
    test_repo = InMemoryRepo()
    set_repo(test_repo)

    u1 = test_repo.upsert_user(701, "Максим")
    u2 = test_repo.upsert_user(702, "Ольга")
    test_repo.accept_legal(701)
    test_repo.accept_legal(702)
    couple = test_repo.create_couple(701, "INV701")
    test_repo.join_couple(couple["id"], 702)

    # Создаем сессию с инпутами
    session = test_repo.create_conflict_session(couple["id"], 701)
    test_repo.save_pending_input(session["id"], 701, "text", crypto.encrypt_text("Текст"))

    app.dependency_overrides[get_current_user] = lambda: u1
    try:
        client = TestClient(app)
        resp = client.delete("/history")
        assert resp.status_code == 200
        assert resp.json()["status"] == "history_deleted"

        # Сессия удалена
        assert test_repo.get_session_by_id(session["id"]) is None
        assert test_repo.count_pending_inputs(session["id"]) == 0

        # Пара и пользователи сохранены
        assert test_repo.get_couple_by_id(couple["id"]) is not None
        assert test_repo.get_user(701) is not None
        assert test_repo.get_user(702) is not None
    finally:
        app.dependency_overrides.clear()


def test_delete_couple_endpoint_unlinks_payments_and_deletes_users():
    """Проверка DELETE /couple: пара удаляется, профили обоих пользователей стираются,
    платежи отвязываются (couple_id = NULL)."""
    test_repo = InMemoryRepo()
    set_repo(test_repo)

    u1 = test_repo.upsert_user(801, "Артем")
    u2 = test_repo.upsert_user(802, "Алиса")
    test_repo.accept_legal(801)
    test_repo.accept_legal(802)
    couple = test_repo.create_couple(801, "INV801")
    test_repo.join_couple(couple["id"], 802)

    # Сохраняем платеж
    payment = test_repo.save_payment(
        product="extra_sessions_5",
        amount=490,
        currency="RUB",
        provider_charge_id="charge_801_abc",
        payer_hash="hash_801",
        couple_id=couple["id"],
    )
    assert payment["couple_id"] == couple["id"]

    app.dependency_overrides[get_current_user] = lambda: u1
    try:
        client = TestClient(app)
        resp = client.delete("/couple")
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"

        # Пара удалена
        assert test_repo.get_couple_by_id(couple["id"]) is None

        # Профили пользователей стёрты
        assert test_repo.get_user(801) is None
        assert test_repo.get_user(802) is None

        # Платеж сохранился, но couple_id стал None
        payments = test_repo.get_payments_by_payer_hash("hash_801")
        assert len(payments) == 1
        assert payments[0]["couple_id"] is None
        assert payments[0]["amount"] == 490
    finally:
        app.dependency_overrides.clear()
