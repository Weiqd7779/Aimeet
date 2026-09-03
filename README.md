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
- `DATA_DIR`: Directory for persisted GroundedVisualEvents and evidence frames (default: `data`)
- `CONTEXT_BEFORE_SECONDS` / `CONTEXT_AFTER_SECONDS`: Context window around a trigger (default: `20` / `30`)
- `BUFFER_SECONDS`: In-memory transcript/frame ring buffer window (default: `60`)

## GroundedVisualEvent pipeline

單一 hypothesis：語音模型辨識「這句話需要看畫面」→ 正確時刻抓幀 → vision 驗證濾口頭禪
→ 結合前後語境建立一筆 GroundedVisualEvent。

- `create_anchor` 進來時建立 `triggered` 事件、主動要求前端擷取 `reason="deictic"` 的關鍵幀
  （此幀繞過 Realtime 的 4 秒節流），並把重處理丟進單一 processing queue；音訊與影格轉發
  永遠不被下游 LLM 呼叫阻塞。
- 背景 worker 用 trigger 時間戳挑最接近的一幀做 vision 驗證，只有
  `is_grounded_visual_reference == true` 才進 `aggregating`；口頭禪（「這件事回去再說」）被丟棄。
- 約 30 秒後聚合 `context_after`，狀態轉 `closed`、填 `time_range.end`。
- 持久資料只有事件與截圖：`data/session_{id}/events.json` 與
  `data/session_{id}/frames/{frame_id}.jpg`（JSON 不含 base64）。原始 transcript 與 frame
  只留最近約 60 秒的記憶體 ring buffer。
- 真實 provider 模式以 LLM tool call 為唯一觸發路徑；前端與 `mock.py` 的 regex 只給 mock/離線 demo。

## 驗收標準

三層都通過才算 done，**只有 mock 綠燈不算 done**：

1. Mock/單元（CI 必跑）：`cd api && uv run pytest -q`
2. 真實 provider 整合（需 `OPENAI_API_KEY`，缺少時 skip）：
   `cd api && uv run pytest -q -m integration`
3. Google Meet E2E（人工，須附錄影、`events.json`、截圖、transcript log）：
   見 [`docs/e2e_google_meet_checklist.md`](docs/e2e_google_meet_checklist.md)
