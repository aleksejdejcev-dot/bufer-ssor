"""
Интерфейс слоя доступа к данным (Repository).
Используется сервисами ai_service.py, bot.py, main.py без прямой привязки к БД.
"""

from typing import Protocol, Dict, Any, Optional, List, Tuple


class Repository(Protocol):
    def get_user(self, telegram_id: int) -> Optional[Dict[str, Any]]:
        ...

    def upsert_user(self, telegram_id: int, first_name: str, username: Optional[str] = None) -> Dict[str, Any]:
        ...

    def accept_legal(self, telegram_id: int) -> Dict[str, Any]:
        ...

    def get_couple_by_id(self, couple_id: str) -> Optional[Dict[str, Any]]:
        ...

    def get_couple_by_invite(self, invite_code: str) -> Optional[Dict[str, Any]]:
        ...

    def get_user_couple(self, telegram_id: int) -> Optional[Dict[str, Any]]:
        ...

    def create_couple(self, partner_1_id: int, invite_code: str) -> Dict[str, Any]:
        ...

    def join_couple(self, couple_id: str, partner_2_id: int) -> Dict[str, Any]:
        ...

    def update_mood(self, couple_id: str, is_partner_1: bool, mood: int) -> Dict[str, Any]:
        ...

    def decrement_free_sessions(self, couple_id: str) -> None:
        ...

    def create_conflict_session_with_access(self, couple_id: str, initiator_id: int) -> Optional[Dict[str, Any]]:
        """Атомарно создает сессию и списывает бесплатный разбор, если подписки нет."""
        ...

    def check_couple_access(self, couple: Dict[str, Any]) -> Tuple[bool, str]:
        ...

    def get_subscription_until_for_user(self, telegram_id: int) -> Optional[str]:
        ...

    def cleanup_expired_subscriptions(self) -> int:
        """Deletes expired payer entitlements and clears expired legacy couple dates."""
        ...

    def add_free_sessions(self, couple_id: str, count: int) -> Dict[str, Any]:
        ...

    def get_active_session(self, couple_id: str) -> Optional[Dict[str, Any]]:
        ...

    def get_session_by_id(self, session_id: str) -> Optional[Dict[str, Any]]:
        ...

    def create_conflict_session(self, couple_id: str, initiator_id: int) -> Dict[str, Any]:
        ...

    def update_session_status(
        self,
        session_id: str,
        status: str,
        completed_at: Optional[str] = None,
        risk_level: Optional[str] = None,
    ) -> None:
        ...

    def claim_session_for_analysis(self, session_id: str) -> bool:
        """
        Атомарно пытается перевести сессию в статус 'processing' для выполнения разбора.
        Возвращает True при успешном захвате, False если сессия уже обрабатывается или завершена.
        """
        ...

    def save_analysis_results(
        self,
        session_id: str,
        results: Dict[str, Any],
        risk_level: str,
        completed_at: str,
    ) -> None:
        """
        Временная запись результатов до взаимного подтверждения завершения;
        исходники удаляются после анализа, а карточки — по подтверждению или TTL.
        """
        ...

    def confirm_conflict_finished(self, session_id: str, telegram_id: int) -> bool:
        """Records participant confirmation and deletes results after both confirm."""
        ...

    def get_expired_sessions(self) -> List[Dict[str, Any]]:
        ...

    def expire_session(self, session_id: str) -> None:
        ...

    def save_pending_input(
        self,
        session_id: str,
        author_telegram_id: int,
        kind: str,
        payload_encrypted: bytes,
    ) -> Dict[str, Any]:
        ...

    def has_user_submitted_input(self, session_id: str, author_telegram_id: int) -> bool:
        ...

    def count_pending_inputs(self, session_id: str) -> int:
        ...

    def get_pending_inputs(self, session_id: str) -> List[Dict[str, Any]]:
        ...

    def delete_pending_input_for_author(self, session_id: str, author_telegram_id: int) -> None:
        ...

    def delete_pending_inputs_for_session(self, session_id: str) -> None:
        ...

    def cleanup_expired_pending_inputs(self) -> int:
        ...

    def delete_history(self, couple_id: str, initiated_by: Optional[int] = None) -> None:
        """Удаляет только сессии и историю ссоры пары, профили и подписка остаются."""
        ...

    def purge_expired_data(self, days_retention: int = 2, hours_raw_ttl: int = 48) -> Dict[str, int]:
        """
        Очистка завершенных сессий по настроенному сроку и удаление зависших сырых данных pending_inputs.
        """
        ...

    def delete_couple_data(self, couple_id: str, initiated_by: Optional[int] = None) -> None:
        """Удаляет пару, её историю и профили; подписку плательщика и платёжный учёт сохраняет."""
        ...

    def save_payment(
        self,
        product: str,
        amount: int,
        currency: str,
        provider_charge_id: str,
        payer_hash: str,
        couple_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        ...

    def create_payment(
        self,
        couple_id: Any,
        user_id: Any,
        payment_id: str,
        amount: Any,
        currency: str = "RUB",
        product: str = "month_sub",
    ) -> Dict[str, Any]:
        """Создает запись о платеже со статусом pending."""
        ...

    def get_payment(self, payment_id: str) -> Optional[Dict[str, Any]]:
        """Возвращает данные платежа по ID платежного провайдера (provider_charge_id)."""
        ...

    def activate_subscription_for_couple(
        self,
        couple_id: Any,
        payment_id: str,
        days: int = 30,
        payer_id: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Идемпотентно активирует подписку владельца платежа при успешной оплате.
        Если платеж уже обработан (status == 'succeeded'), возвращает None.
        Обновляет платеж и персональное право подписки в единой транзакции.
        """
        ...

    def revoke_subscription_for_couple(
        self,
        payment_id: str,
        refund_id: Optional[str] = None,
        days: int = 30,
    ) -> Optional[Dict[str, Any]]:
        """
        Идемпотентно аннулирует подписку для пары при успешном возврате средств (refund.succeeded).
        Устанавливает payment.status = 'refunded', сохраняет refund_id.
        Уменьшает subscription_until у couples на days (или устанавливает в now(), если оплаченный период истек).
        Возвращает данные пары и признак already_refunded=True/False.
        """
        ...

    def get_payments_by_payer_hash(self, payer_hash: str) -> List[Dict[str, Any]]:
        ...

    def get_all_couples(self) -> List[Dict[str, Any]]:
        ...

    def get_admin_stats(self) -> Dict[str, Any]:
        ...

    def reset_state(self) -> None:
        ...

    def check_rate_limit(self, key: str, max_requests: int, window_seconds: int) -> Tuple[bool, int]:
        ...

    def cleanup_rate_limits(self, max_age_seconds: int = 3600) -> int:
        ...

    def cleanup_expired_invites(self, ttl_hours: int = 48) -> int:
        ...

    def cleanup_expired_payments(self, retention_years: int) -> int:
        ...

    def try_advisory_lock(self, lock_id: int) -> bool:
        ...

    def release_advisory_lock(self, lock_id: int) -> bool:
        ...


    def record_failed_invite_attempt(self, telegram_id: int) -> None:
        ...

    def check_invite_bruteforce(self, telegram_id: int) -> Tuple[bool, int]:
        ...

    def reset_invite_bruteforce(self, telegram_id: int) -> None:
        ...

    def get_deletions_log(self) -> List[Dict[str, Any]]:
        ...
