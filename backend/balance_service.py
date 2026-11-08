"""Structured, low-sensitivity AI interpretation for voluntary couple check-ins."""

import asyncio
import logging
from typing import List

from pydantic import BaseModel, Field

from providers import get_provider

logger = logging.getLogger("relationship_balance")


class BalanceAdvice(BaseModel):
    summary: str = Field(..., min_length=20, max_length=320)
    tips: List[str] = Field(..., min_length=2, max_length=3)
    activity_idea: str = Field(..., min_length=10, max_length=140)


async def analyze_balance(answers_1: List[int], answers_2: List[int]) -> dict:
    """Interpret only paired 1–5 ratings; never receive free text or identity data."""
    means = [round((a + b) / 2, 1) for a, b in zip(answers_1, answers_2)]
    score = round(sum(means) / len(means) * 20)
    dimensions = ["разговоры", "понимание", "время вместе", "поддержка", "общие дела", "тепло и нежность"]
    options = ["почти никогда", "редко", "иногда", "часто", "почти всегда"]
    content = "\n".join(
        f"{dimension.capitalize()}: ваш ответ — {options[a - 1]}; ответ партнёра — {options[b - 1]}."
        for dimension, a, b in zip(dimensions, answers_1, answers_2)
    )
    prompt = (
        "Ты бережный помощник для отношений, не психолог и не диагност. "
        "Сформулируй короткий и понятный общий вывод по ответам: 1–2 предложения и не больше 280 знаков, без разбора "
        "каждого вопроса по отдельности. Затем дай ровно 2 простых совета — по одному короткому "
        "предложению каждый — и одну короткую идею занятия для пары. Не упоминай числа, баллы, "
        "оценки, шкалы, средние значения и не сравнивай, кто ответил выше или ниже. Не превращай "
        "ответы в правила вида «если ответ такой, сделайте это». Не обвиняй и не делай выводов "
        "о любви, совместимости, диагнозах или безопасности. Ответы обоих равноправны. "
        "Пиши по-русски, естественно и тепло; не повторяй формулировки вопросов."
    )
    provider = get_provider()
    parsed, meta = await asyncio.wait_for(
        provider.generate_json(
            system_prompt=prompt,
            user_content=content,
            json_schema=BalanceAdvice.model_json_schema(),
            pydantic_model=BalanceAdvice,
            temperature=0.4,
        max_tokens=440,
            tag="relationship_balance",
        ),
        timeout=60,
    )
    if not parsed:
        logger.warning("Relationship balance generation failed: %s", (meta or {}).get("error", "no structured output"))
        raise RuntimeError("Не удалось подготовить результат. Повторите отправку ответов.")
    return {
        "score": score,
        "label": "Есть хорошая опора" if score >= 75 else "Есть темы для внимания" if score >= 55 else "Парам сейчас может быть непросто",
        "summary": parsed.summary,
        "tips": parsed.tips[:2],
        "activity_idea": parsed.activity_idea,
        "dimension_scores": means,
    }
