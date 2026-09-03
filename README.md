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
- `OPENAI_MODEL`: OpenAI model (default: `gpt-5.6-luna`)
- `MOCK_MODE`: Enable mock behavior; defaults to `true` when no Gemini key is set
