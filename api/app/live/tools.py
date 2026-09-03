from google.genai import types


def _function(
    name: str,
    description: str,
    properties: dict,
    required: list[str],
) -> types.FunctionDeclaration:
    return types.FunctionDeclaration(
        name=name,
        description=description,
        parameters_json_schema={
            "type": "object",
            "properties": properties,
            "required": required,
        },
    )


TOOLS = [
    types.Tool(
        function_declarations=[
            _function(
                "create_anchor",
                "建立語音與最新視覺畫面的語義錨點。",
                {
                    "target": {"type": "string", "description": "被指涉的物件或區域"},
                    "observation": {"type": "string", "description": "對該物件的觀察"},
                    "speaker": {"type": "string", "description": "說話者名稱，可省略"},
                    "confidence": {"type": "number", "description": "0 到 1 的信心度"},
                },
                ["target", "observation", "confidence"],
            ),
            _function(
                "propose_decision",
                "當團隊正在收斂時，提出一個待人確認的決策候選。",
                {
                    "topic": {"type": "string"},
                    "chosen": {"type": "string"},
                    "alternatives": {"type": "array", "items": {"type": "string"}},
                    "reasons_for": {"type": "array", "items": {"type": "string"}},
                    "reasons_against": {"type": "array", "items": {"type": "string"}},
                    "constraints": {"type": "array", "items": {"type": "string"}},
                },
                [
                    "topic",
                    "chosen",
                    "alternatives",
                    "reasons_for",
                    "reasons_against",
                    "constraints",
                ],
            ),
            _function(
                "notify_speaker",
                "建立不打斷發言者的靜默提醒。",
                {
                    "message": {"type": "string"},
                    "kind": {"type": "string", "enum": ["conflict", "slide_mismatch", "info"]},
                },
                ["message", "kind"],
            ),
            _function(
                "capture_context",
                "要求前端立即擷取一張高解析度畫面。",
                {"reason": {"type": "string"}},
                ["reason"],
            ),
        ]
    )
]
