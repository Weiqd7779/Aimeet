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
 ├─ EchoFilter (live/echo.py)  開喇叭時與會者的話從麥克風漏回：me 句與 4s 內 remote 句相似即丟棄
 ├─ 每 2 秒一張截圖 + 聽到指示語加拍一張 → 全部落地、伺服器時鐘蓋 ts（拍了不代表會用）
 └─ Reasoner (Responses API)  每句轉錄完成後兩步（不追即時）：
      A 聽：純文字，近 12 句 + 決策/錨點狀態 → 決策/提醒；有指涉就叫 look_at_screen(物件名)
      B 看：只在 A 要求時，撈「開口→收口」區間內的截圖（最多 3 張，找不到往前 10s 再找）
           → create_anchor(frame_index) 或 not_visible
      session 層守門：anchor 要視覺信心 ≥0.6，且（除非信心 ≥0.8）句子要有指示語 + 是完整句；
      同物件 15s 內更新不新增；決策要有拍板詞；同主題合併、理由語意去重
 └─ ConsistencyAgent (app/consistency.py)  與 Reasoner 平行、每句一次（只在句子含時間詞或指派詞時叫模型）：
      維護「承諾帳本」（事／人／時間），最新一句和帳本矛盾 → Inconsistency（time | assignee）
      明講「改成／更正／延到」= 更新不算衝突；問句／確認句不算
      → Alert(kind=inconsistency, detail=「事：X｜人：Y｜時間：A → B」, evidence=[先前原話, 現在原話])
      → app/tts.py 呼叫 ElevenLabs（eleven_v3、自製聲音 IVY）合成口語提醒 → WS `speech` 事件（mp3 base64）
      靜默提醒 = 只有這種（ALERTS_INCONSISTENCY_ONLY=true）；知識庫衝突 / 投影片提醒仍記錄但不顯示
        ▼
