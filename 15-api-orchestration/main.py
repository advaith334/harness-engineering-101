"""API orchestration — where "do things for me" actually cashes out.

An agent that reads from one service, transforms, and writes to another. The LLM part
is small; the engineering is in the effector layer: idempotency, retries, pagination,
dependencies between calls, and not doing the write twice.

The fake services below have deliberately realistic shapes — paginated list endpoints,
an idempotency key on the write, a flaky third call. Swap the bodies for `httpx` calls
to Google Calendar / Gmail / Stripe and the agent code above them does not change.
"""

import json
import os
import uuid
from datetime import date, datetime, timedelta

from mistralai.client import Mistral

client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
MODEL = "mistral-medium-latest"


# =========================== fake external services ==========================

_CALENDAR = [
    {"id": "e1", "start": "2026-09-10T09:00", "end": "2026-09-10T10:00", "title": "standup"},
    {"id": "e2", "start": "2026-09-10T14:00", "end": "2026-09-10T15:30", "title": "design review"},
    # A third event on the 10th, so page 1 does NOT show the whole day. If the agent
    # stops paginating it will confidently book on top of this one.
    {"id": "e3", "start": "2026-09-10T16:00", "end": "2026-09-10T16:30", "title": "retro"},
    {"id": "e4", "start": "2026-09-11T11:00", "end": "2026-09-11T12:00", "title": "1:1"},
]
_CONTACTS = {"priya": "priya@northwind.example", "marco": "marco@northwind.example"}
_SENT: list[dict] = []
_WRITTEN_KEYS: set[str] = set()  # idempotency ledger
_CALL_COUNT = {"n": 0}


def list_events(day: str, page: str = "") -> str:
    """Paginated, like every real list endpoint. The agent must handle next_page."""
    matching = [e for e in _CALENDAR if e["start"].startswith(day)]
    start = int(page or 0)
    page_items = matching[start:start + 2]
    next_page = str(start + 2) if start + 2 < len(matching) else None
    return json.dumps({"events": page_items, "next_page": next_page})


def find_contact(name: str) -> str:
    email = _CONTACTS.get(name.lower())
    return json.dumps({"email": email} if email else {"error": f"no contact named {name!r}"})


def create_event(day: str, start_time: str, minutes: int, title: str, attendee: str,
                 idempotency_key: str) -> str:
    """A WRITE. Note the idempotency key — the agent may retry, the calendar must not double-book."""
    if idempotency_key in _WRITTEN_KEYS:
        return json.dumps({"status": "already_created", "idempotency_key": idempotency_key})
    _WRITTEN_KEYS.add(idempotency_key)

    begin = datetime.fromisoformat(f"{day}T{start_time}")
    event = {"id": f"e{len(_CALENDAR)+1}", "start": begin.isoformat(),
             "end": (begin + timedelta(minutes=minutes)).isoformat(),
             "title": title, "attendee": attendee}
    _CALENDAR.append(event)
    return json.dumps({"status": "created", **event})


def send_email(to: str, subject: str, body: str) -> str:
    """Flaky on purpose: the first attempt fails. The agent must retry, not give up."""
    _CALL_COUNT["n"] += 1
    if _CALL_COUNT["n"] == 1:
        return json.dumps({"error": "503 upstream unavailable", "retryable": True})
    _SENT.append({"to": to, "subject": subject, "body": body})
    return json.dumps({"status": "sent", "to": to})


# =============================== tool schemas ================================

TOOLS_IMPL = {"list_events": list_events, "find_contact": find_contact,
              "create_event": create_event, "send_email": send_email}

TOOLS = [
    {"type": "function", "function": {
        "name": "list_events",
        "description": "List calendar events for a day (YYYY-MM-DD). Returns {events, next_page}. "
                       "If next_page is not null, call again with that page value.",
        "parameters": {"type": "object", "properties": {
            "day": {"type": "string"}, "page": {"type": "string"}}, "required": ["day"]}}},
    {"type": "function", "function": {
        "name": "find_contact",
        "description": "Look up a person's email by first name. Do this before sending email.",
        "parameters": {"type": "object", "properties": {"name": {"type": "string"}},
                       "required": ["name"]}}},
    {"type": "function", "function": {
        "name": "create_event",
        "description": "Create a calendar event. WRITE OPERATION. You must pass a unique "
                       "idempotency_key; reuse the SAME key if you retry the same event.",
        "parameters": {"type": "object", "properties": {
            "day": {"type": "string"}, "start_time": {"type": "string", "description": "HH:MM"},
            "minutes": {"type": "integer"}, "title": {"type": "string"},
            "attendee": {"type": "string", "description": "email address"},
            "idempotency_key": {"type": "string"}},
            "required": ["day", "start_time", "minutes", "title", "attendee", "idempotency_key"]}}},
    {"type": "function", "function": {
        "name": "send_email",
        "description": "Send an email. WRITE OPERATION. If the result says retryable, try again once.",
        "parameters": {"type": "object", "properties": {
            "to": {"type": "string"}, "subject": {"type": "string"}, "body": {"type": "string"}},
            "required": ["to", "subject", "body"]}}},
]


# =================================== agent ===================================

def run(task: str, max_steps: int = 12) -> str:
    messages = [
        {"role": "system", "content":
            f"You are a scheduling assistant. Today is {date.today().isoformat()}.\n"
            "Rules:\n"
            "- Read before you write. Check the calendar before proposing a time.\n"
            "- Paginate fully before concluding anything about a day.\n"
            "- Look up emails; never invent an address.\n"
            f"- Use this idempotency_key for the event: {uuid.uuid4()}\n"
            "- If a call returns retryable, retry it once with identical arguments.\n"
            "- Report what you did in 2 lines."},
        {"role": "user", "content": task},
    ]

    for step in range(max_steps):
        msg = client.chat.complete(
            model=MODEL, messages=messages, tools=TOOLS, tool_choice="auto"
        ).choices[0].message
        messages.append(msg)

        if not msg.tool_calls:
            return msg.content

        for call in msg.tool_calls:
            args = json.loads(call.function.arguments or "{}")
            try:
                result = TOOLS_IMPL[call.function.name](**args)
            except Exception as e:
                result = json.dumps({"error": str(e)})
            # A write log like this is what you actually need in production.
            kind = "WRITE" if call.function.name in ("create_event", "send_email") else "read "
            print(f"  [{step}] {kind} {call.function.name}({args}) -> {result[:100]}")
            messages.append({"role": "tool", "name": call.function.name,
                             "tool_call_id": call.id, "content": result})

    return "hit max_steps"


if __name__ == "__main__":
    print("\n", run(
        "Find a free 45-minute slot on 2026-09-10 for a funnel review with Priya, "
        "book it, and email her the invite."
    ))
    print("\nCalendar now has", len(_CALENDAR), "events;", len(_SENT), "email(s) sent")
