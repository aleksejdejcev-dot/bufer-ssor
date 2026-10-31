"""
Боевая реализация интерфейса Repository на основе Supabase / PostgREST.
"""

from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List, Tuple
import logging
from supabase import create_client, Client
from config import settings
from rate_limiter import RateLimiter, normalize_invite_code

logger = logging.getLogger(__name__)


def _bytes_to_bytea_hex(data: bytes) -> str:
    """Форматирует байты в шестнадцатеричную строку PostgreSQL bytea: \\xdeadbeef"""
    return "\\x" + data.hex()


def _bytea_hex_to_bytes(val: Any) -> bytes:
    """Преобразует строку bytea из PostgreSQL обратно в объект bytes"""
    if isinstance(val, bytes):
        return val
    if isinstance(val, str):
        if val.startswith("\\x"):
            val = val[2:]
        return bytes.fromhex(val)
    return b""


class SupabaseRepo:
    def __init__(self):
        self._client: Optional[Client] = None
        self.rate_limiter = RateLimiter()

    @property
    def client(self) -> Client:
        if self._client is None:
            if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_KEY:
                raise RuntimeError("Supabase client is not configured: missing SUPABASE_URL / SUPABASE_SERVICE_KEY")
            self._client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)
        return self._client

    def reset_state(self) -> None:
        # В боевой базе не очищаем
        pass

    def get_user(self, telegram_id: int) -> Optional[Dict[str, Any]]:
        res = self.client.table("users").select("*").eq("telegram_id", telegram_id).execute()
        return res.data[0] if res.data else None

    def upsert_user(self, telegram_id: int, first_name: str, username: Optional[str] = None) -> Dict[str, Any]:
        data = {"telegram_id": telegram_id, "first_name": first_name}
        if username:
            data["username"] = username
        res = self.client.table("users").upsert(data, on_conflict="telegram_id").execute()
        return res.data[0]

    def accept_legal(self, telegram_id: int) -> Dict[str, Any]:
        now_iso = datetime.now(timezone.utc).isoformat()
        res = (
            self.client.table("users")
            .update({"accepted_legal_at": now_iso})
            .eq("telegram_id", telegram_id)
            .execute()
        )
        return res.data[0] if res.data else {"telegram_id": telegram_id, "accepted_legal_at": now_iso}

    def get_couple_by_id(self, couple_id: str) -> Optional[Dict[str, Any]]:
        res = self.client.table("couples").select("*").eq("id", couple_id).execute()
        return res.data[0] if res.data else None

    def get_couple_by_invite(self, invite_code: str) -> Optional[Dict[str, Any]]:
        res = self.client.table("couples").select("*").eq("invite_code", invite_code).execute()
        return res.data[0] if res.data else None

    def get_user_couple(self, telegram_id: int) -> Optional[Dict[str, Any]]:
        u = self.get_user(telegram_id)
        if u and u.get("couple_id"):
            return self.get_couple_by_id(u["couple_id"])
        res1 = self.client.table("couples").select("*").eq("partner_1_id", telegram_id).execute()
        if res1.data:
            return res1.data[0]
        res2 = self.client.table("couples").select("*").eq("partner_2_id", telegram_id).execute()
        if res2.data:
            return res2.data[0]
        return None

    def create_couple(self, partner_1_id: int, invite_code: str) -> Dict[str, Any]:
        couple_data = {
            "partner_1_id": partner_1_id,
            "invite_code": invite_code,
            "free_sessions_left": 3,
        }
        res = self.client.table("couples").insert(couple_data).execute()
        couple = res.data[0]
        self.client.table("users").update({"couple_id": couple["id"]}).eq("telegram_id", partner_1_id).execute()
        return couple

    def join_couple(self, couple_id: str, partner_2_id: int) -> Dict[str, Any]:
        res = (
            self.client.table("couples")
            .update({"partner_2_id": partner_2_id})
            .eq("id", couple_id)
            .execute()
        )
        couple = res.data[0]
        self.client.table("users").update({"couple_id": couple_id}).eq("telegram_id", partner_2_id).execute()
        return couple

    def update_mood(self, couple_id: str, is_partner_1: bool, mood: int) -> Dict[str, Any]:
        now_iso = datetime.now(timezone.utc).isoformat()
        payload = (
            {"mood_p1": mood, "mood_updated_at_p1": now_iso}
            if is_partner_1
            else {"mood_p2": mood, "mood_updated_at_p2": now_iso}
        )
        res = self.client.table("couples").update(payload).eq("id", couple_id).execute()
        return res.data[0]

    def decrement_free_sessions(self, couple_id: str) -> None:
        c = self.get_couple_by_id(couple_id)
        if c and c.get("free_sessions_left", 0) > 0:
            new_val = c["free_sessions_left"] - 1
            self.client.table("couples").update({"free_sessions_left": new_val}).eq("id", couple_id).execute()

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
        c = self.get_couple_by_id(couple_id)
        if c:
            new_val = c.get("free_sessions_left", 0) + count
            res = self.client.table("couples").update({"free_sessions_left": new_val}).eq("id", couple_id).execute()
            return res.data[0]
        return {}

    def get_active_session(self, couple_id: str) -> Optional[Dict[str, Any]]:
        res = (
            self.client.table("conflict_sessions")
            .select("*")
            .eq("couple_id", couple_id)
            .in_("status", ["waiting_partner_2", "analyzing"])
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        return res.data[0] if res.data else None

    def get_session_by_id(self, session_id: str) -> Optional[Dict[str, Any]]:
        res = self.client.table("conflict_sessions").select("*").eq("id", session_id).execute()
        return res.data[0] if res.data else None

    def create_conflict_session(self, couple_id: str, initiator_id: int) -> Dict[str, Any]:
        session_data = {
            "couple_id": couple_id,
            "initiator_id": initiator_id,
            "status": "waiting_partner_2",
            "risk_level": "none",
        }
        res = self.client.table("conflict_sessions").insert(session_data).execute()
        return res.data[0]

    def update_session_status(
        self,
        session_id: str,
        status: str,
        completed_at: Optional[str] = None,
        risk_level: Optional[str] = None,
    ) -> None:
        payload: Dict[str, Any] = {"status": status}
        if completed_at:
            payload["completed_at"] = completed_at
        if risk_level:
            payload["risk_level"] = risk_level
        self.client.table("conflict_sessions").update(payload).eq("id", session_id).execute()

    def save_analysis_results(
        self,
        session_id: str,
        results: Dict[str, Any],
        risk_level: str,
        completed_at: str,
    ) -> None:
        payload = {
            "ai_advice_p1": results.get("partner_1_response") or results.get("partner_1_card") or results.get("ai_advice_p1"),
            "ai_advice_p2": results.get("partner_2_response") or results.get("partner_2_card") or results.get("ai_advice_p2"),
            "shared_summary": results.get("shared_summary"),
            "risk_level": risk_level,
            "status": "completed",
            "completed_at": completed_at,
        }
        self.client.table("conflict_sessions").update(payload).eq("id", session_id).execute()
        self.delete_pending_inputs_for_session(session_id)

    def get_expired_sessions(self) -> List[Dict[str, Any]]:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=settings.EXPIRATION_HOURS)).isoformat()
        res = (
            self.client.table("conflict_sessions")
            .select("*")
            .eq("status", "waiting_partner_2")
            .lte("created_at", cutoff)
            .execute()
        )
        return res.data or []

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
        data = {
            "session_id": session_id,
            "author_telegram_id": author_telegram_id,
            "kind": kind,
            "payload_encrypted": _bytes_to_bytea_hex(payload_encrypted),
        }
        res = self.client.table("pending_inputs").insert(data).execute()
        item = res.data[0]
        item["payload_encrypted"] = payload_encrypted
        return item

    def has_user_submitted_input(self, session_id: str, author_telegram_id: int) -> bool:
        res = (
            self.client.table("pending_inputs")
            .select("id")
            .eq("session_id", session_id)
            .eq("author_telegram_id", author_telegram_id)
            .execute()
        )
        return bool(res.data)

    def count_pending_inputs(self, session_id: str) -> int:
        res = (
            self.client.table("pending_inputs")
            .select("id", count="exact")
            .eq("session_id", session_id)
            .execute()
        )
        return res.count or len(res.data or [])

    def get_pending_inputs(self, session_id: str) -> List[Dict[str, Any]]:
        res = (
            self.client.table("pending_inputs")
            .select("*")
            .eq("session_id", session_id)
            .order("created_at")
            .execute()
        )
        out = []
        for r in (res.data or []):
            item = dict(r)
            if "payload_encrypted" in item and item["payload_encrypted"] is not None:
                item["payload_encrypted"] = _bytea_hex_to_bytes(item["payload_encrypted"])
            out.append(item)
        return out

    def delete_pending_input_for_author(self, session_id: str, author_telegram_id: int) -> None:
        (
            self.client.table("pending_inputs")
            .delete()
            .eq("session_id", session_id)
            .eq("author_telegram_id", author_telegram_id)
            .execute()
        )

    def delete_pending_inputs_for_session(self, session_id: str) -> None:
        self.client.table("pending_inputs").delete().eq("session_id", session_id).execute()

    def cleanup_expired_pending_inputs(self) -> int:
        res = self.client.rpc("cleanup_expired_pending_inputs").execute()
        return res.data or 0

    def delete_history(self, couple_id: str) -> None:
        """Удаляет только сессии и историю ссоры пары, профили и подписка остаются."""
        # 1. Находим сессии
        sessions = self.client.table("conflict_sessions").select("id").eq("couple_id", couple_id).execute()
        s_ids = [s["id"] for s in (sessions.data or [])]
        for sid in s_ids:
            self.delete_pending_inputs_for_session(sid)
        if s_ids:
            self.client.table("conflict_sessions").delete().eq("couple_id", couple_id).execute()
        # Сброс настроения
        self.client.table("couples").update({
            "mood_p1": None,
            "mood_p2": None,
            "mood_updated_at_p1": None,
            "mood_updated_at_p2": None,
        }).eq("id", couple_id).execute()

    def purge_expired_data(self, days_retention: int = 30, hours_raw_ttl: int = 48) -> Dict[str, int]:
        try:
            res = self.client.rpc("purge_expired_data", {
                "days_retention": days_retention,
                "hours_raw_ttl": hours_raw_ttl,
            }).execute()
            if res.data and isinstance(res.data, dict):
                return {
                    "purged_sessions": int(res.data.get("purged_sessions", 0)),
                    "purged_inputs": int(res.data.get("purged_inputs", 0)),
                }
        except Exception:
            pass

        now = datetime.now(timezone.utc)
        sess_cutoff = (now - timedelta(days=days_retention)).isoformat()
        inp_cutoff = (now - timedelta(hours=hours_raw_ttl)).isoformat()

        purged_sessions = 0
        try:
            upd = self.client.table("conflict_sessions").update({
                "ai_advice_p1": None,
                "ai_advice_p2": None,
                "shared_summary": None,
                "status": "purged_by_retention",
            }).eq("status", "completed").lte("completed_at", sess_cutoff).execute()
            purged_sessions = len(upd.data or [])
        except Exception:
            pass

        purged_inputs = 0
        try:
            inp = self.client.table("pending_inputs").delete().lte("created_at", inp_cutoff).execute()
            purged_inputs = len(inp.data or [])
        except Exception:
            pass

        return {"purged_sessions": purged_sessions, "purged_inputs": purged_inputs}

    def delete_couple_data(self, couple_id: str) -> None:
        """Полное удаление пары, истории и обоих профилей в users."""
        couple = self.get_couple_by_id(couple_id)
        p1_id = couple.get("partner_1_id") if couple else None
        p2_id = couple.get("partner_2_id") if couple else None

        # Сброс payments.couple_id = NULL
        try:
            self.client.table("payments").update({"couple_id": None}).eq("couple_id", couple_id).execute()
        except Exception:
            pass

        # Вызов хранимой функции удаления пары (или каскад)
        try:
            self.client.rpc("delete_couple_data", {"target_couple_id": couple_id}).execute()
        except Exception:
            self.delete_history(couple_id)
            self.client.table("couples").delete().eq("id", couple_id).execute()

        # Удаление профилей пользователей
        if p1_id:
            self.client.table("users").delete().eq("telegram_id", p1_id).execute()
        if p2_id:
            self.client.table("users").delete().eq("telegram_id", p2_id).execute()

    def save_payment(
        self,
        product: str,
        amount: int,
        currency: str,
        provider_charge_id: str,
        payer_hash: str,
        couple_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload = {
            "product": product,
            "amount": amount,
            "currency": currency,
            "provider_charge_id": provider_charge_id,
            "payer_hash": payer_hash,
            "couple_id": couple_id,
        }
        res = self.client.table("payments").insert(payload).execute()
        return res.data[0] if res.data else payload

    def get_payments_by_payer_hash(self, payer_hash: str) -> List[Dict[str, Any]]:
        res = self.client.table("payments").select("*").eq("payer_hash", payer_hash).execute()
        return res.data or []

    def get_all_couples(self) -> List[Dict[str, Any]]:
        res = self.client.table("couples").select("*").execute()
        return res.data or []

    def get_admin_stats(self) -> Dict[str, Any]:
        u = self.client.table("users").select("id", count="exact").execute()
        c = self.client.table("couples").select("id", count="exact").execute()
        s = self.client.table("conflict_sessions").select("id", count="exact").execute()
        return {
            "total_users": u.count or len(u.data or []),
            "total_couples": c.count or len(c.data or []),
            "total_sessions": s.count or len(s.data or []),
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
