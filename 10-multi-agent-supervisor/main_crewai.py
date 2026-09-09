"""The same team in CrewAI — the fastest way to write role-based multi-agent code.

Requires: pip install crewai

CrewAI's model is roles + tasks: you describe agents the way you'd describe people, and
a Crew runs the tasks. `Process.hierarchical` gives you a manager that delegates, which
is folder 10's supervisor; `Process.sequential` is folder 18's handoff line.

What it buys: very little code, and it reads like a brief.
What it costs: ~18% more tokens than an equivalent hand-rolled graph in 2026 benchmarks,
weaker observability, and less control over exactly what each agent sees. Good for a demo
or an internal tool; reach for LangGraph or the raw SDK when the loop needs auditing.
"""

import os

from crewai import Agent, Crew, Process, Task
from crewai.tools import tool

os.environ.setdefault("MISTRAL_API_KEY", os.environ["MISTRAL_API_KEY"])
LLM = "mistral/mistral-medium-latest"  # CrewAI routes through LiteLLM: provider/model


@tool("Search product docs")
def search_docs(query: str) -> str:
    """Search product documentation for pricing, limits and features."""
    return "Pro is $49/user/mo; Enterprise from $25k/yr. Free 60 req/min, Pro 600 req/min."


@tool("Query CRM")
def query_crm(company: str) -> str:
    """Contract and account facts for a company."""
    return f"{company}: 340 seats, Pro plan, renewal in 47 days, 2 open P1 tickets."


docs_agent = Agent(
    role="Product Documentation Specialist",
    goal="Answer product questions accurately from the docs",
    backstory="You know the product catalogue cold and never speculate.",
    tools=[search_docs],
    llm=LLM,
)

account_agent = Agent(
    role="Account Researcher",
    goal="Report the contract and relationship facts for an account",
    backstory="You live in the CRM and report only what's in it.",
    tools=[query_crm],
    llm=LLM,
)

# Tasks are the unit of work. `context` expresses dependencies between them.
research = Task(
    description="Find Acme Corp's contract status and renewal timing.",
    expected_output="3 bullets of account facts.",
    agent=account_agent,
)
compare = Task(
    description="Explain what Enterprise adds over Pro for an account like Acme's.",
    expected_output="3 bullets of concrete differences.",
    agent=docs_agent,
    context=[research],  # sees research's output
)

crew = Crew(
    agents=[account_agent, docs_agent],
    tasks=[research, compare],
    process=Process.sequential,  # Process.hierarchical adds a manager that delegates
    verbose=True,
)

if __name__ == "__main__":
    print(crew.kickoff())
