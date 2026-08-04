# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Tests for the LiteLLM adapter."""

import pytest

pytest.importorskip("litellm")

from observra.adapters.litellm import LiteLLMAdapter


@pytest.fixture
def adapter():
    return LiteLLMAdapter(agent_name="test-agent")


def test_adapter_initializes(adapter):
    assert adapter._agent_name == "test-agent"
    assert adapter._events_captured == 0


def test_adapter_stats(adapter):
    stats = adapter.get_adapter_stats()
    assert stats["framework"] == "litellm"
    assert stats["error_count"] == 0


def test_create_plugin_registers_callback():
    import litellm
    import observra

    initial_count = len(litellm.callbacks)
    observra.create_plugin("litellm")
    assert len(litellm.callbacks) == initial_count + 1
    # Cleanup
    litellm.callbacks.pop()


# TODO: add tests for log_success_event, log_failure_event once implemented
