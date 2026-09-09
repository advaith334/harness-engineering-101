"""Structured output — force the model into a schema so normal code can consume it.

The interface layer. Every topology in this repo that branches on a model's answer
depends on this working reliably.
"""

import json
import os

from mistralai.client import Mistral

client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
MODEL = "mistral-medium-latest"  # or pin: mistral-medium-3-5


# The schema you want back. Keep it flat and name the fields like you'd name columns.
SCHEMA = {
    "urgency": "one of: low | medium | high",
    "category": "one of: billing | bug | feature_request | other",
    "summary": "one sentence",
    "customer_is_angry": "true or false",
}

TICKET = """Subject: charged twice!!
I've been billed 49.00 twice this month and the export button has been throwing
a 500 since Tuesday. This is the third time I'm writing in. Fix it or we churn.
"""


def extract(text: str) -> dict:
    """One call, JSON mode on, parsed into a real dict."""
    resp = client.chat.complete(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": "You extract structured data. Reply with JSON matching this shape "
                f"exactly, no extra keys:\n{json.dumps(SCHEMA, indent=2)}",
            },
            {"role": "user", "content": text},
        ],
        # This is the important line: the API guarantees parseable JSON.
        response_format={"type": "json_object"},
        temperature=0,  # extraction is not a creative task
    )
    return json.loads(resp.choices[0].message.content)


def validate(data: dict) -> list[str]:
    """Never trust the shape. JSON mode guarantees *valid JSON*, not *your schema*."""
    errors = []
    if data.get("urgency") not in {"low", "medium", "high"}:
        errors.append(f"bad urgency: {data.get('urgency')!r}")
    if data.get("category") not in {"billing", "bug", "feature_request", "other"}:
        errors.append(f"bad category: {data.get('category')!r}")
    if not isinstance(data.get("customer_is_angry"), bool):
        errors.append("customer_is_angry is not a bool")
    return errors


if __name__ == "__main__":
    ticket = extract(TICKET)
    print(json.dumps(ticket, indent=2))

    problems = validate(ticket)
    print("\nvalidation:", problems or "ok")

    # And now it's just Python — this is the whole point.
    if ticket["urgency"] == "high" and ticket["category"] == "billing":
        print("-> page the billing on-call")
