import os
import uuid
import pytest
from datetime import datetime, timezone, timedelta
import logging

from repo.in_memory_repo import InMemoryRepo
from repo.postgres_repo import PostgresRepo
from retention_scheduler import (
    clean_pending_inputs,
    clean_completed_sessions,
    clean_rate_limits,
    clean_expired_invites,
    clean_expired_payments,
    run_retention_cycle,
    RETENTION_ADVISORY_LOCK_ID,
)


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
        raise ValueError(f"Имя тестовой базы обязано заканчиваться на _test: {dbname}")

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


def test_clean_pending_inputs(repo):
    """Задача 1: pending_inputs по expires_at."""
    repo.upsert_user(101, "User 1")
    couple = repo.create_couple(101, "INV_INP")
    session = repo.create_conflict_session(couple["id"], 101)

    # 1. Активный ввод (не истек)
    repo.save_pending_input(session["id"], 101, "text", b"active_bytes")

    # 2. Просроченный ввод
    expired_input = repo.save_pending_input(session["id"], 101, "text", b"expired_bytes")
    if isinstance(repo, PostgresRepo):
        async def _set_exp():
            pool = await repo._get_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE pending_inputs SET expires_at = $2 WHERE id = $1;",
                    uuid.UUID(expired_input["id"]),
                    datetime.now(timezone.utc) - timedelta(hours=1),
                )
        repo._run_async(_set_exp())
    else:
        expired_input["expires_at"] = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()

    assert repo.count_pending_inputs(session["id"]) == 2

    purged = clean_pending_inputs(repo)
    assert purged == 1
    assert repo.count_pending_inputs(session["id"]) == 1


def test_clean_completed_sessions(repo):
    """Задача 2: завершенные сессии по RESULTS_RETENTION_DAYS."""
    repo.upsert_user(201, "User 201")
    couple = repo.create_couple(201, "INV_SES")

    # Сессия 1: завершена 40 дней назад
    s_old = repo.create_conflict_session(couple["id"], 201)
    repo.save_analysis_results(
        s_old["id"],
        {"partner_1_response": {"val": 1}, "partner_2_response": {"val": 2}, "shared_summary": {"dyn": "test"}},
        risk_level="none",
        completed_at=datetime.now(timezone.utc).isoformat(),
    )

    # Сессия 2: завершена 5 дней назад
    s_recent = repo.create_conflict_session(couple["id"], 201)
    repo.save_analysis_results(
        s_recent["id"],
        {"partner_1_response": {"val": 10}, "partner_2_response": {"val": 20}, "shared_summary": {"dyn": "recent"}},
        risk_level="none",
        completed_at=datetime.now(timezone.utc).isoformat(),
    )

    if isinstance(repo, PostgresRepo):
        async def _set_completed():
            pool = await repo._get_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE conflict_sessions SET completed_at = $2 WHERE id = $1;",
                    uuid.UUID(s_old["id"]),
                    datetime.now(timezone.utc) - timedelta(days=40),
                )
                await conn.execute(
                    "UPDATE conflict_sessions SET completed_at = $2 WHERE id = $1;",
                    uuid.UUID(s_recent["id"]),
                    datetime.now(timezone.utc) - timedelta(days=5),
                )
        repo._run_async(_set_completed())
    else:
        s_old["completed_at"] = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
        s_recent["completed_at"] = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()

    purged = clean_completed_sessions(repo, results_retention_days=30)
    assert purged == 1

    updated_old = repo.get_session_by_id(s_old["id"])
    assert updated_old is None

    updated_recent = repo.get_session_by_id(s_recent["id"])
    assert updated_recent["status"] == "completed"
    assert updated_recent["ai_advice_p1"] is not None


def test_clean_rate_limits(repo):
    """Задача 3: rate_limits."""
    if isinstance(repo, PostgresRepo):
        async def _seed_rl():
            pool = await repo._get_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO rate_limits (key, requests, window_start) VALUES ($1, 1, $2);",
                    "old_key",
                    datetime.now(timezone.utc) - timedelta(hours=2),
                )
                await conn.execute(
                    "INSERT INTO rate_limits (key, requests, window_start) VALUES ($1, 1, $2);",
                    "fresh_key",
                    datetime.now(timezone.utc) - timedelta(minutes=5),
                )
        repo._run_async(_seed_rl())
    else:
        from collections import deque
        now_ts = datetime.now(timezone.utc).timestamp()
        repo.rate_limiter._history["old_key"] = deque([now_ts - 7200])
        repo.rate_limiter._history["fresh_key"] = deque([now_ts - 100])

    purged = clean_rate_limits(repo, max_age_seconds=3600)
    assert purged == 1

    if isinstance(repo, PostgresRepo):
        async def _check_rl():
            pool = await repo._get_pool()
            async with pool.acquire() as conn:
                c_old = await conn.fetchval("SELECT count(*) FROM rate_limits WHERE key = $1;", "old_key")
                c_fresh = await conn.fetchval("SELECT count(*) FROM rate_limits WHERE key = $1;", "fresh_key")
                return c_old, c_fresh
        c_old, c_fresh = repo._run_async(_check_rl())
        assert c_old == 0
        assert c_fresh == 1
    else:
        assert "old_key" not in repo.rate_limiter._history
        assert "fresh_key" in repo.rate_limiter._history


