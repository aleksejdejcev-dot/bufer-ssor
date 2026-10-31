"""
InMemory реализация интерфейса Repository для локальных тестов и работы без сети.
"""

import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List, Tuple
from config import settings
from rate_limiter import RateLimiter, normalize_invite_code


class InMemoryRepo:
    def __init__(self):
        self.users: Dict[int, Dict[str, Any]] = {}
        self.couples: Dict[str, Dict[str, Any]] = {}
        self.conflict_sessions: Dict[str, Dict[str, Any]] = {}
        self.pending_inputs: Dict[str, Dict[str, Any]] = {}
        self.payments: Dict[str, Dict[str, Any]] = {}
        self.rate_limiter = RateLimiter()

    def reset_state(self) -> None:
        self.users.clear()
        self.couples.clear()
        self.conflict_sessions.clear()
        self.pending_inputs.clear()
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
            "free_sessions_left": 3,
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
        if c:
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
        item = {
            "id": p_id,
            "session_id": session_id,
            "author_telegram_id": author_telegram_id,
            "kind": kind,
            "payload_encrypted": payload_encrypted,
            "created_at": datetime.now(timezone.utc).isoformat(),
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
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=settings.RAW_INPUT_TTL_HOURS)).isoformat()
        to_del = [
            pid for pid, p in self.pending_inputs.items()
            if p.get("created_at", "") <= cutoff
        ]
        for pid in to_del:
            del self.pending_inputs[pid]
        return len(to_del)

    def delete_history(self, couple_id: str) -> None:
        """Удаляет только сессии и историю пары, профили и подписка остаются."""
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

    def delete_couple_data(self, couple_id: str) -> None:
        """Полное удаление пары, истории и обоих профилей в users."""
        couple = self.couples.get(couple_id)
        p1_id = couple.get("partner_1_id") if couple else None
        p2_id = couple.get("partner_2_id") if couple else None

        # 1. Удаляем историю сессий и исходников
        self.delete_history(couple_id)

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
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self.payments[pay_id] = item
        return item

    def get_payments_by_payer_hash(self, payer_hash: str) -> List[Dict[str, Any]]:
        return [p for p in self.payments.values() if p.get("payer_hash") == payer_hash]

    def get_all_couples(self) -> List[Dict[str, Any]]:
        return list(self.couples.values())

    def get_admin_stats(self) -> Dict[str, Any]:
        return {
            "total_users": len(self.users),
            "total_couples": len(self.couples),
            "total_sessions": len(self.conflict_sessions),
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
