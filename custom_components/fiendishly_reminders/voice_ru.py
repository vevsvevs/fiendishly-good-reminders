"""Russian follow-up speech parsing for FGR.

Only used for free-form answers after assist_satellite.ask_question; normal
one-turn requests stay in Hassil. No Home Assistant dependencies.
Other languages continue to use their existing parser.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

_NUMBERS = {
    "ноль": 0, "один": 1, "одна": 1, "одну": 1, "одно": 1,
    "два": 2, "две": 2, "три": 3, "четыре": 4,
    "пять": 5, "шесть": 6, "семь": 7, "восемь": 8, "девять": 9,
    "десять": 10, "одиннадцать": 11, "двенадцать": 12,
    "тринадцать": 13, "четырнадцать": 14, "пятнадцать": 15,
    "шестнадцать": 16, "семнадцать": 17, "восемнадцать": 18,
    "девятнадцать": 19, "двадцать": 20, "тридцать": 30,
    "сорок": 40, "пятьдесят": 50, "шестьдесят": 60,
    "семьдесят": 70, "восемьдесят": 80, "девяносто": 90,
    "сто": 100, "двести": 200, "триста": 300,
}
_UNITS = {
    "сек": 1, "секунд": 1, "секунду": 1, "секунды": 1,
    "мин": 60, "минут": 60, "минуту": 60, "минуты": 60,
    "час": 3600, "часа": 3600, "часов": 3600,
    "день": 86400, "дня": 86400, "дней": 86400,
}
_WEEKDAYS = {
    "понедельник": 0, "понедельникам": 0,
    "вторник": 1, "вторникам": 1,
    "среда": 2, "среду": 2, "средам": 2,
    "четверг": 3, "четвергам": 3,
    "пятница": 4, "пятницу": 4, "пятницам": 4,
    "суббота": 5, "субботу": 5, "субботам": 5,
    "воскресенье": 6, "воскресеньям": 6,
}
_DAYPARTS = {"утром": "morning", "днем": "afternoon",
             "вечером": "evening", "ночью": "night"}


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold().replace("ё", "е")).strip()


def number(value: str) -> int | None:
    """Safely interpret decimal or descending Russian cardinal terms."""
    raw = _normalize(value)
    if raw.isdecimal():
        return int(raw)
    words = raw.split()
    if not words or len(words) > 3 or any(w not in _NUMBERS for w in words):
        return None
    parts = [_NUMBERS[w] for w in words]
    if any(a <= b for a, b in zip(parts, parts[1:])):
        return None
    if len(parts) > 1 and parts[-2] in range(10, 20):
        return None
    return sum(parts)


def _relative(s: str):
    # The free-form answer to "Когда напомнить?" must mean the same thing as
    # the one-turn Hassil slots. Test fractions *before* the integer pattern:
    # "через четыре часа с половиной" otherwise quietly loses 30 minutes.
    numeral = r"(?:\\d+|[а-я]+(?:\\s+[а-я]+){0,2})"
    unit = r"(?:секунду|секунды|секунд|сек|минуту|минуты|минут|мин|часов|часа|час|день|дня|дней)"
    fraction = r"(?:с половиной|с четвертью|с тремя четвертями)"
    fractions = {"с половиной": 0.5, "с четвертью": 0.25,
                 "с тремя четвертями": 0.75}
    for pattern_text in (
        rf"\\b(?:через|спустя)\\s+(?P<n>{numeral})\\s+(?P<f>{fraction})\\s+(?P<u>{unit})\\b",
        rf"\\b(?:через|спустя)\\s+(?P<n>{numeral})\\s+(?P<u>{unit})\\s+(?P<f>{fraction})\\b",
    ):
        for match in re.finditer(pattern_text, s):
            n = number(match.group("n"))
            if n is not None and n > 0:
                return match.start(), timedelta(
                    seconds=(n + fractions[match.group("f")]) * _UNITS[match.group("u")]
                )
    pattern = re.compile(
        r"\b(?:через|спустя)\s+(\d+|[а-я]+(?:\s+[а-я]+){0,2})\s+"
        r"(секунд(?:у|ы)?|сек|минут(?:у|ы)?|мин|час(?:а|ов)?|день|дня|дней)\b"
    )
    for m in pattern.finditer(s):
        n = number(m.group(1))
        if n is not None and n > 0:
            return m.start(), timedelta(seconds=n * _UNITS[m.group(2)])
    for phrase, seconds in (
        ("через полчаса", 1800), ("через пол часа", 1800),
        ("через полтора часа", 5400), ("через полторы минуты", 90),
        ("через четверть часа", 900),
    ):
        at = s.find(phrase)
        if at >= 0:
            return at, timedelta(seconds=seconds)
    return None


def _weekday(s: str):
    for m in re.finditer(r"\b(каждый|по|в)\s+([а-я]+)\b", s):
        if m.group(2) in _WEEKDAYS:
            return m.start(), _WEEKDAYS[m.group(2)], m.group(1) != "в"
    return None


def _clock(s: str, defaults):
    expr = re.compile(
        r"\bв\s+(\d{1,2}|[а-я]+(?:\s+(?:один|одна|два|две|три|четыре|пять|шесть|семь|восемь|девять))?)"
        r"(?::(\d{2}))?(?:\s+час(?:ов|а)?)?"
        r"(?:\s+(\d{1,2}|[а-я]+)\s+минут(?:у|ы)?)?"
        r"(?:\s+(утра|утром|дня|днем|вечера|вечером|ночи|ночью))?\b"
    )
    for m in expr.finditer(s):
        hour = number(m.group(1))
        minute = number(m.group(2) or m.group(3) or "0")
        if hour is None or minute is None or hour > 23 or minute > 59:
            continue
        part = m.group(4) or ""
        if part in ("дня", "днем", "вечера", "вечером") and hour < 12:
            hour += 12
        if part in ("утра", "утром", "ночи", "ночью") and hour == 12:
            hour = 0
        return m.start(), hour, minute
    for m in re.finditer(r"\b(утром|днем|вечером|ночью)\b", s):
        key = _DAYPARTS[m.group(1)]
        if hasattr(defaults, "of"):
            hour, minute = defaults.of(key)
        else:
            hour, minute = {"morning": (8, 15), "afternoon": (14, 0),
                            "evening": (21, 0), "night": (21, 0)}[key]
        return m.start(), hour, minute
    return None


def read_time(sentence: str, now: datetime, default_time=(8, 15)):
    """Return (leading text, due, recurrence) or None for unsupported times."""
    s = _normalize(sentence)
    relative = _relative(s)
    if relative:
        return s[:relative[0]].strip(" ,"), now + relative[1], None
    day = re.search(r"\b(сегодня|завтра|послезавтра)\b", s)
    offset = {"сегодня": 0, "завтра": 1, "послезавтра": 2}.get(day.group(1)) if day else None
    weekday = _weekday(s)
    clock = _clock(s, default_time)
    if not (day or weekday or clock):
        return s, None, None
    hour, minute = clock[1:] if clock else tuple(default_time)
    if weekday:
        delta = (weekday[1] - now.weekday()) % 7
        due = (now + timedelta(days=delta)).replace(
            hour=hour, minute=minute, second=0, microsecond=0
        )
        if due <= now:
            due += timedelta(days=7)
        rule = ("FREQ=WEEKLY;BYDAY=" + "MO TU WE TH FR SA SU".split()[weekday[1]]) if weekday[2] else None
    else:
        due = (now + timedelta(days=offset or 0)).replace(
            hour=hour, minute=minute, second=0, microsecond=0
        )
        if offset is None and due <= now:
            due += timedelta(days=1)
        elif due <= now:
            return s, None, None
        rule = None
    first = min(i for i in (day.start() if day else None,
                            weekday[0] if weekday else None,
                            clock[0] if clock else None) if i is not None)
    return s[:first].strip(" ,"), due, rule


def parse_edit_answer(sentence: str, now: datetime, default_time=(8, 15)):
    """Interpret Russian replies to the edit follow-up without altering English."""
    said = _normalize(sentence).rstrip(" .!?")
    if not said:
        return None, None, None
    name = re.match(r"^(?:измени|поменяй|замени|назови)\s+"
                    r"(?:текст|название|напоминание)\s+(?:на|в)\s+", said)
    if name:
        return said[name.end():] or None, None, None
    time = re.match(r"^(?:измени|поменяй|перенеси|поставь|установи)\s+"
                    r"(?:(?:время|дату|срок|напоминание)\s+)?(?:на|к|в)\s+", said)
    if time:
        rest = said[time.end():]
        if re.fullmatch(r"\d{1,2}(?::\d{2})?", rest):
            rest = "в " + rest
        _, due, rule = read_time(rest, now, default_time)
        return None, due, rule
    lead, due, rule = read_time(said, now, default_time)
    return ((lead or None), due, rule) if due is not None else (said, None, None)


# Speech output is rendered from the *stored* reminder and its calculated due
# datetime, never from the original STT text (which may contain word numerals).
def clock(when: datetime) -> str:
    return f"{when.hour:02d}:{when.minute:02d}"


_MONTH_GENITIVE = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)


def moment(when: datetime) -> str:
    """Russian TTS-friendly date with the month in the correct case."""
    return f"{when.day} {_MONTH_GENITIVE[when.month - 1]} {when.year} года в {clock(when)}"


def delivery_header(name: str | None = None) -> str:
    # A configured owner name has no grammatical case metadata; do not invent its genitive.
    return f"Напоминание из списка «{name}»" if name else "Напоминание"


YES_SENTENCES = ["да", "да конечно", "подтверждаю", "верно", "правильно",
                 "удали", "отмени", "отменяй", "да отмени"]
NO_SENTENCES = ["нет", "не надо", "не отменяй", "оставь", "оставить",
                "нет спасибо", "отмена", "стоп", "передумал", "передумала"]


MESSAGES = {
    "no_text": "Не удалось разобрать, о чём нужно напомнить.",
    "no_time": "Не удалось определить время напоминания.",
    "past_time": "Это время уже прошло.",
    "no_repeat": "Не удалось определить расписание повторения.",
    "repeat_invalid": "Такую периодичность установить не удалось.",
    "created": "Напоминание «{text}» установлено на {when}.",
    "recurring_created": "Повторяющееся напоминание «{text}» создано. Первое срабатывание — {when}.",
    "again_created": "Повторное напоминание «{text}» установлено на {when}.",
    "no_last": "Нет предыдущего напоминания для повторения.",
    "no_reminders": "Напоминаний нет.",
    "reminder_count": "Всего напоминаний: {count}.",
    "next_reminder": "Следующее напоминание — «{text}», {when}.",
    "list_header": "Запланировано напоминаний: {count}.",
    "list_item": "«{text}» — {when}",
    "find_empty": "Подходящих напоминаний не найдено.",
    "find_header": "Найдено напоминаний: {count}.",
    "fallback_empty": "Не удалось разобрать команду напоминания.",
    "ask_when": "Когда напомнить? Время по умолчанию — {time}.",
    "ask_when_retry": "Не удалось разобрать время. Скажите, когда напомнить.",
    "asked_when_created": "Напоминание «{text}» создано на {when}.",
    "asked_when_default": "Использовано время по умолчанию. Напоминание «{text}» создано на {when}.",
    "ask_edit": "Что изменить? Скажите «измени текст на», «перенеси на» или «замени на».",
    "ask_edit_unchanged": "Изменений нет.",
    "ask_edit_missing": "Напоминание больше не найдено.",
    "ask_edit_error": "Не удалось разобрать изменение. Напоминание не изменено.",
    "ask_edit_done": "Напоминание «{text}» изменено. Следующее срабатывание — {when}.",
    "edit_which": "Какое напоминание изменить?",
    "edit_not_found": "Напоминание для изменения не найдено.",
    "edit_ambiguous": "Найдено несколько похожих напоминаний ({count}). Уточните, какое изменить.",
    "edit_one_turn": "Напоминание «{text}» назначено на {when}. Скажите одной фразой: «перенеси напоминание про {text} на девять вечера».",
    "edit_not_recurring": "Напоминание «{text}» и так не повторяется.",
    "edit_stop_repeat": "Повторение напоминания «{text}» отключено. Следующее срабатывание — {when}.",
    "edit_bad_repeat": "Не удалось определить новое расписание повторения.",
    "edit_recurring": "Расписание напоминания «{text}» изменено. Следующее срабатывание — {when}.",
    "edit_moved": "Напоминание «{text}» перенесено на {when}.",
    "edit_moved_series": "Повторяющееся напоминание «{text}» перенесено. Следующее срабатывание — {when}.",
    "confirm_cancel": "Отменить напоминание «{text}»? Ответьте да или нет.",
    "cancel_none": "Напоминание для отмены не найдено.",
    "cancel_one": "Напоминание отменено.",
    "cancel_many": "Отменено напоминаний: {count}.",
    "not_canceled": "Отмена не подтверждена. Напоминания сохранены.",
    "skip_missing": "Напоминание для пропуска не найдено.",
    "skip_success": "Следующее срабатывание пропущено.",
    "skip_week": "Пропущено срабатываний на этой неделе: {count}.",
    "skip_end": "Последнее срабатывание пропущено. Напоминание завершено.",
    "skip_none_left": "На этой неделе больше нечего пропускать.",
    "skip_not_recurring": "Это однократное напоминание; пропустить повторение нельзя.",
    "skip_confirm": "Пропуск приведёт к отмене напоминания «{text}». Подтверждаете?",
    "no_list": "Напоминания ещё не настроены.",
    "unknown_list": "Списка напоминаний для {name} нет.",
    "which_list": "Чьи напоминания: {names}? Назовите имя.",
    "ask_whose": "Для кого это напоминание?",
    "ask_whose_read": "Чьи напоминания показать?",
    "ask_whose_retry": "Не удалось определить имя. {names}?",
    "ask_whose_failed": "Не удалось определить владельца. Напоминание не создано.",
    "ask_whose_read_failed": "Не удалось определить, чьи напоминания показать.",
    "ask_whose_created": "Напоминание «{text}» для {name} создано на {when}.",
    "not_ready": "Менеджер напоминаний ещё загружается.",
    "not_found": "Такое напоминание не найдено.",
}


def message(key: str, **values) -> str:
    return MESSAGES[key].format(**values)


# Announcements use second person, just as the original English integration does.
# Restrict replacements to complete pronouns; never change substrings of names.
_SELF_WORDS = {
    "я": "ты", "меня": "тебя", "мне": "тебе", "мной": "тобой",
    "мною": "тобою",
    "мой": "твой", "моя": "твоя", "мое": "твоё", "мои": "твои",
    "моего": "твоего", "моему": "твоему", "моем": "твоём",
    "моей": "твоей", "мою": "твою", "моим": "твоим",
    "моими": "твоими", "моих": "твоих",
    "мы": "вы", "нас": "вас", "нам": "вам", "нами": "вами",
    "наш": "ваш", "наша": "ваша", "наше": "ваше", "наши": "ваши",
    "нашего": "вашего", "нашей": "вашей", "нашу": "вашу",
    "нашим": "вашим", "наших": "ваших", "нашими": "вашими",
}
# The STT transcript may keep or omit ё (моё/мое, моём/моем).
_SELF_RE = re.compile(
    r"\b(?:" + "|".join(map(re.escape, (*_SELF_WORDS, "моё", "моём"))) + r")\b",
    re.I,
)


def second_person(text: str) -> str:
    """Convert Russian first-person pronouns in an announcement, not in storage."""
    def replace(match: re.Match) -> str:
        word = match.group(0)
        result = _SELF_WORDS[word.lower().replace("ё", "е")]
        if word.isupper():
            return result.upper()
        if word[0].isupper():
            return result[0].upper() + result[1:]
        return result

    return _SELF_RE.sub(replace, text or "")
