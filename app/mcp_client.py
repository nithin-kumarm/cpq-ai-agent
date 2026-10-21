
import sys
import json

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class CPQMCPClient:

    def __init__(self):
        self.server_params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "mcp_server.server"]
        )

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict
    ) -> dict:

        async with stdio_client(
            self.server_params
        ) as (read, write):

            async with ClientSession(read, write) as session:
                await session.initialize()

                result = await session.call_tool(
                    name=tool_name,
                    arguments=arguments
                )

                if result.isError:
                    raise RuntimeError(
                        "MCP tool failed: " +
                        "; ".join(
                            block.text
                            for block in result.content
                            if getattr(block, "type", "") == "text"
                        )
                    )

                structured = getattr(
                    result, "structuredContent", None
                )

                if structured is not None:
                    return structured

                for block in result.content:
                    if getattr(block, "type", "") == "text":
                        return json.loads(block.text)

                return {"status": "EMPTY_RESPONSE"}
