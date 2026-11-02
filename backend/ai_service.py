"""
Модуль ИИ-медиатора «Буфер Ссор» (Этап 3.5: заменяемый слой провайдеров Gemini / GigaChat).
Архитектура пайплайна:
1. Шаг A: Анализатор версий (prompts/analyzer.txt, temperature 0.3).
   - Оценка risk_level. При high или blocked — блокировка генерации текстов, выдача фиксированного
     сообщения безопасности и номеров горячих линий. При elevated — фиксированный safety_note.
2. Шаги B1/B2: Автор персональных карточек (prompts/card_writer.txt, temperature 0.8).
   - Вход строго изолирован: собственная версия, собственный анализ и абстрактные гипотезы партнера.
   - Лестница фоллбэков: (а) до 2 перегенераций (1 при blocked), (б) безопасный режим, (в) статический текст по полям.
3. Шаг C: Автор общего итога (prompts/shared_writer.txt, temperature 0.7).
   - Вход строго абстрактный (shared block), без сырых версий. Запрет на слово 'чай' и роли.
4. Шаг D: Проверка утечек конфиденциальности (prompts/leak_checker.txt, temperature 0.0).
   - Сравнение с обеими версиями и списками secrets.
5. Финальный прогон валидатора перед сохранением в БД: проверяет чистоту данных без пустых полей и служебных строк.
"""

import os
import gc
import json
import logging
import asyncio
import hashlib
import re
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple, Union

from config import settings
from config.hotlines import get_hotlines_text
from config.safety_messages import get_high_risk_message, get_elevated_risk_message
from config.fallbacks import (
    get_random_fallback,
    SPARSE_SHORTNESS_PREFIXES,
    NOT_APPLICABLE_CARD,
    NOT_APPLICABLE_SHARED,
)
import crypto
from repo import get_repo
from leak_guard import (
    check_card_lemma_leaks,
    check_shared_lemma_leaks,
    sanitize_hypothesis_for_other,
    sanitize_agreed_ritual,
)
from schemas import (
    AnalyzerOutput,
    PartnerAnalysis,
    HypothesisForOther,
    SharedAnalysis,
    AgreedRitual,
    PartnerResponse,
    SharedSummary,
    ActionScriptItem,
    MediatorOutput,
    LeakCheckOutput,
    ToneAnalysis,
    get_flat_json_schema,
)
from validators import (
    validate_partner_card,
    validate_shared_summary,
    validate_full_mediator_output,
    validate_ritual_consistency,
    extract_durations,
    align_action_scripts_with_ritual,
    sanitize_minor_banned_words,
    sanitize_card_minor_banned_words,
    sanitize_shared_minor_banned_words,
)
from providers import get_provider, get_model_for_role
from providers.base import LLMProvider
from providers.gemini import GeminiProvider

logger = logging.getLogger("ai_service")

# Пути к текстовым файлам системных инструкций (промптов)
PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


def get_prompt_text(role: str) -> str:
    """Загружает текст промпта с учетом режима GIGACHAT_PROMPT_MODE (standard / compact)."""
    mode = getattr(settings, "GIGACHAT_PROMPT_MODE", "standard") or os.environ.get("GIGACHAT_PROMPT_MODE", "standard")
    if mode == "compact":
        compact_path = PROMPTS_DIR / "compact" / f"{role}.txt"
        if compact_path.exists():
            return compact_path.read_text(encoding="utf-8").strip()

    standard_path = PROMPTS_DIR / f"{role}.txt"
    if standard_path.exists():
        return standard_path.read_text(encoding="utf-8").strip()

    logger.critical("Не найден файл промпта для роли %s в %s", role, PROMPTS_DIR)
    return ""


def _resolve_provider(
    provider_or_client: Optional[Union[LLMProvider, Any]] = None,
    role: Optional[str] = None,
    model: Optional[str] = None,
) -> LLMProvider:
    """Универсальный резолвер: преобразует старый genai.Client или None в LLMProvider."""
    if isinstance(provider_or_client, LLMProvider):
        return provider_or_client

    # Если передан сторонний клиент или None — получаем провайдера из настроек
    return get_provider(role=role, model=model)


def _build_partner_content_parts(kind: str, raw_payload: bytes, label: str) -> List[Any]:
    """Формирует части контента для партнера (текст или нативное аудио при поддержке)."""
    parts: List[Any] = []
    open_tag = f"<{label}>\n"
    close_tag = f"\n</{label}>"

    parts.append(open_tag)
    if kind == "text":
        text_content = raw_payload.decode("utf-8", errors="replace").strip()
        parts.append(text_content)
    elif kind == "audio":
        try:
            from google.genai import types
            audio_part = types.Part.from_bytes(
                data=raw_payload,
                mime_type="audio/ogg",
            )
            parts.append(audio_part)
        except Exception:
            parts.append("[Аудиозапись партнера]")
    parts.append(close_tag)
    return parts


def prepare_analyzer_contents(
    p1_kind: str,
    p1_bytes: bytes,
    p2_kind: str,
    p2_bytes: bytes,
) -> List[Any]:
    """Собирает контекст для Шага A (Анализатор)."""
    contents: List[Any] = []
    contents.extend(_build_partner_content_parts(p1_kind, p1_bytes, "version_partner_1"))
    contents.append("\n\n")
    contents.extend(_build_partner_content_parts(p2_kind, p2_bytes, "version_partner_2"))
    return contents


def prepare_card_writer_contents(
    my_kind: str,
    my_bytes: bytes,
    my_analysis: PartnerAnalysis,
    partner_hypothesis: HypothesisForOther,
    agreed_ritual: Optional[AgreedRitual] = None,
    risk_elevated: bool = False,
    sparse: bool = False,
    guidance: Optional[str] = None,
) -> List[Any]:
    """Собирает строго изолированный контекст для Шага B1/B2 (Автор карточки)."""
    contents: List[Any] = []
    contents.extend(_build_partner_content_parts(my_kind, my_bytes, "my_version"))

    analysis_dict = {
        "topic": my_analysis.topic,
        "key_facts": my_analysis.key_facts,
        "feelings": my_analysis.feelings,
        "unmet_needs": my_analysis.unmet_needs,
        "own_contribution": my_analysis.own_contribution,
        "tone": my_analysis.tone.model_dump(),
        "sparse": my_analysis.sparse,
    }
    contents.append(f"\n\n<my_analysis>\n{json.dumps(analysis_dict, ensure_ascii=False, indent=2)}\n</my_analysis>")

    hypo_dict = partner_hypothesis.model_dump()
    contents.append(f"\n\n<partner_hypothesis>\n{json.dumps(hypo_dict, ensure_ascii=False, indent=2)}\n</partner_hypothesis>")

    if agreed_ritual:
        contents.append(f"\n\n<agreed_ritual>\n{agreed_ritual.model_dump_json(indent=2)}\n</agreed_ritual>")

    if risk_elevated:
        contents.append("\n\n<risk_elevated>true</risk_elevated>")

    if sparse or my_analysis.sparse:
        contents.append("\n\n<sparse>true</sparse>")

    if guidance:
        contents.append(f"\n\n<guidance>\n{guidance}\n</guidance>")

    return contents


def prepare_shared_writer_contents(
    shared_analysis: SharedAnalysis,
    guidance: Optional[str] = None,
) -> List[Any]:
    """Собирает обезличенный контекст для Шага C (Автор общего итога)."""
    contents: List[Any] = []
    shared_dict = shared_analysis.model_dump()
    contents.append(f"<shared_analysis>\n{json.dumps(shared_dict, ensure_ascii=False, indent=2)}\n</shared_analysis>")
    if guidance:
        contents.append(f"\n\n<guidance>\n{guidance}\n</guidance>")
    return contents


def prepare_leak_checker_contents(
    p1_kind: str,
    p1_bytes: bytes,
    p2_kind: str,
    p2_bytes: bytes,
    secrets_p1: List[str],
    secrets_p2: List[str],
    generated_analysis: MediatorOutput,
) -> List[Any]:
    """Собирает контекст для Шага D (Проверка утечек со списками secrets)."""
    contents: List[Any] = []
    contents.extend(_build_partner_content_parts(p1_kind, p1_bytes, "version_partner_1"))
    contents.append("\n\n")
    contents.extend(_build_partner_content_parts(p2_kind, p2_bytes, "version_partner_2"))
    contents.append(f"\n\n<secrets_partner_1>\n{json.dumps(secrets_p1, ensure_ascii=False, indent=2)}\n</secrets_partner_1>")
    contents.append(f"\n\n<secrets_partner_2>\n{json.dumps(secrets_p2, ensure_ascii=False, indent=2)}\n</secrets_partner_2>")

    analysis_json = generated_analysis.model_dump_json(indent=2)
    contents.append(f"\n\n<generated_analysis>\n{analysis_json}\n</generated_analysis>")
    return contents


