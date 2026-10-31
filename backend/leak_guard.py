"""
Детерминированный Leak Guard на основе морфологического анализа лемм (pymorphy3).
Защищает информационный барьер между партнерами, проверяя отсутствие фактов и секретов
другого партнера в тексте персональной карточки и общего итога.
"""

import re
from typing import Set, List, Optional
import pymorphy3

_morph = pymorphy3.MorphAnalyzer()

STOP_WORDS = {
    "просто", "когда", "чтобы", "сразу", "почему", "зачем", "потом",
    "очень", "совсем", "давай", "сейчас", "тогда", "быть", "сказать",
    "говорить", "хотеть", "мочь", "делать", "думать", "знать", "идти",
    "это", "свой", "твой", "мой", "наш", "ваш", "тот", "этот", "весь",
    "один", "другой", "который", "какой", "такой", "себя", "себе", "тобой",
    "тебе", "тебя", "меня", "мне", "мной", "нами", "вами", "ними", "них",
    "если", "даже", "тоже", "только", "ведь", "потому", "поэтому", "вместе",
    "партнер", "партнера", "партнеру", "отношения", "чувство", "ситуация",
    "время", "день", "человек", "слово", "разговор", "вопрос", "дело",
}

ALLOWED_POS = {"NOUN", "VERB", "INFN", "NUMR"}


def extract_content_lemmas(text: str) -> Set[str]:
    """
    Извлекает нормализованные леммы значимых частей речи (существительные, глаголы, числа),
    исключая стоп-слова и короткие токены.
    """
    if not text:
        return set()
    lemmas: Set[str] = set()
    raw_words = re.findall(r"[а-яёa-z0-9]+", text.lower())
    for w in raw_words:
        if w in STOP_WORDS or len(w) < 3:
            continue
        p = _morph.parse(w)[0]
        pos = p.tag.POS
        lemma = p.normal_form
        if lemma in STOP_WORDS or len(lemma) < 3:
            continue
        if pos in ALLOWED_POS:
            lemmas.add(lemma)
    return lemmas


def check_lemma_overlap(
    candidate_text: str,
    forbidden_texts: List[str],
    allowed_texts: List[str],
) -> Set[str]:
    """
    Проверяет пересечение лемм текста кандидата с запрещенными источниками за вычетом разрешенных:
    forbidden = леммы(forbidden_texts) - леммы(allowed_texts)
    leak = леммы(candidate_text) & forbidden
    """
    candidate_lemmas = extract_content_lemmas(candidate_text)
    if not candidate_lemmas:
        return set()

    forbidden_combined = " ".join(t for t in forbidden_texts if t)
    forbidden_lemmas = extract_content_lemmas(forbidden_combined)

    allowed_combined = " ".join(t for t in allowed_texts if t)
    allowed_lemmas = extract_content_lemmas(allowed_combined)

    strictly_forbidden = forbidden_lemmas - allowed_lemmas
    return candidate_lemmas & strictly_forbidden


def check_card_lemma_leaks(
    card_text: str,
    other_private_facts: List[str],
    other_secrets: List[str],
    recipient_raw: str,
    recipient_facts: List[str],
    facts_known_to_both: Optional[List[str]] = None,
) -> Set[str]:
    """
    Проверка персональной карточки:
    Запрещено: приватные факты и тайны другого партнера.
    Разрешено: собственный текст получателя, его факты и факты, известные обоим.
    """
    forbidden = (other_private_facts or []) + (other_secrets or [])
    allowed = [recipient_raw] + (recipient_facts or []) + (facts_known_to_both or [])
    return check_lemma_overlap(card_text, forbidden, allowed)


def check_shared_lemma_leaks(
    shared_text: str,
    all_private_facts: List[str],
    all_secrets: List[str],
    facts_known_to_both: Optional[List[str]] = None,
) -> Set[str]:
    """
    Проверка общего итога:
    Запрещено: приватные факты обоих партнеров и любые тайны.
    Разрешено: только факты, известные обоим (facts_known_to_both / neutral_topic).
    """
    forbidden = (all_private_facts or []) + (all_secrets or [])
    allowed = facts_known_to_both or []
    return check_lemma_overlap(shared_text, forbidden, allowed)
