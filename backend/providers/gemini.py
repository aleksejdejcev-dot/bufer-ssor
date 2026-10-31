"""
Реализация LLM-провайдера для Google Gemini (Этап 3.5).
Использует официальный SDK google-genai с поддержкой структурированного вывода,
таймаутов, прокси и контроля параллельности.
"""

import asyncio
import logging
import os
import re
from typing import TypeVar, Type, Optional, Tuple, Dict, Any, Union, List
from google import genai
from google.genai import types
from pydantic import BaseModel

from config.settings import settings
from config.refusal_patterns import is_refusal_text, get_refusal_reason
from providers.base import LLMProvider

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)

_GEMINI_SEMAPHORE = asyncio.Semaphore(settings.GEMINI_CONCURRENCY)


def _extract_retry_delay(err: Exception) -> Optional[float]:
    """Извлекает значение Retry-After или retryDelay из текста ошибки Google API."""
    err_str = str(err)
    m = re.search(r"retryDelay['\"]?:\s*['\"]?(\d+(?:\.\d+)?)s?", err_str)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    m_after = re.search(r"Retry-After['\"]?:\s*['\"]?(\d+)['\"]?", err_str, re.IGNORECASE)
    if m_after:
        try:
            return float(m_after.group(1))
        except ValueError:
            pass
    return None


class GeminiProvider(LLMProvider):
    """Адаптер для Google Gemini API."""

    provider_name: str = "gemini"
    supports_audio: bool = True

    def __init__(self, api_key: Optional[str] = None, default_model: Optional[str] = None):
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.default_model = default_model or settings.GEMINI_MODEL
        self._client: Optional[genai.Client] = None

    def _get_client(self) -> genai.Client:
        if self._client is None:
            import httpx
            proxy_url = settings.HTTPS_PROXY or os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
            if proxy_url:
                sync_c = httpx.Client(proxy=proxy_url, timeout=60.0)
                async_c = httpx.AsyncClient(proxy=proxy_url, timeout=60.0)
                http_opts = types.HttpOptions(
                    timeout=60000.0,
                    httpx_client=sync_c,
                    httpx_async_client=async_c,
                )
            else:
                http_opts = types.HttpOptions(timeout=60000.0)
            self._client = genai.Client(api_key=self.api_key, http_options=http_opts)
        return self._client

    async def generate_json(
        self,
        system_prompt: str,
        user_content: Union[str, List[Any]],
        json_schema: Dict[str, Any],
        pydantic_model: Type[T],
        temperature: float,
        max_tokens: Optional[int] = None,
        model: Optional[str] = None,
        tag: str = "gemini",
    ) -> Tuple[Optional[T], Dict[str, Any]]:
        client = self._get_client()
        target_model = model or self.default_model

        # Подготовка конфигурации Gemini
        cfg_kwargs: Dict[str, Any] = {
            "system_instruction": system_prompt,
            "temperature": temperature,
            "response_mime_type": "application/json",
            "response_schema": pydantic_model,
        }
        if max_tokens:
            cfg_kwargs["max_output_tokens"] = max_tokens
        if settings.GEMINI_THINKING_BUDGET is not None:
            cfg_kwargs["thinking_config"] = types.ThinkingConfig(
                thinking_budget=settings.GEMINI_THINKING_BUDGET
            )

        config = types.GenerateContentConfig(**cfg_kwargs)

        # Подготовка контента
        if isinstance(user_content, str):
            contents: List[Union[str, types.Part]] = [user_content]
        elif isinstance(user_content, list):
            contents = user_content
        else:
            contents = [str(user_content)]

        backoff_delays = [2.0, 4.0, 8.0]
        meta: Dict[str, Any] = {
            "finish_reason": "unknown",
            "usage_tokens": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "blocked": False,
            "raw_text": "",
            "error": None,
        }

        async with _GEMINI_SEMAPHORE:
            for attempt, delay in enumerate(backoff_delays, start=1):
                try:
                    res = await asyncio.wait_for(
                        client.aio.models.generate_content(
                            model=target_model,
                            contents=contents,
                            config=config,
                        ),
                        timeout=60.0,
                    )

                    raw_text = res.text or ""
                    meta["raw_text"] = raw_text

                    # Учет использования токенов
                    if res.usage_metadata:
                        meta["usage_tokens"] = res.usage_metadata.total_token_count or 0
                        meta["prompt_tokens"] = res.usage_metadata.prompt_token_count or 0
                        meta["completion_tokens"] = res.usage_metadata.candidates_token_count or 0

                    # Извлечение finish_reason
                    if res.candidates and len(res.candidates) > 0:
                        meta["finish_reason"] = str(res.candidates[0].finish_reason or "stop").lower()

                    # Проверка на отказ или блокировку
                    if meta["finish_reason"] in ["safety", "blocked", "prohibited_content"] or is_refusal_text(raw_text):
                        meta["blocked"] = True
                        meta["error"] = get_refusal_reason(raw_text) or f"Blocked by finish_reason: {meta['finish_reason']}"
                        logger.warning("[%s] Gemini refused or blocked response: %s", tag, meta["error"])
                        return None, meta

                    # Парсинг Pydantic
                    parsed = None
                    if getattr(res, "parsed", None) and isinstance(res.parsed, pydantic_model):
                        parsed = res.parsed
                    elif raw_text:
                        parsed = pydantic_model.model_validate_json(raw_text)

                    return parsed, meta

                except Exception as e:
                    err_str = str(e).lower()
                    is_rate_limit = "429" in err_str or "resource_exhausted" in err_str
                    is_5xx = "500" in err_str or "503" in err_str or "504" in err_str

                    meta["error"] = str(e)
                    logger.warning("[%s] Gemini attempt %d failed: %s (%s)", tag, attempt, type(e).__name__, e)

                    if is_rate_limit and ("per day limit exceeded" in err_str or "requests per day" in err_str):
                        meta["blocked"] = True
                        logger.error("[%s] Daily quota limit exceeded: %s", tag, e)
                        return None, meta

                    if attempt < len(backoff_delays):
                        server_delay = _extract_retry_delay(e)
                        sleep_sec = min(server_delay, 60.0) if server_delay is not None and server_delay <= 60.0 else delay
                        await asyncio.sleep(sleep_sec)

        return None, meta

    async def transcribe(self, audio_bytes: bytes) -> str:
        """Транскрибация аудио через Gemini."""
        client = self._get_client()
        part = types.Part.from_bytes(data=audio_bytes, mime_type="audio/ogg")
        cfg = types.GenerateContentConfig(
            system_instruction="Транскрибируй аудиозапись в точный текст на русском языке. Никаких комментариев.",
            temperature=0.1,
        )
        res = await client.aio.models.generate_content(
            model=self.default_model,
            contents=[part, "Транскрибируй аудио."],
            config=cfg,
        )
        return (res.text or "").strip()

    async def get_available_models(self) -> List[str]:
        client = self._get_client()
        models = []
        async for m in client.aio.models.list():
            models.append(m.name.replace("models/", ""))
        return models

    async def check_model(self, model_name: str) -> bool:
        avail = await self.get_available_models()
        clean = model_name.replace("models/", "")
        return clean in avail or f"models/{clean}" in avail
