from app.live.tools import (
    TOOL_DEFINITIONS,
    VISION_TOOL_DEFINITIONS,
    gemini_tools,
    look_tools,
    openai_tools,
)


def test_listen_and_look_tool_sets_are_split() -> None:
    listen = {tool["name"] for tool in openai_tools()}
    look = {tool["name"] for tool in look_tools()}
    assert listen == {"look_at_screen", "propose_decision", "notify_speaker", "capture_context"}
    assert look == {"create_anchor", "not_visible"}
    # step A never anchors directly: it has not seen a frame
    assert "create_anchor" not in listen


def test_gemini_gets_every_tool() -> None:
    expected = {tool["name"] for tool in [*TOOL_DEFINITIONS, *VISION_TOOL_DEFINITIONS]}
    gemini_names = {
        declaration.name
        for tool in gemini_tools()
        for declaration in tool.function_declarations or []
    }
    assert gemini_names == expected
