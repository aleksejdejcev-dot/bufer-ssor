"""
Реализация слоя доступа к данным Repository на основе PostgreSQL и asyncpg.
Использует пул соединений, параметризованные SQL-запросы, транзакции и блокировки.
"""

import asyncio
import threading
import json
import uuid
import re
import hashlib
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List, Tuple
import asyncpg
from config import settings
from rate_limiter import RateLimiter, normalize_invite_code


def mask_db_url(url: str) -> str:
    """Маскирует пароль в URL подключения к базе данных."""
    if not url:
        return ""
    return re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", url)


def _format_row(row: Optional[asyncpg.Record]) -> Optional[Dict[str, Any]]:
    """Преобразует asyncpg.Record в стандартный словарь с конвертацией UUID и дат."""
    if row is None:
        return None
    d = dict(row)
    for k, v in d.items():
        if isinstance(v, uuid.UUID):
            d[k] = str(v)
        elif isinstance(v, datetime):
            d[k] = v.isoformat()
        elif hasattr(v, "as_tuple"):  # Decimal
            d[k] = float(v)
        elif isinstance(v, bytes):
            d[k] = bytes(v)
        elif isinstance(v, str) and (k.startswith("ai_advice") or k == "shared_summary"):
            try:
                d[k] = json.loads(v)
            except Exception:
                pass
    return d


def _format_rows(rows: List[asyncpg.Record]) -> List[Dict[str, Any]]:
    return [_format_row(r) for r in rows if r is not None]  # type: ignore


