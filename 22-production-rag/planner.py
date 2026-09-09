"""The planner — one typed call that decomposes the question and picks a route.

Everything the planner can choose is a CLOSED SET:
  * `route` is an enum, so it cannot invent a fifth kind of work.
  * filter values come from `filters.allowed_values()`, read out of the corpus at
    runtime and injected into the prompt. The planner picks from a list; it cannot
    hallucinate `service='billing-service'` when the corpus says `billing`.
  * `query_name` for aggregates is an enum over the registry in queries.py.

That is the whole safety design: constrain the choice space rather than validate
free-form output afterwards.

Offline (no API key) it falls back to a single `lookup` sub-question, so the rest
of the pipeline stays exercisable.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

import mistral
from filters import Filters, allowed_values
from queries import QUERY_NAMES

Route = Literal["lookup", "compare", "aggregate", "direct"]

ROUTE_HELP = """\
lookup    — one fact from the documentation. The default.
compare   — needs two or more separate retrievals whose results are contrasted.
aggregate — a counting/listing question about the document collection itself
            ("how many runbooks", "what changed since March"). Uses SQL, not search.
direct    — chit-chat or a question about your own capabilities. No retrieval."""


# Flat and all-required: chat.parse emits a strict schema.
class SubQuestion(BaseModel):
    question: str = Field(description="A self-contained question. No pronouns.")
    route: Route
    doc_type: str = Field(description="A doc_type from the allowed list, or empty string.")
    product: str = Field(description="A product from the allowed list, or empty string.")
    service: str = Field(description="A service from the allowed list, or empty string.")
    query_name: str = Field(description="For route=aggregate only, else empty string.")
    query_param: str = Field(description="Parameter for the named query, else empty string.")


class Plan(BaseModel):
    reasoning: str = Field(description="One sentence on how you split the question.")
    sub_questions: list[SubQuestion]


def _system() -> str:
    allowed = allowed_values()
    return (
        "You plan retrieval over a documentation corpus. Split the user's question "
        "into the FEWEST self-contained sub-questions that answer it — usually one. "
        "Split only when parts need genuinely different sources.\n\n"
        f"Routes:\n{ROUTE_HELP}\n\n"
        "Filters are optional and must come from these exact values, or be an empty "
        f"string:\n"
        f"  doc_type: {allowed['doc_type']}\n"
        f"  product:  {allowed['product']}\n"
        f"  service:  {allowed['service']}\n"
        "Never invent a filter value. When unsure, leave it empty — an empty filter "
        "searches everything, which is safe; a wrong one finds nothing.\n\n"
        f"For route=aggregate, query_name must be one of: {list(QUERY_NAMES)}"
    )


def _fallback(question: str) -> Plan:
    return Plan(reasoning="offline fallback: single lookup",
                sub_questions=[SubQuestion(question=question, route="lookup",
                                           doc_type="", product="", service="",
                                           query_name="", query_param="")])


def plan(question: str) -> Plan:
    parsed = mistral.parse(Plan, _system(), question)
    if not parsed or not parsed.sub_questions:
        return _fallback(question)

    # Belt and braces: the enum constrains the model, this constrains a bad enum.
    allowed = allowed_values()
    for sq in parsed.sub_questions:
        for col in ("doc_type", "product", "service"):
            if getattr(sq, col) and getattr(sq, col) not in allowed[col]:
                setattr(sq, col, "")
        if sq.route == "aggregate" and sq.query_name not in QUERY_NAMES:
            sq.route = "lookup"
    return parsed


def filters_for(sq: SubQuestion) -> Filters:
    return Filters(doc_type=sq.doc_type or None,
                   product=sq.product or None,
                   service=sq.service or None)


if __name__ == "__main__":
    for q in ["what is the refund window for annual plans?",
              "how do rate limits and webhook retries differ between Pro and Enterprise?",
              "how many runbooks do we have?"]:
        p = plan(q)
        print(f"\nQ: {q}\n  {p.reasoning}")
        for sq in p.sub_questions:
            print(f"  [{sq.route}] {sq.question}  filters={filters_for(sq).as_dict()}")
