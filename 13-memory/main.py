"""Memory — the three layers, in one file, so you can see how they differ.

  1. BUFFER    recent turns, verbatim. Perfect fidelity, hard ceiling.
  2. SUMMARY   old turns rolled up into a running paragraph. Capacity for fidelity.
  3. LONG-TERM durable facts in a vector store, retrieved on demand. This is RAG
               over the agent's own history — which is why 05 and 13 are the same
               machinery pointed at different data.

Real assistants use all three at once, which is what `build_context()` does here.
Memory is orthogonal to every other topology: you bolt it onto any of them.
"""

import math
import os

from mistralai.client import Mistral

client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
MODEL = "mistral-medium-latest"
EMBED_MODEL = "mistral-embed"

BUFFER_TURNS = 4  # keep this many exchanges verbatim; older ones get summarized


class Memory:
    def __init__(self) -> None:
        self.buffer: list[dict] = []                        # layer 1
        self.summary: str = ""                              # layer 2
        self.facts: list[tuple[str, list[float]]] = []      # layer 3

    # --- layer 3 helpers ---
    def remember(self, fact: str) -> None:
        """Durable facts. In production: a real vector DB, keyed by user id."""
        vec = client.embeddings.create(model=EMBED_MODEL, inputs=[fact]).data[0].embedding
        self.facts.append((fact, vec))
        print(f"    [remembered] {fact}")

    def recall(self, query: str, k: int = 2) -> list[str]:
        if not self.facts:
            return []
        qvec = client.embeddings.create(model=EMBED_MODEL, inputs=[query]).data[0].embedding

        def cos(a, b):
            return sum(x * y for x, y in zip(a, b)) / (
                math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))

        return [f for _, f in sorted(((cos(qvec, v), f) for f, v in self.facts), reverse=True)[:k]]

    # --- layer 2: compression ---
    def compress(self) -> None:
        """Called when the buffer overflows. Fold the oldest turns into the summary."""
        overflow, self.buffer = self.buffer[:-BUFFER_TURNS * 2], self.buffer[-BUFFER_TURNS * 2:]
        if not overflow:
            return
        transcript = "\n".join(f"{m['role']}: {m['content']}" for m in overflow)
        self.summary = client.chat.complete(
            model=MODEL,
            messages=[{"role": "user", "content":
                       f"Existing summary:\n{self.summary or '(none)'}\n\n"
                       f"New turns:\n{transcript}\n\n"
                       "Update the summary. Keep names, numbers, decisions and preferences. "
                       "Drop pleasantries. Under 100 words."}],
            temperature=0,
        ).choices[0].message.content
        print(f"    [compressed {len(overflow)} messages]")

    # --- assemble the prompt ---
    def build_context(self, user_msg: str) -> list[dict]:
        system = "You are a helpful assistant with memory of this user."
        if self.summary:
            system += f"\n\nEarlier in this conversation:\n{self.summary}"
        recalled = self.recall(user_msg)
        if recalled:
            system += "\n\nThings you know about this user:\n" + "\n".join(f"- {f}" for f in recalled)
            print(f"    [recalled] {recalled}")
        return [{"role": "system", "content": system}, *self.buffer,
                {"role": "user", "content": user_msg}]

    def turn(self, user_msg: str) -> str:
        messages = self.build_context(user_msg)
        reply = client.chat.complete(model=MODEL, messages=messages).choices[0].message.content
        self.buffer += [{"role": "user", "content": user_msg},
                        {"role": "assistant", "content": reply}]
        if len(self.buffer) > BUFFER_TURNS * 2:
            self.compress()
        return reply


if __name__ == "__main__":
    mem = Memory()

    # Long-term facts usually get written by a separate extraction pass, not inline.
    mem.remember("User is a backend engineer at a fintech called Northwind.")
    mem.remember("User prefers Python and dislikes verbose explanations.")
    mem.remember("User is on the Pro plan and has hit rate limits twice.")

    for msg in [
        "Hey, what's the rate limit on my plan?",
        "How do I batch requests to stay under it?",
        "Can you show that in a snippet?",
        "Thanks. Unrelated: what's SSO cost?",
        "And remind me what plan I'm on and what language you should use?",  # tests recall
    ]:
        print(f"\nUSER: {msg}")
        print("BOT:", mem.turn(msg))

    print("\n--- memory state ---")
    print("summary:", mem.summary or "(none yet)")
    print("buffer:", len(mem.buffer), "messages")
    print("facts:", len(mem.facts))
