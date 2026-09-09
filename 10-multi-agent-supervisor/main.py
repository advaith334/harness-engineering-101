"""Supervisor / orchestrator-worker — a lead agent delegates to specialist workers.

The most common production multi-agent shape, and the only one worth reaching for
first. A worker is not a magic entity: it is a system prompt + its own tool subset +
its own message history. Context isolation is the actual benefit — each worker sees
3 tools instead of 30, so each one is accurate.

Workers run in PARALLEL because they don't need each other's output. If they did,
you'd want [09-plan-and-execute] instead.
"""

import json
import os
from concurrent.futures import ThreadPoolExecutor

from mistralai.client import Mistral

client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
MODEL = "mistral-medium-latest"


# --- Each worker owns a few tools. No worker sees another's tools. -----------

def search_docs(query: str) -> str:
    return {"pricing": "Pro is $49/user/mo; Enterprise from $25k/yr, annual saves 20%.",
            "limits": "Free 60 req/min, Pro 600 req/min, 429 on overage."}.get(
        query.split()[0].lower(), "Pro is $49/user/mo. Free tier 60 req/min.")


def query_crm(company: str) -> str:
    return f"{company}: 340 seats, Pro plan, renewal in 47 days, 2 open P1 tickets."


def get_usage(company: str) -> str:
    return f"{company}: 1.2M API calls/mo, hitting 429s ~40x/day, 3 users on SSO waitlist."


WORKERS = {
    "docs": {
        "system": "You answer from product documentation. Cite the fact, nothing more.",
        "tools": ["search_docs"],
    },
    "account": {
        "system": "You are an account researcher. Report contract and relationship facts.",
        "tools": ["query_crm"],
    },
    "usage": {
        "system": "You analyze telemetry. Report numbers and what they imply.",
        "tools": ["get_usage"],
    },
}

TOOLS_IMPL = {"search_docs": search_docs, "query_crm": query_crm, "get_usage": get_usage}

TOOL_SCHEMAS = {
    "search_docs": {"type": "function", "function": {
        "name": "search_docs", "description": "Search product docs.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}},
                       "required": ["query"]}}},
    "query_crm": {"type": "function", "function": {
        "name": "query_crm", "description": "Contract and account facts for a company.",
        "parameters": {"type": "object", "properties": {"company": {"type": "string"}},
                       "required": ["company"]}}},
    "get_usage": {"type": "function", "function": {
        "name": "get_usage", "description": "API usage telemetry for a company.",
        "parameters": {"type": "object", "properties": {"company": {"type": "string"}},
                       "required": ["company"]}}},
}


def run_worker(name: str, task: str, max_steps: int = 4) -> str:
    """A worker is just [08-react-tools]'s loop with a narrowed tool list."""
    spec = WORKERS[name]
    messages = [{"role": "system", "content": spec["system"]},
                {"role": "user", "content": task}]
    tools = [TOOL_SCHEMAS[t] for t in spec["tools"]]

    for _ in range(max_steps):
        msg = client.chat.complete(
            model=MODEL, messages=messages, tools=tools, tool_choice="auto"
        ).choices[0].message
        messages.append(msg)
        if not msg.tool_calls:
            return msg.content
        for call in msg.tool_calls:
            args = json.loads(call.function.arguments or "{}")
            messages.append({"role": "tool", "name": call.function.name,
                             "tool_call_id": call.id,
                             "content": str(TOOLS_IMPL[call.function.name](**args))})
    return "(worker hit max_steps)"


# --- 1. Supervisor decomposes ------------------------------------------------

def delegate(goal: str) -> dict[str, str]:
    raw = client.chat.complete(
        model=MODEL,
        messages=[
            {"role": "system", "content":
                "You are a supervisor. Assign a specific sub-task to each specialist that can "
                "help. Omit specialists that can't. Specialists:\n"
                + "\n".join(f"- {n}: {w['system']}" for n, w in WORKERS.items())
                + '\nReply as JSON: {"assignments": {"<specialist>": "<sub-task>"}}'},
            {"role": "user", "content": goal},
        ],
        response_format={"type": "json_object"},
        temperature=0,
    ).choices[0].message.content
    return {k: v for k, v in json.loads(raw)["assignments"].items() if k in WORKERS}


# --- 2. Workers run in parallel, 3. supervisor synthesizes -------------------

def run(goal: str) -> str:
    assignments = delegate(goal)
    print("DELEGATE:")
    for name, task in assignments.items():
        print(f"  {name} <- {task}")

    with ThreadPoolExecutor(max_workers=len(assignments) or 1) as pool:
        futures = {name: pool.submit(run_worker, name, task)
                   for name, task in assignments.items()}
        results = {name: f.result() for name, f in futures.items()}

    print("\nWORKER RESULTS:")
    for name, res in results.items():
        print(f"  [{name}] {res}")

    return client.chat.complete(
        model=MODEL,
        messages=[{"role": "system", "content":
                   "Synthesize the specialist reports into one answer. Note any contradictions."},
                  {"role": "user", "content":
                   f"Goal: {goal}\n\n" + "\n\n".join(f"[{n}]\n{r}" for n, r in results.items())}],
    ).choices[0].message.content


if __name__ == "__main__":
    print("\nSYNTHESIS:", run(
        "Acme Corp's renewal is coming up. Should we push them to Enterprise? "
        "Give me the case in 4 bullets."
    ))
