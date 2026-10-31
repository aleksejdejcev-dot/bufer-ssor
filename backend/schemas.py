"""
Pydantic-схемы для строгого структурированного вывода (structured output)
моделей Google Gemini на Этапе 3.1:
- Шаг A: AnalyzerOutput (анализатор версий)
- Шаг B1/B2: PartnerResponse (автор карточки)
- Шаг C: SharedSummary (автор общего итога)
- Шаг D: LeakCheckOutput (детектор утечек)
- MediatorOutput: агрегированный результат сессии
"""

import warnings
from typing import List, Optional, Literal, Union, Any
from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator

warnings.filterwarnings("ignore", message='Field name "register" in "ToneAnalysis".*')


# ==============================================================================
# Схемы для Шага A: Анализатор (Analyzer)
# ==============================================================================

class ToneAnalysis(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    register: Literal["informal", "formal"] = Field(
        ...,
        description="Регистр речи: informal (разговорный, сленг) или formal (сдержанный, книжный)",
    )
    swearing: bool = Field(
        ...,
        description="Присутствует ли мат или грубая брань в версии",
    )
    length: Literal["short", "long"] = Field(
        ...,
        description="Объем версии: short (1-2 предложения/фразы) или long (развернутый текст)",
    )

    @field_validator("register", mode="before")
    @classmethod
    def normalize_register(cls, v: Any) -> str:
        if isinstance(v, str):
            v_low = v.lower()
            if any(k in v_low for k in ["неформ", "разговор", "informal", "сленг"]):
                return "informal"
            return "formal"
        return "formal"

    @field_validator("swearing", mode="before")
    @classmethod
    def normalize_swearing(cls, v: Any) -> bool:
        if isinstance(v, str):
            return v.lower() in ["true", "1", "да", "есть", "присутствует"]
        return bool(v)

    @field_validator("length", mode="before")
    @classmethod
    def normalize_length(cls, v: Any) -> str:
        if isinstance(v, str):
            v_low = v.lower()
            if any(k in v_low for k in ["коротк", "кратк", "short", "сжат"]):
                return "short"
            return "long"
        return "long"


class HypothesisForOther(BaseModel):
    likely_feelings: List[str] = Field(
        ...,
        description="2-3 общих чувства в обезличенной форме (усталость, тревога, растерянность)",
    )
    likely_needs: List[str] = Field(
        ...,
        description="1-3 общие потребности (в признании, поддержке, тишине, ясности)",
    )


class PartnerAnalysis(BaseModel):
    topic: str = Field(
        ...,
        description="О чем ссора с точки зрения этого партнера, своими словами",
    )
    key_facts: List[str] = Field(
        ...,
        description="3-6 конкретных фактов, названных самим партнером (события, время, действия)",
    )
    feelings: List[str] = Field(
        ...,
        description="2-4 ключевых чувства",
    )
    unmet_needs: List[str] = Field(
        ...,
        description="1-3 неудовлетворенные потребности",
    )
    own_contribution: str = Field(
        "",
        description="Собственный шаг/фраза/тон, усиливший напряжение (только по словам автора; иначе пустая строка)",
    )
    tone: ToneAnalysis = Field(
        ...,
        description="Характеристика тона и регистра речи партнера",
    )
    secrets: List[str] = Field(
        default_factory=list,
        description="Секреты, признания, долги, переписки, имена, факты, известные только ему",
    )
    hypothesis_for_other: HypothesisForOther = Field(
        ...,
        description="Обезличенная гипотеза о чувствах и потребностях для показа другому партнеру",
    )
    sparse: bool = Field(
        default=False,
        description="true, если версия партнера очень короткая (меньше 25 слов) и подробностей мало",
    )

    @field_validator("sparse", mode="before")
    @classmethod
    def normalize_sparse(cls, v: Any) -> bool:
        if isinstance(v, str):
            return v.lower() in ["true", "1", "да", "истина"]
        return bool(v)

    @model_validator(mode="after")
    def adjust_sparse(self):
        # Если версия подробная (от 3 ключевых фактов), она физически не может быть sparse
        if len(self.key_facts) >= 3 and self.sparse:
            self.sparse = False
        return self


class AgreedRitual(BaseModel):
    name: str = Field(
        ...,
        description="Краткое название ритуала",
    )
    duration_minutes: int = Field(
        ...,
        description="Длительность ритуала в минутах (например, 15, 20, 30)",
    )
    when: str = Field(
        ...,
        description="Когда проводится (например, сразу после возвращения с работы, вечером, в выходные)",
    )
    format: str = Field(
        ...,
        description="Формат проведения (например, 15 минут тишины, затем 10 минут разговора)",
    )
    serves_partner_1_need: str = Field(
        ...,
        description="Как ритуал удовлетворяет потребность партнера 1",
    )
    serves_partner_2_need: str = Field(
        ...,
        description="Как ритуал удовлетворяет потребность партнера 2",
    )


class SharedAnalysis(BaseModel):
    pattern: str = Field(
        ...,
        description="Повторяющийся рисунок между партнерами на уровне 'вы' без разделения ролей",
    )
    common_need: str = Field(
        ...,
        description="Общая глубинная потребность обоих партнеров",
    )
    neutral_topic: Optional[str] = Field(
        None,
        description="Тема ссоры в нейтральных словах, если она очевидна и известна обоим, иначе null",
    )
    ritual_ideas: List[str] = Field(
        ...,
        description="3 общих идеи простого ритуала или правила, привязанные к теме (с длительностью и форматом)",
    )
    agreed_ritual: Optional[AgreedRitual] = Field(
        None,
        description="Единый согласованный ритуал, учитывающий потребности обоих партнеров",
    )


class AnalyzerOutput(BaseModel):
    risk_level: Literal["none", "elevated", "high"] = Field(
        ...,
        description="Уровень риска безопасности: none, elevated или high",
    )
    risk_reasons: List[str] = Field(
        default_factory=list,
        description="Причины определения risk_level (только для внутреннего лога, без цитат)",
    )

    @field_validator("risk_level", mode="before")
    @classmethod
    def normalize_risk_level(cls, v: Any) -> str:
        if isinstance(v, str):
            v_low = v.lower()
            if "high" in v_low or "высок" in v_low:
                return "high"
            if "elevat" in v_low or "повыш" in v_low or "средн" in v_low:
                return "elevated"
            return "none"
        return "none"
    partner_1: PartnerAnalysis = Field(
        ...,
        description="Анализ позиции партнера 1",
    )
    partner_2: PartnerAnalysis = Field(
        ...,
        description="Анализ позиции партнера 2",
    )
    shared: SharedAnalysis = Field(
        ...,
        description="Синтез общей динамики для shared summary",
    )
    not_applicable: Optional[bool] = Field(
        False,
        description="Флаг: текст не про конфликт или автор младше 18 лет",
    )


# ==============================================================================
# Схемы для Шага B: Автор карточки (Card Writer)
# ==============================================================================

class ActionScriptItem(BaseModel):
    label: str = Field(
        ...,
        description="Метка скрипта: 'Сообщение прямо сейчас' или 'Предложение на сегодня или завтра'",
    )
    text: str = Field(
        ...,
        description="Готовая фраза от первого лица для отправки партнеру (до 280 символов)",
    )


class PartnerResponse(BaseModel):
    validation: str = Field(
        ...,
        description="Признание чувств получателя с конкретикой из его версии (не короче 180 символов, 3-5 предложений)",
    )
    partner_perspective: str = Field(
        "",
        description="Мягкое объяснение поведения партнера на базе гипотез (не короче 180 символов, 3-5 предложений). Пусто при high",
    )
    blind_spot: str = Field(
        "",
        description="Бережное наблюдение о своем шаге/тоне (не короче 180 символов, 3-4 предложения). Пусто при high",
    )
    action_scripts: List[ActionScriptItem] = Field(
        default_factory=list,
        description="Ровно 2 объекта со скриптами действий. Пустой список при high",
    )
    safety_note: Optional[str] = Field(
        "",
        description="Заметка о безопасности при elevated / high рисках",
    )
    ritual_unfit: Optional[bool] = Field(
        False,
        description="Флаг: общий ритуал не подходит под ситуацию получателя, написан собственный скрипт",
    )

    @field_validator("ritual_unfit", mode="before")
    @classmethod
    def normalize_ritual_unfit(cls, v: Any) -> bool:
        if isinstance(v, str):
            return v.lower() in ["true", "1", "да", "истина"]
        return bool(v)


# ==============================================================================
# Схемы для Шага C: Автор общего итога (Shared Writer)
# ==============================================================================

class SharedSummary(BaseModel):
    situation_overview: str = Field(
        "",
        description="Что в целом происходит между партнерами (не менее 2 предложений, только 'вы'). Пусто при high",
    )
    shared_advice: str = Field(
        "",
        description="Один простой ритуал или правило на ближайшие дни (не менее 2 предложений). Пусто при high",
    )
    conversation_starter: str = Field(
        "",
        description="Нейтральная фраза для совместного начала разговора (1-2 предложения). Пусто при high",
    )


# ==============================================================================
# Схемы для Шага D: Проверка утечек и финальный результат
# ==============================================================================

class LeakCheckOutput(BaseModel):
    leak: bool = Field(
        ...,
        description="Флаг обнаружения утечки конфиденциальности или фактов чужой версии",
    )
    location: Optional[str] = Field(
        None,
        description="Поле, где зафиксирована утечка (partner_1_response, partner_2_response, shared_summary)",
    )
    reason: Optional[str] = Field(
        None,
        description="Краткое пояснение причины утечки без повторения чувствительных деталей",
    )


class MediatorOutput(BaseModel):
    risk_level: Literal["none", "elevated", "high"] = Field(
        ...,
        description="Итоговый уровень риска сессии",
    )
    partner_1_response: PartnerResponse = Field(
        ...,
        description="Персональный разбор для партнера 1",
    )
    partner_2_response: PartnerResponse = Field(
        ...,
        description="Персональный разбор для партнера 2",
    )
    shared_summary: SharedSummary = Field(
        ...,
        description="Общий итог для пары",
    )
    safety_note: str = Field(
        "",
        description="Инструкции по безопасности и контакты экстренной помощи",
    )


# ==============================================================================
# Плоские JSON-схемы для GigaChat (Этап 3.5: strict=True, без $defs и oneOf)
# ==============================================================================

GIGACHAT_PARTNER_ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "topic": {"type": "string"},
        "key_facts": {"type": "array", "items": {"type": "string"}},
        "feelings": {"type": "array", "items": {"type": "string"}},
        "unmet_needs": {"type": "array", "items": {"type": "string"}},
        "own_contribution": {"type": "string"},
        "tone": {
            "type": "object",
            "properties": {
                "register": {"type": "string", "enum": ["informal", "formal"]},
                "swearing": {"type": "boolean"},
                "length": {"type": "string", "enum": ["short", "long"]},
            },
            "required": ["register", "swearing", "length"],
            "additionalProperties": False,
        },
        "secrets": {"type": "array", "items": {"type": "string"}},
        "hypothesis_for_other": {
            "type": "object",
            "properties": {
                "likely_feelings": {"type": "array", "items": {"type": "string"}},
                "likely_needs": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["likely_feelings", "likely_needs"],
            "additionalProperties": False,
        },
        "sparse": {"type": "boolean"},
    },
    "required": [
        "topic",
        "key_facts",
        "feelings",
        "unmet_needs",
        "own_contribution",
        "tone",
        "secrets",
        "hypothesis_for_other",
        "sparse",
    ],
    "additionalProperties": False,
}

