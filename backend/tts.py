import os
import httpx
from openai import AsyncOpenAI
from dotenv import load_dotenv
from .logger import get_logger

load_dotenv()

log = get_logger("tts")

# Windows TLS inspection workaround — verify=False is intentional for this dev environment
_http_client = httpx.AsyncClient(verify=False)


class OpenAITTS:
    def __init__(self):
        self.client = AsyncOpenAI(
            api_key=os.environ.get("OPENAI_API_KEY"),
            http_client=_http_client,
        )
        self.model = "tts-1"
        self.voice = "nova"
        log.info("OpenAITTS initialized: model=%s, voice=%s", self.model, self.voice)
        if not os.environ.get("OPENAI_API_KEY"):
            log.error("OPENAI_API_KEY is not set — TTS will not function")

    async def generate_stream(self, text: str):
        """Streams raw 24kHz 16-bit mono PCM from OpenAI TTS."""
        if not os.environ.get("OPENAI_API_KEY"):
            log.error("TTS: skipping — OPENAI_API_KEY not configured")
            return

        log.info("TTS: requesting OpenAI audio for %d chars: '%s...'", len(text), text[:80])

        try:
            total_bytes = 0
            async with self.client.audio.speech.with_streaming_response.create(
                model=self.model,
                voice=self.voice,
                input=text,
                response_format="pcm",
            ) as response:
                log.debug("TTS: OpenAI stream opened, receiving PCM chunks...")
                async for chunk in response.iter_bytes(chunk_size=4096):
                    total_bytes += len(chunk)
                    yield chunk

            log.info("TTS: streaming complete, %d bytes sent", total_bytes)
        except Exception as e:
            log.error("TTS: OpenAI error: %s", e, exc_info=True)


tts_service = OpenAITTS()