def make_blocked_analyzer_output(reason: str = "provider_refusal") -> AnalyzerOutput:
    """Формирует безопасный объект AnalyzerOutput при блокировке или отказе провайдера."""
    dummy_tone = ToneAnalysis(register="formal", swearing=False, length="short")
    dummy_hypo = HypothesisForOther(
        likely_feelings=["тревога", "напряжение"],
        likely_needs=["безопасность", "поддержка"],
    )
    dummy_partner = PartnerAnalysis(
        topic="Ситуация требует обращения к специалистам",
        key_facts=[],
        feelings=["тревога"],
        unmet_needs=["безопасность"],
        own_contribution="",
        tone=dummy_tone,
        secrets=[],
        hypothesis_for_other=dummy_hypo,
        sparse=False,
    )
    dummy_shared = SharedAnalysis(
        pattern="Защитная блокировка безопасности",
        common_need="безопасность",
        neutral_topic=None,
        ritual_ideas=[],
        agreed_ritual=None,
    )
    return AnalyzerOutput(
        risk_level="high",
        risk_reasons=[reason],
        partner_1=dummy_partner,
        partner_2=dummy_partner,
        shared=dummy_shared,
        not_applicable=False,
        provider_refusal=True,
    )


# ==============================================================================
# Вызовы модели через LLMProvider
# ==============================================================================

async def call_analyzer(
    provider_or_client: Optional[Union[LLMProvider, Any]] = None,
    contents: Union[str, List[Any]] = None,
    model: Optional[str] = None,
    tracker: Optional[Dict[str, Any]] = None,
) -> AnalyzerOutput:
    """Шаг A: Анализатор версий партнеров (temperature 0.3)."""
    p = _resolve_provider(provider_or_client, role="analyzer", model=model)
    system_prompt = get_prompt_text("analyzer")
    schema = get_flat_json_schema(AnalyzerOutput)

    parsed, meta = await p.generate_json(
        system_prompt=system_prompt,
        user_content=contents or [],
        json_schema=schema,
        pydantic_model=AnalyzerOutput,
        temperature=settings.ANALYZER_TEMPERATURE,
        model=model,
        tag="analyzer",
    )

    if tracker is not None:
        tracker["total_tokens"] = tracker.get("total_tokens", 0) + meta.get("usage_tokens", 0)
        tracker["prompt_tokens"] = tracker.get("prompt_tokens", 0) + meta.get("prompt_tokens", 0)
        tracker["completion_tokens"] = tracker.get("completion_tokens", 0) + meta.get("completion_tokens", 0)
        tracker["calls"] = tracker.get("calls", 0) + 1
        if meta.get("blocked"):
            tracker["blocked_calls"] = tracker.get("blocked_calls", 0) + 1

    if meta.get("blocked") or parsed is None:
        refusal_reason = meta.get("error") or "provider_refusal"
        logger.warning("[analyzer] Blocked or refused by provider (%s): treating as high risk", refusal_reason)
        return make_blocked_analyzer_output(reason=refusal_reason)

    return parsed


async def call_card_writer(
    provider_or_client: Optional[Union[LLMProvider, Any]] = None,
    contents: Union[str, List[Any]] = None,
    model: Optional[str] = None,
    tracker: Optional[Dict[str, Any]] = None,
) -> Tuple[Optional[PartnerResponse], Dict[str, Any]]:
    """Шаг B1/B2: Генерация персональной карточки (temperature 0.8)."""
    p = _resolve_provider(provider_or_client, role="card_writer", model=model)
    system_prompt = get_prompt_text("card_writer")
    schema = get_flat_json_schema(PartnerResponse)

    parsed, meta = await p.generate_json(
        system_prompt=system_prompt,
        user_content=contents or [],
        json_schema=schema,
        pydantic_model=PartnerResponse,
        temperature=settings.CARD_WRITER_TEMPERATURE,
        model=model,
        tag="card_writer",
    )

    if tracker is not None:
        tracker["total_tokens"] = tracker.get("total_tokens", 0) + meta.get("usage_tokens", 0)
        tracker["prompt_tokens"] = tracker.get("prompt_tokens", 0) + meta.get("prompt_tokens", 0)
        tracker["completion_tokens"] = tracker.get("completion_tokens", 0) + meta.get("completion_tokens", 0)
        tracker["calls"] = tracker.get("calls", 0) + 1
        if meta.get("blocked"):
            tracker["blocked_calls"] = tracker.get("blocked_calls", 0) + 1

    return parsed, meta


async def call_shared_writer(
    provider_or_client: Optional[Union[LLMProvider, Any]] = None,
    contents: Union[str, List[Any]] = None,
    model: Optional[str] = None,
    tracker: Optional[Dict[str, Any]] = None,
) -> Tuple[Optional[SharedSummary], Dict[str, Any]]:
    """Шаг C: Генерация общего итога для пары (temperature 0.7)."""
    p = _resolve_provider(provider_or_client, role="shared_writer", model=model)
    system_prompt = get_prompt_text("shared_writer")
    schema = get_flat_json_schema(SharedSummary)

    parsed, meta = await p.generate_json(
        system_prompt=system_prompt,
        user_content=contents or [],
        json_schema=schema,
        pydantic_model=SharedSummary,
        temperature=settings.SHARED_WRITER_TEMPERATURE,
        model=model,
        tag="shared_writer",
    )

    if tracker is not None:
        tracker["total_tokens"] = tracker.get("total_tokens", 0) + meta.get("usage_tokens", 0)
        tracker["prompt_tokens"] = tracker.get("prompt_tokens", 0) + meta.get("prompt_tokens", 0)
        tracker["completion_tokens"] = tracker.get("completion_tokens", 0) + meta.get("completion_tokens", 0)
        tracker["calls"] = tracker.get("calls", 0) + 1
        if meta.get("blocked"):
            tracker["blocked_calls"] = tracker.get("blocked_calls", 0) + 1

    return parsed, meta


async def call_leak_checker(
    provider_or_client: Optional[Union[LLMProvider, Any]] = None,
    contents: Union[str, List[Any]] = None,
    model: Optional[str] = None,
    tracker: Optional[Dict[str, Any]] = None,
) -> LeakCheckOutput:
    """Шаг D: Проверка утечек конфиденциальности (temperature 0.0)."""
    p = _resolve_provider(provider_or_client, role="leak_checker", model=model)
    system_prompt = get_prompt_text("leak_checker")
    schema = get_flat_json_schema(LeakCheckOutput)

    parsed, meta = await p.generate_json(
        system_prompt=system_prompt,
        user_content=contents or [],
        json_schema=schema,
        pydantic_model=LeakCheckOutput,
        temperature=settings.LEAK_CHECKER_TEMPERATURE,
        model=model,
        tag="leak_checker",
    )

    if tracker is not None:
        tracker["total_tokens"] = tracker.get("total_tokens", 0) + meta.get("usage_tokens", 0)
        tracker["prompt_tokens"] = tracker.get("prompt_tokens", 0) + meta.get("prompt_tokens", 0)
        tracker["completion_tokens"] = tracker.get("completion_tokens", 0) + meta.get("completion_tokens", 0)
        tracker["calls"] = tracker.get("calls", 0) + 1
        if meta.get("blocked"):
            tracker["blocked_calls"] = tracker.get("blocked_calls", 0) + 1

    if parsed is None or meta.get("blocked"):
        # При блокировке или ошибке чеккера считаем, что утечек нет, чтобы не ломать сессию
        return LeakCheckOutput(leak=False, location="", reason="check_skipped_or_blocked")

    return parsed


# ==============================================================================
# Лестница фоллбэков для карточек и общего итога (Этап 3.2 + 3.5)
# ==============================================================================

