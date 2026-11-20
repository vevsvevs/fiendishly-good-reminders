"""Read-only Russian FGR grammar tests against the versioned Assist/Hassil stack.

Run: python tests/test_ru_hassil.py
The full stock Russian grammar is merged with FGR's additional sentences.
"""
from __future__ import annotations

from copy import deepcopy
import importlib.util
from pathlib import Path
import sys
import yaml
from home_assistant_intents import get_intents
from hassil import Intents, recognize_best
from hassil.intents import TextSlotList

ROOT = Path(__file__).resolve().parent.parent
SENTENCES = ROOT / "custom_sentences" / "ru" / "reminders.yaml"
data = yaml.safe_load(SENTENCES.read_text(encoding="utf-8"))
assert data["language"] == "ru"
base = deepcopy(get_intents("ru"))
for key, value in data.get("lists", {}).items():
    base.setdefault("lists", {})[key] = value
for key, value in data.get("expansion_rules", {}).items():
    base.setdefault("expansion_rules", {})[key] = value
for key, value in data.get("intents", {}).items():
    base.setdefault("intents", {}).setdefault(key, {"data": []})["data"].extend(value["data"])
grammar = Intents.from_dict(base)
# In the live handler an owner swallowed by {reminder_text} / {fallback_rest}
# is recovered before any destructive operation. Exercise the same pure helper.
SRC = ROOT / "custom_components" / "fiendishly_reminders" / "voice_ru.py"
spec = importlib.util.spec_from_file_location("voice_ru_check", SRC)
ru = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ru)
KNOWN_OWNERS = ["Виталий", "Мария", "Анна", "Сергей"]

lists = {
    "name": TextSlotList.from_strings(["свет"], name="name"),
    "area": TextSlotList.from_strings(["гостиной"], name="area"),
    "floor": TextSlotList.from_strings(["первом этаже"], name="floor"),
}

