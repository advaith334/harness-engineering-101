"""The reasoning engine — route, fan out, synthesize with enforced citations.

The multi-agent part that earns its keep is exactly this:
    planner -> N typed retrievals in parallel -> one synthesizer

These workers are NOT personas. They are the same `retrieve()` function called
concurrently with different sub-questions and filters — folder 10's supervisor
shape pointed at retrieval. Giving each one a backstory would add tokens and
nothing else. (If a sub-question genuinely needed its own tool loop, that would be
folder 07 and a different design.)

Citations are integers, mapped back to chunk ids in code. Putting chunk UUIDs in
the prompt guarantees typos, and then a deterministic citation check fails on
answers that were perfectly well grounded.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import mistral
from planner import Plan, SubQuestion, filters_for, plan
from queries import format_rows, run_named_query
from retrieve import Retrieval, retrieve


@dataclass
class SubAnswer:
    sub_question: str
    route: str
    text: str
    retrieval: Retrieval | None = None
    rows: str = ""


@dataclass
class Answer:
    question: str
    plan: Plan
    sub_answers: list[SubAnswer] = field(default_factory=list)
    text: str = ""
    cited: list[int] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)


ANSWER_SYSTEM = (
    "Answer using ONLY the numbered context. Cite every claim with the bracketed "
    "number of the passage it came from, like [2]. If the context does not contain "
    "the answer, say so plainly and cite nothing. Never invent a citation number "
    "that is not in the context. Be concise."
)


def _run_sub(sq: SubQuestion, parent: str) -> SubAnswer:
    """One worker. Route decides whether this is search or SQL."""
    if sq.route == "direct":
        return SubAnswer(sq.question, sq.route,
                         mistral.chat("Answer briefly. You are a documentation "
                                      "assistant.", sq.question))

    if sq.route == "aggregate":
        try:
            cols, rows = run_named_query(sq.query_name, {
                "doc_type": sq.doc_type, "since": sq.query_param,
                "entity": f"%{sq.query_param}%"})
            table = format_rows(cols, rows)
            # Provenance matters: these numbers describe the corpus and its
            # extracted metadata, not the world.
            return SubAnswer(sq.question, sq.route,
                             f"From the document index ({sq.query_name}):\n{table}",
                             rows=table)
        except ValueError as e:
            sq.route = "lookup"            # bad params -> degrade to search
            return _run_sub(sq, parent)

    r = retrieve(sq.question, filters_for(sq), parent_question=parent, route=sq.route)
    if not r.assembled:
        return SubAnswer(sq.question, sq.route, "No relevant documentation found.", r)

    text = mistral.chat(ANSWER_SYSTEM, f"Context:\n{r.context}\n\nQuestion: {sq.question}")
    return SubAnswer(sq.question, sq.route, text, r)


def answer(question: str) -> Answer:
    p = plan(question)
    out = Answer(question=question, plan=p)

    # Parallel: sub-questions are independent by construction. If one depended on
    # another's result, the right shape would be folder 18's sequential handoff.
    with ThreadPoolExecutor(max_workers=min(4, len(p.sub_questions))) as pool:
        out.sub_answers = list(pool.map(lambda sq: _run_sub(sq, question), p.sub_questions))

    # Single sub-question: its answer IS the answer. Don't pay for a synthesis call
    # that can only lose information.
    if len(out.sub_answers) == 1:
        out.text = out.sub_answers[0].text
    else:
        parts = "\n\n".join(f"### {s.sub_question}\n{s.text}" for s in out.sub_answers)
        out.text = mistral.chat(
            "Combine these findings into one answer. Preserve the bracketed citation "
            "numbers exactly as they appear. Note any contradiction between findings "
            "rather than smoothing it over.",
            f"Question: {question}\n\n{parts}")

    out.cited = sorted({int(n) for n in re.findall(r"\[(\d+)\]", out.text)})
    for s in out.sub_answers:
        if s.retrieval:
            out.sources += [f"{c.uri} :: {c.heading_path}"
                            for c in s.retrieval.assembled]
    out.sources = list(dict.fromkeys(out.sources))
    return out
