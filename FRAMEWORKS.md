# Agent Frameworks — the 2026 landscape

Researched September 2026. The short version: **for a 40-minute build, write the loop yourself.**
Every folder in this repo has a raw-SDK `main.py` for that reason. Frameworks are worth reaching for
when they solve a problem you actually have — durability, checkpointing, approvals — and are a
liability when they're just an extra thing to debug in front of an interviewer.

Being able to *name* the landscape and say why you didn't use it is worth more than using it.

---

## The ones that matter

### Mistral Agents API — first-party
`client.beta.agents` + `client.beta.conversations`. See [17](./17-mistral-agents-api/).

Stateful conversations (server-side memory), hosted tools (`web_search`, `code_interpreter`,
`image_generation`, `document_library` for managed RAG), native MCP and OAuth connectors,
`handoffs=[...]` for multi-agent, `guardrails=[...]`, and a built-in local runner
(`RunContext` + `conversations.run_async`) with tool-confirmation HITL.

- **Wins when:** you're on Mistral, you want memory/RAG/tools without building them, and you want
  the platform fluency to show. **In a Mistral interview this is the highest-signal choice.**
- **Costs you:** visibility (no retrieval scores, no rerank hook) and portability.

```python
agent = client.beta.agents.create(model="mistral-medium-latest", name="analyst",
                                  tools=[{"type": "web_search"}, {"type": "code_interpreter"}])
convo = client.beta.conversations.start(agent_id=agent.id, inputs="...", store=True)
convo = client.beta.conversations.append(conversation_id=convo.conversation_id, inputs="...")
```

### LangGraph 1.0 / LangChain `create_agent` — the default orchestration runtime
Hit 1.0 in Oct 2025; overtook CrewAI in stars during 2026 on enterprise adoption. A low-level
graph runtime for stateful agents.

- **Wins when:** you need **durable execution** — checkpointers so a crashed run resumes,
  `interrupt()` for human approval mid-graph, streaming of every node, explicit branching and retries.
  If the ask mentions resumability or approvals, reach for this.
- **Costs you:** a state schema to get right, a real dependency tree, and an abstraction between you
  and the message list when something breaks.
- **⚠️ `create_react_agent` is deprecated** in favour of `create_agent` (in the `langchain` package,
  with a middleware system). Using the old name signals stale knowledge.

```python
from langchain.agents import create_agent
from langgraph.checkpoint.memory import InMemorySaver
agent = create_agent(llm, tools=[...], prompt="...", checkpointer=InMemorySaver())
agent.invoke({"messages": [...]}, {"configurable": {"thread_id": "abc"}})
```
Example: [10/main_langgraph.py](./10-multi-agent-supervisor/main_langgraph.py).

### Pydantic AI — typed agents
Type-safe agents with first-class structured output. 2026 benchmarks put it ahead of LangChain on
P95 latency, error rate under load, and tokens per task.

- **Wins when:** the agent lives inside an application and you want typed results, dependency
  injection, and tight control. Best structured-output ergonomics of any framework.
- **Costs you:** less machinery for long-running stateful graphs than LangGraph.
- **Note for this repo:** on Mistral, `client.chat.parse(response_format=MyModel)` already gives you
  typed output in one call with no extra dependency — see
  [01/main_typed.py](./01-structured-output/main_typed.py). Reach for Pydantic AI when you want the
  whole agent typed, not just the output.

### CrewAI — role-based multi-agent, fastest to write
Agents described as roles with goals and backstories; tasks with dependencies; `Process.sequential`
or `Process.hierarchical`.

- **Wins when:** you want a multi-agent demo in 30 lines that reads like a brief.
- **Costs you:** ~18% more tokens than an equivalent hand-rolled three-agent workflow (2026
  benchmarks), weaker observability and error recovery, less control over each agent's context.

Example: [10/main_crewai.py](./10-multi-agent-supervisor/main_crewai.py).

---

## Named, but off-path for a Mistral round

| Framework | One line | Would win if |
|---|---|---|
| **Microsoft Agent Framework (MAF 1.0)** | AutoGen + Semantic Kernel merged into one production runtime; MS now points new users here rather than AutoGen | You're in the .NET / Azure enterprise stack |
| **OpenAI Agents SDK** | Shipped Mar 2026. Lightweight first-party agents, tools, handoffs, guardrails, tracing | You're building on OpenAI models |
| **Amazon Bedrock AgentCore** | The only fully managed production agent runtime — autoscaling, IAM-native, built-in memory | You're all-in on AWS and don't want to run infra |
| **LlamaIndex Workflows** | Event-driven workflow layer on the strongest RAG-ingestion ecosystem | Document ingestion is the hard part of your problem |
| **Haystack** | Grew from a RAG framework into agent orchestration; pipeline-shaped, production-focused | You already run Haystack pipelines |
| **Strands** | AWS's model-driven agent SDK | Lightweight agents inside AWS |
| **DSPy** | Optimizes prompts programmatically against a metric instead of hand-tuning | You have an eval set and prompt quality is the bottleneck |

Also worth knowing as *protocols* rather than frameworks: **MCP** for tools
([14](./14-mcp-client/)) and **A2A** for agents delegating to each other across vendors.

---

## The decision rule

```
Is the task one LLM call, or a fixed sequence of them?
    -> No framework. Write the calls. (folders 01-06)

Is it an agent loop, in an interview, under time pressure?
    -> Raw SDK loop (folder 08) or Mistral's RunContext runner.
       ~20 lines, zero install risk, and you can debug it live.

Does the ask involve durability, resumability, or mid-run human approval?
    -> LangGraph. That checkpointer + interrupt() combination is the real reason it exists.

Is the ask "assistant that knows our docs and remembers me", fast?
    -> Mistral Agents API. document_library + conversations, and you're done. (folder 17)

Is it a multi-agent demo where speed of writing matters more than control?
    -> CrewAI.

Is the agent a typed component inside a larger Python application?
    -> Pydantic AI.
```

## What to say out loud in the presentation

> "I default to writing the loop against the raw SDK, because the loop is 20 lines and I want to be
> able to see and debug every message. I reach for a framework when it gives me something I'd
> otherwise have to build — LangGraph's checkpointer and `interrupt()` for durable, approval-gated
> runs, or Mistral's Agents API when hosted RAG and server-side memory get me there faster. What I
> don't do is adopt a framework for the agent loop itself; that's the part I most need to understand."

That answer demonstrates you know all three options and have a reason for the one you picked, which
is the actual thing being tested.
