import os
import json
import asyncio
import time
import httpx
from dotenv import load_dotenv
from groq import Groq
from .scraper import get_events_from_sites
from .logger import get_logger

load_dotenv()

log = get_logger("llm")

# Windows TLS inspection workaround — same issue as TTS (see tts.py)
_http_client = httpx.Client(verify=False)


class GroqLLM:
    def __init__(self):
        self.client = Groq(
            api_key=os.environ.get("GROQ_API_KEY"),
            http_client=_http_client,
        )
        self.model = "llama-3.3-70b-versatile"

        self.system_instruction = (
            "You are a helpful Voice AI Assistant for Leisure Planning in Almaty. "
            "You help users find events: concerts, standups, movies, etc. "
            "Use the 'search_events' tool ONLY when the user asks about NEW events or a NEW search. "
            "If the user asks follow-up questions about events already found "
            "(e.g. 'tell me more', 'what was the first one', 'give me details'), "
            "answer from the conversation history — do NOT call search_events again. "
            "Keep your responses concise and natural. Speak in Russian."
        )

        self.tools = [
            {
                "type": "function",
                "function": {
                    "name": "search_events",
                    "description": (
                        "Searches for leisure events (concerts, movies, standups) in Almaty "
                        "on sxodim.com using MCP Playwright."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Type of event (concert, standup, movie, etc)",
                            },
                            "target_date": {
                                "type": "string",
                                "description": "Date or time (e.g., today, tonight, this weekend)",
                            },
                        },
                        "required": ["query"],
                    },
                },
            }
        ]
        log.info("GroqLLM initialized with model=%s", self.model)

    async def get_response(self, user_message: str, history: list[dict]) -> str:
        """
        Sends user message + full conversation history to Llama on Groq.
        Handles tool calls (event search) and returns the final assistant text.
        The caller is responsible for appending this exchange to history.
        """
        # Build message list: system + all previous turns + new user message
        messages = [{"role": "system", "content": self.system_instruction}]
        for turn in history:
            messages.append({"role": turn["role"], "content": turn["text"]})
        messages.append({"role": "user", "content": user_message})

        log.info(
            "LLM request: user='%s...', history_turns=%d, total_messages=%d",
            user_message[:80],
            len(history),
            len(messages),
        )

        loop = asyncio.get_running_loop()
        t0 = time.monotonic()

        try:
            log.debug("LLM: first call to Groq %s with tools...", self.model)
            response = await loop.run_in_executor(
                None,
                lambda: self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=self.tools,
                    tool_choice="auto",
                ),
            )

            elapsed = time.monotonic() - t0
            response_message = response.choices[0].message
            tool_calls = getattr(response_message, "tool_calls", None)

            log.debug(
                "LLM: first response in %.2fs, tool_calls=%s",
                elapsed,
                [tc.function.name for tc in tool_calls] if tool_calls else None,
            )

            if tool_calls:
                # Append the assistant's tool-call message to enable the second call
                messages.append(response_message)

                for tool_call in tool_calls:
                    if tool_call.function.name == "search_events":
                        args = json.loads(tool_call.function.arguments)
                        query = args.get("query", "")
                        target_date = args.get("target_date", "today")

                        log.info(
                            "LLM: executing search_events(query='%s', date='%s')",
                            query,
                            target_date,
                        )
                        t_search = time.monotonic()
                        result = await get_events_from_sites(query, target_date)
                        log.info(
                            "LLM: search_events returned %d chars in %.2fs",
                            len(result),
                            time.monotonic() - t_search,
                        )
                        log.debug("LLM: search_events result:\n%s", result)

                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "name": "search_events",
                                "content": result,
                            }
                        )

                log.debug("LLM: second call to Groq with tool results...")
                t1 = time.monotonic()
                second_response = await loop.run_in_executor(
                    None,
                    lambda: self.client.chat.completions.create(
                        model=self.model,
                        messages=messages,
                    ),
                )
                final_text = second_response.choices[0].message.content
                log.info(
                    "LLM: final response in %.2fs (tool path): '%s...'",
                    time.monotonic() - t1,
                    final_text[:150],
                )
                return final_text
            else:
                final_text = response_message.content
                log.info(
                    "LLM: direct response in %.2fs (no tool): '%s...'",
                    elapsed,
                    final_text[:150],
                )
                return final_text

        except Exception as e:
            log.error("LLM: request failed: %s", e, exc_info=True)
            return "Извините, возникла ошибка при обработке запроса."


llm_service = GroqLLM()
