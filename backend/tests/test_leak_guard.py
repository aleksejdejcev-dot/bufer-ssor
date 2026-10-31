from leak_guard import (
    check_lemma_overlap,
    check_card_lemma_leaks,
    check_shared_lemma_leaks,
    extract_content_lemmas,
)


def test_extract_content_lemmas():
    lemmas = extract_content_lemmas("Партнер взял тайный кредит на миллион рублей в банке")
    assert "кредит" in lemmas
    assert "миллион" in lemmas
    assert "банк" in lemmas
    # Стоп-слова и общие слова исключаются
    assert "партнер" not in lemmas


def test_private_facts_in_other_card_triggers_leak():
    # Ситуация: у Партнера 2 есть тайна про тайный кредит, Партнер 1 об этом не знает
    p1_raw = "Он постоянно замкнут и не говорит со мной вечерами."
    p1_facts = ["замкнутость по вечерам"]
    p2_facts = ["тайный кредит на ремонт машины"]
    p2_secrets = ["кредит на два миллиона"]

    # Кандидат: текст карточки для Партнера 1, куда модель случайно вставила слово "кредит"
    leaked_card_text = "Твой партнер испытывает тревогу из-за давления и скрывает взятый кредит."
    overlap = check_card_lemma_leaks(
        card_text=leaked_card_text,
        other_private_facts=p2_facts,
        other_secrets=p2_secrets,
        recipient_raw=p1_raw,
        recipient_facts=p1_facts,
    )
    assert len(overlap) > 0
    assert "кредит" in overlap


def test_own_terms_in_card_does_not_trigger_leak():
    # Ситуация: слово "работа" есть у обоих или названо получателем
    p1_raw = "Он поздно возвращается с работы, я устаю одна с детьми."
    p1_facts = ["позднее возвращение с работы"]
    p2_facts = ["много работы над проектом"]
    p2_secrets = []

    # Кандидат: карточка Партнера 1 упоминает "работу"
    safe_card_text = "Тебе тяжело, когда партнер задерживается на работе и нет совместного отдыха."
    overlap = check_card_lemma_leaks(
        card_text=safe_card_text,
        other_private_facts=p2_facts,
        other_secrets=p2_secrets,
        recipient_raw=p1_raw,
        recipient_facts=p1_facts,
    )
    # Поскольку "работа" была у самого Партнера 1 в p1_raw, это НЕ утечка
    assert "работа" not in overlap
    assert len(overlap) == 0


def test_private_facts_in_shared_summary_triggers_leak():
    # В shared_summary попало приватное признание одного из партнеров
    all_private_facts = ["он втайне копит на мотоцикл"]
    all_secrets = ["мотоцикл в гараже"]
    facts_known_to_both = ["нехватка семейного бюджета"]

    leaked_shared = "Оба партнера хотят стабильности, но покупка нового мотоцикла вызывает напряжение."
    overlap = check_shared_lemma_leaks(
        shared_text=leaked_shared,
        all_private_facts=all_private_facts,
        all_secrets=all_secrets,
        facts_known_to_both=facts_known_to_both,
    )
    assert "мотоцикл" in overlap
    assert len(overlap) > 0


def test_safe_shared_summary_with_known_facts():
    all_private_facts = ["он втайне копит на мотоцикл"]
    all_secrets = ["мотоцикл"]
    facts_known_to_both = ["семейный бюджет", "расходы на квартиру"]

    safe_shared = "Паре важно согласовать общий семейный бюджет и график расходов на квартиру."
    overlap = check_shared_lemma_leaks(
        shared_text=safe_shared,
        all_private_facts=all_private_facts,
        all_secrets=all_secrets,
        facts_known_to_both=facts_known_to_both,
    )
    assert len(overlap) == 0
