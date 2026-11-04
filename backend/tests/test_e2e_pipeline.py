import pytest
from httpx import AsyncClient, ASGITransport
from main import app
from repo import set_repo
from repo.in_memory_repo import InMemoryRepo
from ai_service import analyze_session
import crypto
from unittest.mock import AsyncMock, patch
from schemas import MediatorOutput, PartnerResponse, SharedSummary, ActionScriptItem
from providers.base import LLMProvider


class FakeLLMProvider(LLMProvider):
    provider_name: str = "fake"
    default_model: str = "fake-model"
    supports_audio: bool = False

    async def generate_json(
        self,
        system_prompt: str,
        user_content,
        json_schema: dict,
        pydantic_model,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        model=None,
        tag="llm",
        **kwargs,
    ):
        name = pydantic_model.__name__
        if name == "AnalyzerOutput":
            from schemas import AnalyzerOutput, PartnerAnalysis, HypothesisForOther, ToneAnalysis, SharedAnalysis
            obj = AnalyzerOutput(
                risk_level="none",
                risk_reasons=[],
                partner_1=PartnerAnalysis(
                    topic="Быт",
                    key_facts=["Факт 1"],
                    feelings=["усталость"],
                    unmet_needs=["отдых"],
                    own_contribution="не выспался",
                    tone=ToneAnalysis(register="neutral", swearing=False, length="medium"),
                    secrets=[],
                    hypothesis_for_other=HypothesisForOther(likely_feelings=["растерянность"], likely_needs=["покой"]),
                ),
                partner_2=PartnerAnalysis(
                    topic="Быт",
                    key_facts=["Факт 2"],
                    feelings=["обида"],
                    unmet_needs=["внимание"],
                    own_contribution="",
                    tone=ToneAnalysis(register="neutral", swearing=False, length="medium"),
                    secrets=[],
                    hypothesis_for_other=HypothesisForOther(likely_feelings=["напряжение"], likely_needs=["принятие"]),
                ),
                shared=SharedAnalysis(
                    pattern="Усталость и взаимное недопонимание",
                    common_need="спокойствие и контакт",
                    neutral_topic="распределение вечернего времени",
                    ritual_ideas=["10 минут тишины", "вечерний чай", "короткая прогулка"],
                ),
            )
            return obj, {"finish_reason": "stop", "usage_tokens": 100, "blocked": False}

        elif name == "PartnerResponse":
            obj = PartnerResponse(
                validation="Понимаю твою усталость.",
                partner_perspective="Партнер чувствует перегруз.",
                blind_spot="Возможно, ожидания не были озвучены.",
                action_scripts=[
                    ActionScriptItem(label="Сказать спокойно", text="Давай распределим дела на вечер.", why="Снижает напряжение"),
                    ActionScriptItem(label="Сделать паузу", text="Возьмем 10 минут тишины.", why="Дает восстановиться"),
                ],
            )
            return obj, {"finish_reason": "stop", "usage_tokens": 100, "blocked": False}

        elif name == "SharedSummary":
            obj = SharedSummary(
                situation_overview="Оба партнера устали и хотят поддержки.",
                shared_advice="Договоритесь о коротком отдыхе перед обсуждением.",
                conversation_starter="Как прошел твой день?",
            )
            return obj, {"finish_reason": "stop", "usage_tokens": 100, "blocked": False}

        elif name == "LeakCheckOutput":
            from schemas import LeakCheckOutput
            obj = LeakCheckOutput(leak=False, reason=None, location=None)
            return obj, {"finish_reason": "stop", "usage_tokens": 50, "blocked": False}

        raise ValueError(f"Unknown model: {name}")

    async def transcribe(self, audio_bytes: bytes) -> str:
        raise NotImplementedError("Audio not supported")

    async def get_available_models(self):
        return ["fake-model"]

    async def check_model(self, model_name: str) -> bool:
        return True