class PostgresRepo:
    """
    Реализация интерфейса Repository поверх PostgreSQL с использованием asyncpg.
    Поддерживает изолированный background-loop для безопасного выполнения в любом контексте.
    """

    def __init__(
        self,
        database_url: Optional[str] = None,
        min_pool_size: Optional[int] = None,
        max_pool_size: Optional[int] = None,
        ssl_mode: Optional[str] = None,
    ):
        self.database_url = database_url or settings.DATABASE_URL
        self.min_pool_size = min_pool_size or getattr(settings, "DB_POOL_MIN", 2)
        self.max_pool_size = max_pool_size or getattr(settings, "DB_POOL_MAX", 10)
        self.ssl_mode = ssl_mode or getattr(settings, "DB_SSLMODE", "disable")
        self.rate_limiter = RateLimiter()

        self._pool: Optional[asyncpg.Pool] = None
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._start_background_loop, daemon=True)
        self._thread.start()
        self._advisory_conn: Optional[asyncpg.Connection] = None
        self._advisory_lock_id: Optional[int] = None

    def _start_background_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _run_async(self, coro, timeout: float = 30.0):
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)

    async def _get_pool(self) -> asyncpg.Pool:
        if self._pool is None:
            if not self.database_url:
                raise RuntimeError("DATABASE_URL is not configured for PostgresRepo")

            dbname = (self.database_url or "").split("/")[-1].split("?")[0]
            is_test_db = dbname.endswith("_test")

            if settings.ENVIRONMENT == "production" and not is_test_db:
                if self.ssl_mode == "disable" or self.ssl_mode not in ("require", "verify-ca", "verify-full"):
                    raise RuntimeError("Production database connection must use TLS (DB_SSLMODE must be require, verify-ca or verify-full)")

            ssl_param = None
            if self.ssl_mode in ("require", "verify-ca", "verify-full"):
                import ssl
                ssl_param = ssl.create_default_context()
                if self.ssl_mode == "require":
                    ssl_param.check_hostname = False
                    ssl_param.verify_mode = ssl.CERT_NONE

            self._pool = await asyncpg.create_pool(
                dsn=self.database_url,
                min_size=self.min_pool_size,
                max_size=self.max_pool_size,
                ssl=ssl_param,
            )

            # Проверка безопасности подключения в режиме production (Пункт 4 аудита)
            if settings.ENVIRONMENT == "production" and not is_test_db:
                try:
                    async with self._pool.acquire() as conn:
                        rolsuper = await conn.fetchval(
                            "SELECT rolsuper FROM pg_roles WHERE rolname = current_user;"
                        )
                        if rolsuper is True:
                            raise RuntimeError("Production database connection must not use a superuser role")
                except Exception:
                    await self._pool.close()
                    self._pool = None
                    raise
        return self._pool

    def close(self):
        try:
            if self._advisory_conn is not None:
                try:
                    self._run_async(self.release_advisory_lock(self._advisory_lock_id or 0))
                except Exception:
                    pass
            if self._pool is not None:
                self._run_async(self._pool.close())
                self._pool = None
        finally:
            if self._loop.is_running():
                self._loop.call_soon_threadsafe(self._loop.stop)
            if self._thread.is_alive():
                self._thread.join(timeout=5)
            if not self._loop.is_running() and not self._loop.is_closed():
                self._loop.close()

    # ==========================================================================
    # Методы интерфейса Repository
    # ==========================================================================

    def reset_state(self) -> None:
        """Очищает данные (используется строго в тестовой БД через DML DELETE)."""
        async def _reset():
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                await conn.execute("""
                    DELETE FROM rate_limits;
                    DELETE FROM pending_inputs;
                    DELETE FROM conflict_sessions;
                    DELETE FROM payments;
                    DELETE FROM user_subscriptions;
                    DELETE FROM couples;
                    DELETE FROM users;
                """)
        self._run_async(_reset())

    def get_user(self, telegram_id: int) -> Optional[Dict[str, Any]]:
        async def _impl():
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow("SELECT * FROM users WHERE telegram_id = $1;", telegram_id)
                return _format_row(row)
        return self._run_async(_impl())

    def upsert_user(self, telegram_id: int, first_name: str, username: Optional[str] = None) -> Dict[str, Any]:
        async def _impl():
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow("""
                    INSERT INTO users (telegram_id, first_name)
                    VALUES ($1, $2)
                    ON CONFLICT (telegram_id) DO UPDATE
                    SET first_name = EXCLUDED.first_name
                    RETURNING *;
                """, telegram_id, first_name)
                return _format_row(row)
        return self._run_async(_impl())

    def accept_legal(self, telegram_id: int) -> Dict[str, Any]:
        async def _impl():
            pool = await self._get_pool()
            now = datetime.now(timezone.utc)
            async with pool.acquire() as conn:
                row = await conn.fetchrow("""
                    UPDATE users
                    SET accepted_legal_at = $2
                    WHERE telegram_id = $1
                    RETURNING *;
                """, telegram_id, now)
                return _format_row(row)
        return self._run_async(_impl())

    def get_couple_by_id(self, couple_id: str) -> Optional[Dict[str, Any]]:
        async def _impl():
            pool = await self._get_pool()
            c_uuid = uuid.UUID(couple_id)
            async with pool.acquire() as conn:
                row = await conn.fetchrow("SELECT * FROM couples WHERE id = $1;", c_uuid)
                return _format_row(row)
        return self._run_async(_impl())

    def get_couple_by_invite(self, invite_code: str) -> Optional[Dict[str, Any]]:
        async def _impl():
            pool = await self._get_pool()
            norm_code = normalize_invite_code(invite_code)
            async with pool.acquire() as conn:
                row = await conn.fetchrow("SELECT * FROM couples WHERE invite_code = $1;", norm_code)
                return _format_row(row)
        return self._run_async(_impl())

    def get_user_couple(self, telegram_id: int) -> Optional[Dict[str, Any]]:
        async def _impl():
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT * FROM couples
                    WHERE partner_1_id = $1 OR partner_2_id = $1
                    ORDER BY created_at DESC
                    LIMIT 1;
                """, telegram_id)
                return _format_row(row)
        return self._run_async(_impl())

    def create_couple(self, partner_1_id: int, invite_code: str) -> Dict[str, Any]:
        async def _impl():
            pool = await self._get_pool()
            norm_code = normalize_invite_code(invite_code)
            async with pool.acquire() as conn:
                async with conn.transaction():
                    row = await conn.fetchrow("""
                        INSERT INTO couples (partner_1_id, invite_code, free_sessions_left)
                        VALUES ($1, $2, 2)
                        RETURNING *;
                    """, partner_1_id, norm_code)
                    couple_data = _format_row(row)
                    c_uuid = row["id"]
                    await conn.execute("UPDATE users SET couple_id = $1 WHERE telegram_id = $2;", c_uuid, partner_1_id)
                    return couple_data
        return self._run_async(_impl())

    def join_couple(self, couple_id: str, partner_2_id: int) -> Dict[str, Any]:
        async def _impl():
            pool = await self._get_pool()
            c_uuid = uuid.UUID(couple_id)
            async with pool.acquire() as conn:
                async with conn.transaction():
                    row = await conn.fetchrow("""
                        UPDATE couples
                        SET partner_2_id = $2
                        WHERE id = $1 AND partner_2_id IS NULL
                        RETURNING *;
                    """, c_uuid, partner_2_id)
                    if not row:
                        raise ValueError("Пара уже заполнена или не существует")
                    await conn.execute("UPDATE users SET couple_id = $1 WHERE telegram_id = $2;", c_uuid, partner_2_id)
                    return _format_row(row)
        return self._run_async(_impl())

    def update_mood(self, couple_id: str, is_partner_1: bool, mood: int) -> Dict[str, Any]:
        async def _impl():
            pool = await self._get_pool()
            c_uuid = uuid.UUID(couple_id)
            now = datetime.now(timezone.utc)
            async with pool.acquire() as conn:
                if is_partner_1:
                    row = await conn.fetchrow("""
                        UPDATE couples
                        SET mood_p1 = $2, mood_updated_at_p1 = $3
                        WHERE id = $1
                        RETURNING *;
                    """, c_uuid, mood, now)
                else:
                    row = await conn.fetchrow("""
                        UPDATE couples
                        SET mood_p2 = $2, mood_updated_at_p2 = $3
                        WHERE id = $1
                        RETURNING *;
                    """, c_uuid, mood, now)
                return _format_row(row)
        return self._run_async(_impl())

    def decrement_free_sessions(self, couple_id: str) -> None:
        async def _impl():
            pool = await self._get_pool()
            c_uuid = uuid.UUID(couple_id)
            async with pool.acquire() as conn:
                await conn.execute("""
                    UPDATE couples
                    SET free_sessions_left = GREATEST(free_sessions_left - 1, 0)
                    WHERE id = $1 AND free_sessions_left > 0;
                """, c_uuid)
        self._run_async(_impl())

    def check_couple_access(self, couple: Dict[str, Any]) -> Tuple[bool, str]:
        sub_until = couple.get("subscription_until")
        if sub_until:
            try:
                sub_dt = datetime.fromisoformat(sub_until)
                if sub_dt.tzinfo is None:
                    sub_dt = sub_dt.replace(tzinfo=timezone.utc)
                if sub_dt > datetime.now(timezone.utc):
                    return True, "subscription"
            except Exception:
                pass
        for user_id in (couple.get("partner_1_id"), couple.get("partner_2_id")):
            if not user_id:
                continue
            until = self.get_subscription_until_for_user(int(user_id))
            if until:
                try:
                    if datetime.fromisoformat(until) > datetime.now(timezone.utc):
                        return True, "subscription"
                except ValueError:
                    pass
        if couple.get("free_sessions_left", 0) > 0:
            return True, "free_session"
        return False, "no_access"

    def get_subscription_until_for_user(self, telegram_id: int) -> Optional[str]:
        hashes = {self._hash_id(telegram_id)}
        couple = self.get_user_couple(telegram_id)
        if couple:
            for member_id in (couple.get("partner_1_id"), couple.get("partner_2_id")):
                if member_id:
                    hashes.add(self._hash_id(member_id))
        async def _impl():
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT GREATEST(
                        (SELECT MAX(subscription_until) FROM user_subscriptions WHERE payer_hash = ANY($1::text[])),
                        (SELECT MAX(subscription_until) FROM couples
                         WHERE (partner_1_id = $2 OR partner_2_id = $2) AND subscription_until > now())
                    ) AS subscription_until;
                """, list(hashes), telegram_id)
                value = row["subscription_until"] if row else None
                return value.isoformat() if value else None
        return self._run_async(_impl())

    def cleanup_expired_subscriptions(self) -> int:
        async def _impl():
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                result = await conn.execute("DELETE FROM user_subscriptions WHERE subscription_until <= now();")
                await conn.execute("UPDATE couples SET subscription_until = NULL WHERE subscription_until <= now();")
                return int(result.rsplit(" ", 1)[-1])
        return self._run_async(_impl())

    def add_free_sessions(self, couple_id: str, count: int) -> Dict[str, Any]:
        async def _impl():
            pool = await self._get_pool()
            c_uuid = uuid.UUID(couple_id)
            async with pool.acquire() as conn:
                row = await conn.fetchrow("""
                    UPDATE couples
                    SET free_sessions_left = free_sessions_left + $2
                    WHERE id = $1
                    RETURNING *;
                """, c_uuid, count)
                return _format_row(row)
        return self._run_async(_impl())

    def get_active_session(self, couple_id: str) -> Optional[Dict[str, Any]]:
        async def _impl():
            pool = await self._get_pool()
            c_uuid = uuid.UUID(couple_id)
            async with pool.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT * FROM conflict_sessions
                    WHERE couple_id = $1 AND status IN ('waiting_partner_2', 'processing', 'analyzing')
                    ORDER BY created_at DESC
                    LIMIT 1;
                """, c_uuid)
                return _format_row(row)
        return self._run_async(_impl())

    def get_sessions_for_analysis_recovery(self) -> List[Dict[str, Any]]:
        """Return sessions left in the pre-analysis status after a process restart."""
        async def _impl():
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch("SELECT * FROM conflict_sessions WHERE status = 'analyzing';")
                return _format_rows(rows)
        return self._run_async(_impl())

    def get_session_by_id(self, session_id: str) -> Optional[Dict[str, Any]]:
        async def _impl():
            pool = await self._get_pool()
            s_uuid = uuid.UUID(session_id)
            async with pool.acquire() as conn:
                row = await conn.fetchrow("SELECT * FROM conflict_sessions WHERE id = $1;", s_uuid)
                return _format_row(row)
        return self._run_async(_impl())

    def create_conflict_session(self, couple_id: str, initiator_id: int) -> Dict[str, Any]:
        async def _impl():
            pool = await self._get_pool()
            c_uuid = uuid.UUID(couple_id)
            async with pool.acquire() as conn:
                row = await conn.fetchrow("""
                    INSERT INTO conflict_sessions (couple_id, initiator_id, status)
                    VALUES ($1, $2, 'waiting_partner_2')
                    RETURNING *;
                """, c_uuid, initiator_id)
                return _format_row(row)
        return self._run_async(_impl())

    def create_conflict_session_with_access(self, couple_id: str, initiator_id: int) -> Optional[Dict[str, Any]]:
        async def _impl():
            pool = await self._get_pool()
            c_uuid = uuid.UUID(couple_id)
            async with pool.acquire() as conn:
                async with conn.transaction():
                    couple = await conn.fetchrow("""
                        SELECT free_sessions_left, subscription_until, partner_1_id, partner_2_id
                        FROM couples WHERE id = $1 FOR UPDATE;
                    """, c_uuid)
                    if not couple:
                        return None
                    active = await conn.fetchval("""
                        SELECT EXISTS(
                            SELECT 1 FROM conflict_sessions
                            WHERE couple_id = $1 AND status IN ('waiting_partner_2', 'processing', 'analyzing')
                        );
                    """, c_uuid)
                    if active:
                        return None
                    # Защищает также от конкурентных транзакций, которые не видят
                    # незакоммиченную строку сессии друг друга.
                    await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1));", couple_id)
                    active = await conn.fetchval("""
                        SELECT EXISTS(
                            SELECT 1 FROM conflict_sessions
                            WHERE couple_id = $1 AND status IN ('waiting_partner_2', 'processing', 'analyzing')
                        );
                    """, c_uuid)
                    if active:
                        return None
                    owner_hashes = [self._hash_id(member_id) for member_id in
                                    (couple["partner_1_id"], couple["partner_2_id"]) if member_id]
                    owner_until = await conn.fetchval("""
                        SELECT MAX(subscription_until) FROM user_subscriptions
                        WHERE payer_hash = ANY($1::text[]);
                    """, owner_hashes)
                    premium = bool(
                        (couple["subscription_until"] and couple["subscription_until"] > datetime.now(timezone.utc))
                        or (owner_until and owner_until > datetime.now(timezone.utc))
                    )
                    if not premium and couple["free_sessions_left"] <= 0:
                        return None
                    row = await conn.fetchrow("""
                        INSERT INTO conflict_sessions (couple_id, initiator_id, status)
                        VALUES ($1, $2, 'waiting_partner_2') RETURNING *;
                    """, c_uuid, initiator_id)
                    return _format_row(row)
        return self._run_async(_impl())

    def update_session_status(
        self,
        session_id: str,
        status: str,
        completed_at: Optional[str] = None,
        risk_level: Optional[str] = None,
    ) -> None:
        async def _impl():
            pool = await self._get_pool()
            s_uuid = uuid.UUID(session_id)
            c_at = datetime.fromisoformat(completed_at) if completed_at else None
            async with pool.acquire() as conn:
                if completed_at and risk_level:
                    await conn.execute("""
                        UPDATE conflict_sessions
                        SET status = $2, completed_at = $3, risk_level = $4
                        WHERE id = $1;
                    """, s_uuid, status, c_at, risk_level)
                elif completed_at:
                    await conn.execute("""
                        UPDATE conflict_sessions
                        SET status = $2, completed_at = $3
                        WHERE id = $1;
                    """, s_uuid, status, c_at)
                elif risk_level:
                    await conn.execute("""
                        UPDATE conflict_sessions
                        SET status = $2, risk_level = $3
                        WHERE id = $1;
                    """, s_uuid, status, risk_level)
                else:
                    await conn.execute("UPDATE conflict_sessions SET status = $2 WHERE id = $1;", s_uuid, status)
        self._run_async(_impl())

    def claim_session_for_analysis(self, session_id: str) -> bool:
        """
        Атомарно переводит сессию в статус 'processing' через WHERE-фильтр.
        Предотвращает двойную параллельную обработку при состоянии гонки (C4).
        """
        async def _impl() -> bool:
            pool = await self._get_pool()
            s_uuid = uuid.UUID(session_id)
            async with pool.acquire() as conn:
                row = await conn.fetchrow("""
                    UPDATE conflict_sessions
                    SET status = 'processing'
                    WHERE id = $1 AND status NOT IN ('processing', 'completed', 'failed', 'expired', 'purged_by_retention')
                    RETURNING id;
                """, s_uuid)
                return row is not None
        return self._run_async(_impl())

    def save_analysis_results(
        self,
        session_id: str,
        results: Dict[str, Any],
        risk_level: str,
        completed_at: str,
    ) -> None:
        async def _impl():
            pool = await self._get_pool()
            s_uuid = uuid.UUID(session_id)
            c_at = datetime.fromisoformat(completed_at)
            async with pool.acquire() as conn:
                async with conn.transaction():
                    await conn.execute("""
                        UPDATE conflict_sessions
                        SET status = 'completed',
                            completed_at = $2,
                            risk_level = $3,
                            ai_advice_p1 = $4::jsonb,
                            ai_advice_p2 = $5::jsonb,
                            shared_summary = $6::jsonb
                        WHERE id = $1;
                    """, s_uuid, c_at, risk_level,
                         json.dumps(results.get("partner_1_response") or results.get("partner_1_card") or results.get("ai_advice_p1")),
                         json.dumps(results.get("partner_2_response") or results.get("partner_2_card") or results.get("ai_advice_p2")),
                         json.dumps(results.get("shared_summary")))

                    # Безвозвратно удаляем временные зашифрованные исходники
                    await conn.execute("DELETE FROM pending_inputs WHERE session_id = $1;", s_uuid)
        self._run_async(_impl())

    def confirm_conflict_finished(self, session_id: str, telegram_id: int) -> bool:
        async def _impl():
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                async with conn.transaction():
                    row = await conn.fetchrow("""
                        UPDATE conflict_sessions AS s
                        SET finish_confirmed_by_p1 = s.finish_confirmed_by_p1 OR c.partner_1_id = $2,
                            finish_confirmed_by_p2 = s.finish_confirmed_by_p2 OR (c.partner_2_id = $2) IS TRUE,
                            ai_advice_p1 = CASE WHEN (s.finish_confirmed_by_p1 OR c.partner_1_id = $2)
                                                     AND (s.finish_confirmed_by_p2 OR (c.partner_2_id = $2) IS TRUE)
                                                THEN NULL ELSE s.ai_advice_p1 END,
                            ai_advice_p2 = CASE WHEN (s.finish_confirmed_by_p1 OR c.partner_1_id = $2)
                                                     AND (s.finish_confirmed_by_p2 OR (c.partner_2_id = $2) IS TRUE)
                                                THEN NULL ELSE s.ai_advice_p2 END,
                            shared_summary = CASE WHEN (s.finish_confirmed_by_p1 OR c.partner_1_id = $2)
                                                       AND (s.finish_confirmed_by_p2 OR (c.partner_2_id = $2) IS TRUE)
                                                  THEN NULL ELSE s.shared_summary END,
                            status = CASE WHEN (s.finish_confirmed_by_p1 OR c.partner_1_id = $2)
                                               AND (s.finish_confirmed_by_p2 OR (c.partner_2_id = $2) IS TRUE)
                                          THEN 'purged_by_retention' ELSE s.status END
                        FROM couples AS c
                        WHERE s.id = $1 AND s.couple_id = c.id
                          AND s.status = 'completed' AND $2 IN (c.partner_1_id, c.partner_2_id)
                        RETURNING s.finish_confirmed_by_p1, s.finish_confirmed_by_p2;
                    """, uuid.UUID(session_id), telegram_id)
                    if row is None:
                        return False
                    finished = row["finish_confirmed_by_p1"] and row["finish_confirmed_by_p2"]
                    if finished:
                        await conn.execute("DELETE FROM pending_inputs WHERE session_id = $1;", uuid.UUID(session_id))
                        await conn.execute("DELETE FROM conflict_sessions WHERE id = $1;", uuid.UUID(session_id))
                    return finished
        return self._run_async(_impl())

    def get_expired_sessions(self) -> List[Dict[str, Any]]:
        async def _impl():
            pool = await self._get_pool()
            cutoff = datetime.now(timezone.utc) - timedelta(hours=getattr(settings, "EXPIRATION_HOURS", 48))
            async with pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT * FROM conflict_sessions
                    WHERE status IN ('waiting_partner_2', 'processing', 'analyzing')
                      AND created_at <= $1;
                """, cutoff)
                return _format_rows(rows)
        return self._run_async(_impl())

    def expire_session(self, session_id: str) -> None:
        async def _impl():
            pool = await self._get_pool()
            s_uuid = uuid.UUID(session_id)
            async with pool.acquire() as conn:
                await conn.execute("DELETE FROM conflict_sessions WHERE id = $1;", s_uuid)
        self._run_async(_impl())

    def save_pending_input(
        self,
        session_id: str,
        author_telegram_id: int,
        kind: str,
        payload_encrypted: bytes,
    ) -> Dict[str, Any]:
        async def _impl():
            pool = await self._get_pool()
            s_uuid = uuid.UUID(session_id)
            expires_at = datetime.now(timezone.utc) + timedelta(hours=getattr(settings, "RAW_INPUT_TTL_HOURS", 48))
            async with pool.acquire() as conn:
                row = await conn.fetchrow("""
                    INSERT INTO pending_inputs (session_id, author_telegram_id, kind, payload_encrypted, expires_at)
                    VALUES ($1, $2, $3, $4, $5)
                    RETURNING *;
                """, s_uuid, author_telegram_id, kind, payload_encrypted, expires_at)
                return _format_row(row)
        return self._run_async(_impl())

    def has_user_submitted_input(self, session_id: str, author_telegram_id: int) -> bool:
        async def _impl():
            pool = await self._get_pool()
            s_uuid = uuid.UUID(session_id)
            async with pool.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT 1 FROM pending_inputs
                    WHERE session_id = $1 AND author_telegram_id = $2
                    LIMIT 1;
                """, s_uuid, author_telegram_id)
                return row is not None
        return self._run_async(_impl())

    def count_pending_inputs(self, session_id: str) -> int:
        async def _impl():
            pool = await self._get_pool()
            s_uuid = uuid.UUID(session_id)
            async with pool.acquire() as conn:
                val = await conn.fetchval("SELECT count(*) FROM pending_inputs WHERE session_id = $1;", s_uuid)
                return int(val or 0)
        return self._run_async(_impl())

    def get_pending_inputs(self, session_id: str) -> List[Dict[str, Any]]:
        async def _impl():
            pool = await self._get_pool()
            s_uuid = uuid.UUID(session_id)
            async with pool.acquire() as conn:
                rows = await conn.fetch("SELECT * FROM pending_inputs WHERE session_id = $1;", s_uuid)
                return _format_rows(rows)
        return self._run_async(_impl())

    def delete_pending_input_for_author(self, session_id: str, author_telegram_id: int) -> None:
        async def _impl():
            pool = await self._get_pool()
            s_uuid = uuid.UUID(session_id)
            async with pool.acquire() as conn:
                await conn.execute("""
                    DELETE FROM pending_inputs
                    WHERE session_id = $1 AND author_telegram_id = $2;
                """, s_uuid, author_telegram_id)
        self._run_async(_impl())

    def delete_pending_inputs_for_session(self, session_id: str) -> None:
        async def _impl():
            pool = await self._get_pool()
            s_uuid = uuid.UUID(session_id)
            async with pool.acquire() as conn:
                await conn.execute("DELETE FROM pending_inputs WHERE session_id = $1;", s_uuid)
        self._run_async(_impl())

    def cleanup_expired_pending_inputs(self) -> int:
        async def _impl():
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                val = await conn.fetchval("SELECT cleanup_expired_pending_inputs();")
                return int(val or 0)
        return self._run_async(_impl())

    def _hash_id(self, val: Any) -> str:
        salt = getattr(settings, "PAYMENT_HASH_KEY", "buffer_salt")
        return hashlib.sha256(f"{val}:{salt}".encode("utf-8")).hexdigest()

    def delete_history(self, couple_id: str, initiated_by: Optional[int] = None) -> None:
        async def _impl():
            pool = await self._get_pool()
            c_uuid = uuid.UUID(couple_id)
            c_hash = self._hash_id(couple_id)
            u_hash = self._hash_id(initiated_by) if initiated_by else "unknown"
            async with pool.acquire() as conn:
                async with conn.transaction():
                    await conn.execute("""
                        INSERT INTO deletions_log (couple_id_hash, initiated_by_hash, entity_type)
                        VALUES ($1, $2, 'history');
                    """, c_hash, u_hash)
                    await conn.execute("""
                        DELETE FROM pending_inputs
                        WHERE session_id IN (SELECT id FROM conflict_sessions WHERE couple_id = $1);
                    """, c_uuid)
                    await conn.execute("DELETE FROM conflict_sessions WHERE couple_id = $1;", c_uuid)
        self._run_async(_impl())

    def purge_expired_data(self, days_retention: int = 2, hours_raw_ttl: int = 48) -> Dict[str, int]:
        async def _impl():
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                val = await conn.fetchval("SELECT purge_expired_data($1, $2);", days_retention, hours_raw_ttl)
                if isinstance(val, str):
                    return json.loads(val)
                elif isinstance(val, dict):
                    return val
                return {"purged_sessions": 0, "purged_inputs": 0}
        return self._run_async(_impl())

    def delete_couple_data(self, couple_id: str, initiated_by: Optional[int] = None) -> None:
        async def _impl():
            pool = await self._get_pool()
            c_uuid = uuid.UUID(couple_id)
            c_hash = self._hash_id(couple_id)
            u_hash = self._hash_id(initiated_by) if initiated_by else "unknown"
            async with pool.acquire() as conn:
                async with conn.transaction():
                    await conn.execute("""
                        INSERT INTO deletions_log (couple_id_hash, initiated_by_hash, entity_type)
                        VALUES ($1, $2, 'couple');
                    """, c_hash, u_hash)
                    await conn.execute("SELECT delete_couple_data($1);", c_uuid)
        self._run_async(_impl())

    def get_deletions_log(self) -> List[Dict[str, Any]]:
        async def _impl():
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch("SELECT * FROM deletions_log ORDER BY deleted_at DESC;")
                return _format_rows(rows)
        return self._run_async(_impl())

    def save_payment(
        self,
        product: str,
        amount: int,
        currency: str,
        provider_charge_id: str,
        payer_hash: str,
        couple_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        async def _impl():
            pool = await self._get_pool()
            c_uuid = uuid.UUID(couple_id) if couple_id else None
            async with pool.acquire() as conn:
                row = await conn.fetchrow("""
                    INSERT INTO payments (product, amount, currency, provider_charge_id, payer_hash, couple_id)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    RETURNING *;
                """, product, amount, currency, provider_charge_id, payer_hash, c_uuid)
                return _format_row(row)
        return self._run_async(_impl())

    def create_payment(
        self,
        couple_id: Any,
        user_id: Any,
        payment_id: str,
        amount: Any,
        currency: str = "RUB",
        product: str = "month_sub",
    ) -> Dict[str, Any]:
        async def _impl():
            pool = await self._get_pool()
            c_uuid = uuid.UUID(str(couple_id)) if couple_id else None
            payer_hash = self._hash_id(user_id)
            numeric_amount = float(amount) if hasattr(amount, "__float__") else amount
            async with pool.acquire() as conn:
                row = await conn.fetchrow("""
                    INSERT INTO payments (product, amount, currency, provider_charge_id, payer_hash, couple_id, status)
                    VALUES ($1, $2, $3, $4, $5, $6, 'pending')
                    ON CONFLICT (provider_charge_id) DO NOTHING
                    RETURNING *;
                """, product, numeric_amount, currency, payment_id, payer_hash, c_uuid)
                if row is None:
                    row = await conn.fetchrow(
                        "SELECT * FROM payments WHERE provider_charge_id = $1;", payment_id
                    )
                return _format_row(row)
        return self._run_async(_impl())

    def get_payment(self, payment_id: str) -> Optional[Dict[str, Any]]:
        async def _impl():
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM payments WHERE provider_charge_id = $1;",
                    payment_id,
                )
                return _format_row(row)
        return self._run_async(_impl())

    def activate_subscription_for_couple(
        self,
        couple_id: Any,
        payment_id: str,
        days: int = 30,
        payer_id: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        async def _impl():
            pool = await self._get_pool()
            c_uuid = uuid.UUID(str(couple_id)) if couple_id else None
            async with pool.acquire() as conn:
                async with conn.transaction():
                    pay_row = await conn.fetchrow("""
                        SELECT id, status, couple_id, payer_hash
                        FROM payments
                        WHERE provider_charge_id = $1
                        FOR UPDATE;
                    """, payment_id)

                    if not pay_row:
                        return None

                    if pay_row["status"] in ("succeeded", "refunded"):
                        return None

                    target_couple_uuid = c_uuid or pay_row["couple_id"]
                    if not target_couple_uuid and payer_id:
                        target_couple_uuid = await conn.fetchval(
                            "SELECT couple_id FROM users WHERE telegram_id = $1;", payer_id
                        )

                    entitlement = await conn.fetchrow(
                        "SELECT subscription_until FROM user_subscriptions WHERE payer_hash = $1 FOR UPDATE;",
                        pay_row["payer_hash"],
                    )
                    current_until = entitlement["subscription_until"] if entitlement else None
                    couple_row = None
                    if target_couple_uuid:
                        couple_row = await conn.fetchrow(
                            "SELECT id, subscription_until, partner_1_id, partner_2_id FROM couples WHERE id = $1 FOR UPDATE;",
                            target_couple_uuid,
                        )
                        if couple_row and couple_row["subscription_until"]:
                            current_until = max(current_until, couple_row["subscription_until"]) if current_until else couple_row["subscription_until"]

                    base_until = max(current_until, datetime.now(timezone.utc)) if current_until else datetime.now(timezone.utc)
                    new_until = base_until + timedelta(days=days)

                    await conn.execute("""
                        UPDATE payments
                        SET status = 'succeeded', paid_at = now()
                        WHERE provider_charge_id = $1;
                    """, payment_id)
                    await conn.execute("""
                        INSERT INTO user_subscriptions (payer_hash, subscription_until)
                        VALUES ($1, $2)
                        ON CONFLICT (payer_hash) DO UPDATE
                        SET subscription_until = EXCLUDED.subscription_until, updated_at = now();
                    """, pay_row["payer_hash"], new_until)
                    if couple_row:
                        await conn.execute("UPDATE couples SET subscription_until = $2 WHERE id = $1;", target_couple_uuid, new_until)
                    result = _format_row(couple_row) if couple_row else {}
                    result.update({"id": str(target_couple_uuid) if target_couple_uuid else None,
                                   "subscription_until": new_until.isoformat(),
                                   "partner_1_id": couple_row["partner_1_id"] if couple_row else payer_id,
                                   "partner_2_id": couple_row["partner_2_id"] if couple_row else None})
                    return result
        return self._run_async(_impl())

    def revoke_subscription_for_couple(
        self,
        payment_id: str,
        refund_id: Optional[str] = None,
        days: int = 30,
    ) -> Optional[Dict[str, Any]]:
        async def _impl():
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                async with conn.transaction():
                    pay_row = await conn.fetchrow("""
                        SELECT id, status, couple_id, payer_hash
                        FROM payments
                        WHERE provider_charge_id = $1
                        FOR UPDATE;
                    """, payment_id)

                    if not pay_row:
                        return None

                    target_couple_uuid = pay_row["couple_id"]

                    if pay_row["status"] == "refunded":
                        c_info = None
                        if target_couple_uuid:
                            c_info = await conn.fetchrow(
                                "SELECT id, partner_1_id, partner_2_id, subscription_until FROM couples WHERE id = $1;",
                                target_couple_uuid,
                            )
                        return {
                            "already_refunded": True,
                            "payment_id": payment_id,
                            "couple_id": str(target_couple_uuid) if target_couple_uuid else None,
                            "partner_1_id": c_info["partner_1_id"] if c_info else None,
                            "partner_2_id": c_info["partner_2_id"] if c_info else None,
                            "subscription_until": c_info["subscription_until"].isoformat() if (c_info and c_info["subscription_until"]) else None,
                        }

                    await conn.execute("""
                        UPDATE payments
                        SET status = 'refunded', refund_id = $2, refunded_at = now()
                        WHERE provider_charge_id = $1;
                    """, payment_id, refund_id)

                    await conn.execute("""
                        UPDATE user_subscriptions
                        SET subscription_until = GREATEST(now(), subscription_until - ($2 * interval '1 day')),
                            updated_at = now()
                        WHERE payer_hash = $1;
                    """, pay_row["payer_hash"], days)

                    if not target_couple_uuid:
                        return {
                            "already_refunded": False,
                            "payment_id": payment_id,
                            "couple_id": None,
                            "partner_1_id": None,
                            "partner_2_id": None,
                            "subscription_until": None,
                        }

                    couple_row = await conn.fetchrow("""
                        UPDATE couples
                        SET subscription_until = CASE
                            WHEN subscription_until IS NULL THEN now()
                            WHEN subscription_until - ($2 * interval '1 day') <= now() THEN now()
                            ELSE subscription_until - ($2 * interval '1 day')
                        END
                        WHERE id = $1
                        RETURNING id, subscription_until, partner_1_id, partner_2_id;
                    """, target_couple_uuid, days)

                    if not couple_row:
                        return None

                    res = _format_row(couple_row)
                    res["already_refunded"] = False
                    res["couple_id"] = str(target_couple_uuid)
                    res["payment_id"] = payment_id
                    return res
        return self._run_async(_impl())

    def get_payments_by_payer_hash(self, payer_hash: str) -> List[Dict[str, Any]]:
        async def _impl():
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch("SELECT * FROM payments WHERE payer_hash = $1 ORDER BY created_at DESC;", payer_hash)
                return _format_rows(rows)
        return self._run_async(_impl())

    def get_all_couples(self) -> List[Dict[str, Any]]:
        async def _impl():
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch("SELECT * FROM couples;")
                return _format_rows(rows)
        return self._run_async(_impl())

    def get_admin_stats(self) -> Dict[str, Any]:
        async def _impl():
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                total_users = await conn.fetchval("SELECT count(*) FROM users;")
                total_couples = await conn.fetchval("SELECT count(*) FROM couples;")
                paired_couples = await conn.fetchval("SELECT count(*) FROM couples WHERE partner_2_id IS NOT NULL;")
                waiting_couples = await conn.fetchval("SELECT count(*) FROM couples WHERE partner_2_id IS NULL;")
                total_sessions = await conn.fetchval("SELECT count(*) FROM conflict_sessions;")
                completed_sessions = await conn.fetchval("SELECT count(*) FROM conflict_sessions WHERE status = 'completed';")
                active_sessions = await conn.fetchval("SELECT count(*) FROM conflict_sessions WHERE status NOT IN ('completed', 'cancelled');")
                high_risk_sessions = await conn.fetchval("SELECT count(*) FROM conflict_sessions WHERE risk_level IN ('high', 'critical');")
                return {
                    "total_users": total_users or 0,
                    "active_users": total_users or 0,
                    "total_couples": total_couples or 0,
                    "paired_couples": paired_couples or 0,
                    "waiting_couples": waiting_couples or 0,
                    "total_sessions": total_sessions or 0,
                    "completed_sessions": completed_sessions or 0,
                    "active_sessions": active_sessions or 0,
                    "high_risk_sessions": high_risk_sessions or 0,
                }
        return self._run_async(_impl())

    def check_rate_limit(self, key: str, max_requests: int, window_seconds: int) -> Tuple[bool, int]:
        return self.rate_limiter.check(key, max_requests, window_seconds)

    def record_failed_invite_attempt(self, telegram_id: int) -> None:
        async def _impl():
            pool = await self._get_pool()
            key = f"invite_fail:{telegram_id}"
            async with pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO rate_limits (key, requests, window_start)
                    VALUES ($1, 1, now())
                    ON CONFLICT (key) DO UPDATE
                    SET requests = CASE
                        WHEN rate_limits.window_start <= now() - interval '3600 seconds' THEN 1
                        ELSE rate_limits.requests + 1
                    END,
                    window_start = CASE
                        WHEN rate_limits.window_start <= now() - interval '3600 seconds' THEN now()
                        ELSE rate_limits.window_start
                    END;
                """, key)
        self._run_async(_impl())

    def check_invite_bruteforce(self, telegram_id: int) -> Tuple[bool, int]:
        async def _impl() -> Tuple[bool, int]:
            pool = await self._get_pool()
            key = f"invite_fail:{telegram_id}"
            async with pool.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT requests, window_start
                    FROM rate_limits
                    WHERE key = $1;
                """, key)
                if not row:
                    return False, 0
                reqs = row["requests"]
                w_start = row["window_start"]
                now = datetime.now(timezone.utc)
                if w_start.tzinfo is None:
                    w_start = w_start.replace(tzinfo=timezone.utc)
                elapsed = (now - w_start).total_seconds()
                if elapsed >= 3600:
                    return False, 0
                if reqs >= 5:
                    retry_after = max(1, int(3600 - elapsed) + 1)
                    return True, retry_after
                return False, 0
        return self._run_async(_impl())

    def reset_invite_bruteforce(self, telegram_id: int) -> None:
        async def _impl():
            pool = await self._get_pool()
            key = f"invite_fail:{telegram_id}"
            async with pool.acquire() as conn:
                await conn.execute("DELETE FROM rate_limits WHERE key = $1;", key)
        self._run_async(_impl())

    def cleanup_rate_limits(self, max_age_seconds: int = 3600) -> int:
        async def _impl():
            pool = await self._get_pool()
            cutoff = datetime.now(timezone.utc) - timedelta(seconds=max_age_seconds)
            async with pool.acquire() as conn:
                res = await conn.execute("DELETE FROM rate_limits WHERE window_start <= $1;", cutoff)
                # res is like 'DELETE 5'
                count = int(res.split()[1]) if len(res.split()) > 1 else 0
                return count
        return self._run_async(_impl())

    def cleanup_expired_invites(self, ttl_hours: int = 48) -> int:
        async def _impl():
            pool = await self._get_pool()
            cutoff = datetime.now(timezone.utc) - timedelta(hours=ttl_hours)
            async with pool.acquire() as conn:
                res = await conn.execute("""
                    DELETE FROM couples
                    WHERE partner_2_id IS NULL AND created_at <= $1;
                """, cutoff)
                count = int(res.split()[1]) if len(res.split()) > 1 else 0
                return count
        return self._run_async(_impl())

    def cleanup_expired_payments(self, retention_years: int) -> int:
        async def _impl():
            pool = await self._get_pool()
            now = datetime.now(timezone.utc)
            try:
                cutoff = now.replace(year=now.year - retention_years)
            except ValueError:  # Feb 29 in a leap year -> Feb 28 in the target year.
                cutoff = now.replace(year=now.year - retention_years, day=28)
            async with pool.acquire() as conn:
                res = await conn.execute("DELETE FROM payments WHERE created_at <= $1;", cutoff)
                count = int(res.split()[1]) if len(res.split()) > 1 else 0
                return count
        return self._run_async(_impl())

    def try_advisory_lock(self, lock_id: int) -> bool:
        async def _impl() -> bool:
            if self._advisory_conn is not None:
                return False
            pool = await self._get_pool()
            conn = await pool.acquire()
            try:
                val = await conn.fetchval("SELECT pg_try_advisory_lock($1);", lock_id)
                if val:
                    self._advisory_conn = conn
                    self._advisory_lock_id = lock_id
                    return True
                else:
                    await pool.release(conn)
                    return False
            except Exception:
                await pool.release(conn)
                return False
        return self._run_async(_impl())

    def release_advisory_lock(self, lock_id: int) -> bool:
        async def _impl() -> bool:
            if self._advisory_conn is None:
                return False
            conn = self._advisory_conn
            self._advisory_conn = None
            self._advisory_lock_id = None
            pool = await self._get_pool()
            try:
                val = await conn.fetchval("SELECT pg_advisory_unlock($1);", lock_id)
                return bool(val)
            finally:
                await pool.release(conn)
        return self._run_async(_impl())


