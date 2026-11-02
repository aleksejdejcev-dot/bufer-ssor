"""
Фоновый планировщик очистки данных (Retention Scheduler).
Работает автономно без pg_cron с использованием распределенной блокировки pg_try_advisory_lock.
"""

import asyncio
import logging
from typing import Optional, Dict, Any
from repo.base import Repository

logger = logging.getLogger(__name__)

# Фиксированный идентификатор для pg_try_advisory_lock
RETENTION_ADVISORY_LOCK_ID = 74839201


def clean_pending_inputs(repo: Repository) -> int:
    """Удаляет просроченные зашифрованные исходники по TTL."""
    count = repo.cleanup_expired_pending_inputs()
    if count > 0:
        logger.info("Retention: удалено %d просроченных исходников pending_inputs", count)
    return count


def clean_completed_sessions(repo: Repository, results_retention_days: int = 30) -> int:
    """Обнуляет результаты завершенных сессий старше results_retention_days."""
    res = repo.purge_expired_data(days_retention=results_retention_days)
    purged_sessions = res.get("purged_sessions", 0)
    if purged_sessions > 0:
        logger.info("Retention: обнулено %d сессий старше %d дней", purged_sessions, results_retention_days)
    return purged_sessions


def clean_rate_limits(repo: Repository, max_age_seconds: int = 3600) -> int:
    """Очищает устаревшие счетчики rate_limits."""
    count = repo.cleanup_rate_limits(max_age_seconds=max_age_seconds)
    if count > 0:
        logger.info("Retention: удалено %d устаревших записей rate_limits", count)
    return count


def clean_expired_invites(repo: Repository, ttl_hours: int = 48) -> int:
    """Удаляет неподтвержденные инвайты пар старше ttl_hours."""
    count = repo.cleanup_expired_invites(ttl_hours=ttl_hours)
    if count > 0:
        logger.info("Retention: удалено %d просроченных инвайтов", count)
    return count


def clean_expired_payments(repo: Repository, retention_years: Optional[int]) -> int:
    """Удаляет финансовые транзакции старше retention_years (только если значение задано)."""
    if retention_years is None or retention_years <= 0:
        logger.warning(
            "PAYMENT_RETENTION_YEARS не задан: автоматическое удаление финансовых записей отключено."
        )
        return 0

    count = repo.cleanup_expired_payments(retention_years=retention_years)
    if count > 0:
        logger.info("Retention: удалено %d финансовых записей старше %d лет", count, retention_years)
    return count


def clean_waiting_sessions(repo: Repository) -> int:
    """Переводит просроченные сессии (waiting_partner_2 > 48ч) в статус expired."""
    expired = repo.get_expired_sessions()
    for s in expired:
        repo.expire_session(s["id"])
    if expired:
        logger.info("Retention: переведено %d просроченных сессий в статус expired", len(expired))
    return len(expired)


def run_retention_cycle(
    repo: Repository,
    results_retention_days: int = 30,
    payment_retention_years: Optional[int] = None,
    invite_ttl_hours: int = 48,
    rate_limit_max_age_seconds: int = 3600,
) -> Dict[str, Any]:
    """
    Выполняет один цикл очистки всех типов устаревших данных с защитой через advisory_lock.
    Если блокировка уже занята другим экземпляром, цикл пропускается.
    """
    locked = repo.try_advisory_lock(RETENTION_ADVISORY_LOCK_ID)
    if not locked:
        logger.debug("Retention: advisory lock %d занят другим инстансом, пропуск цикла", RETENTION_ADVISORY_LOCK_ID)
        return {"status": "skipped", "reason": "lock_held"}

    try:
        purged_inputs = clean_pending_inputs(repo)
        purged_sessions = clean_completed_sessions(repo, results_retention_days=results_retention_days)
        purged_rate_limits = clean_rate_limits(repo, max_age_seconds=rate_limit_max_age_seconds)
        purged_invites = clean_expired_invites(repo, ttl_hours=invite_ttl_hours)
        purged_payments = clean_expired_payments(repo, retention_years=payment_retention_years)
        purged_waiting = clean_waiting_sessions(repo)

        return {
            "status": "completed",
            "purged_inputs": purged_inputs,
            "purged_sessions": purged_sessions,
            "purged_rate_limits": purged_rate_limits,
            "purged_invites": purged_invites,
            "purged_payments": purged_payments,
            "purged_waiting": purged_waiting,
        }
    finally:
        repo.release_advisory_lock(RETENTION_ADVISORY_LOCK_ID)


async def retention_worker_loop(
    repo: Repository,
    interval_seconds: int = 3600,
    results_retention_days: int = 30,
    payment_retention_years: Optional[int] = None,
):
    """Фоновый цикл asyncio для запуска в lifespan FastAPI."""
    if payment_retention_years is None:
        logger.warning(
            "Старт приложения: PAYMENT_RETENTION_YEARS не задан. Автоудаление платежей отключено."
        )

    while True:
        try:
            run_retention_cycle(
                repo=repo,
                results_retention_days=results_retention_days,
                payment_retention_years=payment_retention_years,
            )
        except Exception as e:
            logger.exception("Ошибка в цикле фоновой очистки данных: %s", e)

        await asyncio.sleep(interval_seconds)
