# Almaty Leisure — Voice AI Assistant

A fully voice-driven AI assistant for discovering events and leisure activities. Speak your request in English, and the assistant searches a configurable events website in real time using a headless browser, then speaks the results back to you using natural-sounding speech.

---

## What the Agent Does

The assistant runs a fully autonomous voice pipeline on every turn:

1. **Listens** — captures your voice via the browser microphone (16 kHz mono PCM)
2. **Transcribes** — sends the audio to Groq Whisper for fast, accurate speech-to-text
3. **Thinks** — sends the transcript to Llama 3.3-70B, which decides whether to search for new events or answer from conversation memory
4. **Searches** (when needed) — instructs a headless Chromium browser (via MCP Playwright) to navigate to the configured events site, fetch the live HTML, and extract event listings
5. **Responds** — the LLM composes a detailed, enthusiastic reply from the scraped results
6. **Speaks** — sends the reply text to OpenAI TTS and streams raw PCM audio back to the browser for immediate playback
7. **Remembers** — maintains full per-session conversation history so follow-up questions ("tell me more about the first one", "which one is cheapest?") are answered instantly from memory without triggering a new search

---

## Architecture

```
Browser (frontend)
│
│   WebSocket  ws://localhost:8000/ws
│   ┌──────────────────────────────────────────────────┐
│   │  mic → Float32 PCM → Int16 binary frames  ──────►│  (audio upload)
│   │  JSON: { type: "start_recording" }         ──────►│  (control)
│   │  JSON: { type: "stop_recording"  }         ──────►│  (control)
│   │◄────── JSON: { type: "status", state, message }  │  (UI state)
│   │◄────── JSON: { type: "transcript", role, text }  │  (transcript)
│   │◄────── Int16 PCM binary frames (TTS audio)       │  (audio playback)
│   └──────────────────────────────────────────────────┘
│
FastAPI Backend  (backend/)
│
├── main.py        FastAPI app, WebSocket endpoint, MCP Playwright lifecycle
├── agent.py       Session orchestrator: greeting → [ASR → LLM → TTS] loop
├── asr.py         Groq Whisper: raw PCM bytes → transcript string
├── llm.py         Groq Llama 3: text + history → response (with tool use)
├── tts.py         OpenAI TTS: response text → raw 24 kHz PCM stream
├── scraper.py     Events website scraper (BeautifulSoup on MCP-fetched HTML)
├── mcp_client.py  MCP client that controls the headless Playwright browser
└── logger.py      Centralised rotating file logger  →  logs/app.log
```

### Full Request Flow (one turn)

```
User speaks
    │
    ▼
[Frontend]  Web Audio API records at 16 kHz, converts Float32 → Int16 PCM
            Sends binary WebSocket frames while recording
            Sends { type: "stop_recording" } when mic button released
    │
    ▼
[agent.py]  collect_utterance() buffers all binary frames until stop signal
    │  raw 16 kHz mono PCM bytes
    ▼
[asr.py]  GroqASR.transcribe()
  • Wraps PCM in an in-memory WAV header (wave module)
  • POSTs to Groq Whisper large-v3-turbo  (language = "en")
  • Returns transcript string
    │  transcript text
    ▼
[llm.py]  GroqLLM.get_response()
  • Builds message list: system prompt + full conversation history + new user message
  • First Groq call: Llama 3.3-70B-Versatile with search_events tool definition
  │
  ├─ If LLM calls search_events(query, target_date):
  │       │
  │       ▼
  │   [scraper.py]  get_events_from_sites()
  │       │
  │       ▼
  │   [mcp_client.py]  call_tool("browser_navigate", { url: TARGET_URL })
  │                    call_tool("browser_evaluate", { function: "() => document.documentElement.outerHTML" })
  │       │  raw page HTML (tens of thousands of chars)
  │       ▼
  │   parse_sxodim()       — BeautifulSoup walks CSS selectors to extract event titles
  │   deduplicate_events() — deduplicates by lowercase title
  │       │  formatted event list string (up to 5 results)
  │       ▼
  │   Second Groq call: Llama 3.3-70B with tool result → final reply text
  │
  └─ If LLM answers from memory: returns content directly (no second call)
    │  assistant reply text
    ▼
[tts.py]  OpenAITTS.generate_stream()
  • Calls OpenAI TTS  (model: tts-1, voice: nova, format: pcm)
  • Streams raw 24 kHz 16-bit mono PCM chunks
    │  binary PCM chunks over WebSocket
    ▼
[Frontend]  Decodes Int16 PCM → Float32
            Queues AudioBuffer objects in a 24 kHz AudioContext
            Plays back sequentially via Web Audio API
```

