"""The retrieval funnel — four stages, each narrowing, each traced.

    stage 1  soft SQL pre-filter      thousands -> hundreds
    stage 2  hybrid RRF (3 arms)      hundreds  -> 24
    stage 3  batched rerank           24        -> 8
    stage 4  section assembly         8         -> a token-capped context

Stage 1 is soft on purpose. A planner-supplied filter that matches nothing returns
zero rows silently and the answer downstream is confidently wrong. So: if filtering
leaves fewer than PREFILTER_FLOOR candidates, drop the filter, re-run, and record
`filter_relaxed` on the trace. A hard filter must be requested with strict=True.

Every stage writes its surviving ids to `retrieval_traces`. That table is what lets
evaluation say WHICH stage lost the right chunk — without it, a bad answer is just
a bad answer and you are guessing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import mistral
from config import (ASSEMBLY_TOKEN_BUDGET, FUSED_K, PREFILTER_FLOOR, RERANK_KEEP)
from db import connect
from filters import Filters
from search import Candidate, count_filtered, hybrid_search


@dataclass
class Retrieval:
    """Everything the funnel did, not just what it returned."""
    question: str
    filters: dict
    filter_relaxed: bool
    prefilter_count: int
    fused: list[Candidate] = field(default_factory=list)
    reranked: list[Candidate] = field(default_factory=list)
    assembled: list[Candidate] = field(default_factory=list)
    context: str = ""

    @property
    def citation_map(self) -> dict[int, Candidate]:
        """[1]..[n] -> chunk. The model cites small integers, never chunk ids:
        UUIDs in a prompt get typo'd and the citation check then fails on
        perfectly well-grounded answers."""
        return {i: c for i, c in enumerate(self.assembled, start=1)}


# --- stage 3: rerank ---------------------------------------------------------

def rerank(question: str, candidates: list[Candidate], keep: int) -> list[Candidate]:
    """ONE call listing every candidate. Never one call per candidate."""
    if len(candidates) <= keep or mistral.OFFLINE:
        return candidates[:keep]

    listing = "\n".join(
        f"{i}: [{c.heading_path}] {c.content[:300]}" for i, c in enumerate(candidates))
    raw = mistral.chat(
        "You rank passages by how directly they answer the question. "
        f"Reply with the {keep} most useful passage numbers, comma-separated, best "
        "first. Numbers only, nothing else.",
        f"Question: {question}\n\nPassages:\n{listing}",
        small=True,
    )
    picked, seen = [], set()
    for token in raw.replace(",", " ").split():
        if token.isdigit() and (n := int(token)) < len(candidates) and n not in seen:
            seen.add(n)
            picked.append(candidates[n])
    # Fall back rather than return nothing — a reranker that fails to parse must
    # not be able to empty the context.
    return picked[:keep] or candidates[:keep]


# --- stage 4: assembly -------------------------------------------------------

def assemble(candidates: list[Candidate]) -> tuple[list[Candidate], str]:
    """Expand winners to their surrounding section, within a hard token budget.

    Parent expansion is what turns a 400-token fragment into a coherent answer,
    and it is also how you silently blow the context window: one runbook section
    with a big table is 4k tokens, times eight. So expand greedily by rank and
    drop EXPANSIONS, never chunks, when the budget runs out.
    """
    if not candidates:
        return [], ""

    section_keys = list(dict.fromkeys(c.section_key for c in candidates))
    with connect() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT section_key, string_agg(content, E'\n\n' ORDER BY ordinal),
                   sum(token_count)
            FROM chunks WHERE section_key = ANY(%s) GROUP BY section_key
        """, (section_keys,))
        sections = {k: (text, tok) for k, text, tok in cur.fetchall()}

    used, budget, kept, parts = set(), 0, [], []
    for c in candidates:
        if c.section_key in used:
            continue                       # dedupe: two hits in one section
        text, tokens = sections.get(c.section_key, (c.content, c.token_count))
        if budget + tokens > ASSEMBLY_TOKEN_BUDGET:
            text, tokens = c.content, c.token_count      # drop the expansion only
            if budget + tokens > ASSEMBLY_TOKEN_BUDGET:
                break
        used.add(c.section_key)
        budget += tokens
        kept.append(c)
        parts.append(f"[{len(kept)}] ({c.uri} :: {c.heading_path})\n{text}")

    return kept, "\n\n".join(parts)


# --- the funnel --------------------------------------------------------------

def retrieve(question: str, filters: Filters | None = None,
             parent_question: str | None = None, route: str = "lookup") -> Retrieval:
    filters = filters or Filters()

    # stage 1 — soft pre-filter
    count = count_filtered(filters)
    relaxed = False
    if count < PREFILTER_FLOOR and not filters.strict and filters.as_dict():
        relaxed = True
        filters = Filters()                # drop it entirely and try again
        count = count_filtered(filters)

    # stage 2 — hybrid RRF
    qvec = mistral.embed([question])[0]
    fused = hybrid_search(question, qvec, filters, limit=FUSED_K)

    # stage 3 — rerank
    reranked = rerank(question, fused, RERANK_KEEP)

    # stage 4 — assemble
    assembled, context = assemble(reranked)

    r = Retrieval(question=question, filters=filters.as_dict(), filter_relaxed=relaxed,
                  prefilter_count=count, fused=fused, reranked=reranked,
                  assembled=assembled, context=context)
    _trace(parent_question or question, r, route)
    return r


def _trace(parent: str, r: Retrieval, route: str) -> None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO retrieval_traces (question, sub_question, route, filters,
                filter_relaxed, prefilter_count, fused_ids, reranked_ids, assembled_ids)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (parent, r.question, route, json.dumps(r.filters), r.filter_relaxed,
              r.prefilter_count, [c.chunk_id for c in r.fused],
              [c.chunk_id for c in r.reranked], [c.chunk_id for c in r.assembled]))
        conn.commit()


if __name__ == "__main__":
    r = retrieve("what is the refund window for annual plans")
    print(f"prefilter={r.prefilter_count} fused={len(r.fused)} "
          f"reranked={len(r.reranked)} assembled={len(r.assembled)} "
          f"relaxed={r.filter_relaxed}")
    for i, c in r.citation_map.items():
        print(f"  [{i}] {c.uri} :: {c.heading_path}")

    print("\n--- deliberate over-filter (doc_type that matches nothing) ---")
    r2 = retrieve("refund window", Filters(doc_type="nonexistent"))
    print(f"relaxed={r2.filter_relaxed} assembled={len(r2.assembled)} "
          f"(must be > 0 — relaxation, not zero results)")
