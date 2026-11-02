"""
Запрещенные слова, паттерны формулировок и правила очистки (config/banned.py).
Используются валидаторами качества текстов медиации (validators.py)
и генераторами карточек (ai_service.py).
"""

import re
from typing import Set, List, Any

# Запрещенные основы (стемы) одиночных слов (проверяются через stemmer)
FORBIDDEN_SINGLE_STEMS: Set[str] = {
    "конструктивн",  # конструктивный, конструктивно, конструктивность
    "ушат",          # ушат, ушатом, ушата
    "неуместн",      # неуместно, неуместный, неуместность
    "несоразмерн",    # несоразмерно, несоразмерный
    "бойкот",        # бойкот, бойкотировать
    "абсолютн",      # абсолютно, абсолютный
    "жизнен",        # жизненно, жизненный, жизненно важно
    "биоритм",       # биоритм, биоритмы
    "протокол",      # протокол
    "нарцисс",       # нарцисс, нарциссизм
    "газлайтинг",    # газлайтинг
    "токсич",        # токсично, токсичный
    "созависим",     # созависимость, созависимый
    "проработа",     # проработать, проработайте, проработка
    "сепарац",       # сепарация, сепарации, сепарироваться
    "гештальт",      # гештальт, гештальты
    "травм",         # травма, травмы, травмировать
}

# Запрещенные составные фразы (проверяются через регулярные выражения с гибкими окончаниями)
FORBIDDEN_PHRASE_PATTERNS: List[str] = [
    r"безопасн\w*\s+пространств\w*",
    r"безопасн\w*\s+сред\w*",
    r"пространств\w*\s+(?:для\s+)?диалог\w*",
    r"настоящ\w*\s+ад\b",
    r"эмоциональн\w*\s+изоляци\w*",
    r"жизненн\w*\s+важн\w*",
    r"ты\s+всегда\b",
    r"ты\s+никогда\b",
    r"(?:вы|ты)\s+обязан\w*",
    r"(?:вам|тебе)\s+нужно\b",
]

# Запрещенные фразы для скриптов действий (action_scripts) — честность формулировок и ритуалов (Этап 3.3, 3.9, 3.10)
FORBIDDEN_SCRIPT_PATTERNS: List[str] = [
    r"\bхотелк\w*",
    r"\bкаприз\w*",
    r"\bдутьс[яе]\b",
    r"\bнадул(?:ся|ась|ись)\b",
    r"обид\w*-страдани\w*",
    r"я\s+тебя\s+любл[юе]",
    r"мне\s+стыдно\b",
    r"\bмне\s+(?:очень\s+|правда\s+|так\s+|искренне\s+|сильно\s+)?жаль\b",
    r"\bпрости(?:\s+меня)?\b",
    r"\bизвини(?:\s+меня)?\b",
    r"не\s+хотел[аои]?\s+злиться\b",
    # Этап 3.9 + 3.10: запрет галлюцинаций предварительной договоренности
    r"как\s+(?:мы\s+)?договаривалис[ья]",
    r"наш\s+еженедельн\w*",
    r"наш\s+обычн\w*\s+чек-?ин",
    r"сделаем\s+нашу\s+паузу",
    r"\bнаш[а-яё]*\s+(?:\S+\s+){0,2}(?:чек-ин|чекин|пауз|правил|ритуал)",
]

# Дополнительно запрещенные фразы и слова в shared_summary (строго уровень 'вы', запрет ролей и клише)
SHARED_FORBIDDEN_PATTERNS: List[str] = [
    r"один\s+партн[её]р\w*",
    r"другой\s+партн[её]р\w*",
    r"один\s+из",
    r"одна\s+из",
    r"кто-то",
    r"\bкого-то\b",
    r"\bкому-то\b",
    r"\bкем-то\b",
    r"\bком-то\b",
    # Ролевая пара один ... второй (Этап 3.11)
    r"\bодин\b.*\bвторой\b",
    r"\bодна\b.*\bвторая\b",
    r"\bодного\b.*\bвторого\b",
    r"\bодному\b.*\bвторому\b",
    r"\bодним\b.*\bвторым\b",
    r"\bодного\b",
    r"\bдругого\b",
    r"\bодному\b",
    r"\bдругому\b",
    r"\bодним\b",
    r"\bдругим\b",
    r"\bодна\b\s+из",
    r"\bдругая\b",
    r"твой\s+партн[её]р\w*",
    r"\bты\b",
    r"\bтебя\b",
    r"\bтебе\b",
    r"\bтобой\b",
    r"\bтобою\b",
    r"\bча[яеюём]\b",  # чай, чаем, чаю, чая
    r"\bчай\b",
    # Клише начала общего итога (Этап 3.9)
    r"между вами\s+(?:\S+\s+){0,2}возникает напряжение",
    # Запрет притяжательных местоимений ритуала (Этап 3.10)
    r"\bнаш[а-яё]*\s+(?:\S+\s+){0,2}(?:чек-ин|чекин|пауз|правил|ритуал)",
]

# Смягчители для partner_perspective
HEDGE_WORDS: List[str] = ["возможно", "похоже", "бывает"]

# Белый список орфографии для pymorphy3 (Этап 3.9)
SPELL_WHITELIST: Set[str] = {
    "недосказанность",
    "недопонимание",
    "обесценивание",
    "чек-ин",
    "чекин",
    "тайм-аут",
    "онлайн",
    "офлайн",
    "щас",
    "ща",
    "чё",
    "чо",
    "ппц",
    "спс",
    "плиз",
    "ок",
    "норм",
    "инфа",
    "окэй",
    "пвз",
    "капс",
    "капсом",
    "макбук",
    "старостат",
}


