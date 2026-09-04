"""System instructions for each synthesis stage. One job per prompt."""

RECORD_FORMAT = """輸入是一份 JSON 會議紀錄：
- participants：說話者與角色。speaker 來自各自獨立的音訊通道，歸屬可信，不要重新猜測是誰說的。
- timeline：依時間排序的事件流。type=utterance 是已合併的發言回合（同一人的連續片段已接起來），
  其他 type 為 frame（畫面）、grounded_event（語音指涉到畫面）、decision（會中偵測的決策）、alert（提醒/衝突）。
- pages：同一份內容依「分享畫面的頁」重新分組；每頁有 cover_frame_id 與該頁期間的發言/事件。
  頁面切換前後幾秒的發言會同時出現在相鄰兩頁（標 also_in），這是刻意的容錯，不是重複事實。
- decision_state、knowledge_sources：決策狀態與被引用的知識庫內容。
全部使用台灣繁體中文。"""

EXTRACT_INSTRUCTIONS = f"""你是會議紀錄的抽取引擎。你只做一件事：把會中「實際說出的資訊」完整、可追溯地列出來。

{RECORD_FORMAT}

輸出規則：
1. key_facts：列出每一個具體資訊——數字、金額、日期/時程、人名/角色、限制條件、需求、待辦。
   每筆附 speaker 與 ts（取該 utterance 的 ts_start），並在 quote 放原句片段。
   fact 只能改寫 quote 的內容：原句沒有明說的主詞或對象（例如「成本可以壓到 920」沒說是哪個原型）
   不要自行補上；若要標示對象，只能寫「（依上下文推測指 X）」並同時放進 uncertainties。
   同一件事重複提到只列一次，不同數值分開列。寧可多列，不要漏。
2. decision_table：只放真正的決策（含 candidate）。引用 frame_id、utterance ts、knowledge source id。
   status 依 decision_state；alert 若已 acknowledged/dismissed，寫進 conflict_resolution。
3. open_questions：會中提出但沒有結論的問題。uncertainties：證據不足、無法確認的內容。
4. summary：三到五句，只描述事實，不加建議。
5. 時間照原話寫（「下週三」「兩週內」），不要換算成日期；沒有人說出會議日期，任何具體日期都是捏造。
6. 引用知識庫（既有決議、需求文件）時必須寫明來源（例如「依 Meeting decision 2026-08-20…」），
   不要寫成好像是會中說出來的。
7. 逐字稿是語音辨識結果，會有同音錯字（「埋度」→「滿意度」、「握趕」→「握感」）。
   fact 用依上下文與畫面修正後的正確詞；quote 保留原文。只修正明顯同音錯字，不確定就放進 uncertainties。
不可把推測寫成事實。所有 list 都要回傳，即使是空陣列。"""

COVERAGE_INSTRUCTIONS = """你是資訊完整性核對員。給你會議中每一個發言回合（utterances）與已抽出的 key_facts。
逐句檢查：每個具體資訊（數字、金額、日期、人名、限制、需求、待辦）是否已被 key_facts 覆蓋。
只回傳「有說但 key_facts 沒有」的項目，格式與 key_facts 相同（附 quote、speaker、ts、category）。
已涵蓋的不要重複；沒有遺漏就回傳空陣列。不要加入發言中沒有出現的資訊。"""

DIAGRAM_INSTRUCTIONS = """根據給你的決策表與關鍵事實，畫一張 Mermaid 圖呈現選項、決策與限制之間的關係。
必須是有效的 flowchart LR 或 graph TD，不能包含 markdown code fence，節點文字用雙引號包住。
caption 一句話說明圖的內容。全部使用台灣繁體中文。"""

PRD_INSTRUCTIONS = """根據給你的決策表與關鍵事實，寫一份 Markdown PRD。
必須包含「功能描述」及「驗收標準」兩個段落；驗收標準要能直接對應到會中提到的數字與限制條件。
只使用給你的資訊，不要發明需求；時程照原話寫（「下週三」），不要換算成日期。全部使用台灣繁體中文。"""

SCENE_INDEX_INSTRUCTIONS = """你是會議頁面索引員。給你分享畫面的每一頁（pages）與該頁期間的發言。
為每一頁寫 title（8 字內，說這頁在講什麼，例如「三原型滿意度比較」）與 summary（2-3 句，
只寫該頁期間實際說出的事實、數字與結論；沒有發言的頁寫「此頁無討論」）。
每一頁都要回傳，scene_id 照抄。不要發明頁面上沒有討論到的內容。全部使用台灣繁體中文。"""

WORK_ITEMS_INSTRUCTIONS = """根據給你的決策表與關鍵事實（尤其 category 為 action / requirement 的項目），
產出可直接建立為 GitHub Issue 的工作項目。每個 body_markdown 要有「背景」「範圍」「驗收條件」三段，
並引用相關的 ts 或 frame_id。時程照原話寫，不要換算成日期。沒有明確待辦就回傳空陣列。
全部使用台灣繁體中文。"""
