import os
from contextlib import AsyncExitStack
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from .logger import get_logger

log = get_logger("mcp")


class MCPClient:
    def __init__(self):
        self.session = None
        self._exit_stack = None

    async def connect(self):
        log.info("Connecting to Playwright MCP server via 'npx -y @playwright/mcp'...")
        server_params = StdioServerParameters(
            command="npx",
            args=["-y", "@playwright/mcp"],
            env=os.environ.copy(),
        )

        self._exit_stack = AsyncExitStack()
        try:
            read_stream, write_stream = await self._exit_stack.enter_async_context(
                stdio_client(server_params)
            )
            self.session = await self._exit_stack.enter_async_context(
                ClientSession(read_stream, write_stream)
            )
            await self.session.initialize()
            log.info("MCP Playwright connected and initialized")
        except Exception as e:
            log.error("MCP connect failed: %s", e, exc_info=True)
            await self.close()
            raise

    async def call_tool(self, tool_name: str, arguments: dict):
        if not self.session:
            log.error("call_tool('%s') called but session is not connected", tool_name)
            raise RuntimeError("MCP client is not connected.")
        log.debug("MCP call_tool: '%s', args=%s", tool_name, arguments)
        result = await self.session.call_tool(tool_name, arguments)
        content_size = len(result.content[0].text) if result.content else 0
        log.debug("MCP tool '%s' returned %d chars", tool_name, content_size)
        return result

    async def close(self):
        log.info("Closing MCP Playwright connection...")
        if self._exit_stack:
            await self._exit_stack.aclose()
            self._exit_stack = None
        self.session = None
        log.info("MCP Playwright disconnected")


mcp_client = MCPClient()
