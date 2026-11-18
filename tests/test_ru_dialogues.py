"""Russian FGR satellite dialogue and speech-language integration tests."""
import sys, types, datetime, importlib.util, asyncio

for name in ["homeassistant","homeassistant.core","homeassistant.exceptions",
             "homeassistant.helpers","homeassistant.helpers.storage","homeassistant.util",
             "homeassistant.util.dt","homeassistant.helpers.entity_registry",
             "homeassistant.helpers.intent","dateutil","dateutil.rrule"]:
    sys.modules.setdefault(name, types.ModuleType(name))
sys.modules["homeassistant.core"].HomeAssistant=object
class _HAError(Exception): pass
sys.modules["homeassistant.exceptions"].HomeAssistantError=_HAError
sys.modules["homeassistant.helpers.storage"].Store=object
sys.modules["homeassistant.helpers"].entity_registry=sys.modules["homeassistant.helpers.entity_registry"]
sys.modules["homeassistant.helpers"].intent=sys.modules["homeassistant.helpers.intent"]
class _IH: pass
sys.modules["homeassistant.helpers.intent"].IntentHandler=_IH
sys.modules["homeassistant.helpers.intent"].Intent=object
sys.modules["homeassistant.helpers.intent"].IntentResponse=object
sys.modules["homeassistant.helpers.intent"].async_register=lambda *a: None
LOCAL=datetime.timezone(datetime.timedelta(hours=-7))
dt=sys.modules["homeassistant.util.dt"]
dt.DEFAULT_TIME_ZONE=LOCAL; dt.parse_datetime=lambda v: None; dt.parse_time=lambda v: None
dt.now=lambda: datetime.datetime(2026,9,6,14,0,tzinfo=LOCAL); dt.as_local=lambda d: d
import dateutil.rrule as _rr
_rr.rrulestr=lambda *a, **k: None

import os, pathlib
# Set FGR_SRC to test a copy somewhere else - a live /config, say. Otherwise this
# checkout is what gets tested.
SRC = pathlib.Path(os.environ.get("FGR_SRC") or
                   pathlib.Path(__file__).resolve().parent.parent
                   / "custom_components" / "fiendishly_reminders")
pkg=types.ModuleType("fr"); pkg.__path__=[str(SRC)]
sys.modules["fr"]=pkg
for m in ("const","store","intents"):
    sp=importlib.util.spec_from_file_location("fr."+m, SRC / f"{m}.py")
    mod=importlib.util.module_from_spec(sp); sys.modules["fr."+m]=mod; sp.loader.exec_module(mod)
it=sys.modules["fr.intents"]
it.ASK_SETTLE=0                      # the test is about repeats, not about waiting

DUE=datetime.datetime(2026,9,7,17,0,tzinfo=LOCAL)


class FakeReminder:
    recurring=False; every_base=""; every_bound=""
    def __init__(self,due): self.due=due

class FakeManager:
    def __init__(self,name,entry_id):
        self.name=name; self.scheduled=[]
        self.entry=types.SimpleNamespace(entry_id=entry_id)
    def schedule(self,text,due,rrule=None, language=None):
        self.scheduled.append(text); return FakeReminder(due)

class FakeHass:
    """Answers ask_question from a script of replies, and records what was said.

    A reply of None raises, which is what a turn that ended in silence does. A string
    reply is a raw transcript; a dict is a matched answer.
    """
    def __init__(self,replies):
        self.replies=list(replies); self.asked=[]; self.announced=[]
        self.services=self
    async def async_call(self,domain,service,data,**kw):
        if service=="ask_question":
            self.asked.append(data["question"])
            reply=self.replies.pop(0) if self.replies else None
            if reply is None:
                raise _HAError("No answer from question")
            return {"sentence": reply} if isinstance(reply, str) else reply
        if service=="announce":
            self.announced.append(data["message"])
        return None


# Exercise real dialogue functions, not just the message catalog.
it.ASK_REPEATS = 3
dt.parse_datetime = datetime.datetime.fromisoformat

class Rem:
    def __init__(self, text="полить цветы", due=DUE, ident="r1", rrule=None, language="ru"):
        self.text=text; self.due=due; self.id=ident; self.recurring=bool(rrule)
        self.every_base="every day" if rrule else ""; self.every_bound=""
        self.language=language

