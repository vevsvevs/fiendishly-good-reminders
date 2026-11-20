"""Expose the FGR scheduler to the Home Assistant Assist LLM API."""

import asyncio
from datetime import timedelta
from types import SimpleNamespace

import voluptuous as vol

from homeassistant.components.homeassistant import async_should_expose
from homeassistant.components.llm import LLMTools
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.llm import (
    LLM_API_ASSIST,
    LLMContext,
    Tool,
    ToolAnnotations,
    ToolInput,
    ToolResult,
)
from homeassistant.util import dt as dt_util

from . import _as_dict, all_managers, manager_named
from .const import DOMAIN, RESULT_OK
from .intents import (
    ReminderIntent,
    _confirm_then_cancel,
    _ru_message,
    _skip_empties_it,
)
from .store import InvalidRule, PastDue

_LIMIT = 25
_TEXT = vol.All(str, vol.Strip, vol.Length(min=1))
_DELAY = vol.All(int, vol.Range(min=1, max=315360000))
_TIMING = {vol.Optional("due"): _TEXT, vol.Optional("delay_seconds"): _DELAY}
_RANGE = {vol.Optional("from"): _TEXT, vol.Optional("until"): _TEXT}

_PROMPT = (
    "Use fiendishly_reminders tools for requests about reminders, including follow-up "
    "answers that give only the task and time. A reminder is distinct from a countdown "
    "timer. Never substitute a timer or a to-do action for a reminder. If the purpose "
    "is unclear, ask a question. For relative times supply delay_seconds; for an "
    "absolute time supply an ISO 8601 datetime in due. Ask if the time is missing. "
    "Find the exact reminder ID before changing it. Use cancel_all only for an explicit "
    "request to clear a named list. If a tool reports confirmation_pending, a separate "
    "voice confirmation owns the outcome. Do not claim that anything was deleted. "
    "Only report success after the corresponding FGR tool returns success."
)


def _error(reason: str, **details) -> ToolResult:
    return ToolResult(data={"status": "error", "error": reason, **details}, error=True)


def _success(**details) -> ToolResult:
    return ToolResult(data={"status": "success", **details})


def _range_date(value: str | None):
    if value is None:
        return None
    if (date := dt_util.parse_datetime(value)) is None:
        raise ValueError("Supply an ISO 8601 date and time.")
    return dt_util.as_local(date) if date.tzinfo else date.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)


def _due(args: dict):
    delay = args.get("delay_seconds")
    if "due" in args and delay is not None:
        raise ValueError("Supply either due or delay_seconds.")
    return dt_util.now() + timedelta(seconds=delay) if delay is not None else _range_date(args.get("due"))


class ReminderTool(Tool):
    """A reminder operation scoped to lists exposed to this assistant."""

    integration = DOMAIN

    def __init__(self, operation, description, fields, *, read_only=False, destructive=True):
        self.name = f"{DOMAIN}__{operation.__name__.removeprefix('_')}"
        self.description = description
        if not any(field.schema == "target" for field in fields):
            fields = {vol.Optional("target"): _TEXT, **fields}
        self.parameters = vol.Schema(fields)
        self.annotations = ToolAnnotations(
            read_only=read_only, destructive=destructive and not read_only, open_world=False
        )
        self._operation = operation

    async def async_call(self, hass: HomeAssistant, tool_input: ToolInput,
                         llm_context: LLMContext) -> ToolResult:
        try:
            args = self.parameters(tool_input.tool_args)
            managers = _exposed_managers(hass, llm_context)
            target = args.pop("target", None)
            manager = _select_manager(hass, llm_context, managers, target)
            if manager is None:
                return _error(
                    "Choose an exposed reminder list by target ID." if managers
                    else "No reminder list is exposed to this assistant.",
                    lists=[{"target": m.entry.entry_id, "name": m.name} for m in managers],
                )
            result = self._operation(hass, llm_context, manager, args)
            result.data["list"] = {"target": manager.entry.entry_id, "name": manager.name}
            return result
        except (vol.Invalid, ValueError, PastDue, InvalidRule) as err:
            return _error(str(err))


