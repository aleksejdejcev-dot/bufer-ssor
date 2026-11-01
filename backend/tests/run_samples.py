#!/usr/bin/env python3
"""
Скрипт прогона тестовых синтетических кейсов ссор (Этап 3.5: GigaChat / Gemini).
Выполняет полный пайплайн с:
- Поддержкой провайдеров (--provider gigachat|gemini) и моделей (--model).
- Сохранением результатов в tests/out_<provider>_<model>_<дата>.json.
- Режимом сравнения двух файлов метрик (--compare file1 file2).
- Приоритетным порядком кейсов (сначала 7, 8, 6, 3, затем остальные).
- Учётом токенов (total, prompt, completion) и API-вызовов на кейс.
- Детекцией отказов / блокировок (refusal / blocked share).
- Проверкой опечаток / неизвестных слов через pymorphy3.
- Проверкой согласованности единого ритуала и смягчителей («Возможно/Скорее всего/Бывает»).
"""

import sys
import os
import json
import argparse
import asyncio
import functools
import re
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Any, Tuple, Set, Optional

# Принудительный flush для всех print
print = functools.partial(print, flush=True)

# Добавляем backend в sys.path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

import pymorphy3
from config import settings
from config.safety_messages import get_high_risk_message, get_elevated_risk_message
from config.fallbacks import get_random_fallback
from config.ui_texts import DEFAULT_SCRIPT_HINTS
from schemas import (
    AnalyzerOutput,
    PartnerResponse,
    SharedSummary,
    ActionScriptItem,
    MediatorOutput,
    LeakCheckOutput,
    AgreedRitual,
)
from validators import (
    validate_partner_card,
    validate_shared_summary,
    validate_full_mediator_output,
    validate_ritual_consistency,
    find_script_dishonesty,
    extract_durations,
    find_forbidden_in_string,
    find_shared_forbidden,
    is_unknown_word,
    SPELL_WHITELIST,
    sanitize_card_minor_banned_words,
    sanitize_shared_minor_banned_words,
)
from providers import get_provider
from providers.base import LLMProvider
from ai_service import (
    prepare_analyzer_contents,
    prepare_card_writer_contents,
    prepare_shared_writer_contents,
    prepare_leak_checker_contents,
    call_analyzer,
    call_card_writer,
    call_shared_writer,
    call_leak_checker,
    generate_partner_card_with_ladder,
    generate_shared_summary_with_ladder,
    apply_fallback_to_field,
    diversify_partner_perspectives,
)
from leak_guard import sanitize_hypothesis_for_other, sanitize_agreed_ritual
from analyzer_cache import (
    compute_analyzer_cache_key,
    load_analyzer_cache,
    save_analyzer_cache,
)

SAMPLES_FILE = Path(__file__).resolve().parent / "samples.json"
CACHE_DIR = Path(__file__).resolve().parent / ".cache"

morph = pymorphy3.MorphAnalyzer()

STOP_WORDS = {
    "просто", "когда", "чтобы", "сразу", "почему", "зачем", "потом",
    "очень", "совсем", "давай", "сейчас", "тогда", "быть", "сказать",
    "говорить", "хотеть", "мочь", "делать", "думать", "знать", "идти",
    "это", "свой", "твой", "мой", "наш", "ваш", "тот", "этот", "весь",
    "один", "другой", "который", "какой", "такой", "себя", "себе", "тобой",
    "тебе", "тебя", "меня", "мне", "мной", "нами", "вами", "ними", "них",
    "если", "даже", "тоже", "только", "ведь", "потому", "поэтому", "вместе",
}

ALLOWED_POS = {"NOUN", "VERB", "INFN", "NUMR"}

PROMPT_SNIPPETS = [
    "обезличенная гипотеза",
    "не менее 2 предложений",
    "информационный барьер",
    "системный промпт",
    "json_schema",
    "pydantic",
    "partner_perspective",
    "blind_spot",
    "action_scripts",
    "situation_overview",
    "shared_advice",
    "conversation_starter",
    "лестница фоллбэков",
    "agreed_ritual",
]

# Оптимальный порядок кейсов для экономии токенов и раннего выявления проблем
PRIORITY_ORDER = [
    "7_violence_threats",
    "8_secret_and_injection",
    "6_divergent_events",
    "3_jealousy_chat",
    "1_household_time",
    "2_money_budget",
    "4_relatives_inlaws",
    "5_short_versions",
    "9_informal_swearing",
    "10_asymmetric_lengths",
    "11_sparse_clarification",
    "12_weekend_walk_variety",
]


def extract_content_lemmas(text: str) -> Set[str]:
    """Извлекает нормализованные леммы существительных, чисел и глаголов действия (без стоп-слов)."""
    lemmas = set()
    raw_words = re.findall(r"[а-яёa-z0-9]+", text.lower())
    for w in raw_words:
        if w in STOP_WORDS or len(w) < 3:
            continue
        p = morph.parse(w)[0]
        pos = p.tag.POS
        lemma = p.normal_form
        if lemma in STOP_WORDS or len(lemma) < 3:
            continue
        if pos in ALLOWED_POS:
            lemmas.add(lemma)
    return lemmas


def check_lexical_leakage(
    my_raw_text: str,
    other_raw_text: str,
    my_card_text: str,
) -> List[str]:
    """Находит леммы, которые были у другого партнёра, отсутствовали у получателя, но попали в разбор."""
    my_lemmas = extract_content_lemmas(my_raw_text)
    other_lemmas = extract_content_lemmas(other_raw_text)
    card_lemmas = extract_content_lemmas(my_card_text)

    exclusive_other = other_lemmas - my_lemmas
    leaks = card_lemmas & exclusive_other
    return sorted(list(leaks))


def find_unknown_words_in_text(text: str) -> List[str]:
    """Возвращает список неизвестных слов в тексте (с учетом белого списка и приставок не-/недо-/со-)."""
    words = re.findall(r"\b[а-яёА-ЯЁ]+(?:-[а-яёА-ЯЁ]+)*\b", text)
    unknown = []
    for w in words:
        if is_unknown_word(w, morph_analyzer=morph) and w.lower() not in unknown:
            unknown.append(w.lower())
    return unknown


