"""Structured, low-sensitivity AI interpretation for voluntary couple check-ins."""

import asyncio
import logging
from typing import List

from pydantic import BaseModel, Field

from providers import get_provider

logger = logging.getLogger("relationship_balance")


class BalanceAdvice(BaseModel):
    summary: str = Field(..., min_length=20, max_length=600)
    tips: List[str] = Field(..., min_length=2, max_length=3)
    activity_idea: str = Field(..., min_length=10, max_length=240)


async def analyze_balance(answers_1: List[int], answers_2: List[int]) -> dict:
    """Interpret only paired 1–5 ratings; never receive free text or identity data."""
    means = [round((a + b) / 2, 1) for a, b in zip(answers_1, answers_2)]
    score = round(sum(means) / len(means) * 20)
    spread = max(abs(a - b) for a, b in zip(answers_1, answers_2))
    content = (
        f"Средние оценки пары по шести темам (1–5): {means}. "
        f"Разница максимальных ответов партнёров по одному вопросу: {spread} из 4. "
        f"Общий ориентировочный индекс: {score}/100."
    )
    prompt = (
        "Ты бережный помощник для отношений, не психолог и не диагност. "
        "По агрегированным оценкам пары напиши нейтральное общее наблюдение, 2–3 "
        "маленьких выполнимых совета и одну идею совместного занятия. Не обвиняй, "
        "не делай выводов о любви, совместимости, диагнозах или безопасности; "
        "не трактуй балл как научный тест. Если оценки расходятся, предложи спокойно "
        "обсудить разные ожидания. Ответы обоих равноправны. Пиши по-русски, просто и тепло."
    )
    provider = get_provider()
    parsed, meta = await asyncio.wait_for(
        provider.generate_json(
            system_prompt=prompt,
            user_content=content,
            json_schema=BalanceAdvice.model_json_schema(),
            pydantic_model=BalanceAdvice,
            temperature=0.4,
            max_tokens=700,
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
        "tips": parsed.tips,
        "activity_idea": parsed.activity_idea,
        "dimension_scores": means,
    }
