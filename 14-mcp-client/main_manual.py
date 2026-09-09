"""The same thing without the SDK's help, so you can see what MCP actually is.

An MCP server exposes `tools/list` and `tools/call`. That's the entire protocol as far
as tool use is concerned. A "client" is 30 lines: list the tools, rename the fields into
your provider's tool-schema shape, and route calls back over the transport.

Understanding this is the difference between "we use MCP" and being able to debug it.

Requires: pip install mcp
"""

import asyncio
import json
import os
import tempfile
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mistralai.client import Mistral

client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
MODEL = "mistral-medium-latest"


def mcp_tool_to_mistral(tool) -> dict:
    """The whole adapter. MCP's `inputSchema` IS a JSON schema, so this is a rename."""
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description or "",
            "parameters": tool.inputSchema,
        },
    }


async def main() -> None:
    sandbox = Path(tempfile.mkdtemp(prefix="mcp-demo-"))
    (sandbox / "notes.md").write_text("# Q3\n- launch slipped to Oct 6\n- funnel down to 2.1%\n")

    params = StdioServerParameters(
        command="npx",
        args=["-y", "@modelcontextprotocol/server-filesystem", str(sandbox)],
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # 1. DISCOVER
            listed = await session.list_tools()
            allowed = {"read_text_file", "list_directory"}
            tools = [mcp_tool_to_mistral(t) for t in listed.tools if t.name in allowed]
            print("discovered:", [t["function"]["name"] for t in tools])

            # 2. The ordinary agent loop from 08-react-tools. MCP changed nothing about it.
            messages = [
                {"role": "system", "content": "Use the filesystem tools to answer. Be brief."},
                {"role": "user", "content": "What's blocking Q3? Check the files."},
            ]

            for step in range(6):
                msg = client.chat.complete(
                    model=MODEL, messages=messages, tools=tools, tool_choice="auto"
                ).choices[0].message
                messages.append(msg)

                if not msg.tool_calls:
                    print("\nANSWER:", msg.content)
                    return

                for call in msg.tool_calls:
                    args = json.loads(call.function.arguments or "{}")
                    print(f"  [{step}] {call.function.name}({args})")

                    # 3. CALL — route it back over the MCP transport
                    out = await session.call_tool(call.function.name, args)
                    text = "\n".join(getattr(c, "text", "") for c in out.content)

                    messages.append({"role": "tool", "name": call.function.name,
                                     "tool_call_id": call.id, "content": text})


if __name__ == "__main__":
    asyncio.run(main())