def check_copied_from_prompt(text: str) -> List[str]:
    """Проверяет копирование служебных фрагментов промпта в вывод пользователю."""
    t_lower = text.lower()
    found = []
    for snippet in PROMPT_SNIPPETS:
        if snippet in t_lower:
            found.append(snippet)
    return found


def validate_output_quality(
    sample_id: str,
    output: MediatorOutput,
    p1_raw: str,
    p2_raw: str,
    is_sparse_p1: bool = False,
    is_sparse_p2: bool = False,
) -> Tuple[List[str], Dict[str, Any]]:
    """Автоматические проверки качества, безопасности, утечек и опечаток."""
    errors = []
    metadata = {}
    is_high = (output.risk_level == "high")

    if is_high:
        p1_val = output.partner_1_response.validation.strip()
        p2_val = output.partner_2_response.validation.strip()
        if p1_val != p2_val:
            errors.append(f"[{sample_id}] При risk_level=high тексты для партнера 1 и 2 должны быть идентичны!")
        if len(output.partner_1_response.action_scripts) != 0 or len(output.partner_2_response.action_scripts) != 0:
            errors.append(f"[{sample_id}] При high action_scripts должны быть пустыми")
    else:
        val_err_p1 = validate_partner_card(output.partner_1_response, is_high_risk=False, sparse=is_sparse_p1)
        for err in val_err_p1:
            errors.append(f"[{sample_id} - P1] {err}")

        val_err_p2 = validate_partner_card(output.partner_2_response, is_high_risk=False, sparse=is_sparse_p2)
        for err in val_err_p2:
            errors.append(f"[{sample_id} - P2] {err}")

        val_err_shared = validate_shared_summary(output.shared_summary, is_high_risk=False)
        for err in val_err_shared:
            errors.append(f"[{sample_id} - Shared] {err}")

        # Проверка согласованности единого ритуала
        p1_s2 = output.partner_1_response.action_scripts[1].text if len(output.partner_1_response.action_scripts) >= 2 else ""
        p2_s2 = output.partner_2_response.action_scripts[1].text if len(output.partner_2_response.action_scripts) >= 2 else ""
        sh_adv = output.shared_summary.shared_advice or ""
        cons_errs = validate_ritual_consistency(
            p1_s2,
            p2_s2,
            sh_adv,
            ritual_unfit_p1=bool(output.partner_1_response.ritual_unfit),
            ritual_unfit_p2=bool(output.partner_2_response.ritual_unfit),
        )
        for err in cons_errs:
            errors.append(f"[{sample_id} - RitualConsistency] {err}")

    # Сбор всех текстов
    p1_card_full = " ".join([
        output.partner_1_response.validation,
        output.partner_1_response.partner_perspective,
        output.partner_1_response.blind_spot,
        " ".join(s.text for s in output.partner_1_response.action_scripts),
    ])
    p2_card_full = " ".join([
        output.partner_2_response.validation,
        output.partner_2_response.partner_perspective,
        output.partner_2_response.blind_spot,
        " ".join(s.text for s in output.partner_2_response.action_scripts),
    ])
    shared_full = " ".join([
        output.shared_summary.situation_overview,
        output.shared_summary.shared_advice,
        output.shared_summary.conversation_starter,
    ])
    all_output_text = f"{p1_card_full} {p2_card_full} {shared_full}"

    # Лексические утечки
    lexical_leaks_p1 = check_lexical_leakage(p1_raw, p2_raw, p1_card_full) if not is_high else []
    lexical_leaks_p2 = check_lexical_leakage(p2_raw, p1_raw, p2_card_full) if not is_high else []

    # Начало с «Возможно / Скорее всего / Бывает»
    softener_prefixes = ("возможно", "скорее всего", "бывает", "наверное", "похоже")
    pp1 = output.partner_1_response.partner_perspective.strip().lower()
    pp2 = output.partner_2_response.partner_perspective.strip().lower()
    p1_starts_softener = any(pp1.startswith(pfx) for pfx in softener_prefixes) if not is_high else False
    p2_starts_softener = any(pp2.startswith(pfx) for pfx in softener_prefixes) if not is_high else False

    # Опечатки и копирование из промпта
    unknown_words = find_unknown_words_in_text(all_output_text) if not is_high else []
    copied_prompt_phrases = check_copied_from_prompt(all_output_text)

    metadata["lexical_leaks_p1"] = lexical_leaks_p1
    metadata["lexical_leaks_p2"] = lexical_leaks_p2
    metadata["p1_starts_softener"] = p1_starts_softener
    metadata["p2_starts_softener"] = p2_starts_softener
    metadata["unknown_words"] = unknown_words
    metadata["copied_from_prompt"] = copied_prompt_phrases

    return errors, metadata


