"""
InMemory реализация интерфейса Repository для локальных тестов и работы без сети.
"""

import uuid
import threading
import hashlib
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List, Tuple
from config import settings
from rate_limiter import RateLimiter, normalize_invite_code


class InMemoryRepo:
    def __init__(self):
        self._session_lock = threading.RLock()
        self.users: Dict[int, Dict[str, Any]] = {}
        self.couples: Dict[str, Dict[str, Any]] = {}
        self.conflict_sessions: Dict[str, Dict[str, Any]] = {}
        self.pending_inputs: Dict[str, Dict[str, Any]] = {}
        self.payments: Dict[str, Dict[str, Any]] = {}
        self.user_subscriptions: Dict[str, str] = {}
        self.rate_limiter = RateLimiter()
        self.advisory_locks: set[int] = set()
        self.deletions_log: List[Dict[str, Any]] = []

    def reset_state(self) -> None:
        self.users.clear()
        self.couples.clear()
        self.conflict_sessions.clear()
        self.pending_inputs.clear()
        self.payments.clear()
        self.user_subscriptions.clear()
        self.rate_limiter = RateLimiter()
        self.advisory_locks.clear()
        self.deletions_log.clear()
        self.payments.clear()
        self.rate_limiter.clear()

    def get_user(self, telegram_id: int) -> Optional[Dict[str, Any]]:
        return self.users.get(telegram_id)

    def upsert_user(self, telegram_id: int, first_name: str, username: Optional[str] = None) -> Dict[str, Any]:
        user = self.users.get(telegram_id)
        if user:
            user["first_name"] = first_name
            if username:
                user["username"] = username
            return user

        user = {
            "telegram_id": telegram_id,
            "first_name": first_name,
            "username": username,
            "accepted_legal_at": None,
            "couple_id": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self.users[telegram_id] = user
        return user

    def accept_legal(self, telegram_id: int) -> Dict[str, Any]:
        user = self.upsert_user(telegram_id, first_name="Партнер")
        user["accepted_legal_at"] = datetime.now(timezone.utc).isoformat()
        return user

    def get_couple_by_id(self, couple_id: str) -> Optional[Dict[str, Any]]:
        return self.couples.get(couple_id)

    def get_couple_by_invite(self, invite_code: str) -> Optional[Dict[str, Any]]:
        target_norm = invite_code.replace("-", "").strip().upper()
        for c in self.couples.values():
            c_norm = c.get("invite_code", "").replace("-", "").strip().upper()
            if c_norm == target_norm:
                return c
        return None

    def get_user_couple(self, telegram_id: int) -> Optional[Dict[str, Any]]:
        user = self.get_user(telegram_id)
        if user and user.get("couple_id"):
            c = self.get_couple_by_id(user["couple_id"])
            if c:
                return c
        for c in self.couples.values():
            if c.get("partner_1_id") == telegram_id or c.get("partner_2_id") == telegram_id:
                return c
        return None

    def create_couple(self, partner_1_id: int, invite_code: str) -> Dict[str, Any]:
        c_id = str(uuid.uuid4())
        now_dt = datetime.now(timezone.utc)
        now = now_dt.isoformat()
        couple = {
            "id": c_id,
            "partner_1_id": partner_1_id,
            "partner_2_id": None,
            "invite_code": invite_code,
            "invite_created_at": now,
            "invite_expires_at": (now_dt + timedelta(days=7)).isoformat(),
            "free_sessions_left": 2,
            "subscription_until": None,
            "mood_p1": None,
            "mood_p2": None,
            "created_at": now,
        }
        self.couples[c_id] = couple
        if partner_1_id in self.users:
            self.users[partner_1_id]["couple_id"] = c_id
        return couple

    def join_couple(self, couple_id: str, partner_2_id: int) -> Dict[str, Any]:
        c = self.couples.get(couple_id)
        if not c or c.get("partner_2_id") is not None:
            raise ValueError("Пара уже заполнена или не существует")
        c["partner_2_id"] = partner_2_id
        if partner_2_id in self.users:
            self.users[partner_2_id]["couple_id"] = couple_id
        return c

    def update_mood(self, couple_id: str, is_partner_1: bool, mood: int) -> Dict[str, Any]:
        c = self.couples.get(couple_id)
        if not c:
            raise ValueError("Couple not found")
        now = datetime.now(timezone.utc).isoformat()
        if is_partner_1:
            c["mood_p1"] = mood
            c["mood_updated_at_p1"] = now
        else:
            c["mood_p2"] = mood
            c["mood_updated_at_p2"] = now
        return c

    def decrement_free_sessions(self, couple_id: str) -> None:
        c = self.couples.get(couple_id)
        if c and c.get("free_sessions_left", 0) > 0:
            c["free_sessions_left"] -= 1

    def check_couple_access(self, couple: Dict[str, Any]) -> Tuple[bool, str]:
        for member_id in (couple.get("partner_1_id"), couple.get("partner_2_id")):
            until = self.get_subscription_until_for_user(member_id) if member_id else None
            if until:
                try:
                    if datetime.fromisoformat(until) > datetime.now(timezone.utc):
                        return True, "subscription"
                except Exception:
                    pass
        sub_until = couple.get("subscription_until")
        if sub_until:
            try:
                sub_dt = datetime.fromisoformat(sub_until)
                if sub_dt > datetime.now(timezone.utc):
                    return True, "subscription"
            except Exception:
                pass
        if couple.get("free_sessions_left", 0) > 0:
            return True, "free_session"
        return False, "no_access"

    def get_subscription_until_for_user(self, telegram_id: int) -> Optional[str]:
        until = self.user_subscriptions.get(self._hash_id(telegram_id))
        couple = self.get_user_couple(telegram_id)
        member_until = [self.user_subscriptions.get(self._hash_id(member_id))
                        for member_id in ((couple or {}).get("partner_1_id"), (couple or {}).get("partner_2_id"))
                        if member_id]
        values = [value for value in [until, *(member_until or [])] if value]
        legacy = couple.get("subscription_until") if couple else None
        if legacy:
            values.append(legacy)
        valid = []
        for value in values:
            try:
                parsed = datetime.fromisoformat(value)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                if parsed > datetime.now(timezone.utc):
                    valid.append((parsed, value))
            except Exception:
                continue
        return max(valid, default=(None, None))[1]

    def cleanup_expired_subscriptions(self) -> int:
        now = datetime.now(timezone.utc)
        expired = []
        for payer_hash, value in self.user_subscriptions.items():
            try:
                until = datetime.fromisoformat(value)
                if until.tzinfo is None:
                    until = until.replace(tzinfo=timezone.utc)
                if until <= now:
                    expired.append(payer_hash)
            except Exception:
                expired.append(payer_hash)
        for payer_hash in expired:
            self.user_subscriptions.pop(payer_hash, None)
        for couple in self.couples.values():
            until = couple.get("subscription_until")
            if until:
                try:
                    dt = datetime.fromisoformat(until)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    if dt <= now:
                        couple["subscription_until"] = None
                except Exception:
                    couple["subscription_until"] = None
        return len(expired)

    def add_free_sessions(self, couple_id: str, count: int) -> Dict[str, Any]:
        c = self.couples.get(couple_id)
        if c:
            c["free_sessions_left"] = c.get("free_sessions_left", 0) + count
        return c

    def get_active_session(self, couple_id: str) -> Optional[Dict[str, Any]]:
        active = [
            s for s in self.conflict_sessions.values()
            if s.get("couple_id") == couple_id and s.get("status") in ("waiting_partner_2", "analyzing")
        ]
        if active:
            active.sort(key=lambda x: x.get("created_at", ""), reverse=True)
            return active[0]
        return None

    def get_session_by_id(self, session_id: str) -> Optional[Dict[str, Any]]:
        return self.conflict_sessions.get(session_id)

    def create_conflict_session(self, couple_id: str, initiator_id: int) -> Dict[str, Any]:
        s_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        session = {
            "id": s_id,
            "couple_id": couple_id,
            "initiator_id": initiator_id,
            "status": "waiting_partner_2",
            "risk_level": "none",
            "shared_summary": None,
            "ai_advice_p1": None,
            "ai_advice_p2": None,
            "created_at": now,
            "completed_at": None,
        }
        self.conflict_sessions[s_id] = session
        return session

    def create_conflict_session_with_access(self, couple_id: str, initiator_id: int) -> Optional[Dict[str, Any]]:
        with self._session_lock:
            couple = self.couples.get(couple_id)
            if not couple or not self.check_couple_access(couple)[0] or self.get_active_session(couple_id):
                return None
            sub_until = couple.get("subscription_until")
            premium = False
            if sub_until:
                try:
                    premium = datetime.fromisoformat(sub_until) > datetime.now(timezone.utc)
                except Exception:
                    premium = False
            session = self.create_conflict_session(couple_id, initiator_id)
            if not premium:
                couple["free_sessions_left"] = max(0, couple.get("free_sessions_left", 0) - 1)
            return session

    def update_session_status(
        self,
        session_id: str,
        status: str,
        completed_at: Optional[str] = None,
        risk_level: Optional[str] = None,
    ) -> None:
        s = self.conflict_sessions.get(session_id)
        if s:
            s["status"] = status
            if completed_at:
                s["completed_at"] = completed_at
            if risk_level:
                s["risk_level"] = risk_level

    def claim_session_for_analysis(self, session_id: str) -> bool:
        s = self.conflict_sessions.get(session_id)
        if not s:
            return False
        if s.get("status") in ("processing", "analyzing", "completed", "failed", "expired", "purged_by_retention"):
            return False
        s["status"] = "processing"
        return True

    def save_analysis_results(
        self,
        session_id: str,
        results: Dict[str, Any],
        risk_level: str,
        completed_at: str,
    ) -> None:
        s = self.conflict_sessions.get(session_id)
        if s:
            s["ai_advice_p1"] = results.get("partner_1_response") or results.get("partner_1_card") or results.get("ai_advice_p1")
            s["ai_advice_p2"] = results.get("partner_2_response") or results.get("partner_2_card") or results.get("ai_advice_p2")
            s["shared_summary"] = results.get("shared_summary")
            s["risk_level"] = risk_level
            s["status"] = "completed"
            s["completed_at"] = completed_at
        # Удаление pending_inputs
        self.delete_pending_inputs_for_session(session_id)

    def get_expired_sessions(self) -> List[Dict[str, Any]]:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=settings.EXPIRATION_HOURS)).isoformat()
        return [
            s for s in self.conflict_sessions.values()
            if s.get("status") == "waiting_partner_2" and s.get("created_at", "") <= cutoff
        ]

    def expire_session(self, session_id: str) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        self.update_session_status(session_id, status="expired", completed_at=now_iso)
        self.delete_pending_inputs_for_session(session_id)

    def save_pending_input(
        self,
        session_id: str,
        author_telegram_id: int,
        kind: str,
        payload_encrypted: bytes,
    ) -> Dict[str, Any]:
        p_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        expires_at = (now + timedelta(hours=getattr(settings, "RAW_INPUT_TTL_HOURS", 48))).isoformat()
        item = {
            "id": p_id,
            "session_id": session_id,
            "author_telegram_id": author_telegram_id,
            "kind": kind,
            "payload_encrypted": payload_encrypted,
            "created_at": now.isoformat(),
            "expires_at": expires_at,
        }
        self.pending_inputs[p_id] = item
        return item

    def has_user_submitted_input(self, session_id: str, author_telegram_id: int) -> bool:
        return any(
            p.get("session_id") == session_id and p.get("author_telegram_id") == author_telegram_id
            for p in self.pending_inputs.values()
        )

    def count_pending_inputs(self, session_id: str) -> int:
        return sum(1 for p in self.pending_inputs.values() if p.get("session_id") == session_id)

    def get_pending_inputs(self, session_id: str) -> List[Dict[str, Any]]:
        res = [p for p in self.pending_inputs.values() if p.get("session_id") == session_id]
        res.sort(key=lambda x: x.get("created_at", ""))
        return res

    def delete_pending_input_for_author(self, session_id: str, author_telegram_id: int) -> None:
        to_del = [
            pid for pid, p in self.pending_inputs.items()
            if p.get("session_id") == session_id and p.get("author_telegram_id") == author_telegram_id
        ]
        for pid in to_del:
            del self.pending_inputs[pid]

    def delete_pending_inputs_for_session(self, session_id: str) -> None:
        to_del = [pid for pid, p in self.pending_inputs.items() if p.get("session_id") == session_id]
        for pid in to_del:
            del self.pending_inputs[pid]

    def cleanup_expired_pending_inputs(self) -> int:
        now_iso = datetime.now(timezone.utc).isoformat()
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=getattr(settings, "RAW_INPUT_TTL_HOURS", 48))).isoformat()
        to_del = [
            pid for pid, p in self.pending_inputs.items()
            if (p.get("expires_at") and p["expires_at"] <= now_iso)
            or (p.get("created_at") and p["created_at"] <= cutoff)
        ]
        for pid in to_del:
            del self.pending_inputs[pid]
        return len(to_del)

    def _hash_id(self, val: Any) -> str:
        salt = getattr(settings, "PAYMENT_HASH_KEY", "buffer_salt")
        return hashlib.sha256(f"{val}:{salt}".encode("utf-8")).hexdigest()

    def delete_history(self, couple_id: str, initiated_by: Optional[int] = None) -> None:
        """Удаляет только сессии и историю пары, профили и подписка остаются."""
        c_hash = self._hash_id(couple_id)
        u_hash = self._hash_id(initiated_by) if initiated_by else "unknown"
        self.deletions_log.append({
            "id": str(uuid.uuid4()),
            "couple_id_hash": c_hash,
            "initiated_by_hash": u_hash,
            "entity_type": "history",
            "deleted_at": datetime.now(timezone.utc).isoformat(),
        })
        s_ids = [s_id for s_id, s in self.conflict_sessions.items() if s.get("couple_id") == couple_id]
        for pid in list(self.pending_inputs.keys()):
            if self.pending_inputs[pid].get("session_id") in s_ids:
                del self.pending_inputs[pid]
        for sid in s_ids:
            del self.conflict_sessions[sid]
        couple = self.couples.get(couple_id)
        if couple:
            couple["mood_p1"] = None
            couple["mood_p2"] = None
            couple["mood_updated_at_p1"] = None
            couple["mood_updated_at_p2"] = None

    def purge_expired_data(self, days_retention: int = 30, hours_raw_ttl: int = 48) -> Dict[str, int]:
        now = datetime.now(timezone.utc)
        sess_cutoff = (now - timedelta(days=days_retention)).isoformat()
        inp_cutoff = (now - timedelta(hours=hours_raw_ttl)).isoformat()

        purged_sessions = 0
        for s in self.conflict_sessions.values():
            if s.get("status") == "completed":
                c_at = s.get("completed_at") or ""
                if c_at and c_at <= sess_cutoff:
                    s["ai_advice_p1"] = None
                    s["ai_advice_p2"] = None
                    s["shared_summary"] = None
                    s["status"] = "purged_by_retention"
                    purged_sessions += 1

        purged_inputs = 0
        for pid in list(self.pending_inputs.keys()):
            inp = self.pending_inputs[pid]
            c_at = inp.get("created_at") or ""
            exp_at = inp.get("expires_at") or ""
            if (c_at and c_at <= inp_cutoff) or (exp_at and exp_at <= now.isoformat()):
                del self.pending_inputs[pid]
                purged_inputs += 1

        return {"purged_sessions": purged_sessions, "purged_inputs": purged_inputs}

    def delete_couple_data(self, couple_id: str, initiated_by: Optional[int] = None) -> None:
        """Удаляет пару, её историю и профили; подписку плательщика и платёжный учёт сохраняет."""
        c_hash = self._hash_id(couple_id)
        u_hash = self._hash_id(initiated_by) if initiated_by else "unknown"
        self.deletions_log.append({
            "id": str(uuid.uuid4()),
            "couple_id_hash": c_hash,
            "initiated_by_hash": u_hash,
            "entity_type": "couple",
            "deleted_at": datetime.now(timezone.utc).isoformat(),
        })
        couple = self.couples.get(couple_id)
        p1_id = couple.get("partner_1_id") if couple else None
        p2_id = couple.get("partner_2_id") if couple else None

        # 1. Удаляем историю сессий и исходников (без повторной записи в deletions_log)
        s_ids = [s_id for s_id, s in self.conflict_sessions.items() if s.get("couple_id") == couple_id]
        for pid in list(self.pending_inputs.keys()):
            if self.pending_inputs[pid].get("session_id") in s_ids:
                del self.pending_inputs[pid]
        for sid in s_ids:
            del self.conflict_sessions[sid]

        # 2. Удаляем пару
        if couple_id in self.couples:
            del self.couples[couple_id]

        # 3. Удаляем профили обоих партнеров
        if p1_id and p1_id in self.users:
            del self.users[p1_id]
        if p2_id and p2_id in self.users:
            del self.users[p2_id]

        # 4. В записях платежей ставим couple_id = None (ON DELETE SET NULL)
        for pay in self.payments.values():
            if pay.get("couple_id") == couple_id:
                pay["couple_id"] = None

    def get_deletions_log(self) -> List[Dict[str, Any]]:
        return list(self.deletions_log)

    def save_payment(
        self,
        product: str,
        amount: int,
        currency: str,
        provider_charge_id: str,
        payer_hash: str,
        couple_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        pay_id = str(uuid.uuid4())
        item = {
            "id": pay_id,
            "product": product,
            "amount": amount,
            "currency": currency,
            "provider_charge_id": provider_charge_id,
            "payer_hash": payer_hash,
            "couple_id": couple_id,
            "status": "succeeded",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self.payments[pay_id] = item
        return item

    def create_payment(
        self,
        couple_id: Any,
        user_id: Any,
        payment_id: str,
        amount: Any,
        currency: str = "RUB",
        product: str = "month_sub",
    ) -> Dict[str, Any]:
        pay_id = str(uuid.uuid4())
        item = {
            "id": pay_id,
            "product": product,
            "amount": float(amount) if hasattr(amount, "__float__") else amount,
            "currency": currency,
            "provider_charge_id": payment_id,
            "payer_hash": self._hash_id(user_id),
            "couple_id": str(couple_id) if couple_id else None,
            "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "paid_at": None,
        }
        for p in self.payments.values():
            if p.get("provider_charge_id") == payment_id:
                p.update(item)
                return p
        self.payments[pay_id] = item
        return item

    def get_payment(self, payment_id: str) -> Optional[Dict[str, Any]]:
        for p in self.payments.values():
            if p.get("provider_charge_id") == payment_id:
                return dict(p)
        return None

    def activate_subscription_for_couple(
        self,
        couple_id: Any,
        payment_id: str,
        days: int = 30,
        payer_id: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        target_pay = None
        for p in self.payments.values():
            if p.get("provider_charge_id") == payment_id:
                target_pay = p
                break

        if not target_pay:
            return None

        if target_pay.get("status") == "succeeded":
            return None

        c_id = str(couple_id) if couple_id else target_pay.get("couple_id")
        if not c_id and payer_id:
            user_couple = self.get_user_couple(payer_id)
            c_id = user_couple.get("id") if user_couple else None

        target_pay["status"] = "succeeded"
        target_pay["paid_at"] = datetime.now(timezone.utc).isoformat()

        now = datetime.now(timezone.utc)
        payer_hash = target_pay["payer_hash"]
        couple = self.couples.get(c_id) if c_id else None
        current_until = self.user_subscriptions.get(payer_hash) or (couple.get("subscription_until") if couple else None)
        if current_until:
            try:
                dt = datetime.fromisoformat(current_until)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                base_date = max(now, dt)
            except Exception:
                base_date = now
        else:
            base_date = now

        new_until = (base_date + timedelta(days=days)).isoformat()
        self.user_subscriptions[payer_hash] = new_until

        if couple:
            couple["subscription_until"] = new_until

        return {
            "id": couple["id"] if couple else None,
            "subscription_until": new_until,
            "partner_1_id": couple.get("partner_1_id") if couple else payer_id,
            "partner_2_id": couple.get("partner_2_id") if couple else None,
        }

    def revoke_subscription_for_couple(
        self,
        payment_id: str,
        refund_id: Optional[str] = None,
        days: int = 30,
    ) -> Optional[Dict[str, Any]]:
        target_pay = None
        for p in self.payments.values():
            if p.get("provider_charge_id") == payment_id:
                target_pay = p
                break

        if not target_pay:
            return None

        c_id = str(target_pay.get("couple_id") or "")
        couple = self.couples.get(c_id)

        if target_pay.get("status") == "refunded":
            return {
                "already_refunded": True,
                "payment_id": payment_id,
                "couple_id": c_id,
                "partner_1_id": couple.get("partner_1_id") if couple else None,
                "partner_2_id": couple.get("partner_2_id") if couple else None,
                "subscription_until": couple.get("subscription_until") if couple else None,
            }

        target_pay["status"] = "refunded"
        target_pay["refund_id"] = refund_id
        target_pay["refunded_at"] = datetime.now(timezone.utc).isoformat()
        current_owner_until = self.user_subscriptions.get(target_pay.get("payer_hash"))
        if current_owner_until:
            owner_dt = datetime.fromisoformat(current_owner_until)
            now_utc = datetime.now(timezone.utc)
            if owner_dt.tzinfo is None:
                owner_dt = owner_dt.replace(tzinfo=timezone.utc)
            self.user_subscriptions[target_pay["payer_hash"]] = max(now_utc, owner_dt - timedelta(days=days)).isoformat()

        if not couple:
            return {
                "already_refunded": False,
                "payment_id": payment_id,
                "couple_id": c_id,
                "partner_1_id": None,
                "partner_2_id": None,
                "subscription_until": None,
            }

        now = datetime.now(timezone.utc)
        current_until = couple.get("subscription_until")
        if current_until:
            try:
                dt = datetime.fromisoformat(current_until)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                reduced_dt = dt - timedelta(days=days)
                if reduced_dt <= now:
                    new_until = now.isoformat()
                else:
                    new_until = reduced_dt.isoformat()
            except Exception:
                new_until = now.isoformat()
        else:
            new_until = now.isoformat()

        couple["subscription_until"] = new_until

        return {
            "already_refunded": False,
            "id": couple["id"],
            "couple_id": couple["id"],
            "subscription_until": new_until,
            "partner_1_id": couple["partner_1_id"],
            "partner_2_id": couple.get("partner_2_id"),
        }

    def get_payments_by_payer_hash(self, payer_hash: str) -> List[Dict[str, Any]]:
        return [p for p in self.payments.values() if p.get("payer_hash") == payer_hash]

    def get_all_couples(self) -> List[Dict[str, Any]]:
        return list(self.couples.values())

    def get_admin_stats(self) -> Dict[str, Any]:
        paired = sum(1 for c in self.couples.values() if c.get("partner_2_id"))
        waiting = sum(1 for c in self.couples.values() if not c.get("partner_2_id"))
        completed = sum(1 for s in self.conflict_sessions.values() if s.get("status") == "completed")
        active = sum(1 for s in self.conflict_sessions.values() if s.get("status") not in ("completed", "cancelled"))
        high_risk = sum(1 for s in self.conflict_sessions.values() if s.get("risk_level") in ("high", "critical"))
        return {
            "total_users": len(self.users),
            "active_users": len(self.users),
            "total_couples": len(self.couples),
            "paired_couples": paired,
            "waiting_couples": waiting,
            "total_sessions": len(self.conflict_sessions),
            "completed_sessions": completed,
            "active_sessions": active,
            "high_risk_sessions": high_risk,
        }

    def check_rate_limit(self, key: str, max_requests: int, window_seconds: int) -> Tuple[bool, int]:
        return self.rate_limiter.check(key, max_requests, window_seconds)

    def record_failed_invite_attempt(self, telegram_id: int) -> None:
        self.rate_limiter.record_hit(f"invite_fail:{telegram_id}")

    def check_invite_bruteforce(self, telegram_id: int) -> Tuple[bool, int]:
        allowed, retry_after = self.rate_limiter.peek(f"invite_fail:{telegram_id}", max_requests=5, window_seconds=3600)
        return (not allowed), retry_after

    def reset_invite_bruteforce(self, telegram_id: int) -> None:
        self.rate_limiter.reset(f"invite_fail:{telegram_id}")

    def cleanup_rate_limits(self, max_age_seconds: int = 3600) -> int:
        now = datetime.now(timezone.utc)
        purged = 0
        keys_to_delete = []
        for k, v in self.rate_limiter._history.items():
            first_ts = v[0] if v else 0
            if (now.timestamp() - first_ts) > max_age_seconds:
                keys_to_delete.append(k)
        for k in keys_to_delete:
            del self.rate_limiter._history[k]
            purged += 1
        return purged

    def cleanup_expired_invites(self, ttl_hours: int = 48) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=ttl_hours)
        purged = 0
        to_delete = []
        for c_id, c in self.couples.items():
            if c.get("partner_2_id") is None:
                c_created = datetime.fromisoformat(c["created_at"])
                if c_created.tzinfo is None:
                    c_created = c_created.replace(tzinfo=timezone.utc)
                if c_created <= cutoff:
                    to_delete.append(c_id)
        for c_id in to_delete:
            del self.couples[c_id]
            purged += 1
        return purged

    def cleanup_expired_payments(self, retention_years: int) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(days=365 * retention_years)
        purged = 0
        to_delete = []
        for p_id, p in self.payments.items():
            p_created = datetime.fromisoformat(p["created_at"])
            if p_created.tzinfo is None:
                p_created = p_created.replace(tzinfo=timezone.utc)
            if p_created <= cutoff:
                to_delete.append(p_id)
        for p_id in to_delete:
            del self.payments[p_id]
            purged += 1
        return purged

    def try_advisory_lock(self, lock_id: int) -> bool:
        if not hasattr(self, "_advisory_locks"):
            self._advisory_locks = set()
        if lock_id in self._advisory_locks:
            return False
        self._advisory_locks.add(lock_id)
        return True

    def release_advisory_lock(self, lock_id: int) -> bool:
        if hasattr(self, "_advisory_locks") and lock_id in self._advisory_locks:
            self._advisory_locks.remove(lock_id)
            return True
        return False

