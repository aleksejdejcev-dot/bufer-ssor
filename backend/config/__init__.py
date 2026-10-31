"""
Пакет конфигурации приложения «Буфер Ссор».
"""

from config.settings import settings, Settings
from config.hotlines import get_hotlines_text, HOTLINES
from config.safety_messages import HIGH_RISK_BASE_MESSAGE, get_high_risk_message
from config.fallbacks import (
    FALLBACK_PARTNER_PERSPECTIVE,
    FALLBACK_BLIND_SPOT,
    FALLBACK_ACTION_SCRIPTS,
    FALLBACK_VALIDATION,
    FALLBACK_SHARED_SUMMARY,
    get_fallback_field,
)

__all__ = [
    "settings",
    "Settings",
    "get_hotlines_text",
    "HOTLINES",
    "HIGH_RISK_BASE_MESSAGE",
    "get_high_risk_message",
    "FALLBACK_PARTNER_PERSPECTIVE",
    "FALLBACK_BLIND_SPOT",
    "FALLBACK_ACTION_SCRIPTS",
    "FALLBACK_VALIDATION",
    "FALLBACK_SHARED_SUMMARY",
    "get_fallback_field",
]