def format_sparse_validation(text: str, default_note: Optional[str] = None) -> str:
    """
    Приводит validation для sparse=True к стандарту Патча 3.4 (п. 6):
    Детерминированно добавляет пометку о краткости (если её там ещё нет)
    и оставляет ровно 2 предложения (первое — пометка о краткости,
    второе — ёмкая мысль из сгенерированного validation).
    """
    if not text:
        return default_note or "Ты рассказал(а) совсем коротко, поэтому скажу осторожно. Твои чувства и накопившаяся усталость от недопонимания вполне естественны."

    note = default_note or "Ты рассказал(а) совсем коротко, поэтому скажу осторожно."
    sents = [s.strip() for s in re.split(r"(?<=[.!?…])\s+", text.strip()) if s.strip()]

    starts_with_note = False
    for pfx in SPARSE_SHORTNESS_PREFIXES:
        if sents and re.search(re.escape(pfx[:25]), sents[0], flags=re.IGNORECASE):
            starts_with_note = True
            break
    if not starts_with_note:
        for pat in [
            r"ты\s+рассказал[ао]?\s+совсем\s+коротко",
            r"ты\s+описал[ао]?\s+ситуаци\w*\s+совсем\s+коротко",
            r"тво[её]\s+сообщени\w*\s+совсем\s+коротк",
            r"ты\s+поделил(?:ся|ась|ось)\s+очень\s+кратко",
            r"скажу\s+осторожно",
        ]:
            if sents and re.search(pat, sents[0], flags=re.IGNORECASE):
                starts_with_note = True
                break

    if starts_with_note:
        first_sent = sents[0]
        second_sent = sents[1] if len(sents) > 1 else "Твои чувства и накопившаяся усталость от недопонимания вполне естественны."
    else:
        first_sent = note
        second_sent = sents[0] if sents else "Твои чувства и накопившаяся усталость от недопонимания вполне естественны."

    if not re.search(r"[.!?…]$", first_sent):
        first_sent += "."
    if not re.search(r"[.!?…]$", second_sent):
        second_sent += "."

    return f"{first_sent} {second_sent}"


def build_deterministic_ritual_script(agreed_ritual: Optional[Any], shared_advice: str) -> str:
    """
    Формирует содержательный скрипт действия #2 для ритуала.
    Если ritual_phrase_we короче 25 символов или не содержит цифр/длительности из shared_advice,
    извлекает ключевое правило с длительностью из shared_advice (Этап 3.10 / 3.11).
    """
    rit_phrase = ""
    if agreed_ritual:
        rit_phrase = (getattr(agreed_ritual, "ritual_phrase_we", None) or getattr(agreed_ritual, "format", None) or "").strip()

    advice_durs = extract_durations(shared_advice)
    advice_numbers = re.findall(r"\b\d+\b", shared_advice)

    is_good_phrase = len(rit_phrase) >= 25
    if is_good_phrase and (advice_durs or advice_numbers):
        phrase_numbers = set(re.findall(r"\b\d+\b", rit_phrase))
        has_number_match = bool(phrase_numbers & (set(advice_numbers) | set(re.findall(r"\b\d+\b", " ".join(advice_durs)))))
        if not has_number_match:
            is_good_phrase = False

    if not is_good_phrase and shared_advice:
        sentences = [s.strip() for s in re.split(r"(?<=[.!?…])\s+", shared_advice) if s.strip()]
        candidate_sent = ""
        for s in sentences:
            if any(num in s for num in advice_numbers) or extract_durations(s):
                candidate_sent = s
                break
        if not candidate_sent and sentences:
            candidate_sent = sentences[0]

        if candidate_sent:
            cleaned_rule = re.sub(r"^(?:договоритесь\s+о\s+правиле:?|выберите\s+правило:?|попробуйте\s+внедрить:?)\s*", "", candidate_sent, flags=re.IGNORECASE)
            cleaned_rule = re.sub(r"^[Дд]оговоритесь\s+о\s+правиле:?\s*", "", cleaned_rule)
            cleaned_rule = cleaned_rule.rstrip(".!?…")
            if cleaned_rule:
                cleaned_rule = cleaned_rule[0].lower() + cleaned_rule[1:]
                return f"Предлагаю попробовать новое правило: {cleaned_rule}. Что скажешь?"

    if not rit_phrase or len(rit_phrase) < 25:
        rit_phrase = "делать 15-минутную паузу и обсуждать ситуацию без взаимных упрёков"

    rit_phrase = rit_phrase[0].lower() + rit_phrase[1:] if rit_phrase else rit_phrase
    return f"Предлагаю попробовать новое правило: {rit_phrase}. Что скажешь?"


def reformulate_perspective_opening(text: str) -> str:
    """
    Переформулирует зачин partner_perspective, устраняя штампы
    ('Возможно', 'Скорее всего', 'Бывает', 'Вероятно', 'Похоже')
    и обеспечивая разнообразие начал между партнёрами (Этап 3.4 / 3.9 / 3.11).
    Использует зачины БЕЗ слова «партнёр», исключая тавтологии.
    """
    if not text:
        return text
    cleaned = text.strip()

    # НЕ применять модификацию, если поле уже начинается с «У твоего партнёра»
    if re.search(r"^у\s+(?:твоего\s+)?партн[её]ра\b", cleaned, flags=re.IGNORECASE):
        return cleaned

    patterns = [
        (r"^(?:возможно|вероятно),\s*", "В таких ситуациях "),
        (r"^скорее всего,\s*", "Нередко в такие моменты "),
        (r"^бывает,\s*(?:что\s*)?", "За такой реакцией часто стоит то, что "),
        (r"^похоже,\s*", "В такой ситуации "),
        (r"^наверное,\s*", "Нередко в такие моменты "),
    ]
    for pat, repl in patterns:
        if re.search(pat, cleaned, flags=re.IGNORECASE):
            return re.sub(pat, repl, cleaned, count=1, flags=re.IGNORECASE)

    words = re.findall(r"\b\w+\b", cleaned)
    if words:
        first_w = words[0]
        return re.sub(rf"^{re.escape(first_w)}[,\s]+", f"В такой ситуации, {first_w.lower()} ", cleaned, count=1, flags=re.IGNORECASE)

    return cleaned


def diversify_partner_perspectives(p1_card: Optional[PartnerResponse], p2_card: Optional[PartnerResponse]) -> None:
    """
    Проверяет симметрию зачинов partner_perspective партнёра 1 и 2.
    Если они начинаются с одного и того же первого слова или оба начинаются со слова
    из списка смягчителей, переформулирует начало второго (Этап 3.4 / 3.9 / 3.11).
    """
    if not p1_card or not p2_card:
        return
    pp1 = (p1_card.partner_perspective or "").strip()
    pp2 = (p2_card.partner_perspective or "").strip()
    if not pp1 or not pp2:
        return

    # Если второе поле уже начинается с «У твоего партнёра», модификацию не применяем
    if re.search(r"^у\s+(?:твоего\s+)?партн[её]ра\b", pp2, flags=re.IGNORECASE):
        return

    words1 = re.findall(r"\b\w+\b", pp1.lower())
    words2 = re.findall(r"\b\w+\b", pp2.lower())
    if not words1 or not words2:
        return

    w1 = words1[0]
    w2 = words2[0]

    softeners = {"возможно", "скорее", "бывает", "вероятно", "похоже", "наверное"}
    same_start = (w1 == w2)
    both_softeners = (w1 in softeners and w2 in softeners)

    if same_start or both_softeners:
        logger.info("Diversifying partner_perspective openings: P1 starts with '%s', P2 with '%s'", w1, w2)
        new_pp2 = reformulate_perspective_opening(pp2)
        p2_card.partner_perspective = new_pp2

