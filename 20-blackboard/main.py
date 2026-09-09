"""Blackboard — agents read and write a shared workspace instead of messaging each other.

The key inversion: in folders 10 and 18 the topology is who-talks-to-whom, and adding an
agent means rewiring. Here the topology is the DATA. Agents are decoupled: each looks at
the board, decides if it has something to contribute, contributes, and stops. Add a new
agent and nothing else changes.

This is how long-horizon agent systems actually stay manageable, and it's the same idea
as an agent writing to a plan file or a state object — "working memory" made shared.

A controller loop decides who runs next. Here it's a simple rule (whoever is unblocked),
which is deliberately boring: the intelligence is in the agents, not the scheduler.
"""

import json
import os

from mistralai.client import Mistral

client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
MODEL = "mistral-medium-latest"


# --- the blackboard ---------------------------------------------------------

class Blackboard:
    """Shared state. In production: a row in Postgres, a JSON file, or a Redis hash.
    The important property is that it is durable and inspectable — you can crash,
    restart, and pick up exactly where you were."""

    def __init__(self, goal: str) -> None:
        self.goal = goal
        self.entries: dict[str, str] = {}

    def has(self, *keys: str) -> bool:
        return all(k in self.entries for k in keys)

    def write(self, key: str, value: str, author: str) -> None:
        self.entries[key] = value
        print(f"  [{author} wrote {key}] {value[:90]}")

    def render(self) -> str:
        if not self.entries:
            return "(empty)"
        return "\n".join(f"### {k}\n{v}" for k, v in self.entries.items())


# --- agents: each declares what it needs and what it produces ---------------
# `needs` is the only coordination mechanism. No agent knows another exists.

def call(system: str, user: str) -> str:
    return client.chat.complete(
        model=MODEL,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.3,
    ).choices[0].message.content


AGENTS = [
    {
        "name": "researcher",
        "needs": [],
        "produces": "findings",
        "system": "You are a market researcher. List 4 concrete facts relevant to the goal. "
                  "Invent plausible specifics where you must, and label them (est.).",
    },
    {
        "name": "analyst",
        "needs": ["findings"],
        "produces": "analysis",
        "system": "You are an analyst. Using only the findings on the board, identify the two "
                  "biggest risks and the one biggest opportunity. Be blunt.",
    },
    {
        "name": "skeptic",
        "needs": ["analysis"],
        "produces": "critique",
        "system": "You are a skeptic. Attack the analysis on the board. Name what it assumes "
                  "without evidence. Do not propose solutions.",
    },
    {
        "name": "writer",
        "needs": ["findings", "analysis", "critique"],
        "produces": "recommendation",
        "system": "You are a strategist. Write a 4-bullet recommendation that survives the "
                  "critique on the board. Reference the risks by name.",
    },
]


def run(goal: str, max_cycles: int = 6) -> Blackboard:
    board = Blackboard(goal)

    for cycle in range(max_cycles):
        # The controller: pick agents whose inputs exist and whose output doesn't yet.
        ready = [a for a in AGENTS
                 if a["produces"] not in board.entries and board.has(*a["needs"])]
        if not ready:
            break

        print(f"\ncycle {cycle}: ready = {[a['name'] for a in ready]}")
        for agent in ready:
            output = call(agent["system"],
                          f"Goal: {board.goal}\n\nBlackboard:\n{board.render()}")
            board.write(agent["produces"], output, agent["name"])

    return board


if __name__ == "__main__":
    board = run("Should we launch a self-serve tier at 19 EUR/month alongside our 49 EUR Pro plan?")
    print("\n=== FINAL BOARD ===")
    print(board.render())
    print("\nkeys:", list(board.entries))
    # Because the board is plain data, this whole run is resumable: persist
    # `board.entries` and the controller picks up exactly where it stopped.
