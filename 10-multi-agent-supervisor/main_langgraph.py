"""The same supervisor in LangGraph 1.0 — for when you need durable state.

Requires: pip install langgraph langchain langchain-mistralai

What the framework buys you over main.py:
  - a checkpointer, so a crashed run resumes instead of restarting
  - interrupt() for human approval mid-graph (see 16-human-in-the-loop)
  - streaming of every intermediate node, free
  - a real graph you can visualise

What it costs you: a state schema to get right, a dependency tree, and an abstraction
between you and the message list when something goes wrong. For a quick build,
main.py is usually the better bet. Reach for this when the requirement mentions
durability, resumability, or approvals.

NOTE: `create_react_agent` is deprecated as of LangChain 1.0 — use `create_agent`.
The keyword is `system_prompt=`, not `prompt=`; the latter raises TypeError.
Verified against langchain 1.4.0 / langgraph 1.2.11 / langchain-mistralai 1.1.6.
"""

import os

from langchain.agents import create_agent
from langchain_core.tools import tool
from langchain_mistralai import ChatMistralAI
from langgraph.checkpoint.memory import InMemorySaver

llm = ChatMistralAI(model="mistral-medium-latest", api_key=os.environ["MISTRAL_API_KEY"])


@tool
def search_docs(query: str) -> str:
    """Search product documentation."""
    return "Pro is $49/user/mo; Enterprise from $25k/yr. Free tier 60 req/min."


@tool
def query_crm(company: str) -> str:
    """Contract and account facts for a company."""
    return f"{company}: 340 seats, Pro plan, renewal in 47 days, 2 open P1 tickets."


# Each worker is an agent with its own narrow tool set — same principle as main.py.
docs_agent = create_agent(llm, tools=[search_docs], system_prompt="You answer from product docs.")
account_agent = create_agent(llm, tools=[query_crm], system_prompt="You report account facts.")


# The supervisor exposes each worker as a tool. Calling a worker == delegating.
@tool
def ask_docs(question: str) -> str:
    """Ask the documentation specialist a question."""
    out = docs_agent.invoke({"messages": [{"role": "user", "content": question}]})
    return out["messages"][-1].content


@tool
def ask_account(question: str) -> str:
    """Ask the account specialist a question."""
    out = account_agent.invoke({"messages": [{"role": "user", "content": question}]})
    return out["messages"][-1].content


supervisor = create_agent(
    llm,
    tools=[ask_docs, ask_account],
    system_prompt="You are a supervisor. Delegate to specialists, then synthesize their answers.",
    checkpointer=InMemorySaver(),  # swap for SqliteSaver/PostgresSaver to survive restarts
)

if __name__ == "__main__":
    config = {"configurable": {"thread_id": "acme-renewal"}}  # the durability key
    result = supervisor.invoke(
        {"messages": [{"role": "user", "content":
                       "Acme Corp renews in 47 days. Should we push them to Enterprise?"}]},
        config,
    )
    print(result["messages"][-1].content)
