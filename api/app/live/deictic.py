"""Words that mean the speaker is pointing at something on screen / in front of the camera.

Shared by the reasoner (forces the vision step) and the session (hard gate for anchors).
"""

import re

DEICTIC = re.compile(
    # pointing words
    r"這個|那個|這裡|那裡|這邊|那邊|右邊|左邊|上面|下面|這塊|那塊|這張|那張|這頁|那頁|這行|那行"
    # talking about what is on screen
    r"|螢幕|畫面|上一頁|下一頁|投影片|簡報|圖表|表格|這張圖|這個圖|柱狀圖|折線圖|截圖"
    # English: only when the pointer is attached to a screen noun, so "this is fine" never fires
    r"|\b(?:this|that|the)\s+(?:one|chart|table|slide|page|graph|diagram|row|column|number|screen)\b"
    r"|\bon\s+(?:the\s+)?screen\b|\b(?:over|right)\s+here\b",
    re.IGNORECASE,
)
