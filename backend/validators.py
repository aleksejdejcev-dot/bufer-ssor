"""
Модуль валидации качества сгенерированных текстов медиации (Этап 3.2).
Проверяет:
1. Длину полей и количество предложений (включая режим sparse).
2. Количество и длину скриптов действий (action_scripts) и why.
3. Проверку запрещенных терминов по стемам (snowballstemmer / pymorphy3) ко ВСЕМ строковым полям.
4. Дополнительные запреты в shared_summary (роли, местоимения, 'чай').
5. Проверку итогового вывода перед сохранением в БД.
"""

import re
from typing import List, Dict, Any, Union, Optional, Set
import snowballstemmer
from schemas import PartnerResponse, SharedSummary, ActionScriptItem, MediatorOutput
from config.banned import (
    FORBIDDEN_SINGLE_STEMS,
    FORBIDDEN_PHRASE_PATTERNS,
    FORBIDDEN_SCRIPT_PATTERNS,
    SHARED_FORBIDDEN_PATTERNS,
    HEDGE_WORDS,
    SPELL_WHITELIST,
    sanitize_minor_banned_words,
    sanitize_card_minor_banned_words,
    sanitize_shared_minor_banned_words,
)
from config.fallbacks import SPARSE_SHORTNESS_PREFIXES

stemmer = snowballstemmer.stemmer("russian")

# Обратная совместимость для тестов
GLOBAL_FORBIDDEN_PATTERNS = list(FORBIDDEN_SINGLE_STEMS) + FORBIDDEN_PHRASE_PATTERNS

_spell_morph = None


def get_spell_morph() -> Any:
    """Ленивая инициализация pymorphy3 для проверки орфографии."""
    global _spell_morph
    if _spell_morph is None:
        import pymorphy3
        _spell_morph = pymorphy3.MorphAnalyzer()
    return _spell_morph


def is_unknown_word(
    word: str,
    morph_analyzer: Optional[Any] = None,
    user_whitelist: Optional[Set[str]] = None,
) -> bool:
    """
    Проверяет, является ли слово опечаткой или неизвестным словом (Этап 3.9, 3.13).
    Учитывает белый список, слова с дефисом, приставки 'не-', 'недо-', 'со-',
    а также слова и леммы из пользовательского ввода (user_whitelist).
    """
    clean = word.lower().strip(".,!?:;\"'«»()[]{}*`~")
    if not clean or len(clean) < 3:
        return False
    if clean in SPELL_WHITELIST:
        return False
    if user_whitelist and clean in user_whitelist:
        return False

    # Проверка слов из SPELL_WHITELIST с падежными окончаниями (Этап 3.11)
    for white_prefix in ("чек-ин", "чекин", "тайм-аут", "онлайн", "офлайн"):
        if clean.startswith(white_prefix):
            suffix = clean[len(white_prefix):]
            if suffix in {"", "а", "у", "ом", "е", "ы", "ов", "ам", "ами", "ах", "ном", "не"}:
                return False

    morph = morph_analyzer or get_spell_morph()

    if user_whitelist:
        for p in morph.parse(clean):
            if p.normal_form in user_whitelist:
                return False

    if "-" in clean:
        parts = clean.split("-")
        if all(
            morph.word_is_known(p) or p in SPELL_WHITELIST or (user_whitelist and p in user_whitelist)
            for p in parts
            if len(p) >= 2
        ):
            return False

    if morph.word_is_known(clean):
        return False

    # Проверка слов с приставками 'недо-', 'не-', 'со-'
    for pfx in ("недо", "не", "со"):
        if clean.startswith(pfx) and len(clean) > len(pfx) + 2:
            stem = clean[len(pfx):]
            if (
                morph.word_is_known(stem)
                or stem in SPELL_WHITELIST
                or (user_whitelist and stem in user_whitelist)
            ):
                return False

    parses = morph.parse(clean)
    if not parses:
        return True
    return any(method[0].__class__.__name__ in ("FakeDictionary", "UnknAnalyzer") for method in parses[0].methods_stack)