def test_clean_expired_invites(repo):
    """Задача 4: просроченные инвайты (partner_2_id is None, created_at > 48ч)."""
    repo.upsert_user(301, "User 301")
    repo.upsert_user(302, "User 302")

    # 1. Просроченный инвайт (создан 50 часов назад, никто не присоединился)
    c_expired = repo.create_couple(301, "INV_EXP")

    # 2. Свежий инвайт (создан 2 часа назад)
    c_fresh = repo.create_couple(301, "INV_FRESH")

    # 3. Присоединенная пара (старая, но partner_2_id уже есть)
    c_joined = repo.create_couple(301, "INV_JOIN")
    repo.join_couple(c_joined["id"], 302)

    if isinstance(repo, PostgresRepo):
        async def _set_invites_created():
            pool = await repo._get_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE couples SET created_at = $2 WHERE id = $1;",
                    uuid.UUID(c_expired["id"]),
                    datetime.now(timezone.utc) - timedelta(hours=50),
                )
                await conn.execute(
                    "UPDATE couples SET created_at = $2 WHERE id = $1;",
                    uuid.UUID(c_fresh["id"]),
                    datetime.now(timezone.utc) - timedelta(hours=2),
                )
                await conn.execute(
                    "UPDATE couples SET created_at = $2 WHERE id = $1;",
                    uuid.UUID(c_joined["id"]),
                    datetime.now(timezone.utc) - timedelta(hours=50),
                )
        repo._run_async(_set_invites_created())
    else:
        c_expired["created_at"] = (datetime.now(timezone.utc) - timedelta(hours=50)).isoformat()
        c_fresh["created_at"] = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        c_joined["created_at"] = (datetime.now(timezone.utc) - timedelta(hours=50)).isoformat()

    purged = clean_expired_invites(repo, ttl_hours=48)
    assert purged == 1
    assert repo.get_couple_by_id(c_expired["id"]) is None
    assert repo.get_couple_by_id(c_fresh["id"]) is not None
    assert repo.get_couple_by_id(c_joined["id"]) is not None


def test_clean_expired_payments_none_and_set(repo, caplog):
    """Задача 5: платежи по PAYMENT_RETENTION_YEARS (предупреждение при None, очистка при значении)."""
    # 1. Если параметр не задан: предупреждение и 0 удалений
    with caplog.at_level(logging.WARNING):
        purged = clean_expired_payments(repo, retention_years=None)
        assert purged == 0
        assert "PAYMENT_RETENTION_YEARS не задан: автоматическое удаление финансовых записей отключено" in caplog.text

    # 2. Если параметр задан: удаление платежей старше N лет
    p_old = repo.save_payment("pack_1", 100, "RUB", "ch_old", "hash_old")
    p_recent = repo.save_payment("pack_2", 200, "RUB", "ch_rec", "hash_rec")

    if isinstance(repo, PostgresRepo):
        async def _set_pay_created():
            pool = await repo._get_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE payments SET created_at = $2 WHERE id = $1;",
                    uuid.UUID(p_old["id"]),
                    datetime.now(timezone.utc) - timedelta(days=365 * 6),
                )
                await conn.execute(
                    "UPDATE payments SET created_at = $2 WHERE id = $1;",
                    uuid.UUID(p_recent["id"]),
                    datetime.now(timezone.utc) - timedelta(days=365 * 2),
                )
        repo._run_async(_set_pay_created())
    else:
        p_old["created_at"] = (datetime.now(timezone.utc) - timedelta(days=365 * 6)).isoformat()
        p_recent["created_at"] = (datetime.now(timezone.utc) - timedelta(days=365 * 2)).isoformat()

    purged_5y = clean_expired_payments(repo, retention_years=5)
    assert purged_5y == 1
    assert len(repo.get_payments_by_payer_hash("hash_old")) == 0
    assert len(repo.get_payments_by_payer_hash("hash_rec")) == 1


def test_run_retention_cycle_advisory_lock(repo):
    """Проверка pg_try_advisory_lock: пропуск цикла, если блокировка уже удерживается."""
    # Захватываем блокировку вручную (симулируем другой экземпляр приложения)
    assert repo.try_advisory_lock(RETENTION_ADVISORY_LOCK_ID) is True

    # Пытаемся запустить цикл: должен вернуть skipped
    res = run_retention_cycle(repo)
    assert res["status"] == "skipped"
    assert res["reason"] == "lock_held"

    # Освобождаем блокировку
    repo.release_advisory_lock(RETENTION_ADVISORY_LOCK_ID)

    # Теперь цикл успешно выполняется
    res2 = run_retention_cycle(repo, payment_retention_years=5)
    assert res2["status"] == "completed"
