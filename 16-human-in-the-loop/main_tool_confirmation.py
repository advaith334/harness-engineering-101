"""The same gate, using the Mistral SDK's built-in tool confirmation.

Register a function with `requires_confirmation=True` and the runner will not execute it.
It raises `DeferredToolCallsException` instead, carrying the pending calls. You decide,
then resume by passing back DeferredToolCallConfirmation / DeferredToolCallRejection.

The advantage over main.py: the pause is a first-class, serializable object. You can
raise it out of a web request, put it in a queue, and resume from a different process
tomorrow — which is what a real approval flow needs.
"""

import asyncio
import json
import os

from mistralai.client import Mistral
from mistralai.extra.exceptions import DeferredToolCallsException
from mistralai.extra.run.context import RunContext

client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
MODEL = "mistral-medium-latest"

_LOG: list[str] = []


def get_ticket(ticket_id: str) -> str:
    """Fetch a support ticket by id."""
    return json.dumps({"status": "open", "customer": "Acme", "refund_requested": 4900,
                       "days_since_charge": 22})


def issue_refund(ticket_id: str, amount_cents: int) -> str:
    """Issue a refund in cents. Irreversible."""
    _LOG.append(f"REFUNDED {amount_cents} on {ticket_id}")
    return json.dumps({"status": "refunded"})


async def main() -> None:
    async with RunContext(model=MODEL) as ctx:
        ctx.register_func(get_ticket)                              # AUTO
        ctx.register_func(issue_refund, requires_confirmation=True)  # gated

        inputs = "Ticket T-1041: customer wants a refund. Check it and refund if appropriate."

        while True:
            try:
                result = await client.beta.conversations.run_async(run_ctx=ctx, inputs=inputs)
                print("\n", result.output_as_text)
                break

            except DeferredToolCallsException as pending:
                # `pending.to_dict()` is a JSON-serializable checkpoint: put it in a queue,
                # rebuild it later with DeferredToolCallsException.from_dict(...), and resume.
                # That is what makes this an approval *workflow* and not just an input() call.
                responses = []
                for entry in pending.deferred_calls:
                    print(f"\n  *** APPROVAL NEEDED ***\n  {entry.tool_name}({entry.arguments})")
                    if input("  approve? [y/N] ").strip().lower() in ("y", "yes"):
                        responses.append(entry.confirm())
                    else:
                        responses.append(entry.reject("human declined"))
                inputs = responses  # resume by feeding the decisions back in

    print("\nside effects:", _LOG or "none")


if __name__ == "__main__":
    asyncio.run(main())
