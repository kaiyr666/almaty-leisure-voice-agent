# Voice AI Assistant for Leisure Planning

## Overview
A voice-driven AI assistant designed to help users plan their leisure time in Almaty. Users can speak their requests (e.g., "Where can I go tonight?"), and the system will process the audio, search for relevant events, and respond with a voice message suggesting options.

## Core Features
1. **Voice-Only Interaction (with text UI fallback):** End-to-end flow from voice input to voice output.
2. **Web Scraping via MCP Playwright:** The assistant autonomously searches for events on specific target websites.
3. **Data Deduplication & Filtering:** Overlapping events from different sites are deduplicated, and only events matching the user's criteria are presented.
4. **Streaming Architecture:** Real-time or near real-time streaming of audio to minimize latency.
5. **Modern Frontend:** A beautiful, world-class UI without gradient styles, featuring animations during processing and playback.

## Target Websites
- `https://sxodim.com/almaty`
- `https://kino.kz/ru`
- `https://ticketon.kz/almaty`

## Technology Stack
- **Frontend:** HTML/JS/CSS (Vanilla or React/Vue) with a modern, gradient-free design.
- **Backend:** Python (FastAPI) to orchestrate the pipeline.
- **LLM / ASR / TTS:** Google Stack (Gemini Multimodal LLM for text/audio processing).
- **Web Browsing:** MCP Playwright.

## Definition of Done
- **End-to-end flow works:** Voice in -> Voice out.
- **MCP Playwright integrated:** Successfully searches the required sites.
- **Audio Quality:** Reliable ASR and high-quality TTS.
- **Code Organization:** Clean separation of Frontend and Backend, logical API.
- **Git workflow:** Code shipped in small, tested pieces with PRs.
