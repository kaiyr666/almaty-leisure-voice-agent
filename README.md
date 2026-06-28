# Almaty Leisure — Voice AI Assistant

A voice-driven AI assistant that helps users find events in Almaty. Speak your request in Russian ("Что интересного сегодня вечером?"), and the assistant searches sxodim.com in real time, then speaks the results back to you.

---

## What the Agent Does

The assistant follows a fully autonomous pipeline on every turn:

1. **Listens** — captures your voice via the browser microphone
2. **Transcribes** — sends the raw audio to Groq Whisper (speech-to-text)
3. **Thinks** — sends the transcript to Llama 3 (LLM), which decides whether to search or answer from memory
4. **Searches** (if needed) — instructs a tool to launch a real Chromium browser, navigate to sxodim.com, and extract live event listings
5. **Responds** — the LLM composes a natural Russian reply from the search results
6. **Speaks** — sends the reply text to OpenAI TTS and streams the audio back to your browser
7. **Remembers** — stores the full conversation history so follow-up questions ("расскажи подробнее про первый") are answered without re-searching

---

## Architecture

```
Browser (frontend)
│   WebSocket (ws://localhost:8000/ws)
│   ┌─────────────────────────────────────┐
│   │  mic → Float32 PCM → Int16 binary   │ (sent as binary frames)
│   │  JSON control messages              │ (start_recording / stop_recording)
│   │  JSON status / transcript messages  │ (received from server)
│   │  Int16 PCM audio ← TTS stream       │ (received as binary frames)
│   └─────────────────────────────────────┘
│
FastAPI Backend (backend/)
│
├── main.py          — FastAPI app, WebSocket endpoint, MCP Playwright lifecycle
├── agent.py         — Session orchestrator: greeting → [ASR → LLM → TTS] loop
├── asr.py           — Groq Whisper: PCM bytes → transcript text
├── llm.py           — Groq Llama 3: text + history → response (with tool use)
├── tts.py           — OpenAI TTS: response text → raw PCM audio stream
├── scraper.py       — sxodim.com parser (BeautifulSoup on MCP-fetched HTML)
├── mcp_client.py    — MCP client that controls the headless Playwright browser
└── logger.py        — Centralised rotating file logger (logs/app.log)
```

### Request Flow (one full turn)

```
User speaks
    │
    ▼
[Frontend] Records 16kHz mono PCM via Web Audio API
    │  binary WebSocket frames
    ▼
[agent.py] collect_utterance() — buffers PCM until stop_recording signal
    │  raw PCM bytes
    ▼
[asr.py] GroqASR.transcribe()
  • Wraps PCM in WAV header (in memory)
  • Calls Groq Whisper large-v3-turbo
  • Returns transcript string
    │  transcript text
    ▼
[llm.py] GroqLLM.get_response()
  • Builds message list: system prompt + full conversation history + new user text
  • First LLM call: Llama 3.3-70B with tool definition for search_events
  │
  ├── If LLM decides to search:
  │     │
  │     ▼
  │   [scraper.py] get_events_from_sites()
  │     │
  │     ▼
  │   [mcp_client.py] call_tool("browser_navigate", url)
  │                   call_tool("browser_evaluate", js)
  │     │  raw HTML
  │     ▼
  │   parse_sxodim() — BeautifulSoup extracts event titles
  │   deduplicate_events() — removes duplicates
  │     │  formatted event list string
  │     ▼
  │   Second LLM call: Llama 3.3-70B with tool result → final reply text
  │
  └── If LLM answers from memory: returns text directly
    │  assistant reply text
    ▼
[tts.py] OpenAITTS.generate_stream()
  • Streams raw 24kHz 16-bit PCM from OpenAI TTS (tts-1 / nova voice)
    │  binary PCM chunks via WebSocket
    ▼
[Frontend] Queues PCM chunks in AudioContext (24kHz)
           Plays back sequentially via Web Audio API
```

---

## Technology Stack

| Layer | Technology | Purpose |
|---|---|---|
| Frontend | HTML / CSS / Vanilla JS | Voice UI, WebSocket client, audio capture & playback |
| Backend | Python 3.12 + FastAPI | WebSocket server, async pipeline orchestration |
| ASR | Groq — Whisper large-v3-turbo | Speech-to-text (Russian, fast inference) |
| LLM | Groq — Llama 3.3-70B Versatile | Intent understanding, tool use, response generation |
| TTS | OpenAI — tts-1 (nova voice) | Text-to-speech, streams raw PCM |
| Web scraping | MCP Playwright (`@playwright/mcp`) | Headless Chromium browser controlled via MCP protocol |
| HTML parsing | BeautifulSoup4 | Extracts event data from scraped HTML |
| Logging | Python `logging` + RotatingFileHandler | Per-module structured logs to `logs/app.log` |

---

## Conversation Memory

