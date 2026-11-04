"""
Шаблоны отказов и блокировок языковых моделей (Этап 3.5).
Используются для детекции отказов провайдера GigaChat из-за цензурных
или safety-фильтров при обработке острых конфликтов (угрозы, насилие и т.д.).
"""

import re
from typing import List, Optional

# Регулярные выражения и фразы-маркеры отказа нейросети
REFUSAL_PATTERNS: List[str] = [
    r"не могу ответить на этот вопрос",
    r"не могу выполнить (?:этот|данный)?\s*запрос",
    r"не могу продолжить (?:этот|данный)?\s*диалог",
    r"не могу обсуждать (?:эту|данную)?\s*тему",
    r"не в силах ответить",
    r"я не могу ответить",
    r"я не могу выполнить",
    r"как искусственный интеллект",
    r"как языковая модель",
    r"я всего лишь языковая модель",
    r"не имею права (?:обсуждать|отвечать)",
    r"содержит недопустимый контент",
    r"нарушает правила (?:использования|безопасности)",
    r"запрос содержит небезопасн\w*",
    r"не могу предоставить информацию",
    r"неприемлем\w* контент",
    r"отказ от ответа",
    r"обратитесь к специалисту",
    r"не могу поддержать (?:эту|данную)?\s*беседу",
    r"я не могу генерировать такой контент",
    r"сожалею, но я не могу",
]

_COMPILED_PATTERNS = [re.compile(p, re.IGNORECASE) for p in REFUSAL_PATTERNS]


def is_refusal_text(text: Optional[str]) -> bool:
    """
    Проверяет, является ли текст ответа отказом языковой модели.
    Пустой ответ или ответ короче 10 символов также считается отказом/сбоем.
    """
    if not text or not text.strip():
        return True

    clean = text.strip()
    if len(clean) < 10:
        return True

    for pattern in _COMPILED_PATTERNS:
        if pattern.search(clean):
            return True

    return False


def get_refusal_reason(text: Optional[str]) -> Optional[str]:
    """Возвращает найденный паттерн отказа или пояснение, почему ответ заблокирован."""
    if not text or not text.strip():
        return "empty_response"

    clean = text.strip()
    for pattern in _COMPILED_PATTERNS:
        m = pattern.search(clean)
        if m:
            return f"refusal_pattern_matched: '{m.group(0)}'"

    if len(clean) < 10:
        return f"too_short_response: {clean}"

    return None
