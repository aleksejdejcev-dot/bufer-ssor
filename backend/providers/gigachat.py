"""
Реализация LLM-провайдера для Сбер GigaChat (Этап 3.5).
Использует официальный SDK gigachat (асинхронный клиент),
строгий структурированный вывод по JSON-схемам, доверенные корневые сертификаты РФ (TLS),
контроль параллельности и детекцию цензуры / отказов.
"""

import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import TypeVar, Type, Optional, Tuple, Dict, Any, Union, List

from gigachat import GigaChat
from gigachat.models import Chat, Messages, MessagesRole
from pydantic import BaseModel, ValidationError

from config.settings import settings
from config.refusal_patterns import is_refusal_text, get_refusal_reason
from providers.base import LLMProvider

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)

_GIGACHAT_SEMAPHORE = asyncio.Semaphore(settings.GIGACHAT_CONCURRENCY)


def clean_json_text(text: str) -> str:
    """Очищает ответ модели от markdown-обёрток ```json ... ``` и внешнего текста."""
    if not text:
        return ""
    clean = text.strip()

    # Срезаем markdown codeblocks
    if clean.startswith("```"):
        lines = clean.splitlines()
        if len(lines) >= 2:
            first_line = lines[0].strip()
            last_line = lines[-1].strip()
            if first_line.startswith("```"):
                lines = lines[1:]
            if len(lines) > 0 and lines[-1].strip() == "```":
                lines = lines[:-1]
            clean = "\n".join(lines).strip()

    # Если внутри остался лишний текст вокруг JSON, ищем первый { и последний }
    start_idx = clean.find("{")
    end_idx = clean.rfind("}")
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        clean = clean[start_idx : end_idx + 1]

    return clean


