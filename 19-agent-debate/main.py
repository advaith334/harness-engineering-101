"""Multi-agent debate — instances argue across rounds, then a judge decides.

Why it works: a single model asked "is this a good idea?" anchors on its first framing
and rationalizes. Two instances given OPPOSED mandates surface objections neither would
raise alone. It's an ensemble over reasoning, not over sampling.

Two variants live in this file:
  debate()   — adversarial: fixed pro/con roles, then a judge. Best for decisions.
  round_table() — collaborative group chat: distinct personas, shared transcript,
                  speaking in turn. Best for design review and finding blind spots.

Cost warning: this is rounds x agents calls. It buys quality on genuinely contested
questions and wastes money on everything else.
"""

import json
import os

from mistralai.client import Mistral

client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
MODEL = "mistral-medium-latest"


def speak(system: str, transcript: str, instruction: str) -> str:
    return client.chat.complete(
        model=MODEL,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": f"{transcript}\n\n{instruction}"}],
        temperature=0.7,  # some variance, or the agents converge to the same paragraph
    ).choices[0].message.content


# --- variant A: adversarial debate ------------------------------------------

def debate(question: str, rounds: int = 2) -> str:
    pro = ("You argue FOR the proposal. Make the strongest honest case. Attack the opponent's "
           "specific claims. Never concede the overall position. Under 90 words.")
    con = ("You argue AGAINST the proposal. Make the strongest honest case. Attack the opponent's "
           "specific claims. Never concede the overall position. Under 90 words.")

    transcript = f"Proposal: {question}"
    for r in range(1, rounds + 1):
        for name, role in (("PRO", pro), ("CON", con)):
            turn = speak(role, transcript,
                         "Give your argument for this round." if r == 1
                         else "Rebut the latest opposing argument, then add one new point.")
            print(f"\n--- round {r} · {name} ---\n{turn}")
            transcript += f"\n\n[{name} round {r}]\n{turn}"

    # The judge is the point. A debate with no adjudicator is just noise.
    verdict = client.chat.complete(
        model=MODEL,
        messages=[
            {"role": "system", "content":
                "You are an impartial judge. Weigh the arguments actually made — do not add your "
                "own. Name the strongest point on each side, then decide.\n"
                'Reply as JSON: {"decision": "for|against|conditional", '
                '"strongest_for": "...", "strongest_against": "...", "reasoning": "2 sentences"}'},
            {"role": "user", "content": transcript},
        ],
        response_format={"type": "json_object"},
        temperature=0,
    ).choices[0].message.content
    return json.dumps(json.loads(verdict), indent=2)


# --- variant B: collaborative round table -----------------------------------

PERSONAS = {
    "PM": "You are a product manager. You care about user value and shipping date. Be concrete.",
    "Engineer": "You are a staff engineer. You care about failure modes, migration cost and on-call "
                "burden. Name specific risks.",
    "Security": "You are a security engineer. You care about data exposure and abuse paths. "
                "Raise only realistic threats.",
}


def round_table(topic: str, rounds: int = 2) -> str:
    """Everyone sees the shared transcript and speaks in turn — the group chat topology."""
    transcript = f"Topic: {topic}"
    for r in range(1, rounds + 1):
        for name, persona in PERSONAS.items():
            turn = speak(persona, transcript,
                         "Add your perspective in under 70 words. Do not repeat what others said. "
                         "If you disagree with someone, name them and say why.")
            print(f"\n--- round {r} · {name} ---\n{turn}")
            transcript += f"\n\n[{name}]\n{turn}"

    return client.chat.complete(
        model=MODEL,
        messages=[{"role": "system", "content":
                   "Summarize the discussion: points of agreement, unresolved disagreements, and "
                   "the top 3 risks raised. Do not invent anything not said."},
                  {"role": "user", "content": transcript}],
    ).choices[0].message.content


if __name__ == "__main__":
    print("\n=== ADVERSARIAL DEBATE ===")
    print(debate("We should let the support agent issue refunds up to 100 EUR "
                 "with no human approval."))

    print("\n\n=== ROUND TABLE ===")
    print(round_table("Let the support agent issue refunds up to 100 EUR without approval."))
