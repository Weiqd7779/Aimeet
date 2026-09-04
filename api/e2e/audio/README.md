# 真人錄音（給 e2e 用）

把錄好的檔案放這裡：`<name>.wav`（16-bit PCM，單/雙聲道、任何取樣率皆可）。
scenario step 用 `"clip": "<name>"` 取代 `"say"`，例如：

```json
{ "at": 1.0, "speaker": "me", "clip": "me_02" }
{ "at": 8.0, "speaker": "remote", "clip": "remote_01", "echo": true }
```

建議錄的句子（用 demo 當天的設備、開喇叭、在會場類似的房間，句尾停 1 秒）：

| 檔名 | 說話者 | 內容 |
|---|---|---|
| me_01 | 主持人 | 今天要決定 Q4 的主打方案，先看一下使用者滿意度。 |
| me_02 | 主持人 | 但是 B 的成本是一千零二十，超過我們八百五的上限。 |
| me_03 | 主持人 | 你看右邊這張表，Prototype C 的滿意度是中等。 |
| me_04 | 主持人 | 那就決定 Q4 採用 Prototype C。 |
| me_05 | 主持人 | 這個 PR 你先開，我下午 review 完就 merge。 |
| remote_01 | 與會者 | 這張圖表顯示 Prototype B 的滿意度最高，測試者都給正面回饋。 |
| remote_02 | 與會者 | 如果外殼改用矽膠包覆，成本可以壓到大概九百二十。 |
| remote_03 | 與會者 | Prototype C 的握感問題還沒解決。 |
| remote_04 | 與會者 | 供應商說兩週內可以交樣品。 |
| remote_05 | 與會者 | Kubernetes 的 pod 一直 OOM，先 rollback 到上一個 image tag。 |
| echo_01 | （回音） | 用另一台裝置播 remote_01，讓筆電喇叭出聲、筆電麥克風錄下 |
| echo_04 | （回音） | 同上，播 remote_04 |

`.wav` 檔不進 git。
