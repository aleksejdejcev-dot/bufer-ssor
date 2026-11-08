import base64
import os
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("INPUT_ENCRYPTION_KEY", base64.urlsafe_b64encode(os.urandom(32)).decode())

from main import app, require_legal_accepted
from repo import set_repo
from repo.in_memory_repo import InMemoryRepo


@pytest.fixture
def balance_pair():
    repo = InMemoryRepo()
    set_repo(repo)
    p1 = repo.upsert_user(8301, "Участник 1")
    p2 = repo.upsert_user(8302, "Участник 2")
    repo.accept_legal(8301)
    repo.accept_legal(8302)
    couple = repo.create_couple(8301, "BAL-1234")
    repo.join_couple(couple["id"], 8302)
    yield repo, p1, p2, couple
    app.dependency_overrides.clear()


def test_relationship_balance_waits_for_both_then_purges_source_answers(balance_pair, monkeypatch):
    repo, p1, p2, couple = balance_pair
    current_user = {"value": p1}
    app.dependency_overrides[require_legal_accepted] = lambda: current_user["value"]
    monkeypatch.setattr("main.asyncio.create_task", lambda coroutine: coroutine.close())
    result = {
        "score": 80,
        "label": "Есть хорошая опора",
        "summary": "У пары есть сильные стороны и место для разговора.",
        "tips": ["Спросите друг друга, какая поддержка сейчас нужна.", "Запланируйте время вдвоём."],
        "activity_idea": "Выберите прогулку в новом месте.",
        "dimension_scores": [4, 4, 3, 4, 3, 4],
    }
    monkeypatch.setattr("main.analyze_balance", AsyncMock(return_value=result))
    client = TestClient(app)

    started = client.post("/relationship-balance/start")
    assert started.status_code == 200
    session_id = started.json()["id"]
    answers_1 = [4, 4, 3, 5, 3, 4]
    answers_2 = [4, 3, 3, 4, 4, 4]

    first = client.post(f"/relationship-balance/{session_id}/answer", json={"answers": answers_1})
    assert first.status_code == 200
    assert first.json()["status"] == "waiting_partner"
    stored = repo.get_relationship_balance(session_id)
    assert stored["answers_p1"] != answers_1

    current_user["value"] = p2
    second = client.post(f"/relationship-balance/{session_id}/answer", json={"answers": answers_2})
    assert second.status_code == 200
    assert second.json()["status"] == "completed"
    stored = repo.get_relationship_balance(session_id)
    assert stored["answers_p1"] is None and stored["answers_p2"] is None
    assert stored["result"] == result

    current_user["value"] = p1
    assert client.get(f"/relationship-balance/{session_id}").json()["result"] == result
    assert client.post(f"/relationship-balance/{session_id}/finish").json()["finished"] is False
    current_user["value"] = p2
    assert client.post(f"/relationship-balance/{session_id}/finish").json()["finished"] is True
    assert repo.get_relationship_balance(session_id) is None


def test_relationship_balance_rejects_invalid_scale_values(balance_pair, monkeypatch):
    _repo, p1, _p2, _couple = balance_pair
    app.dependency_overrides[require_legal_accepted] = lambda: p1
    monkeypatch.setattr("main.asyncio.create_task", lambda coroutine: coroutine.close())
    session_id = TestClient(app).post("/relationship-balance/start").json()["id"]
    response = TestClient(app).post(
        f"/relationship-balance/{session_id}/answer",
        json={"answers": [1, 2, 3, 4, 5, 9]},
    )
    assert response.status_code == 422


def test_relationship_balance_start_notifies_partner_once_with_initiator_name(balance_pair, monkeypatch):
    _repo, p1, p2, _couple = balance_pair
    current_user = {"value": p1}
    app.dependency_overrides[require_legal_accepted] = lambda: current_user["value"]
    notifications = []

    def notify(partner_id, initiator_name):
        notifications.append((partner_id, initiator_name))

        async def done():
            return None

        return done()

    monkeypatch.setattr("main.notify_balance_partner_prompt", notify)
    monkeypatch.setattr("main.asyncio.create_task", lambda coroutine: coroutine.close())
    client = TestClient(app)

    first = client.post("/relationship-balance/start")
    current_user["value"] = p2
    second = client.post("/relationship-balance/start")

    assert first.status_code == second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert notifications == [(p2["telegram_id"], p1["first_name"])]
