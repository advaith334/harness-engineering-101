"""Router — classify the request, then send it down a specialized path.

Two wins in one pattern: each downstream prompt stays focused (better quality),
and easy requests get answered by a small cheap model (lower cost + latency).
"""

import json
import os

from mistralai.client import Mistral

client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])

SMALL = "mistral-small-latest"   # the router itself: cheap, fast, one word out
BIG = "mistral-medium-latest"    # only for routes that actually need it


def chat(prompt: str, system: str, model: str = BIG, **kw) -> str:
    return client.chat.complete(
        model=model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        **kw,
    ).choices[0].message.content


# --- The routes. Each is a focused specialist, not a general assistant. -------

ROUTES = {
    "billing": {
        "model": BIG,
        "system": "You are a billing specialist. Cite exact amounts and dates. "
                  "Never promise a refund; say it will be reviewed within 2 business days.",
    },
    "technical": {
        "model": BIG,
        "system": "You are a support engineer. Ask for logs, versions, and repro steps. "
                  "Give a concrete next action.",
    },
    "sales": {
        "model": BIG,
        "system": "You are a solutions engineer. Qualify the use case, then propose a plan tier.",
    },
    "smalltalk": {
        "model": SMALL,  # cost tier: don't spend a big model on 'thanks!'
        "system": "You are a friendly assistant. One short sentence.",
    },
}


def route(query: str) -> str:
    """One cheap call whose only job is to pick a label."""
    raw = chat(
        query,
        system="Classify the user message into exactly one of: "
               f"{', '.join(ROUTES)}. Reply as JSON: {{\"route\": \"...\"}}",
        model=SMALL,
        response_format={"type": "json_object"},
        temperature=0,
    )
    choice = json.loads(raw).get("route")
    # Always have a fallback. A router that can return garbage is a crash waiting to happen.
    return choice if choice in ROUTES else "technical"


def handle(query: str) -> tuple[str, str]:
    name = route(query)
    spec = ROUTES[name]
    return name, chat(query, system=spec["system"], model=spec["model"])


if __name__ == "__main__":
    for q in [
        "You charged me 49 twice on the 3rd. What's going on?",
        "Exports 500 on files over 2GB. Started Tuesday.",
        "Thanks, that fixed it!",
        "We're 200 engineers, do you do SSO and an on-prem option?",
    ]:
        name, answer = handle(q)
        print(f"\n[{name}] {q}\n  -> {answer}")
