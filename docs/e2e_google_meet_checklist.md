# 第三層驗收：Google Meet 實跑 checklist（人工，須附證據）

三層驗收缺一不可。**只有 mock 綠燈不算 done**：

1. 第一層 Mock/單元（CI 必跑）：`cd api && uv run pytest -q`
2. 第二層 真實 provider 整合：`cd api && OPENAI_API_KEY=... uv run pytest -q -m integration`
3. 第三層 Google Meet E2E：本文件，人工執行並附證據。

## 第二層需要的 fixture

Realtime 測試需要預錄中文音訊與對應畫面，放在 `api/tests/fixtures/realtime/`：

| 檔案 | 內容 | 期待結果 |
| --- | --- | --- |
| `reject_filler.pcm` + `reject_filler.jpg` | 例：「這件事回去再說」 | 不建立事件 |
| `accept_button.pcm` + `accept_button.jpg` | 例：「你看這邊這個按鈕太小」 | 建立事件並跑完 triggered→closed |

音訊格式為 16 kHz mono s16le raw PCM，可用：

```bash
ffmpeg -i recording.m4a -f s16le -acodec pcm_s16le -ar 16000 -ac 1 accept_button.pcm
```

缺 fixture 時測試會 skip；缺 `OPENAI_API_KEY` 時整檔 skip。

## 準備

```bash
cp .env.example api/.env   # 填入 OPENAI_API_KEY，MOCK_MODE=false，LIVE_PROVIDER=openai
make dev-api
make dev-web
```

在 Google Meet 開一場真實會議，分享一個有明顯 UI 元素的畫面（例如設定頁），
在 web app 以「分享螢幕 + 麥克風」開始 session。

## 情境（三個都要錄）

### A. 口頭禪不觸發

- 說：「這件事回去再說」「這個方法昨天討論過」
- 期待：`Grounded Visual Events` 面板沒有新增事件；`data/session_{id}/events.json` 沒有對應紀錄。
- 證據：錄影片段 + 當下的 events.json。

### B. 真實指涉建立事件（含正確截圖與前後文）

- 指著畫面說：「你看這邊這個按鈕太小」，接著繼續討論約 30 秒。
- 期待：
  - 事件先出現 `aggregating`，約 30 秒後轉為 `closed`。
  - `time_range.trigger` 對應說話當下，`start = trigger - 20`，`end = trigger + 30`。
  - `evidence_frame_ids` 對應的截圖確實是說話當下的畫面（不是幾秒前的舊幀）。
  - `context_before` / `context_after` 有抓到前後語句。
- 證據：錄影片段、`data/session_{id}/events.json`、`data/session_{id}/frames/{frame_id}.jpg`。

### C. 可讀的 context 敘述

- 從 closed 事件輸出一段人看得懂的敘述，例如：
  「[08:12] Alice 指著設定頁的 Save 按鈕說『你看這邊這個按鈕太小』；
  前文在討論深色模式的密度設定，後文決定把按鈕改成 40 px。」
- 證據：敘述文字 + 對應截圖。

## 附上的證據清單

- [ ] 三段錄影（A / B / C）
- [ ] `data/session_{id}/events.json`
- [ ] `evidence_frame_ids` 對應的截圖
- [ ] transcript log
