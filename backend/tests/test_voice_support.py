import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from aiogram.types import Message, User, Chat, Voice

from repo import set_repo
from repo.in_memory_repo import InMemoryRepo
from bot import handle_conflict_input
from ai_service import analyze_session
from providers.base import LLMProvider
import crypto


class DummyProviderNoAudio(LLMProvider):
    provider_name: str = "gigachat"
    supports_audio: bool = False

    async def generate_json(self, *args, **kwargs):
        return {}, {"finish_reason": "stop", "usage_tokens": 10, "blocked": False}

    async def transcribe(self, audio_bytes: bytes) -> str:
        raise NotImplementedError("Audio not supported")

    async def check_model(self) -> bool:
        return True

    async def get_available_models(self):
        return ["GigaChat-3-Ultra"]


class DummyProviderWithAudio(LLMProvider):
    provider_name: str = "gemini"
    supports_audio: bool = True

    async def generate_json(self, *args, **kwargs):
        return {}, {"finish_reason": "stop", "usage_tokens": 10, "blocked": False}

    async def transcribe(self, audio_bytes: bytes) -> str:
        return "Транскрибированный текст голоса"

    async def check_model(self) -> bool:
        return True

    async def get_available_models(self):
        return ["gemini-2.5-flash"]


@pytest.mark.asyncio
async def test_bot_rejects_voice_when_provider_no_audio():
    """Если supports_audio == False, бот сразу отказывает и не скачивает файл."""
    test_repo = InMemoryRepo()
    set_repo(test_repo)

    u1 = test_repo.upsert_user(301, "Иван")
    u2 = test_repo.upsert_user(302, "Мария")
    test_repo.accept_legal(301)
    test_repo.accept_legal(302)

    couple = test_repo.create_couple(301, "INV301")
    test_repo.join_couple(couple["id"], 302)

    session = test_repo.create_conflict_session(couple["id"], 301)
    session_id = session["id"]

    # Создаем фиктивное голосовое сообщение
    message = MagicMock(spec=Message)
    message.from_user = User(id=301, is_bot=False, first_name="Иван")
    message.chat = Chat(id=301, type="private")
    message.voice = Voice(
        file_id="voice_file_123",
        file_unique_id="unique_123",
        duration=25,
        file_size=50000,
    )
    message.text = None
    message.answer = AsyncMock()

    no_audio_provider = DummyProviderNoAudio()

    with patch("bot.get_provider", return_value=no_audio_provider), \
         patch("bot.bot.download", new_callable=AsyncMock) as mock_download:

        await handle_conflict_input(message)

        # 1. Ответ бота
        message.answer.assert_called_once()
        answer_text = message.answer.call_args[0][0]
        assert "Голосовые пока недоступны, отправь, пожалуйста, текстом" in answer_text

        # 2. bot.download НЕ вызывался
        mock_download.assert_not_called()

        # 3. Ничего не записано в pending_inputs
        assert test_repo.count_pending_inputs(session_id) == 0


@pytest.mark.asyncio
async def test_bot_accepts_voice_when_provider_supports_audio():
    """Если supports_audio == True, бот скачивает голос и сохраняет в pending_inputs."""
    test_repo = InMemoryRepo()
    set_repo(test_repo)

    u1 = test_repo.upsert_user(401, "Анна")
    u2 = test_repo.upsert_user(402, "Олег")
    test_repo.accept_legal(401)
    test_repo.accept_legal(402)

    couple = test_repo.create_couple(401, "INV401")
    test_repo.join_couple(couple["id"], 402)

    session = test_repo.create_conflict_session(couple["id"], 401)
    session_id = session["id"]

    message = MagicMock(spec=Message)
    message.from_user = User(id=401, is_bot=False, first_name="Анна")
    message.chat = Chat(id=401, type="private")
    message.voice = Voice(
        file_id="voice_file_456",
        file_unique_id="unique_456",
        duration=20,
        file_size=20000,
    )
    message.text = None
    message.answer = AsyncMock()

    audio_provider = DummyProviderWithAudio()

    # Имитируем скачивание байтов аудио
    async def fake_download(file, destination):
        destination.write(b"OggS_fake_audio_content")

    with patch("bot.get_provider", return_value=audio_provider), \
         patch("bot.bot.download", side_effect=fake_download):

        await handle_conflict_input(message)

        assert test_repo.count_pending_inputs(session_id) == 1
        inputs = test_repo.get_pending_inputs(session_id)
        assert inputs[0]["kind"] == "audio"


@pytest.mark.asyncio
async def test_ai_service_handles_unsupported_audio_gracefully():
    """Если в ai_service попал аудио-инпут, а провайдер не поддерживает аудио:
    - сессия завершается со статусом failed,
    - pending_inputs удаляются,
    - пользователям уходит уведомление."""
    test_repo = InMemoryRepo()
    set_repo(test_repo)

    u1 = test_repo.upsert_user(501, "User1")
    u2 = test_repo.upsert_user(502, "User2")
    test_repo.accept_legal(501)
    test_repo.accept_legal(502)

    couple = test_repo.create_couple(501, "INV501")
    test_repo.join_couple(couple["id"], 502)

    session = test_repo.create_conflict_session(couple["id"], 501)
    session_id = session["id"]

    # Сохраняем один текстовый инпут и один аудио инпут
    enc_text = crypto.encrypt_text("Я устал и хочу тишины.")
    enc_audio = crypto.encrypt_bytes(b"OggS_audio_data")

    test_repo.save_pending_input(session_id, 501, "text", enc_text)
    test_repo.save_pending_input(session_id, 502, "audio", enc_audio)
    assert test_repo.count_pending_inputs(session_id) == 2

    no_audio_provider = DummyProviderNoAudio()

    with patch("ai_service.get_provider", return_value=no_audio_provider), \
         patch("bot.bot.send_message", new_callable=AsyncMock) as mock_send:

        # Не должно выбросить unhandled exception
        await analyze_session(session_id)

        # 1. Сессия стала failed
        updated_session = test_repo.get_session_by_id(session_id)
        assert updated_session["status"] == "failed"

        # 2. pending_inputs удалены
        assert test_repo.count_pending_inputs(session_id) == 0

        # 3. Пользователям отправлено уведомление
        assert mock_send.call_count == 2
        notified_chats = {call[1]["chat_id"] for call in mock_send.call_args_list}
        assert notified_chats == {501, 502}
