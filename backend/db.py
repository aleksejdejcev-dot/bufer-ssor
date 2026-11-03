"""
Модуль доступа к данным (фасад для Repository).
Делегирует все операции активному экземпляру Repository (PostgresRepo или InMemoryRepo).
"""

from typing import Dict, Any, Optional, List, Tuple
from repo import get_repo


def get_user(telegram_id: int) -> Optional[Dict[str, Any]]:
    return get_repo().get_user(telegram_id)


def upsert_user(telegram_id: int, first_name: str, username: Optional[str] = None) -> Dict[str, Any]:
    return get_repo().upsert_user(telegram_id, first_name, username)


def accept_legal(telegram_id: int) -> Dict[str, Any]:
    return get_repo().accept_legal(telegram_id)


def get_couple_by_id(couple_id: str) -> Optional[Dict[str, Any]]:
    return get_repo().get_couple_by_id(couple_id)


def get_couple_by_invite(invite_code: str) -> Optional[Dict[str, Any]]:
    return get_repo().get_couple_by_invite(invite_code)


def get_user_couple(telegram_id: int) -> Optional[Dict[str, Any]]:
    return get_repo().get_user_couple(telegram_id)


def create_couple(partner_1_id: int, invite_code: str) -> Dict[str, Any]:
    return get_repo().create_couple(partner_1_id, invite_code)


def join_couple(couple_id: str, partner_2_id: int) -> Dict[str, Any]:
    return get_repo().join_couple(couple_id, partner_2_id)


def update_mood(couple_id: str, is_partner_1: bool, mood: int) -> Dict[str, Any]:
    return get_repo().update_mood(couple_id, is_partner_1, mood)


def decrement_free_sessions(couple_id: str) -> None:
    return get_repo().decrement_free_sessions(couple_id)


def check_couple_access(couple: Dict[str, Any]) -> Tuple[bool, str]:
    return get_repo().check_couple_access(couple)


def add_free_sessions(couple_id: str, count: int) -> Dict[str, Any]:
    return get_repo().add_free_sessions(couple_id, count)


def get_active_session(couple_id: str) -> Optional[Dict[str, Any]]:
    return get_repo().get_active_session(couple_id)


def get_session_by_id(session_id: str) -> Optional[Dict[str, Any]]:
    return get_repo().get_session_by_id(session_id)


def create_conflict_session(couple_id: str, initiator_id: int) -> Dict[str, Any]:
    return get_repo().create_conflict_session(couple_id, initiator_id)


def update_session_status(
    session_id: str,
    status: str,
    completed_at: Optional[str] = None,
    risk_level: Optional[str] = None,
) -> None:
    return get_repo().update_session_status(session_id, status, completed_at, risk_level)


def claim_session_for_analysis(session_id: str) -> bool:
    return get_repo().claim_session_for_analysis(session_id)


def save_analysis_results(
    session_id: str,
    results: Dict[str, Any],
    risk_level: str,
    completed_at: str,
) -> None:
    return get_repo().save_analysis_results(session_id, results, risk_level, completed_at)


def get_expired_sessions() -> List[Dict[str, Any]]:
    return get_repo().get_expired_sessions()


def expire_session(session_id: str) -> None:
    return get_repo().expire_session(session_id)


def save_pending_input(
    session_id: str,
    author_telegram_id: int,
    kind: str,
    payload_encrypted: bytes,
) -> Dict[str, Any]:
    return get_repo().save_pending_input(session_id, author_telegram_id, kind, payload_encrypted)


def has_user_submitted_input(session_id: str, author_telegram_id: int) -> bool:
    return get_repo().has_user_submitted_input(session_id, author_telegram_id)


def count_pending_inputs(session_id: str) -> int:
    return get_repo().count_pending_inputs(session_id)


def get_pending_inputs(session_id: str) -> List[Dict[str, Any]]:
    return get_repo().get_pending_inputs(session_id)


def delete_pending_input_for_author(session_id: str, author_telegram_id: int) -> None:
    return get_repo().delete_pending_input_for_author(session_id, author_telegram_id)


def delete_pending_inputs_for_session(session_id: str) -> None:
    return get_repo().delete_pending_inputs_for_session(session_id)


def cleanup_expired_pending_inputs() -> int:
    return get_repo().cleanup_expired_pending_inputs()


def delete_history(couple_id: str, initiated_by: Optional[int] = None) -> None:
    return get_repo().delete_history(couple_id, initiated_by=initiated_by)


def purge_expired_data(days_retention: int = 30, hours_raw_ttl: int = 48) -> Dict[str, int]:
    return get_repo().purge_expired_data(days_retention=days_retention, hours_raw_ttl=hours_raw_ttl)


def delete_couple_data(couple_id: str, initiated_by: Optional[int] = None) -> None:
    return get_repo().delete_couple_data(couple_id, initiated_by=initiated_by)


def save_payment(
    product: str,
    amount: int,
    currency: str,
    provider_charge_id: str,
    payer_hash: str,
    couple_id: Optional[str] = None,
) -> Dict[str, Any]:
    return get_repo().save_payment(product, amount, currency, provider_charge_id, payer_hash, couple_id)


def create_payment(
    couple_id: Any,
    user_id: Any,
    payment_id: str,
    amount: Any,
    currency: str = "RUB",
    product: str = "month_sub",
) -> Dict[str, Any]:
    return get_repo().create_payment(couple_id, user_id, payment_id, amount, currency, product)


def get_payment(payment_id: str) -> Optional[Dict[str, Any]]:
    return get_repo().get_payment(payment_id)


def activate_subscription_for_couple(
    couple_id: Any,
    payment_id: str,
    days: int = 30,
) -> Optional[Dict[str, Any]]:
    return get_repo().activate_subscription_for_couple(couple_id, payment_id, days)


def revoke_subscription_for_couple(
    payment_id: str,
    refund_id: Optional[str] = None,
    days: int = 30,
) -> Optional[Dict[str, Any]]:
    return get_repo().revoke_subscription_for_couple(payment_id, refund_id, days)


def get_payments_by_payer_hash(payer_hash: str) -> List[Dict[str, Any]]:
    return get_repo().get_payments_by_payer_hash(payer_hash)


def get_all_couples() -> List[Dict[str, Any]]:
    return get_repo().get_all_couples()


def get_admin_stats() -> Dict[str, Any]:
    return get_repo().get_admin_stats()


def check_rate_limit(key: str, max_requests: int, window_seconds: int) -> Tuple[bool, int]:
    return get_repo().check_rate_limit(key, max_requests, window_seconds)


def record_failed_invite_attempt(telegram_id: int) -> None:
    return get_repo().record_failed_invite_attempt(telegram_id)


def check_invite_bruteforce(telegram_id: int) -> Tuple[bool, int]:
    return get_repo().check_invite_bruteforce(telegram_id)


def reset_invite_bruteforce(telegram_id: int) -> None:
    return get_repo().reset_invite_bruteforce(telegram_id)


# Алиасы для обратной совместимости
get_session = get_session_by_id
get_couple = get_couple_by_id
get_pending_inputs_for_session = get_pending_inputs