Each browser session maintains a `history` list in `agent.py`. Every completed exchange (user utterance + assistant reply) is appended:

```python
history = [
    {"role": "assistant", "text": "Привет! Я твой голосовой помощник..."},
    {"role": "user",      "text": "Что идёт в кино сегодня?"},
    {"role": "assistant", "text": "Вот что я нашёл на sxodim.com: 1. ..."},
    # next turn appended here
]
```

On every new turn this entire history is prepended to the LLM's message list. The system prompt explicitly instructs the model to answer follow-up questions ("расскажи про второй", "сколько стоит") from this history rather than triggering a new search.

Memory is per-session (in-process). Closing the browser tab starts a fresh session.

---

## Project Structure

```
Seminar 17/
├── backend/
│   ├── agent.py        Session orchestrator and main pipeline loop
│   ├── asr.py          Groq Whisper speech-to-text
│   ├── llm.py          Groq Llama LLM with search_events tool
│   ├── tts.py          OpenAI TTS streaming
│   ├── scraper.py      sxodim.com scraper and event parser
│   ├── mcp_client.py   MCP Playwright browser client
│   ├── main.py         FastAPI app, WebSocket endpoint
│   └── logger.py       Centralised logging setup
├── frontend/
│   ├── index.html      Single-page voice UI
│   ├── app.js          WebSocket client, audio capture, PCM playback
│   └── style.css       Dark glassmorphism design, state-based orb animations
├── logs/
│   └── app.log         Rotating log file (10 MB × 5 backups)
├── .env                API keys (not committed to version control)
├── requirements.txt    Python dependencies
└── agent.md            Original feature specification
```

---

## Setup

### Prerequisites

- Python 3.12+
- Node.js + npm (for `npx @playwright/mcp` — installs automatically on first run)

### Install dependencies

```bash
pip install -r requirements.txt
```

### Configure API keys

Create a `.env` file in the project root (or edit the existing one):

```env
GROQ_API_KEY=your_groq_api_key
OPENAI_API_KEY=your_openai_api_key
```

- **Groq API key** — free at [console.groq.com](https://console.groq.com). Used for both ASR (Whisper) and LLM (Llama).
- **OpenAI API key** — from [platform.openai.com](https://platform.openai.com). Used for TTS only.

### Run

```bash
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

Open **http://localhost:8000** in your browser.

On first startup, MCP Playwright downloads a Chromium browser (~10 seconds). Once you see `Application startup complete.` in the terminal, the assistant is ready.

---

## How to Use

1. Open http://localhost:8000
2. Click the **microphone button** to start recording
3. Speak your request in Russian (e.g., *"Что можно посмотреть сегодня вечером?"*)
4. Click the microphone button again to stop recording
5. Wait for the orb animation to cycle through **processing → speaking**
6. Listen to the spoken response; read it in the transcript panel
7. Ask follow-up questions without re-clicking — the assistant remembers what was found

**Example conversation:**
```
You:       Что интересного в Алматы на выходных?
Assistant: Вот что я нашёл на sxodim.com: 1. Стендап концерт...
You:       Расскажи подробнее про первый
Assistant: Это стендап концерт в... [answers from memory, no new search]
```

---

## Logging

All pipeline activity is written to `logs/app.log` with timestamps, log level, and module name:

```
[2026-06-28 23:17:51] [INFO ] [assistant.agent] === Session started [id=147...] ===
[2026-06-28 23:17:51] [INFO ] [assistant.tts]   TTS: requesting OpenAI audio for 116 chars...
[2026-06-28 23:17:55] [INFO ] [assistant.tts]   TTS: streaming complete, 369600 bytes sent
[2026-06-28 23:17:55] [INFO ] [assistant.agent] === Turn 1 — waiting for voice input ===
[2026-06-28 23:17:56] [INFO ] [assistant.asr]   ASR: result = 'Что идёт в кино?'
[2026-06-28 23:17:57] [INFO ] [assistant.llm]   LLM: executing search_events(query='кино', date='сегодня')
[2026-06-28 23:18:08] [INFO ] [assistant.llm]   LLM: search_events returned 207 chars in 11.67s
[2026-06-28 23:18:09] [INFO ] [assistant.agent] Turn 1 complete in 13240ms
```

Log files rotate at 10 MB and keep 5 backups (`app.log`, `app.log.1`, … `app.log.5`).

---

## Known Limitations

- **Scraper selectors** — sxodim.com's HTML structure may change. If real events are not found, the scraper falls back to dummy placeholder events. Check `logs/app.log` for `[WARN] All selectors failed` to diagnose this.
- **Session memory** — history is in-process and not persisted to disk. Restarting the server or refreshing the browser clears it.
- **Language** — ASR is configured for Russian (`language="ru"`). English input will still work but accuracy may be lower.
- **MCP startup time** — the Playwright browser takes ~10 seconds to initialise on each server start.
