# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Tests for Claude adapter session_id seeding via get_hook_options()."""

import asyncio

import pytest

from observra.adapters.claude import ClaudeAdapter
from observra.core.context import get_session_id


@pytest.fixture
def adapter():
    return ClaudeAdapter(capture_tool_data=True)


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