async def generate_partner_card_with_ladder(
    provider_or_client: Optional[Union[LLMProvider, Any]] = None,
    my_kind: str = "text",
    my_bytes: bytes = b"",
    my_analysis: Optional[PartnerAnalysis] = None,
    partner_hypothesis: Optional[HypothesisForOther] = None,
    agreed_ritual: Optional[AgreedRitual] = None,
    risk_elevated: bool = False,
    sparse: bool = False,
    has_followup: bool = False,
    partner_tag: str = "partner_1",
    fallback_records: Optional[List[Dict[str, str]]] = None,
    guidance: Optional[str] = None,
    model: Optional[str] = None,
    tracker: Optional[Dict[str, Any]] = None,
    client: Optional[Any] = None,
) -> PartnerResponse:
    """
    Генерация персональной карточки партнёра по Лестнице фоллбэков:
    (а) До 2 перегенераций с указанием ошибок (1 повтор при blocked);
    (б) Безопасный режим с пустой partner_hypothesis;
    (в) Статический текст из config/fallbacks.py строго для проблемных полей.
    """
    p = _resolve_provider(provider_or_client or client, role="card_writer", model=model)
    effective_sparse = False if has_followup else (sparse or getattr(my_analysis, "sparse", False))
    if my_analysis is None:
        my_analysis = PartnerAnalysis(
            topic="", key_facts=[], feelings=[], unmet_needs=[], own_contribution="",
            tone=ToneAnalysis(register="formal", swearing=False, length="short"),
            hypothesis_for_other=HypothesisForOther(likely_feelings=[], likely_needs=[]),
        )
    if partner_hypothesis is None:
        partner_hypothesis = HypothesisForOther(likely_feelings=[], likely_needs=[])

    # 1. Первая попытка
    contents = prepare_card_writer_contents(
        my_kind=my_kind,
        my_bytes=my_bytes,
        my_analysis=my_analysis,
        partner_hypothesis=partner_hypothesis,
        agreed_ritual=agreed_ritual,
        risk_elevated=risk_elevated,
        sparse=effective_sparse,
        guidance=guidance,
    )
    card, meta = await call_card_writer(p, contents, model=model, tracker=tracker)

    is_blocked = meta.get("blocked", False)
    if card is not None and not is_blocked:
        card = sanitize_card_minor_banned_words(card)
        if agreed_ritual and card.action_scripts and not card.ritual_unfit:
            card.action_scripts = align_action_scripts_with_ritual(card.action_scripts, agreed_ritual)
        if effective_sparse:
            card.validation = format_sparse_validation(card.validation)
        errors = validate_partner_card(card, is_high_risk=False, sparse=effective_sparse)
    elif card is None or is_blocked:
        errors = ["blocked: " + str(meta.get("error", "provider_refusal"))]
    else:
        errors = validate_partner_card(card, is_high_risk=False, sparse=effective_sparse)

    # 2. Шаг (а): до 2 повторов (при blocked — максимум 1 повтор)
    max_retries = 1 if is_blocked else 2
    for retry_idx in range(1, max_retries + 1):
        if not errors and card is not None:
            break
        logger.warning("[%s] Card validation errors (retry %d/%d): %s", partner_tag, retry_idx, max_retries, errors)
        guidance_text = (
            f"В прошлой попытке найдены ошибки: {'; '.join(errors)}. "
            "Перепиши аккуратно. Не используй запрещенные слова/стемы. "
            "Соблюдай честность формулировок и опирайся на согласованный ритуал (<agreed_ritual>)."
        )
        retry_contents = prepare_card_writer_contents(
            my_kind=my_kind,
            my_bytes=my_bytes,
            my_analysis=my_analysis,
            partner_hypothesis=partner_hypothesis,
            agreed_ritual=agreed_ritual,
            risk_elevated=risk_elevated,
            sparse=effective_sparse,
            guidance=guidance_text,
        )
        card, meta = await call_card_writer(p, retry_contents, model=model, tracker=tracker)
        if card is not None and not meta.get("blocked"):
            card = sanitize_card_minor_banned_words(card)
            if agreed_ritual and card.action_scripts and not card.ritual_unfit:
                card.action_scripts = align_action_scripts_with_ritual(card.action_scripts, agreed_ritual)
            if effective_sparse:
                card.validation = format_sparse_validation(card.validation)
            errors = validate_partner_card(card, is_high_risk=False, sparse=effective_sparse)
        elif card is None or meta.get("blocked"):
            errors = ["blocked: " + str(meta.get("error", "provider_refusal"))]
        else:
            errors = validate_partner_card(card, is_high_risk=False, sparse=effective_sparse)

    # 3. Шаг (б): безопасный режим с пустой partner_hypothesis (если не заблокировано наглухо)
    if errors and not meta.get("blocked"):
        logger.warning("[%s] Card validation still failing after retries. Trying safe mode...", partner_tag)
        safe_guidance = (
            "Безопасный режим: напиши partner_perspective предельно общо: "
            "«У твоего партнёра в этой ситуации, скорее всего, тоже свои переживания, "
            "и они могут отличаться от того, как это выглядит со стороны»."
        )
        safe_contents = prepare_card_writer_contents(
            my_kind=my_kind,
            my_bytes=my_bytes,
            my_analysis=my_analysis,
            partner_hypothesis=HypothesisForOther(likely_feelings=[], likely_needs=[]),
            agreed_ritual=agreed_ritual,
            risk_elevated=risk_elevated,
            sparse=effective_sparse,
            guidance=safe_guidance,
        )
        card, meta = await call_card_writer(p, safe_contents, model=model, tracker=tracker)
        if card is not None and not meta.get("blocked"):
            card = sanitize_card_minor_banned_words(card)
            if agreed_ritual and card.action_scripts and not card.ritual_unfit:
                card.action_scripts = align_action_scripts_with_ritual(card.action_scripts, agreed_ritual)
            if effective_sparse:
                card.validation = format_sparse_validation(card.validation)
            errors = validate_partner_card(card, is_high_risk=False, sparse=effective_sparse)
        elif card is None or meta.get("blocked"):
            errors = ["blocked: " + str(meta.get("error", "provider_refusal"))]
        else:
            errors = validate_partner_card(card, is_high_risk=False, sparse=effective_sparse)

    # Если card так и не сформировалась (например при блокировке) — создаем каркас
    if card is None:
        card = PartnerResponse(
            validation=get_random_fallback("validation", sparse=effective_sparse),
            partner_perspective=get_random_fallback("partner_perspective", sparse=effective_sparse),
            blind_spot=get_random_fallback("blind_spot", sparse=effective_sparse),
            action_scripts=[ActionScriptItem(**s) for s in get_random_fallback("action_scripts")],
            safety_note="",
            ritual_unfit=False,
        )
        if fallback_records is not None:
            fallback_records.append({"field": f"{partner_tag}.full_card", "reason": "blocked_or_parse_failure"})
        return card

    # 4. Шаг (в): замена ТОЛЬКО проблемных полей статическим фоллбэком
    if errors:
        logger.warning("[%s] Applying field-level static fallbacks: %s", partner_tag, errors)
        for err in errors:
            err_lower = err.lower()
            if "validation" in err_lower or "blocked" in err_lower:
                card.validation = get_random_fallback("validation", sparse=effective_sparse)
                reason = "sparse" if effective_sparse else "validator"
                logger.info("Fallback applied: field=%s.validation, reason=%s", partner_tag, reason)
                if fallback_records is not None:
                    fallback_records.append({"field": f"{partner_tag}.validation", "reason": reason})

            if "partner_perspective" in err_lower or "blocked" in err_lower:
                card.partner_perspective = get_random_fallback("partner_perspective", sparse=effective_sparse)
                logger.info("Fallback applied: field=%s.partner_perspective, reason=validator", partner_tag)
                if fallback_records is not None:
                    fallback_records.append({"field": f"{partner_tag}.partner_perspective", "reason": "validator"})

            if "blind_spot" in err_lower or "blocked" in err_lower:
                card.blind_spot = get_random_fallback("blind_spot", sparse=effective_sparse)
                logger.info("Fallback applied: field=%s.blind_spot, reason=validator", partner_tag)
                if fallback_records is not None:
                    fallback_records.append({"field": f"{partner_tag}.blind_spot", "reason": "validator"})

            if "action_scripts" in err_lower or "скрипт" in err_lower or "blocked" in err_lower:
                raw_scripts = get_random_fallback("action_scripts")
                card.action_scripts = [ActionScriptItem(**s) for s in raw_scripts]
                logger.info("Fallback applied: field=%s.action_scripts, reason=validator", partner_tag)
                if fallback_records is not None:
                    fallback_records.append({"field": f"{partner_tag}.action_scripts", "reason": "validator"})

    return card


