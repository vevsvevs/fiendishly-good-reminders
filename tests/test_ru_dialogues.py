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
    assert "6 сентября в 14:05" in h.announced[-1]
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
    assert "7 сентября в 17:00" in h.announced[-1]
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
    assert ru.second_person("проверить моё письмо") == "проверить твоё письмо"
    assert ru.second_person("посмотреть в моём шкафу") == "посмотреть в твоём шкафу"
    assert ru.second_person("услышать мойку на кухне") == "услышать мойку на кухне"
check("delivery: Russian second-person inflection",case_pronouns)

from fr import store as st
def case_storage_roundtrip():
    record=st.Reminder("a", "купить хлеб", DUE,DUE,language="ru")
    assert st.Reminder.from_dict(record.to_dict()).language=="ru"
    old=record.to_dict();old.pop("language")
    assert st.Reminder.from_dict(old).language is None
check("delivery: stored locale and legacy reminders",case_storage_roundtrip)


# Whole-list deletion is a different, high-risk action from canceling one match.
# It MUST be fail-closed for typed Assist (device_id=None), even if the owner's
# ordinary "confirm before cancel" setting is disabled.
class MassManager(Manager):
    def __init__(self, count=3):
        super().__init__("Виталий", "one")
        self.items = {
            f"r{index}": Rem("покормить малыша", ident=f"r{index}")
            for index in range(count)
        }
        self.store = types.SimpleNamespace(reminders=self.items)
    def cancel_reminders(self, matches):
        removed = 0
        for reminder in matches:
            if self.items.pop(reminder.id, None):
                self.deleted.append(reminder.id)
                removed += 1
        return removed

class MassHass(Sat):
    def __init__(self, replies, on_question=None):
        super().__init__(replies)
        self.tasks = []
        self.on_question = on_question
    def async_create_background_task(self, coro, name=None):
        task = asyncio.create_task(coro)
        self.tasks.append(task)
        return task
    async def async_call(self, domain, service, data, **kw):
        if service == "ask_question" and self.on_question:
            self.on_question()
        return await super().async_call(domain, service, data, **kw)

class FakeResponse:
    def async_set_speech(self, text):
        self.speech = text

class MassIntent:
    def __init__(self, hass, *, device_id=None, language="ru"):
        self.hass = hass
        self.device_id = device_id
        self.language = language
        self.slots = {}
    def create_response(self):
        return FakeResponse()

def run_mass(reply, *, device_id=None, count=3, ambiguous=False,
             on_question=None, language="ru"):
    m = MassManager(count)
    h = MassHass([reply], on_question=lambda: on_question(m) if on_question else None)
    obj = MassIntent(h, device_id=device_id, language=language)
    handler = it.CancelAllRemindersIntent()
    handler._routed_manager = lambda hass, intent: (
        (None, None, True) if ambiguous else (m, None, False)
    )
    handler._satellite = lambda hass, manager, intent: (
        "assist_satellite.kitchen" if intent.device_id else None
    )
    async def go():
        response = await handler.async_handle(obj)
        if h.tasks:
            await asyncio.gather(*h.tasks)
        return response
    response = asyncio.run(go())
    return m, h, response

def case_mass_no_satellite():
    m, h, response = run_mass({"id": "yes"}, device_id=None)
    assert len(m.items) == 3
    assert not h.asked and not h.announced and not h.tasks
    assert "требует голосового подтверждения" in response.speech.lower()
check("mass-delete typed request never deletes", case_mass_no_satellite)

def case_mass_voice_yes():
    m, h, response = run_mass({"id": "yes"}, device_id="device", count=3)
    assert not m.items and set(m.deleted) == {"r0", "r1", "r2"}
    assert response.speech == ""
    assert "Найдено напоминаний: 3" in h.asked[0]
    assert h.announced == ["Отменено напоминаний: 3."]
    assert "да" in h.questions[0]["answers"][0]["sentences"]
    assert "нет" in h.questions[0]["answers"][1]["sentences"]
    check_sat(h)
check("mass-delete voice yes removes three same-named reminders", case_mass_voice_yes)

