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
    are_durations_consistent,
    find_script_dishonesty,
    sanitize_minor_banned_words,
    is_unknown_word,
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


def test_stage_3_9_sanitize_minor_banned_words():
    # Авто-замена абсолютно / жизненно с сохранением регистра
    assert sanitize_minor_banned_words("Твои чувства абсолютно понятны.") == "Твои чувства вполне понятны."
    assert sanitize_minor_banned_words("Абсолютно нормально злиться в такой момент.") == "Вполне нормально злиться в такой момент."
    assert sanitize_minor_banned_words("Это жизненно важно для обоих.") == "Это по-человечески важно для обоих."
    assert sanitize_minor_banned_words("Жизненно необходимо выдохнуть.") == "По-человечески необходимо выдохнуть."


def test_stage_3_9_shared_summary_banned_roles_and_cliche():
    # Кейс 3: Между вами возникает напряжение ... одному важно ... другому
    shared = SharedSummary(
        situation_overview="Между вами возникает напряжение, когда речь заходит о телефонах: одному важно чувствовать безопасность, другому — сохранять автономию.",
        shared_advice="Договоритесь о правиле открытости без резких жестов. Это укрепит доверие в паре.",
        conversation_starter="Давайте вместе обсудим этот момент спокойно.",
    )
    errs = validate_shared_summary(shared, is_high_risk=False)
    assert any("слова разделения ролей" in e for e in errs)
    # Проверка выявления клише и падежей одного/другого
    assert any("возникает напряжение" in e or "одному" in e or "другому" in e for e in errs)

    # Проверка других падежей: одним / другим
    shared_cases = SharedSummary(
        situation_overview="В этот момент одним сложно сдержаться, а другим хочется спрятаться. Напряжение мешает услышать друг друга.",
        shared_advice="Возьмите совместную паузу на 15 минут.",
        conversation_starter="Давайте обсудим всё спокойно.",
    )
    errs_cases = validate_shared_summary(shared_cases, is_high_risk=False)
    assert any("слова разделения ролей" in e for e in errs_cases)


@pytest.mark.parametrize("dishonest_ritual_phrase", [
    "как договаривались", "как мы договаривались", "наш еженедельный", "наш обычный чек-ин", "сделаем нашу паузу"
])
def test_stage_3_9_script_ritual_dishonesty(dishonest_ritual_phrase):
    text = f"Давай проведем чек-ин, {dishonest_ritual_phrase}."
    found = find_script_dishonesty(text)
    assert len(found) > 0, f"Expected '{dishonest_ritual_phrase}' to be detected in script"


def test_stage_3_9_spell_whitelist_and_prefixes():
    # Проверка слов из белого списка
    whitelist_words = [
        "недосказанность", "недопонимание", "обесценивание",
        "чек-ин", "чекин", "тайм-аут", "онлайн", "офлайн"
    ]
    for w in whitelist_words:
        assert not is_unknown_word(w), f"Слово '{w}' из белого списка не должно быть неизвестным"

    # Проверка слов с приставками не-, недо-, со-
    assert not is_unknown_word("недоверие")
    assert not is_unknown_word("недопонял")
    assert not is_unknown_word("сопереживание")

    # Проверка явной абракадабры
    assert is_unknown_word("абырвалг")
    assert is_unknown_word("ывапролдж")


def test_stage_3_9_diversify_partner_perspectives():
    from ai_service import diversify_partner_perspectives

    card1 = PartnerResponse(
        validation=FALLBACK_VALIDATION,
        partner_perspective="Возможно, твой партнёр растерялся и просто закрылся от боли. В моменты кризиса за внешней резкостью стоит растерянность. С его стороны это выглядело иначе.",
        blind_spot=FALLBACK_BLIND_SPOT,
        action_scripts=[ActionScriptItem(**s) for s in FALLBACK_ACTION_SCRIPTS],
    )
    card2 = PartnerResponse(
        validation=FALLBACK_VALIDATION,
        partner_perspective="Возможно, она тревожится из-за денег и пытается контролировать то, что кажется нестабильным. За этим поведением прячется страх за завтрашний день. Ей важно чувствовать опору.",
        blind_spot=FALLBACK_BLIND_SPOT,
        action_scripts=[ActionScriptItem(**s) for s in FALLBACK_ACTION_SCRIPTS],
    )

    diversify_partner_perspectives(card1, card2)
    assert card1.partner_perspective.startswith("Возможно")
    assert not card2.partner_perspective.startswith("Возможно")
    assert card2.partner_perspective.startswith("В таких ситуациях")


