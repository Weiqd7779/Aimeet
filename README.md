# AIMEET 艾咪 — 會議脈絡驗證 Agent

> 艾咪不是取代你的會議工具，而是驗證會議中發生的事情。

---

## 摘要與背景

> **54%** 的人離開會議時，仍不知道下一步是什麼，或任務到底由誰負責。  
> — *Atlassian, 2024*

> **93%** 的「哪一個／在哪裡」回答都伴隨著指向手勢——但今天的會議紀錄，只記得你說了什麼。  
> — *University of Chicago, Frontiers in Communication*

AIMEET 將語音、手勢、視覺情境與會議記憶整合在一起，不只理解「說了什麼」，更理解「實際指的是什麼、誰要負責什麼」。  
當負責人、截止日期或決策內容與先前討論發生衝突時，AIMEET 會在錯誤被寫進待辦事項之前主動偵測並即時提醒。

---

## 為什麼需要 AIMEET？

### 核心痛點
1. **會議脈絡容易遺失**：像「這個交給 Amy」這類語句，傳統逐字稿無法辨識「這個」實際對應到畫面上的哪一個白板內容、架構物件或介面流程。
2. **決策衝突被直接記錄成錯誤待辦**：當負責人、截止日期或決策內容前後矛盾時，現有工具多半只負責被動記錄與摘要，缺乏會中的即時比對與驗證機制。

### 解決方案
1. **多模態脈絡綁定 (Visual Grounding)**：結合雙軌語音與伺服器端畫面時間對齊，精確解析「誰說了什麼、指了什麼、誰要負責什麼」。
2. **即時決策驗證 (Consistency Agent)**：主動偵測衝突，並透過語音與介面在錯誤成為定案前即時提醒。

---

## 使用場景與功能展示
 
**場景**：線上產品會議。主持人一邊分享畫面、一邊拿起實體原型講解陸續補充時程與分工。
 
Aimeet 掛在會議旁邊：
 
| 在會議裡… | Aimeet 當下… |
|---|---|
| 拿出一顆白綠色小球說：「這個……我們最新的產品，寶寶球」 | 從鏡頭畫面即時認出手上拿的實體物體，自動**截圖 + 辨識特徵 + 綁定上下文**，在左側生成一張「01 · 會議焦點物件」卡（`鏡頭前方、左手拿著的白綠色小圓形物件`）。 |
| 先說「原型主要由 **Ivy** 負責，星期五以前交最終定稿」；會議尾聲又說「提醒一下 **Jack**，寶寶球最終定稿星期五以前交給我」 | 立即抓到前後負責人矛盾，啟動 AI 語音助理 IVY 即時插話提醒：<br>「**嗯，提醒一下，寶寶球原型定稿剛才是 Ivy 負責，現在聽到的是 Jack。要不要確認一下最後由誰負責？**」 |
| 立刻反應澄清說：「**喔抱歉！是 Ivy，剛剛口誤了**」 | 理解發言者的口誤修正，自動確認最終責任歸屬，不產生誤判與干擾。 |
| 會議進行與結束（點擊「**產生報告**」） | 將會議中的視覺實體焦點（寶寶球截圖與脈絡）、負責人決策修正歷程（Ivy / Jack）、逐字稿一併結構化彙整為正式會議結論、待辦事項與報告。 |

## 系統架構

```mermaid
flowchart LR
  subgraph IN["輸入（瀏覽器）"]
    A["🎙 我的麥克風"]
    B["🖥 會議分頁<br/>聲音 + 畫面"]
  end

  subgraph CORE["後端核心（FastAPI）"]
    STT["兩路獨立轉錄<br/>我 / 與會者 "]
    subgraph AGENTS["兩個 Agent，各管一件事"]
      R["Agent 1 · 統整決策、物件"]
      C["Agent 2 · 抓衝突時間 / 負責人矛盾"]
    end
    REC["會議紀錄<br/>逐字稿 · 截圖 · 事件<br/>"]
  end

  subgraph OUT["輸出"]
    UI["即時畫面<br/>焦點物件 · AI 統整"]
    VOICE["🔊 語音提醒<br/>ElevenLabs · IVY"]
    REP["會後報告<br/>決策表 · PRD · 待辦"]
  end

  A --> STT
  B --> STT
  STT --> R
  STT --> C
  B -- 截圖 --> R
  R --> UI
  C --> UI
  C --> VOICE
  R --> REC
  C --> REC
  STT --> REC
  REC --> REP
```
## 使用技術