def extract_user_input_words(text: str, morph_analyzer: Optional[Any] = None) -> Set[str]:
    """
    Извлекает токены, части через дефис и леммы из пользовательского текста
    для белого списка орфографии (Этап 3.13).
    """
    if not text:
        return set()
    morph = morph_analyzer or get_spell_morph()
    tokens = re.findall(r"\b[а-яёa-z0-9]+(?:-[а-яёa-z0-9]+)*\b", text.lower())
    result: Set[str] = set()
    for tok in tokens:
        clean = tok.strip(".,!?:;\"'«»()[]{}*`~")
        if not clean:
            continue
        result.add(clean)
        if "-" in clean:
            for part in clean.split("-"):
                if len(part) >= 2:
                    result.add(part)
        for p in morph.parse(clean):
            result.add(p.normal_form)
    return result


def count_sentences(text: str) -> int:
    """Подсчитывает количество предложений в тексте по разделителям (. ! ? …)."""
    if not text:
        return 0
    cleaned = text.strip()
    sentences = re.split(r"[.!?…]+(?:\s+|$)", cleaned)
    valid_sentences = [s.strip() for s in sentences if len(s.strip()) > 0]
    return len(valid_sentences)


def find_forbidden_in_string(text: str) -> List[str]:
    """
    Проверяет строку на наличие запрещенных стемов и выражений.
    Возвращает список обнаруженных нарушений.
    """
    if not text:
        return []
    found = []

    # 1. Проверка составных фраз
    for pat in FORBIDDEN_PHRASE_PATTERNS:
        match = re.search(pat, text, flags=re.IGNORECASE)
        if match:
            found.append(f"фраза '{match.group(0)}'")

    # 2. Проверка одиночных стемов по словам
    words = re.findall(r"[а-яёa-z0-9]+", text.lower())
    for w in words:
        s = stemmer.stemWord(w)
        for fs in FORBIDDEN_SINGLE_STEMS:
            if s.startswith(fs):
                found.append(f"слово '{w}' (стем: {fs})")
                break

    return list(dict.fromkeys(found))


def find_shared_forbidden(text: str) -> List[str]:
    """Ищет запрещенные паттерны ролей, местоимений и слово 'чай' в общем блоке."""
    if not text:
        return []
    found = []
    for pat in SHARED_FORBIDDEN_PATTERNS:
        match = re.search(pat, text, flags=re.IGNORECASE)
        if match:
            found.append(f"запрещенный элемент в shared: '{match.group(0)}'")
    return list(dict.fromkeys(found))


def find_script_dishonesty(text: str) -> List[str]:
    """Проверяет текст скрипта на недопустимые формулировки и надуманные эмоции (Этап 3.3)."""
    if not text:
        return []
    found = []
    for pat in FORBIDDEN_SCRIPT_PATTERNS:
        match = re.search(pat, text, flags=re.IGNORECASE)
        if match:
            found.append(f"недопустимое выражение в скрипте: '{match.group(0)}'")
    return list(dict.fromkeys(found))


