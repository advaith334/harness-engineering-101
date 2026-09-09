"""ReAct — the agent loop. Reason -> Act -> Observe, repeated until done.

This is THE pattern. Once you can write this loop from memory you can build almost
any agent, because everything else in families VII-XII is a variation on it:
swap the tools, swap what ends the loop, swap who approves the actions.

The whole thing is 20 lines. The rest of this file is the tools.
"""

import json
import os
from datetime import date, timedelta

from mistralai.client import Mistral

client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
MODEL = "mistral-medium-latest"


# --- The tools: plain Python functions. Fake data, real signatures. ----------

WEATHER = {"Paris": "14C, rain", "Lisbon": "24C, sunny", "Oslo": "3C, snow"}
PRICES = {"Paris": 210, "Lisbon": 180, "Oslo": 340}


def get_weather(city: str) -> str:
    return WEATHER.get(city, f"no data for {city}")


def get_flight_price(city: str, when: str = "") -> str:
    price = PRICES.get(city)
    return f"{price} EUR return" if price else f"no route to {city}"


def today() -> str:
    return date.today().isoformat()


TOOLS_IMPL = {"get_weather": get_weather, "get_flight_price": get_flight_price, "today": today}

# The schemas the model sees. The `description` fields ARE the prompt — this is
# where most agent debugging happens, not in the system message.
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Current weather for a city. Use before recommending a destination.",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string", "description": "City name, e.g. Paris"}},
                "required": ["city"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_flight_price",
            "description": "Return flight price in EUR for a city.",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string"},
                    "when": {"type": "string", "description": "ISO date, optional"},
                },
                "required": ["city"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "today",
            "description": "Today's date in ISO format.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


# --- The loop ----------------------------------------------------------------

def run(task: str, max_steps: int = 8) -> str:
    messages = [
        {"role": "system", "content": "You are a travel assistant. Use tools to check facts "
                                      "before answering. Never guess weather or prices."},
        {"role": "user", "content": task},
    ]

    for step in range(max_steps):
        resp = client.chat.complete(
            model=MODEL, messages=messages, tools=TOOLS, tool_choice="auto"
        )
        msg = resp.choices[0].message
        messages.append(msg)

        # No tool calls -> the model is answering. That's the exit condition.
        if not msg.tool_calls:
            return msg.content

        for call in msg.tool_calls:
            args = json.loads(call.function.arguments or "{}")
            print(f"  [{step}] {call.function.name}({args})", end=" ")
            try:
                result = TOOLS_IMPL[call.function.name](**args)
            except Exception as e:
                # Feed errors BACK to the model. It will usually correct itself —
                # that's the difference between an agent and a pipeline.
                result = f"ERROR: {e}"
            print(f"-> {result}")

            messages.append({
                "role": "tool",
                "name": call.function.name,
                "tool_call_id": call.id,
                "content": str(result),
            })

    return "hit max_steps without finishing"  # ALWAYS bound the loop


if __name__ == "__main__":
    print(run("I want a warm city break next weekend, under 250 EUR. "
              "Compare Paris, Lisbon and Oslo and pick one."))
