"""Server-side memory — let Mistral hold the conversation state.

`conversations.start()` returns a conversation_id. `conversations.append()` continues it.
The history lives on Mistral's side, so you send one new message per turn instead of
resending the whole transcript. That means:

  + no buffer management, no compression code, no resend cost
  + the conversation survives your process restarting
  - the state isn't yours to inspect, edit, or migrate
  - you still need your own vector store for cross-conversation facts about a user

Rule: use server-side for conversation continuity, your own store for user facts.
"""

import os

from mistralai.client import Mistral

client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
MODEL = "mistral-medium-latest"

if __name__ == "__main__":
    agent = client.beta.agents.create(
        model=MODEL,
        name="memory-demo",
        instructions="You are a concise assistant. Remember what the user tells you.",
    )

    # Turn 1 — start the conversation. store=True is what makes it persistent.
    convo = client.beta.conversations.start(
        agent_id=agent.id,
        inputs="I'm Priya, a backend engineer at Northwind. I only want Python examples.",
        store=True,
    )
    print("conversation_id:", convo.conversation_id)
    print("BOT:", convo.outputs[-1])

    # Turn 2 — append. Note we do NOT resend turn 1.
    convo = client.beta.conversations.append(
        conversation_id=convo.conversation_id,
        inputs="What's a good way to batch API requests?",
    )
    print("\nBOT:", convo.outputs[-1])

    # Turn 3 — the memory test.
    convo = client.beta.conversations.append(
        conversation_id=convo.conversation_id,
        inputs="What's my name and which language should you use?",
    )
    print("\nBOT:", convo.outputs[-1])

    # The full history is retrievable server-side — useful for audit and debugging.
    history = client.beta.conversations.get_history(conversation_id=convo.conversation_id)
    print(f"\n{len(history.entries)} entries stored server-side")
