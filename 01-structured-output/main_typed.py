"""Same thing, but typed — the Mistral SDK will parse straight into a Pydantic model.

`client.chat.parse(...)` builds the JSON schema from your model, sends it as the
response_format, and hands you back a validated instance. Prefer this over hand-rolled
JSON mode whenever you're on the Mistral SDK: you get generation *and* validation in
one call, and the schema can never drift from the type your code uses.
"""

import os
from typing import Literal

from mistralai.client import Mistral
from pydantic import BaseModel, Field

client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
MODEL = "mistral-medium-latest"


class Ticket(BaseModel):
    urgency: Literal["low", "medium", "high"]
    category: Literal["billing", "bug", "feature_request", "other"]
    summary: str = Field(description="one sentence")
    customer_is_angry: bool


TICKET = """Subject: charged twice!!
I've been billed 49.00 twice this month and the export button has been throwing
a 500 since Tuesday. This is the third time I'm writing in. Fix it or we churn.
"""

if __name__ == "__main__":
    resp = client.chat.parse(
        model=MODEL,
        messages=[
            {"role": "system", "content": "Extract the ticket fields."},
            {"role": "user", "content": TICKET},
        ],
        response_format=Ticket,  # a Pydantic class, not a dict
        temperature=0,
    )

    ticket: Ticket = resp.choices[0].message.parsed
    print(ticket)
    print("\nurgency ->", ticket.urgency)  # typed attribute access, IDE autocomplete works