def check_gender_consistency(
    validation: str,
    action_scripts: List[Any],
    morph_analyzer: Optional[Any] = None,
) -> List[str]:
    """
    Проверяет согласованность грамматического рода между validation (обращение к автору)
    и action_scripts (реплики от первого лица автора) (Этап 3.13).
    Если validation обращается к женщине (ждала, просила), а скрипт написан от мужчины (я сорвался),
    или наоборот — возвращает ошибку RoleGenderMismatch.
    """
    if not validation or not action_scripts:
        return []

    morph = morph_analyzer or get_spell_morph()

    # 1. Определение рода адресата в validation ("ты [не]? <глагол/причастие>")
    val_fem_count = 0
    val_masc_count = 0
    for m in re.finditer(
        r"\bты\s+(?:(?:не|тоже|вчера|уже|так|сильно|очень|только|просто|вновь|опять|снова|сама?)\s+){0,3}([а-яё]+)\b",
        validation,
        re.IGNORECASE,
    ):
        w = m.group(1).lower()
        parses = morph.parse(w)
        for p in parses:
            if p.tag.POS in ("VERB", "ADJF", "ADJS", "PRTS"):
                if p.tag.number == "sing":
                    if p.tag.gender == "femn":
                        val_fem_count += 1
                        break
                    elif p.tag.gender == "masc":
                        val_masc_count += 1
                        break

    val_gender = None
    if val_fem_count > 0 and val_masc_count == 0:
        val_gender = "femn"
    elif val_masc_count > 0 and val_fem_count == 0:
        val_gender = "masc"

    if not val_gender:
        return []

    # 2. Определение рода первого лица в скриптах ("я [не]? <прошедшее время/причастие/прилагательное>")
    scr_fem_count = 0
    scr_masc_count = 0
    for s in action_scripts:
        t = getattr(s, "text", None) or (s.get("text") if isinstance(s, dict) else str(s))
        if not t:
            continue
        for m in re.finditer(
            r"\bя\s+(?:(?:не|тоже|вчера|уже|так|сильно|очень|только|просто|вновь|опять|снова|сама?)\s+){0,3}([а-яё]+)\b",
            t,
            re.IGNORECASE,
        ):
            w = m.group(1).lower()
            parses = morph.parse(w)
            for p in parses:
                if p.tag.POS in ("VERB", "ADJF", "ADJS", "PRTS"):
                    if p.tag.tense == "past" or p.tag.POS in ("ADJF", "ADJS", "PRTS"):
                        if p.tag.number == "sing":
                            if p.tag.gender == "femn":
                                scr_fem_count += 1
                                break
                            elif p.tag.gender == "masc":
                                scr_masc_count += 1
                                break

    scr_gender = None
    if scr_fem_count > 0 and scr_masc_count == 0:
        scr_gender = "femn"
    elif scr_masc_count > 0 and scr_fem_count == 0:
        scr_gender = "masc"

    if scr_gender and val_gender and scr_gender != val_gender:
        return ["RoleGenderMismatch: скрипт написан от противоположного рода/лица"]

    return []


RUSSIAN_NUM_WORDS = {
    "один": 1, "одна": 1, "два": 2, "две": 2, "три": 3, "четыре": 4, "пять": 5,
    "десять": 10, "пятнадцать": 15, "пятнадцати": 15, "двадцать": 20, "двадцати": 20,
    "тридцать": 30, "тридцати": 30, "сорок": 40, "сорока": 40, "пятьдесят": 50,
}


def extract_durations(text: str) -> List[str]:
    """Извлекает нормализованные упоминания длительностей времени из текста (например, '15 мин', '30 мин')."""
    if not text:
        return []
    durations = []
    lower = text.lower()

    # Числа с единицами: 15 минут, 20 мин, 1 час, 24 часа
    matches = re.findall(r"(\d+)\s*(мин(?:ут[аы]?)?|час(?:а|ов)?|сут(?:ок|ки)?|дн(?:я|ей)?)", lower)
    for num_str, unit in matches:
        val = int(num_str)
        if "мин" in unit:
            durations.append(f"{val} мин")
        elif "час" in unit:
            durations.append(f"{val} час")
        elif "сут" in unit or "дн" in unit:
            durations.append(f"{val} сут")

    # Словесные формы
    if re.search(r"\bполчас\w*", lower):
        durations.append("30 мин")
    for word, val in RUSSIAN_NUM_WORDS.items():
        if re.search(rf"\b{word}\s+мин\w*", lower):
            durations.append(f"{val} мин")
        elif re.search(rf"\b{word}\s+час\w*", lower):
            durations.append(f"{val} час")

    return sorted(list(dict.fromkeys(durations)))


def duration_str_to_minutes(d_str: str) -> Optional[int]:
    """Преобразует строку длительности ('15 мин', '1 час') в число минут (Этап 3.10)."""
    m = re.search(r"(\d+)\s*(мин|час|сут|дн)", d_str.lower())
    if not m:
        nums = re.findall(r"\d+", d_str)
        return int(nums[0]) if nums else None
    val = int(m.group(1))
    unit = m.group(2)
    if "мин" in unit:
        return val
    elif "час" in unit:
        return val * 60
    elif "сут" in unit or "дн" in unit:
        return val * 24 * 60
    return val


