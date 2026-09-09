"""Plan-and-execute — a planner writes the whole plan first, an executor runs it.

ReAct decides one step at a time, so on long tasks it drifts: by step 9 it has
forgotten what step 1 was for. Here strategy is separated from execution — the plan
is a visible artifact you can inspect, edit, cost, or hand to a human before anything runs.
"""

import json
import os

from mistralai.client import Mistral

client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
MODEL = "mistral-medium-latest"

# Fake corporate systems. Real signatures, fake bodies.
HEADCOUNT = {"eng": 42, "sales": 18, "support": 9}
SALARIES = {"eng": 165_000, "sales": 120_000, "support": 78_000}


def get_headcount(team: str) -> str:
    return str(HEADCOUNT.get(team, "unknown team"))


def get_avg_salary(team: str) -> str:
    return str(SALARIES.get(team, "unknown team"))


def calculate(expression: str) -> str:
    """Arithmetic belongs in code, never in the model's head."""
    return str(eval(expression, {"__builtins__": {}}, {}))


TOOLS_IMPL = {"get_headcount": get_headcount, "get_avg_salary": get_avg_salary,
              "calculate": calculate}

TOOLS = [
    {"type": "function", "function": {
        "name": "get_headcount", "description": "Headcount for a team (eng, sales, support).",
        "parameters": {"type": "object", "properties": {"team": {"type": "string"}},
                       "required": ["team"]}}},
    {"type": "function", "function": {
        "name": "get_avg_salary", "description": "Average salary in USD for a team.",
        "parameters": {"type": "object", "properties": {"team": {"type": "string"}},
                       "required": ["team"]}}},
    {"type": "function", "function": {
        "name": "calculate", "description": "Evaluate an arithmetic expression, e.g. '42*165000'.",
        "parameters": {"type": "object", "properties": {"expression": {"type": "string"}},
                       "required": ["expression"]}}},
]


# --- 1. PLAN -----------------------------------------------------------------

def plan(goal: str) -> list[str]:
    """One call. Output is a plain list of steps — inspectable before anything runs."""
    raw = client.chat.complete(
        model=MODEL,
        messages=[
            {"role": "system", "content":
                "Break the goal into 2-6 ordered, concrete steps. Each step must be doable with "
                f"one of these tools: {list(TOOLS_IMPL)}. "
                'Reply as JSON: {"steps": ["...", "..."]}'},
            {"role": "user", "content": goal},
        ],
        response_format={"type": "json_object"},
        temperature=0,
    ).choices[0].message.content
    return json.loads(raw)["steps"]


# --- 2. EXECUTE --------------------------------------------------------------

def execute_step(step: str, scratchpad: list[str]) -> str:
    """Each step is a mini agent loop, but it only sees this step + prior results."""
    messages = [
        {"role": "system", "content": "Do exactly this one step using tools. Report the result "
                                      "in one line. Do not do the other steps."},
        {"role": "user", "content": f"Results so far:\n" + ("\n".join(scratchpad) or "(none)")
                                    + f"\n\nYour step: {step}"},
    ]
    for _ in range(4):
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
                result = f"ERROR: {e}"
            print(f"      {call.function.name}({args}) -> {result}")
            messages.append({"role": "tool", "name": call.function.name,
                             "tool_call_id": call.id, "content": str(result)})
    return "step did not complete"


# --- 3. SYNTHESIZE -----------------------------------------------------------

def run(goal: str) -> str:
    steps = plan(goal)
    print("PLAN:")
    for i, s in enumerate(steps, 1):
        print(f"  {i}. {s}")
    # This is the natural place for a human approval gate — see 16-human-in-the-loop.

    scratchpad: list[str] = []
    print("\nEXECUTE:")
    for i, step in enumerate(steps, 1):
        print(f"  step {i}: {step}")
        result = execute_step(step, scratchpad)
        print(f"    = {result}")
        scratchpad.append(f"Step {i} ({step}): {result}")

    return client.chat.complete(
        model=MODEL,
        messages=[{"role": "user", "content":
                   f"Goal: {goal}\n\nStep results:\n" + "\n".join(scratchpad)
                   + "\n\nAnswer the goal in 2-3 sentences."}],
    ).choices[0].message.content


if __name__ == "__main__":
    print("\nANSWER:", run(
        "What is our total annual payroll across eng, sales and support, "
        "and which team is the most expensive?"
    ))
