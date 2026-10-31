"""
Базовый интерфейс LLM-провайдера (Этап 3.5).
Обеспечивает заменяемость слоя ИИ (Google Gemini / Sber GigaChat)
без изменения бизнес-логики медиатора конфликтов.
"""

from abc import ABC, abstractmethod
from typing import TypeVar, Type, Optional, Tuple, Dict, Any, Union, List
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMProvider(ABC):
    """Абстрактный интерфейс для взаимодействия с языковыми моделями."""

    provider_name: str = "base"
    supports_audio: bool = False
    default_model: str = ""

    @abstractmethod
    async def generate_json(
        self,
        system_prompt: str,
        user_content: Union[str, List[Any]],
        json_schema: Dict[str, Any],
        pydantic_model: Type[T],
        temperature: float,
        max_tokens: Optional[int] = None,
        model: Optional[str] = None,
        tag: str = "llm",
    ) -> Tuple[Optional[T], Dict[str, Any]]:
        """
        Генерирует структурированный ответ, валидирует по Pydantic-схеме и возвращает мета-данные.

        Returns:
            Tuple[Optional[T], Dict[str, Any]]:
                - parsed: экземпляр pydantic_model или None при фатальной ошибке
                - meta: словарь метаданных вызова:
                    finish_reason: str (например "stop", "blacklist", "length")
                    usage_tokens: int (суммарно токенов)
                    prompt_tokens: int
                    completion_tokens: int
                    blocked: bool (True если сработал отказ или цензура)
                    raw_text: str (исходный текст до парсинга)
                    error: Optional[str]
        """
        pass

    async def transcribe(self, audio_bytes: bytes) -> str:
        """
        Транскрибация аудиозаписи в текст.
        Если провайдер не поддерживает аудио, вызывается NotImplementedError.
        """
        raise NotImplementedError(f"Provider '{self.provider_name}' does not support audio transcription")

    @abstractmethod
    async def get_available_models(self) -> List[str]:
        """Возвращает список доступных идентификаторов моделей."""
        pass

    @abstractmethod
    async def check_model(self, model_name: str) -> bool:
        """Проверяет наличие и доступность конкретной модели."""
        pass