def test_stage_3_10_ritual_durations_consistent():
    """Проверка умного сравнения длительностей ритуала (10 + 5 == 15)."""
    # 1. 10 мин + 5 мин == 15 мин при наличии суммы в одном из множеств
    assert are_durations_consistent({"10 мин", "5 мин"}, {"10 мин", "5 мин", "15 мин"}) is True
    assert are_durations_consistent({"10 мин", "5 мин", "15 мин"}, {"10 мин", "5 мин"}) is True

    # 2. Сумма двух элементов равна единственному элементу другого
    assert are_durations_consistent({"10 мин", "5 мин"}, {"15 мин"}) is True
    assert are_durations_consistent({"15 мин"}, {"10 мин", "5 мин"}) is True

    # 3. Полное совпадение
    assert are_durations_consistent({"15 мин"}, {"15 мин"}) is True
    assert are_durations_consistent({"10 мин", "5 мин"}, {"5 мин", "10 мин"}) is True

    # 4. Несовпадающие длительности
    assert are_durations_consistent({"10 мин"}, {"15 мин"}) is False
    assert are_durations_consistent({"10 мин", "5 мин"}, {"20 мин"}) is False


def test_stage_3_10_sanitize_possessive_ritual_phrases():
    """Проверка авто-санитайзера ложной договоренности и притяжательных местоимений."""
    # 1. наш вечерний чек-ин -> вечерний чек-ин
    assert sanitize_minor_banned_words("сделаем наш вечерний чек-ин") == "сделаем вечерний чек-ин"
    assert sanitize_minor_banned_words("Наш вечерний чек-ин поможет нам.") == "Вечерний чек-ин поможет нам."

    # 2. наш финансовый чек-ин -> финансовый чек-ин
    assert sanitize_minor_banned_words("сделаем наш финансовый чек-ин") == "сделаем финансовый чек-ин"

    # 3. наша пауза -> пауза
    assert sanitize_minor_banned_words("сделаем нашу паузу 10+5") == "сделаем паузу 10+5"
    assert sanitize_minor_banned_words("Наша пауза на 15 минут завершилась.") == "Пауза на 15 минут завершилась."

    # 4. наше правило -> новое правило
    assert sanitize_minor_banned_words("попробуем наше правило") == "попробуем новое правило"
    assert sanitize_minor_banned_words("Наше правило поможет договориться.") == "Новое правило поможет договориться."

    # 5. как договаривались / как мы договаривались
    assert sanitize_minor_banned_words("давай сделаем, как договаривались, паузу") == "давай сделаем паузу"
    assert sanitize_minor_banned_words("давай сделаем паузу, как мы договаривались.") == "давай сделаем паузу."


def test_stage_3_10_leak_guard_analyzer_filter():
    """Проверка фильтрации приватных фактов чужой версии из hypothesis_for_other и agreed_ritual."""
    from leak_guard import filter_text_leaks, sanitize_hypothesis_for_other
    from schemas import HypothesisForOther

    # Слово 'планёрка' есть в секретах/фактах P2 и отсутствует в общих
    text = "обсудить планёрку и график дежурств"
    cleaned = filter_text_leaks(text, forbidden_texts=["планёрка у начальника"], allowed_texts=["график дежурств"])
    assert "планёрк" not in cleaned
    assert "график дежурств" in cleaned

    hyp = HypothesisForOther(
        likely_feelings=["тревога из-за планёрки"],
        likely_needs=["ясность"],
    )
    sanitized_hyp = sanitize_hypothesis_for_other(
        hyp,
        other_private_facts=["была тяжелая планёрка"],
        other_secrets=[],
        facts_known_to_both=[],
    )
    assert "планёрк" not in sanitized_hyp.likely_feelings[0]


