"""Filters — and the closed enum that stops the planner inventing values.

The most dangerous thing in this system is a planner emitting a filter value that
looks plausible and matches nothing: `service='billing-service'` when the corpus
says `billing`. You get zero rows, no error, and a confident wrong answer.

Two defences, both here:
  1. The allowed values are read from the database at runtime and handed to the
     planner. It picks from a list; it cannot invent.
  2. Filters are SOFT. If filtering leaves too few candidates, retrieval re-runs
     unfiltered and flags the trace. A hard filter must be asked for explicitly.

Filtering is only ever on enumerable columns — never a free-text LIKE.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from db import connect

FILTERABLE = ("doc_type", "product", "service")


@dataclass
class Filters:
    doc_type: str | None = None
    product: str | None = None
    service: str | None = None
    since: str | None = None      # ISO date, matched against effective_date
    strict: bool = False          # if False (default) filters may be relaxed

    def as_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v not in (None, False)}

    def where(self) -> tuple[str, dict]:
        """Build a parameterized WHERE fragment. Never string-interpolates values."""
        clauses, params = [], {}
        for col in FILTERABLE:
            if (val := getattr(self, col)) is not None:
                clauses.append(f"d.{col} = %({col})s")
                params[col] = val
        if self.since:
            clauses.append("d.effective_date >= %(since)s")
            params["since"] = self.since
        return (" AND ".join(clauses) if clauses else "TRUE"), params


def allowed_values() -> dict[str, list[str]]:
    """The closed enum, read from the corpus itself."""
    out: dict[str, list[str]] = {}
    with connect() as conn, conn.cursor() as cur:
        for col in FILTERABLE:
            cur.execute(
                f"SELECT DISTINCT {col} FROM documents "
                f"WHERE {col} IS NOT NULL ORDER BY 1")
            out[col] = [r[0] for r in cur.fetchall()]
    return out


if __name__ == "__main__":
    for col, vals in allowed_values().items():
        print(f"{col}: {vals}")
