"""Advanced RAG — naive RAG plus the three refinements that actually move the needle.

  1. Query rewriting (HyDE)  — fix the question before you search with it.
  2. Hybrid search           — dense vectors OR keyword, fused. Catches what embeddings miss.
  3. Reranking               — retrieve wide, then let a model pick what's genuinely relevant.

Each is independently useful. Add them one at a time, measuring, not all at once.
"""

import math
import os
import re

from mistralai.client import Mistral

client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
MODEL = "mistral-medium-latest"
SMALL = "mistral-small-latest"
EMBED_MODEL = "mistral-embed"

DOCS = [
    "Refunds: customers on monthly plans may request a refund within 14 days of a charge. "
    "Annual plans are refundable pro-rata within 30 days.",
    "Rate limits: the Free tier allows 60 requests/minute. Pro allows 600/minute. "
    "Exceeding a limit returns HTTP 429 with a Retry-After header.",
    "Error codes: E1004 means the webhook signature failed validation. E1005 means the payload "
    "exceeded 1MB. E2001 means the destination timed out.",
    "SSO: SAML and OIDC are available on Enterprise only. Setup requires a metadata XML upload.",
    "Data retention: logs are kept 30 days on Free, 1 year on Pro. Deleted workspaces purge after 7 days.",
    "Pricing: Free is $0. Pro is $49/user/month. Enterprise starts around $25,000/year.",
]

INDEX: list[tuple[str, list[float]]] = []


def embed(texts: list[str]) -> list[list[float]]:
    return [d.embedding for d in client.embeddings.create(model=EMBED_MODEL, inputs=texts).data]


def cosine(a, b) -> float:
    return sum(x * y for x, y in zip(a, b)) / (
        math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    )


def build_index() -> None:
    INDEX.extend(zip(DOCS, embed(DOCS)))


# --- 1. Query rewriting (HyDE) ----------------------------------------------
# Questions and answers don't look alike in embedding space. So embed a *fake answer*
# instead of the question — it lands much closer to the real one.

def hyde(query: str) -> str:
    return client.chat.complete(
        model=SMALL,
        messages=[{
            "role": "user",
            "content": f"Write one sentence that would plausibly appear in documentation "
                       f"answering: {query}\nInvent specifics. Output only the sentence.",
        }],
        temperature=0,
    ).choices[0].message.content


# --- 2. Hybrid search --------------------------------------------------------
# Dense embeddings are great at meaning and bad at literals. "E1004" has no semantics.
# Keyword scoring covers exactly that gap. Fuse the two rankings.

def dense_search(text: str, k: int) -> list[str]:
    qvec = embed([text])[0]
    ranked = sorted(((cosine(qvec, v), d) for d, v in INDEX), reverse=True)
    return [d for _, d in ranked[:k]]


def keyword_search(query: str, k: int) -> list[str]:
    terms = set(re.findall(r"\w+", query.lower()))
    ranked = sorted(
        ((len(terms & set(re.findall(r"\w+", d.lower()))), d) for d in DOCS),
        key=lambda t: -t[0],
    )
    return [d for score, d in ranked[:k] if score > 0]


def fuse(*rankings: list[str], k: int = 4) -> list[str]:
    """Reciprocal rank fusion: score by position, not by each system's incomparable scores."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, doc in enumerate(ranking):
            scores[doc] = scores.get(doc, 0) + 1 / (60 + rank)  # 60 is the usual RRF constant
    return sorted(scores, key=lambda d: -scores[d])[:k]


# --- 3. Rerank ---------------------------------------------------------------
# Retrieval optimizes for recall (cast wide). Reranking optimizes for precision
# (keep only what helps). Doing both is why this beats naive RAG.

def rerank(query: str, docs: list[str], keep: int = 2) -> list[str]:
    listing = "\n".join(f"{i}: {d}" for i, d in enumerate(docs))
    raw = client.chat.complete(
        model=SMALL,
        messages=[{
            "role": "user",
            "content": f"Question: {query}\n\nPassages:\n{listing}\n\n"
                       f"Reply with the {keep} most useful passage numbers, comma-separated. Numbers only.",
        }],
        temperature=0,
    ).choices[0].message.content
    picked = [int(n) for n in re.findall(r"\d+", raw) if int(n) < len(docs)]
    return [docs[i] for i in picked[:keep]] or docs[:keep]


# --- Pipeline ----------------------------------------------------------------

def answer(query: str) -> str:
    hypothetical = hyde(query)
    print(f"  hyde     : {hypothetical}")

    dense = dense_search(hypothetical, k=4)   # search with the fake answer, not the question
    sparse = keyword_search(query, k=4)       # search with the literal words the user typed
    candidates = fuse(dense, sparse, k=4)
    print(f"  fused    : {len(candidates)} candidates")

    top = rerank(query, candidates, keep=2)
    print(f"  reranked : {[d[:45] + '...' for d in top]}")

    context = "\n\n".join(f"[{i+1}] {d}" for i, d in enumerate(top))
    return client.chat.complete(
        model=MODEL,
        messages=[
            {"role": "system", "content": "Answer using ONLY the context. Cite like [1]. "
                                          "If it isn't there, say so."},
            {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {query}"},
        ],
        temperature=0,
    ).choices[0].message.content


if __name__ == "__main__":
    build_index()
    for q in [
        "what does E1004 mean",              # literal code: keyword search saves this one
        "can I get my money back after 3 weeks",  # semantic: dense + HyDE save this one
    ]:
        print(f"\nQ: {q}")
        print("A:", answer(q))
