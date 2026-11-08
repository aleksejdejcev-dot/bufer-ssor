import pytest
from fastapi.testclient import TestClient

from main import app, require_legal_accepted
from repo import set_repo
from repo.in_memory_repo import InMemoryRepo
from bot import get_miniapp_keyboard


def test_age_confirmation_button_preserves_invite_code(monkeypatch):
    monkeypatch.setenv("MINI_APP_URL", "https://bufer-ssor.ru")
    keyboard = get_miniapp_keyboard(invite_code="ABCD-1234")
    button = keyboard.inline_keyboard[0][0]
    assert button.web_app.url == "https://bufer-ssor.ru?invite=ABCD-1234"


def test_join_invite_after_legal_confirmation(monkeypatch):
    repo = InMemoryRepo()
    set_repo(repo)
    owner = repo.upsert_user(7101, "Алексей")
    guest = repo.upsert_user(7102, "Мария")
    repo.accept_legal(guest["telegram_id"])
    couple = repo.create_couple(owner["telegram_id"], "ABCD-1234")
    monkeypatch.setattr("main.asyncio.create_task", lambda coroutine: coroutine.close())
    app.dependency_overrides[require_legal_accepted] = lambda: guest
    try:
        response = TestClient(app).post("/couple/join", json={"invite_code": "ABCD-1234"})
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "joined"
        linked = repo.get_user_couple(guest["telegram_id"])
        assert linked["id"] == couple["id"]
        assert linked["partner_2_id"] == guest["telegram_id"]
    finally:
        app.dependency_overrides.clear()


def test_conflict_start_schedules_messages_for_both_partners(monkeypatch):
    repo = InMemoryRepo()
    set_repo(repo)
    initiator = repo.upsert_user(7201, "Алексей")
    partner = repo.upsert_user(7202, "Мария")
    repo.accept_legal(initiator["telegram_id"])
    repo.accept_legal(partner["telegram_id"])
    couple = repo.create_couple(initiator["telegram_id"], "EFGH-1234")
    repo.join_couple(couple["id"], partner["telegram_id"])
    scheduled = []

    def capture(coroutine):
        scheduled.append(coroutine)
        coroutine.close()

    monkeypatch.setattr("main.asyncio.create_task", capture)
    app.dependency_overrides[require_legal_accepted] = lambda: initiator
    try:
        response = TestClient(app).post("/conflict/start")
        assert response.status_code == 200, response.text
        assert {coro.cr_code.co_name for coro in scheduled} == {
            "notify_initiator_prompt",
            "notify_conflict_partner_prompt",
        }
        assert len(scheduled) == 2
    finally:
        app.dependency_overrides.clear()
