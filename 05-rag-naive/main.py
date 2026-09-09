"""Naive RAG — embed the query, fetch top-k similar chunks, stuff them in the prompt.

The canonical retrieval loop and the correct starting point for any "answer over
our data" ask. Get this working first, then measure, then escalate to 06.

No vector DB, no numpy: an in-memory list and a dot product. That is genuinely all
a vector store is until you have millions of chunks.
"""

import math
import os

from mistralai.client import Mistral

client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
MODEL = "mistral-medium-latest"
EMBED_MODEL = "mistral-embed"


# --- The "corpus". In the interview: read files, split on paragraphs. --------

DOCS = [
    "Refunds: customers on monthly plans may request a refund within 14 days of a charge. "
    "Annual plans are refundable pro-rata within 30 days.",
    "Rate limits: the Free tier allows 60 requests/minute. Pro allows 600/minute. "
    "Enterprise limits are set per contract. Exceeding a limit returns HTTP 429.",
    "SSO: SAML and OIDC are available on Enterprise only. Setup requires a metadata XML "
    "upload and takes about 30 minutes.",
    "Data retention: logs are kept 30 days on Free, 1 year on Pro, and are configurable on "
    "Enterprise. Deleted workspaces are purged after 7 days.",
    "Support SLAs: Free is community-only. Pro is a 24-hour first response. Enterprise is "
    "1 hour for P1 incidents, 24/7.",
    "Pricing: Free is $0. Pro is $49/user/month. Enterprise is custom, starting around "
    "$25,000/year. Annual billing saves 20%.",
]


# --- Index -------------------------------------------------------------------

def embed(texts: list[str]) -> list[list[float]]:
    resp = client.embeddings.create(model=EMBED_MODEL, inputs=texts)
    return [d.embedding for d in resp.data]


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb)


INDEX: list[tuple[str, list[float]]] = []


def build_index() -> None:
    # One batched call for the whole corpus — do not embed in a loop.
    for doc, vec in zip(DOCS, embed(DOCS)):
        INDEX.append((doc, vec))


# --- Retrieve ----------------------------------------------------------------

def retrieve(query: str, k: int = 2) -> list[tuple[float, str]]:
    qvec = embed([query])[0]
    scored = [(cosine(qvec, vec), doc) for doc, vec in INDEX]
    scored.sort(reverse=True)
    return scored[:k]


# --- Generate ----------------------------------------------------------------

def answer(query: str, k: int = 2) -> str:
    hits = retrieve(query, k)
    context = "\n\n".join(f"[{i+1}] {doc}" for i, (_, doc) in enumerate(hits))

    print(f"  retrieved (k={k}):")
    for score, doc in hits:
        print(f"    {score:.3f}  {doc[:70]}...")

    return client.chat.complete(
        model=MODEL,
        messages=[
            {
                "role": "system",
                # The two rules that make RAG trustworthy: ground it, and let it say no.
                "content": "Answer using ONLY the context. Cite sources like [1]. "
                           "If the context doesn't contain the answer, say so.",
            },
            {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {query}"},
        ],
        temperature=0,
    ).choices[0].message.content


if __name__ == "__main__":
    build_index()
    for q in [
        "Can I get my money back if I cancel after a week?",
        "What happens if I send too many requests?",
        "Do you support Kubernetes?",  # not in the corpus — it should decline
    ]:
        print(f"\nQ: {q}")
        print("A:", answer(q))