def to_minute_set(durs: Any) -> Set[int]:
    """Нормализует набор длительностей (строки или числа) в множество минут (int) (Этап 3.10)."""
    if not durs:
        return set()
    res = set()
    for d in durs:
        if isinstance(d, int):
            res.add(d)
        elif isinstance(d, str):
            val = duration_str_to_minutes(d)
            if val is not None:
                res.add(val)
    return res


def are_durations_consistent(durs1: Any, durs2: Any) -> bool:
    """
    Проверяет согласованность двух наборов длительностей (Этап 3.10, 3.18).
    Нормализует в минуты (числа int) и считает согласованными, если:
    1. A == B
    2. Одно множество отличается от другого только числом, равным сумме остальных элементов (например, {10, 5} и {10, 5, 15})
    3. Сумма элементов одного равна единственному элементу другого (например, {10, 5} и {15})
    4. Одно множество содержит единственный элемент, равный максимальному элементу другого,
       при условии что остальные элементы суммируются в этот максимум (например, {10, 5, 15} и {15})
    5. Общий максимальный тайминг ритуала совпадает (например, {20} и {2, 3, 20} при разбиении на микро-шаги)
    6. Наличие общего согласованного времени ритуала (пересечение A & B не пусто)
    7. Равенство сумм микро-шагов (sum(A) == sum(B))
    8. Сумма одного множества входит в другое (sum(A) in B или sum(B) in A)
    """
    A = to_minute_set(durs1)
    B = to_minute_set(durs2)

    if not A or not B:
        return True

    # 1. Точное совпадение
    if A == B:
        return True

    # 2. Общий максимальный тайминг ритуала (например, {20} и {2, 3, 20})
    if max(A) == max(B):
        return True

    # 3. Пересечение множеств (оба партнера упоминают один и тот же основной хронометраж)
    if bool(A & B):
        return True

    # 4. Равенство сумм микро-шагов
    if sum(A) == sum(B):
        return True

    # 5. Одно множество отличается числом, равным сумме остальных элементов
    if len(B - A) == 1:
        diff_elem = next(iter(B - A))
        remaining = B - {diff_elem}
        if remaining and sum(remaining) == diff_elem:
            return True

    if len(A - B) == 1:
        diff_elem = next(iter(A - B))
        remaining = A - {diff_elem}
        if remaining and sum(remaining) == diff_elem:
            return True

    # 6. Сумма элементов одного равна любому элементу другого
    if sum(A) in B or sum(B) in A:
        return True

    # 7. Единственный элемент одного входит в другое и равен сумме остальных элементов
    if len(B) == 1 and next(iter(B)) in A:
        b_val = next(iter(B))
        rest = A - {b_val}
        if rest and sum(rest) == b_val:
            return True
    if len(A) == 1 and next(iter(A)) in B:
        a_val = next(iter(A))
        rest = B - {a_val}
        if rest and sum(rest) == a_val:
            return True

    return False