def _exposed_managers(hass, context):
    registry = er.async_get(hass)
    managers = []
    for manager in all_managers(hass):
        sensor = registry.async_get_entity_id(
            "sensor", DOMAIN, f"{manager.entry.entry_id}_next_reminder"
        )
        if sensor and hass.states.get(sensor) is not None and async_should_expose(
            hass, context.assistant, sensor
        ):
            managers.append(manager)
    return managers


def _select_manager(hass, context, managers, target):
    if target is not None:
        manager = manager_named(hass, target)
        return manager if manager in managers else None
    if len(managers) == 1:
        return managers[0]
    if context.device_id:
        registry = er.async_get(hass)
        satellites = [
            entry.entity_id
            for entry in er.async_entries_for_device(registry, context.device_id)
            if entry.domain == "assist_satellite"
        ]
        owners = [m for m in managers if any(m.owns_satellite(s) for s in satellites)]
        if len(owners) == 1:
            return owners[0]
    return None


def _schedule(hass, context, manager, args):
    due = _due(args)
    if due is None:
        return _error("Ask when to remind. Provide due or delay_seconds.")
    reminder = manager.schedule(args["text"], due, args.get("rrule"), language=context.language)
    return _success(reminder=_as_dict(reminder))


def _again(hass, context, manager, args):
    if not (last_text := manager.store.last_text):
        return _error("This list has no previous reminder to repeat.")
    return _schedule(hass, context, manager, {**args, "text": last_text})


def _list(hass, context, manager, args):
    return _find(hass, context, manager, args)


def _find(hass, context, manager, args):
    start = _range_date(args.get("from"))
    end = _range_date(args.get("until"))
    if start and end and start > end:
        return _error("The start of the range must precede its end.")
    rows = manager.search(args.get("text"), start, end)
    rows.sort(key=lambda row: row[1][0] if row[1] else row[0].due)
    return _success(
        count=len(rows), truncated=len(rows) > _LIMIT,
        reminders=[_as_dict(reminder, occurrences) for reminder, occurrences in rows[:_LIMIT]],
    )


def _edit(hass, context, manager, args):
    reminder = manager.store.reminders.get(args["id"])
    if reminder is None:
        return _error("Reminder ID not found in this list. Search before editing.")
    changes = {key: args[key] for key in ("text", "rrule") if key in args}
    if (due := _due(args)) is not None:
        changes["due"] = due
    if not changes:
        return _error("Specify what to change.")
    return _success(reminder=_as_dict(manager.edit(reminder, **changes)))


def _confirmation(hass, context, manager, matches, question, *, skip_id=None):
    handler = ReminderIntent()
    language = context.language or getattr(hass.config, "language", "en") or "en"
    satellite = handler._satellite(hass, manager, SimpleNamespace(device_id=context.device_id))
    if satellite is None:
        return _error("This operation requires live voice confirmation on a configured satellite.")
    pending = hass.data.setdefault(f"{DOMAIN}_llm_confirmations", set())
    if satellite in pending:
        return _error("A reminder confirmation is already pending on this satellite.")
    pending.add(satellite)
    hass.async_create_background_task(
        _confirm_after_reply(hass, manager, satellite, matches, question, language, skip_id, pending),
        name="reminders_confirm_llm_operation",
    )
    return ToolResult(data={"status": "confirmation_pending", "count": len(matches)})


async def _confirm_after_reply(hass, manager, satellite, matches, question, language, skip_id, pending):
    """Let the current voice turn finish before asking the satellite to listen."""
    try:
        async with asyncio.timeout(60):
            while state := hass.states.get(satellite):
                if state.state == "idle":
                    break
                if state.state in ("unknown", "unavailable"):
                    return
                await asyncio.sleep(0.25)
            else:
                return
        await _confirm_then_cancel(
            hass, manager, satellite, matches, question, language=language, skip_id=skip_id
        )
    except TimeoutError:
        return
    finally:
        pending.discard(satellite)