async def generate_shared_summary_with_ladder(
    provider_or_client: Optional[Union[LLMProvider, Any]] = None,
    shared_analysis: Optional[SharedAnalysis] = None,
    fallback_records: Optional[List[Dict[str, str]]] = None,
    model: Optional[str] = None,
    tracker: Optional[Dict[str, Any]] = None,
    client: Optional[Any] = None,
) -> SharedSummary:
    """Генерация общего итога пары по Лестнице фоллбэков."""
    p = _resolve_provider(provider_or_client or client, role="shared_writer", model=model)
    if shared_analysis is None:
        shared_analysis = SharedAnalysis(
            pattern="Разногласия во взглядах", common_need="взаимопонимание",
            neutral_topic=None, ritual_ideas=[], agreed_ritual=None,
        )

    contents = prepare_shared_writer_contents(shared_analysis)
    shared_card, meta = await call_shared_writer(p, contents, model=model, tracker=tracker)

    is_blocked = meta.get("blocked", False)
    if shared_card is not None and not is_blocked:
        shared_card = sanitize_shared_minor_banned_words(shared_card)
        errors = validate_shared_summary(shared_card, is_high_risk=False)
    elif shared_card is None or is_blocked:
        errors = ["blocked: " + str(meta.get("error", "provider_refusal"))]
    else:
        errors = validate_shared_summary(shared_card, is_high_risk=False)

    max_retries = 1 if is_blocked else 2
    for retry_idx in range(1, max_retries + 1):
        if not errors and shared_card is not None:
            break
        logger.warning("[shared] Shared validation errors (retry %d/%d): %s", retry_idx, max_retries, errors)
        guidance = (
            f"В прошлой попытке общий итог не прошёл валидацию: {'; '.join(errors)}. "
            "Убедись, что situation_overview и shared_advice содержат не менее 2 предложений каждое, "
            "используются исключительно местоимения 'вы'/'вам'/'вас', нет слов 'один', 'другой', 'ты', 'чай'."
        )
        retry_contents = prepare_shared_writer_contents(shared_analysis, guidance=guidance)
        shared_card, meta = await call_shared_writer(p, retry_contents, model=model, tracker=tracker)
        if shared_card is not None and not meta.get("blocked"):
            shared_card = sanitize_shared_minor_banned_words(shared_card)
            errors = validate_shared_summary(shared_card, is_high_risk=False)
        elif shared_card is None or meta.get("blocked"):
            errors = ["blocked: " + str(meta.get("error", "provider_refusal"))]
        else:
            errors = validate_shared_summary(shared_card, is_high_risk=False)

    if shared_card is None:
        raw_sh = get_random_fallback("shared_summary")
        shared_card = SharedSummary(
            situation_overview=raw_sh["situation_overview"],
            shared_advice=raw_sh["shared_advice"],
            conversation_starter=raw_sh["conversation_starter"],
        )
        if fallback_records is not None:
            fallback_records.append({"field": "shared_summary.full", "reason": "blocked_or_parse_failure"})
        return shared_card

    if errors:
        logger.warning("[shared] Applying field-level static fallbacks: %s", errors)
        for err in errors:
            err_lower = err.lower()
            if "situation_overview" in err_lower or "blocked" in err_lower:
                shared_card.situation_overview = get_random_fallback("situation_overview")
                logger.info("Fallback applied: field=shared_summary.situation_overview, reason=validator")
                if fallback_records is not None:
                    fallback_records.append({"field": "shared_summary.situation_overview", "reason": "validator"})

            if "shared_advice" in err_lower or "blocked" in err_lower:
                shared_card.shared_advice = get_random_fallback("shared_advice")
                logger.info("Fallback applied: field=shared_summary.shared_advice, reason=validator")
                if fallback_records is not None:
                    fallback_records.append({"field": "shared_summary.shared_advice", "reason": "validator"})

            if "conversation_starter" in err_lower or "blocked" in err_lower:
                shared_card.conversation_starter = get_random_fallback("conversation_starter")
                logger.info("Fallback applied: field=shared_summary.conversation_starter, reason=validator")
                if fallback_records is not None:
                    fallback_records.append({"field": "shared_summary.conversation_starter", "reason": "validator"})

    return shared_card


def apply_fallback_to_field(output: MediatorOutput, location: Optional[str]) -> MediatorOutput:
    """Применяет случайный статический безопасный фоллбэк к конкретному полю при утечке."""
    loc = (location or "").lower()

    if "partner_1" in loc or "partner_1_response" in loc:
        if "partner_perspective" in loc:
            output.partner_1_response.partner_perspective = get_random_fallback("partner_perspective")
        elif "blind_spot" in loc:
            output.partner_1_response.blind_spot = get_random_fallback("blind_spot")
        elif "action_scripts" in loc:
            raw_s = get_random_fallback("action_scripts")
            output.partner_1_response.action_scripts = [ActionScriptItem(**s) for s in raw_s]
        elif "validation" in loc:
            output.partner_1_response.validation = get_random_fallback("validation")
        else:
            output.partner_1_response.partner_perspective = get_random_fallback("partner_perspective")

    elif "partner_2" in loc or "partner_2_response" in loc:
        if "partner_perspective" in loc:
            output.partner_2_response.partner_perspective = get_random_fallback("partner_perspective")
        elif "blind_spot" in loc:
            output.partner_2_response.blind_spot = get_random_fallback("blind_spot")
        elif "action_scripts" in loc:
            raw_s = get_random_fallback("action_scripts")
            output.partner_2_response.action_scripts = [ActionScriptItem(**s) for s in raw_s]
        elif "validation" in loc:
            output.partner_2_response.validation = get_random_fallback("validation")
        else:
            output.partner_2_response.partner_perspective = get_random_fallback("partner_perspective")

    elif "shared" in loc:
        if "situation_overview" in loc:
            output.shared_summary.situation_overview = get_random_fallback("situation_overview")
        elif "shared_advice" in loc:
            output.shared_summary.shared_advice = get_random_fallback("shared_advice")
        elif "conversation_starter" in loc:
            output.shared_summary.conversation_starter = get_random_fallback("conversation_starter")
        else:
            raw_sh = get_random_fallback("shared_summary")
            output.shared_summary.situation_overview = raw_sh["situation_overview"]
            output.shared_summary.shared_advice = raw_sh["shared_advice"]
            output.shared_summary.conversation_starter = raw_sh["conversation_starter"]

    # Гарантия наличия ровно 2 скриптов действий после любых фоллбэков
    if output.partner_1_response and len(output.partner_1_response.action_scripts) != 2:
        raw_s = get_random_fallback("action_scripts")
        output.partner_1_response.action_scripts = [ActionScriptItem(**s) for s in raw_s]
    if output.partner_2_response and len(output.partner_2_response.action_scripts) != 2:
        raw_s = get_random_fallback("action_scripts")
        output.partner_2_response.action_scripts = [ActionScriptItem(**s) for s in raw_s]

    return output


# Совместимость со старым вызовом
def get_genai_client():
    """Совместимость: возвращает экземпляр GeminiProvider."""
    return get_provider(provider_name="gemini")


# ==============================================================================
# Главная точка входа: analyze_session(session_id)
# ==============================================================================