async def run_single_sample(
    provider: LLMProvider,
    sample: Dict[str, Any],
    target_model: Optional[str] = None,
    use_cache: bool = True,
) -> Tuple[List[str], Dict[str, Any]]:
    """Прогон одного кейса через полный пайплайн с выбранным провайдером."""
    sample_id = sample["id"]
    name = sample["name"]
    p1_text = sample.get("transcript") or sample["partner_1"]
    p2_text = sample.get("transcript_2") or sample["partner_2"]

    p1_bytes = p1_text.encode("utf-8")
    p2_bytes = p2_text.encode("utf-8")

    retry_log = []
    fallback_records = []
    tracker = {
        "total_tokens": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "calls": 0,
        "blocked_calls": 0,
    }
    leak_detected = False

    # ==========================================================================
    # Шаг A: Анализатор (кэш tests/.cache с разделением по provider и model)
    # ==========================================================================
    eff_model = target_model or provider.default_model
    cache_key = compute_analyzer_cache_key("text", p1_bytes, "text", p2_bytes, provider.provider_name, eff_model)
    analyzer_res = load_analyzer_cache(cache_key, CACHE_DIR) if use_cache else None

    if analyzer_res:
        retry_log.append("Analyzer loaded from tests/.cache")
    else:
        analyzer_contents = prepare_analyzer_contents(
            p1_kind="text",
            p1_bytes=p1_bytes,
            p2_kind="text",
            p2_bytes=p2_bytes,
        )
        analyzer_res = await call_analyzer(provider, analyzer_contents, model=target_model, tracker=tracker)
        if use_cache and analyzer_res.risk_level != "high":
            save_analyzer_cache(cache_key, analyzer_res, CACHE_DIR)

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

    p1_is_sparse = bool(sample.get("sparse")) or (len(p1_text.split()) < 20) or (analyzer_res.partner_1.sparse and len(p1_text.split()) < 30)
    p2_is_sparse = bool(sample.get("sparse")) or (len(p2_text.split()) < 20) or (analyzer_res.partner_2.sparse and len(p2_text.split()) < 30)

    if analyzer_res.risk_level == "high":
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
        )
    else:
        is_elevated = (analyzer_res.risk_level == "elevated")

        # Шаг B1: Карточка партнера 1 (по Лестнице фоллбэков)
        p1_card = await generate_partner_card_with_ladder(
            provider_or_client=provider,
            my_kind="text",
            my_bytes=p1_bytes,
            my_analysis=analyzer_res.partner_1,
            partner_hypothesis=analyzer_res.partner_2.hypothesis_for_other,
            agreed_ritual=analyzer_res.shared.agreed_ritual,
            risk_elevated=is_elevated,
            sparse=p1_is_sparse,
            partner_tag="partner_1",
            fallback_records=fallback_records,
            model=target_model,
            tracker=tracker,
        )

        # Шаг B2: Карточка партнера 2 (по Лестнице фоллбэков)
        p2_card = await generate_partner_card_with_ladder(
            provider_or_client=provider,
            my_kind="text",
            my_bytes=p2_bytes,
            my_analysis=analyzer_res.partner_2,
            partner_hypothesis=analyzer_res.partner_1.hypothesis_for_other,
            agreed_ritual=analyzer_res.shared.agreed_ritual,
            risk_elevated=is_elevated,
            sparse=p2_is_sparse,
            partner_tag="partner_2",
            fallback_records=fallback_records,
            model=target_model,
            tracker=tracker,
        )

        # Шаг C: Общий итог (по Лестнице фоллбэков)
        shared_card = await generate_shared_summary_with_ladder(
            provider_or_client=provider,
            shared_analysis=analyzer_res.shared,
            fallback_records=fallback_records,
            model=target_model,
            tracker=tracker,
        )

        # Проверка согласованности длительностей единого ритуала
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
            retry_log.append(f"Ritual consistency retry: {cons_errs}")
            dur_hint = analyzer_res.shared.agreed_ritual.duration_minutes if analyzer_res.shared.agreed_ritual else "из ритуала"
            retry_guidance = f"Используй точную длительность ({dur_hint} мин) из согласованного ритуала во втором скрипте."
            p1_durs = extract_durations(p1_s2_text)
            p2_durs = extract_durations(p2_s2_text)
            sh_durs = extract_durations(shared_card.shared_advice or "")
            if p1_durs != sh_durs and not p1_card.ritual_unfit:
                p1_card = await generate_partner_card_with_ladder(
                    provider_or_client=provider,
                    my_kind="text",
                    my_bytes=p1_bytes,
                    my_analysis=analyzer_res.partner_1,
                    partner_hypothesis=analyzer_res.partner_2.hypothesis_for_other,
                    agreed_ritual=analyzer_res.shared.agreed_ritual,
                    risk_elevated=is_elevated,
                    sparse=p1_is_sparse,
                    partner_tag="partner_1",
                    fallback_records=fallback_records,
                    guidance=retry_guidance,
                    model=target_model,
                    tracker=tracker,
                )
            if p2_durs != sh_durs and not p2_card.ritual_unfit:
                p2_card = await generate_partner_card_with_ladder(
                    provider_or_client=provider,
                    my_kind="text",
                    my_bytes=p2_bytes,
                    my_analysis=analyzer_res.partner_2,
                    partner_hypothesis=analyzer_res.partner_1.hypothesis_for_other,
                    agreed_ritual=analyzer_res.shared.agreed_ritual,
                    risk_elevated=is_elevated,
                    sparse=p2_is_sparse,
                    partner_tag="partner_2",
                    fallback_records=fallback_records,
                    guidance=retry_guidance,
                    model=target_model,
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
                rit_phrase = ""
                if analyzer_res.shared and analyzer_res.shared.agreed_ritual:
                    rit_phrase = analyzer_res.shared.agreed_ritual.ritual_phrase_we or analyzer_res.shared.agreed_ritual.format or ""
                if not rit_phrase:
                    rit_phrase = "делать 15-минутную паузу и обсуждать ситуацию без взаимных упрёков"
                det_script_text = f"Предлагаю попробовать новое правило: {rit_phrase}. Что скажешь?"
                if len(p1_card.action_scripts) >= 2:
                    p1_card.action_scripts[1].text = det_script_text
                if len(p2_card.action_scripts) >= 2:
                    p2_card.action_scripts[1].text = det_script_text
                retry_log.append("Ritual duration deterministic fallback applied")

        safety_note_text = ""
        if is_elevated:
            safety_note_text = get_elevated_risk_message()
            p1_card.safety_note = safety_note_text
            p2_card.safety_note = safety_note_text

        # Разнообразие зачинов partner_perspective (Этап 3.4, 3.9)
        diversify_partner_perspectives(p1_card, p2_card)

        mediator_output = MediatorOutput(
            risk_level=analyzer_res.risk_level,
            partner_1_response=p1_card,
            partner_2_response=p2_card,
            shared_summary=shared_card,
            safety_note=safety_note_text,
        )

        # ======================================================================
        # Шаг D: Проверка утечек конфиденциальности (Leak Checker)
        # ==========================================================================
        leak_contents = prepare_leak_checker_contents(
            p1_kind="text",
            p1_bytes=p1_bytes,
            p2_kind="text",
            p2_bytes=p2_bytes,
            secrets_p1=analyzer_res.partner_1.secrets,
            secrets_p2=analyzer_res.partner_2.secrets,
            generated_analysis=mediator_output,
        )
        leak_res = await call_leak_checker(provider, leak_contents, model=target_model, tracker=tracker)

        if leak_res.leak:
            leak_detected = True
            loc = leak_res.location or "unknown"
            retry_log.append(f"Leak detected in {loc}: {leak_res.reason}")
            leak_guidance = (
                f"ВНИМАНИЕ: В прошлой попытке обнаружена утечка в '{loc}' ({leak_res.reason}). "
                "Перепиши строго более общо, соблюдая информационный барьер и не раскрывая чужих секретов."
            )
            if "partner_1" in loc:
                mediator_output.partner_1_response = await generate_partner_card_with_ladder(
                    provider_or_client=provider,
                    my_kind="text",
                    my_bytes=p1_bytes,
                    my_analysis=analyzer_res.partner_1,
                    partner_hypothesis=analyzer_res.partner_2.hypothesis_for_other,
                    risk_elevated=is_elevated,
                    sparse=p1_is_sparse,
                    guidance=leak_guidance,
                    model=target_model,
                    tracker=tracker,
                )
            elif "partner_2" in loc:
                mediator_output.partner_2_response = await generate_partner_card_with_ladder(
                    provider_or_client=provider,
                    my_kind="text",
                    my_bytes=p2_bytes,
                    my_analysis=analyzer_res.partner_2,
                    partner_hypothesis=analyzer_res.partner_1.hypothesis_for_other,
                    risk_elevated=is_elevated,
                    sparse=p2_is_sparse,
                    guidance=leak_guidance,
                    model=target_model,
                    tracker=tracker,
                )
            elif "shared" in loc:
                mediator_output.shared_summary = await generate_shared_summary_with_ladder(
                    provider_or_client=provider,
                    shared_analysis=analyzer_res.shared,
                    fallback_records=fallback_records,
                    model=target_model,
                    tracker=tracker,
                )

            # Вторая проверка утечки
            second_leak = await call_leak_checker(
                provider,
                prepare_leak_checker_contents(
                    p1_kind="text",
                    p1_bytes=p1_bytes,
                    p2_kind="text",
                    p2_bytes=p2_bytes,
                    secrets_p1=analyzer_res.partner_1.secrets,
                    secrets_p2=analyzer_res.partner_2.secrets,
                    generated_analysis=mediator_output,
                ),
                model=target_model,
                tracker=tracker,
            )
            if second_leak.leak:
                loc2 = second_leak.location or loc
                retry_log.append(f"Leak persisted: applying fallback for {loc2}")
                mediator_output = apply_fallback_to_field(mediator_output, loc2)
                fallback_records.append({"field": loc2, "reason": "leak"})

    # Финальная проверка качества
    errors, quality_meta = validate_output_quality(
        sample_id,
        mediator_output,
        p1_text,
        p2_text,
        is_sparse_p1=p1_is_sparse,
        is_sparse_p2=p2_is_sparse,
    )

    is_blocked_case = (mediator_output.risk_level == "high" and any("refusal" in str(r).lower() or "blocked" in str(r).lower() for r in analyzer_res.risk_reasons))

    result_data = {
        "id": sample_id,
        "name": name,
        "expected_risk": sample.get("expected_risk"),
        "actual_risk": mediator_output.risk_level,
        "analyzer_reasons": analyzer_res.risk_reasons,
        "secrets_p1": analyzer_res.partner_1.secrets,
        "secrets_p2": analyzer_res.partner_2.secrets,
        "retries": retry_log,
        "fallback_records": fallback_records,
        "mediator_output": mediator_output.model_dump(),
        "lexical_leaks_p1": quality_meta.get("lexical_leaks_p1", []),
        "lexical_leaks_p2": quality_meta.get("lexical_leaks_p2", []),
        "p1_starts_softener": quality_meta.get("p1_starts_softener", False),
        "p2_starts_softener": quality_meta.get("p2_starts_softener", False),
        "unknown_words": quality_meta.get("unknown_words", []),
        "copied_from_prompt": quality_meta.get("copied_from_prompt", []),
        "leak_guard_triggered": leak_detected,
        "is_blocked": is_blocked_case,
        "api_calls": tracker["calls"],
        "tokens_total": tracker["total_tokens"],
        "tokens_prompt": tracker["prompt_tokens"],
        "tokens_completion": tracker["completion_tokens"],
        "errors": errors,
    }

    return errors, result_data


def print_clean_readable_sample(res: Dict[str, Any]):
    """Печатает разбор отдельным структурированным блоком для удобного чтения человеком."""
    print("=" * 80)
    print(f"КЕЙС: {res['id']} — {res['name']}")
    print(f"Оценка риска: {res['actual_risk'].upper()} (ожидалось: {res.get('expected_risk')})")

    out = res["mediator_output"]
    p1 = out.get("partner_1_response", {})
    p2 = out.get("partner_2_response", {})
    sh = out.get("shared_summary", {})

    if out.get("risk_level") == "high":
        print("\n⚠️ ВЫСОКИЙ РИСК: Выдано экстренное сообщение безопасности:")
        print(f"  {out.get('safety_note')}")
    else:
        print("\n--- РАЗБОР ДЛЯ ПАРТНЁРА 1 ---")
        print(f"• Понимание (validation):\n  {p1.get('validation')}")
        print(f"• Взгляд партнёра (partner_perspective):\n  {p1.get('partner_perspective')}")
        print(f"• Точка роста (blind_spot):\n  {p1.get('blind_spot')}")
        print("• Скрипты действий:")
        for idx, s in enumerate(p1.get("action_scripts", [])):
            hint = DEFAULT_SCRIPT_HINTS[idx] if idx < len(DEFAULT_SCRIPT_HINTS) else ""
            print(f"  [{s.get('label')}] «{s.get('text')}»\n    Зачем: {hint}")

        print("\n--- РАЗБОР ДЛЯ ПАРТНЁРА 2 ---")
        print(f"• Понимание (validation):\n  {p2.get('validation')}")
        print(f"• Взгляд партнёра (partner_perspective):\n  {p2.get('partner_perspective')}")
        print(f"• Точка роста (blind_spot):\n  {p2.get('blind_spot')}")
        print("• Скрипты действий:")
        for idx, s in enumerate(p2.get("action_scripts", [])):
            hint = DEFAULT_SCRIPT_HINTS[idx] if idx < len(DEFAULT_SCRIPT_HINTS) else ""
            print(f"  [{s.get('label')}] «{s.get('text')}»\n    Зачем: {hint}")

        print("\n--- ОБЩИЙ ИТОГ ДЛЯ ПАРЫ (SHARED SUMMARY) ---")
        print(f"• Общая динамика:\n  {sh.get('situation_overview')}")
        print(f"• Общий ритуал/совет:\n  {sh.get('shared_advice')}")
        print(f"• Стартовая фраза:\n  «{sh.get('conversation_starter')}»")

    if res.get("fallback_records"):
        print(f"\n📦 Фоллбэки: {res['fallback_records']}")

    if res.get("unknown_words"):
        print(f"\n🔍 Неизвестные слова / опечатки (pymorphy3): {res['unknown_words']}")

    if res.get("copied_from_prompt"):
        print(f"\n⚠️ Фразы из промпта: {res['copied_from_prompt']}")

    print(f"\n📊 Токены: {res.get('tokens_total', 0)} (prompt={res.get('tokens_prompt', 0)}, comp={res.get('tokens_completion', 0)}) | API-вызовы: {res.get('api_calls', 0)}")

    if res.get("errors"):
        print("\n❌ ОШИБКИ ВАЛИДАЦИИ:")
        for err in res["errors"]:
            print(f"  {err}")

    print("=" * 80 + "\n")


def compute_metrics(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Вычисляет сводные метрики качества и эффективности прогона."""
    valid_cases = [r for r in results if "error" not in r]
    total_cases = len(valid_cases)
    if total_cases == 0:
        return {}

    high_risk_cases = sum(1 for r in valid_cases if r.get("actual_risk") == "high")
    blocked_cases = sum(1 for r in valid_cases if r.get("is_blocked"))
    successful_cards = sum(1 for r in valid_cases if r.get("actual_risk") != "high")
    cases_with_fallbacks = sum(1 for r in valid_cases if len(r.get("fallback_records", [])) > 0)
    leak_guard_triggers = sum(1 for r in valid_cases if r.get("leak_guard_triggered"))

    total_tokens = sum(r.get("tokens_total", 0) for r in valid_cases)
    total_prompt_tokens = sum(r.get("tokens_prompt", 0) for r in valid_cases)
    total_comp_tokens = sum(r.get("tokens_completion", 0) for r in valid_cases)
    total_calls = sum(r.get("api_calls", 0) for r in valid_cases)

    avg_tokens = total_tokens / total_cases
    avg_calls = total_calls / total_cases

    # Подсчет полей и фоллбэков
    total_perspectives = 0
    perspectives_softener = 0
    total_ritual_cases = 0
    ritual_mismatches = 0
    all_unknown_words = []
    all_copied_phrases = []

    for r in valid_cases:
        if r.get("actual_risk") != "high":
            total_ritual_cases += 1
            mo = r.get("mediator_output", {})
            p1_r = mo.get("partner_1_response", {})
            p2_r = mo.get("partner_2_response", {})
            sh_r = mo.get("shared_summary", {})
            s1 = p1_r.get("action_scripts", [])
            s2 = p2_r.get("action_scripts", [])
            p1_s2 = s1[1]["text"] if len(s1) > 1 and isinstance(s1[1], dict) else ""
            p2_s2 = s2[1]["text"] if len(s2) > 1 and isinstance(s2[1], dict) else ""
            sh_adv = sh_r.get("shared_advice", "") if sh_r else ""
            if p1_s2 and p2_s2:
                rit_mismatch = bool(validate_ritual_consistency(
                    p1_s2,
                    p2_s2,
                    sh_adv,
                    ritual_unfit_p1=bool(p1_r.get("ritual_unfit")),
                    ritual_unfit_p2=bool(p2_r.get("ritual_unfit")),
                ))
            else:
                rit_mismatch = any("RitualConsistency" in str(e) for e in r.get("errors", []))
            if rit_mismatch:
                ritual_mismatches += 1

            total_perspectives += 2
            if r.get("p1_starts_softener"):
                perspectives_softener += 1
            if r.get("p2_starts_softener"):
                perspectives_softener += 1

        all_unknown_words.extend(r.get("unknown_words", []))
        all_copied_phrases.extend(r.get("copied_from_prompt", []))

    softener_rate = (perspectives_softener / total_perspectives * 100) if total_perspectives > 0 else 0.0
    ritual_mismatch_rate = (ritual_mismatches / total_ritual_cases * 100) if total_ritual_cases > 0 else 0.0

    return {
        "total_cases": total_cases,
        "high_risk_cases": high_risk_cases,
        "blocked_cases": blocked_cases,
        "successful_cards": successful_cards,
        "cases_with_fallbacks": cases_with_fallbacks,
        "leak_guard_triggers": leak_guard_triggers,
        "total_tokens": total_tokens,
        "total_prompt_tokens": total_prompt_tokens,
        "total_comp_tokens": total_comp_tokens,
        "avg_tokens": avg_tokens,
        "total_calls": total_calls,
        "avg_calls": avg_calls,
        "softener_rate": softener_rate,
        "ritual_mismatch_rate": ritual_mismatch_rate,
        "unknown_words_count": len(all_unknown_words),
        "unknown_words_list": sorted(list(set(all_unknown_words))),
        "copied_phrases_count": len(all_copied_phrases),
    }


def compare_result_files(file1: Path, file2: Path) -> None:
    """Сравнивает два файла результатов по ключевым метрикам (Этап 3.5)."""
    with open(file1, "r", encoding="utf-8") as f:
        data1 = json.load(f)
    with open(file2, "r", encoding="utf-8") as f:
        data2 = json.load(f)

    m1 = compute_metrics(data1)
    m2 = compute_metrics(data2)

    print("\n" + "=" * 90)
    print(f"📊 СРАВНИТЕЛЬНЫЙ АНАЛИЗ ПРОГОНОВ (Этап 3.5)")
    print(f"Файл 1: {file1.name}")
    print(f"Файл 2: {file2.name}")
    print("=" * 90)
    print(f"{'Метрика':<45} | {'Файл 1':<20} | {'Файл 2':<20}")
    print("-" * 90)
    print(f"{'Всего кейсов':<45} | {m1.get('total_cases', 0):<20} | {m2.get('total_cases', 0):<20}")
    print(f"{'Успешных карточек':<45} | {m1.get('successful_cards', 0):<20} | {m2.get('successful_cards', 0):<20}")
    print(f"{'Высокий риск (High Risk)':<45} | {m1.get('high_risk_cases', 0):<20} | {m2.get('high_risk_cases', 0):<20}")
    print(f"{'Заблокировано (Blocked / Refusal)':<45} | {m1.get('blocked_cases', 0):<20} | {m2.get('blocked_cases', 0):<20}")
    print(f"{'Кейсов с фоллбэками':<45} | {m1.get('cases_with_fallbacks', 0):<20} | {m2.get('cases_with_fallbacks', 0):<20}")
    print(f"{'Срабатываний Leak Guard':<45} | {m1.get('leak_guard_triggers', 0):<20} | {m2.get('leak_guard_triggers', 0):<20}")
    print(f"{'Несовпадение ритуала':<45} | {m1.get('ritual_mismatch_rate', 0):.1f}%{'':<15} | {m2.get('ritual_mismatch_rate', 0):.1f}%")
    print(f"{'Доля «Возможно/Скорее всего/Бывает»':<45} | {m1.get('softener_rate', 0):.1f}%{'':<15} | {m2.get('softener_rate', 0):.1f}%")
    print(f"{'Среднее число API-вызовов на кейс':<45} | {m1.get('avg_calls', 0):.1f}{'':<16} | {m2.get('avg_calls', 0):.1f}")
    print(f"{'Среднее число токенов на кейс':<45} | {m1.get('avg_tokens', 0):.0f}{'':<16} | {m2.get('avg_tokens', 0):.0f}")
    print(f"{'Всего токенов':<45} | {m1.get('total_tokens', 0):<20} | {m2.get('total_tokens', 0):<20}")
    print(f"{'Опечатки / неизвестные слова (pymorphy3)':<45} | {m1.get('unknown_words_count', 0):<20} | {m2.get('unknown_words_count', 0):<20}")
    print(f"{'Фразы из промпта (copied_from_prompt)':<45} | {m1.get('copied_phrases_count', 0):<20} | {m2.get('copied_phrases_count', 0):<20}")
    print("=" * 90 + "\n")


def dry_validate(file_path: Path) -> Tuple[Dict[str, Any], List[str]]:
    """
    Валидация уже сохраненного JSON-отчета без обращения к LLM и сети (Блок F).
    Проверяет структуру, валидаторы карточек, общих итогов, ритуалов, скриптов,
    и вычисляет сводные метрики качества.
    """
    if not file_path.exists():
        print(f"❌ Файл для dry-validate не найден: {file_path}")
        sys.exit(1)

    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        print(f"❌ Ошибка: ожидался список результатов кейсов, получено {type(data)}")
        sys.exit(1)

    print("\n" + "=" * 80)
    print(f"🔍 DRY-VALIDATE: Валидация сохраненных результатов")
    print(f"Файл: {file_path.name} | Всего кейсов в отчете: {len(data)}")
    print("=" * 80)

    all_errors: List[str] = []
    for item in data:
        s_id = item.get("id", "unknown")
        name = item.get("name", "")
        print(f"\nКейс {s_id}: {name}")

        if "error" in item:
            err = f"Кейс {s_id} содержит ошибку выполнения: {item['error']}"
            all_errors.append(err)
            print(f"  ❌ {err}")
            continue

        mediator_out = item.get("mediator_output", {})
        risk_level = mediator_out.get("risk_level", item.get("actual_risk", "normal"))

        # Для кейсов normal/elevated валидируем схемы и правила
        if risk_level != "high":
            p1_resp = mediator_out.get("partner_1_response")
            p2_resp = mediator_out.get("partner_2_response")
            sh_resp = mediator_out.get("shared_summary")

            if p1_resp:
                try:
                    p1_obj = PartnerResponse(**p1_resp)
                    p1_obj = sanitize_card_minor_banned_words(p1_obj)
                    p1_errs = validate_partner_card(p1_obj)
                    all_errors.extend([f"[{s_id} P1] {e}" for e in p1_errs])
                except Exception as ex:
                    all_errors.append(f"[{s_id} P1 Schema] {ex}")

            if p2_resp:
                try:
                    p2_obj = PartnerResponse(**p2_resp)
                    p2_obj = sanitize_card_minor_banned_words(p2_obj)
                    p2_errs = validate_partner_card(p2_obj)
                    all_errors.extend([f"[{s_id} P2] {e}" for e in p2_errs])
                except Exception as ex:
                    all_errors.append(f"[{s_id} P2 Schema] {ex}")

            if sh_resp:
                try:
                    sh_obj = SharedSummary(**sh_resp)
                    sh_obj = sanitize_shared_minor_banned_words(sh_obj)
                    sh_errs = validate_shared_summary(sh_obj)
                    all_errors.extend([f"[{s_id} Shared] {e}" for e in sh_errs])
                except Exception as ex:
                    all_errors.append(f"[{s_id} Shared Schema] {ex}")

            # Проверка консистентности ритуала
            if p1_resp and p2_resp:
                s1 = p1_resp.get("action_scripts", [])
                s2 = p2_resp.get("action_scripts", [])
                try:
                    p1_s2 = s1[1]["text"] if len(s1) > 1 and isinstance(s1[1], dict) else ""
                    p2_s2 = s2[1]["text"] if len(s2) > 1 and isinstance(s2[1], dict) else ""
                    sh_adv = sh_resp.get("shared_advice", "") if sh_resp else ""
                    rit_errs = validate_ritual_consistency(
                        p1_s2,
                        p2_s2,
                        sh_adv,
                        ritual_unfit_p1=bool(p1_resp.get("ritual_unfit")),
                        ritual_unfit_p2=bool(p2_resp.get("ritual_unfit")),
                    )
                    all_errors.extend([f"[{s_id} Ritual] {e}" for e in rit_errs])
                except Exception:
                    pass

        # Ошибки, зафиксированные при прогоне
        recorded_errs = item.get("errors", [])
        if recorded_errs:
            for re_err in recorded_errs:
                if "RitualConsistency" in re_err and p1_resp and p2_resp:
                    s1 = p1_resp.get("action_scripts", [])
                    s2 = p2_resp.get("action_scripts", [])
                    p1_s2 = s1[1]["text"] if len(s1) > 1 and isinstance(s1[1], dict) else ""
                    p2_s2 = s2[1]["text"] if len(s2) > 1 and isinstance(s2[1], dict) else ""
                    sh_adv = sh_resp.get("shared_advice", "") if sh_resp else ""
                    if not validate_ritual_consistency(
                        p1_s2,
                        p2_s2,
                        sh_adv,
                        ritual_unfit_p1=bool(p1_resp.get("ritual_unfit")),
                        ritual_unfit_p2=bool(p2_resp.get("ritual_unfit")),
                    ):
                        continue
                tag = f"[{s_id} Recorded] {re_err}"
                if tag not in all_errors:
                    all_errors.append(tag)

        case_errors = [e for e in all_errors if f"[{s_id}" in e]
        if case_errors:
            print(f"  ⚠️ Замечания ({len(case_errors)}):")
            for ce in case_errors[:3]:
                print(f"    - {ce}")
            if len(case_errors) > 3:
                print(f"    ... и еще {len(case_errors) - 3}")
        else:
            print(f"  ✅ Валидация пройдена без замечаний")

    metrics = compute_metrics(data)
    print("\n" + "=" * 80)
    print(f"📊 МЕТРИКИ ФАЙЛА {file_path.name}:")
    print(f"• Всего кейсов: {metrics.get('total_cases', 0)}")
    print(f"• Успешных карточек: {metrics.get('successful_cards', 0)}")
    print(f"• Высокий риск / Блокировка: {metrics.get('high_risk_cases', 0)} (отказов: {metrics.get('blocked_cases', 0)})")
    print(f"• Кейсов с фоллбэками: {metrics.get('cases_with_fallbacks', 0)}")
    print(f"• Срабатываний Leak Guard: {metrics.get('leak_guard_triggers', 0)}")
    print(f"• Всего токенов: {metrics.get('total_tokens', 0):,} (в среднем: {metrics.get('avg_tokens', 0):.0f})")
    print(f"• Среднее число API-вызовов: {metrics.get('avg_calls', 0):.1f}")
    print(f"• Доля смягчителей в partner_perspective: {metrics.get('softener_rate', 0):.1f}%")
    print(f"• Несовпадение ритуала: {metrics.get('ritual_mismatch_rate', 0):.1f}%")
    print(f"• Опечаток/неизвестных слов: {metrics.get('unknown_words_count', 0)}")
    print("=" * 80)

    if all_errors:
        print(f"\n⚠️ ИТОГО замечаний валидатора: {len(all_errors)}")
    else:
        print(f"\n🎉 ВСЕ КЕЙСЫ В ФАЙЛЕ ПОЛНОСТЬЮ ВАЛИДНЫ!")

    return metrics, all_errors


async def main():
    parser = argparse.ArgumentParser(description="Запуск прогона синтетических ссор (Этап 3.5: GigaChat / Gemini)")
    parser.add_argument("--provider", type=str, default=None, help="LLM-провайдер: gigachat | gemini (по умолчанию из .env)")
    parser.add_argument("--model", type=str, default=None, help="Модель LLM (например GigaChat-3-Ultra, GigaChat-Pro, gemini-2.5-flash)")
    parser.add_argument("--limit", type=int, default=None, help="Ограничить количество кейсов")
    parser.add_argument("--cases", type=str, default=None, help="Выборочные кейсы через запятую, например '7,8,6,3'")
    parser.add_argument("--runs", type=int, default=1, help="Количество повторных прогонов каждого кейса (по умолчанию 1)")
    parser.add_argument("--resume", action="store_true", help="Пропустить уже посчитанные кейсы")
    parser.add_argument("--sleep", type=float, default=0.0, help="Пауза между кейсами в секундах")
    parser.add_argument("--no-cache", action="store_true", help="Не использовать кэш Шага A")
    parser.add_argument("--compare", nargs="*", default=None, help="Сравнение файлов: --compare file1.json file2.json (или сохранить out_<provider>_<model>_<ts>.json)")
    parser.add_argument("--dry-validate", type=str, default=None, help="Проверить уже сохранённый JSON без обращений к ИИ")
    args = parser.parse_args()

    # Режим dry-validate (без обращения к сети и ИИ)
    if args.dry_validate:
        dry_validate(Path(args.dry_validate))
        return

    # Режим сравнения двух файлов
    if args.compare and len(args.compare) == 2:
        compare_result_files(Path(args.compare[0]), Path(args.compare[1]))
        return

    provider_name = args.provider or settings.LLM_PROVIDER
    provider = get_provider(provider_name=provider_name, model=args.model)
    active_model = args.model or provider.default_model

    print(f"\n================================================================================")
    print(f"🚀 ЗАПУСК ПРОГОНА СИНТЕТИЧЕСКИХ ССОР (Этап 3.5)")
    print(f"Провайдер: {provider.provider_name.upper()} | Модель: {active_model}")
    allow_cache = (os.getenv("TEST_CACHE") == "1") and not args.no_cache
    print(f"Кэш Шага A (TEST_CACHE=1): {'ВКЛ' if allow_cache else 'ВЫКЛ'} | Пауза: {args.sleep}с")
    print(f"================================================================================\n")

    if not SAMPLES_FILE.exists():
        print(f"❌ Файл с кейсами не найден: {SAMPLES_FILE}")
        sys.exit(1)

    with open(SAMPLES_FILE, "r", encoding="utf-8") as f:
        samples_raw = json.load(f)

    # Приоритетная сортировка кейсов
    def sort_key(s):
        sid = s["id"]
        for idx, p in enumerate(PRIORITY_ORDER):
            if sid == p or sid.startswith(p):
                return idx
        return 999

    samples = sorted(samples_raw, key=sort_key)

    if args.cases:
        selected_cases = [c.strip() for c in args.cases.split(",") if c.strip()]
        samples = [
            s for s in samples
            if any(s["id"] == c or s["id"].startswith(f"{c}_") for c in selected_cases)
        ]
        print(f"🎯 Выбрано кейсов по фильтру --cases ({args.cases}): {len(samples)}")

    if args.limit:
        samples = samples[: args.limit]

    if args.runs > 1:
        expanded_samples = []
        for r_num in range(1, args.runs + 1):
            for s in samples:
                s_copy = dict(s)
                s_copy["id"] = f"{s['id']}_run{r_num}"
                s_copy["name"] = f"{s['name']} (прогон {r_num}/{args.runs})"
                expanded_samples.append(s_copy)
        samples = expanded_samples
        print(f"🔁 Количество прогонов (--runs): {args.runs}. Всего запусков: {len(samples)}")

    latest_out = Path(__file__).resolve().parent / "samples_results.json"
    resumed_dict: Dict[str, Dict[str, Any]] = {}
    if latest_out.exists() and args.resume:
        try:
            with open(latest_out, "r", encoding="utf-8") as f:
                prev_data = json.load(f)
                if isinstance(prev_data, list):
                    for item in prev_data:
                        if isinstance(item, dict) and "id" in item:
                            resumed_dict[item["id"]] = item
            print(f"🔄 Режим --resume: найдено {len(resumed_dict)} сохранённых результатов")
        except Exception as e:
            print(f"⚠️ Не удалось прочитать samples_results.json: {e}")

    all_results = []
    total_errors = []

    for i, sample in enumerate(samples, 1):
        s_id = sample["id"]
        if args.resume and s_id in resumed_dict and "error" not in resumed_dict[s_id]:
            print(f"[{i}/{len(samples)}] Пропуск кейса: {s_id} ({sample['name']}) [Загружен из samples_results.json]")
            res_data = resumed_dict[s_id]
            all_results.append(res_data)
            total_errors.extend(res_data.get("errors", []))
        else:
            print(f"[{i}/{len(samples)}] Обработка кейса: {s_id} ({sample['name']})...")
            try:
                errs, res_data = await run_single_sample(
                    provider=provider,
                    sample=sample,
                    target_model=active_model,
                    use_cache=allow_cache,
                )
                all_results.append(res_data)
                total_errors.extend(errs)
                print_clean_readable_sample(res_data)
            except Exception as e:
                print(f"❌ Сбой при обработке кейса {s_id}: {e}\n")
                res_data = {
                    "id": s_id,
                    "name": sample["name"],
                    "error": str(e),
                    "api_calls": 0,
                    "tokens_total": 0,
                }
                all_results.append(res_data)

            if args.sleep > 0 and i < len(samples):
                await asyncio.sleep(args.sleep)

    # Сохранение обновленного samples_results.json
    merged_results = dict(resumed_dict)
    for r in all_results:
        merged_results[r["id"]] = r

    with open(latest_out, "w", encoding="utf-8") as f:
        json.dump(list(merged_results.values()), f, ensure_ascii=False, indent=2)
    print(f"💾 Последние результаты обновлены в: {latest_out}")

    # Сохранение версионного файла tests/out_<provider>_<model>_<дата>.json
    clean_model_name = active_model.replace("/", "_")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_versioned_path = Path(__file__).resolve().parent / f"out_{provider.provider_name}_{clean_model_name}_{ts}.json"
    with open(out_versioned_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    print(f"💾 Версионный отчет сохранен в: {out_versioned_path}")

    # Сводка метрик
    metrics = compute_metrics(all_results)

    print("\n" + "=" * 80)
    print(f"📊 ИТОГОВЫЕ МЕТРИКИ ПРОГОНА: {provider.provider_name.upper()} ({active_model})")
    print(f"1. Результаты кейсов (всего {metrics.get('total_cases', 0)}):")
    print(f"   • Успешно сформированных карточек: {metrics.get('successful_cards', 0)}")
    print(f"   • Заблокировано / Высокий риск: {metrics.get('high_risk_cases', 0)} (в т.ч. отказов модели: {metrics.get('blocked_cases', 0)})")
    print(f"   • Потребовало фоллбэков: {metrics.get('cases_with_fallbacks', 0)}")
    print(f"   • Срабатываний Leak Guard: {metrics.get('leak_guard_triggers', 0)}")
    print(f"2. Токены и вызовы:")
    print(f"   • Всего токенов: {metrics.get('total_tokens', 0):,}")
    print(f"   • В среднем токенов на кейс: {metrics.get('avg_tokens', 0):.0f}")
    print(f"   • В среднем API-вызовов на кейс: {metrics.get('avg_calls', 0):.1f}")
    print(f"3. Качество текстов:")
    print(f"   • Доля «Возможно/Скорее всего/Бывает» в partner_perspective: {metrics.get('softener_rate', 0):.1f}%")
    print(f"   • Несовпадение длительностей ритуала: {metrics.get('ritual_mismatch_rate', 0):.1f}%")
    print(f"   • Неизвестные слова / опечатки (pymorphy3): {metrics.get('unknown_words_count', 0)}")
    if metrics.get("unknown_words_list"):
        print(f"     Список: {metrics.get('unknown_words_list')[:10]}")
    print(f"   • Копирование фраз из промпта: {metrics.get('copied_phrases_count', 0)}")
    print("=" * 80)

    if total_errors:
        print(f"\n⚠️  Всего замечаний валидатора: {len(total_errors)}")
        for e in total_errors[:10]:
            print(f"  - {e}")
        if len(total_errors) > 10:
            print(f"  ... и еще {len(total_errors) - 10} замечаний")
    else:
        print("\n🎉 ВСЕ КЕЙСЫ УСПЕШНО ПРОШЛИ АВТОВАЛИДАЦИЮ!")


if __name__ == "__main__":
    asyncio.run(main())