def case_mass_voice_no():
    m, h, response = run_mass({"id": "no"}, device_id="device")
    assert len(m.items) == 3 and not m.deleted
    assert "не подтверждена" in h.announced[0].lower()
    check_sat(h)
check("mass-delete voice no refuses", case_mass_voice_no)

def case_mass_voice_silence():
    m, h, response = run_mass(None, device_id="device")
    assert len(m.items) == 3 and not m.deleted
    assert "не подтверждена" in h.announced[0].lower()
    check_sat(h)
check("mass-delete unanswered voice never deletes", case_mass_voice_silence)

def case_mass_empty():
    m, h, response = run_mass({"id": "yes"}, device_id="device", count=0)
    assert "нет напоминаний" in response.speech.lower()
    assert not h.asked and not h.tasks
check("mass-delete empty list is a no-op", case_mass_empty)

def case_mass_ambiguous():
    m, h, response = run_mass({"id": "yes"}, device_id="device", ambiguous=True)
    assert len(m.items) == 3 and not m.deleted
    assert "несколько списков" in response.speech.lower()
    assert not h.asked and not h.tasks
check("mass-delete ambiguous owner never deletes", case_mass_ambiguous)

def case_mass_snapshot():
    def add_new(manager):
        manager.items["r-new"] = Rem("новое после вопроса", ident="r-new")
    m, h, response = run_mass({"id": "yes"}, device_id="device",
                               on_question=add_new)
    assert len(m.deleted) == 3
    assert list(m.items) == ["r-new"]
check("mass-delete excludes reminders added after confirmation question", case_mass_snapshot)

assert it.CancelAllRemindersIntent in it.HANDLERS


# Routing through the real owner selector (extracted without initializing HAOS).
import ast
_init_tree = ast.parse((SRC / "__init__.py").read_text(encoding="utf-8"))
_named_fn = next(n for n in _init_tree.body
                 if isinstance(n, ast.FunctionDef) and n.name == "manager_named")
_owner_globals = {"__name__": "fr.owner_test", "__package__": "fr",
                  "HomeAssistant": object,
                  "all_managers": lambda hass: pkg.all_managers(hass)}
exec(compile(ast.fix_missing_locations(ast.Module(body=[_named_fn], type_ignores=[])),
             "<actual manager_named>", "exec"), _owner_globals)
owner_fn = _owner_globals["manager_named"]
pkg.manager_named = owner_fn
pkg.sole_manager = lambda hass: (
    pkg.all_managers(hass)[0] if len(pkg.all_managers(hass)) == 1 else None
)

def case_ru_owner_cases():
    v=MassManager(1); v.name="Виталий"
    m=MassManager(1); m.name="Мария"
    a=MassManager(1); a.name="Анна"
    sg=MassManager(1); sg.name="Сергей"
    pkg.all_managers=lambda hh:[v,m,a,sg]
    h=MassHass([])
    for spoken,expected in (
        ("Виталий",v), ("Виталия",v), ("Виталию",v), ("Виталии",v),
        ("Мария",m), ("Марии",m), ("Марию",m),
        ("Анна",a), ("Анны",a), ("Анне",a), ("Анну",a),
        ("Сергей",sg), ("Сергея",sg), ("Сергею",sg)):
        assert owner_fn(h,spoken) is expected, spoken
    for unknown in ("Вит", "Витал", "Мар", "Иван", "Марианна"):
        assert owner_fn(h,unknown) is None, unknown
check("routing: Russian owner nominative, dative and genitive",case_ru_owner_cases)

def case_english_possessive():
    j=MassManager(1); j.name="James"
    pkg.all_managers=lambda hh:[j]
    h=MassHass([])
    assert owner_fn(h,"James's") is j
    assert owner_fn(h,"James’s") is j
    assert owner_fn(h,"James") is j
    assert owner_fn(h,"Jam") is None
check("routing: English 's remains functional without stripping names",case_english_possessive)

def case_ambiguous_names():
    a=MassManager(1); a.name="Мария"
    b=MassManager(1); b.name="Марий"
    pkg.all_managers=lambda hh:[a,b]
    assert owner_fn(MassHass([]),"Мария") is None  # same form for both
check("routing: ambiguous declined owner names fail closed",case_ambiguous_names)

