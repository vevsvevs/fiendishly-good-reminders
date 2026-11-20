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

from . import _as_dict, all_managers, manager_named, voice_ru
from .const import DOMAIN, RESULT_OK
from .intents import (
    ReminderIntent,
    _canceled_speech,
    _confirm_then_cancel,
    _ru_message,
    _skip_empties_it,
    _skip_speech,
)
from .store import InvalidRule, PastDue

_LIMIT = 25
_TEXT = vol.All(str, vol.Strip, vol.Length(min=1))
_DELAY = vol.All(int, vol.Range(min=1, max=315360000))
_TIMING = {vol.Optional("due"): _TEXT, vol.Optional("delay_seconds"): _DELAY}
_RANGE = {vol.Optional("from"): _TEXT, vol.Optional("until"): _TEXT}

_PROMPT = (
    "Use the fiendishly_reminders tools for the user's reminders. A reminder delivers a "
    "message about a task at a time; a timer measures a duration. Requests such as "
    "«напомни», «добавь напоминание», «какие у меня напоминания» or 'remind me to' "
    "refer to FGR. The words «через минуту» or 'in one minute' can specify either "
    "operation and do not by themselves make a request a timer. "
    "Use conversation history to keep the operation from the previous turn. For example, "
    "if you asked «О чём напомнить?» and the user says «покушать через одну минуту», "
    "call fiendishly_reminders__schedule with text='покушать' and delay_seconds=60. "
    "Use FGR rather than timer or to-do tools to perform reminder operations. If the user "
    "clearly changes the request to a countdown, use the timer tool. If you cannot tell "
    "whether the user wants a reminder or a timer, ask before acting. If a reminder is "
    "missing its task, time, or an unambiguous list, ask for what is missing. "
    "For absolute times use an ISO 8601 datetime; for intervals use delay_seconds. "
    "Use find or list to obtain the exact ID before changing, cancelling or skipping "
    "a reminder. If several reminders match, ask which one. Skip affects occurrences; "
    "cancel deletes the whole reminder. Cancel an entire list only on explicit request "
    "and use cancel_all with the list target. If the result is confirmation_pending, "
    "tell the user to wait for the separate voice prompt. Report a change as completed "
    "only if the matching FGR tool returned status='success'. "
    "For a standard Russian response, speak the tool's speech field verbatim without "
    "adding an introduction or changing the date, time, or reminder text. For a "
    "next-reminder question use next_speech; for a count question use count_speech. "
    "For nonstandard questions, use the structured result to compose your own answer. "
    "When confirming creation, repeating, or a change, or answering which reminder is "
    "scheduled, always give the actual reminder text and its scheduled date and time. "
    "Use the returned due time, or the returned matching occurrence for a date-range "
    "query. Do not substitute the requested delay for the scheduled clock time."
)


def _error(reason: str, **details) -> ToolResult:
    return ToolResult(data={"status": "error", "error": reason, **details}, error=True)


def _success(**details) -> ToolResult:
    return ToolResult(data={"status": "success", **details})


def _russian(context) -> bool:
    return (context.language or "").lower().startswith("ru")


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


def _schedule(hass, context, manager, args, *, again: bool = False):
    due = _due(args)
    if due is None:
        return _error("Ask when to remind. Provide due or delay_seconds.")
    reminder = manager.schedule(args["text"], due, args.get("rrule"), language=context.language)
    result = _success(reminder=_as_dict(reminder))
    if _russian(context):
        kind = "recurring_created" if reminder.recurring else "created"
        if again:
            kind = "again_created"
        result.data["speech"] = voice_ru.scheduled(reminder.text, reminder.due, kind=kind)
    return result


def _again(hass, context, manager, args):
    if not (last_text := manager.store.last_text):
        return _error("This list has no previous reminder to repeat.")
    return _schedule(hass, context, manager, {**args, "text": last_text}, again=True)


def _list(hass, context, manager, args):
    return _find(hass, context, manager, args, search=bool(args.get("from") or args.get("until")))


def _find(hass, context, manager, args, *, search: bool = True):
    start = _range_date(args.get("from"))
    end = _range_date(args.get("until"))
    if start and end and start > end:
        return _error("The start of the range must precede its end.")
    rows = manager.search(args.get("text"), start, end)
    rows.sort(key=lambda row: row[1][0] if row[1] else row[0].due)
    result = _success(
        count=len(rows), truncated=len(rows) > _LIMIT,
        reminders=[_as_dict(reminder, occurrences) for reminder, occurrences in rows[:_LIMIT]],
    )
    if _russian(context):
        now = dt_util.now()
        result.data["speech"] = voice_ru.reminder_list(rows, now, search=search)
        result.data["count_speech"] = voice_ru.message("reminder_count", count=len(rows))
        result.data["next_speech"] = voice_ru.message("no_reminders")
        if rows:
            reminder, occurrences = rows[0]
            when = occurrences[0] if occurrences else reminder.due
            result.data["next_speech"] = voice_ru.next_reminder(reminder.text, when, now)
    return result