class Manager(FakeManager):
    def __init__(self, name, entry_id):
        super().__init__(name,entry_id)
        self.items={"r1":Rem()}
        self.store=types.SimpleNamespace(reminders=self.items)
        self.edited=[]; self.deleted=[]
    def schedule(self, text, due, rrule=None, language=None):
        self.scheduled.append((text,due,rrule,language))
        return Rem(text,due,rrule=rrule,language=language)
    def edit(self, reminder, text=None, due=None, rrule=None):
        self.edited.append((text,due,rrule))
        if text is not None: reminder.text=text
        if due is not None: reminder.due=due
    def cancel_reminders(self, matches):
        self.deleted.extend(matches)
        return len(matches)

class Sat(FakeHass):
    def __init__(self, replies):
        super().__init__(replies)
        self.questions=[]
        self.is_running=True
        # Deliberately English HA interface language. The spoken RU intent must win.
        self.config=types.SimpleNamespace(language="en")
    async def async_call(self, domain, service, data, **kw):
        if service == "ask_question": self.questions.append(data)
        return await super().async_call(domain, service, data, **kw)

def run(coro):
    return asyncio.run(coro)

def voice_looks_russian(text):
    assert any("\u0400" <= ch <= "\u04FF" for ch in text), repr(text)
    assert not any(word in text.casefold() for word in (
        "who's this", "when should", "alright", "are you sure", "beg pardon",
        "sorry", "didn't get", "i don't know", "not canceled", "the usual",
    )), repr(text)

def check_sat(sat):
    for q in sat.asked: voice_looks_russian(q)
    for a in sat.announced: voice_looks_russian(a)

cases=[]
def check(name, callback):
    callback(); cases.append(name); print("PASS", name)

def case_when_success():
    m=Manager("Иван", "owner1"); h=Sat(["через пять минут"])
    run(it._ask_when_then_schedule(h,m,"assist_satellite.kitchen","проверить плиту",
        "Когда напомнить?",it.Times((8,15)), "вам", "ru"))
    assert len(m.scheduled)==1 and m.scheduled[0][3]=="ru"
    assert "создано" in h.announced[-1]
    check_sat(h)
check("when: Russian question and creation",case_when_success)

def case_when_silence():
    m=Manager("Иван", "owner1"); h=Sat([None,None,None])
    run(it._ask_when_then_schedule(h,m,"assist_satellite.kitchen","проверить плиту",
        "Когда напомнить?",it.Times((8,15)), "вам","ru"))
    assert len(h.asked)==3
    assert len(m.scheduled)==1
    assert "по умолчанию" in h.announced[-1]
    check_sat(h)
check("when: unanswered follow-up",case_when_silence)

def case_when_unknown():
    m=Manager("Иван", "owner1"); h=Sat(["не знаю","через пятнадцать минут"])
    run(it._ask_when_then_schedule(h,m,"assist_satellite.kitchen","купить хлеб",
        "Когда напомнить?",it.Times((8,15)), "вам","ru"))
    assert len(h.asked)==2
    assert "Не удалось" in h.asked[1]
    assert len(m.scheduled)==1
    check_sat(h)
check("when: unclear answer then Russian retry",case_when_unknown)

def case_whose_success():
    a=Manager("Иван","a"); b=Manager("Мария","b"); h=Sat([{"id":"b"}])
    run(it._ask_whose_then_schedule(h,"assist_satellite.kitchen",[a,b],"принять витамины",DUE,None,"ru"))
    assert not a.scheduled and len(b.scheduled)==1
    assert b.scheduled[0][3]=="ru"
    assert "или" in h.asked[0] and "—" in h.asked[0]
    check_sat(h)
check("owner: Russian selection and confirmation",case_whose_success)

def case_whose_silence():
    a=Manager("Иван","a"); b=Manager("Мария","b"); h=Sat([None,None,None])
    run(it._ask_whose_then_schedule(h,"assist_satellite.kitchen",[a,b],"полить цветы",DUE,None,"ru"))
    assert len(h.asked)==3 and not a.scheduled and not b.scheduled
    assert "не создано" in h.announced[0]
    check_sat(h)
check("owner: unanswered owner does not create",case_whose_silence)

class Handler:
    def _default_time(self,m): return it.Times((8,15),{})
    def _default_time_phrase(self,m): return "8:15 AM"
    def _whose(self,h,m): return m.name

