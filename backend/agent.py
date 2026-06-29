import json
import array
import asyncio
import time
from starlette.websockets import WebSocketDisconnect
from .asr import asr_service
from .llm import llm_service
from .tts import tts_service
from .logger import get_logger

log = get_logger("agent")

GREETING_TEXT = (
    "Hey there! I'm your AI leisure assistant. "
    "Tell me what kind of event you're looking for — "
    "concerts, movies, standups, festivals — and I'll find the best options for you!"
)


def _peak_amplitude(pcm: bytes) -> int:
    samples = array.array("h")
    samples.frombytes(pcm[: len(pcm) - (len(pcm) % 2)])
    return max((abs(s) for s in samples), default=0)


async def collect_utterance(client_websocket):
    """Buffer websocket messages until stop_recording is received.
    Returns the PCM bytes for the utterance, or None on disconnect."""
    audio_buffer = bytearray()
    peak = 0
    log.debug("Waiting for next user utterance...")

    while True:
        try:
            message = await client_websocket.receive()
        except Exception as e:
            log.warning("WebSocket receive error: %s", e)
            return None

        if message.get("type") == "websocket.disconnect":
            log.info("Client disconnected during utterance collection")
            return None

        if "bytes" in message:
            data = message["bytes"]
            audio_buffer.extend(data)
            peak = max(peak, _peak_amplitude(data))

        elif "text" in message:
            try:
                ctrl = json.loads(message["text"])
            except Exception as parse_err:
                log.warning("Control parse error: %s — raw: %s", parse_err, message["text"])
                continue

            kind = ctrl.get("type")
            if kind == "start_recording":
                log.debug("start_recording: clearing audio buffer")
                audio_buffer = bytearray()
                peak = 0
            elif kind == "stop_recording":
                duration_s = len(audio_buffer) / 2 / 16000
                log.info(
                    "stop_recording: %d bytes captured (%.2fs), peak=%d/32767",
                    len(audio_buffer),
                    duration_s,
                    peak,
                )
                return bytes(audio_buffer)
            else:
                log.debug("Unknown control message type: %s", kind)


async def handle_gemini_session(client_websocket):
    """
    Main session loop: greeting → [ASR → LLM → TTS] per turn.
    Maintains per-session conversation history so the LLM can answer
    follow-up questions without re-searching.
    """
    session_id = id(client_websocket)
    log.info("=== Session started [id=%s] ===", session_id)

    # Conversation history — persists for the full WebSocket session.
    # Each entry: {"role": "user"|"assistant", "text": "..."}
    # The LLM receives this on every turn, enabling contextual follow-up.
    history: list[dict] = []
    turn_count = 0

    try:
        # --- Greeting ---
        log.info("[%s] Sending greeting via TTS", session_id)
        await client_websocket.send_text(
            json.dumps({"type": "status", "message": "Speaking...", "state": "speaking"})
        )
        await client_websocket.send_text(
            json.dumps({"type": "transcript", "role": "assistant", "text": GREETING_TEXT})
        )

        t0 = time.monotonic()
        async for chunk in tts_service.generate_stream(GREETING_TEXT):
            await client_websocket.send_bytes(chunk)
        log.info("[%s] Greeting TTS done in %.2fs", session_id, time.monotonic() - t0)

        history.append({"role": "assistant", "text": GREETING_TEXT})

        await client_websocket.send_text(
            json.dumps({"type": "status", "message": "Click the microphone to speak", "state": "idle"})
        )

        # --- Main loop ---
        while True:
            turn_count += 1
            log.info("[%s] === Turn %d — waiting for voice input ===", session_id, turn_count)

            user_pcm = await collect_utterance(client_websocket)
            if user_pcm is None:
                log.info("[%s] Session ended after %d turns", session_id, turn_count - 1)
                break

            if len(user_pcm) < 3200:  # < 100ms of audio
                log.warning(
                    "[%s] Audio too short (%d bytes) — skipping turn", session_id, len(user_pcm)
                )
                continue

            t_turn = time.monotonic()

            # --- ASR ---
            await client_websocket.send_text(
                json.dumps({"type": "status", "message": "Processing speech...", "state": "processing"})
            )

            log.info("[%s] Turn %d: ASR starting...", session_id, turn_count)
            t_asr = time.monotonic()
            user_text = await asr_service.transcribe(user_pcm)
            log.info(
                "[%s] Turn %d: ASR done in %.2fs → '%s'",
                session_id,
                turn_count,
                time.monotonic() - t_asr,
                user_text,
            )

            if not user_text:
                log.warning("[%s] ASR returned empty — asking user to retry", session_id)
                await client_websocket.send_text(
                    json.dumps({"type": "status", "message": "Didn't catch that — please try again.", "state": "idle"})
                )
                continue

            await client_websocket.send_text(
                json.dumps({"type": "transcript", "role": "user", "text": user_text})
            )

            # --- LLM ---
            log.info(
                "[%s] Turn %d: LLM starting (history=%d entries)...",
                session_id,
                turn_count,
                len(history),
            )
            t_llm = time.monotonic()
            assistant_text = await llm_service.get_response(user_text, history)
            log.info(
                "[%s] Turn %d: LLM done in %.2fs → '%s...'",
                session_id,
                turn_count,
                time.monotonic() - t_llm,
                assistant_text[:100],
            )

            # Persist this exchange to history for future follow-up questions
            history.append({"role": "user", "text": user_text})
            history.append({"role": "assistant", "text": assistant_text})
            log.debug("[%s] History now has %d entries", session_id, len(history))

            await client_websocket.send_text(
                json.dumps({"type": "transcript", "role": "assistant", "text": assistant_text})
            )

            # --- TTS ---
            log.info("[%s] Turn %d: TTS starting...", session_id, turn_count)
            await client_websocket.send_text(
                json.dumps({"type": "status", "message": "Speaking...", "state": "speaking"})
            )

            t_tts = time.monotonic()
            audio_sent = False
            async for chunk in tts_service.generate_stream(assistant_text):
                await client_websocket.send_bytes(chunk)
                audio_sent = True
            log.info(
                "[%s] Turn %d: TTS done in %.2fs, audio_sent=%s",
                session_id,
                turn_count,
                time.monotonic() - t_tts,
                audio_sent,
            )

            if not audio_sent:
                log.error("[%s] TTS produced no audio — falling back to text status", session_id)
                await client_websocket.send_text(
                    json.dumps({"type": "status", "message": assistant_text, "state": "idle"})
                )

            log.info(
                "[%s] Turn %d complete in %.0fms",
                session_id,
                turn_count,
                (time.monotonic() - t_turn) * 1000,
            )

            await client_websocket.send_text(
                json.dumps({"type": "status", "message": "Click the microphone to speak", "state": "idle"})
            )

    except WebSocketDisconnect:
        log.info("[%s] Client disconnected mid-session (turn %d)", session_id, turn_count)
    except Exception as e:
        log.error("[%s] Fatal session error: %s", session_id, e, exc_info=True)
