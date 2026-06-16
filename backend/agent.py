import os
import json
import asyncio
from google import genai
from google.genai import types
from dotenv import load_dotenv

from .mcp_client import mcp_client
from .scraper import get_events_from_sites

load_dotenv()

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

async def search_events_tool(query: str, target_date: str = "today") -> str:
    """Searches for leisure events in Almaty using MCP Playwright.
    
    Args:
        query: What kind of events to look for (e.g. concert, standup, movie)
        target_date: The date to search for (e.g. today, tomorrow)
        
    Returns:
        A formatted string of deduplicated events found on the websites.
    """
    print(f"Agent requested to search events: query='{query}', date='{target_date}'")
    # In a fully autonomous setup, we'd give the agent 'navigate' and 'get_dom' directly.
    # To ensure reliability and speed, we orchestrate the MCP Playwright calls here.
    events_data = await get_events_from_sites(query, target_date)
    return events_data

# The declaration for Gemini
search_events_declaration = types.FunctionDeclaration(
    name="search_events",
    description="Searches for leisure events (concerts, movies, standups) in Almaty on afisha websites using MCP Playwright.",
    parameters={
        "type": "OBJECT",
        "properties": {
            "query": {"type": "STRING", "description": "Type of event (concert, standup, movie, etc)"},
            "target_date": {"type": "STRING", "description": "Date or time (e.g., today, tonight, this weekend)"}
        },
        "required": ["query"]
    }
)

tool = types.Tool(function_declarations=[search_events_declaration])

async def handle_gemini_session(client_websocket):
    config = types.LiveConnectConfig(
        response_modalities=[types.LiveConnectResponseModality.AUDIO],
        tools=[tool],
        system_instruction=types.Content(parts=[types.Part.from_text(
            "You are a helpful Voice AI Assistant for Leisure Planning in Almaty. "
            "You can talk to the user and help them find events (concerts, standups, etc). "
            "Always use the 'search_events' tool to fetch current events from sxodim.com, kino.kz, or ticketon.kz. "
            "Keep your responses concise and natural. Speak in Russian."
        )])
    )
    
    try:
        async with client.aio.live.connect(model="gemini-2.0-flash-exp", config=config) as session:
            print("Connected to Gemini Live.")
            
            # Send initial greeting
            await session.send(input="Привет! Скажи, что ты можешь помочь найти куда сходить в Алматы.", end_of_turn=True)
            
            # Task to receive audio from frontend and send to Gemini
            async def receive_from_client():
                while True:
                    data = await client_websocket.receive_bytes()
                    # We assume it's PCM 16-bit 16kHz from frontend
                    await session.send(
                        input={"mime_type": "audio/pcm;rate=16000", "data": data}
                    )
            
            # Task to receive from Gemini and send to frontend
            async def receive_from_gemini():
                async for response in session.receive():
                    if response.server_content:
                        model_turn = response.server_content.model_turn
                        if model_turn:
                            for part in model_turn.parts:
                                if part.inline_data:
                                    # Forward audio PCM to frontend
                                    # Wait, Gemini returns 24kHz PCM by default!
                                    await client_websocket.send_bytes(part.inline_data.data)
                                if part.text:
                                    # Optional text logging
                                    print(f"Gemini: {part.text}")
                        if response.server_content.interrupted:
                            print("Gemini interrupted.")
                            
                    # Handle tool calls
                    if response.tool_call:
                        for fc in response.tool_call.function_calls:
                            if fc.name == "search_events":
                                args = {k: v for k, v in fc.args.items()}
                                query = args.get("query", "")
                                date = args.get("target_date", "today")
                                
                                # Let frontend know we are searching
                                await client_websocket.send_text(json.dumps({
                                    "type": "status", 
                                    "message": "Searching web...", 
                                    "state": "idle"
                                }))
                                
                                result_text = await search_events_tool(query, date)
                                
                                # Send result back to Gemini
                                tool_response = types.LiveClientContent(
                                    turn_complete=True,
                                    tool_response=types.ToolResponse(
                                        function_responses=[
                                            types.FunctionResponse(
                                                name=fc.name,
                                                id=fc.id,
                                                response={"result": result_text}
                                            )
                                        ]
                                    )
                                )
                                await session.send(input=tool_response)
                                
            await asyncio.gather(receive_from_client(), receive_from_gemini())
            
    except Exception as e:
        print(f"Gemini Session Error: {e}")