| 類型 | 技術／服務 | 用途 |
| --- | --- | --- |
| AI 模型 | OpenAI `gpt-4o-mini-transcribe` | 即時語音轉錄 (STT)，原生繁體中文識別與低錯誤率 |
| AI 模型 | OpenAI `gpt-5.4-mini` (Responses API) | 會中即時推理、工具呼叫與視覺指涉判定 |
| AI 模型 | OpenAI `gpt-5.6-luna` | 會後多階段資訊萃取、覆蓋率檢查與報告合成 |
| AI 模型 | ElevenLabs (`eleven_v3` / IVY) | 會中即時口語衝突提醒語音合成 (TTS) |
| 前端 | Next.js 14, React, TypeScript, Tailwind CSS | 即時會議介面、音訊雙軌擷取 (`getUserMedia` / `getDisplayMedia`) |
| 後端 | Python 3.11+, FastAPI, WebSockets, uv | 雙軌音訊串流管理、回音過濾 (EchoFilter)、事件流持久化 |

---
## 安裝與執行
 
### 需求
- Windows 10/11（啟動腳本是 PowerShell；macOS / Linux 見下方手動啟動）
- Python 3.11+ 與 [uv](https://docs.astral.sh/uv/)
- Node.js 20+
- Chrome 或 Edge（需要 `getDisplayMedia` 分享畫面 + 分頁音訊）
- OpenAI API key（必要）；ElevenLabs API key（要語音提醒才需要）
 
### 安裝
 
```powershell
git clone https://github.com/Weiqd7779/Aimeet.git
cd Aimeet
cd api;  uv sync;  cd ..      # 依 uv.lock 建立 .venv
cd web;  npm ci;   cd ..      # 依 package-lock.json 安裝
Copy-Item .env.example api\.env
```
### 編輯 api\.env
```ini
OPENAI_API_KEY=sk-...
MOCK_MODE=false
LIVE_PROVIDER=openai
ELEVENLABS_API_KEY=sk_...     # 可留空：提醒卡片照出，只是不出聲
```
### 執行
```powershell
.\dev.ps1          # 啟動 / 重啟：清掉舊程序後開兩個視窗 → API :8000、Web :3000
.\dev.ps1 -Stop    # 全部停掉
```
打開 http://localhost:3000 → 開始會議 → 選要分享的分頁（勾「分享分頁音訊」）→ 允許麥克風。 http://localhost:8000/health 應回 {"status":"ok","live_provider":"openai"}。

### macOS / Linux

```bash
git clone https://github.com/Weiqd7779/Aimeet.git
cd Aimeet
make dev          # 自動跑 setup.sh（裝依賴、建 api/.env）後同時起 api 與 web
make setup        # 只裝依賴不啟動
make dev-api / make dev-web   # 分開兩個 terminal 跑；make restart 只殺不起
```

**Windows 上不要直接跑 `uvicorn` / `next dev`。** 只殺 reloader 父進程會留下 worker 繼續佔 port；
新起的 server 綁得上但連線全被孤兒接走，跑的是它當初載入的舊程式碼。`dev.ps1` 啟動前清、Ctrl+C 後再清一次。

**沒有 OPENAI_API_KEY 也能看 UI**：保留 `MOCK_MODE=true`，開始會議後會重播 `api/app/live/mock_script.json`。
沒有 `ELEVENLABS_API_KEY` 時提醒卡片照出，只是不出聲。

### 用 Google Meet 測試

1. 另開分頁進入 Google Meet 會議，回到 web app 按「開始」。
2. Chrome 的分享視窗選 **該 Meet 分頁**，並勾選 **「同時分享分頁音訊」**——
   分頁音訊來自會議而非本機麥克風，所以觸發語句要由會議中的**其他參與者／另一台裝置**說出。
3. 想快點看到事件 `closed`，在 `api/.env` 加 `CONTEXT_AFTER_SECONDS=5`。
4. 證據會寫到 `api/data/session_{id}/events.json` 與 `api/data/session_{id}/frames/*.jpg`；
   完整人工驗收步驟見 [`docs/e2e_google_meet_checklist.md`](docs/e2e_google_meet_checklist.md)。

### 環境變數（`api/.env`）

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

## 作品展示

- 作品展示網址（選填）：
- 評選影片：https://youtu.be/27ZzpMc-uB0

## 限制與未來工作

| 面向 | 限制 | 現況處理 |
|---|---|---|
| 提醒延遲 | 從說出矛盾到聽見語音約 8–12 秒 | 可換 `eleven_flash_v2_5`（<1 秒）但失去語氣標記 |
| 衝突範圍 | 只抓「時間」與「負責人」兩種矛盾；金額、規格、範圍變更不在本版 | 帳本結構已預留 `task` 欄位可擴充 |
| 說話者 | 只有兩路：「我」與「與會者」。遠端多人會全部歸為「與會者」，無法分辨誰說的 | 兩路獨立轉錄保證「我 / 對方」不會錯 |
| 相對日期 | 「下星期三」換算成日期依會議當天推算，跨週／口誤時可能算錯 | 報告會把無法對回逐字稿的日期列進「不確定事項」 |
| 回音 | 開喇叭時與會者聲音漏回麥克風，靠文字相似度在 4 秒內去重，非聲學消除 | 建議 demo 戴耳機 |
| 平台 | 啟動腳本為 Windows PowerShell；macOS / Linux 需手動起 uvicorn 與 next | README 附手動指令 |
| 儲存 | 檔案系統落地，無資料庫、無使用者、無權限；多場會議只靠資料夾隔離 | 事實資料已使用結構化 json 儲存，可日後匯入資料庫 |

### 後續發展方向
1. **更多矛盾類型**：金額、數量、規格、範圍（「先做 A」→「先做 B」），以及跨會議的矛盾（今天說的和上週決議不同）
2. **說話者分離**：遠端多人時用聲紋或會議平台 API 取得參與者名稱，帳本的「人」就能對到真人
3. **持久化與多租戶**：record.json 匯入 Postgres + 向量索引，做跨會議搜尋與 RAG

## 第三方服務、資料與素材
 
### 外部服務（需自備帳號與金鑰）
 
| 服務 | 用途 | 連結 | 授權 / 條款 |
|---|---|---|---|
| OpenAI API — `gpt-4o-mini-transcribe` | 即時語音轉文字（兩路獨立） | https://platform.openai.com/docs/guides/realtime-transcription | [OpenAI Terms of Use](https://openai.com/policies/terms-of-use)、[Usage Policies](https://openai.com/policies/usage-policies)；按量計費 |
| OpenAI API — `gpt-5.4-mini` | 會中推理（決策、指涉、視覺定位） | https://platform.openai.com/docs/api-reference/responses | 同上 |
| OpenAI API — `gpt-5.6-luna` | 抓衝突判斷、會後報告整理 | 同上 | 同上 |
| OpenAI API — `gpt-4o-mini-tts` | 僅 e2e 測試：合成兩位模擬說話者 | https://platform.openai.com/docs/guides/text-to-speech | 同上 |
| ElevenLabs API — `eleven_v3` | 提醒語音合成 | https://elevenlabs.io/docs/api-reference/text-to-speech/convert | [ElevenLabs Terms of Service](https://elevenlabs.io/terms-of-use)；按字元計費 |
| ElevenLabs — 聲音「IVY」 | 提醒使用的聲音 | 帳號內 Instant Voice Clone | 由本專案成員以**本人聲音**建立，僅供本專案使用；不對外散布聲音模型 |
| Google Gemini API | 僅 STT A/B benchmark（`bench/`），主流程未使用 | https://ai.google.dev/gemini-api/docs | [Gemini API Terms](https://ai.google.dev/gemini-api/terms) |

，專案未使用任何外部圖片、音樂、資料集或第三方文字內容。

## 團隊成員

| 姓名 | 分工 |
| Mumu | 程式開發、撰寫文稿 |
| Ivy | 程式開發、製作簡報 |

## License

請在儲存庫根目錄加入明確的 `LICENSE` 檔案，並在此標示授權名稱。
