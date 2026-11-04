"""
Тесты логики Telegram-бота на aiogram 3.x (обработчики команд и сообщений).
"""

import os
import io
import time
import base64
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

TEST_FERNET_KEY = base64.urlsafe_b64encode(os.urandom(32)).decode()
os.environ["INPUT_ENCRYPTION_KEY"] = TEST_FERNET_KEY
os.environ["DATABASE_URL"] = os.getenv("DATABASE_URL_TEST") or os.getenv("DATABASE_URL") or "postgresql://buffer_admin:buffer_dev_pass@127.0.0.1:5432/buffer_ssor_test"
os.environ["TELEGRAM_BOT_TOKEN"] = "123456:DUMMY_TOKEN"
os.environ["TELEGRAM_WEBHOOK_SECRET"] = "dummy_secret"
os.environ["WEBHOOK_BASE_URL"] = "https://test.ngrok.app"
from aiogram.types import User, Chat, Message, Voice
from aiogram.filters import CommandObject

import db
from bot import (
    handle_start,
    handle_conflict_input,
    send_white_flag,
    send_hint_message,
    handle_support_command,
    setup_bot_commands,
)


@pytest.fixture
def mock_message():
    def _create_message(text=None, voice=None, user_id=101, first_name="Иван"):
        msg = MagicMock(spec=Message)
        msg.from_user = MagicMock(spec=User)
        msg.from_user.id = user_id
        msg.from_user.first_name = first_name
        msg.chat = MagicMock(spec=Chat)
        msg.chat.id = user_id
        msg.text = text
        msg.voice = voice
        msg.answer = AsyncMock()
        return msg
    return _create_message


@pytest.mark.asyncio
async def test_bot_start_regular(mock_message, monkeypatch):
    """Обычный /start без аргументов"""
    upsert_mock = MagicMock(return_value={"telegram_id": 101, "first_name": "Иван"})
    monkeypatch.setattr(db, "upsert_user", upsert_mock)

    msg = mock_message()
    cmd = CommandObject(prefix="/", command="start", args=None)

    await handle_start(msg, cmd)

    upsert_mock.assert_called_once_with(telegram_id=101, first_name="Иван")
    assert msg.answer.called
    args, kwargs = msg.answer.call_args
    assert "Буфер Ссор" in args[0]
    assert "reply_markup" in kwargs


@pytest.mark.asyncio
async def test_bot_start_pair_without_legal(mock_message, monkeypatch):
    """Попытка присоединиться к паре до принятия 18+"""
    user_data = {"telegram_id": 102, "first_name": "Мария", "accepted_legal_at": None}
    monkeypatch.setattr(db, "upsert_user", MagicMock(return_value=user_data))

    msg = mock_message(user_id=102, first_name="Мария")
    cmd = CommandObject(prefix="/", command="start", args="pair_ABC123")

    await handle_start(msg, cmd)

    assert msg.answer.called
    answer_text = msg.answer.call_args[0][0]
    assert "подтвердить возраст 18+" in answer_text


@pytest.mark.asyncio
async def test_bot_start_pair_with_self(mock_message, monkeypatch):
    """Попытка объединиться в пару с самим собой"""
    user_data = {"telegram_id": 101, "first_name": "Иван", "accepted_legal_at": "2026-10-29"}
    couple_data = {"id": "c1", "partner_1_id": 101, "partner_2_id": None, "invite_code": "ABC123"}
    
    monkeypatch.setattr(db, "upsert_user", MagicMock(return_value=user_data))
    monkeypatch.setattr(db, "get_couple_by_invite", MagicMock(return_value=couple_data))

    msg = mock_message(user_id=101, first_name="Иван")
    cmd = CommandObject(prefix="/", command="start", args="pair_ABC123")

    await handle_start(msg, cmd)

    assert msg.answer.called
    answer_text = msg.answer.call_args[0][0]
    assert "самим собой" in answer_text


@pytest.mark.asyncio
async def test_bot_voice_input_exceeds_duration(mock_message, monkeypatch):
    """Голосовое сообщение длительностью более 5 минут отклоняется"""
    user_data = {"telegram_id": 101, "first_name": "Иван", "accepted_legal_at": "2026-10-31T00:00:00Z"}
    couple_data = {"id": "c1", "partner_1_id": 101, "partner_2_id": 102}
    session_data = {"id": "s1", "status": "waiting_partner_2"}

    monkeypatch.setattr(db, "get_user", MagicMock(return_value=user_data))
    monkeypatch.setattr(db, "get_user_couple", MagicMock(return_value=couple_data))
    monkeypatch.setattr(db, "get_active_session", MagicMock(return_value=session_data))
    monkeypatch.setattr(db, "has_user_submitted_input", MagicMock(return_value=False))

    voice_mock = MagicMock(spec=Voice)
    voice_mock.duration = 350  # > 300 секунд
    voice_mock.file_size = 1000

    audio_prov = MagicMock()
    audio_prov.supports_audio = True
    monkeypatch.setattr("bot.get_provider", MagicMock(return_value=audio_prov))

    msg = mock_message(voice=voice_mock, user_id=101)
    await handle_conflict_input(msg)

    assert msg.answer.called
    answer_text = msg.answer.call_args[0][0]
    assert "слишком длинное" in answer_text


@pytest.mark.asyncio
async def test_bot_support_command(mock_message):
    """Тест команды /support со ссылкой на автора"""
    msg = mock_message(text="/support", user_id=101)
    await handle_support_command(msg)

    assert msg.answer.called
    args, kwargs = msg.answer.call_args
    assert "Возникли вопросы по подписке, возврату или работе сервиса?" in args[0]
    assert "Напишите автору напрямую — поможем разобраться:" in args[0]
    assert "reply_markup" in kwargs
    kb = kwargs["reply_markup"]
    assert any(
        btn.url == "https://t.me/Griiikkk" and "Написать автору" in btn.text
        for row in kb.inline_keyboard
        for btn in row
    )


@pytest.mark.asyncio
async def test_setup_bot_commands():
    """Тест регистрации команд в меню бота"""
    mock_bot = MagicMock()
    mock_bot.set_my_commands = AsyncMock()

    await setup_bot_commands(mock_bot)

    assert mock_bot.set_my_commands.called
    cmds = mock_bot.set_my_commands.call_args[0][0]
    commands_map = {cmd.command: cmd.description for cmd in cmds}
    assert "support" in commands_map
    assert commands_map["support"] == "Связь с поддержкой"
    assert "start" in commands_map

