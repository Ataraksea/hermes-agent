from __future__ import annotations

from hermes_cli.plugins import PluginManager, VALID_HOOKS


def test_select_tool_schemas_is_valid_hook():
    assert "select_tool_schemas" in VALID_HOOKS


def test_select_tool_schemas_returns_first_non_none_result():
    mgr = PluginManager()
    original = [{"type": "function", "function": {"name": "a"}}]
    selected = [{"type": "function", "function": {"name": "b"}}]
    mgr._hooks["select_tool_schemas"] = [lambda **kwargs: None, lambda **kwargs: selected]

    results = mgr.invoke_hook("select_tool_schemas", schemas=original)

    assert results[0] == selected


def test_select_tool_schemas_exception_fails_open_to_other_results():
    mgr = PluginManager()
    selected = [{"type": "function", "function": {"name": "safe"}}]

    def boom(**kwargs):
        raise RuntimeError("broken selector")

    mgr._hooks["select_tool_schemas"] = [boom, lambda **kwargs: selected]

    assert mgr.invoke_hook("select_tool_schemas", schemas=[]) == [selected]


def test_request_tools_helper_preserves_empty_selection_and_catalog():
    class AgentLike:
        def __init__(self):
            self.tools = [{"name": "read_file"}, {"name": "search_files"}]
            self._tools_for_request = None

        def _active_tools_for_request(self):
            request_tools = getattr(self, "_tools_for_request", None)
            return request_tools if request_tools is not None else self.tools

    agent = AgentLike()
    assert agent._active_tools_for_request() == agent.tools
    agent._tools_for_request = []
    assert agent._active_tools_for_request() == []
    assert agent.tools == [{"name": "read_file"}, {"name": "search_files"}]
    agent._tools_for_request = None
    assert agent._active_tools_for_request() == agent.tools