---

## Technology Stack

| Layer | Technology | Detail |
|---|---|---|
| Frontend | HTML5 / CSS3 / Vanilla JS | Voice UI, WebSocket client, audio capture & PCM playback |
| Web server | Python 3.12 + FastAPI | Async WebSocket server, static file serving |
| ASR | Groq — Whisper large-v3-turbo | Speech-to-text, English, ~1 s latency |
| LLM | Groq — Llama 3.3-70B Versatile | Intent understanding, tool-use decisions, detailed response generation |
| TTS | OpenAI — tts-1 / nova voice | Text-to-speech, streams raw 24 kHz PCM |
| Browser automation | MCP Playwright (`@playwright/mcp` via npx) | Headless Chromium controlled via the Model Context Protocol |
| HTML parsing | BeautifulSoup4 | Extracts event titles from scraped page HTML |
| Logging | Python `logging` + RotatingFileHandler | Structured per-module logs → `logs/app.log` (10 MB × 5 backups) |

---

## Conversation Memory

Each WebSocket session maintains a `history` list in `agent.py`. After every completed turn, both the user message and the assistant reply are appended:

```python
history = [
    {"role": "assistant", "text": "Hey there! I'm your AI leisure assistant..."},
    {"role": "user",      "text": "Find me standup events this weekend."},
    {"role": "assistant", "text": "Great choice! Here are the standups I found: 1. ..."},
    {"role": "user",      "text": "Tell me more about the first one."},
    # LLM answers from history — no new search triggered
]
```

The full history is prepended to the LLM message list on every turn. The system prompt explicitly instructs the model to use `search_events` only for new queries — follow-up questions ("which one is cheaper?", "what's the venue?") are answered directly from the accumulated context.

Memory is **per-session and in-process**. Closing the browser tab or restarting the server starts a fresh session.

---

## Configurable Search Target

The events website is controlled by the `TARGET_URL` environment variable, making the agent reusable for any city or events platform:

```env
TARGET_URL=https://sxodim.com/almaty
```

Change this to point at any events listing page. The scraper will navigate to that URL, fetch its HTML, and attempt to extract event titles from it.

---

## Project Structure

```
Seminar 17/
├── backend/
│   ├── main.py         FastAPI app, WebSocket endpoint, MCP lifecycle
│   ├── agent.py        Session orchestrator and main pipeline loop
│   ├── asr.py          Groq Whisper speech-to-text
│   ├── llm.py          Groq Llama LLM with search_events tool
│   ├── tts.py          OpenAI TTS streaming (tts-1 / nova)
│   ├── scraper.py      Events website scraper and HTML parser
│   ├── mcp_client.py   MCP Playwright headless browser client
│   └── logger.py       Centralised logging configuration
├── frontend/
│   ├── index.html      Single-page voice UI
│   ├── app.js          WebSocket client, audio capture, PCM playback queue
│   └── style.css       Dark glassmorphism design, orb state animations
├── logs/
│   └── app.log         Rotating log file (created on first run)
├── .env                API keys — not committed to version control
├── requirements.txt    Python dependencies
└── agent.md            Original feature specification
```

---

## Setup

### Prerequisites

- **Python 3.12+**
- **Node.js + npm** — required for `npx @playwright/mcp` (auto-downloaded on first run, no manual install needed)

### 1. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure environment variables

Create a `.env` file in the project root:

```env
GROQ_API_KEY=your_groq_api_key
OPENAI_API_KEY=your_openai_api_key
TARGET_URL=https://sxodim.com/almaty
```

