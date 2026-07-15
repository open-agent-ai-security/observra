# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Tests for Claude adapter session_id seeding and agent_name attribution."""

import pytest

# These tests build ClaudeAgentOptions via get_hook_options(), which lazily
# imports claude_agent_sdk — skip the module on base installs (the [claude] extra
# is only present in the test-extras CI job), matching test_examples_smoke.py.
pytest.importorskip("claude_agent_sdk", reason="requires the [claude] extra")

from observra.adapters.claude import ClaudeAdapter  # noqa: E402
from observra.core.context import get_session_id  # noqa: E402


@pytest.fixture
def adapter():
    return ClaudeAdapter(capture_tool_data=True)


@pytest.fixture
def named_adapter():
    return ClaudeAdapter(capture_tool_data=True, agent_name="my-research-agent")


def test_get_hook_options_seeds_session_id(adapter):
    adapter.get_hook_options()
    session_id = get_session_id()
    assert session_id
    assert len(session_id) > 10  # ULID, not empty


@pytest.mark.asyncio
async def test_all_events_share_seeded_session_id(adapter):
    adapter.get_hook_options()
    seeded_id = get_session_id()

    await adapter._on_pre_tool_use(
        input_data={"tool_name": "read_file", "tool_input": {"path": "/tmp/x"}},
        tool_use_id="tool-001",
        context=None,
    )
    await adapter._on_post_tool_use(
        input_data={"tool_name": "read_file", "tool_input": {}, "tool_response": "ok"},
        tool_use_id="tool-001",
        context=None,
    )
    await adapter._on_user_prompt_submit(
        input_data={"message": {"role": "user", "content": "hello"}},
        tool_use_id="prompt-001",
        context=None,
    )

    events = adapter.events
    assert len(events) == 3
    session_ids = {e.session_id for e in events}
    assert session_ids == {seeded_id}


@pytest.mark.asyncio
async def test_agent_name_populated_in_all_events(named_adapter):
    named_adapter.get_hook_options()

    await named_adapter._on_pre_tool_use(
        input_data={"tool_name": "read_file", "tool_input": {}},
        tool_use_id="tool-001",
        context=None,
    )
    await named_adapter._on_post_tool_use(
        input_data={"tool_name": "read_file", "tool_input": {}, "tool_response": "ok"},
        tool_use_id="tool-001",
        context=None,
    )
    await named_adapter._on_user_prompt_submit(
        input_data={"message": {"role": "user", "content": "hello"}},
        tool_use_id="prompt-001",
        context=None,
    )
    await named_adapter._on_stop(
        input_data={"stop_hook_active": True},
        tool_use_id="stop-001",
        context=None,
    )

    events = named_adapter.events
    assert len(events) == 4
    for event in events:
        assert event.agent_name == "my-research-agent"


@pytest.mark.asyncio
async def test_agent_name_none_when_not_provided(adapter):
    adapter.get_hook_options()

    await adapter._on_pre_tool_use(
        input_data={"tool_name": "read_file", "tool_input": {}},
        tool_use_id="tool-001",
        context=None,
    )

    events = adapter.events
    assert len(events) == 1
    assert events[0].agent_name is None


@pytest.mark.asyncio
async def test_subagent_stop_prefers_agent_type_from_input(named_adapter):
    named_adapter.get_hook_options()

    await named_adapter._on_subagent_stop(
        input_data={"agent_type": "code-reviewer", "agent_id": "sub-1", "stop_hook_active": False},
        tool_use_id="sub-stop-001",
        context=None,
    )

    events = named_adapter.events
    assert len(events) == 1
    assert events[0].agent_name == "code-reviewer"