def validate_ritual_consistency(
    p1_script2_text: str,
    p2_script2_text: str,
    shared_advice_text: str,
    ritual_unfit_p1: bool = False,
    ritual_unfit_p2: bool = False,
) -> List[str]:
    """
    Валидатор согласованности параметров ритуала (Этап 3.3, 3.10, 3.18).
    Проверяет, что длительности в скриптах 2 обоих партнеров и в shared_advice согласованы.
    """
    errors: List[str] = []
    dur_p1 = set(extract_durations(p1_script2_text)) if not ritual_unfit_p1 else set()
    dur_p2 = set(extract_durations(p2_script2_text)) if not ritual_unfit_p2 else set()
    dur_sh = set(extract_durations(shared_advice_text))

    # Проверка скрипта 1 на согласованность с общим советом
    p1_consistent_sh = (
        not dur_sh
        or not dur_p1
        or are_durations_consistent(dur_sh, dur_p1)
        or bool(dur_sh & dur_p1)
    )

    # Проверка скрипта 2 на согласованность с общим советом
    p2_consistent_sh = (
        not dur_sh
        or not dur_p2
        or are_durations_consistent(dur_sh, dur_p2)
        or bool(dur_sh & dur_p2)
    )

    # Если общий совет содержит длительность и оба партнера согласованы с общим советом,
    # они считаются взаимно согласованными (даже если один расписал микро-шаги)
    if dur_sh and p1_consistent_sh and p2_consistent_sh:
        pass
    else:
        # Если в обоих скриптах указана длительность, они обязаны быть согласованы
        if dur_p1 and dur_p2 and not (are_durations_consistent(dur_p1, dur_p2) or bool(dur_p1 & dur_p2)):
            errors.append(
                f"Длительности в скриптах #2 партнеров не согласованы: P1={dur_p1} vs P2={dur_p2}. "
                "Используй длительность из ritual."
            )

    # Скрипт 1 должен согласовываться с общим советом
    if dur_sh and dur_p1 and not p1_consistent_sh:
        errors.append(
            f"Длительность в скрипте #2 партнера 1 ({dur_p1}) не совпадает с общим ритуалом ({dur_sh}). "
            "Используй длительность из ritual."
        )

    # Скрипт 2 должен согласовываться с общим советом
    if dur_sh and dur_p2 and not p2_consistent_sh:
        errors.append(
            f"Длительность в скрипте #2 партнера 2 ({dur_p2}) не совпадает с общим ритуалом ({dur_sh}). "
            "Используй длительность из ritual."
        )

    return errors


# Алиас для совместимости (Этап 3.18)
check_ritual_consistency = validate_ritual_consistency


def validate_ritual_action_scripts_consistency(
    action_scripts: List[ActionScriptItem],
    agreed_ritual: Any,
) -> List[str]:
    """
    Проверяет, что если в action_scripts упомянуты числа минут/длительности,
    они согласуются с agreed_ritual.duration_minutes (Этап 3.18).
    (Допускается совпадение, микро-шаги или отсутствие упоминания конкретных минут; явное противоречие запрещено).
    """
    errors: List[str] = []
    if not agreed_ritual:
        return errors

    target_minutes = getattr(agreed_ritual, "duration_minutes", None)
    if not target_minutes or not isinstance(target_minutes, int):
        return errors

    for idx, s in enumerate(action_scripts or [], start=1):
        text = s.text or ""
        matches = [int(m) for m in re.findall(r"\b(\d+)\s*(?:мин(?:ут[аы]?)?)\b", text, flags=re.IGNORECASE)]
        if not matches:
            continue
        # Если целевое время присутствует среди упоминаний или сумма чисел равна target_minutes — всё корректно
        if target_minutes in matches or sum(matches) == target_minutes:
            continue
        # Если все числа строго меньше target_minutes (микро-шаги ритуала) и их сумма <= target_minutes — корректно
        if all(m < target_minutes for m in matches) and sum(matches) <= target_minutes:
            continue
        # Проверяем на явное противоречие (например, указано 40 мин при ритуале 15 мин)
        for val in matches:
            if val != target_minutes and val > target_minutes:
                errors.append(
                    f"В скрипте #{idx} указано {val} минут, что противоречит согласованному ритуалу ({target_minutes} минут)"
                )
    return errors


def align_action_scripts_with_ritual(
    action_scripts: List[ActionScriptItem],
    agreed_ritual: Any,
) -> List[ActionScriptItem]:
    """
    Автовыравнивание: приводит упоминания минут в action_scripts к параметрам agreed_ritual.
    Мягко подтягивает длительность под согласованный ритуал, не повреждая микро-шаги (Этап 3.18).
    """
    if not agreed_ritual:
        return action_scripts

    target_minutes = getattr(agreed_ritual, "duration_minutes", None)
    if not target_minutes or not isinstance(target_minutes, int):
        return action_scripts

    # Определение правильного склонения слова "минута"
    if 11 <= target_minutes % 100 <= 19:
        unit_str = "минут"
    elif target_minutes % 10 == 1:
        unit_str = "минуту"
    elif target_minutes % 10 in (2, 3, 4):
        unit_str = "минуты"
    else:
        unit_str = "минут"

    target_phrase = f"{target_minutes} {unit_str}"

    aligned_scripts = []
    for s in action_scripts or []:
        text = s.text or ""
        matches = [int(m) for m in re.findall(r"\b(\d+)\s*(?:мин(?:ут[аы]?)?)\b", text, flags=re.IGNORECASE)]

        # Если целевое время уже присутствует или микро-шаги суммируются в target_minutes — текст не трогаем!
        if target_minutes in matches or (matches and sum(matches) == target_minutes):
            aligned_scripts.append(s)
            continue

        # Заменяем упоминание минут, только если оно противоречит ритуалу (больше целевого или единственный тайминг)
        def _replace_minutes(match: re.Match) -> str:
            val = int(match.group(1))
            if val != target_minutes and (val > target_minutes or len(matches) == 1):
                return target_phrase
            return match.group(0)

        new_text = re.sub(
            r"\b(\d+)\s*(?:мин(?:ут[аы]?)?)\b",
            _replace_minutes,
            text,
            flags=re.IGNORECASE,
        )

        aligned_scripts.append(ActionScriptItem(label=s.label, text=new_text))
    return aligned_scripts


