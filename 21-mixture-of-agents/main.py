"""Mixture-of-Agents — layers of agents refine each other's drafts, then aggregate.

Proposers answer the same question independently and in parallel. An aggregator reads
ALL the drafts and writes a better one. Optionally repeat: the layer-2 proposers see
layer 1's aggregate as reference material, which is what makes this "layered" rather
than just voting.

The result reliably beats any single proposer, because different drafts fail in
different places and the aggregator can see where they disagree.

Contrast with:
  - self-consistency (folder 11 notes): same prompt N times, take the majority. Cheaper,
    works only when there's one right answer to vote on.
  - debate (folder 19): agents argue with each other. Adversarial, sequential.
  - MoA (here): agents don't interact. Parallel, cooperative, aggregated.

Diversity is the active ingredient. Vary the MODEL where you can; vary the persona and
temperature where you can't.
"""

import os
from concurrent.futures import ThreadPoolExecutor

from mistralai.client import Mistral

client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])

# Real diversity comes from different models. Vary these if your key has access.
PROPOSERS = [
    {"model": "mistral-medium-latest", "temp": 0.4,
     "system": "You are a systems engineer. Answer concretely, with mechanisms and numbers."},
    {"model": "mistral-medium-latest", "temp": 0.9,
     "system": "You are a contrarian consultant. Lead with what everyone gets wrong."},
    {"model": "mistral-small-latest", "temp": 0.7,
     "system": "You are a pragmatist. Answer in the fewest words that are still useful."},
]
AGGREGATOR = "mistral-medium-latest"

QUESTION = ("Our RAG chatbot answers correctly about 70% of the time. "
            "What should we do first to improve it, and why that first?")


def propose(spec: dict, question: str, reference: str | None = None) -> str:
    user = question
    if reference:
        # Layer 2+: earlier answers are *reference material*, not instructions.
        user = (f"{question}\n\nA previous synthesized answer is below. Use it as reference; "
                f"improve on it and correct anything wrong. Do not simply agree.\n\n{reference}")
    return client.chat.complete(
        model=spec["model"],
        messages=[{"role": "system", "content": spec["system"] + " Under 120 words."},
                  {"role": "user", "content": user}],
        temperature=spec["temp"],
    ).choices[0].message.content


def aggregate(question: str, drafts: list[str]) -> str:
    listing = "\n\n".join(f"[draft {i+1}]\n{d}" for i, d in enumerate(drafts))
    return client.chat.complete(
        model=AGGREGATOR,
        messages=[
            {"role": "system", "content":
                "You synthesize multiple expert drafts into one better answer. Keep what they "
                "agree on. Where they conflict, pick the better-reasoned side and say why in one "
                "clause. Drop anything unsupported. Do not mention that there were drafts."},
            {"role": "user", "content": f"Question: {question}\n\n{listing}"},
        ],
        temperature=0.2,
    ).choices[0].message.content


def moa(question: str, layers: int = 2) -> str:
    reference: str | None = None

    for layer in range(1, layers + 1):
        with ThreadPoolExecutor(max_workers=len(PROPOSERS)) as pool:
            drafts = list(pool.map(lambda s: propose(s, question, reference), PROPOSERS))

        print(f"\n=== layer {layer}: {len(drafts)} drafts ===")
        for i, d in enumerate(drafts, 1):
            print(f"  [{i}] {d[:100].replace(chr(10), ' ')}...")

        reference = aggregate(question, drafts)
        print(f"  -> aggregate: {reference[:120].replace(chr(10), ' ')}...")

    return reference


if __name__ == "__main__":
    print("\n=== FINAL ===\n" + moa(QUESTION, layers=2))
