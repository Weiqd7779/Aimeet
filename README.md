# Live Multimodal Decision Agent

Hackathon POC that grounds meeting decisions in live audio and selected visual
frames, then prepares traceable structured outputs.

## Run locally

```bash
cp .env.example api/.env
make dev-api
```

In another terminal:

```bash
make dev-web
```

The web app runs at http://localhost:3000 and the API at
http://localhost:8000.

## Environment variables

- `GEMINI_API_KEY`: Gemini Live API key (optional in mock mode)
- `OPENAI_API_KEY`: OpenAI API key for post-meeting synthesis
- `GEMINI_LIVE_MODEL`: Gemini Live model (default: `gemini-3.1-flash-live-preview`)
- `OPENAI_REALTIME_MODEL`: OpenAI Realtime model (default: `gpt-realtime-2.1`)
- `OPENAI_TRANSCRIBE_MODEL`: OpenAI audio transcription model (default: `gpt-4o-mini-transcribe`)
- `OPENAI_MODEL`: OpenAI synthesis model (default: `gpt-5.6-luna`)
- `OPENAI_MODEL_COMPLEX`: OpenAI synthesis model for complex sessions (default: `gpt-5.6-terra`)
- `MOCK_MODE`: Force mock live behavior; defaults to `true` when neither live provider key is set
- `LIVE_PROVIDER`: Live provider (`gemini`, `openai`, or `mock`). Defaults to OpenAI
  when only an OpenAI key is available, Gemini when a Gemini key is available, and
  mock otherwise. `MOCK_MODE=true` always forces `mock`.
- `SYNTHESIS_MOCK`: Force deterministic synthesis mock mode; defaults to `true` when no OpenAI key is set
