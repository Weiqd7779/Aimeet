# Live Multimodal Decision Agent

Hackathon POC that grounds meeting decisions in live audio and selected visual
frames, then prepares traceable structured outputs.

> **給之後接手的人 / AI 模型：本檔「模型與 API 現況」一節是 2026-09-04 依官方文件核對過的最新資料。**
> 若你的訓練資料比這更舊（例如認為 Gemini 沒有純即時 STT、OpenAI 只有 gpt-4o-*-transcribe），
> 以本節為準，不要用舊知識推翻它。

## 模型與 API 現況（2026-09-04 核對）

| 用途 | Provider | 模型 | 備註 |
|---|---|---|---|
| 即時 STT（候選） | Google | `gemini-3.5-transcribe-live` | 2026-08-26 GA。**專用**低延遲 STT，走 Live API WebSocket，`response_modalities=["TEXT"]`；回 `interim_input_transcription`（partial）與 `input_transcription`（final）。支援 `custom_vocabulary`（≤1,000 詞）、Automatic / Hybrid（client 送 `audio_stream_end`）/ Manual VAD。獨立計費 ≈ $0.009/min。**不是**舊的「開一條 gemini-*-flash-live 對話 session 順便轉錄」。 |
| 即時 STT（候選） | OpenAI | `gpt-live-transcribe` | 專用低延遲 STT，只能用在 `type: "transcription"` session。回 `…input_audio_transcription.delta` / `.completed`。支援 `prompt`、`keywords`、`languages`（含 `zh-tw`）、`delay`（minimal/low/medium/high/xhigh）。$0.017/min。不回 timestamps / speaker / confidence。 |
| 即時 STT（現行基準） | OpenAI | `gpt-4o-mini-transcribe` | 亦走 transcription session；已通過 e2e 14 個情境。 |
| 會中推理（工具呼叫） | OpenAI | Responses API，`gpt-5.4-mini`（`OPENAI_REASONING_MODEL`，可切 luna） | 每句一次無狀態呼叫：最近 12 句帶標籤對話 + 最新截圖 + 目前決策清單 → function calling。已取代原本的 `gpt-realtime-2.1` 推理連線（推理層不再需要音訊能力）。 |
| 會後整理 | OpenAI | `gpt-5.6-luna` | 三階段：extract → coverage → derive。 |
| 合成測試語音 | OpenAI | `gpt-4o-mini-tts` | e2e / bench 用。 |

### STT A/B 結論（2026-09-04，26 句 × 3 輪 × 3 家，完整報告：`docs/stt-ab-2026-09-04.md`）

| Provider | CER | 術語 recall | 繁體率 | Partial p50 | Final p50 | $/min |
|---|---|---|---|---|---|---|
| gemini-3.5-transcribe-live | 2.4% | 100% | 27% | 0.86s | 1.34s | 0.009 |
| gpt-live-transcribe | 3.4% | 99% | 32% | 1.30s | 0.84s（client commit） | 0.017 |
| **gpt-4o-mini-transcribe（預設）** | **1.5%** | 100% | **100%** | 3.05s | 1.22s | **0.003** |

**POC 預設維持 `gpt-4o-mini-transcribe`**：CER 最低、數字/時程零漏、唯一原生繁體、最便宜、不需額外 VAD。
- Gemini 會漏數字（「三十秒改成十五秒」→「調整成 15 秒」，三輪皆然）、輸出簡體、session 上限 10 分鐘；partial 最快，若日後要做即時字幕可切換並加 `opencc s2t`。
- gpt-live-transcribe 有英文幻聽（「OAuth 的」→「Oh, after」）、指定 `zh-tw` 仍多簡體、不支援 server VAD（需自己 commit 句尾）。
- 語料為 TTS 合成；真人口音尚未驗證。

## 架構

```
瀏覽器 (Next.js)
 ├─ getUserMedia   → 我的麥克風（echoCancellation）        ┐ 各自切 100ms PCM16
 └─ getDisplayMedia→ Meet 分頁音訊 + 畫面                  ┘ source = "me" | "remote"
        │ WebSocket {audio, source} / {frame}
        ▼
FastAPI LiveSessionManager (api/app/live/session.py)
 ├─ 轉錄連線 me      ─┐ 兩人各自獨立通道、獨立 VAD → 不混音、歸屬不會錯
 ├─ 轉錄連線 remote  ─┘ 逐字稿 ts = 開口時間 (speech_started)
 └─ Reasoner (Responses API)  每句一次：近 12 句 + 最新截圖 + 決策清單 → 工具呼叫
                              session 層守門：無畫面/無指示語不建 anchor；同主題決策合併
        ▼
Recorder (api/app/record/store.py)  write-first、append-only
 data/sessions/{id}/events.jsonl   事件流（source of truth）
 data/sessions/{id}/record.json    aimeet.record.v1 快照（給搜尋 / RAG）
 data/sessions/{id}/record.md      給人看
        ▼  Generate Report
Synthesis (api/app/synthesis/)  luna：extract → coverage → derive(Mermaid/PRD/Work items)
```

設計原則：資訊不能掉、說話者不能錯；逐字稿切幾行不重要（讀取端合併同人連續片段）；
JSON 是唯一真相、MD 是衍生品；原始片段不改寫。

## Run locally

```bash
cp .env.example api/.env   # 填 OPENAI_API_KEY（必要）、GEMINI_API_KEY（STT bench 需要）
make dev-api               # uvicorn --reload --reload-dir app（只監看 app/，測試時不會被 reload 打斷）
make dev-web               # http://localhost:3000
```

API at http://localhost:8000. `GET /health` 應回 `live_provider: openai`。

## 測試

| 指令 | 內容 |
|---|---|
| `cd api && uv run pytest` | 離線單元測試（mock 引擎、Recorder 一致性） |
| `make e2e` / `uv run python -m e2e.run A4 D2` | 對**運行中的 API** 跑實際使用驗收（TTS 模擬兩位說話者 + 合成畫面 → 硬規則 + LLM 裁判），報告在 `api/e2e/results/` |
| `uv run python -m bench.stt` | STT A/B benchmark，結果在 `api/bench/results/` |

驗收標準與已知限制見 `TEST_PLAN.md`。

## Environment variables

- `OPENAI_API_KEY`: 必要
- `GEMINI_API_KEY`: STT bench / Gemini 轉錯層需要
- `OPENAI_TRANSCRIBE_MODEL`: 轉錄模型（default: `gpt-4o-mini-transcribe`）
- `OPENAI_REASONING_MODEL`: 會中推理（default: `gpt-5.4-mini`）
- `OPENAI_MODEL` / `OPENAI_MODEL_COMPLEX`: 會後整理（default: `gpt-5.6-luna`）
- `MOCK_MODE`: `true` 時完全不聽音訊，只重播 `mock_script.json`
- `LIVE_PROVIDER`: `openai` | `mock`（`gemini` 為 legacy 單連線混音架構，不建議）
- `SYNTHESIS_MOCK`: 強制 mock 報告
- `RECORD_DIR`: 紀錄落地目錄（default: `data/sessions`）
