"""Evaluation — deterministic checks first, the judge second.

The ordering is the point. Two of the three most useful signals here cost nothing
and cannot themselves be wrong:

  citation validity — every [n] the model emitted is in range and maps to a chunk
                      that was actually retrieved. Catches fabricated citations
                      outright, with no model call.
  hit rate / MRR    — did the expected document appear in the assembled context,
                      and how high? This separates a RETRIEVAL failure from a
                      GENERATION failure, which is the distinction that tells you
                      what to go and fix.

Only then does an LLM judge score groundedness and completeness. Judges are useful
for comparing v1 against v2; they are not a source of absolute truth, and they
cannot tell you which funnel stage lost a chunk. `retrieval_traces` can.
"""

from __future__ import annotations

import sys
from datetime import datetime

import mistral
from db import connect
from eval_questions import GOLDEN
from reason import Answer, answer

JUDGE_SYSTEM = (
    "Score the answer against the context it was given.\n"
    "  groundedness 1-5: is every claim supported by the context?\n"
    "  completeness 1-5: does it actually answer the question asked?\n"
    "An honest 'not in the documentation' scores 5 for groundedness when the "
    "context truly lacks the answer.\n"
    'Reply as JSON: {"groundedness": n, "completeness": n, "note": "one line"}'
)


def deterministic_checks(a: Answer, expected_docs: list[str]) -> dict:
    """No model calls. Nothing here can hallucinate."""
    n_sources = len(a.sources)
    citations_valid = all(1 <= c <= n_sources for c in a.cited)

    # rank of the first expected document within the assembled context
    rr, hit = 0.0, False
    if expected_docs:
        for rank, src in enumerate(a.sources, start=1):
            if any(src.startswith(d) for d in expected_docs):
                hit, rr = True, 1.0 / rank
                break

    refused = any(p in a.text.lower() for p in
                  ("not in the documentation", "does not contain", "no relevant",
                   "isn't in the", "not available in", "cannot find", "offline"))

    return dict(citations_valid=citations_valid, hit=hit, reciprocal_rank=rr,
                refused=refused, n_cited=len(a.cited), n_sources=n_sources)


def judge(a: Answer) -> dict:
    if mistral.OFFLINE:
        return {}
    context = "\n\n".join(s.retrieval.context for s in a.sub_answers if s.retrieval)
    import json
    raw = mistral.chat(JUDGE_SYSTEM,
                       f"Context:\n{context[:8000]}\n\nQuestion: {a.question}\n\n"
                       f"Answer: {a.text}", small=True)
    try:
        return json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
    except (ValueError, KeyError):
        return {}


def main() -> None:
    label = datetime.now().strftime("run-%Y%m%d-%H%M%S")
    rows, hits, rrs, valid, refusals_ok = [], 0, [], 0, 0
    n_refusal_cases = sum(1 for g in GOLDEN if g.get("expect_refusal"))

    for g in GOLDEN:
        a = answer(g["q"])
        d = deterministic_checks(a, g["docs"])
        j = judge(a)

        if g["docs"]:
            hits += d["hit"]
            rrs.append(d["reciprocal_rank"])
        valid += d["citations_valid"]
        if g.get("expect_refusal"):
            refusals_ok += d["refused"]

        flag = "ok " if d["citations_valid"] else "CIT"
        if g["docs"] and not d["hit"]:
            flag = "MISS"
        print(f"  {flag:>4}  rr={d['reciprocal_rank']:.2f}  {g['q'][:62]}")

        rows.append((label, g["q"], g["docs"], a.text[:4000], d["citations_valid"],
                     d["hit"], d["reciprocal_rank"], j.get("groundedness"),
                     j.get("completeness"), j.get("note")))

    with connect() as conn, conn.cursor() as cur:
        cur.executemany("""
            INSERT INTO eval_runs (run_label, question, expected_docs, answer,
                citations_valid, hit, reciprocal_rank, groundedness, completeness,
                judge_note)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", rows)
        conn.commit()

    n_doc_cases = sum(1 for g in GOLDEN if g["docs"])
    print(f"\n=== {label} ===")
    print(f"  retrieval hit rate : {hits}/{n_doc_cases}"
          f"  ({hits / n_doc_cases:.0%})")
    print(f"  MRR                : {sum(rrs) / len(rrs):.3f}")
    print(f"  citations valid    : {valid}/{len(GOLDEN)}")
    print(f"  refusals correct   : {refusals_ok}/{n_refusal_cases}")
    if mistral.OFFLINE:
        print("\n  [OFFLINE] Judge skipped and generation is a placeholder. Retrieval"
              "\n  numbers above are real but dense vectors are pseudo-random, so hit"
              "\n  rate reflects the LEXICAL arms only — treat it as a floor.")


if __name__ == "__main__":
    main()
