import os
import pytest
from datetime import datetime, timezone, timedelta

from repo.in_memory_repo import InMemoryRepo
from repo.postgres_repo import PostgresRepo


def make_postgres_test_repo(url_env_var: str = "DATABASE_URL_TEST"):
    default_url = (
        "postgresql://app_user:app_user_dev_pass@127.0.0.1:5432/buffer_ssor_test"
        if url_env_var == "DATABASE_URL_APP_TEST"
        else "postgresql://buffer_admin:buffer_dev_pass@127.0.0.1:5432/buffer_ssor_test"
    )
    test_db_url = os.environ.get(url_env_var, default_url)
    # Защита D6 / Task 3: отказ работать, если не localhost или база не заканчивается на _test
    if not any(h in test_db_url for h in ("localhost", "127.0.0.1")):
        raise ValueError(f"{url_env_var} должен указывать исключительно на localhost / 127.0.0.1")
    dbname = test_db_url.split("/")[-1].split("?")[0]
    if not dbname.endswith("_test"):
        raise ValueError(f"Имя тестовой базы обязано заканчиваться на _test, получено: {dbname}")

    return PostgresRepo(database_url=test_db_url)


@pytest.fixture(params=[
    pytest.param("in_memory", id="in_memory"),
    pytest.param("postgres_admin", id="postgres_admin", marks=pytest.mark.postgres),
    pytest.param("postgres_app_user", id="postgres_app_user", marks=pytest.mark.postgres),
])
def repo(request):
    if request.param == "in_memory":
        r = InMemoryRepo()
        r.reset_state()
        yield r
    elif request.param == "postgres_admin":
        r = make_postgres_test_repo("DATABASE_URL_TEST")
        r.reset_state()
        yield r
        r.reset_state()
        r.close()
    elif request.param == "postgres_app_user":
        r = make_postgres_test_repo("DATABASE_URL_APP_TEST")
        r.reset_state()
        yield r
        r.reset_state()
        r.close()


def test_repo_create_and_join_couple(repo):
    """Сценарий 1: Создание пары, регистрация пользователей и присоединение партнера."""
    u1 = repo.upsert_user(1101, "Партнер А")
    u2 = repo.upsert_user(1102, "Партнер Б")
    repo.accept_legal(1101)
    repo.accept_legal(1102)

    couple = repo.create_couple(1101, "INV-1101")
    assert couple["partner_1_id"] == 1101
    assert couple["partner_2_id"] is None
    assert couple["free_sessions_left"] == 3

    # Поиск по инвайту
    by_invite = repo.get_couple_by_invite("INV-1101")
    assert by_invite is not None
    assert by_invite["id"] == couple["id"]

    # Присоединение второго партнера
    joined = repo.join_couple(couple["id"], 1102)
    assert joined["partner_2_id"] == 1102

    # Проверка связи у пользователей
    c1 = repo.get_user_couple(1101)
    c2 = repo.get_user_couple(1102)
    assert c1["id"] == couple["id"]
    assert c2["id"] == couple["id"]


def test_repo_session_and_pending_inputs(repo):
    """Сценарий 2: Сессия конфликта и зашифрованные pending_inputs."""
    repo.upsert_user(1201, "Партнер А")
    repo.upsert_user(1202, "Партнер Б")
    couple = repo.create_couple(1201, "INV-1201")
    repo.join_couple(couple["id"], 1202)

    session = repo.create_conflict_session(couple["id"], 1201)
    s_id = session["id"]
    assert session["status"] == "waiting_partner_2"

    assert repo.count_pending_inputs(s_id) == 0
    assert repo.has_user_submitted_input(s_id, 1201) is False

    # Сохраняем ввод партнера 1
    repo.save_pending_input(s_id, 1201, "text", b"encrypted_p1_text")
    assert repo.count_pending_inputs(s_id) == 1
    assert repo.has_user_submitted_input(s_id, 1201) is True
    assert repo.has_user_submitted_input(s_id, 1202) is False

    # Сохраняем ввод партнера 2
    repo.save_pending_input(s_id, 1202, "audio", b"encrypted_p2_audio")
    assert repo.count_pending_inputs(s_id) == 2
    assert repo.has_user_submitted_input(s_id, 1202) is True

    inputs = repo.get_pending_inputs(s_id)
    assert len(inputs) == 2
    p1_inp = next(i for i in inputs if i["author_telegram_id"] == 1201)
    assert p1_inp["payload_encrypted"] == b"encrypted_p1_text"
    assert p1_inp["kind"] == "text"


