"""Prompt chaining — output of call N becomes input to call N+1.

The control flow is authored by you, not decided by the model. That makes it
deterministic, testable, and easy to debug: you can print between every step.
"""

import os

from mistralai.client import Mistral

client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
MODEL = "mistral-medium-latest"


def chat(prompt: str, system: str | None = None, **kw) -> str:
    msgs = ([{"role": "system", "content": system}] if system else []) + [
        {"role": "user", "content": prompt}
    ]
    return client.chat.complete(model=MODEL, messages=msgs, **kw).choices[0].message.content


TRANSCRIPT = """
[10:02] Priya: ok so the Q3 launch. Where are we on the pricing page?
[10:03] Marco: blocked. Legal hasn't signed off on the "unlimited" wording.
[10:04] Priya: I'll ping legal today. Marco, can you have the fallback copy ready by Thursday?
[10:05] Marco: yep, Thursday.
[10:07] Dana: separately, the signup funnel is converting at 2.1%, down from 3.4%.
[10:08] Priya: that's the bigger fire. Dana, can you get me a breakdown by traffic source by Friday?
[10:09] Dana: on it.
[10:11] Priya: let's push the launch to Oct 6 to be safe. I'll tell the exec team.
"""


# --- The chain. Three narrow steps beat one mega-prompt. ---------------------

def step_1_extract(transcript: str) -> str:
    """Pull raw facts. No interpretation yet."""
    return chat(
        f"List every decision made and every action item, verbatim-ish, as bullets.\n\n{transcript}",
        system="You are a precise note-taker. Extract only what was said. Do not infer.",
        temperature=0,
    )


def step_2_structure(facts: str) -> str:
    """Reshape. Now it can interpret, but only over the facts from step 1."""
    return chat(
        f"Turn these into a table with columns: Owner | Task | Due | Type (decision/action).\n\n{facts}",
        system="You reorganize notes. Use only the given facts.",
        temperature=0,
    )


def step_3_summarize(table: str) -> str:
    """Compose. The audience changes, so the instruction changes."""
    return chat(
        f"Write a 3-sentence update for the exec team. Lead with the risk.\n\n{table}",
        system="You write terse executive updates. No preamble, no bullet points.",
    )


if __name__ == "__main__":
    facts = step_1_extract(TRANSCRIPT)
    print("=== 1. EXTRACT ===\n", facts, "\n")

    table = step_2_structure(facts)
    print("=== 2. STRUCTURE ===\n", table, "\n")

    # A cheap deterministic gate between steps — this is a chain's superpower.
    if "Dana" not in table:
        print("!! warning: expected owner missing, step 2 likely dropped a row")

    update = step_3_summarize(table)
    print("=== 3. SUMMARIZE ===\n", update)