def test_stage_3_11_sparse_validation_and_followup():
    """Проверка сборки и валидации sparse-карточек, пометки о краткости и сброса при followup."""
    from ai_service import format_sparse_validation
    from config.fallbacks import (
        SPARSE_SHORTNESS_PREFIXES,
        FALLBACK_SPARSE_VALIDATION_OPTIONS,
        get_random_fallback,
    )

    # 1. format_sparse_validation добавляет пометку и оставляет ровно 2 предложения
    long_val = (
        "Твои чувства и накопившаяся усталость вполне естественны. "
        "В близких отношениях любая отстранённость ощущается особенно тяжело. "
        "Понятно желание найти ясность, спокойствие и ощущение того, что старания замечают."
    )
    formatted = format_sparse_validation(long_val)
    assert count_sentences(formatted) == 2
    assert any(pfx[:20] in formatted for pfx in SPARSE_SHORTNESS_PREFIXES) or "Ты рассказал(а) совсем коротко" in formatted

    # Если пометка уже есть — она сохраняется
    already_sparse = "Ты рассказал(а) совсем коротко, поэтому скажу осторожно. Твои переживания естественны."
    assert format_sparse_validation(already_sparse) == already_sparse

    # 2. Валидация sparse=True карточки
    card = PartnerResponse(
        validation=formatted,
        partner_perspective="За такой реакцией часто стоит то, что человек устал и растерян.",  # 1 предложение
        blind_spot="Иногда короткая пауза помогает вернуть спокойный тон.",  # 1 предложение
        action_scripts=[
            ActionScriptItem(label="Шаг 1", text="Сделать паузу на 10 минут и передохнуть."),
            ActionScriptItem(label="Шаг 2", text="Предлагаю попробовать новое правило: 15-минутный разговор без упрёков. Что скажешь?"),
        ],
    )
    # При sparse=True должно проходить без замечаний
    errs_sparse = validate_partner_card(card, sparse=True)
    assert not errs_sparse, f"Sparse card should be valid: {errs_sparse}"

    # Допускается 2 или 3 предложения в validation (при наличии пометки)
    card.validation = f"{SPARSE_SHORTNESS_PREFIXES[0]}. Первое предложение о чувствах. Второе о поддержке."
    assert not validate_partner_card(card, sparse=True)

    # При отсутствии пометки о краткости sparse=True выдаёт ошибку
    card.validation = "Твои чувства естественны. В близких отношениях важно понимание."
    errs_no_note = validate_partner_card(card, sparse=True)
    assert any("пометка о краткости" in e for e in errs_no_note)

    # 3. get_random_fallback(..., sparse=True)
    for _ in range(10):
        val_fb = get_random_fallback("validation", sparse=True)
        assert count_sentences(val_fb) == 2
        assert any(pfx[:20] in val_fb for pfx in SPARSE_SHORTNESS_PREFIXES)

        pp_fb = get_random_fallback("partner_perspective", sparse=True)
        assert 1 <= count_sentences(pp_fb) <= 2

        bs_fb = get_random_fallback("blind_spot", sparse=True)
        assert count_sentences(bs_fb) == 1

    # 4. Проверка сброса sparse при наличии followup (Патч 3.4 правило 6)
    # Если has_followup=True, карточка трактуется как обычная (is_sparse=False)
    # и без достаточной длины не проходит валидатор sparse=False
    errs_non_sparse = validate_partner_card(card, sparse=False)
    assert any("слишком короткое" in e for e in errs_non_sparse)


def test_stage_3_11_no_tautology_in_partner_perspective():
    """Проверка отсутствия тавтологии «Со стороны партнёра, у твоего партнёра...»."""
    from ai_service import diversify_partner_perspectives, reformulate_perspective_opening

    # Если текст уже начинается с «У твоего партнёра...» — не добавлять «партнёр»
    text = "У твоего партнёра в этой ситуации тоже есть свои переживания."
    reformed = reformulate_perspective_opening(text)
    assert "Со стороны партнёра, у твоего партнёра" not in reformed
    assert not reformed.startswith("Со стороны партнёра, у")

    # Проверка работы diversify_partner_perspectives
    p1 = PartnerResponse(
        validation=FALLBACK_VALIDATION,
        partner_perspective="Возможно, в такой момент партнёр закрывается от перегрузки.",
        blind_spot=FALLBACK_BLIND_SPOT,
        action_scripts=[ActionScriptItem(**s) for s in FALLBACK_ACTION_SCRIPTS],
    )
    p2 = PartnerResponse(
        validation=FALLBACK_VALIDATION,
        partner_perspective="У твоего партнёра в этой ситуации, скорее всего, тоже свои переживания.",
        blind_spot=FALLBACK_BLIND_SPOT,
        action_scripts=[ActionScriptItem(**s) for s in FALLBACK_ACTION_SCRIPTS],
    )
    diversify_partner_perspectives(p1, p2)
    assert "Со стороны партнёра, у твоего партнёра" not in p2.partner_perspective
    assert "Со стороны партнёра, у твоего партнёра" not in p1.partner_perspective


