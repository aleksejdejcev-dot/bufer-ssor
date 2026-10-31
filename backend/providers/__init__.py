"""
Фабрика LLM-провайдеров (Этап 3.5).
Предоставляет функцию get_provider(...) для прозрачного переключения
между Google Gemini и Сбер GigaChat с поддержкой per-role моделей.
"""

from typing import Optional
from config.settings import settings
from providers.base import LLMProvider
from providers.gemini import GeminiProvider
from providers.gigachat import GigaChatProvider


def get_model_for_role(provider_name: str, role: Optional[str] = None) -> str:
    """Определяет модель для конкретной роли (analyzer, card, shared, checker)."""
    p_name = (provider_name or settings.LLM_PROVIDER).lower()

    if role == "analyzer" and settings.ANALYZER_MODEL:
        return settings.ANALYZER_MODEL
    if role in ["card", "card_writer"] and settings.CARD_MODEL:
        return settings.CARD_MODEL
    if role in ["shared", "shared_writer"] and settings.SHARED_MODEL:
        return settings.SHARED_MODEL
    if role in ["checker", "leak_checker"] and settings.CHECKER_MODEL:
        return settings.CHECKER_MODEL

    if p_name == "gigachat":
        return settings.GIGACHAT_MODEL
    return settings.GEMINI_MODEL


def get_provider(
    role: Optional[str] = None,
    provider_name: Optional[str] = None,
    model: Optional[str] = None,
) -> LLMProvider:
    """
    Фабрика провайдера.
    Выбирает провайдера по env LLM_PROVIDER (gigachat | gemini) или явному параметру.
    """
    p_name = (provider_name or settings.LLM_PROVIDER).lower()
    target_model = model or get_model_for_role(p_name, role)

    if p_name == "gigachat":
        return GigaChatProvider(default_model=target_model)
    elif p_name == "gemini":
        return GeminiProvider(default_model=target_model)
    else:
        raise ValueError(f"Неизвестный LLM_PROVIDER: '{p_name}'. Допустимы: 'gigachat', 'gemini'.")
