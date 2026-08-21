import asyncio

from backend.service.intervention_tools import LocalTextTool, MockVoiceTool, select_intervention_tool


def test_mock_voice_tool_is_explicitly_simulated():
    result = asyncio.run(MockVoiceTool().execute(object(), "请先坐稳并注意安全"))
    assert result.delivery_status == "SUCCESS"
    assert result.tool_name == "mock_voice"
    assert result.simulated is True
    assert "Mock" in result.resolution_reason


def test_local_text_tool_is_explicitly_simulated():
    result = asyncio.run(LocalTextTool().execute(object(), "请先坐稳并注意安全"))
    assert result.delivery_status == "SUCCESS"
    assert result.tool_name == "local_text"
    assert result.simulated is True


def test_unverified_live_voice_selects_mock_tool():
    tool = select_intervention_tool()
    assert isinstance(tool, MockVoiceTool)
