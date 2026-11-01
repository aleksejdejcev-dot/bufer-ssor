"""
Вспомогательный кэш для аналитических прогонов в тестах (Шаг A).
Изолирован строго внутри каталога backend/tests/ и не используется боевым кодом.
"""

import hashlib
import logging
from pathlib import Path
from typing import Optional

from ai_service import get_prompt_text
from schemas import AnalyzerOutput

logger = logging.getLogger(__name__)


def compute_analyzer_cache_key(
    p1_kind: str,
    p1_bytes: bytes,
    p2_kind: str,
    p2_bytes: bytes,
    provider_name: str = "gemini",
    model_name: str = "",
) -> str:
    """Вычисляет sha256 хэш для безопасного кэширования Шага A в тестах."""
    h = hashlib.sha256()
    h.update(provider_name.encode("utf-8"))
    h.update(model_name.encode("utf-8"))
    h.update(p1_kind.encode("utf-8"))
    h.update(p1_bytes)
    h.update(p2_kind.encode("utf-8"))
    h.update(p2_bytes)
    prompt_text = get_prompt_text("analyzer")
    h.update(prompt_text.encode("utf-8"))
    return h.hexdigest()


def load_analyzer_cache(cache_key: str, cache_dir: Optional[Path]) -> Optional[AnalyzerOutput]:
    """Загружает результат анализатора из локального кэша тестов."""
    if not cache_dir:
        return None
    cache_file = cache_dir / f"analyzer_{cache_key}.json"
    if cache_file.exists():
        try:
            return AnalyzerOutput.model_validate_json(cache_file.read_text(encoding="utf-8"))
        except Exception as e:
            logger.debug("Failed to read analyzer cache: %s", e)
            return None
    return None


def save_analyzer_cache(cache_key: str, output: AnalyzerOutput, cache_dir: Optional[Path]) -> None:
    """Сохраняет результат анализатора в локальный кэш тестов."""
    if not cache_dir:
        return
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / f"analyzer_{cache_key}.json"
        cache_file.write_text(output.model_dump_json(indent=2), encoding="utf-8")
    except Exception as e:
        logger.debug("Failed to write analyzer cache: %s", e)
