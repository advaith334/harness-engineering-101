"""The same idea using Mistral's first-party multi-agent primitive: HANDOFFS.

You create real Agent objects server-side, declare which agents each may hand off to,
and start one conversation. Mistral routes between them for you and keeps the whole
multi-agent trace in one conversation object.

Difference from main.py: handoffs are *sequential delegation* (control moves to another
agent) rather than *parallel fan-out*. Use handoffs when the next specialist depends on
what the last one found; use main.py's ThreadPoolExecutor when they're independent.
"""

import os

from mistralai.client import Mistral

client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
MODEL = "mistral-medium-latest"


def build_team() -> str:
    """Create the agents once. In production you'd store these IDs, not recreate them."""
    docs = client.beta.agents.create(
        model=MODEL,
        name="docs-agent",
        description="Answers questions about product features, pricing and limits.",
        instructions="You answer from product knowledge. Be factual and brief.",
        tools=[{"type": "web_search"}],  # a hosted tool — nothing to implement
    )

    account = client.beta.agents.create(
        model=MODEL,
        name="account-agent",
        description="Reports on a customer's contract, seats and renewal timing.",
        instructions="You report account facts. If you need product detail, hand off.",
    )

    triage = client.beta.agents.create(
        model=MODEL,
        name="triage-agent",
        description="Front door. Routes to the right specialist.",
        instructions="Decide which specialist should answer and hand off to them. "
                     "Do not answer specialist questions yourself.",
    )

    # The topology is this one line: who may delegate to whom.
    client.beta.agents.update(agent_id=triage.id, handoffs=[docs.id, account.id])
    client.beta.agents.update(agent_id=account.id, handoffs=[docs.id])

    return triage.id


if __name__ == "__main__":
    triage_id = build_team()

    response = client.beta.conversations.start(
        agent_id=triage_id,
        inputs="Acme Corp renews in 47 days on Pro. What would Enterprise get them?",
        # "server" = Mistral executes handoffs internally (default).
        # "client" = control returns to you at each handoff, so you can log/approve/override.
        handoff_execution="server",
    )

    # Every hop is an entry — this is the multi-agent trace.
    for entry in response.outputs:
        print(f"[{entry.type}] {str(entry)[:160]}")
