# 實際使用驗收標準（Google Meet 場景）

目的：以「demo 當天會不會出包」為準，而不是程式碼測試是否通過。
自動化：`cd api && uv run python -m e2e.run`（對運行中的 API 用 TTS 模擬兩位說話者 + 合成畫面；
硬規則 + LLM 裁判；報告在 `api/e2e/results/`）。標「自動」的項目每次改動後都要重跑；
標「手測」的項目是瀏覽器授權 / 真人聲音相關，賽前手動驗一次。

## 前置

- `api/.env`：`MOCK_MODE=false`、`LIVE_PROVIDER=openai`，`/health` 回 `live_provider: openai`。
- 兩台裝置或兩個帳號進同一個 Meet；本機瀏覽器開 `http://localhost:3000`。
- 點 **Start Meeting** → 選 Meet **分頁** + 勾 **分享分頁音訊** → 允許麥克風。
- 建議戴耳機；A5 專門測喇叭。

## A. 說話者分離（核心）

| # | 操作 | 通過條件 | 現況 |
|---|------|---------|------|
| A1 | 只有我講 | 每行 speaker 皆為「我」，內容對應 | 自動 PASS |
| A2 | 只有與會者講 | 每行 speaker 皆為「與會者」 | 自動 PASS |
| A3 | 兩人一句一句交替 | 每句歸屬正確、順序正確（依開口時間） | 自動 PASS |
| A4 | 兩人**同時**講 | 各自獨立行、內容不互相混入 | 自動 PASS |
| A5 | 用喇叭、與會者講話 | 不出現內容相同的「我」行（回音） | 手測 |
| A6 | 中英夾雜 | 逐字稿為繁體，不出現簡體 | 自動 PASS |
| A7 | 句中 0.4s 停頓 | 一行 | 自動 PASS |
| A8 | 句中 1s 思考停頓 | 可切行，但同一人、資訊完整、紀錄一致 | 自動 PASS |

## B. 視覺指涉與決策

| # | 操作 | 通過條件 | 現況 |
|---|------|---------|------|
| B1 | 有畫面，與會者說「右邊這塊圖表先不要動」 | grounded event 指向右側圖表、附截圖、speaker=與會者 | 自動 PASS |
| B2 | 「我們決定採用方案 B」 | 一個候選決策，chosen 含方案 B，不重複 | 自動 PASS |
| B3 | 沒有畫面時說「這個」 | **不**產生 grounded event | 自動 PASS |
| B4 | 決策與知識庫衝突（Prototype B 超上限） | conflict alert 含 1,020 > 850 | 自動 PASS |
| B5 | 閒聊 | 無 decision / alert / grounded | 自動 PASS |

## C. 失敗情境要「看得到」

| # | 操作 | 通過條件 | 現況 |
|---|------|---------|------|
| C1 | 未勾「分享分頁音訊」 | 立即 toast 提示 | 已實作，手測 |
| C2 | 拒絕麥克風 | toast 提示，與會者通道仍正常 | 已實作，手測 |
| C3 | 分享「整個螢幕」而非分頁 | 仍能運作 | 手測 |
| C4 | 網路中斷 / OpenAI 錯誤 | 狀態變 Ended 並有 toast | 手測（實測曾遇 OpenAI 端無預警關閉一次） |

## D. 紀錄與報告（資訊不掉）

| # | 操作 | 通過條件 | 現況 |
|---|------|---------|------|
| D1 | 會後 Generate Report | 決策表含會中決策、引用 speaker 正確 | 自動 PASS |
| D2 | **十句混合對話** | 紀錄 = 逐字稿一一對應、無 pending、決策/指涉連回觸發句；順序 10 輪正確；報告 key_facts 含全部 10 個數字/時程/人名/待辦；只有 1 個 grounded、決策不重複 | 自動 PASS |

## 從實測反推已修的問題（時間序）

- 混音 + 能量判斷會把同時說話併成一行 → 每個說話者一條獨立轉錯連線（A4）。
- 轉錄輸出簡體 → 轉錄 prompt + 詞彙表（A6）；STT A/B 後仍維持 gpt-4o-mini-transcribe（唯一原生繁體）。
- 固定毫秒 VAD 不穩健 → `semantic_vad`（A7）；1s 思考停頓仍會切行，改為讀取端合併片段（A8）。
- 時間戳用轉錄完成時間導致順序錯亂 → 用 `speech_started.audio_start_ms` 算開口時間（D2）。
- 同一件事被重複提成多個決策 → session 層 rapidfuzz 合併 + prompt 只在拍板時提案（B2/D2）。
- 報告把「成本壓到 920」補上錯誤主詞 → key_facts 加 `quote`，fact 只能改寫原句（D2）。
- 一個 prompt 要 luna 做七件事 → 拆 extract / coverage / derive 三階段（D1/D2）。
- Realtime 推理連線在只收文字後失去意義 → 換 Responses API 每句無狀態呼叫（B/D 全數回歸）。
- gpt-5.4-mini 有畫面時過度建 anchor → session 守門：無畫面或無指示語不建（B3/D2 grounded_max）。
- 測試 harness 本身的失真：同人音訊交錯、TTS 首尾靜音、句間沒有持續送靜音導致 VAD 不收尾與時間漂移、
  在伺服器落檔前就抓紀錄 → 全部修正，避免把 harness 問題誤判成產品問題。

## 已知限制

- 語料為 TTS 合成；真人口音、喇叭回音（A5）、C 類情境需手測。
- STT 同音錯字（握感→握趕、C→第一）仍會發生；報告層靠上下文修正，不保證。
- Gemini legacy 引擎（`LIVE_PROVIDER=gemini`）未跟上雙通道架構，不建議使用。
