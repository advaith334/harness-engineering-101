"""The Mistral Agents API — the first-party stack, in one file.

Everything the earlier folders build by hand, Mistral will host for you:

    folder 05/06  RAG            -> the `document_library` tool over an uploaded library
    folder 08     agent loop     -> `conversations.start` runs it server-side
    folder 13     memory         -> `conversations.append` keeps state, no resend
    folder 12     guardrails     -> a `guardrails=[...]` config on the agent
    folder 14     MCP            -> attach an MCP server / hosted connector
    folder 15     code execution -> the `code_interpreter` tool, sandboxed

Tradeoff, stated plainly: you trade control for speed. You can't see the retrieval
scores, can't rerank, can't inspect the loop. For a 40-minute MVP that's usually the
right trade — and it demonstrates fluency with their platform, which is the point.
"""

import json
import os

from mistralai.client import Mistral

client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
MODEL = "mistral-medium-latest"


# --- 1. A local function tool: declared to the agent, executed by you --------
# `function` tools are declared to the agent but executed by YOU: the conversation
# comes back with a `function.call` entry and you append a `function.result`.
# Same contract as folder 08, just spread across two HTTP calls.

INTERNAL_TARGETS = {"2026": "4200000", "2027": "6800000"}

FUNCTION_TOOL = {
    "type": "function",
    "function": {
        "name": "get_internal_target",
        "description": "Our internal revenue target for a year, in EUR.",
        "parameters": {"type": "object",
                       "properties": {"year": {"type": "string"}},
                       "required": ["year"]},
    },
}


def resolve_function_calls(convo):
    """Execute any function calls the agent asked for, and send the results back."""
    pending = [e for e in convo.outputs if e.type == "function.call"]
    if not pending:
        return convo

    results = []
    for entry in pending:
        args = json.loads(entry.arguments or "{}")
        value = INTERNAL_TARGETS.get(args.get("year"), "unknown")
        print(f"  executing locally: {entry.name}({args}) -> {value}")
        results.append({"type": "function.result",
                        "tool_call_id": entry.tool_call_id,
                        "result": value})

    return client.beta.conversations.append(
        conversation_id=convo.conversation_id, inputs=results
    )



# --- 2. An agent with HOSTED tools. Nothing to implement. -------------------

def build_agent() -> str:
    agent = client.beta.agents.create(
        model=MODEL,
        name="research-analyst",
        description="Researches a topic and computes numbers from it.",
        instructions=(
            "You are a research analyst. Search the web for current facts, then use the "
            "code interpreter for any arithmetic. Never do maths in your head. Cite sources."
        ),
        tools=[
            {"type": "web_search"},       # live retrieval, no index to build
            {"type": "code_interpreter"}, # sandboxed Python, no container to run
            FUNCTION_TOOL,                # yours, executed locally
        ],
        completion_args={"temperature": 0.2},
    )
    print("agent:", agent.id)
    return agent.id


if __name__ == "__main__":
    agent_id = build_agent()

    # --- 3. A stateful conversation. This IS folder 13's memory, hosted. -----
    convo = client.beta.conversations.start(
        agent_id=agent_id,
        inputs="What is Mistral AI's latest model release, and what year was the company founded? "
               "Then compute how many years old the company is.",
        store=True,  # persist server-side
    )
    print("\nconversation:", convo.conversation_id)
    for entry in convo.outputs:
        # Entry types tell you what happened: tool.execution, message.output, function.call...
        print(f"  [{entry.type}] {str(entry)[:140]}")

    # --- 4. Follow-up that needs OUR data, so the agent calls our function. --
    convo = client.beta.conversations.append(
        conversation_id=convo.conversation_id,
        inputs="Look up our internal 2027 revenue target and tell me in 3 sentences "
               "whether it looks realistic.",
    )
    convo = resolve_function_calls(convo)
    print("\nfollow-up:")
    for entry in convo.outputs:
        print(f"  [{entry.type}] {str(entry)[:200]}")

    # --- 5. Audit trail, free ----------------------------------------------
    history = client.beta.conversations.get_history(conversation_id=convo.conversation_id)
    print(f"\n{len(history.entries)} entries stored server-side")
