"""Sequential handoff — agents pass control down a line, each owning one stage.

Looks like a chain (folder 02), but the nodes are agents: each one decides whether it
can finish or must hand off, and to whom. The topology is a directed line (or a small
graph), and control moves rather than results being collected.

This is the shape of nearly every real support/triage system, and it's the multi-agent
pattern most likely to be the right answer to a "customer service agent" prompt.

Contrast with folder 10: a supervisor FANS OUT and collects. A handoff line MOVES
control forward. Use handoff when stage N+1 depends on stage N's work; use supervisor
when the sub-tasks are independent.
"""

import json
import os

from mistralai.client import Mistral

client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
MODEL = "mistral-medium-latest"


# --- tools, owned per stage --------------------------------------------------

def lookup_account(email: str) -> str:
    return json.dumps({"email": email, "plan": "Pro", "seats": 12,
                       "last_charge": "2026-08-18", "amount_cents": 58800})


def check_refund_policy(days: int) -> str:
    return json.dumps({"eligible": days <= 14, "limit_days": 14})


def escalate_to_human(summary: str, reason: str) -> str:
    return json.dumps({"status": "escalated", "queue": "tier-2", "summary": summary})


TOOLS_IMPL = {"lookup_account": lookup_account, "check_refund_policy": check_refund_policy,
              "escalate_to_human": escalate_to_human}

SCHEMAS = {
    "lookup_account": {"type": "function", "function": {
        "name": "lookup_account", "description": "Account facts by email.",
        "parameters": {"type": "object", "properties": {"email": {"type": "string"}},
                       "required": ["email"]}}},
    "check_refund_policy": {"type": "function", "function": {
        "name": "check_refund_policy", "description": "Is a refund allowed after N days?",
        "parameters": {"type": "object", "properties": {"days": {"type": "integer"}},
                       "required": ["days"]}}},
    "escalate_to_human": {"type": "function", "function": {
        "name": "escalate_to_human", "description": "Hand the case to a human queue.",
        "parameters": {"type": "object", "properties": {
            "summary": {"type": "string"}, "reason": {"type": "string"}},
            "required": ["summary", "reason"]}}},
}


# --- the line. `next` is the allowed handoff targets for each stage. ---------

STAGES = {
    "triage": {
        "system": "You are first-line triage. Classify the issue and gather the customer's "
                  "email if present. Do not solve it. Hand off.",
        "tools": [],
        "next": ["billing", "technical"],
    },
    "billing": {
        "system": "You are billing. Look up the account, check the refund policy, and state "
                  "the decision. If the customer is outside policy but angry, hand off to retention.",
        "tools": ["lookup_account", "check_refund_policy"],
        "next": ["retention"],
    },
    "technical": {
        "system": "You are technical support. Diagnose and give a concrete next step. "
                  "You are the end of the line.",
        "tools": [],
        "next": [],
    },
    "retention": {
        "system": "You are retention. Offer a goodwill gesture within policy, or escalate.",
        "tools": ["escalate_to_human"],
        "next": [],
    },
}


def run_stage(stage: str, case: str, notes: list[str]) -> tuple[str, str | None]:
    """Returns (this stage's output, next stage or None).

    The handoff decision is made with a tool-shaped choice: we give the model a
    `handoff` function whose `to` parameter is an enum of ONLY the legal next stages.
    Constraining the enum is what keeps the graph bounded.
    """
    spec = STAGES[stage]
    tools = [SCHEMAS[t] for t in spec["tools"]]
    if spec["next"]:
        tools.append({"type": "function", "function": {
            "name": "handoff",
            "description": "Pass the case to another team when it isn't yours to finish.",
            "parameters": {"type": "object", "properties": {
                "to": {"type": "string", "enum": spec["next"]},
                "why": {"type": "string"}}, "required": ["to", "why"]}}})

    messages = [
        {"role": "system", "content": spec["system"] + "\nBe brief. Two sentences maximum."},
        {"role": "user", "content": f"Case: {case}\n\nNotes from earlier stages:\n"
                                    + ("\n".join(notes) or "(none)")},
    ]

    for _ in range(5):
        msg = client.chat.complete(
            model=MODEL, messages=messages, tools=tools or None, tool_choice="auto"
        ).choices[0].message
        messages.append(msg)

        if not msg.tool_calls:
            return msg.content, None

        for call in msg.tool_calls:
            args = json.loads(call.function.arguments or "{}")

            if call.function.name == "handoff":
                print(f"    handoff -> {args['to']}: {args['why']}")
                return msg.content or args["why"], args["to"]

            result = TOOLS_IMPL[call.function.name](**args)
            print(f"    {call.function.name}({args}) -> {result[:80]}")
            messages.append({"role": "tool", "name": call.function.name,
                             "tool_call_id": call.id, "content": result})

    return "(stage stalled)", None


def run(case: str, start: str = "triage", max_hops: int = 5) -> list[str]:
    notes: list[str] = []
    stage: str | None = start

    for hop in range(max_hops):  # bound the line — cycles are possible in a graph
        if stage is None:
            break
        print(f"\n[{hop}] stage: {stage}")
        output, stage = run_stage(stage, case, notes)
        print(f"    = {output}")
        notes.append(f"{output}")
    return notes


if __name__ == "__main__":
    run("Hi, I'm at priya@northwind.example. I was charged 588.00 on Aug 18 and I want it "
        "refunded. I've been a customer for two years and I'm pretty annoyed.")
