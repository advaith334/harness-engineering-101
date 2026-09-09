"""MCP — connect an agent to tools it didn't ship with.

MCP (Model Context Protocol) is the USB-C of agent tooling: a server advertises tools,
resources and prompts; any MCP-aware client discovers and calls them at runtime. You
write the integration once and every MCP-aware agent can use it.

The Mistral SDK has an MCP client built in, so this is short: point a RunContext at an
MCP server and its tools join the agent's tool list automatically.

Requires: pip install mcp
Runs: the official filesystem MCP server over stdio (needs npx / Node on PATH).
"""

import asyncio
import os
import tempfile
from pathlib import Path

from mcp import StdioServerParameters
from mistralai.client import Mistral
from mistralai.extra.mcp.stdio import MCPClientSTDIO
from mistralai.extra.run.context import RunContext

client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
MODEL = "mistral-medium-latest"


def make_sandbox() -> str:
    """A throwaway directory with something to find, so the demo has real work to do."""
    d = Path(tempfile.mkdtemp(prefix="mcp-demo-"))
    (d / "notes.md").write_text("# Q3\n- launch slipped to Oct 6\n- funnel down to 2.1%\n")
    (d / "todo.txt").write_text("legal signoff on pricing copy\nfunnel breakdown by source\n")
    return str(d)


async def main() -> None:
    sandbox = make_sandbox()
    print("sandbox:", sandbox)

    # The server: a separate process, speaking MCP over stdin/stdout.
    # Scoping it to `sandbox` is the security boundary — the agent cannot see outside it.
    server = MCPClientSTDIO(
        stdio_params=StdioServerParameters(
            command="npx",
            args=["-y", "@modelcontextprotocol/server-filesystem", sandbox],
        )
    )

    async with RunContext(model=MODEL) as ctx:
        # Discovery happens here: the client asks the server what it can do and
        # converts each MCP tool into a tool schema the model can call.
        await ctx.register_mcp_client(
            server,
            # Allow-list what the agent may use. Without this it gets write and delete too.
            tool_configuration={"include": ["read_text_file", "list_directory"]},
        )

        for tool in ctx.get_tools():
            print("  discovered:", tool.function.name)

        result = await client.beta.conversations.run_async(
            run_ctx=ctx,
            inputs="Look through the files here and tell me what's blocking Q3.",
        )

    for entry in result.output_entries:
        print(f"  {entry.type}: {str(entry)[:110]}")
    print("\n", result.output_as_text)


if __name__ == "__main__":
    asyncio.run(main())
