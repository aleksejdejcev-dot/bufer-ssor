"""
Тесты валидатора качества текстов медиации (backend/validators.py).
"""

import pytest
from schemas import PartnerResponse, SharedSummary, ActionScriptItem
from validators import (
    count_sentences,
    validate_partner_card,
    validate_shared_summary,
    validate_ritual_consistency,
    find_script_dishonesty,
    GLOBAL_FORBIDDEN_PATTERNS,
    SHARED_FORBIDDEN_PATTERNS,
)
from config.fallbacks import (
    FALLBACK_VALIDATION,
    FALLBACK_PARTNER_PERSPECTIVE,
    FALLBACK_BLIND_SPOT,
    FALLBACK_ACTION_SCRIPTS,
    FALLBACK_SHARED_SUMMARY,
)


def test_count_sentences():
    assert count_sentences("Одно предложение.") == 1
    assert count_sentences("Первое! Второе? Третье… Четвертое.") == 4
    assert count_sentences("") == 0
    assert count_sentences("Просто текст без точек") == 1


def test_fallbacks_pass_validation():
    """Проверяет, что все тексты из fallbacks.py строго удовлетворяют валидатору."""
    card = PartnerResponse(
        validation=FALLBACK_VALIDATION,
        partner_perspective=FALLBACK_PARTNER_PERSPECTIVE,
        blind_spot=FALLBACK_BLIND_SPOT,
        action_scripts=[ActionScriptItem(**s) for s in FALLBACK_ACTION_SCRIPTS],
    )
    errs = validate_partner_card(card, is_high_risk=False)
    assert not errs, f"Fallback card failed validation: {errs}"

    shared = SharedSummary(**FALLBACK_SHARED_SUMMARY)
    shared_errs = validate_shared_summary(shared, is_high_risk=False)
    assert not shared_errs, f"Fallback shared summary failed validation: {shared_errs}"


def test_validation_short_fields():
    card = PartnerResponse(
        validation="Слишком короткий текст.",
        partner_perspective="Также слишком коротко.",
        blind_spot="И здесь коротко.",
        action_scripts=[
            ActionScriptItem(label="1", text="Тест"),
            ActionScriptItem(label="2", text="Тест"),
        ],
    )
    errs = validate_partner_card(card, is_high_risk=False)
    assert any("< 180 символов" in e for e in errs)
    assert any("< 3" in e for e in errs)


def test_validation_action_scripts_count_and_len():
    # Неверное количество скриптов (1 вместо 2)
    card1 = PartnerResponse(
        validation=FALLBACK_VALIDATION,
        partner_perspective=FALLBACK_PARTNER_PERSPECTIVE,
        blind_spot=FALLBACK_BLIND_SPOT,
        action_scripts=[
            ActionScriptItem(label="1", text="Тест"),
        ],
    )
    errs1 = validate_partner_card(card1, is_high_risk=False)
    assert any("ожидалось ровно 2" in e for e in errs1)

    # Превышение 280 символов
    card2 = PartnerResponse(
        validation=FALLBACK_VALIDATION,
        partner_perspective=FALLBACK_PARTNER_PERSPECTIVE,
        blind_spot=FALLBACK_BLIND_SPOT,
        action_scripts=[
            ActionScriptItem(label="1", text="А" * 300),
            ActionScriptItem(label="2", text="Тест"),
        ],
    )
    errs2 = validate_partner_card(card2, is_high_risk=False)
    assert any("превышает 280 символов" in e for e in errs2)


@pytest.mark.parametrize("word", [
    "биоритм", "протокол", "безопасное пространство", "эмоциональная изоляция",
    "нарцисс", "газлайтинг", "токсичный", "созависимость", "жизненно важно"
])
def test_global_forbidden_words_detected(word):
    card = PartnerResponse(
        validation=f"{FALLBACK_VALIDATION} Упоминаем {word} в тексте.",
        partner_perspective=FALLBACK_PARTNER_PERSPECTIVE,
        blind_spot=FALLBACK_BLIND_SPOT,
        action_scripts=[ActionScriptItem(**s) for s in FALLBACK_ACTION_SCRIPTS],
    )
    errs = validate_partner_card(card, is_high_risk=False)
    assert any("обнаружены запрещенные слова" in e for e in errs)


@pytest.mark.parametrize("word", [
    "один партнёр", "другой партнер", "один из", "кто-то", "одного", "другого", "твой партнёр", "ты", "тебя", "тебе"
])
def test_shared_forbidden_words_detected(word):
    shared = SharedSummary(
        situation_overview=f"Похоже, что {word} переживает. В отношениях важно спокойствие.",
        shared_advice="Договоритесь о правиле тишины. Это поможет обоим отдохнуть.",
        conversation_starter="Давайте спокойно поговорим.",
    )
    errs = validate_shared_summary(shared, is_high_risk=False)
    assert any("обнаружены слова разделения ролей или 'ты'" in e for e in errs)