class GigaChatProvider(LLMProvider):
    """Адаптер для GigaChat API от Сбера."""

    provider_name: str = "gigachat"
    supports_audio: bool = False

    def __init__(
        self,
        credentials: Optional[str] = None,
        scope: Optional[str] = None,
        default_model: Optional[str] = None,
        ca_bundle: Optional[str] = None,
        insecure: Optional[bool] = None,
    ):
        self.credentials = credentials or settings.GIGACHAT_CREDENTIALS
        self.scope = scope or settings.GIGACHAT_SCOPE
        self.default_model = default_model or settings.GIGACHAT_MODEL
        self.ca_bundle = ca_bundle or settings.GIGACHAT_CA_BUNDLE
        self.insecure = insecure if insecure is not None else settings.GIGACHAT_INSECURE

        # Проверка пути к сертификатам
        self._effective_ca: Optional[str] = None
        if not self.insecure and self.ca_bundle:
            ca_path = Path(self.ca_bundle)
            if not ca_path.is_absolute():
                # Поддерживаем путь относительно корня репозитория и backend.
                # В контейнере рабочая директория — /app/backend, а настройки
                # могут содержать backend/certs/... (путь от корня репозитория).
                proj_root = Path(__file__).resolve().parent.parent
                candidates = (
                    proj_root / ca_path,
                    proj_root / "certs" / ca_path.name,
                    ca_path,
                )
                resolved_ca = next((candidate for candidate in candidates if candidate.is_file()), None)
                if resolved_ca:
                    self._effective_ca = str(resolved_ca.resolve())
            elif ca_path.exists():
                self._effective_ca = str(ca_path.resolve())

        self._verified_models: Optional[List[str]] = None

    def _create_client(self) -> GigaChat:
        """Создает контекст клиента GigaChat с корректным TLS."""
        kwargs: Dict[str, Any] = {
            "credentials": self.credentials,
            "scope": self.scope,
            "timeout": 60.0,
        }
        if self.insecure:
            logger.warning("[GigaChat] Insecure mode: TLS certificate verification is DISABLED!")
            kwargs["verify_ssl_certs"] = False
        else:
            if not self._effective_ca or not Path(self._effective_ca).exists():
                raise FileNotFoundError(
                    f"Сертификат Минцифры (Russian Trusted Root CA) не найден по пути '{self.ca_bundle}'. "
                    "При GIGACHAT_INSECURE=0 наличие валидного сертификата обязательно. "
                    "См. инструкцию по установке в backend/certs/README.md."
                )
            kwargs["verify_ssl_certs"] = True
            kwargs["ca_bundle_file"] = self._effective_ca

        return GigaChat(**kwargs)

    async def get_available_models(self) -> List[str]:
        """Возвращает список доступных для токена моделей."""
        async with self._create_client() as giga:
            models_data = await giga.aget_models()
            return [m.id_ for m in models_data.data if getattr(m, "id_", None)]

    async def check_model(self, model_name: str) -> bool:
        """Проверяет доступность модели в тарифе."""
        if self._verified_models is None:
            self._verified_models = await self.get_available_models()
        return model_name in self._verified_models

    async def verify_startup_model(self) -> None:
        """Проверяет GIGACHAT_MODEL при старте, при отсутствии бросает понятное исключение."""
        available = await self.get_available_models()
        if self.default_model not in available:
            models_str = ", ".join(available)
            raise ValueError(
                f"Модель '{self.default_model}' недоступна по вашему тарифу GigaChat!\n"
                f"Доступные модели: {models_str}\n"
                f"Укажите подходящую модель в переменной окружения GIGACHAT_MODEL."
            )
        logger.info("[GigaChat] Model '%s' verified successfully. Available: %s", self.default_model, available)

    async def generate_json(
        self,
        system_prompt: str,
        user_content: Union[str, List[Any]],
        json_schema: Dict[str, Any],
        pydantic_model: Type[T],
        temperature: float,
        max_tokens: Optional[int] = None,
        model: Optional[str] = None,
        tag: str = "gigachat",
    ) -> Tuple[Optional[T], Dict[str, Any]]:
        target_model = model or self.default_model

        # Формирование текстового user-запроса
        if isinstance(user_content, list):
            text_parts = []
            for item in user_content:
                if isinstance(item, str):
                    text_parts.append(item)
                elif hasattr(item, "text"):
                    text_parts.append(getattr(item, "text", ""))
                else:
                    text_parts.append(str(item))
            user_text = "\n".join(text_parts)
        else:
            user_text = str(user_content)

        messages = [
            Messages(role=MessagesRole.SYSTEM, content=system_prompt),
            Messages(role=MessagesRole.USER, content=user_text),
        ]

        response_format = {
            "type": "json_schema",
            "schema": json_schema,
            "strict": True,
        }

        meta: Dict[str, Any] = {
            "finish_reason": "unknown",
            "usage_tokens": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "blocked": False,
            "raw_text": "",
            "error": None,
        }

        backoff_delays = [2.0, 4.0, 8.0]

        async with _GIGACHAT_SEMAPHORE:
            async with self._create_client() as giga:
                for attempt, delay in enumerate(backoff_delays, start=1):
                    try:
                        chat_payload = Chat(
                            model=target_model,
                            messages=messages,
                            temperature=temperature,
                            response_format=response_format,
                        )
                        if max_tokens:
                            chat_payload.max_tokens = max_tokens

                        res = await asyncio.wait_for(giga.achat(chat_payload), timeout=60.0)

                        if not res.choices or len(res.choices) == 0:
                            meta["blocked"] = True
                            meta["error"] = "Empty choices in response"
                            return None, meta

                        choice = res.choices[0]
                        raw_content = (choice.message.content or "").strip()
                        meta["raw_text"] = raw_content
                        meta["finish_reason"] = str(choice.finish_reason or "stop").lower()

                        if res.usage:
                            meta["usage_tokens"] = res.usage.total_tokens or 0
                            meta["prompt_tokens"] = res.usage.prompt_tokens or 0
                            meta["completion_tokens"] = res.usage.completion_tokens or 0

                        # Детекция блокировки / цензуры
                        if meta["finish_reason"] not in ["stop", "stop_sequence"] or is_refusal_text(raw_content):
                            meta["blocked"] = True
                            meta["error"] = get_refusal_reason(raw_content) or f"Finish reason: {meta['finish_reason']}"
                            logger.warning("[%s] GigaChat refusal/blocked: %s", tag, meta["error"])
                            return None, meta

                        # Очистка и ремонт JSON
                        cleaned_json = clean_json_text(raw_content)

                        # Валидация Pydantic
                        try:
                            parsed = pydantic_model.model_validate_json(cleaned_json)
                            return parsed, meta
                        except (ValidationError, json.JSONDecodeError) as val_err:
                            logger.warning(
                                "[%s] JSON validation failed on attempt %d: %s. Performing 1 reminder retry...",
                                tag,
                                attempt,
                                val_err,
                            )
                            # Ровно один повтор с напоминанием формата
                            retry_messages = list(messages) + [
                                Messages(role=MessagesRole.ASSISTANT, content=raw_content),
                                Messages(
                                    role=MessagesRole.USER,
                                    content="Ошибка: ответ не соответствовал JSON-схеме. Ответь ТОЛЬКО валидным JSON-объектом по заданной схеме без лишнего текста и без markdown-разметки.",
                                ),
                            ]
                            retry_payload = Chat(
                                model=target_model,
                                messages=retry_messages,
                                temperature=0.2,
                                response_format=response_format,
                            )
                            retry_res = await asyncio.wait_for(giga.achat(retry_payload), timeout=60.0)
                            if retry_res.choices:
                                retry_raw = (retry_res.choices[0].message.content or "").strip()
                                meta["raw_text"] = retry_raw
                                if retry_res.usage:
                                    meta["usage_tokens"] += retry_res.usage.total_tokens or 0
                                retry_cleaned = clean_json_text(retry_raw)
                                parsed = pydantic_model.model_validate_json(retry_cleaned)
                                return parsed, meta
                            raise val_err

                    except Exception as e:
                        err_str = str(e).lower()
                        meta["error"] = str(e)
                        is_rate = "429" in err_str or "too many requests" in err_str
                        is_5xx = "500" in err_str or "502" in err_str or "503" in err_str or "504" in err_str

                        logger.warning("[%s] GigaChat error on attempt %d: %s", tag, attempt, e)

                        if attempt < len(backoff_delays):
                            await asyncio.sleep(delay)

        return None, meta

    async def transcribe(self, audio_bytes: bytes) -> str:
        """
        Заглушка транскрибации для GigaChat (пока поддерживается только текст).
        В боевом коде подключим отдельный сервис распознавания речи (SaluteSpeech / Whisper).
        """
        raise NotImplementedError("GigaChat provider does not natively transcribe audio yet. Use text transcript.")