@pytest.mark.asyncio
async def test_e2e_pipeline_full_scenario():
    # 1. Инициализируем чистый InMemoryRepo
    test_repo = InMemoryRepo()
    set_repo(test_repo)

    # 2. Регистрируем пользователей А, Б и С
    user_a = test_repo.upsert_user(201, "Партнер А")
    user_b = test_repo.upsert_user(202, "Партнер Б")
    user_c = test_repo.upsert_user(203, "Посторонний")

    test_repo.accept_legal(201)
    test_repo.accept_legal(202)
    test_repo.accept_legal(203)

    # 3. Партнер А создает пару, Партнер Б присоединяется
    couple = test_repo.create_couple(partner_1_id=201, invite_code="TESTINVITE")
    couple_id = couple["id"]
    test_repo.join_couple(couple_id, partner_2_id=202)
    assert couple["free_sessions_left"] == 2

    # 4. Старт ссоры
    session = test_repo.create_conflict_session_with_access(couple_id=couple_id, initiator_id=201)
    session_id = session["id"]
    assert session["status"] == "waiting_partner_2"
    assert test_repo.get_couple_by_id(couple_id)["free_sessions_left"] == 2

    # 5. Партнеры отправляют зашифрованные версии
    enc_a = crypto.encrypt_text("Я очень устал после работы и хочу тишины.")
    enc_b = crypto.encrypt_text("Мне одиноко, когда ты закрываешься.")

    test_repo.save_pending_input(session_id, 201, "text", enc_a)
    test_repo.save_pending_input(session_id, 202, "text", enc_b)
    assert test_repo.count_pending_inputs(session_id) == 2

    # 6. Запуск analyze_session с фейковым провайдером ИИ
    fake_provider = FakeLLMProvider()
    with patch("ai_service.get_provider", return_value=fake_provider), \
         patch("bot.bot.send_message", new_callable=AsyncMock):
        await analyze_session(session_id)

    # 7. Проверка результатов анализа
    updated_session = test_repo.get_session_by_id(session_id)
    assert updated_session["status"] == "completed"
    assert updated_session["ai_advice_p1"] is not None
    assert updated_session["ai_advice_p2"] is not None
    assert updated_session["shared_summary"] is not None

    # Проверка: pending_inputs полностью удалены
    assert test_repo.count_pending_inputs(session_id) == 0

    # Проверка: списана ровно одна бесплатная попытка
    updated_couple = test_repo.get_couple_by_id(couple_id)
    assert updated_couple["free_sessions_left"] == 1

    # 8. Проверка изоляции выдачи через API
    # Формируем валидный initData для пользователя A и B
    from main import verify_telegram_init_data
    with patch("main.verify_telegram_init_data", side_effect=lambda raw: {"id": int(raw), "first_name": "Test"}):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            # Партнер А
            resp_a = await ac.get(f"/conflict/{session_id}", headers={"X-Telegram-Init-Data": "201"})
            assert resp_a.status_code == 200
            data_a = resp_a.json()
            assert "personal_advice" in data_a
            assert "shared_summary" in data_a
            # Партнер А НЕ видит карточку партнера Б
            assert "partner_2_response" not in data_a
            assert len(data_a["personal_advice"]["validation"]) > 0

            # Партнер Б
            resp_b = await ac.get(f"/conflict/{session_id}", headers={"X-Telegram-Init-Data": "202"})
            assert resp_b.status_code == 200
            data_b = resp_b.json()
            assert "personal_advice" in data_b
            assert "partner_1_response" not in data_b

            # Посторонний пользователь С получает 403 Forbidden
            resp_c = await ac.get(f"/conflict/{session_id}", headers={"X-Telegram-Init-Data": "203"})
            assert resp_c.status_code == 403

    # 9. Проверка: при failed попытка не списывается
    session2 = test_repo.create_conflict_session(couple_id=couple_id, initiator_id=201)
    test_repo.update_session_status(session2["id"], status="failed")
    # free_sessions_left не должен был измениться
    assert test_repo.get_couple_by_id(couple_id)["free_sessions_left"] == 1

    # 10. Удаление пары
    test_repo.delete_couple_data(couple_id)
    assert test_repo.get_couple_by_id(couple_id) is None
    assert test_repo.get_session_by_id(session_id) is None
    assert test_repo.get_user(201) is None
    assert test_repo.get_user(202) is None