Recorder (api/app/record/store.py)  write-first、append-only
 data/sessions/{id}/events.jsonl   事件流（source of truth）
 data/sessions/{id}/record.json    aimeet.record.v1 快照（給搜尋 / RAG）
 data/sessions/{id}/record.md      給人看
 data/sessions/{id}/frames/*.jpg   每張截圖落地
 data/sessions/{id}/report.json    會後報告
 SceneTracker (record/scenes.py)   截圖 dHash 分「頁」；每句記 scene_id (+ 邊界 ±4s 的 adjacent)
        ▼  Generate Report（API 重啟後 sessions 從硬碟重建）
Synthesis (api/app/synthesis/)  luna：extract → coverage → derive(Mermaid/PRD/Work items) ∥ scene index
                                輸入含 pages（依頁重排的內容，邊界句列在兩頁）；輸出含每頁 title/summary
```

設計原則：資訊不能掉、說話者不能錯；逐字稿切幾行不重要（讀取端合併同人連續片段）；
JSON 是唯一真相、MD 是衍生品；原始片段不改寫。

兩層畫面連結：**scene（頁）** 每句都有、不需要有人指東西、容許翻頁前後幾秒重疊 → 回答「講成本那頁在講什麼」；
**anchor** 只在有人指畫面（「右邊這張表」）時建立 → 回答「他說的『那個』是什麼」。
模型的 confidence 不能當 anchor 放行條件（實測十句對話會出 12 個），指示語是硬條件。

**時間對齊是 grounding 的核心**：語音的開口/收口（`speech_started/stopped.audio_*_ms`）與截圖都在伺服器時鐘上；
「這個是貓咪杯子」的逐字稿晚 8 秒才到，但系統會回頭撈開口當下的那幾張圖，讓視覺去找語音講的那個名字
（「指甲剪」），而不是拿最新一張圖硬猜。實機錄音重放：`uv run python -m e2e.replay <session_id>`。

## Run locally

需求：Python 3.12+、Node.js 20+、Chrome/Edge（getDisplayMedia）；`uv` 由 setup 自動安裝。

macOS / Linux：

```bash
git clone https://github.com/Weiqd7779/Aimeet.git
cd Aimeet
make dev          # 自動跑 setup.sh（裝依賴、建 api/.env）後同時起 api 與 web
make setup        # 只裝依賴不啟動
```

Windows PowerShell：

```powershell
git clone https://github.com/Weiqd7779/Aimeet.git; cd Aimeet
Copy-Item .env.example api\.env   # 填 OPENAI_API_KEY（必要）、ELEVENLABS_API_KEY（要語音提醒才需要）
                                  # 並把 MOCK_MODE 改成 false、LIVE_PROVIDER=openai
cd api; uv sync; cd ..            # 依 uv.lock 建 .venv
cd web; npm ci; cd ..             # 依 package-lock.json
.\dev.ps1                         # 一鍵：殺掉舊的 → 開兩個視窗跑 API(:8000) + Web(:3000)
.\dev.ps1 -Stop                   # 全部停掉
make dev-api / make dev-web       # 單獨啟動（各自的 dev.ps1）；make restart 只殺不起
```

`make dev` 會啟動 API（http://localhost:8000）與 web app（http://localhost:3000）。
只想裝依賴不啟動時跑 `make setup`（等同 `./setup.sh`，可重複執行）；
想分開兩個 terminal 跑就用 `make dev-api` 與 `make dev-web`。

- 離線 demo：不需要任何 key，直接在頁面按 **Mock Demo**。
- 真實模式：編輯 `api/.env`，填 `OPENAI_API_KEY=...`，設 `MOCK_MODE=false`、`LIVE_PROVIDER=openai`，
  重啟 API 後按一般「開始」。

### 用 Google Meet 測試

1. 另開分頁進入 Google Meet 會議，回到 web app 按「開始」。
2. Chrome 的分享視窗選 **該 Meet 分頁**，並勾選 **「同時分享分頁音訊」**——
   音訊來自分頁而非本機麥克風，所以觸發語句要由會議中的**其他參與者／另一台裝置**說出。
3. 想快點看到事件 `closed`，在 `api/.env` 加 `CONTEXT_AFTER_SECONDS=5`。
4. 證據會寫到 `api/data/session_{id}/events.json` 與 `api/data/session_{id}/frames/*.jpg`。

完整人工驗收步驟見 [`docs/e2e_google_meet_checklist.md`](docs/e2e_google_meet_checklist.md)。

**沒有 OPENAI_API_KEY 也能看 UI**：保留 `MOCK_MODE=true`，開始會議後會重播 `api/app/live/mock_script.json`。
沒有 `ELEVENLABS_API_KEY` 時提醒卡片照出，只是不出聲。

**Windows 上不要直接跑 `uvicorn` / `next dev`。** 只殺 reloader 父進程會留下 worker 繼續佔 port；
新起的 server 綁得上但連線全被孤兒接走，跑的是它當初載入的舊程式碼。我們曾因此對著一個 20 分鐘前的
worker debug「prompt 修了怎麼還洩漏」。`dev.ps1` 啟動前清、Ctrl+C 後再清一次。

API at http://localhost:8000. `GET /health` 應回 `live_provider: openai`。

## 測試

| 指令 | 內容 |
|---|---|
| `cd api && uv run pytest` | 離線單元測試（mock 引擎、Recorder 一致性、衝突 agent 規則、錨定門檻） |
| `make e2e` / `uv run python -m e2e.run A4 D2` | 對**運行中的 API** 跑實際使用驗收（TTS 模擬兩位說話者 + 合成畫面 + 合成喇叭回音 → 硬規則 + LLM 裁判），報告在 `api/e2e/results/` |
| `uv run python -m e2e.run B6` | 前後矛盾情境：需 `ELEVENLABS_API_KEY`；驗證 inconsistency 提醒 + 語音真的有合成，mp3 存到 `api/e2e/results/speech/` 可直接聽 |
| `uv run python -m e2e.calibrate` | 裁判校準：故意弄壞（speaker 對調 / 少數字 / 少一句）必須被判 FAIL |
| `uv run python -m bench.stt` | STT A/B benchmark，結果在 `api/bench/results/` |

真人錄音：放到 `api/e2e/audio/<name>.wav`（16-bit PCM，任何取樣率），scenario step 用 `"clip": "<name>"` 取代 `say`。

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
- `DATA_DIR`: Directory for persisted GroundedVisualEvents and evidence frames (default: `data`)
- `CONTEXT_BEFORE_SECONDS` / `CONTEXT_AFTER_SECONDS`: Context window around a trigger (default: `20` / `30`)
- `BUFFER_SECONDS`: In-memory transcript/frame ring buffer window (default: `60`)
- `ELEVENLABS_API_KEY`: 語音提醒；空白則只有卡片不出聲
- `ELEVENLABS_VOICE_ID`: 聲音（default: `1ulrCnnL9y7FtQmCz2nP` = 自製 clone「IVY」；`GET /v1/voices` 可列出帳號內所有聲音）
- `ELEVENLABS_MODEL`: `eleven_v3`（支援 `[clears throat]` 等 audio tags、最像人、約 6–9s 延遲）或 `eleven_flash_v2_5`（<1s、1.15x 語速、tags 會自動拿掉）
- `ALERTS_INCONSISTENCY_ONLY`: `true`（default）靜默提醒只保留時間／負責人不一致；`false` 恢復知識庫衝突與投影片提醒
- `CONSISTENCY_ENABLED`: `false` 可整個關掉衝突 agent

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