def sanitize_minor_banned_words(text: str) -> str:
    """
    Мягкая авто-очистка одиночных наречий-усилителей ('абсолютно', 'жизненно')
    и выражений ложной договоренности ('наш чек-ин', 'наша пауза', 'наше правило',
    'как договаривались') (Этап 3.9, 3.10).
    """
    if not text:
        return text

    # 1. Авто-замена абсолютно -> вполне, жизненно -> по-человечески
    def _replace_absolutno(m: re.Match) -> str:
        word = m.group(0)
        return "Вполне" if word[0].isupper() else "вполне"

    def _replace_zhiznenno(m: re.Match) -> str:
        word = m.group(0)
        return "По-человечески" if word[0].isupper() else "по-человечески"

    text = re.sub(r"\bабсолютно\b", _replace_absolutno, text, flags=re.IGNORECASE)
    text = re.sub(r"\bжизненно\b", _replace_zhiznenno, text, flags=re.IGNORECASE)

    # 1.1 Замена бойкот* -> молчание / игнорирование (Этап 3.11)
    def _replace_boycott(m: re.Match) -> str:
        word = m.group(0).lower()
        is_cap = m.group(0)[0].isupper()
        if "ирова" in word:
            res = "игнорирование" if "ани" in word else "игнорировать"
        elif "иру" in word:
            res = "игнорирует" if "ет" in word else "игнорируют"
        elif word in ("бойкотом", "бойкоте", "бойкоту", "бойкота", "бойкот"):
            res_dict = {
                "бойкот": "молчание",
                "бойкота": "молчания",
                "бойкоту": "молчанию",
                "бойкотом": "молчанием",
                "бойкоте": "молчании",
            }
            res = res_dict.get(word, "молчание")
        else:
            res = "молчание"
        return res.capitalize() if is_cap else res

    text = re.sub(r"\bбойкот[а-яё]*\b", _replace_boycott, text, flags=re.IGNORECASE)

    # 2. Вырезание 'как договаривались', 'как мы договаривались' вместе с запятыми
    text = re.sub(r",\s*как\s+(?:мы\s+)?договаривалис[ья]\s*,", " ", text, flags=re.IGNORECASE)
    text = re.sub(r",?\s*\bкак\s+(?:мы\s+)?договаривалис[ья]\s*(?=[.?!]|$)", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^\s*как\s+(?:мы\s+)?договаривалис[ья]\s*,?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\bкак\s+(?:мы\s+)?договаривалис[ья]\b\s*,?", "", text, flags=re.IGNORECASE)

    # 3. наш... чек-ин/чекин/ритуал -> \1
    def _repl_ritual(m: re.Match) -> str:
        full_match = m.group(0)
        target = m.group(1)
        if full_match[0].isupper() and target:
            return target[0].upper() + target[1:]
        return target

    text = re.sub(
        r"\bнаш(?:его|ему|им|ем)?\s+((?:\S+\s+){0,2}(?:чек-ин\w*|чекин\w*|ритуал\w*))",
        _repl_ritual,
        text,
        flags=re.IGNORECASE,
    )

    # 4. наша... пауза -> \1
    def _repl_pause(m: re.Match) -> str:
        full_match = m.group(0)
        target = m.group(1)
        if full_match[0].isupper() and target:
            return target[0].upper() + target[1:]
        return target

    text = re.sub(
        r"\bнаш(?:а|ей|у|ею)\s+((?:\S+\s+){0,2}пауз\w*)",
        _repl_pause,
        text,
        flags=re.IGNORECASE,
    )

    # 5. наше... правило -> новое \1
    def _repl_rule(m: re.Match) -> str:
        full_match = m.group(0)
        target = m.group(1)
        prefix = "Новое " if full_match[0].isupper() else "новое "
        return prefix + target

    text = re.sub(
        r"\bнаш(?:е|его|ему|им)\s+((?:\S+\s+){0,2}правил\w*)",
        _repl_rule,
        text,
        flags=re.IGNORECASE,
    )

    # Убираем двойные пробелы и висячие знаки
    text = re.sub(r"\s{2,}", " ", text)
    text = re.sub(r"\s+([.?!,])", r"\1", text)
    return text.strip()


def sanitize_card_minor_banned_words(card: Any) -> Any:
    """Очищает поля карточки от одиночных наречий-усилителей перед валидацией и ретраями."""
    if card is None:
        return card

    if getattr(card, "validation", None):
        card.validation = sanitize_minor_banned_words(card.validation)
    if getattr(card, "partner_perspective", None):
        card.partner_perspective = sanitize_minor_banned_words(card.partner_perspective)
    if getattr(card, "blind_spot", None):
        card.blind_spot = sanitize_minor_banned_words(card.blind_spot)
    if getattr(card, "action_scripts", None):
        for s in card.action_scripts:
            if getattr(s, "text", None):
                s.text = sanitize_minor_banned_words(s.text)
            if getattr(s, "label", None):
                s.label = sanitize_minor_banned_words(s.label)
    if getattr(card, "safety_note", None):
        card.safety_note = sanitize_minor_banned_words(card.safety_note)
    return card


def sanitize_shared_minor_banned_words(shared: Any) -> Any:
    """Очищает поля общего итога от одиночных наречий-усилителей перед валидацией и ретраями."""
    if shared is None:
        return shared

    if getattr(shared, "situation_overview", None):
        shared.situation_overview = sanitize_minor_banned_words(shared.situation_overview)
    if getattr(shared, "shared_advice", None):
        shared.shared_advice = sanitize_minor_banned_words(shared.shared_advice)
    if getattr(shared, "conversation_starter", None):
        shared.conversation_starter = sanitize_minor_banned_words(shared.conversation_starter)
    return shared