def _cancel(hass, context, manager, args):
    reminder = manager.store.reminders.get(args["id"])
    if reminder is None:
        return _error("Reminder ID not found in this list. Search before cancelling.")
    handler = ReminderIntent()
    satellite = handler._satellite(hass, manager, SimpleNamespace(device_id=context.device_id))
    if satellite is not None and handler._confirms(manager):
        question = (_ru_message("confirm_cancel", text=reminder.text)
                    if (context.language or "").startswith("ru")
                    else f"Cancel the reminder {reminder.text}? Answer yes or no.")
        return _confirmation(hass, context, manager, [reminder], question)
    return _success(count=manager.cancel_reminders([reminder]))


def _cancel_all(hass, context, manager, args):
    matches = list(manager.store.reminders.values())
    if not matches:
        return _success(count=0)
    question = (
        _ru_message("cancel_all_question", name=manager.name, count=len(matches))
        if (context.language or "").startswith("ru")
        else f"Delete all {len(matches)} reminders from {manager.name}'s list, including recurring ones? Answer yes or no."
    )
    return _confirmation(hass, context, manager, matches, question)


def _skip(hass, context, manager, args):
    reminder = manager.store.reminders.get(args["id"])
    if reminder is None:
        return _error("Reminder ID not found in this list. Search before skipping.")
    if not reminder.recurring:
        return _error("A one-off reminder cannot be skipped. Ask whether to cancel it.")
    scope = args["scope"]
    if _skip_empties_it(manager, reminder, scope, dt_util.now()):
        question = (_ru_message("skip_confirm", text=reminder.text)
                    if (context.language or "").startswith("ru")
                    else f"Skipping will end the reminder {reminder.text}. Answer yes or no.")
        return _confirmation(hass, context, manager, [reminder], question, skip_id=(reminder.id, scope))
    result = manager.skip(None, scope, reminder_id=reminder.id)
    if result["success"] != RESULT_OK:
        return _error(result["error"])
    return _success(count=result["number"], ended=result["ended"],
                    occurrences=[when.isoformat() for when in result["occurrences"]])


_TOOLS = [
    ReminderTool(
        _schedule, "Create a one-off or recurring FGR reminder. Supply text and exactly one of "
        "due (an ISO 8601 datetime) or delay_seconds; optional rrule is an RFC 5545 recurrence.",
        {vol.Required("text"): _TEXT, **_TIMING, vol.Optional("rrule"): _TEXT}, destructive=False,
    ),
    ReminderTool(_again, "Schedule the last reminder text again at due or after delay_seconds.",
                 _TIMING, destructive=False),
    ReminderTool(_list, "List, count or find the next FGR reminders, optionally in a date range.",
                 _RANGE, read_only=True),
    ReminderTool(_find, "Find FGR reminders by text or ISO 8601 datetime range; returns exact IDs.",
                 {vol.Optional("text"): _TEXT, **_RANGE}, read_only=True),
    ReminderTool(_edit, "Edit one FGR reminder by ID. Supply new text, due, delay_seconds or rrule. "
                 "An empty rrule ends recurrence.",
                 {vol.Required("id"): _TEXT, vol.Optional("text"): _TEXT,
                  **_TIMING, vol.Optional("rrule"): str}),
    ReminderTool(_cancel, "Cancel exactly one FGR reminder by ID, including its future occurrences.",
                 {vol.Required("id"): _TEXT}),
    ReminderTool(_skip, "Skip the next occurrence or the rest of this week for one recurring reminder.",
                 {vol.Required("id"): _TEXT, vol.Optional("scope", default="next"): vol.In(("next", "week"))}),
    ReminderTool(_cancel_all, "Request a live confirmation to delete every reminder in a named FGR list.",
                 {vol.Required("target"): _TEXT}),
]


@callback
def async_get_tools(hass: HomeAssistant, llm_context: LLMContext, api_id: str) -> LLMTools | None:
    """Use the existing Device control API and the next-reminder sensor's exposure."""
    if api_id == LLM_API_ASSIST and _exposed_managers(hass, llm_context):
        return LLMTools(tools=list(_TOOLS), prompt=_PROMPT)
    return None