CASES = [
    # Russian case endings and close variants of the phrase seen in Assist.
    ("расскажи о напоминаниях", "CustomReminderList", {}),
    ("расскажи мне о моих напоминаниях", "CustomReminderList", {}),
    ("расскажите обо всех моих напоминаниях", "CustomReminderList", {}),
    ("скажи об активных напоминаниях", "CustomReminderList", {}),
    ("мои напоминания пожалуйста", "CustomReminderList", {}),
    ("расскажи о напоминаниях у меня", "CustomReminderList", {}),
    ("расскажи о напоминаниях Виталия", "CustomReminderList", {"person": "Виталия"}),
    ("расскажи мне о напоминаниях у Марии", "CustomReminderList", {"person": "Марии"}),
    ("расскажи о напоминаниях на завтра", "CustomReminderFind", {"when_kind": "tomorrow"}),
    ("скажи о моих напоминаниях на сегодня", "CustomReminderFind", {"when_kind": "today"}),
    ("расскажи о завтрашних напоминаниях", "CustomReminderFind", {"when_kind": "tomorrow"}),
    ("прочитай сегодняшние напоминания", "CustomReminderFind", {"when_kind": "today"}),
    ("расскажи какие у меня есть напоминания на выходные", "CustomReminderFind", {"when_kind": "weekend"}),
    ("расскажи о напоминаниях у Марии на завтра", "CustomReminderFind", {"person": "Марии", "when_kind": "tomorrow"}),
    ("расскажи о напоминаниях на завтра у Марии", "CustomReminderFind", {"person": "Марии", "when_kind": "tomorrow"}),
    ("расскажи о напоминаниях Виталия на завтра", "CustomReminderFind", {"person": "Виталия", "when_kind": "tomorrow"}),
    ("расскажи о завтрашних напоминаниях Виталия", "CustomReminderFind", {"person": "Виталия", "when_kind": "tomorrow"}),
    ("расскажи о напоминаниях Виталия в пятницу", "CustomReminderFind", {"person": "Виталия", "weekday": 4}),
    ("расскажи о напоминаниях у меня на завтра", "CustomReminderFind", {"when_kind": "tomorrow"}),
    ("расскажи о напоминаниях в пятницу", "CustomReminderFind", {"weekday": 4}),
    ("скажи сколько у меня осталось напоминаний", "CustomReminderCount", {}),
    ("скажи сколько всего напоминаний у Марии", "CustomReminderCount", {"person": "Марии"}),
    ("расскажи какие у Марии напоминания на завтра", "CustomReminderFind", {"person": "Марии", "when_kind": "tomorrow"}),
    ("расскажи какие у Марии напоминания", "CustomReminderList", {"person": "Марии"}),
    ("скажи сколько у Марии напоминаний", "CustomReminderCount", {"person": "Марии"}),
    ("расскажи сколько у Марии напоминаний на завтра", "CustomReminderCount", {"person": "Марии", "when_kind": "tomorrow"}),
    ("расскажи о ближайшем напоминании", "CustomReminderNext", {}),
    ("скажи о моём следующем напоминании", "CustomReminderNext", {}),
    ("расскажи о ближайшем напоминании Виталия", "CustomReminderNext", {"person": "Виталия"}),
    ("когда сработает ближайшее напоминание", "CustomReminderNext", {}),
    ("когда у меня сработает следующее напоминание", "CustomReminderNext", {}),
    ("скажи во сколько сработает ближайшее напоминание", "CustomReminderNext", {}),
    ("расскажи о напоминании про врача", "CustomReminderFind", {"reminder_text": "врача"}),
    ("расскажи о напоминании о встрече у Марии", "CustomReminderFind", {"reminder_text": "встрече", "person": "Марии"}),
    # Natural spoken reads, with exact scoping checked below.
    ("что у меня с напоминаниями", "CustomReminderList", {}),
    ("что там у меня с напоминаниями", "CustomReminderList", {}),
    ("что у меня из напоминаний", "CustomReminderList", {}),
    ("расскажи что у меня с напоминаниями", "CustomReminderList", {}),
    ("расскажи про мои напоминания", "CustomReminderList", {}),
    ("расскажи какие у меня есть напоминания", "CustomReminderList", {}),
    ("озвучь все мои напоминания", "CustomReminderList", {}),
    ("зачитай список моих напоминаний", "CustomReminderList", {}),
    ("что у меня в списке напоминаний", "CustomReminderList", {}),
    ("у меня есть напоминания", "CustomReminderList", {}),
    ("есть ли у меня какие-нибудь напоминания", "CustomReminderList", {}),
    ("какие напоминания у меня", "CustomReminderList", {}),
    ("сколько напоминаний у меня на завтра", "CustomReminderCount", {"when_kind": "tomorrow"}),
    ("когда ближайшее напоминание у меня", "CustomReminderNext", {}),
    ("какие напоминания у меня стоят", "CustomReminderList", {}),
    ("расскажи про напоминания Виталия", "CustomReminderList", {"person": "Виталия"}),
    ("что у Марии с напоминаниями", "CustomReminderList", {"person": "Марии"}),
    ("какие у Марии напоминания", "CustomReminderList", {"person": "Марии"}),
    ("прочитай напоминания из списка Марии", "CustomReminderList", {"person": "Марии"}),
    ("озвучь моё ближайшее напоминание", "CustomReminderNext", {}),
    ("о чём у меня следующее напоминание", "CustomReminderNext", {}),
    ("во сколько будет ближайшее напоминание", "CustomReminderNext", {}),
    ("назови ближайшее напоминание Виталия", "CustomReminderNext", {"person": "Виталия"}),
    ("когда у Марии будет следующее напоминание", "CustomReminderNext", {"person": "Марии"}),
    ("сколько всего активных напоминаний у меня", "CustomReminderCount", {}),
    ("сколько у Марии запланированных напоминаний", "CustomReminderCount", {"person": "Марии"}),
    ("сколько у меня напоминаний на завтра", "CustomReminderCount", {"when_kind": "tomorrow"}),
    ("сколько напоминаний у Марии на выходные", "CustomReminderCount", {"person": "Марии", "when_kind": "weekend"}),
    ("сколько напоминаний у меня в пятницу", "CustomReminderCount", {"weekday": 4}),
    ("сколько у Марии напоминаний в понедельник", "CustomReminderCount", {"person": "Марии", "weekday": 0}),
    ("сколько напоминаний сегодня у Марии", "CustomReminderCount", {"person": "Марии", "when_kind": "today"}),
    ("когда сработает напоминание об оплате", "CustomReminderFind", {"reminder_text": "оплате"}),
    ("есть ли у меня напоминание про врача", "CustomReminderFind", {"reminder_text": "врача"}),
    ("расскажи про напоминание о враче", "CustomReminderFind", {"reminder_text": "враче"}),
    ("во сколько напоминание о враче у Марии", "CustomReminderFind", {"person": "Марии", "reminder_text": "враче"}),
    ("напоминания на сегодня есть", "CustomReminderFind", {"when_kind": "today"}),
    ("есть напоминания на сегодня", "CustomReminderFind", {"when_kind": "today"}),
    ("что за напоминания у меня сегодня", "CustomReminderFind", {"when_kind": "today"}),
    ("какие напоминания у меня на сегодня", "CustomReminderFind", {"when_kind": "today"}),
    ("сегодня какие у меня напоминания", "CustomReminderFind", {"when_kind": "today"}),
    ("расскажи про мои напоминания на завтра", "CustomReminderFind", {"when_kind": "tomorrow"}),
    ("озвучь мои напоминания на послезавтра", "CustomReminderFind", {"when_kind": "day_after_tomorrow"}),
    ("есть ли у меня напоминания на выходные", "CustomReminderFind", {"when_kind": "weekend"}),
    ("что у меня с напоминаниями на этой неделе", "CustomReminderFind", {"when_kind": "week"}),
    ("какие напоминания у меня запланированы на следующую неделю", "CustomReminderFind", {"when_kind": "nextweek"}),
    ("что у меня в списке напоминаний в этом месяце", "CustomReminderFind", {"when_kind": "month"}),
    ("перечисли напоминания на следующий месяц", "CustomReminderFind", {"when_kind": "nextmonth"}),
    ("что у Марии с напоминаниями на завтра", "CustomReminderFind", {"person": "Марии", "when_kind": "tomorrow"}),
    ("завтра какие напоминания у Марии", "CustomReminderFind", {"person": "Марии", "when_kind": "tomorrow"}),
    ("какие напоминания у Марии завтра", "CustomReminderFind", {"person": "Марии", "when_kind": "tomorrow"}),
    ("есть ли у Марии напоминания на завтра", "CustomReminderFind", {"person": "Марии", "when_kind": "tomorrow"}),
    ("озвучь напоминания на завтра из списка Марии", "CustomReminderFind", {"person": "Марии", "when_kind": "tomorrow"}),
    ("какие у меня напоминания во вторник", "CustomReminderFind", {"weekday": 1}),
    ("прочитай напоминания у Марии на пятницу", "CustomReminderFind", {"person": "Марии", "weekday": 4}),
    # Owner-scoped Russian commands: every operation must yield a distinct person slot.
    ("напомни купить молоко через два часа для Марии", "CustomReminderFallback", {"person": "Марии", "fallback_rest": "купить молоко через два часа"}),
    ("напомни Виталию про молоко через два часа", "CustomReminderSet", {"person": "Виталию", "reminder_text": "молоко", "rel_num": 2}),
    ("напоминай пить воду каждый день для Марии", "CustomReminderRecurring", {"person": "Марии", "recur": "daily"}),
    ("удали напоминание про молоко у Виталия", "CustomReminderCancel", {"person": "Виталия", "reminder_text": "молоко"}),
    ("отмени у Марии напоминание про воду", "CustomReminderCancel", {"person": "Марии", "reminder_text": "воду"}),
    ("удали напоминание Виталия про молоко", "CustomReminderCancel", {"person": "Виталия", "reminder_text": "молоко"}),
    ("удали последнее напоминание у Виталия", "CustomReminderCancel", {"person": "Виталия", "use_last": 1}),
    ("удали напоминание у Марии в девять вечера", "CustomReminderCancelAt", {"person": "Марии", "hour": 9, "ampm": "pm"}),
    ("удали все напоминания Виталия", "CustomReminderCancelAll", {"person": "Виталия"}),
    ("удали все напоминания у Марии", "CustomReminderCancelAll", {"person": "Марии"}),
    ("очисти список напоминаний Виталия", "CustomReminderCancelAll", {"person": "Виталия"}),
    ("покажи напоминания Виталия", "CustomReminderList", {"person": "Виталия"}),
    ("покажи напоминания у Марии", "CustomReminderList", {"person": "Марии"}),
    ("какое следующее напоминание у Виталия", "CustomReminderNext", {"person": "Виталия"}),
    ("сколько напоминаний у Марии", "CustomReminderCount", {"person": "Марии"}),
    ("когда напоминание про воду у Виталия", "CustomReminderFind", {"person": "Виталия", "reminder_text": "воду"}),
    ("измени напоминание про воду у Марии", "CustomReminderEdit", {"person": "Марии", "reminder_text": "воду"}),
    ("пропусти следующее напоминание про воду у Виталия", "CustomReminderSkip", {"person": "Виталия", "reminder_text": "воду"}),
    ("напомни Виталию еще раз через два часа", "CustomReminderAgain", {"person": "Виталию", "rel_num": 2}),
    # Mass deletion must be handled locally by a *separate*, fail-closed intent.
    ("Удали все напоминания", "CustomReminderCancelAll", {}),
    ("отмени все мои напоминания", "CustomReminderCancelAll", {}),
    ("сотри вообще все запланированные напоминания", "CustomReminderCancelAll", {}),
    ("очисти список напоминаний", "CustomReminderCancelAll", {}),
    ("удали каждое напоминание", "CustomReminderCancelAll", {}),
    ("удали напоминания полностью", "CustomReminderCancelAll", {}),
    # Time-first user utterance from the provided Assist log. It must never reach Codex.
    ("Через четыре с половиной часа напомни покормить малыша", "CustomReminderSet",
     {"reminder_text": "покормить малыша", "rel_num": 4, "rel_unit": "hours", "rel_fraction": "half"}),
    ("Напомни через четыре с половиной часа покормить малыша", "CustomReminderSet",
     {"reminder_text": "покормить малыша", "rel_num": 4, "rel_unit": "hours", "rel_fraction": "half"}),
    ("через 4 часа напомни покормить малыша", "CustomReminderSet",
     {"reminder_text": "покормить малыша", "rel_num": 4, "rel_unit": "hours"}),
    ("спустя пять с половиной минут напомни выключить духовку", "CustomReminderSet",
     {"reminder_text": "выключить духовку", "rel_num": 5, "rel_fraction": "half", "rel_unit": "minutes"}),
    ("через четыре часа с половиной напомни купить молоко", "CustomReminderSet",
     {"reminder_text": "купить молоко", "rel_num": 4, "rel_fraction": "half", "rel_unit": "hours"}),
    ("через семь с четвертью часов напомни выпить воду", "CustomReminderSet",
     {"reminder_text": "выпить воду", "rel_num": 7, "rel_fraction": "quarter", "rel_unit": "hours"}),
    ("через полчаса напомни полить цветы", "CustomReminderSet",
     {"reminder_text": "полить цветы", "rel_num": 30, "rel_unit": "minutes"}),
    ("через пятнадцать минут напомни позвонить", "CustomReminderSet",
     {"reminder_text": "позвонить", "rel_num": 15, "rel_unit": "minutes"}),
    ("завтра в девять вечера напомни позвонить", "CustomReminderSet",
     {"reminder_text": "позвонить", "day_offset": 1, "hour": 9, "ampm": "pm"}),
    ("завтра в 21:30 напомни позвонить", "CustomReminderSet",
     {"reminder_text": "позвонить", "day_offset": 1, "hour": 21, "minute": 30}),
    ("послезавтра утром напомни записаться к врачу", "CustomReminderSet",
     {"reminder_text": "записаться к врачу", "day_offset": 2, "daypart": "morning"}),
    ("в понедельник напомни полить цветы", "CustomReminderSet",
     {"reminder_text": "полить цветы", "weekday": 0}),
    ("в пятницу вечером напомни проверить почту", "CustomReminderSet",
     {"reminder_text": "проверить почту", "weekday": 4, "daypart": "evening"}),
    ("каждый день напоминай пить воду", "CustomReminderRecurring",
     {"reminder_text": "пить воду", "recur": "daily"}),
    ("каждую пятницу напоминай выносить мусор", "CustomReminderRecurring",
     {"reminder_text": "выносить мусор", "weekday": 4, "recur": "weekly"}),
    # Exact user utterance: 4.5 hours must resolve to a SET intent, not fallback.
    ("Напомни покормить малыша через четыре с половиной часа", "CustomReminderSet", {"reminder_text": "покормить малыша", "rel_num": 4, "rel_unit": "hours", "rel_fraction": "half"}),
    ("напомни через 4 с половиной часа покормить малыша", "CustomReminderSet", {"rel_num": 4, "rel_unit": "hours", "rel_fraction": "half"}),
    ("напомни проверить почту через восемь с половиной часов", "CustomReminderSet", {"rel_num": 8, "rel_unit": "hours", "rel_fraction": "half"}),
    ("напомни купить хлеб через два с половиной дня", "CustomReminderSet", {"rel_num": 2, "rel_unit": "days", "rel_fraction": "half"}),
    ("напомни выпить воду через пять с половиной минут", "CustomReminderSet", {"rel_num": 5, "rel_unit": "minutes", "rel_fraction": "half"}),
    ("напомни через 17 минут с половиной проверить чайник", "CustomReminderSet", {"rel_num": 17, "rel_unit": "minutes", "rel_fraction": "half"}),
    ("напомни позвонить спустя два с четвертью часа", "CustomReminderSet", {"rel_num": 2, "rel_unit": "hours", "rel_fraction": "quarter"}),
    ("напомни проверить плиту через три с тремя четвертями часа", "CustomReminderSet", {"rel_num": 3, "rel_unit": "hours", "rel_fraction": "three_quarters"}),
    ("напомни еще раз через четыре с половиной часа", "CustomReminderAgain", {"rel_num": 4, "rel_unit": "hours", "rel_fraction": "half"}),
    ("напомни завтра в 9 купить хлеб", "CustomReminderSet", {"day_offset": 1, "hour": 9}),
    ("напомни проверить плиту через пару минут", "CustomReminderSet", {"rel_num": 2, "rel_unit": "minutes"}),
    ("напомни купить воду через часик", "CustomReminderSet", {"rel_num": 1, "rel_unit": "hours"}),
    ("напомни позвонить в восемь", "CustomReminderSet", {"hour": 8}),
    ("напомни выгулять собаку во вторник", "CustomReminderSet", {"weekday": 1}),
    ("напоминай пить таблетки каждую пятницу", "CustomReminderRecurring", {"recur": "weekly", "weekday": 4}),
    ("напоминай покупать хлеб по вторникам в девять утра", "CustomReminderRecurring", {"recur": "weekly", "weekday": 1, "hour": 9, "ampm": "am"}),
    ("напоминай поливать цветы ежедневно в девять", "CustomReminderRecurring", {"recur": "daily", "hour": 9}),
    ("напоминай принимать витамины каждый день вечером", "CustomReminderRecurring", {"recur": "daily", "daypart": "evening"}),
    ("напомни проверить почту завтра вечером", "CustomReminderSet", {"day_offset": 1, "daypart": "evening"}),
    ("напомни сходить к врачу через полтора часа", "CustomReminderSet", {"rel_num": 90, "rel_unit": "minutes"}),
    ("напомни купить молоко через двадцать минут", "CustomReminderSet", {"rel_num": 20, "rel_unit": "minutes"}),
    ("напомни через 5 минут купить молоко", "CustomReminderSet", {"rel_num": 5, "rel_unit": "minutes"}),
    ("напомни позвонить через полчаса", "CustomReminderSet", {"rel_num": 30, "rel_unit": "minutes"}),
    ("напомни через полторы минуты проверить плиту", "CustomReminderSet", {"rel_num": 90, "rel_unit": "seconds"}),
    ("напомни вынести мусор завтра в девять вечера", "CustomReminderSet", {"day_offset": 1, "hour": 9, "ampm": "pm"}),
    ("напомни завтра в 21:30 позвонить", "CustomReminderSet", {"day_offset": 1, "hour": 21, "minute": 30}),
    ("напомни проверить духовку послезавтра утром", "CustomReminderSet", {"day_offset": 2, "daypart": "morning"}),
    ("напомни выгулять собаку в понедельник", "CustomReminderSet", {"weekday": 0}),
    ("напоминай пить воду каждый день", "CustomReminderRecurring", {"recur": "daily"}),
    ("напоминай гулять по будням", "CustomReminderRecurring", {"recur": "weekdays"}),
    ("напоминай отдыхать по выходным", "CustomReminderRecurring", {"recur": "weekends"}),
    ("напоминай выносить мусор каждый вторник", "CustomReminderRecurring", {"recur": "weekly", "weekday": 1}),
    ("напоминай платить за квартиру каждого 15 числа", "CustomReminderRecurring", {"recur": "monthly", "monthday": 15}),
    ("отмени напоминание про молоко", "CustomReminderCancel", {}),
    ("пропусти следующее напоминание про витамины", "CustomReminderSkip", {"scope": "next"}),
    ("покажи мои напоминания", "CustomReminderList", {}),
    ("когда ближайшее напоминание", "CustomReminderNext", {}),
    ("сколько у меня напоминаний", "CustomReminderCount", {}),
    ("какие у меня напоминания завтра", "CustomReminderFind", {"when_kind": "tomorrow"}),
    ("измени напоминание про зубного", "CustomReminderEdit", {"edit_ask": "yes"}),
    ("напомни еще раз через пять минут", "CustomReminderAgain", {"rel_num": 5}),
]
# Must not be claimed by the reminder grammar:
NEGATIVE = (
    "что мне нужно сделать завтра",
    "что мне делать на этой неделе",
    "что у меня с таймерами",
    "расскажи про дела на завтра",
    "расскажи о таймерах",
    "расскажи о настройках напоминаний",
    "скажи сколько времени осталось на таймере",
    "перечисли покупки на выходные",
    "поставь таймер на двадцать минут",
    "через четыре с половиной часа включи свет в гостиной",
    "завтра в девять включи свет в гостиной",
    "каждый день включай свет в гостиной",
    "через полчаса поставь таймер на десять минут",
    "удали все задачи из списка покупок",
    "удали все покупки Марии",
    "покажи список покупок Виталия",
    "выключи свет у Марии",
    "перенеси встречу Виталия на завтра",
    "очисти список дел",
    "включи свет в гостиной",
    "установи яркость 50 процентов",
)

