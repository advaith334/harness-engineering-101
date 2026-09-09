"""The same agent, using the runner built into the Mistral SDK.

`RunContext` + `conversations.run_async` IS the loop from main.py — it does the
tool-schema generation (from your type hints and docstrings), the execution, the
message bookkeeping, and the termination check.

Use this when you want it working fast. Know main.py so you can debug it when it
misbehaves, and so you can port the pattern to any provider.
"""

import asyncio
import os
from datetime import date

from mistralai.client import Mistral
from mistralai.extra.run.context import RunContext

client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
MODEL = "mistral-medium-latest"


# No JSON schemas by hand: the runner derives them from the signature + docstring.
def get_weather(city: str) -> str:
    """Current weather for a city."""
    return {"Paris": "14C, rain", "Lisbon": "24C, sunny", "Oslo": "3C, snow"}.get(city, "unknown")


PRICES = {"Paris": 210, "Lisbon": 180, "Oslo": 340}


def get_flight_price(city: str) -> str:
    """Return flight price in EUR for a city."""
    return f"{PRICES.get(city, 0)} EUR return"


def today() -> str:
    """Today's date, ISO format."""
    return date.today().isoformat()


async def main() -> None:
    async with RunContext(model=MODEL) as ctx:
        for fn in (get_weather, get_flight_price, today):
            ctx.register_func(fn)

        result = await client.beta.conversations.run_async(
            run_ctx=ctx,
            inputs="I want a warm city break next weekend under 250 EUR. "
                   "Compare Paris, Lisbon and Oslo and pick one.",
        )

    # Every step the runner took is on the result — this is your trace.
    for entry in result.output_entries:
        print(f"  {entry.type}: {str(entry)[:110]}")

    print("\n", result.output_as_text)  # a property, not a method


if __name__ == "__main__":
    asyncio.run(main())
