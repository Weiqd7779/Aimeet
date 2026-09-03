from google.genai import types

TOOL_DEFINITIONS: list[dict] = [
    {
        "name": "create_anchor",
        "description": "建立語音與最新視覺畫面的語義錨點。",
        "parameters": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "被指涉的物件或區域"},
                "observation": {"type": "string", "description": "對該物件的觀察"},
                "speaker": {"type": "string", "description": "說話者名稱，可省略"},
                "confidence": {"type": "number", "description": "0 到 1 的信心度"},
            },
            "required": ["target", "observation", "confidence"],
        },
    },
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
                for tool in TOOL_DEFINITIONS
            ]
        )
    ]


def openai_tools() -> list[dict]:
    return [{"type": "function", **tool} for tool in TOOL_DEFINITIONS]


TOOLS = gemini_tools()
