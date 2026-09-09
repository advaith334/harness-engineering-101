"""Generator-critic — split author and editor into two prompts, and loop.

Asking one call to "write it well" underperforms asking one call to write and
another to tear it apart against a rubric. Critique is an easier task than
generation, so the critic is more reliable than the generator's own self-assessment.

The loop exits on a score threshold, not on a fixed count — otherwise you burn
calls polishing something that was already fine.
"""

import json
import os

from mistralai.client import Mistral

client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
MODEL = "mistral-medium-latest"

TASK = ("Write a 3-sentence outreach email to a VP of Engineering at a 500-person fintech "
        "about our API observability product.")

# The rubric is the whole design. A vague critic writes vague criticism.
RUBRIC = """
1. Specific to fintech and to a VP of Engineering (not generic B2B filler).
2. Names a concrete problem, not a product category.
3. No superlatives, no "revolutionary", no "I hope this email finds you well".
4. Exactly 3 sentences, ends with one clear ask.
"""


def generate(task: str, feedback: str | None = None, draft: str | None = None) -> str:
    if feedback is None:
        prompt = task
    else:
        prompt = (f"Task: {task}\n\nYour previous draft:\n{draft}\n\n"
                  f"Editor's feedback:\n{feedback}\n\nRewrite it. Fix every point.")
    return client.chat.complete(
        model=MODEL,
        messages=[{"role": "system", "content": "You are a copywriter. Output only the email."},
                  {"role": "user", "content": prompt}],
    ).choices[0].message.content


def critique(draft: str) -> dict:
    """Structured output matters here: we branch on `score`, so it must be a number."""
    raw = client.chat.complete(
        model=MODEL,
        messages=[
            {"role": "system", "content":
                "You are a harsh editor. Score the draft 1-10 against the rubric and list "
                "concrete fixes. Do not rewrite it yourself.\n"
                f"Rubric:{RUBRIC}\n"
                'Reply as JSON: {"score": <int>, "issues": ["...", "..."]}'},
            {"role": "user", "content": draft},
        ],
        response_format={"type": "json_object"},
        temperature=0,
    ).choices[0].message.content
    return json.loads(raw)


def refine(task: str, threshold: int = 8, max_rounds: int = 3) -> str:
    draft = generate(task)
    for round_no in range(1, max_rounds + 1):
        review = critique(draft)
        print(f"\n--- round {round_no} | score {review['score']}/10 ---")
        print(draft)
        for issue in review["issues"]:
            print("  ! " + issue)

        # Exit on quality, not on a fixed count.
        if review["score"] >= threshold:
            print(f"\n(passed at round {round_no})")
            return draft

        draft = generate(task, feedback="\n".join(review["issues"]), draft=draft)
    return draft


if __name__ == "__main__":
    print("\n=== FINAL ===\n" + refine(TASK))
