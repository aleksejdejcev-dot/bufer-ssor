import pytest
from fastapi.testclient import TestClient
from schemas import ActionScriptItem, GIGACHAT_PARTNER_CARD_SCHEMA
from config.ui_texts import get_script_hints, DEFAULT_SCRIPT_HINTS
from main import app, get_current_user
from repo import get_repo, set_repo
from repo.in_memory_repo import InMemoryRepo
import crypto


def test_action_script_item_schema_no_why():
    """Проверка, что поле 'why' полностью удалено из схемы ActionScriptItem и GigaChat schema."""
    assert "why" not in ActionScriptItem.model_fields
    assert "label" in ActionScriptItem.model_fields
    assert "text" in ActionScriptItem.model_fields

    script_schema = GIGACHAT_PARTNER_CARD_SCHEMA["properties"]["action_scripts"]["items"]
    assert "why" not in script_schema["properties"]
    assert "why" not in script_schema["required"]
    assert set(script_schema["required"]) == {"label", "text"}


def test_ui_script_hints():
    """Проверка дефолтных UI-подсказок для скриптов."""
    hints = get_script_hints()
    assert len(hints) == 2
    assert hints == DEFAULT_SCRIPT_HINTS
    assert "первый шаг к диалогу" in hints[0]
    assert "совместное микро-действие" in hints[1]


def test_conflict_endpoint_returns_script_hints_and_no_why():
    """Проверка, что эндпоинт /conflict/{session_id} возвращает script_hints, и в скриптах нет why."""
    test_repo = InMemoryRepo()
    set_repo(test_repo)

    # Создаем тестовую пару и сессию
    u1 = test_repo.upsert_user(1001, "User1")
    u2 = test_repo.upsert_user(1002, "User2")
    test_repo.accept_legal(1001)
    test_repo.accept_legal(1002)

    couple = test_repo.create_couple(1001, "INVITE1001")
    test_repo.join_couple(couple["id"], 1002)

    session = test_repo.create_conflict_session(couple["id"], 1001)
    session_id = session["id"]

    # Имитируем сохранение результатов анализа
    analysis_data = {
        "status": "completed",
        "shared_summary": {
            "agreed_facts": ["Факт"],
            "core_difference": "Разница",
            "tension_point": "Точка напряжения",
            "shared_goal": "Общая цель",
            "agreed_ritual": {
                "format": "Разговор на 15 минут",
                "rules": ["Без криков"],
                "when": "Вечером"
            }
        },
        "partner_1_card": {
            "validation": "Понимаю твои чувства.",
            "partner_perspective": "Партнер тоже устал.",
            "blind_spot": "Ты можешь не замечать тон.",
            "action_scripts": [
                {"label": "Вариант 1", "text": "Давай поговорим спокойно."},
                {"label": "Вариант 2", "text": "Мне нужно 15 минут паузы."}
            ]
        },
        "partner_2_card": {
            "validation": "Твои переживания важны.",
            "partner_perspective": "Партнер хочет диалога.",
            "blind_spot": "Ты можешь закрываться.",
            "action_scripts": [
                {"label": "Вариант 1", "text": "Я готов выслушать тебя."},
                {"label": "Вариант 2", "text": "Давай обнимемся сначала."}
            ]
        }
    }
    test_repo.save_analysis_results(
        session_id=session_id,
        results=analysis_data,
        risk_level="low",
        completed_at="2026-10-31T12:00:00Z"
    )

    app.dependency_overrides[get_current_user] = lambda: u1
    try:
        client = TestClient(app)
        resp = client.get(f"/conflict/{session_id}")
        assert resp.status_code == 200
        data = resp.json()

        assert "script_hints" in data
        assert len(data["script_hints"]) == 2
        assert "personal_advice" in data
        scripts = data["personal_advice"]["action_scripts"]
        assert len(scripts) == 2
        for s in scripts:
            assert "why" not in s
            assert "label" in s
            assert "text" in s
    finally:
        app.dependency_overrides.clear()
