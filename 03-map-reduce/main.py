"""Map-reduce / fan-out-fan-in — split, process in parallel, aggregate.

The standard answer for "do something across N documents" where N x document
doesn't fit in one context window, or where you want the wall-clock win.
"""

import os
from concurrent.futures import ThreadPoolExecutor

from mistralai.client import Mistral

client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
MODEL = "mistral-medium-latest"


def chat(prompt: str, system: str | None = None, **kw) -> str:
    msgs = ([{"role": "system", "content": system}] if system else []) + [
        {"role": "user", "content": prompt}
    ]
    return client.chat.complete(model=MODEL, messages=msgs, **kw).choices[0].message.content


# Pretend these came off disk. In practice: glob a directory.
REVIEWS = [
    "Setup took 4 hours because the docs skip the DNS step. Product itself is great once running.",
    "Support answered in 12 minutes on a Sunday. Genuinely impressed. Pricing is steep though.",
    "Third outage this month. We're evaluating alternatives. The status page wasn't even updated.",
    "Love the API. The dashboard is slow and I basically never use it.",
    "Onboarding docs are still missing the DNS configuration bit. Took us most of a day.",
    "Billing charged us twice and it took two weeks to refund. Product is fine, ops are not.",
    "Fast, reliable for us, no complaints in 6 months. Dashboard could use a dark mode.",
    "The API rate limits aren't documented anywhere and we hit them in production.",
]


# --- MAP: one narrow call per chunk, run concurrently ------------------------

def map_one(review: str) -> str:
    return chat(
        f"Review: {review}\n\nIn one line: the single complaint or praise, and its theme "
        "(docs/support/reliability/pricing/ux/billing).",
        system="You compress feedback. One line. No preamble.",
        temperature=0,
    )


def map_all(reviews: list[str]) -> list[str]:
    # I/O-bound, so threads are the right tool. 8 workers = 8 concurrent HTTP calls.
    with ThreadPoolExecutor(max_workers=8) as pool:
        return list(pool.map(map_one, reviews))


# --- REDUCE: one call over the compressed outputs ---------------------------

def reduce(summaries: list[str]) -> str:
    joined = "\n".join(f"- {s}" for s in summaries)
    return chat(
        f"{joined}\n\nCluster these into themes. For each: theme, count, and the fix. "
        "Order by how much it hurts.",
        system="You are a product analyst. Be concrete. No filler.",
    )


if __name__ == "__main__":
    print(f"MAP: {len(REVIEWS)} reviews in parallel...")
    summaries = map_all(REVIEWS)
    for s in summaries:
        print("  ·", s)

    print("\nREDUCE:")
    print(reduce(summaries))

    # If `summaries` is itself too big for one context window, reduce in a tree:
    # chunk it into groups, reduce each group, then reduce the reductions.
