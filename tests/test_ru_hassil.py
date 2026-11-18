"""Read-only Russian FGR grammar tests against the versioned Assist/Hassil stack.

Run: python tests/test_ru_hassil.py
The full stock Russian grammar is merged with FGR's additional sentences.
"""
from __future__ import annotations

from copy import deepcopy
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
lists = {
    "name": TextSlotList.from_strings(["свет"], name="name"),
    "area": TextSlotList.from_strings(["гостиной"], name="area"),
    "floor": TextSlotList.from_strings(["первом этаже"], name="floor"),
}

CASES = [
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
NEGATIVE = ("поставь таймер на двадцать минут",
            "включи свет в гостиной",
            "установи яркость 50 процентов")

failures = []
for phrase, expected, slots in CASES:
    r = recognize_best(phrase, grammar, language="ru", slot_lists=lists, best_slot_name="name")
    got = r.intent.name if r else None
    vals = {x.name: x.value for x in r.entities_list} if r else {}
    ok = got == expected and all(
        (float(vals.get(k)) == float(v) if isinstance(v, (int, float)) and vals.get(k) is not None else vals.get(k) == v) for k, v in slots.items()
    )
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
