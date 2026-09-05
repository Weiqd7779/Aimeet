from google.genai import types

LOOK_TOOL_DEFINITIONS: list[dict] = [
    {
        "name": "look_at_screen",
        "description": (
            "發言者正在指畫面上的某個東西（這個、那個、右邊這張表、鏡頭前的樣品…）。"
            "先判斷他指的是「已錨定清單」裡的哪一個，還是新的東西；再說出這句話對它講了什麼。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "object": {
                    "type": "string",
                    "description": "用說話者自己的稱呼（例如「指甲剪」「貓咪杯子」「右邊的長條圖」）；不知道名稱就寫「手上拿的東西」",
                },
                "refers_to": {
                    "type": ["string", "null"],
                    "description": "若指的就是已錨定清單中的某一個，填該 anchor 的 id；新的東西填 null。"
                    "接著上一句繼續講同一個東西（「這個東西之後會推出」）通常是同一個；"
                    "說「另一個」「這兩個」「換一個」才是新的。",
                },
                "about": {
                    "type": "string",
                    "description": "這句話對該物件說了什麼有用資訊（用途、定位、日期、數字、問題）。"
                    "只寫這句新增的，沒有就填空字串。",
                },
            },
            "required": ["object", "refers_to", "about"],
        },
    },
]

VISION_TOOL_DEFINITIONS: list[dict] = [
    {
        "name": "create_anchor",
        "description": (
            "把發言中的指涉（這個、右邊那張…）連到畫面上實際看得到的物件或區域。"
            "只有在某張畫面確實出現說話者所指／所稱的東西時才呼叫。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "被指涉的物件：先用說話者自己的稱呼（例如「指甲剪」「貓咪杯子」），再加位置",
                },
                "observation": {
                    "type": "string",
                    "description": "畫面中實際看到的細節（顏色、形狀、文字）",
                },
                "frame_index": {
                    "type": "integer",
                    "description": "哪一張候選畫面看得到該物件（從 1 開始，對應輸入中的「畫面 N」）",
                },
                "speaker": {"type": "string", "description": "說話者名稱，可省略"},
                "confidence": {
                    "type": "number",
                    "description": "0 到 1；看不清楚或畫面沒有該物件時應低於 0.5",
                },
            },
            "required": ["target", "observation", "frame_index", "confidence"],
        },
    },
    {
        "name": "not_visible",
        "description": "每一張畫面都看不到說話者所指的東西。",
        "parameters": {
            "type": "object",
            "properties": {"why": {"type": "string", "description": "簡短說明畫面裡有什麼"}},
            "required": ["why"],
        },
    },
]

TOOL_DEFINITIONS: list[dict] = [
    *LOOK_TOOL_DEFINITIONS,
    {
        "name": "propose_decision",
        "description": "當團隊正在收斂時，提出一個待人確認的決策候選。",
        "parameters": {
            "type": "object",
            "properties": {
                "topic": {"type": "string"},
                "chosen": {"type": "string"},
                "alternatives": {"type": "array", "items": {"type": "string"}},
                "reasons_for": {"type": "array", "items": {"type": "string"}},
                "reasons_against": {"type": "array", "items": {"type": "string"}},
                "constraints": {"type": "array", "items": {"type": "string"}},
            },
            "required": [
                "topic",
                "chosen",
                "alternatives",
                "reasons_for",
                "reasons_against",
                "constraints",
            ],
        },
    },
    {
        "name": "notify_speaker",
        "description": "建立不打斷發言者的靜默提醒。",
        "parameters": {
            "type": "object",
            "properties": {
                "message": {"type": "string"},
                "kind": {"type": "string", "enum": ["conflict", "slide_mismatch", "info"]},
            },
            "required": ["message", "kind"],
        },
    },
    {
        "name": "capture_context",
        "description": "要求前端立即擷取一張高解析度畫面。",
        "parameters": {
            "type": "object",
            "properties": {"reason": {"type": "string"}},
            "required": ["reason"],
        },
    },
]


def gemini_tools() -> list[types.Tool]:
    return [
        types.Tool(
            function_declarations=[
                types.FunctionDeclaration(
                    name=tool["name"],
                    description=tool["description"],
                    parameters_json_schema=tool["parameters"],
                )
                for tool in [*TOOL_DEFINITIONS, *VISION_TOOL_DEFINITIONS]
            ]
        )
    ]


def openai_tools() -> list[dict]:
    """Step A (listen): decisions, alerts, capture requests, and 'go look at X'."""
    return [{"type": "function", **tool} for tool in TOOL_DEFINITIONS]


def look_tools() -> list[dict]:
    """Step B (look): report where X is in a frame, or that it is not visible."""
    return [{"type": "function", **tool} for tool in VISION_TOOL_DEFINITIONS]


TOOLS = gemini_tools()
