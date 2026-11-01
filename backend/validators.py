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


def is_unknown_word(word: str, morph_analyzer: Optional[Any] = None) -> bool:
    """
    Проверяет, является ли слово опечаткой или неизвестным словом (Этап 3.9).
    Учитывает белый список, слова с дефисом, и приставки 'не-', 'недо-', 'со-'.
    """
    clean = word.lower().strip(".,!?:;\"'«»()[]{}*`~")
    if not clean or len(clean) < 3:
        return False
    if clean in SPELL_WHITELIST:
        return False

    morph = morph_analyzer or get_spell_morph()

    if "-" in clean:
        parts = clean.split("-")
        if all(morph.word_is_known(p) or p in SPELL_WHITELIST for p in parts if len(p) >= 2):
            return False

    if morph.word_is_known(clean):
        return False

    # Проверка слов с приставками 'недо-', 'не-', 'со-'
    for pfx in ("недо", "не", "со"):
        if clean.startswith(pfx) and len(clean) > len(pfx) + 2:
            stem = clean[len(pfx):]
            if morph.word_is_known(stem) or stem in SPELL_WHITELIST:
                return False

    parses = morph.parse(clean)
    if not parses:
        return True
    return any(method[0].__class__.__name__ == "FakeDictionary" for method in parses[0].methods_stack)


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
    Проверяет согласованность двух наборов длительностей (Этап 3.10).
    Нормализует в минуты (числа int) и считает согласованными, если:
    1. A == B
    2. Одно множество отличается от другого только числом, равным сумме остальных элементов (например, {10, 5} и {10, 5, 15})
    3. Сумма элементов одного равна единственному элементу другого (например, {10, 5} и {15})
    4. Одно множество содержит единственный элемент, равный максимальному элементу другого,
       при условии что остальные элементы суммируются в этот максимум (например, {10, 5, 15} и {15})
    """
    A = to_minute_set(durs1)
    B = to_minute_set(durs2)

    if not A or not B:
        return True

    # 1. Точное совпадение
    if A == B:
        return True

    # 2. Одно множество отличается числом, равным сумме остальных элементов
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

    # 3. Сумма элементов одного равна единственному элементу другого
    if len(B) == 1 and sum(A) == next(iter(B)):
        return True
    if len(A) == 1 and sum(B) == next(iter(A)):
        return True

    # 4. Единственный элемент одного входит в другое и равен сумме остальных элементов
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
    Валидатор согласованности параметров ритуала (Этап 3.3, 3.10).
    Проверяет, что длительности в скриптах 2 обоих партнеров и в shared_advice согласованы.
    """
    errors: List[str] = []
    dur_p1 = set(extract_durations(p1_script2_text)) if not ritual_unfit_p1 else set()
    dur_p2 = set(extract_durations(p2_script2_text)) if not ritual_unfit_p2 else set()
    dur_sh = set(extract_durations(shared_advice_text))

    # Если в обоих скриптах указана длительность, они обязаны быть согласованы
    if dur_p1 and dur_p2 and not are_durations_consistent(dur_p1, dur_p2):
        errors.append(f"Длительности в скриптах #2 партнеров не согласованы: P1={dur_p1} vs P2={dur_p2}. Используй длительность из ritual.")

    # Скрипт 1 должен согласовываться с общим советом
    if dur_sh and dur_p1 and not (are_durations_consistent(dur_sh, dur_p1) or bool(dur_sh & dur_p1)):
        errors.append(f"Длительность в скрипте #2 партнера 1 ({dur_p1}) не совпадает с общим ритуалом ({dur_sh}). Используй длительность из ritual.")

    # Скрипт 2 должен согласовываться с общим советом
    if dur_sh and dur_p2 and not (are_durations_consistent(dur_sh, dur_p2) or bool(dur_sh & dur_p2)):
        errors.append(f"Длительность в скрипте #2 партнера 2 ({dur_p2}) не совпадает с общим ритуалом ({dur_sh}). Используй длительность из ritual.")

    return errors


def validate_ritual_action_scripts_consistency(
    action_scripts: List[ActionScriptItem],
    agreed_ritual: Any,
) -> List[str]:
    """
    Проверяет, что если в action_scripts упомянуты числа минут/длительности,
    они согласуются с agreed_ritual.duration_minutes.
    (Допускается совпадение или отсутствие упоминания конкретных минут; противоречие запрещено).
    """
    errors: List[str] = []
    if not agreed_ritual:
        return errors

    target_minutes = getattr(agreed_ritual, "duration_minutes", None)
    if not target_minutes or not isinstance(target_minutes, int):
        return errors

    for idx, s in enumerate(action_scripts or [], start=1):
        text = s.text or ""
        matches = re.findall(r"\b(\d+)\s*(?:мин(?:ут[аы]?)?)\b", text, flags=re.IGNORECASE)
        for m in matches:
            val = int(m)
            if val != target_minutes:
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
        def _replace_minutes(match):
            val = int(match.group(1))
            if val != target_minutes:
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

    # 1. Проверка поля validation
    val_text = card.validation or ""
    val_sentences = count_sentences(val_text)

    if sparse:
        if val_sentences != 2:
            errors.append(f"При sparse=True в validation ожидалось ровно 2 предложения, получено {val_sentences}")
        if not re.search(r"^ты\s+рассказал[ао]?\s+совсем\s+коротко,\s+поэтому\s+скажу\s+осторожно", val_text.strip(), re.IGNORECASE):
            errors.append("При sparse=True в начале validation должна быть фраза: «Ты рассказал(а) совсем коротко, поэтому скажу осторожно»")
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
        if bs_sentences != 1:
            errors.append(f"При sparse=True в blind_spot ожидалось ровно 1 предложение, получено {bs_sentences}")
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

    # 5. Проверка safety_note (если присутствует)
    if card.safety_note:
        fb_sn = find_forbidden_in_string(card.safety_note)
        if fb_sn:
            errors.append(f"В safety_note обнаружены запрещенные слова: {', '.join(fb_sn)}")

    return errors


def validate_shared_summary(shared: SharedSummary, is_high_risk: bool = False) -> List[str]:
    """
    Валидация качества общего итога для пары (Шаг C).
    """
    errors: List[str] = []
    if is_high_risk:
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