def validate_partner_card(
    card: PartnerResponse,
    is_high_risk: bool = False,
    sparse: bool = False,
    not_applicable: bool = False,
) -> List[str]:
    """
    Валидация качества персональной карточки партнера (Шаг B1/B2).
    """
    errors: List[str] = []

    if is_high_risk:
        # При высоком риске проверяется только safety_note
        fb = find_forbidden_in_string(card.validation)
        if fb:
            errors.append(f"В safety message найдены запрещенные элементы: {', '.join(fb)}")
        return errors

    if not_applicable or getattr(card, "not_applicable", False) or "не подлежит разбору" in (card.validation or ""):
        # Системный отказ при нерелевантном вводе (not_applicable): пропускается без проверки полей карточки (Этап 3.16)
        return errors

    # 1. Проверка поля validation
    val_text = card.validation or ""
    val_sentences = count_sentences(val_text)

    if sparse:
        if val_sentences < 2 or val_sentences > 3:
            errors.append(f"При sparse=True в validation ожидалось 2-3 предложения, получено {val_sentences}")
        # Проверка наличия любой из пометок о краткости (Этап 3.11)
        has_shortness_note = False
        for pfx in SPARSE_SHORTNESS_PREFIXES:
            if re.search(re.escape(pfx[:25]), val_text.strip(), flags=re.IGNORECASE):
                has_shortness_note = True
                break
        if not has_shortness_note:
            for pat in [
                r"^ты\s+рассказал[ао]?\s+совсем\s+коротко",
                r"^ты\s+описал[ао]?\s+ситуаци\w*\s+совсем\s+коротко",
                r"^тво[её]\s+сообщени\w*\s+совсем\s+коротк",
                r"^ты\s+поделил(?:ся|ась|ось)\s+очень\s+кратко",
                r"скажу\s+осторожно",
            ]:
                if re.search(pat, val_text.strip(), flags=re.IGNORECASE):
                    has_shortness_note = True
                    break
        if not has_shortness_note:
            errors.append("При sparse=True в начале validation должна быть фраза: «Ты рассказал(а) совсем коротко, поэтому скажу осторожно» (или пометка о краткости)")
    else:
        if len(val_text.strip()) < 180:
            errors.append(f"Поле validation слишком короткое ({len(val_text.strip())} < 180 символов)")
        if val_sentences < 3:
            errors.append(f"В поле validation недостаточно предложений ({val_sentences} < 3)")

    fb_val = find_forbidden_in_string(val_text)
    if fb_val:
        errors.append(f"В validation обнаружены запрещенные слова: {', '.join(fb_val)}")

    # 2. Проверка поля partner_perspective
    pp_text = card.partner_perspective or ""
    pp_sentences = count_sentences(pp_text)

    if sparse:
        if pp_sentences < 1 or pp_sentences > 2:
            errors.append(f"При sparse=True в partner_perspective ожидалось 1-2 предложения, получено {pp_sentences}")
    else:
        if len(pp_text.strip()) < 180:
            errors.append(f"Поле partner_perspective слишком короткое ({len(pp_text.strip())} < 180 символов)")
        if pp_sentences < 3:
            errors.append(f"В поле partner_perspective недостаточно предложений ({pp_sentences} < 3)")

    fb_pp = find_forbidden_in_string(pp_text)
    if fb_pp:
        errors.append(f"В partner_perspective обнаружены запрещенные слова: {', '.join(fb_pp)}")

    # Проверка смягчителей в partner_perspective (Этап 3.3)
    pp_sentence_list = [s.strip() for s in re.split(r"[.!?…]+(?:\s+|$)", pp_text) if s.strip()]
    hedge_starts = 0
    for s_idx, sent in enumerate(pp_sentence_list, start=1):
        found_hedges = re.findall(r"\b(?:возможно|похоже|бывает)\b", sent, flags=re.IGNORECASE)
        if len(found_hedges) > 1:
            errors.append(f"В предложении #{s_idx} partner_perspective более одного смягчителя: {found_hedges}")
        if re.match(r"^(?:возможно|похоже|бывает)\b", sent, flags=re.IGNORECASE):
            hedge_starts += 1
    if len(pp_sentence_list) >= 3 and hedge_starts == len(pp_sentence_list):
        errors.append("Все предложения partner_perspective начинаются со слов-смягчителей, необходимо чередовать структуру")

    # 3. Проверка поля blind_spot
    bs_text = card.blind_spot or ""
    bs_sentences = count_sentences(bs_text)

    if sparse:
        if bs_sentences < 1 or bs_sentences > 2:
            errors.append(f"При sparse=True в blind_spot ожидалось 1-2 предложения, получено {bs_sentences}")
    else:
        if len(bs_text.strip()) < 180:
            errors.append(f"Поле blind_spot слишком короткое ({len(bs_text.strip())} < 180 символов)")
        if bs_sentences < 3:
            errors.append(f"В поле blind_spot недостаточно предложений ({bs_sentences} < 3)")

    fb_bs = find_forbidden_in_string(bs_text)
    if fb_bs:
        errors.append(f"В blind_spot обнаружены запрещенные слова: {', '.join(fb_bs)}")

    # 4. Проверка action_scripts
    scripts = card.action_scripts or []
    if len(scripts) != 2:
        errors.append(f"В action_scripts ожидалось ровно 2 объекта, получено {len(scripts)}")
    else:
        for idx, s in enumerate(scripts, start=1):
            s_text = s.text or ""
            s_label = s.label or ""

            if len(s_text) > 280:
                errors.append(f"Текст скрипта #{idx} превышает 280 символов ({len(s_text)} > 280)")

            fb_s = find_forbidden_in_string(s_text)
            if fb_s:
                errors.append(f"В тексте скрипта #{idx} обнаружены запрещенные слова: {', '.join(fb_s)}")

            dishonest_fb = find_script_dishonesty(s_text)
            if dishonest_fb:
                errors.append(f"В тексте скрипта #{idx} нарушена честность формулировок: {', '.join(dishonest_fb)}")

            fb_label = find_forbidden_in_string(s_label)
            if fb_label:
                errors.append(f"В label скрипта #{idx} обнаружены запрещенные слова: {', '.join(fb_label)}")

        # 4.1 Проверка согласованности грамматического рода (Этап 3.13)
        gender_errs = check_gender_consistency(val_text, scripts)
        errors.extend(gender_errs)

    # 5. Проверка safety_note (если присутствует)
    if card.safety_note:
        fb_sn = find_forbidden_in_string(card.safety_note)
        if fb_sn:
            errors.append(f"В safety_note обнаружены запрещенные слова: {', '.join(fb_sn)}")

    return errors


