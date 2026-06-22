# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for hot_cold module."""

from observra.core.hot_cold import COLD_PATH_EVENT_TYPES, HOT_PATH_EVENT_TYPES, is_cold_path, is_hot_path


def test_hot_path_types():
    """Test that all expected hot path types return True."""
    hot_path_types = [
        "session_start",
        "session_end",
        "agent_start",
        "agent_end",
        "model_request",
        "cost_threshold_exceeded",
    ]

    for event_type in hot_path_types:
        assert is_hot_path(event_type) is True, f"{event_type} should be hot path"


def test_cold_path_types():
    """Test that all expected cold path types return True."""
    cold_path_types = [
        "tool_start",
        "tool_end",
        "tool_error",
        "user_message",
        "model_error",
        "stream_event",
        "adapter_close",
        "depth_exceeded",
        "log_message",
        "agent_handoff",
        "agent_handoff_error",
    ]

    for event_type in cold_path_types:
        assert is_cold_path(event_type) is True, f"{event_type} should be cold path"


def test_log_message_is_cold():
    """Test that log_message is classified as cold path."""
    assert is_cold_path("log_message") is True
    assert is_hot_path("log_message") is False


def test_unknown_type_not_hot():
    """Test that unknown event types are not classified as hot path."""
    assert is_hot_path("unknown_type") is False


def test_no_overlap_between_hot_and_cold():
    """Test that hot and cold path sets do not overlap."""
    overlap = HOT_PATH_EVENT_TYPES & COLD_PATH_EVENT_TYPES
    assert len(overlap) == 0, f"Hot and cold paths should not overlap: {overlap}"