def _edit(hass, context, manager, args):
    reminder = manager.store.reminders.get(args["id"])
    if reminder is None:
        return _error("Reminder ID not found in this list. Search before editing.")
    changes = {key: args[key] for key in ("text", "rrule") if key in args}
    if (due := _due(args)) is not None:
        changes["due"] = due
    if not changes:
        return _error("Specify what to change.")
    was_recurring = reminder.recurring
    reminder = manager.edit(reminder, **changes)
    result = _success(reminder=_as_dict(reminder))
    if _russian(context):
        if "rrule" in changes and was_recurring and not reminder.recurring:
            key = "edit_stop_repeat"
        elif "rrule" in changes and reminder.recurring:
            key = "edit_recurring"
        elif "due" in changes and "text" not in changes:
            key = "edit_moved_series" if was_recurring else "edit_moved"
        else:
            key = "ask_edit_done"
        result.data["speech"] = voice_ru.message(
            key, text=reminder.text, when=voice_ru.moment(reminder.due)
        )
    return result


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
    count = manager.cancel_reminders([reminder])
    result = _success(count=count)
    if _russian(context):
        result.data["speech"] = _canceled_speech(count, context.language)
    return result


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
    response = _success(count=result["number"], ended=result["ended"],
                        occurrences=[when.isoformat() for when in result["occurrences"]])
    if _russian(context):
        response.data["speech"] = _skip_speech(result, scope, dt_util.now(), context.language)
    return response


_TOOLS = [
    ReminderTool(
        _schedule,
        "Schedule a spoken reminder for a task («напомни», «добавь напоминание», "
        "'remind me'). Use this for both one-turn requests and follow-up replies with a "
        "task and time, such as «покушать через одну минуту» after a reminder question. "
        "Supply text and exactly one of due (ISO 8601 datetime) or delay_seconds. "
        "For a recurring reminder, also supply an RFC 5545 rrule.",
        {vol.Required("text"): _TEXT, **_TIMING, vol.Optional("rrule"): _TEXT},
        destructive=False,
    ),
    ReminderTool(
        _again, "Schedule the last reminder task again («напомни ещё раз»). "
        "Supply a new ISO 8601 due time or delay_seconds.", _TIMING, destructive=False,
    ),
    ReminderTool(
        _list, "List upcoming reminders («какие у меня напоминания»), get the nearest "
        "one or count reminders, optionally in a date range. Returns reminder IDs "
        "and scheduled times.", _RANGE, read_only=True,
    ),
    ReminderTool(
        _find, "Find a reminder by task text or ISO 8601 datetime range, for example "
        "«когда напоминание про врача?». Use the returned ID to edit, cancel or skip "
        "one reminder. If several match, ask which one.", {vol.Optional("text"): _TEXT, **_RANGE},
        read_only=True,
    ),
    ReminderTool(
        _edit, "Move, rename or change the recurrence of one reminder by ID "
        "(«перенеси напоминание», «измени напоминание»). Set a new due datetime or "
        "delay_seconds to move it. An empty rrule ends recurrence.",
        {vol.Required("id"): _TEXT, vol.Optional("text"): _TEXT,
         **_TIMING, vol.Optional("rrule"): str},
    ),
    ReminderTool(
        _cancel, "Delete one reminder by exact ID («удали напоминание», «отмени напоминание»). "
        "For a recurring reminder, this cancels the entire series. Use skip to omit occurrences.",
        {vol.Required("id"): _TEXT},
    ),
    ReminderTool(
        _skip, "Skip the next occurrence or this week's occurrences of one recurring "
        "reminder by exact ID («пропусти следующее напоминание»). Use cancel to end the series.",
        {vol.Required("id"): _TEXT, vol.Optional("scope", default="next"): vol.In(("next", "week"))},
    ),
    ReminderTool(
        _cancel_all, "Request a separate live voice confirmation for an explicit "
        "request to delete every reminder in a named list («удали все напоминания»). "
        "Supply the list target. A pending confirmation means nothing has been deleted yet.",
        {vol.Required("target"): _TEXT},
    ),
]


@callback
def async_get_tools(hass: HomeAssistant, llm_context: LLMContext, api_id: str) -> LLMTools | None:
    """Use the existing Device control API and the next-reminder sensor's exposure."""
    if api_id == LLM_API_ASSIST and _exposed_managers(hass, llm_context):
        return LLMTools(tools=list(_TOOLS), prompt=_PROMPT)
    return None
