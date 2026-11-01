from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from fastapi.testclient import TestClient
from aiogram.types import Message, User, Chat

from main import app, get_current_user
from repo import set_repo
from repo.in_memory_repo import InMemoryRepo
from bot import handle_conflict_input
from schemas import PartnerResponse, SharedSummary, ActionScriptItem, AgreedRitual
from validators import (
    validate_partner_card,
    validate_shared_summary,
    find_forbidden_in_string,
)
from config.safety_messages import get_high_risk_message
from providers.gigachat import GigaChatProvider
from config.fallbacks import FALLBACK_VALIDATION, FALLBACK_PARTNER_PERSPECTIVE, FALLBACK_BLIND_SPOT


def test_403_on_endpoints_without_legal_accepted():
    """Тест 9.1: Доступ ко всем чувствительным эндпоинтам запрещен (403), пока accepted_legal_at пуст."""
    test_repo = InMemoryRepo()
    set_repo(test_repo)

    # u1 зарегистрирован, но НЕ нажал accept_legal
    u1 = test_repo.upsert_user(1101, "Несогласный")
    assert u1["accepted_legal_at"] is None

    app.dependency_overrides[get_current_user] = lambda: u1
    try:
        client = TestClient(app)

        # 1. /couple/invite
        r_invite = client.post("/couple/invite")
        assert r_invite.status_code == 403
        assert "согласиться с условиями сервиса" in r_invite.json()["detail"]

        # 2. /conflict/start
        r_conflict = client.post("/conflict/start")
        assert r_conflict.status_code == 403

        # 3. /mood
        r_mood = client.post("/mood", json={"mood": 7})
        assert r_mood.status_code == 403

        # 4. /signal/white-flag
        r_signal = client.post("/signal/white-flag")
        assert r_signal.status_code == 403

        # Но /me доступен!
        r_me = client.get("/me")
        assert r_me.status_code == 200
        assert r_me.json()["user"]["accepted_legal_at"] is None
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_bot_rejects_input_without_legal_accepted():
    """Тест 9.1: Бот отклоняет ввод и не сохраняет данные, если accepted_legal_at пуст."""
    test_repo = InMemoryRepo()
    set_repo(test_repo)

    u1 = test_repo.upsert_user(1102, "БезСогласия")

    message = MagicMock(spec=Message)
    message.from_user = User(id=1102, is_bot=False, first_name="БезСогласия")
    message.chat = Chat(id=1102, type="private")
    message.text = "Моя версия конфликта..."
    message.voice = None
    message.answer = AsyncMock()

    await handle_conflict_input(message)

    message.answer.assert_called_once()
    reply = message.answer.call_args[0][0]
    assert "необходимо подтвердить возраст 18+" in reply
    assert len(test_repo.pending_inputs) == 0


def test_high_risk_identical_texts():
    """Тест 9.2: При высоком риске оба партнера получают ИДЕНТИЧНЫЙ фиксированный текст."""
    high_msg_1 = get_high_risk_message()
    high_msg_2 = get_high_risk_message()

    assert high_msg_1 == high_msg_2
    assert "112" in high_msg_1
    assert "8-800-7000-600" in high_msg_1
    assert "безопасность" in high_msg_1.lower()


@pytest.mark.parametrize("banned_phrase", [
    "проработайте эту проблему",
    "вам нужна сепарация от родителей",
    "нужно закрыть гештальт",
    "психологическая травма детства",
    "ты всегда опаздываешь",
    "ты никогда меня не слушаешь",
    "вы обязаны договориться",
    "вам нужно изменить поведение",
])
def test_banned_stems_and_phrases_detected_in_card(banned_phrase):
    """Тест 9.3: Валидатор находит запрещенные штампы, обвинения и директивы."""
    card = PartnerResponse(
        validation=f"{FALLBACK_VALIDATION} {banned_phrase}",
        partner_perspective=FALLBACK_PARTNER_PERSPECTIVE,
        blind_spot=FALLBACK_BLIND_SPOT,
        action_scripts=[
            ActionScriptItem(label="1", text="Спокойно поговорим."),
            ActionScriptItem(label="2", text="Сделаем перерыв."),
        ],
    )
    errs = validate_partner_card(card, is_high_risk=False)
    assert any("обнаружены запрещенные слова" in e for e in errs), f"Фраза '{banned_phrase}' не была обнаружена!"


def test_sparse_flag_handling_per_partner():
    """Тест 9.4: Если один партнер sparse, валидатор проверяет карточку по коротким лимитам,
    а второго партнера — по полным стандартным лимитам."""
    short_validation = "Ты рассказал совсем коротко, поэтому скажу осторожно. Твои переживания понятны, и мы разберемся вместе."
    short_perspective = "Похоже, партнер тоже сильно переживает этот холод и закрывается от усталости."
    short_blind_spot = "В спешке легко упустить, что близкий человек ждет не спора, а простого признания."

    sparse_card = PartnerResponse(
        validation=short_validation,
        partner_perspective=short_perspective,
        blind_spot=short_blind_spot,
        action_scripts=[
            ActionScriptItem(label="1", text="Давай поговорим без упреков."),
            ActionScriptItem(label="2", text="Мне нужно 15 минут паузы."),
        ],
    )

    # При sparse=True карточка проходит валидацию
    errs_sparse = validate_partner_card(sparse_card, is_high_risk=False, sparse=True)
    assert len(errs_sparse) == 0

    # При sparse=False (полный режим) та же карточка дает ошибку по длине (<180)
    errs_full = validate_partner_card(sparse_card, is_high_risk=False, sparse=False)
    assert any("< 180 символов" in e for e in errs_full)


def test_russian_trusted_root_ca_documentation_and_enforcement():
    """Тест 9.5: Документация сертификата Минцифры и проверка при GIGACHAT_INSECURE=0."""
    readme_path = Path(__file__).resolve().parent.parent / "certs" / "README.md"
    assert readme_path.exists(), "backend/certs/README.md должен существовать"
    readme_text = readme_path.read_text(encoding="utf-8")
    assert "Ожидаемый хэш: заполняет владелец после сверки с официальным источником" in readme_text

    # Если сертификата нет и insecure=False -> FileNotFoundError
    with pytest.raises(FileNotFoundError) as exc_info:
        provider = GigaChatProvider(
            credentials="test_cred",
            ca_bundle="non_existent_cert_path.pem",
            insecure=False,
        )
        provider._create_client()

    assert "backend/certs/README.md" in str(exc_info.value)
