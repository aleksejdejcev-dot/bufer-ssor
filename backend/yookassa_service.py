"""
backend/yookassa_service.py
Интеграция с платежным шлюзом ЮKassa (YooKassa API v3) через httpx.
Поддерживает создание платежей и прямую проверку статуса (для безопасной валидации вебхуков).
"""

import uuid
import logging
from decimal import Decimal
from typing import Dict, Any, Optional
import httpx
from config import settings

logger = logging.getLogger(__name__)

YOOKASSA_API_BASE = "https://api.yookassa.ru/v3"

PLANS: Dict[str, Dict[str, Any]] = {
    "month_sub": {
        "title": "Подписка «Буфер Ссор» (1 месяц)",
        "amount": Decimal("199.00"),
        "currency": "RUB",
        "days": 30,
    }
}


def get_plan(plan_name: str) -> Dict[str, Any]:
    if plan_name not in PLANS:
        raise ValueError(f"Неизвестный тариф: {plan_name}")
    return PLANS[plan_name]


async def create_yookassa_payment(
    amount: Decimal,
    currency: str = "RUB",
    return_url: Optional[str] = None,
    description: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    idempotence_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Создает платеж в ЮKassa через POST /v3/payments с Idempotence-Key.
    Возвращает словарь ответа ЮKassa (id, status, confirmation_url и т.д.).
    """
    shop_id = (settings.YOOKASSA_SHOP_ID or "").strip()
    secret_key = (settings.YOOKASSA_SECRET_KEY or "").strip()

    if not shop_id or not secret_key:
        raise RuntimeError("YOOKASSA_SHOP_ID и YOOKASSA_SECRET_KEY не настроены")

    idem_key = idempotence_key or str(uuid.uuid4())
    actual_return_url = return_url or settings.YOOKASSA_RETURN_URL or settings.MINIAPP_URL

    payload = {
        "amount": {
            "value": f"{amount:.2f}",
            "currency": currency,
        },
        "capture": True,
        "confirmation": {
            "type": "redirect",
            "return_url": actual_return_url,
        },
        "description": description or "Оплата подписки «Буфер Ссор»",
        "metadata": metadata or {},
    }

    headers = {
        "Idempotence-Key": idem_key,
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f"{YOOKASSA_API_BASE}/payments",
            json=payload,
            headers=headers,
            auth=(shop_id, secret_key),
        )
        if resp.status_code not in (200, 201):
            logger.error("Ошибка создания платежа в ЮKassa: status=%s", resp.status_code)
            raise RuntimeError(f"ЮKassa API error ({resp.status_code})")

        return resp.json()


async def get_yookassa_payment(payment_id: str) -> Dict[str, Any]:
    """
    Получает информацию о платеже напрямую из ЮKassa через GET /v3/payments/{id}.
    Используется для проверки подлинности входящих вебхуков.
    """
    shop_id = (settings.YOOKASSA_SHOP_ID or "").strip()
    secret_key = (settings.YOOKASSA_SECRET_KEY or "").strip()

    if not shop_id or not secret_key:
        raise RuntimeError("YOOKASSA_SHOP_ID и YOOKASSA_SECRET_KEY не настроены")

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{YOOKASSA_API_BASE}/payments/{payment_id}",
            auth=(shop_id, secret_key),
        )
        if resp.status_code != 200:
            logger.error("Ошибка проверки платежа %s в ЮKassa: status=%s", payment_id, resp.status_code)
            raise RuntimeError(f"ЮKassa API error ({resp.status_code})")

        return resp.json()


async def get_yookassa_refund(refund_id: str) -> Dict[str, Any]:
    """
    Получает информацию о возврате напрямую из ЮKassa через GET /v3/refunds/{id}.
    Используется для проверки подлинности входящих вебхуков возврата.
    """
    shop_id = (settings.YOOKASSA_SHOP_ID or "").strip()
    secret_key = (settings.YOOKASSA_SECRET_KEY or "").strip()

    if not shop_id or not secret_key:
        raise RuntimeError("YOOKASSA_SHOP_ID и YOOKASSA_SECRET_KEY не настроены")

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{YOOKASSA_API_BASE}/refunds/{refund_id}",
            auth=(shop_id, secret_key),
        )
        if resp.status_code != 200:
            logger.error("Ошибка проверки возврата %s в ЮKassa: status=%s", refund_id, resp.status_code)
            raise RuntimeError(f"ЮKassa API error ({resp.status_code})")

        return resp.json()
