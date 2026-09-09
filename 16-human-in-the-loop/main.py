"""Human-in-the-loop — the autonomy axis, and usually the difference between a demo
and something you'd actually turn on.

The rule that matters: gate on SIDE EFFECTS, not on intelligence. Reads run freely.
Writes stop and ask. A tool's blast radius, not the model's confidence, decides.

Three autonomy tiers appear in the code below:
    AUTO     reversible / read-only  -> just run it
    CONFIRM  writes, sends, spends   -> pause for a human
    NEVER    destructive             -> not in the tool list at all

Note the loop pauses and RESUMES. That's what makes this real: the pending call is
serializable, so in production the pause is a Slack message and the resume is a
different process an hour later.
"""

import json
import os

from mistralai.client import Mistral

client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
MODEL = "mistral-medium-latest"

_TICKETS = {"T-1041": {"status": "open", "customer": "Acme", "refund_requested": 4900}}
_LOG: list[str] = []


# --- tools, tagged by blast radius ------------------------------------------

def get_ticket(ticket_id: str) -> str:
    return json.dumps(_TICKETS.get(ticket_id, {"error": "not found"}))


def check_refund_policy(days_since_charge: int) -> str:
    return json.dumps({"eligible": days_since_charge <= 14, "limit_days": 14})


def issue_refund(ticket_id: str, amount_cents: int) -> str:
    _LOG.append(f"REFUNDED {amount_cents} on {ticket_id}")
    return json.dumps({"status": "refunded", "amount_cents": amount_cents})


def email_customer(ticket_id: str, body: str) -> str:
    _LOG.append(f"EMAILED {ticket_id}")
    return json.dumps({"status": "sent"})


TOOLS_IMPL = {"get_ticket": get_ticket, "check_refund_policy": check_refund_policy,
              "issue_refund": issue_refund, "email_customer": email_customer}

# The allow-list IS the fence. This dict is your security policy — keep it in code,
# not in a prompt, because a prompt can be talked out of it.
AUTONOMY = {
    "get_ticket": "AUTO",
    "check_refund_policy": "AUTO",
    "issue_refund": "CONFIRM",     # moves money
    "email_customer": "CONFIRM",   # can't be unsent
}

TOOLS = [
    {"type": "function", "function": {
        "name": "get_ticket", "description": "Fetch a support ticket by id.",
        "parameters": {"type": "object", "properties": {"ticket_id": {"type": "string"}},
                       "required": ["ticket_id"]}}},
    {"type": "function", "function": {
        "name": "check_refund_policy", "description": "Is a refund allowed after N days?",
        "parameters": {"type": "object", "properties": {"days_since_charge": {"type": "integer"}},
                       "required": ["days_since_charge"]}}},
    {"type": "function", "function": {
        "name": "issue_refund", "description": "Issue a refund in cents. Irreversible.",
        "parameters": {"type": "object", "properties": {
            "ticket_id": {"type": "string"}, "amount_cents": {"type": "integer"}},
            "required": ["ticket_id", "amount_cents"]}}},
    {"type": "function", "function": {
        "name": "email_customer", "description": "Email the customer on a ticket.",
        "parameters": {"type": "object", "properties": {
            "ticket_id": {"type": "string"}, "body": {"type": "string"}},
            "required": ["ticket_id", "body"]}}},
]


def ask_human(name: str, args: dict) -> tuple[bool, str]:
    """In production: a Slack Block Kit message, or a row in an approvals table.
    The important property is that this function can take an hour to return."""
    print(f"\n  *** APPROVAL NEEDED ***\n  {name}({json.dumps(args)})")
    reply = input("  approve? [y/N/reason] ").strip()
    if reply.lower() in ("y", "yes"):
        return True, ""
    return False, reply if reply.lower() not in ("n", "no", "") else "human declined"


def run(task: str, max_steps: int = 10) -> str:
    messages = [
        {"role": "system", "content":
            "You are a support agent. Check the ticket and the policy before acting. "
            "If a human declines an action, do not retry it — explain and stop."},
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
            name = call.function.name
            args = json.loads(call.function.arguments or "{}")
            tier = AUTONOMY.get(name, "CONFIRM")  # unknown tool -> gate it. Fail closed.

            if tier == "CONFIRM":
                # --- the pause. `messages` here is the resumable checkpoint. ---
                approved, reason = ask_human(name, args)
                if not approved:
                    # A rejection is an OBSERVATION, not a crash. Tell the model why.
                    messages.append({"role": "tool", "name": name, "tool_call_id": call.id,
                                     "content": json.dumps({"status": "rejected_by_human",
                                                            "reason": reason})})
                    continue

            result = TOOLS_IMPL[name](**args)
            print(f"  [{step}] {tier:7} {name}({args}) -> {result}")
            messages.append({"role": "tool", "name": name, "tool_call_id": call.id,
                             "content": result})

    return "hit max_steps"


if __name__ == "__main__":
    print("\n", run("Ticket T-1041: the customer was charged 22 days ago and wants a refund. "
                    "Handle it."))
    print("\nside effects:", _LOG or "none")