failures = []
for phrase, expected, slots in CASES:
    r = recognize_best(phrase, grammar, language="ru", slot_lists=lists, best_slot_name="name")
    got = r.intent.name if r else None
    vals = {x.name: x.value for x in r.entities_list} if r else {}
    if got and got.startswith("CustomReminder") and "person" not in vals:
        for field in ("reminder_text", "fallback_rest"):
            if field in vals:
                owner, cleaned = ru.extract_owner_clause(
                    str(vals[field]), KNOWN_OWNERS, strict=got in (
                        "CustomReminderCancel", "CustomReminderCancelAt",
                        "CustomReminderEdit", "CustomReminderSkip"))
                if owner:
                    vals["person"] = owner
                    vals[field] = cleaned
                    break
    ok = got == expected and all(
        (float(vals.get(k)) == float(v) if isinstance(v, (int, float)) and vals.get(k) is not None else vals.get(k) == v) for k, v in slots.items()
    )
    if expected in ("CustomReminderList", "CustomReminderNext", "CustomReminderCount", "CustomReminderFind"):
        ok = ok and vals.keys() == slots.keys()
    if not ok:
        failures.append((phrase, got, vals, expected, slots))
    else:
        print("PASS", repr(phrase), "=>", expected)
for phrase in NEGATIVE:
    r = recognize_best(phrase, grammar, language="ru", slot_lists=lists, best_slot_name="name")
    got = r.intent.name if r else None
    if got and got.startswith("CustomReminder"):
        failures.append((phrase, got, {}, "not a reminder", {}))
for row in failures:
    print("FAIL", row)
print(f"RESULT {len(CASES) + len(NEGATIVE) - len(failures)}/{len(CASES) + len(NEGATIVE)}")
sys.exit(bool(failures))