GIGACHAT_ANALYZER_SCHEMA = {
    "type": "object",
    "properties": {
        "risk_level": {"type": "string", "enum": ["none", "elevated", "high"]},
        "risk_reasons": {"type": "array", "items": {"type": "string"}},
        "partner_1": GIGACHAT_PARTNER_ANALYSIS_SCHEMA,
        "partner_2": GIGACHAT_PARTNER_ANALYSIS_SCHEMA,
        "shared": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "common_need": {"type": "string"},
                "neutral_topic": {"type": "string"},
                "ritual_ideas": {"type": "array", "items": {"type": "string"}},
                "agreed_ritual": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "duration_minutes": {"type": "integer"},
                        "when": {"type": "string"},
                        "format": {"type": "string"},
                        "serves_partner_1_need": {"type": "string"},
                        "serves_partner_2_need": {"type": "string"},
                    },
                    "required": [
                        "name",
                        "duration_minutes",
                        "when",
                        "format",
                        "serves_partner_1_need",
                        "serves_partner_2_need",
                    ],
                    "additionalProperties": False,
                },
            },
            "required": ["pattern", "common_need", "neutral_topic", "ritual_ideas", "agreed_ritual"],
            "additionalProperties": False,
        },
        "not_applicable": {"type": "boolean"},
    },
    "required": ["risk_level", "risk_reasons", "partner_1", "partner_2", "shared", "not_applicable"],
    "additionalProperties": False,
}

