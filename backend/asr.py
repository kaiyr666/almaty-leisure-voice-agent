import os
import io
import asyncio
import wave
import httpx
from dotenv import load_dotenv
from groq import Groq
from .logger import get_logger

load_dotenv()

log = get_logger("asr")

# Windows TLS inspection workaround — same issue as TTS (see tts.py)
_http_client = httpx.Client(verify=False)


class GroqASR:
    def __init__(self):
        self.client = Groq(
            api_key=os.environ.get("GROQ_API_KEY"),
            http_client=_http_client,
        )
        self.model = "whisper-large-v3-turbo"
        log.info("GroqASR initialized with model=%s", self.model)

    def _pcm_to_wav(
        self, pcm_bytes: bytes, sample_rate: int = 16000, channels: int = 1, sampwidth: int = 2
    ) -> bytes:
        """Converts raw headerless PCM bytes to WAV format in memory."""
        wav_io = io.BytesIO()
        with wave.open(wav_io, "wb") as wav_file:
            wav_file.setnchannels(channels)
            wav_file.setsampwidth(sampwidth)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(pcm_bytes)
        return wav_io.getvalue()

    async def transcribe(self, pcm_bytes: bytes) -> str:
        """Transcribes raw 16kHz mono PCM bytes using Groq Whisper."""
        if not pcm_bytes:
            log.warning("transcribe() called with empty PCM bytes")
            return ""

        duration_s = len(pcm_bytes) / 2 / 16000
        log.info("ASR: transcribing %d bytes (%.2fs of audio)", len(pcm_bytes), duration_s)

        wav_bytes = self._pcm_to_wav(pcm_bytes)
        audio_file = io.BytesIO(wav_bytes)
        audio_file.name = "audio.wav"

        loop = asyncio.get_running_loop()
        try:
            log.debug("ASR: sending to Groq Whisper (%s)...", self.model)
            translation = await loop.run_in_executor(
                None,
                lambda: self.client.audio.transcriptions.create(
                    file=audio_file,
                    model=self.model,
                    language="ru",
                    response_format="json",
                ),
            )
            text = getattr(translation, "text", "").strip()
            log.info("ASR: result = '%s'", text)
            return text
        except Exception as e:
            log.error("ASR: transcription error: %s", e, exc_info=True)
            return ""


asr_service = GroqASR()
