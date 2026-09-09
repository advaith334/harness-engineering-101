"""Agentic RAG — retrieval becomes a tool the model calls, not a fixed pre-step.

Naive RAG retrieves exactly once, with the user's literal question, whether or not
that's a good idea. Here the model decides *whether* to search, *what* to search for,
and *how many times* — so it can decompose a multi-part question, notice a thin result
and re-query, or skip retrieval entirely.

This is [05-rag-naive] + [08-react-tools]. That composition is the whole idea.
"""

import json
import math
import os

from mistralai.client import Mistral

client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
MODEL = "mistral-medium-latest"
EMBED_MODEL = "mistral-embed"

# Two separate sources — the agent has to work out which to query, and often both.
POLICY_DOCS = [
    "Refunds: monthly plans are refundable within 14 days. Annual plans pro-rata within 30 days.",
    "Cancellation: you keep access until the end of the paid period. No partial-month credits.",
    "Data retention: workspaces are purged 7 days after deletion. Exports must happen before then.",
]
PRODUCT_DOCS = [
    "Rate limits: Free 60 req/min, Pro 600 req/min. Over the limit returns HTTP 429.",
    "SSO via SAML and OIDC is Enterprise-only and takes about 30 minutes to configure.",
    "The bulk export endpoint is Pro and above, and is capped at 10 exports per day.",
]

INDEXES: dict[str, list[tuple[str, list[float]]]] = {}


def embed(texts: list[str]) -> list[list[float]]:
    return [d.embedding for d in client.embeddings.create(model=EMBED_MODEL, inputs=texts).data]


def cosine(a, b) -> float:
    return sum(x * y for x, y in zip(a, b)) / (
        math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    )


def build_indexes() -> None:
    for name, docs in (("policy", POLICY_DOCS), ("product", PRODUCT_DOCS)):
        INDEXES[name] = list(zip(docs, embed(docs)))


# --- Retrieval, exposed as a tool -------------------------------------------

def search(collection: str, query: str) -> str:
    """The tool body. Note it returns a string — tool results are always text."""
    index = INDEXES.get(collection)
    if index is None:
        return f"unknown collection {collection!r}; valid: {list(INDEXES)}"
    qvec = embed([query])[0]
    hits = sorted(((cosine(qvec, v), d) for d, v in index), reverse=True)[:2]
    return "\n".join(f"({s:.2f}) {d}" for s, d in hits)


TOOLS = [{
    "type": "function",
    "function": {
        "name": "search",
        "description": "Search the knowledge base. Call once per distinct sub-question. "
                       "Rephrase and call again if results look irrelevant.",
        "parameters": {
            "type": "object",
            "properties": {
                "collection": {
                    "type": "string",
                    "enum": ["policy", "product"],
                    "description": "policy = billing, refunds, retention. product = features, limits.",
                },
                "query": {"type": "string", "description": "A focused search phrase, not the "
                                                           "user's full question."},
            },
            "required": ["collection", "query"],
        },
    },
}]


def run(question: str, max_steps: int = 6) -> str:
    messages = [
        {"role": "system", "content":
            "Answer from the knowledge base only. Break multi-part questions into separate "
            "searches. If results are irrelevant, search again with different wording. "
            "If the answer isn't in the knowledge base, say so."},
        {"role": "user", "content": question},
    ]

    for step in range(max_steps):
        msg = client.chat.complete(
            model=MODEL, messages=messages, tools=TOOLS, tool_choice="auto"
        ).choices[0].message
        messages.append(msg)

        if not msg.tool_calls:
            return msg.content

        for call in msg.tool_calls:
            args = json.loads(call.function.arguments or "{}")
            print(f"  [{step}] search({args['collection']!r}, {args['query']!r})")
            messages.append({
                "role": "tool", "name": "search", "tool_call_id": call.id,
                "content": search(**args),
            })

    return "hit max_steps"


if __name__ == "__main__":
    build_indexes()
    for q in [
        # Two sub-questions across two collections — naive RAG retrieves once and misses half.
        "If I cancel my annual plan, do I get money back, and do I lose bulk export first?",
        # No retrieval needed at all — a good agent just answers.
        "Hi, what can you help me with?",
    ]:
        print(f"\nQ: {q}")
        print("A:", run(q))
