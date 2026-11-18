"""Exercise the *actual* FGR delivery method without installing HA Core.

An AST-extracted method is executed with a fake hass/service bus, so the same
code path can be checked for satellite speech, phone notification and fallback.
"""
import ast
import asyncio
import importlib.util
from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "custom_components" / "fiendishly_reminders"
source = ast.parse((SRC / "__init__.py").read_text(encoding="utf-8"))
manager_class = next(node for node in source.body if isinstance(node, ast.ClassDef)
                     and node.name == "ReminderManager")
func = next(node for node in manager_class.body if isinstance(node, ast.AsyncFunctionDef)
            and node.name == "deliver")
module = ast.fix_missing_locations(ast.Module(body=[func], type_ignores=[]))

pkg = types.ModuleType("fr")
pkg.__path__ = [str(SRC)]
sys.modules["fr"] = pkg
spec = importlib.util.spec_from_file_location("fr.voice_ru", SRC / "voice_ru.py")
voice_ru = importlib.util.module_from_spec(spec)
sys.modules["fr.voice_ru"] = voice_ru
spec.loader.exec_module(voice_ru)

class FakeServices:
    def __init__(self):
        self.calls = []
    async def async_call(self, domain, service, data, **kwargs):
        self.calls.append((domain, service, data))
        return {}

class FakeHass:
    def __init__(self, language="en"):
        self.config = types.SimpleNamespace(language=language)
        self.services = FakeServices()

class FakeManager:
    def __init__(self, ha_language="en", channel="satellite", name="Иван"):
        self.hass = FakeHass(ha_language)
        self.name = name
        self.channel = channel
    def _opt(self, key, default=None):
        if key == "announce_targets":
            return ["assist_satellite.kitchen"] if self.channel == "satellite" else []
        if key == "notify_service":
            return ["notify.phone"] if self.channel == "phone" else []
        return default
    def _chime(self):
        return False, None
    def _audible(self):
        return True
    def _notify_targets(self, configured):
        return (["notify.phone"], []) if self.channel == "phone" else ([], [])

ctx = {
    "__name__": "fr.delivery_test",
    "__package__": "fr",
    "CONF_ANNOUNCE_TARGETS": "announce_targets",
    "CONF_NOTIFY_SERVICE": "notify_service",
    "all_managers": lambda hass: [manager],
    # English conversion is tested separately by the original test suite.
    "second_person": lambda text: text,
}
exec(compile(module, "<actual ReminderManager.deliver>", "exec"), ctx)

def deliver(language, ha_language="en", channel="satellite", count=1):
    global manager
    manager = FakeManager(ha_language, channel)
    if count > 1:
        ctx["all_managers"] = lambda hass: [manager, object()]
    else:
        ctx["all_managers"] = lambda hass: [manager]
    asyncio.run(ctx["deliver"](manager, "проверить мои документы", language=language))
    assert len(manager.hass.services.calls) == 1, manager.hass.services.calls
    return manager.hass.services.calls[0]

def check(label, condition):
    assert condition, label
    print("PASS", label)

domain, service, data = deliver("ru", "en")
check("RU voice language overrides EN HA interface",
      domain == "assist_satellite" and service == "announce"
      and data["message"] == "Напоминание: проверить твои документы")

domain, service, data = deliver("en", "ru")
check("EN reminder keeps its language on RU interface",
      domain == "assist_satellite" and data["message"] == "Reminder: проверить мои документы")

domain, service, data = deliver(None, "ru")
check("legacy reminder uses HA UI locale",
      data["message"] == "Напоминание: проверить твои документы")

domain, service, data = deliver("ru", "en", channel="phone")
check("RU phone notification",
      domain == "notify" and service == "send_message"
      and data["title"] == "Напоминание"
      and data["message"] == "проверить твои документы")

domain, service, data = deliver("ru", "en", channel="fallback")
check("RU persistent notification",
      domain == "persistent_notification" and service == "create"
      and data["title"] == "Напоминание"
      and data["message"] == "проверить твои документы")

domain, service, data = deliver("ru", "en", count=2)
check("RU announcement for shared multi-owner system",
      data["message"].startswith("Напоминание для Иван:"))

check("Russian date formatting", "ноября" in voice_ru.moment(
    __import__("datetime").datetime(2026,11,18,9,30)))
print("RESULT 7/7 actual delivery-path checks")