def test_stage_3_11_spell_whitelist_inflections():
    """Проверка распознавания падежных форм чек-ин* и тайм-аут* в белом списке орфографии."""
    # Чек-ин во всех формах должен быть признан известным
    for form in ["чек-ин", "чек-ина", "чек-ину", "чек-ином", "чек-ине", "чек-ины", "чек-инов", "чек-инам"]:
        assert not is_unknown_word(form), f"Word {form} should be recognized as known"

    # Тайм-аут во всех формах
    for form in ["тайм-аут", "тайм-аута", "тайм-ауту", "тайм-аутом", "тайм-ауте", "тайм-ауты"]:
        assert not is_unknown_word(form), f"Word {form} should be recognized as known"

    # Несуществующее слово должно распознаваться как неизвестное
    assert is_unknown_word("непонятнаяабракадабра123") is True
    assert is_unknown_word("абырвалг") is True


def test_stage_3_11_shared_forbidden_pronouns_and_roles():
    """Проверка блокировки «кому-то», «один ... второй» и санитизации «бойкот» / «жизненно»."""
    # 1. Блокировка падежей 'кто-то' в shared_summary
    sh1 = SharedSummary(
        situation_overview="У вас разный способ восстановиться: кому-то нужна тишина, кому-то — контакт.",
        shared_advice="Ежедневно делайте 15-минутный разговор без упрёков.",
        conversation_starter="Давайте сегодня сделаем 15-минутный разговор. Что скажете?",
    )
    errs1 = validate_shared_summary(sh1)
    assert any("кому-то" in e for e in errs1), f"Expected 'кому-то' to be flagged: {errs1}"

    # 2. Блокировка ролевой пары 'один ... второй'
    sh2 = SharedSummary(
        situation_overview="В ссоре один начинает говорить громче, второй закрывается и уходит.",
        shared_advice="Ежедневно делайте 15-минутный разговор без упрёков.",
        conversation_starter="Давайте сегодня сделаем 15-минутный разговор. Что скажете?",
    )
    errs2 = validate_shared_summary(sh2)
    assert any("один" in e and "второй" in e for e in errs2), f"Expected 'один ... второй' to be flagged: {errs2}"

    # 3. Санитизация наречий и бойкота
    assert sanitize_minor_banned_words("это жизненно важно для нас") == "это по-человечески важно для нас"
    assert sanitize_minor_banned_words("это жизненно.") == "это по-человечески."
    assert sanitize_minor_banned_words("он объявил бойкот разговорам") == "он объявил молчание разговорам"
    assert sanitize_minor_banned_words("прекратить бойкотирование") == "прекратить игнорирование"


def test_stage_3_11_build_deterministic_ritual_script():
    """Проверка формирования ритуального скрипта #2 при коротком ritual_phrase_we."""
    from ai_service import build_deterministic_ritual_script
    from schemas import AgreedRitual

    # Короткое название ритуала 'разговор' без чисел
    short_ritual = AgreedRitual(
        name="разговор",
        duration_minutes=20,
        when="каждый вечер",
        format="разговор",
        ritual_phrase_we="разговор",
        serves_partner_1_need="внимание",
        serves_partner_2_need="спокойствие",
    )
    shared_advice = (
        "Договоритесь о правиле: 48 часов на обдумывание крупных трат свыше 5000 рублей. "
        "Раз в неделю проводите 20-минутный финансовый разговор."
    )
    script_text = build_deterministic_ritual_script(short_ritual, shared_advice)
    # Скрипт должен подтянуть правило с числами из shared_advice
    assert "Предлагаю попробовать новое правило:" in script_text
    assert ("48 часов" in script_text or "20-минутный" in script_text)
    assert script_text.endswith("Что скажешь?")





