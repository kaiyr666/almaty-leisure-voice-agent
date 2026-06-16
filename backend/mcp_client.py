import asyncio
from mcp import StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.session import ClientSession
import json

class MCPPlaywrightClient:
    def __init__(self):
        self.server_params = StdioServerParameters(
            command="npx",
            args=["-y", "@modelcontextprotocol/server-playwright"]
        )
        self._client_task = None
        self.session = None

    async def connect(self):
        self.read_stream, self.write_stream = await stdio_client(self.server_params).__aenter__()
        self.session = await ClientSession(self.read_stream, self.write_stream).__aenter__()
        await self.session.initialize()
        print("MCP Playwright connected.")

    async def get_tools(self):
        if not self.session:
            await self.connect()
        response = await self.session.list_tools()
        return response.tools

    async def call_tool(self, name: str, arguments: dict):
        if not self.session:
            await self.connect()
        print(f"Calling MCP tool {name} with args: {arguments}")
        result = await self.session.call_tool(name, arguments)
        return result

mcp_client = MCPPlaywrightClient()