def case_two_questions():
    a=Manager("Иван","a"); b=Manager("Мария","b")
    h=Sat([{"id":"b"}, "через десять минут"])
    run(it._ask_whose_then_when(h,Handler(),"assist_satellite.kitchen",[a,b],"вынести мусор","ru"))
    assert len(h.asked)==2 and len(b.scheduled)==1
    assert all(row[3]=="ru" for row in b.scheduled)
    check_sat(h)
check("owner + when: both questions in Russian",case_two_questions)

def case_owner_read():
    a=Manager("Иван","a"); b=Manager("Мария","b"); h=Sat([{"id":"b"}])
    run(it._ask_whose_then_answer(h,"assist_satellite.kitchen",[a,b],
                                  lambda chosen: f"Напоминания: {chosen.name}", "ru"))
    assert h.announced==["Напоминания: Мария"]
    check_sat(h)
check("owner: list query in Russian",case_owner_read)

def case_edit():
    m=Manager("Иван","a"); h=Sat(["перенеси на завтра в девять вечера"])
    run(it._ask_then_edit(h,m,"assist_satellite.kitchen","r1",it.Times((8,15)),"ru"))
    assert len(m.edited)==1 and m.edited[0][1].hour==21
    assert "изменено" in h.announced[-1]
    check_sat(h)
check("edit: Russian prompt and readback",case_edit)

def case_edit_silence():
    m=Manager("Иван","a"); h=Sat([None])
    run(it._ask_then_edit(h,m,"assist_satellite.kitchen","r1",it.Times((8,15)),"ru"))
    assert not m.edited and "Изменений нет" in h.announced[0]
    check_sat(h)
check("edit: silence stays Russian",case_edit_silence)

def case_confirm_yes():
    m=Manager("Иван","a"); h=Sat([{"id":"yes"}])
    run(it._confirm_then_cancel(h,m,"assist_satellite.kitchen",[m.items["r1"]],
         "Удалить напоминание?", language="ru"))
    assert len(m.deleted)==1
    assert "да" in h.questions[0]["answers"][0]["sentences"]
    assert "нет" in h.questions[0]["answers"][1]["sentences"]
    assert "отменено" in h.announced[-1].lower()
    check_sat(h)
check("cancel: Russian yes/no answers and success",case_confirm_yes)

def case_confirm_no():
    m=Manager("Иван","a"); h=Sat([{"id":"no"}])
    run(it._confirm_then_cancel(h,m,"assist_satellite.kitchen",[m.items["r1"]],
         "Удалить напоминание?", language="ru"))
    assert not m.deleted and "не подтверждена" in h.announced[-1]
    check_sat(h)
check("cancel: Russian refusal",case_confirm_no)

def case_intent_locale():
    h=Sat([]); h.config.language="en"
    obj=types.SimpleNamespace(language="ru",hass=h)
    from fr import intents
    from fr import const
    pkg.all_managers=lambda hh: []
    handler=it.ReminderIntent()
    assert "не настроены" in handler._not_ready(h, obj)
    a=Manager("Иван","a");b=Manager("Мария","b")
    pkg.all_managers=lambda hh: [a,b]
    assert "или" in handler._which_list(h,obj)
    assert "or" not in handler._which_list(h,obj)
check("intent language overrides English HA UI",case_intent_locale)

# No English in Russian task pronoun transformation. Stores keep original text.
ru = __import__("fr.voice_ru", fromlist=["second_person"])
def case_pronouns():
    assert ru.second_person("проверить мои документы") == "проверить твои документы"
    assert ru.second_person("позвонить моей маме") == "позвонить твоей маме"
    assert ru.second_person("Мой ноутбук") == "Твой ноутбук"
    assert ru.second_person("услышать мойку на кухне") == "услышать мойку на кухне"
check("delivery: Russian second-person inflection",case_pronouns)

from fr import store as st
def case_storage_roundtrip():
    record=st.Reminder("a", "купить хлеб", DUE,DUE,language="ru")
    assert st.Reminder.from_dict(record.to_dict()).language=="ru"
    old=record.to_dict();old.pop("language")
    assert st.Reminder.from_dict(old).language is None
check("delivery: stored locale and legacy reminders",case_storage_roundtrip)

print(f"RESULT {len(cases)} Russian dialogue assertions")