def test_repo_save_analysis_results_transaction(repo):
    """Сценарий 3: Атомарная транзакция сохранения результатов и очистки pending_inputs."""
    repo.upsert_user(1301, "Партнер А")
    repo.upsert_user(1302, "Партнер Б")
    couple = repo.create_couple(1301, "INV-1301")
    repo.join_couple(couple["id"], 1302)

    session = repo.create_conflict_session(couple["id"], 1301)
    s_id = session["id"]

    repo.save_pending_input(s_id, 1301, "text", b"secret_p1")
    repo.save_pending_input(s_id, 1302, "text", b"secret_p2")
    assert repo.count_pending_inputs(s_id) == 2

    # Сохраняем результаты
    now_iso = datetime.now(timezone.utc).isoformat()
    analysis_res = {
        "partner_1_response": {"validation": "Понимаем вас"},
        "partner_2_response": {"validation": "Понимаем партнера"},
        "shared_summary": {"situation_overview": "Общий итог"},
    }
    repo.save_analysis_results(
        session_id=s_id,
        results=analysis_res,
        risk_level="none",
        completed_at=now_iso,
    )

    # В той же транзакции:
    # 1. pending_inputs безвозвратно удалены
    assert repo.count_pending_inputs(s_id) == 0
    # 2. Результаты записаны в session
    updated_session = repo.get_session_by_id(s_id)
    assert updated_session["status"] == "completed"
    assert updated_session["ai_advice_p1"] == {"validation": "Понимаем вас"}
    assert updated_session["ai_advice_p2"] == {"validation": "Понимаем партнера"}
    assert updated_session["shared_summary"] == {"situation_overview": "Общий итог"}


def test_repo_expire_session(repo):
    """Сценарий 4: Истечение срока сессии с удалением pending_inputs."""
    repo.upsert_user(1401, "Партнер А")
    couple = repo.create_couple(1401, "INV-1401")
    session = repo.create_conflict_session(couple["id"], 1401)
    s_id = session["id"]

    repo.save_pending_input(s_id, 1401, "text", b"data")
    assert repo.count_pending_inputs(s_id) == 1

    repo.expire_session(s_id)

    updated = repo.get_session_by_id(s_id)
    assert updated["status"] == "expired"
    assert repo.count_pending_inputs(s_id) == 0


def test_repo_delete_history(repo):
    """Сценарий 5: Удаление только истории и сессий с сохранением пары и пользователей."""
    repo.upsert_user(1501, "Партнер А")
    repo.upsert_user(1502, "Партнер Б")
    couple = repo.create_couple(1501, "INV-1501")
    repo.join_couple(couple["id"], 1502)

    session = repo.create_conflict_session(couple["id"], 1501)
    s_id = session["id"]
    repo.save_pending_input(s_id, 1501, "text", b"data")

    repo.delete_history(couple["id"])

    # Сессия и исходники удалены
    assert repo.get_session_by_id(s_id) is None
    assert repo.count_pending_inputs(s_id) == 0

    # Пара и пользователи сохранились
    assert repo.get_couple_by_id(couple["id"]) is not None
    assert repo.get_user(1501) is not None
    assert repo.get_user(1502) is not None


def test_repo_delete_couple_data(repo):
    """Сценарий 6: Полное удаление пары, пользователей и отвязка платежей (couple_id=NULL)."""
    repo.upsert_user(1601, "Партнер А")
    repo.upsert_user(1602, "Партнер Б")
    couple = repo.create_couple(1601, "INV-1601")
    repo.join_couple(couple["id"], 1602)

    pay = repo.save_payment(
        product="test_pack",
        amount=1000,
        currency="RUB",
        provider_charge_id="ch_1601",
        payer_hash="hash_1601",
        couple_id=couple["id"],
    )

    repo.delete_couple_data(couple["id"])

    # Пара и пользователи удалены
    assert repo.get_couple_by_id(couple["id"]) is None
    assert repo.get_user(1601) is None
    assert repo.get_user(1602) is None

    # Платеж сохранился, но couple_id стал None
    payments = repo.get_payments_by_payer_hash("hash_1601")
    assert len(payments) == 1
    assert payments[0]["id"] == pay["id"]
    assert payments[0]["couple_id"] is None


def test_repo_rate_limits(repo):
    """Сценарий 7: Rate limits."""
    key = "test_rate_key"
    allowed1, retry1 = repo.check_rate_limit(key, max_requests=2, window_seconds=60)
    assert allowed1 is True
    assert retry1 == 0

    allowed2, retry2 = repo.check_rate_limit(key, max_requests=2, window_seconds=60)
    assert allowed2 is True

    # Третий запрос превышает лимит 2
    allowed3, retry3 = repo.check_rate_limit(key, max_requests=2, window_seconds=60)
    assert allowed3 is False
    assert retry3 > 0


def test_repo_invites_ttl_and_bruteforce(repo):
    """Сценарий 8: Инвайты, защита от перебора."""
    tg_id = 1801
    assert repo.check_invite_bruteforce(tg_id)[0] is False

    for _ in range(5):
        repo.record_failed_invite_attempt(tg_id)

    # После 5 неудачных попыток — блокировка
    blocked, retry_after = repo.check_invite_bruteforce(tg_id)
    assert blocked is True
    assert retry_after > 0

    # Сброс перебора
    repo.reset_invite_bruteforce(tg_id)
    assert repo.check_invite_bruteforce(tg_id)[0] is False


def test_repo_claim_session_atomic_c4(repo):
    """Сценарий 9: Атомарная блокировка сессии для разбора (C4)."""
    repo.upsert_user(1901, "Партнер А")
    couple = repo.create_couple(1901, "INV-1901")
    session = repo.create_conflict_session(couple["id"], 1901)
    s_id = session["id"]

    # Первый захват успешен
    first_claim = repo.claim_session_for_analysis(s_id)
    assert first_claim is True

    # Второй захват той же сессии отклоняется
    second_claim = repo.claim_session_for_analysis(s_id)
    assert second_claim is False

    # Статус сессии стал processing
    updated = repo.get_session_by_id(s_id)
    assert updated["status"] == "processing"