| Variable | Where to get it | Used for |
|---|---|---|
| `GROQ_API_KEY` | [console.groq.com](https://console.groq.com) — free tier available | ASR (Whisper) + LLM (Llama) |
| `OPENAI_API_KEY` | [platform.openai.com](https://platform.openai.com) | TTS only |
| `TARGET_URL` | Any events listing URL | Controls which site the scraper navigates to |

### 3. Start the server

```bash
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

On first startup, MCP Playwright downloads a Chromium browser (~10 seconds, one-time). Once you see `Application startup complete.` in the terminal, the assistant is ready.

### 4. Open the UI

Navigate to **http://localhost:8000** in your browser.

---

## How to Use

1. Open **http://localhost:8000**
2. Wait for the status indicator to show **"Connected. Press the microphone to speak"**
3. Click the **microphone button** to start recording — the orb pulses blue
4. **Speak your request in English** (e.g. *"Find me standup events this weekend"*)
5. Click the microphone button again to stop recording
6. Watch the orb cycle through **Processing → Speaking**
7. Listen to the spoken response; read it in the transcript panel below
8. Ask follow-up questions freely — the assistant remembers everything found in this session

**Example conversation:**

```
You:        Find me standup comedy events this weekend in Almaty.
Assistant:  Great news! I found some fantastic standup shows this weekend.
            1. Thursday Night Laughs at ...  2. Weekend Comedy Gala at ...
            I'd especially recommend number two if you're going with friends!

You:        Tell me more about the second one.
Assistant:  The Weekend Comedy Gala features ... [answers from memory, no new search]

You:        Are there any concerts happening too?
Assistant:  Let me check for you! [triggers new search_events("concert")]
```

---

## Logging

All pipeline stages emit structured logs to `logs/app.log`. This is the primary tool for debugging and tracing issues:

```
[2026-06-29 23:09:28] [INFO ] [assistant.agent]   === Turn 1 — waiting for voice input ===
[2026-06-29 23:09:28] [INFO ] [assistant.asr]     ASR: transcribing 212992 bytes (6.66s of audio)
[2026-06-29 23:09:28] [INFO ] [assistant.asr]     ASR: result = 'Find me stand-ups this weekend in Almaty.'
[2026-06-29 23:09:28] [INFO ] [assistant.llm]     LLM: executing search_events(query='standup', date='this weekend')
[2026-06-29 23:09:28] [INFO ] [assistant.scraper] Navigating MCP Playwright to: https://sxodim.com/almaty
[2026-06-29 23:09:36] [DEBUG] [assistant.mcp]     MCP tool 'browser_navigate' returned 372 chars
[2026-06-29 23:09:39] [INFO ] [assistant.scraper] Fetched 84312 chars of HTML from https://sxodim.com/almaty
[2026-06-29 23:09:39] [INFO ] [assistant.scraper] Parsed 5 events for query='standup'
[2026-06-29 23:09:40] [INFO ] [assistant.tts]     TTS: streaming complete, 724800 bytes sent
[2026-06-29 23:09:43] [INFO ] [assistant.agent]   Turn 1 complete in 16250ms
```

**Log levels:**
- `INFO` — key pipeline milestones (session start, ASR result, LLM tool call, TTS complete)
- `DEBUG` — detailed internals (MCP raw responses, HTML snippet previews, history size)
- `WARNING` — recoverable issues (scraper selector misses, short audio clips)
- `ERROR` — failures requiring attention (API errors, TTS failures, session crashes)

Log files rotate at **10 MB** and keep **5 backups** (`app.log`, `app.log.1`, … `app.log.5`).

---

## Known Limitations

- **Scraper CSS selectors** — event website HTML structures change. If the scraper fails to find events, `logs/app.log` will contain a `[WARNING] All selectors failed` entry along with a 3 000-char HTML snippet to help diagnose which selectors need updating.
- **Session memory** — conversation history is held in process memory and not persisted to disk. Restarting the server or refreshing the browser tab starts a fresh session.
- **Browser autoplay policy** — browsers block audio until the user interacts with the page. The greeting audio plays after the first click (mic button or anywhere on the page).
- **MCP startup time** — the Playwright browser takes ~10 seconds to initialise on each server start. Queries made during this window will time out.
- **Windows TLS** — on Windows machines with corporate TLS inspection (antivirus/proxy), standard certificate verification may fail. The current setup uses `httpx` clients with `verify=False` as a dev-environment workaround. Do not use this in production.
- **Single-user** — each WebSocket connection is an independent session. The server supports concurrent sessions but there is no shared state between them.

---

## Environment Variables Reference

| Variable | Required | Default | Description |
|---|---|---|---|
| `GROQ_API_KEY` | Yes | — | Groq API key for Whisper ASR and Llama LLM |
| `OPENAI_API_KEY` | Yes | — | OpenAI API key for TTS |
| `TARGET_URL` | No | `https://sxodim.com/almaty` | Events website URL the scraper navigates to |