def case_declined_owner_replies():
    v=MassManager(1); v.name="Виталий"
    m=MassManager(1); m.name="Мария"
    for phrase,wanted in (("для Виталия",v), ("у Марии",m),
                          ("напоминания Виталия",v),
                          ("это для Марии",m)):
        h=MassHass([{"sentence":phrase}])
        chosen,heard=run(it._ask_whose_once(
            h,"assist_satellite.kitchen",[v,m],"Чьи напоминания?","ru"))
        assert chosen is wanted,(phrase,chosen)
    h=MassHass([{"sentence":"для Виталия и Марии"}])
    chosen,heard=run(it._ask_whose_once(
        h,"assist_satellite.kitchen",[v,m],"Чьи напоминания?","ru"))
    assert chosen is None
check("dialogue: declined Russian owner replies and ambiguous speech",case_declined_owner_replies)

def make_routing_manager(name, n=1):
    m=MassManager(n); m.name=name
    for r in m.items.values(): r.text="купить молоко"
    m.store.find=lambda needle, mm=m: [
        r for r in mm.items.values() if needle.casefold() in r.text.casefold()
    ]
    m.store.find_loose=m.store.find
    m.find_at=lambda when, mm=m: list(mm.items.values())
    return m

def call_individual(manager_list, spoken_text, owner=None, *, by_time=False):
    pkg.all_managers=lambda h:manager_list
    h=MassHass([]); h.config.language="en"
    obj=MassIntent(h,device_id=None)
    obj.slots={
        ("hour" if by_time else "reminder_text"): {"value": 9 if by_time else spoken_text}
    }
    if owner is not None: obj.slots["person"]={"value":owner}
    handler=(it.CancelReminderAtIntent() if by_time else it.CancelReminderIntent())
    handler._confirms=lambda m:False
    handler._satellite=lambda *args:None
    response=run(handler.async_handle(obj))
    return response, obj

def case_single_delete_owners():
    v=make_routing_manager("Виталий")
    m=make_routing_manager("Мария")
    response,obj=call_individual([v,m],"молоко у Марии")
    assert len(v.items)==1 and len(m.deleted)==1, response.speech
    assert obj.slots["person"]["value"]=="Марии"
    assert obj.slots["reminder_text"]["value"]=="молоко"
check("delete: declined owner only deletes within selected person's list",case_single_delete_owners)

def case_single_delete_wrong_owner():
    v=make_routing_manager("Виталий")
    response,obj=call_individual([v],"молоко",owner="Павла")
    assert len(v.items)==1 and not v.deleted
    assert "Павла" in response.speech
check("delete: explicitly unknown owner cannot use sole list",case_single_delete_wrong_owner)

def case_single_delete_duplicate():
    m=make_routing_manager("Виталий",3)
    response,obj=call_individual([m],"молоко")
    assert len(m.items)==3 and not m.deleted
    assert "Уточните" in response.speech
check("delete: singular request never removes three identically titled records",case_single_delete_duplicate)

def case_same_time_duplicate():
    m=make_routing_manager("Виталий",2)
    response,obj=call_individual([m],None,by_time=True)
    assert len(m.items)==2 and not m.deleted
    assert "Уточните" in response.speech
check("delete: two reminders at the same time are not arbitrarily selected",case_same_time_duplicate)

def case_delete_ambiguous_owner():
    v=make_routing_manager("Виталий")
    m=make_routing_manager("Мария")
    response,obj=call_individual([v,m],"молоко")
    assert not v.deleted and not m.deleted
check("delete: multiple lists without owner remain unchanged",case_delete_ambiguous_owner)

def case_unknown_mass_owner():
    m=MassManager(3);m.name="Виталий"
    pkg.all_managers=lambda h:[m]
    h=MassHass([])
    obj=MassIntent(h,device_id="device")
    obj.slots["person"]={"value":"о кормлении"}
    handler=it.CancelAllRemindersIntent()
    handler._satellite=lambda *args:"assist_satellite.kitchen"
    response=run(handler.async_handle(obj))
    assert len(m.items)==3 and not h.questions and "о кормлении" in response.speech
check("delete all: vague subject never triggers a purge",case_unknown_mass_owner)


print(f"RESULT {len(cases)} Russian dialogue assertions")