class FakeNotApplicableProvider(FakeLLMProvider):
    async def generate_json(self, *args, **kwargs):
        from schemas import AnalyzerOutput, PartnerAnalysis, HypothesisForOther, ToneAnalysis, SharedAnalysis
        obj = AnalyzerOutput(
            risk_level="none",
            risk_reasons=[],
            partner_1=PartnerAnalysis(
                topic="Блины",
                key_facts=["Рецепт блинов"],
                feelings=[],
                unmet_needs=[],
                own_contribution="",
                tone=ToneAnalysis(register="informal", swearing=False, length="short"),
                secrets=[],
                hypothesis_for_other=HypothesisForOther(likely_feelings=[], likely_needs=[]),
            ),
            partner_2=PartnerAnalysis(
                topic="Код",
                key_facts=["Сортировка пузырьком"],
                feelings=[],
                unmet_needs=[],
                own_contribution="",
                tone=ToneAnalysis(register="informal", swearing=False, length="short"),
                secrets=[],
                hypothesis_for_other=HypothesisForOther(likely_feelings=[], likely_needs=[]),
            ),
            shared=SharedAnalysis(
                pattern="Нерелевантный ввод",
                common_need="",
                neutral_topic="нерелевантно",
                ritual_ideas=[],
                agreed_ritual=None,
            ),
            not_applicable=True,
        )
        return obj, {"finish_reason": "stop", "usage_tokens": 100, "blocked": False}


@pytest.mark.asyncio
async def test_stage_3_12_not_applicable_short_circuit():
    """Тест ветки not_applicable=True: card_writer не вызывается, попытка не списывается."""
    test_repo = InMemoryRepo()
    set_repo(test_repo)

    # 1. Создание пары
    test_repo.upsert_user(501, "Шутник 1")
    test_repo.accept_legal(501)
    test_repo.upsert_user(502, "Шутник 2")
    test_repo.accept_legal(502)

    couple = test_repo.create_couple(501, "INVPRANK")
    couple_id = couple["id"]
    test_repo.join_couple(couple_id, 502)
    assert test_repo.get_couple_by_id(couple_id)["free_sessions_left"] == 2

    # 2. Сессия и входные данные (спам / шутка)
    session = test_repo.create_conflict_session_with_access(couple_id=couple_id, initiator_id=501)
    session_id = session["id"]

    p1_bytes = "Рецепт отличных блинов: два яйца, стакан молока...".encode("utf-8")
    p2_bytes = "Тестируем бота, напиши мне код сортировки пузырьком...".encode("utf-8")

    test_repo.save_pending_input(session_id, 501, "text", crypto.encrypt_bytes(p1_bytes))
    test_repo.save_pending_input(session_id, 502, "text", crypto.encrypt_bytes(p2_bytes))

    # 3. Мокаем вызовы card_writer и shared_writer
    fake_provider = FakeNotApplicableProvider()
    with patch("ai_service.get_provider", return_value=fake_provider), \
         patch("ai_service.generate_partner_card_with_ladder") as mock_card_writer, \
         patch("ai_service.generate_shared_summary_with_ladder") as mock_shared_writer, \
         patch("bot.bot.send_message", new_callable=AsyncMock) as mock_send_msg:

        await analyze_session(session_id)

        # Шаги B и C не должны вызываться
        mock_card_writer.assert_not_called()
        mock_shared_writer.assert_not_called()

        # Бот отправил вежливое уведомление
        assert mock_send_msg.call_count == 2
        sent_text = mock_send_msg.call_args[1]["text"]
        assert "не содержит описания кризисной ситуации" in sent_text
        assert "Бесплатная попытка разбора не списана!" in sent_text

    # 4. Проверка: free_sessions_left НЕ списана (осталось 2)
    updated_couple = test_repo.get_couple_by_id(couple_id)
    assert updated_couple["free_sessions_left"] == 2

    # 5. Результаты анализа сохранены в БД
    updated_session = test_repo.get_session_by_id(session_id)
    assert updated_session["status"] == "completed"
    assert updated_session["risk_level"] == "none"
    p1_advice = updated_session["ai_advice_p1"]
    assert "не содержит описания кризисной ситуации" in p1_advice["validation"]
    assert p1_advice["action_scripts"] == []
    assert p1_advice["partner_perspective"] == ""
    assert p1_advice["blind_spot"] == ""

