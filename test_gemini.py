import asyncio
from google import genai
from google.genai import types
import os
from dotenv import load_dotenv

load_dotenv()

async def main():
    try:
        client = genai.Client()
        print("GenAI Client initialized.")
        config = types.LiveConnectConfig(
            response_modalities=[types.LiveConnectResponseModality.AUDIO]
        )
        # Just test if the connection can be established
        async with client.aio.live.connect(model="gemini-2.0-flash-exp", config=config) as session:
            print("Successfully connected to Gemini Live API.")
            await session.send(input="Hello! Just testing.", end_of_turn=True)
            
            async for response in session.receive():
                if response.server_content:
                    model_turn = response.server_content.model_turn
                    if model_turn:
                        for part in model_turn.parts:
                            if part.inline_data:
                                print(f"Received audio part with {len(part.inline_data.data)} bytes.")
                            if part.text:
                                print(f"Received text: {part.text}")
                break
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
