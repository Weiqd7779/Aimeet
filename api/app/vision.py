import logging
import re

from openai import AsyncOpenAI
from pydantic import BaseModel

from app.config import settings

logger = logging.getLogger(__name__)


class VisionVerdict(BaseModel):
    is_grounded_visual_reference: bool
    confidence: float
    reason: str


DEICTIC_PATTERN = re.compile(
    r"這個|這邊|這裡|這張|這塊|這條|那個|那邊|那裡|那張|右邊|左邊|上面|下面|"
    r"\b(?:this|that|here|there)\b",
    re.IGNORECASE,
)
FILLER_PATTERN = re.compile(
    r"回去再說|再說吧|等一下再|之後再|昨天|上次|上週|上禮拜|剛剛講過|討論過|提過|先跳過"
)

INSTRUCTIONS = """你是視覺指涉判定器。判斷這句話是否真的在指涉「當下正在展示的畫面內容」，
也就是聽者必須看到畫面才能理解這句話。

判為 true 的例子：「你看這邊這個按鈕太小」「你看右邊這張圖的色階怪怪的」。
判為 false 的例子：「這件事回去再說」「這個方法昨天討論過」——
指示詞只是口頭禪或指涉抽象事物、過去的討論，不需要畫面即可理解。

只輸出 JSON。"""


def _prompt(trigger_text: str, context: list[str]) -> str:
    joined = "\n".join(context) if context else "(無)"
    return f"觸發語句：{trigger_text}\n最近語境：\n{joined}"


def heuristic_verdict(trigger_text: str, context: list[str]) -> VisionVerdict:
    del context
    if FILLER_PATTERN.search(trigger_text):
        return VisionVerdict(
            is_grounded_visual_reference=False,
            confidence=0.8,
            reason="指示詞屬於口頭禪或指涉過去討論，不需要畫面即可理解。",
        )
    if DEICTIC_PATTERN.search(trigger_text):
        return VisionVerdict(
            is_grounded_visual_reference=True,
            confidence=0.7,
            reason="語句包含指向當下畫面的指示語。",
        )
    return VisionVerdict(
        is_grounded_visual_reference=False,
        confidence=0.5,
        reason="語句沒有指向畫面的指示語。",
    )


async def _verify_with_openai(
    trigger_text: str,
    context: list[str],
    jpeg_b64: str | None,
) -> VisionVerdict | None:
    content: list[dict[str, str]] = [{"type": "input_text", "text": _prompt(trigger_text, context)}]
    if jpeg_b64:
        content.append({"type": "input_image", "image_url": f"data:image/jpeg;base64,{jpeg_b64}"})
    response = await AsyncOpenAI(api_key=settings.openai_api_key).responses.parse(
        model=settings.openai_model,
        instructions=INSTRUCTIONS,
        input=[{"role": "user", "content": content}],
        text_format=VisionVerdict,
    )
    return response.output_parsed


async def verify_visual_reference(
    trigger_text: str,
    context: list[str],
    jpeg_b64: str | None,
) -> VisionVerdict:
    if settings.mock_mode or settings.live_provider == "mock" or not settings.openai_api_key:
        return heuristic_verdict(trigger_text, context)
    try:
        verdict = await _verify_with_openai(trigger_text, context, jpeg_b64)
    except Exception:
        logger.exception("Vision verification failed")
        return heuristic_verdict(trigger_text, context)
    if verdict is None:
        return heuristic_verdict(trigger_text, context)
    return verdict