@pytest.mark.parametrize("word", [
    "конструктивный", "ушатом", "неуместно", "несоразмерный", "бойкот", "абсолютно", "жизненно"
])
def test_stage_3_2_new_forbidden_stems(word):
    card = PartnerResponse(
        validation=f"{FALLBACK_VALIDATION} Это было {word} в поведении.",
        partner_perspective=FALLBACK_PARTNER_PERSPECTIVE,
        blind_spot=FALLBACK_BLIND_SPOT,
        action_scripts=[ActionScriptItem(**s) for s in FALLBACK_ACTION_SCRIPTS],
    )
    errs = validate_partner_card(card, is_high_risk=False)
    assert any("обнаружены запрещенные слова" in e for e in errs)


def test_shared_tea_forbidden():
    shared = SharedSummary(
        situation_overview="В моменты усталости вам обоим сложно найти баланс. Напряжение мешает услышать друг друга.",
        shared_advice="Попейте вместе чай и отдохните. Это поможет восстановить силы.",
        conversation_starter="Давайте спокойно поговорим.",
    )
    errs = validate_shared_summary(shared, is_high_risk=False)
    assert any("обнаружены слова разделения ролей или 'ты'" in e for e in errs)


def test_sparse_validation():
    # Валидная карточка в режиме sparse
    card_valid = PartnerResponse(
        validation="Ты рассказал совсем коротко, поэтому скажу осторожно. Похоже, здесь накопилось сильное напряжение.",
        partner_perspective="Возможно, партнёр тоже чувствует растерянность и закрывается.",
        blind_spot="Иногда молчание выглядит как отказ от общения.",
        action_scripts=[ActionScriptItem(**s) for s in FALLBACK_ACTION_SCRIPTS],
    )
    errs = validate_partner_card(card_valid, is_high_risk=False, sparse=True)
    assert len(errs) == 0

    # Ошибка: отсутствует вводная фраза
    card_invalid_prefix = PartnerResponse(
        validation="Ты не хочешь говорить. Похоже, здесь накопилось сильное напряжение.",
        partner_perspective="Возможно, партнёр тоже чувствует растерянность и закрывается.",
        blind_spot="Иногда молчание выглядит как отказ от общения.",
        action_scripts=[ActionScriptItem(**s) for s in FALLBACK_ACTION_SCRIPTS],
    )
    errs2 = validate_partner_card(card_invalid_prefix, is_high_risk=False, sparse=True)
    assert any("должна быть фраза" in e for e in errs2)


def test_stage_3_3_ritual_consistency():
    # Согласованные длительности
    p1_s2 = "Давай сегодня сделаем паузу на 15 минут, а потом спокойно вернемся к разговору."
    p2_s2 = "Предлагаю взять паузу на 15 мин и после этого обсудить всё без спешки."
    sh_adv = "Возьмите совместную паузу на 15 минут для снижения эмоционального накала."
    errs = validate_ritual_consistency(p1_s2, p2_s2, sh_adv)
    assert len(errs) == 0, f"Expected no errors, got: {errs}"

    # Несогласованные длительности (15 мин vs 30 мин)
    p2_s2_bad = "Предлагаю взять паузу на 30 минут и после этого обсудить всё."
    errs_bad = validate_ritual_consistency(p1_s2, p2_s2_bad, sh_adv)
    assert len(errs_bad) > 0
    assert any("не согласованы" in e or "не совпадает" in e for e in errs_bad)

    # Флаг ritual_unfit исключает проверку несовпадения
    errs_unfit = validate_ritual_consistency(p1_s2, p2_s2_bad, sh_adv, ritual_unfit_p2=True)
    assert len(errs_unfit) == 0


@pytest.mark.parametrize("dishonest_word", [
    "хотелки", "капризы", "дуться", "я тебя люблю", "мне стыдно", "мне жаль", "не хотел злиться"
])
def test_stage_3_3_script_dishonesty(dishonest_word):
    text = f"Я вижу твои {dishonest_word} и хочу обсудить это спокойно."
    found = find_script_dishonesty(text)
    assert len(found) > 0, f"Expected '{dishonest_word}' to be detected"


def test_stage_3_3_partner_perspective_hedge_rules():
    # 2 смягчителя в одном предложении
    card_two_hedges = PartnerResponse(
        validation=FALLBACK_VALIDATION,
        partner_perspective="Возможно, похоже, твоему партнёру тоже непросто в этой ситуации. Ему хочется понимания и спокойствия. Со стороны это может выглядеть как отстранение.",
        blind_spot=FALLBACK_BLIND_SPOT,
        action_scripts=[ActionScriptItem(**s) for s in FALLBACK_ACTION_SCRIPTS],
    )
    errs = validate_partner_card(card_two_hedges, is_high_risk=False)
    assert any("более одного смягчителя" in e for e in errs)

    # Все 3 предложения начинаются со смягчителей
    card_all_hedge_starts = PartnerResponse(
        validation=FALLBACK_VALIDATION,
        partner_perspective="Возможно, партнёру сейчас очень тяжело внутри. Похоже, он чувствует сильную перегрузку на работе. Бывает, что в такие моменты человек просто закрывается.",
        blind_spot=FALLBACK_BLIND_SPOT,
        action_scripts=[ActionScriptItem(**s) for s in FALLBACK_ACTION_SCRIPTS],
    )
    errs2 = validate_partner_card(card_all_hedge_starts, is_high_risk=False)
    assert any("начинаются со слов-смягчителей" in e for e in errs2)