GIGACHAT_PARTNER_CARD_SCHEMA = {
    "type": "object",
    "properties": {
        "validation": {"type": "string"},
        "partner_perspective": {"type": "string"},
        "blind_spot": {"type": "string"},
        "action_scripts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "text": {"type": "string"},
                },
                "required": ["label", "text"],
                "additionalProperties": False,
            },
        },
        "safety_note": {"type": "string"},
        "ritual_unfit": {"type": "boolean"},
    },
    "required": ["validation", "partner_perspective", "blind_spot", "action_scripts", "safety_note", "ritual_unfit"],
    "additionalProperties": False,
}

GIGACHAT_SHARED_SCHEMA = {
    "type": "object",
    "properties": {
        "situation_overview": {"type": "string"},
        "shared_advice": {"type": "string"},
        "conversation_starter": {"type": "string"},
    },
    "required": ["situation_overview", "shared_advice", "conversation_starter"],
    "additionalProperties": False,
}

GIGACHAT_LEAK_CHECK_SCHEMA = {
    "type": "object",
    "properties": {
        "leak": {"type": "boolean"},
        "location": {"type": "string"},
        "reason": {"type": "string"},
    },
    "required": ["leak", "location", "reason"],
    "additionalProperties": False,
}


def get_flat_json_schema(model_cls: type) -> dict:
    """Возвращает оптимизированную плоскую JSON-схему для GigaChat без $defs и refs."""
    if model_cls == AnalyzerOutput:
        return GIGACHAT_ANALYZER_SCHEMA
    if model_cls == PartnerResponse:
        return GIGACHAT_PARTNER_CARD_SCHEMA
    if model_cls == SharedSummary:
        return GIGACHAT_SHARED_SCHEMA
    if model_cls == LeakCheckOutput:
        return GIGACHAT_LEAK_CHECK_SCHEMA
    # Резервный вариант: стандартный pydantic json schema
    return model_cls.model_json_schema()
