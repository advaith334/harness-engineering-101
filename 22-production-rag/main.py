"""python main.py "your question" — the whole system, with its trace printed.

Printing the intermediate stages is not decoration. When an answer is wrong the
first question is always "which stage lost it?", and a system that only prints its
final answer cannot tell you.
"""

import sys

import mistral
from reason import answer


def main(question: str) -> None:
    a = answer(question)

    print(f"\nQ: {question}")
    print(f"\nPLAN ({len(a.plan.sub_questions)} sub-question(s)): {a.plan.reasoning}")
    for s in a.sub_answers:
        print(f"  [{s.route}] {s.sub_question}")
        if s.retrieval:
            r = s.retrieval
            print(f"      funnel: prefilter {r.prefilter_count} -> fused {len(r.fused)}"
                  f" -> reranked {len(r.reranked)} -> assembled {len(r.assembled)}"
                  f"{'  (FILTER RELAXED)' if r.filter_relaxed else ''}")

    print(f"\nANSWER:\n{a.text}")

    if a.sources:
        print("\nSOURCES:")
        for i, s in enumerate(a.sources, 1):
            marker = "*" if i in a.cited else " "
            print(f"  {marker}[{i}] {s}")
        print("  (* = actually cited)")

    if mistral.OFFLINE:
        print("\n[OFFLINE: no MISTRAL_API_KEY. Retrieval ran for real against Neon; "
              "dense vectors and all generated text are placeholders.]")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    main(" ".join(sys.argv[1:]))
