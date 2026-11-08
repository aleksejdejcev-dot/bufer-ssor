import pytest

from balance_service import BalanceAdvice, analyze_balance


@pytest.mark.asyncio
async def test_balance_ai_receives_plain_language_patterns_not_numeric_scores(monkeypatch):
    captured = {}

    class FakeProvider:
        async def generate_json(self, **kwargs):
            captured.update(kwargs)
            return BalanceAdvice(
                summary="У вас есть взаимная поддержка, а в повседневной близости может хотеться большего.",
                tips=["Спросите друг друга, какая поддержка сейчас была бы кстати.", "Выберите время для разговора без телефонов."],
                activity_idea="Приготовьте вместе новое блюдо.",
            ), {}

    monkeypatch.setattr("balance_service.get_provider", lambda: FakeProvider())

    result = await analyze_balance([5, 4, 3, 4, 2, 4], [4, 3, 2, 5, 3, 4])

    assert not any(character.isdigit() for character in captured["user_content"])
    assert "не упоминай числа, баллы" in captured["system_prompt"].lower()
    assert result["score"] == 72
    assert len(result["tips"]) == 2
