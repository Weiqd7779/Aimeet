from app.live.tools import TOOL_DEFINITIONS, gemini_tools, openai_tools


def test_provider_tool_conversions_expose_same_names() -> None:
    expected = {tool["name"] for tool in TOOL_DEFINITIONS}
    gemini_names = {
        declaration.name
        for tool in gemini_tools()
        for declaration in tool.function_declarations or []
    }
    openai_names = {tool["name"] for tool in openai_tools()}

    assert expected == {"create_anchor", "propose_decision", "notify_speaker", "capture_context"}
    assert gemini_names == expected
    assert openai_names == expected