async def analyze_session(session_id: str) -> None:
    """
    Выполняет полный конфиденциальный многошаговый пайплайн разбора конфликта.
    Соблюдает строгий информационный барьер, Лестницу фоллбэков и нулевой лог сырых данных.
    Работает с текущим активным LLMProvider (Gemini / GigaChat).
    """
    from bot import bot, get_miniapp_keyboard
    repo = get_repo()

    logger.info("Starting multi-step conflict analysis for session %s (provider=%s)", session_id, settings.LLM_PROVIDER)
    session = repo.get_session_by_id(session_id)
    if not session:
        logger.error("Session %s not found in DB", session_id)
        return

    # Атомарный захват сессии для разбора (защита от повторного/параллельного запуска)
    if not repo.claim_session_for_analysis(session_id):
        logger.warning("Session %s is already being analyzed or completed, skipping duplicate execution", session_id)
        return

    couple = repo.get_couple_by_id(session["couple_id"])
    if not couple:
        logger.error("Couple for session %s not found", session_id)
        return

    p1_id = couple.get("partner_1_id")
    p2_id = couple.get("partner_2_id")

    # 1. Извлекаем зашифрованные исходники из pending_inputs
    inputs = repo.get_pending_inputs(session_id)
    p1_input = next((inp for inp in inputs if inp["author_telegram_id"] == p1_id), None)
    p2_input = next((inp for inp in inputs if inp["author_telegram_id"] == p2_id), None)

    if not p1_input or not p2_input:
        logger.error("Missing pending inputs for session %s", session_id)
        now_iso = datetime.now(timezone.utc).isoformat()
        repo.update_session_status(session_id, status="failed", completed_at=now_iso)

        fail_msg = (
            "⚠️ Разбор не может быть завершен: не получена позиция одного из партнеров.\n"
            "Бесплатная попытка не списана. Пожалуйста, запустите разбор заново, когда оба будете готовы."
        )
        for target_id in (p1_id, p2_id):
            if target_id:
                try:
                    await bot.send_message(target_id, fail_msg, reply_markup=get_miniapp_keyboard())
                except Exception as ex:
                    logger.warning("Failed to notify user %s: %s", target_id, ex)
        return

    # 2. Расшифровываем полезную нагрузку в памяти
    p1_raw: Optional[bytes] = None
    p2_raw: Optional[bytes] = None

    try:
        p1_raw = crypto.decrypt_bytes(p1_input["payload_encrypted"])
        p2_raw = crypto.decrypt_bytes(p2_input["payload_encrypted"])
        if len(p1_raw.strip()) == 0 or len(p2_raw.strip()) == 0:
            raise ValueError("Пустая позиция после расшифровки")
    except Exception as e:
        logger.error("Failed to decrypt inputs for session %s: %s", session_id, e)
        now_iso = datetime.now(timezone.utc).isoformat()
        repo.update_session_status(session_id, status="failed", completed_at=now_iso)
        return

    provider = get_provider()
    mediator_output: Optional[MediatorOutput] = None
    fallback_records: List[Dict[str, str]] = []
    tracker: Dict[str, Any] = {
        "total_tokens": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "calls": 0,
        "blocked_calls": 0,
    }

    try:
        # Обработка аудио: проверка поддержки аудио провайдером
        p1_kind = p1_input["kind"]
        p2_kind = p2_input["kind"]
        if (p1_kind == "audio" or p2_kind == "audio") and not getattr(provider, "supports_audio", False):
            logger.warning(
                "Audio input received for session %s, but provider %s does not support audio",
                session_id,
                getattr(provider, "provider_name", "unknown"),
            )
            repo.delete_pending_inputs_for_session(session_id)
            now_iso = datetime.now(timezone.utc).isoformat()
            repo.update_session_status(session_id, status="failed", completed_at=now_iso)
            from bot import bot
            unsupported_msg = (
                "⚠️ Не удалось обработать сессию: голосовые сообщения не поддерживаются текущим провайдером ИИ. "
                "Пожалуйста, отправьте версии текстом."
            )
            for uid in (p1_input.get("author_telegram_id"), p2_input.get("author_telegram_id")):
                if uid:
                    try:
                        await bot.send_message(chat_id=uid, text=unsupported_msg)
                    except Exception as ex:
                        logger.warning("Failed to notify user %s about unsupported audio: %s", uid, ex)
            return

        # Если провайдер поддерживает аудио через транскрибацию (не gemini):
        try:
            if p1_kind == "audio" and provider.provider_name != "gemini":
                logger.info("Transcribing audio for partner 1 via provider interface...")
                p1_text = await provider.transcribe(p1_raw)
                p1_raw = p1_text.encode("utf-8")
                p1_kind = "text"
            if p2_kind == "audio" and provider.provider_name != "gemini":
                logger.info("Transcribing audio for partner 2 via provider interface...")
                p2_text = await provider.transcribe(p2_raw)
                p2_raw = p2_text.encode("utf-8")
                p2_kind = "text"
        except NotImplementedError:
            logger.warning(
                "Provider %s transcribe raised NotImplementedError for session %s",
                getattr(provider, "provider_name", "unknown"),
                session_id,
            )
            repo.delete_pending_inputs_for_session(session_id)
            now_iso = datetime.now(timezone.utc).isoformat()
            repo.update_session_status(session_id, status="failed", completed_at=now_iso)
            from bot import bot
            unsupported_msg = (
                "⚠️ Не удалось обработать сессию: распознавание голосовых сообщений недоступно. "
                "Пожалуйста, отправьте версии текстом."
            )
            for uid in (p1_input.get("author_telegram_id"), p2_input.get("author_telegram_id")):
                if uid:
                    try:
                        await bot.send_message(chat_id=uid, text=unsupported_msg)
                    except Exception as ex:
                        logger.warning("Failed to notify user %s: %s", uid, ex)
            return

        # ======================================================================
        # Шаг A: Анализатор версий
        # ======================================================================
        analyzer_contents = prepare_analyzer_contents(
            p1_kind=p1_kind,
            p1_bytes=p1_raw,
            p2_kind=p2_kind,
            p2_bytes=p2_raw,
        )
        analyzer_res = await call_analyzer(provider, analyzer_contents, tracker=tracker)
        logger.info(
            "Analyzer completed for session %s. Risk level: %s (risk_reasons_count=%d)",
            session_id,
            analyzer_res.risk_level,
            len(analyzer_res.risk_reasons or []),
        )

        # Очистка hypothesis_for_other и agreed_ritual от приватных фактов чужой версии (Этап 3.10)
        neutral_facts = [analyzer_res.shared.neutral_topic] if analyzer_res.shared and analyzer_res.shared.neutral_topic else []
        if analyzer_res.partner_1 and analyzer_res.partner_2:
            analyzer_res.partner_1.hypothesis_for_other = sanitize_hypothesis_for_other(
                analyzer_res.partner_1.hypothesis_for_other,
                other_private_facts=analyzer_res.partner_2.key_facts,
                other_secrets=analyzer_res.partner_2.secrets,
                facts_known_to_both=neutral_facts,
            )
            analyzer_res.partner_2.hypothesis_for_other = sanitize_hypothesis_for_other(
                analyzer_res.partner_2.hypothesis_for_other,
                other_private_facts=analyzer_res.partner_1.key_facts,
                other_secrets=analyzer_res.partner_1.secrets,
                facts_known_to_both=neutral_facts,
            )
        if analyzer_res.shared and analyzer_res.shared.agreed_ritual:
            all_priv = (analyzer_res.partner_1.key_facts or []) + (analyzer_res.partner_2.key_facts or [])
            all_sec = (analyzer_res.partner_1.secrets or []) + (analyzer_res.partner_2.secrets or [])
            analyzer_res.shared.agreed_ritual = sanitize_agreed_ritual(
                analyzer_res.shared.agreed_ritual,
                all_private_facts=all_priv,
                all_secrets=all_sec,
                facts_known_to_both=neutral_facts,
            )

        # ----------------------------------------------------------------------
        # ВЕТВЬ 0: НЕРЕЛЕВАНТНЫЙ ВВОД / СПАМ / ШУТКА (NOT APPLICABLE) (Этап 3.16)
        # ----------------------------------------------------------------------
        if getattr(analyzer_res, "not_applicable", False):
            logger.info("Analyzer marked session %s as not_applicable=True. Using polite refusal notice.", session_id)
            p1_resp = PartnerResponse(**NOT_APPLICABLE_CARD)
            p2_resp = PartnerResponse(**NOT_APPLICABLE_CARD)
            shared_res = SharedSummary(**NOT_APPLICABLE_SHARED)
            mediator_output = MediatorOutput(
                risk_level="none",
                partner_1_response=p1_resp,
                partner_2_response=p2_resp,
                shared_summary=shared_res,
                safety_note="",
                not_applicable=True,
                provider_refusal=getattr(analyzer_res, "provider_refusal", False),
            )

        # ----------------------------------------------------------------------
        # ВЕТВЬ 1: ВЫСОКИЙ РИСК (HIGH) ИЛИ ОТКАЗ ПРОВАЙДЕРА
        # ----------------------------------------------------------------------
        elif analyzer_res.risk_level == "high":
            safety_msg = get_high_risk_message()
            p1_resp = PartnerResponse(
                validation=safety_msg,
                partner_perspective="",
                blind_spot="",
                action_scripts=[],
                safety_note=safety_msg,
            )
            p2_resp = PartnerResponse(
                validation=safety_msg,
                partner_perspective="",
                blind_spot="",
                action_scripts=[],
                safety_note=safety_msg,
            )
            shared_res = SharedSummary(
                situation_overview="",
                shared_advice="",
                conversation_starter="",
            )
            mediator_output = MediatorOutput(
                risk_level="high",
                partner_1_response=p1_resp,
                partner_2_response=p2_resp,
                shared_summary=shared_res,
                safety_note=safety_msg,
                provider_refusal=getattr(analyzer_res, "provider_refusal", False),
            )

        # ----------------------------------------------------------------------
        # ВЕТВЬ 2: ОБЫЧНЫЙ ИЛИ ПОВЫШЕННЫЙ РИСК (NONE / ELEVATED)
        # ----------------------------------------------------------------------
        else:
            is_elevated = (analyzer_res.risk_level == "elevated")
            has_followup_p1 = bool(p1_input.get("has_followup") or p1_input.get("has_clarification"))
            has_followup_p2 = bool(p2_input.get("has_followup") or p2_input.get("has_clarification"))

            # Шаг B1: Карточка партнера 1 по Лестнице фоллбэков
            p1_card = await generate_partner_card_with_ladder(
                provider_or_client=provider,
                my_kind=p1_kind,
                my_bytes=p1_raw,
                my_analysis=analyzer_res.partner_1,
                partner_hypothesis=analyzer_res.partner_2.hypothesis_for_other,
                agreed_ritual=analyzer_res.shared.agreed_ritual,
                risk_elevated=is_elevated,
                sparse=analyzer_res.partner_1.sparse,
                has_followup=has_followup_p1,
                partner_tag="partner_1",
                fallback_records=fallback_records,
                tracker=tracker,
            )

            # Шаг B2: Карточка партнера 2 по Лестнице фоллбэков
            p2_card = await generate_partner_card_with_ladder(
                provider_or_client=provider,
                my_kind=p2_kind,
                my_bytes=p2_raw,
                my_analysis=analyzer_res.partner_2,
                partner_hypothesis=analyzer_res.partner_1.hypothesis_for_other,
                agreed_ritual=analyzer_res.shared.agreed_ritual,
                risk_elevated=is_elevated,
                sparse=analyzer_res.partner_2.sparse,
                has_followup=has_followup_p2,
                partner_tag="partner_2",
                fallback_records=fallback_records,
                tracker=tracker,
            )

            # Шаг C: Общий итог для пары по Лестнице фоллбэков
            shared_card = await generate_shared_summary_with_ladder(
                provider_or_client=provider,
                shared_analysis=analyzer_res.shared,
                fallback_records=fallback_records,
                tracker=tracker,
            )

            # Автовыравнивание ритуала в action_scripts перед валидацией согласованности (Этап 3.18)
            if analyzer_res.shared and analyzer_res.shared.agreed_ritual:
                rit = analyzer_res.shared.agreed_ritual
                if p1_card.action_scripts and not p1_card.ritual_unfit:
                    p1_card.action_scripts = align_action_scripts_with_ritual(p1_card.action_scripts, rit)
                if p2_card.action_scripts and not p2_card.ritual_unfit:
                    p2_card.action_scripts = align_action_scripts_with_ritual(p2_card.action_scripts, rit)

            # Проверка согласованности длительностей ритуала (Этап 3.3, 3.18)
            p1_s2_text = p1_card.action_scripts[1].text if len(p1_card.action_scripts) >= 2 else ""
            p2_s2_text = p2_card.action_scripts[1].text if len(p2_card.action_scripts) >= 2 else ""
            cons_errs = validate_ritual_consistency(
                p1_s2_text,
                p2_s2_text,
                shared_card.shared_advice or "",
                ritual_unfit_p1=bool(p1_card.ritual_unfit),
                ritual_unfit_p2=bool(p2_card.ritual_unfit),
            )
            if cons_errs:
                logger.warning("Ritual duration mismatch: %s. Performing retry...", cons_errs)
                dur_hint = analyzer_res.shared.agreed_ritual.duration_minutes if analyzer_res.shared.agreed_ritual else "из ритуала"
                retry_guidance = f"Используй точную длительность ({dur_hint} мин) из согласованного ритуала во втором скрипте."
                p1_durs = extract_durations(p1_s2_text)
                p2_durs = extract_durations(p2_s2_text)
                sh_durs = extract_durations(shared_card.shared_advice or "")
                if p1_durs != sh_durs and not p1_card.ritual_unfit:
                    p1_card = await generate_partner_card_with_ladder(
                        provider_or_client=provider,
                        my_kind=p1_kind,
                        my_bytes=p1_raw,
                        my_analysis=analyzer_res.partner_1,
                        partner_hypothesis=analyzer_res.partner_2.hypothesis_for_other,
                        agreed_ritual=analyzer_res.shared.agreed_ritual,
                        risk_elevated=is_elevated,
                        sparse=analyzer_res.partner_1.sparse,
                        partner_tag="partner_1",
                        fallback_records=fallback_records,
                        guidance=retry_guidance,
                        tracker=tracker,
                    )
                if p2_durs != sh_durs and not p2_card.ritual_unfit:
                    p2_card = await generate_partner_card_with_ladder(
                        provider_or_client=provider,
                        my_kind=p2_kind,
                        my_bytes=p2_raw,
                        my_analysis=analyzer_res.partner_2,
                        partner_hypothesis=analyzer_res.partner_1.hypothesis_for_other,
                        agreed_ritual=analyzer_res.shared.agreed_ritual,
                        risk_elevated=is_elevated,
                        sparse=analyzer_res.partner_2.sparse,
                        partner_tag="partner_2",
                        fallback_records=fallback_records,
                        guidance=retry_guidance,
                        tracker=tracker,
                    )

                # Повторная проверка: если расхождение всё равно осталось — детерминированный фоллбэк (Этап 3.10)
                p1_s2_retry = p1_card.action_scripts[1].text if len(p1_card.action_scripts) >= 2 else ""
                p2_s2_retry = p2_card.action_scripts[1].text if len(p2_card.action_scripts) >= 2 else ""
                post_retry_errs = validate_ritual_consistency(
                    p1_s2_retry,
                    p2_s2_retry,
                    shared_card.shared_advice or "",
                    ritual_unfit_p1=bool(p1_card.ritual_unfit),
                    ritual_unfit_p2=bool(p2_card.ritual_unfit),
                )
                if post_retry_errs:
                    logger.warning("Ritual duration mismatch persisted after retry: %s. Applying deterministic overwrite.", post_retry_errs)
                    det_script_text = build_deterministic_ritual_script(
                        analyzer_res.shared.agreed_ritual if analyzer_res.shared else None,
                        shared_card.shared_advice or "",
                    )
                    if len(p1_card.action_scripts) >= 2:
                        p1_card.action_scripts[1].text = det_script_text
                    if len(p2_card.action_scripts) >= 2:
                        p2_card.action_scripts[1].text = det_script_text

            # При risk_level == elevated: фиксированный шаблон safety_note
            safety_note_text = ""
            if is_elevated:
                safety_note_text = get_elevated_risk_message()
                p1_card.safety_note = safety_note_text
                p2_card.safety_note = safety_note_text

            # ------------------------------------------------------------------
            # Шаг D.1: Детерминированный Leak Guard (лемматический барьер)
            # ------------------------------------------------------------------
            p1_text_str = p1_raw.decode("utf-8", errors="ignore")
            p2_text_str = p2_raw.decode("utf-8", errors="ignore")
            neutral_facts = [analyzer_res.shared.neutral_topic] if analyzer_res.shared and analyzer_res.shared.neutral_topic else []

            p1_card_text = f"{p1_card.validation} {p1_card.partner_perspective} {p1_card.blind_spot} " + " ".join(s.text for s in p1_card.action_scripts)
            p1_leak = check_card_lemma_leaks(
                card_text=p1_card_text,
                other_private_facts=analyzer_res.partner_2.key_facts,
                other_secrets=analyzer_res.partner_2.secrets,
                recipient_raw=p1_text_str,
                recipient_facts=analyzer_res.partner_1.key_facts,
                facts_known_to_both=neutral_facts,
            )
            if p1_leak:
                logger.warning("lemma leak field=partner_1 count=%d", len(p1_leak))
                p1_card = await generate_partner_card_with_ladder(
                    provider_or_client=provider,
                    my_kind=p1_kind,
                    my_bytes=p1_raw,
                    my_analysis=analyzer_res.partner_1,
                    partner_hypothesis=analyzer_res.partner_2.hypothesis_for_other,
                    risk_elevated=is_elevated,
                    sparse=analyzer_res.partner_1.sparse,
                    guidance="ВНИМАНИЕ: Обнаружено совпадение фактов второго партнера. Избегай конкретных деталей чужой версии.",
                    tracker=tracker,
                    fallback_records=fallback_records,
                )

            p2_card_text = f"{p2_card.validation} {p2_card.partner_perspective} {p2_card.blind_spot} " + " ".join(s.text for s in p2_card.action_scripts)
            p2_leak = check_card_lemma_leaks(
                card_text=p2_card_text,
                other_private_facts=analyzer_res.partner_1.key_facts,
                other_secrets=analyzer_res.partner_1.secrets,
                recipient_raw=p2_text_str,
                recipient_facts=analyzer_res.partner_2.key_facts,
                facts_known_to_both=neutral_facts,
            )
            if p2_leak:
                logger.warning("lemma leak field=partner_2 count=%d", len(p2_leak))
                p2_card = await generate_partner_card_with_ladder(
                    provider_or_client=provider,
                    my_kind=p2_kind,
                    my_bytes=p2_raw,
                    my_analysis=analyzer_res.partner_2,
                    partner_hypothesis=analyzer_res.partner_1.hypothesis_for_other,
                    risk_elevated=is_elevated,
                    sparse=analyzer_res.partner_2.sparse,
                    guidance="ВНИМАНИЕ: Обнаружено совпадение фактов второго партнера. Избегай конкретных деталей чужой версии.",
                    tracker=tracker,
                    fallback_records=fallback_records,
                )

            shared_card_text = f"{shared_card.situation_overview} {shared_card.shared_advice} {shared_card.conversation_starter}"
            shared_leak = check_shared_lemma_leaks(
                shared_text=shared_card_text,
                all_private_facts=(analyzer_res.partner_1.key_facts or []) + (analyzer_res.partner_2.key_facts or []),
                all_secrets=(analyzer_res.partner_1.secrets or []) + (analyzer_res.partner_2.secrets or []),
                facts_known_to_both=neutral_facts,
            )
            if shared_leak:
                logger.warning("lemma leak field=shared_summary count=%d", len(shared_leak))
                shared_card = await generate_shared_summary_with_ladder(
                    provider_or_client=provider,
                    shared_analysis=analyzer_res.shared,
                    partner_1_topic=analyzer_res.partner_1.topic,
                    partner_2_topic=analyzer_res.partner_2.topic,
                    risk_elevated=is_elevated,
                    guidance="ВНИМАНИЕ: В общем итоге обнаружены приватные факты партнеров. Сформулируй строго нейтрально.",
                    tracker=tracker,
                    fallback_records=fallback_records,
                )

            # Разнообразие зачинов partner_perspective (Этап 3.4, 3.9)
            diversify_partner_perspectives(p1_card, p2_card)

            mediator_output = MediatorOutput(
                risk_level=analyzer_res.risk_level,
                partner_1_response=p1_card,
                partner_2_response=p2_card,
                shared_summary=shared_card,
                safety_note=safety_note_text,
                provider_refusal=getattr(analyzer_res, "provider_refusal", False),
            )

            # ==================================================================
            # Шаг D.2: LLM Проверка утечек конфиденциальности (Leak Checker)
            # ==================================================================
            leak_contents = prepare_leak_checker_contents(
                p1_kind=p1_kind,
                p1_bytes=p1_raw,
                p2_kind=p2_kind,
                p2_bytes=p2_raw,
                secrets_p1=analyzer_res.partner_1.secrets,
                secrets_p2=analyzer_res.partner_2.secrets,
                generated_analysis=mediator_output,
            )
            leak_res = await call_leak_checker(provider, leak_contents, tracker=tracker)

            if leak_res.leak:
                loc = leak_res.location or "unknown"
                logger.warning("Leak detected field=%s count=1. Starting leak ladder...", loc)

                leak_guidance = (
                    f"ВНИМАНИЕ: В прошлой попытке обнаружена утечка в '{loc}' ({leak_res.reason}). "
                    "Перепиши строго более общо, соблюдая информационный барьер и не раскрывая чужих секретов."
                )
                if "partner_1" in loc:
                    mediator_output.partner_1_response = await generate_partner_card_with_ladder(
                        provider_or_client=provider,
                        my_kind=p1_kind,
                        my_bytes=p1_raw,
                        my_analysis=analyzer_res.partner_1,
                        partner_hypothesis=analyzer_res.partner_2.hypothesis_for_other,
                        risk_elevated=is_elevated,
                        sparse=analyzer_res.partner_1.sparse,
                        guidance=leak_guidance,
                        tracker=tracker,
                    )
                elif "partner_2" in loc:
                    mediator_output.partner_2_response = await generate_partner_card_with_ladder(
                        provider_or_client=provider,
                        my_kind=p2_kind,
                        my_bytes=p2_raw,
                        my_analysis=analyzer_res.partner_2,
                        partner_hypothesis=analyzer_res.partner_1.hypothesis_for_other,
                        risk_elevated=is_elevated,
                        sparse=analyzer_res.partner_2.sparse,
                        guidance=leak_guidance,
                        tracker=tracker,
                    )
                elif "shared" in loc:
                    mediator_output.shared_summary = await generate_shared_summary_with_ladder(
                        provider_or_client=provider,
                        shared_analysis=analyzer_res.shared,
                        fallback_records=fallback_records,
                        tracker=tracker,
                    )

                # Вторая проверка утечки
                second_leak = await call_leak_checker(
                    provider,
                    prepare_leak_checker_contents(
                        p1_kind=p1_kind,
                        p1_bytes=p1_raw,
                        p2_kind=p2_kind,
                        p2_bytes=p2_raw,
                        secrets_p1=analyzer_res.partner_1.secrets,
                        secrets_p2=analyzer_res.partner_2.secrets,
                        generated_analysis=mediator_output,
                    ),
                    tracker=tracker,
                )
                if second_leak.leak:
                    loc2 = second_leak.location or loc
                    logger.warning("Leak persisted in safe mode. Applying static fallback for '%s'", loc2)
                    mediator_output = apply_fallback_to_field(mediator_output, loc2)
                    fallback_records.append({"field": loc2, "reason": "leak"})

            # ------------------------------------------------------------------
            # Финальный прогон валидатора перед записью в БД
            # ------------------------------------------------------------------
            final_errors = validate_full_mediator_output(
                mediator_output,
                is_sparse_p1=analyzer_res.partner_1.sparse,
                is_sparse_p2=analyzer_res.partner_2.sparse,
            )
            if final_errors:
                logger.warning("Final validation detected issues: %s. Sanitizing...", final_errors)
                for err in final_errors:
                    err_l = err.lower()
                    if "[p1]" in err_l:
                        mediator_output = apply_fallback_to_field(mediator_output, "partner_1_response." + err_l.split("]")[1])
                        fallback_records.append({"field": "partner_1", "reason": "validator"})
                    elif "[p2]" in err_l:
                        mediator_output = apply_fallback_to_field(mediator_output, "partner_2_response." + err_l.split("]")[1])
                        fallback_records.append({"field": "partner_2", "reason": "validator"})
                    elif "[shared]" in err_l:
                        mediator_output = apply_fallback_to_field(mediator_output, "shared_summary." + err_l.split("]")[1])
                        fallback_records.append({"field": "shared_summary", "reason": "validator"})

    except Exception as e:
        logger.error("Analysis failed with exception for session %s: %s", session_id, e, exc_info=True)
        now_iso = datetime.now(timezone.utc).isoformat()
        repo.update_session_status(session_id, status="failed", completed_at=now_iso)

        error_notify = (
            "⚠️ Произошла ошибка при формировании разбора ссоры. "
            "Пожалуйста, попробуйте перезапустить разбор чуть позже. Попытка не списана."
        )
        for target_id in (p1_id, p2_id):
            if target_id:
                try:
                    await bot.send_message(target_id, error_notify, reply_markup=get_miniapp_keyboard())
                except Exception as ex:
                    logger.warning("Failed to send error notification: %s", ex)
        return

    finally:
        del p1_raw
        del p2_raw
        gc.collect()

    logger.info(
        "Session %s LLM usage: %d total tokens (prompt=%d, comp=%d, calls=%d, blocked=%d)",
        session_id,
        tracker["total_tokens"],
        tracker["prompt_tokens"],
        tracker["completion_tokens"],
        tracker["calls"],
        tracker["blocked_calls"],
    )

    # Автовыравнивание ритуала в action_scripts с agreed_ritual (только для релевантных разборов)
    if not mediator_output.not_applicable and mediator_output.shared_summary and getattr(mediator_output.shared_summary, "agreed_ritual", None):
        ritual = mediator_output.shared_summary.agreed_ritual
        if mediator_output.partner_1_response and mediator_output.partner_1_response.action_scripts:
            mediator_output.partner_1_response.action_scripts = align_action_scripts_with_ritual(
                mediator_output.partner_1_response.action_scripts, ritual
            )
        if mediator_output.partner_2_response and mediator_output.partner_2_response.action_scripts:
            mediator_output.partner_2_response.action_scripts = align_action_scripts_with_ritual(
                mediator_output.partner_2_response.action_scripts, ritual
            )

    # Сохранение готового результата в базу данных
    now_iso = datetime.now(timezone.utc).isoformat()
    analysis_payload = mediator_output.model_dump()

    repo.save_analysis_results(
        session_id=session_id,
        results=analysis_payload,
        risk_level=mediator_output.risk_level,
        completed_at=now_iso,
    )
    logger.info("Analysis successfully saved in DB for session %s (not_applicable=%s)", session_id, mediator_output.not_applicable)

    # При not_applicable бесплатный разбор НЕ списывается (Этап 3.12)
    if not mediator_output.not_applicable:
        has_sub, sub_type = repo.check_couple_access(couple)
        if sub_type == "free_session":
            repo.decrement_free_sessions(couple["id"])

    if mediator_output.not_applicable:
        push_message = (
            "ℹ️ Текст не содержит описания кризисной ситуации в паре и не подлежит разбору.\n\n"
            "Пожалуйста, опишите реальную ситуацию или конфликт между вами.\n"
            "Бесплатная попытка разбора не списана!"
        )
    else:
        push_message = (
            "✨ Разбор вашей ситуации готов!\n\n"
            "Мы подготовили персональный разбор для каждого и общий итог для пары.\n"
            "Откройте приложение, чтобы ознакомиться с результатами."
        )
    for target_id in (p1_id, p2_id):
        if target_id:
            try:
                await bot.send_message(
                    chat_id=target_id,
                    text=push_message,
                    reply_markup=get_miniapp_keyboard(),
                )
            except Exception as ex:
                logger.warning("Failed to send completion notification to user %s: %s", target_id, ex)
