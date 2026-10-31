import pytest
from schemas import ActionScriptItem, AgreedRitual
from validators import (
    validate_ritual_action_scripts_consistency,
    align_action_scripts_with_ritual,
)


def test_validator_catches_ritual_mismatch():
    """Тест валидатора: ловит несовпадение между временем в action_scripts (20 мин)
    и agreed_ritual (15 мин)."""
    ritual = AgreedRitual(
        name="Пауза тишины",
        duration_minutes=15,
        when="Сразу после работы",
        format="15 минут отдыха в разных комнатах",
        serves_partner_1_need="Дает возможность выдохнуть",
        serves_partner_2_need="Помогает успокоиться",
    )

    scripts_matching = [
        ActionScriptItem(label="1", text="Давай возьмем паузу на 15 минут, а потом поговорим."),
        ActionScriptItem(label="2", text="Я готов выслушать тебя спокойно."),
    ]
    errs_ok = validate_ritual_action_scripts_consistency(scripts_matching, ritual)
    assert len(errs_ok) == 0

    scripts_mismatch = [
        ActionScriptItem(label="1", text="Давай возьмем паузу на 20 минут, чтобы остыть."),
        ActionScriptItem(label="2", text="Давай помолчим 30 мин перед ужином."),
    ]
    errs_fail = validate_ritual_action_scripts_consistency(scripts_mismatch, ritual)
    assert len(errs_fail) == 2
    assert "20 минут" in errs_fail[0] or "20" in errs_fail[0]
    assert "30 минут" in errs_fail[1] or "30" in errs_fail[1]


def test_auto_alignment_replaces_mismatched_duration():
    """Тест автовыравнивания: заменяет расхождение во времени на время из agreed_ritual (15 минут)."""
    ritual = AgreedRitual(
        name="Спокойный диалог",
        duration_minutes=15,
        when="Вечером",
        format="15 минут диалога без обвинений",
        serves_partner_1_need="Снижает тревогу",
        serves_partner_2_need="Дает пространство для выражения чувств",
    )

    scripts_with_mismatch = [
        ActionScriptItem(label="Вариант 1", text="Давай поговорим ровно 20 минут и остановимся."),
        ActionScriptItem(label="Вариант 2", text="Мне нужно 10 мин тишины, затем обсудим."),
    ]

    aligned = align_action_scripts_with_ritual(scripts_with_mismatch, ritual)
    assert len(aligned) == 2

    # Проверяем первый скрипт: 20 минут заменено на 15 минут
    assert "15 минут" in aligned[0].text
    assert "20 минут" not in aligned[0].text

    # Проверяем второй скрипт: 10 мин заменено на 15 минут
    assert "15 минут" in aligned[1].text
    assert "10 мин" not in aligned[1].text

    # Валидатор теперь не должен находить ошибок
    errs_after = validate_ritual_action_scripts_consistency(aligned, ritual)
    assert len(errs_after) == 0