def validate_shared_summary(
    shared: SharedSummary,
    is_high_risk: bool = False,
    not_applicable: bool = False,
) -> List[str]:
    """
    Валидация качества общего итога для пары (Шаг C).
    """
    errors: List[str] = []
    if (
        is_high_risk
        or not_applicable
        or getattr(shared, "not_applicable", False)
        or "не подлежит разбору" in (shared.situation_overview or "")
    ):
        return errors

    overview_text = shared.situation_overview or ""
    advice_text = shared.shared_advice or ""
    starter_text = shared.conversation_starter or ""

    # Проверка количества предложений
    s_overview = count_sentences(overview_text)
    if s_overview < 2:
        errors.append(f"В situation_overview недостаточно предложений ({s_overview} < 2)")

    s_advice = count_sentences(advice_text)
    if s_advice < 2:
        errors.append(f"В shared_advice недостаточно предложений ({s_advice} < 2)")

    s_starter = count_sentences(starter_text)
    if s_starter < 1:
        errors.append(f"В conversation_starter недостаточно предложений ({s_starter} < 1)")

    # Проверка глобальных запрещенных стемов во всех полях
    for name, text in [
        ("situation_overview", overview_text),
        ("shared_advice", advice_text),
        ("conversation_starter", starter_text),
    ]:
        fb = find_forbidden_in_string(text)
        if fb:
            errors.append(f"В {name} обнаружены запрещенные слова: {', '.join(fb)}")

        sh_fb = find_shared_forbidden(text)
        if sh_fb:
            errors.append(f"В {name} обнаружены слова разделения ролей или 'ты': {', '.join(sh_fb)}")

    # Проверка строковых полей agreed_ritual
    agreed_ritual = getattr(shared, "agreed_ritual", None)
    if agreed_ritual:
        for f_name in ["name", "when", "format", "serves_partner_1_need", "serves_partner_2_need"]:
            val = getattr(agreed_ritual, f_name, None)
            if val and isinstance(val, str):
                fb_r = find_forbidden_in_string(val)
                if fb_r:
                    errors.append(f"В agreed_ritual.{f_name} обнаружены запрещенные слова: {', '.join(fb_r)}")
                sh_fb_r = find_shared_forbidden(val)
                if sh_fb_r:
                    errors.append(f"В agreed_ritual.{f_name} обнаружены слова разделения ролей или 'ты': {', '.join(sh_fb_r)}")

    return errors


def validate_full_mediator_output(
    mediator_output: MediatorOutput,
    is_sparse_p1: bool = False,
    is_sparse_p2: bool = False,
) -> List[str]:
    """Полная сквозная проверка всего агрегированного вывода перед записью в БД."""
    all_errors: List[str] = []
    if getattr(mediator_output, "not_applicable", False) or (
        mediator_output.partner_1_response
        and "не подлежит разбору" in (mediator_output.partner_1_response.validation or "")
    ):
        return all_errors

    is_high = (mediator_output.risk_level == "high")

    errs_p1 = validate_partner_card(
        mediator_output.partner_1_response,
        is_high_risk=is_high,
        sparse=is_sparse_p1,
    )
    for e in errs_p1:
        all_errors.append(f"[P1] {e}")

    errs_p2 = validate_partner_card(
        mediator_output.partner_2_response,
        is_high_risk=is_high,
        sparse=is_sparse_p2,
    )
    for e in errs_p2:
        all_errors.append(f"[P2] {e}")

    errs_sh = validate_shared_summary(
        mediator_output.shared_summary,
        is_high_risk=is_high,
    )
    for e in errs_sh:
        all_errors.append(f"[Shared] {e}")

    if not is_high:
        p1_s2 = mediator_output.partner_1_response.action_scripts[1].text if len(mediator_output.partner_1_response.action_scripts) >= 2 else ""
        p2_s2 = mediator_output.partner_2_response.action_scripts[1].text if len(mediator_output.partner_2_response.action_scripts) >= 2 else ""
        sh_adv = mediator_output.shared_summary.shared_advice or ""
        unfit_p1 = bool(mediator_output.partner_1_response.ritual_unfit)
        unfit_p2 = bool(mediator_output.partner_2_response.ritual_unfit)
        cons_errs = validate_ritual_consistency(p1_s2, p2_s2, sh_adv, unfit_p1, unfit_p2)
        for e in cons_errs:
            all_errors.append(f"[RitualConsistency] {e}")

    if mediator_output.safety_note:
        fb_note = find_forbidden_in_string(mediator_output.safety_note)
        if fb_note:
            all_errors.append(f"[SafetyNote] Запрещенные элементы: {', '.join(fb_note)}")

    return all_errors
