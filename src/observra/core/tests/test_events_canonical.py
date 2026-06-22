# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0

"""End-to-end contract tests for ``create_event``.

Asserts that every event from every framework carries the same canonical
``data`` block and the same host-context fields. Mirrors the Rust
``rust/tests/e2e_schema_consistency.rs`` integration test.
"""

from __future__ import annotations

import pytest

from observra import create_event


@pytest.mark.parametrize(
    "event_type,model,tool,expected_action,expected_vendor,expected_result",
    [
        ("session_start", "claude-opus-4-7", None, "start_session", "anthropic", None),
        ("session_end", "gpt-5", None, "end_session", "openai", None),
        ("user_message", "gemini-2.5-pro", None, "prompt_submit", "google", None),
        ("model_response", "claude-opus-4-7", None, "call_llm", "anthropic", "success"),
        ("model_error", "gpt-5", None, "call_llm", "openai", "failure"),
        ("turn", "claude-opus-4-7", None, "call_llm", "anthropic", "success"),
        ("compact_boundary", "claude-opus-4-7", None, "compact_context", "anthropic", None),
        ("tool_start", "gpt-5", "Bash", "tool_call", "openai", None),
        ("tool_end", "gemini-2.5-pro", "Read", "tool_call", "google", "success"),
        ("tool_error", "claude-opus-4-7", "Web", "tool_call", "anthropic", "failure"),
        ("agent_start", "gpt-5", None, "invoke_agent", "openai", None),
        ("agent_end", "gemini-2.5-pro", None, "invoke_agent", "google", "success"),
        ("agent_handoff", "gpt-5", None, "invoke_agent", "openai", None),
    ],
)
def test_canonical_data_block_matches_contract(
    event_type, model, tool, expected_action, expected_vendor, expected_result
) -> None:
    e = create_event(event_type, framework="unknown", model_name=model, tool_name=tool)
    assert e.data is not None
    assert e.data["action"] == expected_action, f"{event_type} action"
    assert e.data["vendor"] == expected_vendor, f"{event_type} vendor"
    if expected_result is None:
        assert "result" not in e.data, f"{event_type} should not have result"
    else:
        assert e.data["result"] == expected_result, f"{event_type} result"


def test_every_event_carries_full_host_context() -> None:
    e = create_event("session_start", framework="unknown", model_name="claude-opus-4-7")
    assert e.arch is not None, "arch must be populated on every event"
    assert e.library_version is not None, "library_version must be populated"
    # host/user/os are best-effort; one of host or user should be set.
    assert e.host or e.user, "at least one of host/user must resolve"


def test_explicit_data_kwargs_override_canonical_defaults() -> None:
    # An adapter passing action/vendor/result explicitly must win — used by
    # OpenClaw to emit data.action="invoke_tool" rather than the default
    # "tool_call" in some legacy paths.
    e = create_event(
        "tool_end",
        framework="unknown",
        model_name="claude-opus-4-7",
        tool_name="custom_tool",
        action="custom_action",
        vendor="custom_vendor",
        result="timeout",
    )
    assert e.data["action"] == "custom_action"
    assert e.data["vendor"] == "custom_vendor"
    assert e.data["result"] == "timeout"


def test_tool_call_auto_classifies_reversibility() -> None:
    e_send = create_event("tool_start", framework="unknown", model_name="claude-opus-4-7", tool_name="send_email")
    assert e_send.data["reversible"] is False

    e_read = create_event("tool_start", framework="unknown", model_name="claude-opus-4-7", tool_name="read_file")
    assert e_read.data["reversible"] is True

    # Unknown tool → no reversible key (rather than False/True/null guess).
    e_bash = create_event("tool_start", framework="unknown", model_name="claude-opus-4-7", tool_name="Bash")
    assert "reversible" not in e_bash.data


def test_explicit_reversibility_kwarg_wins_over_classification() -> None:
    e = create_event(
        "tool_start",
        framework="unknown",
        model_name="claude-opus-4-7",
        tool_name="send_email",  # would classify as False
        reversible=True,
    )
    assert e.data["reversible"] is True


def test_cross_vendor_siem_rule_works_for_failure_signal() -> None:
    """One SIEM rule, four vendors, identical match shape."""
    fails = []
    for model in ("claude-opus-4-7", "gpt-5", "gemini-2.5-pro", "github-copilot"):
        e = create_event("tool_error", framework="unknown", model_name=model, tool_name="X")
        fails.append((e.data["action"], e.data["result"], e.data["vendor"]))
    actions = {a for a, _r, _v in fails}
    results = {r for _a, r, _v in fails}
    vendors = {v for _a, _r, v in fails}
    assert actions == {"tool_call"}, "data.action must be uniform across vendors"
    assert results == {"failure"}, "data.result must be uniform"
    assert vendors == {"anthropic", "openai", "google", "microsoft"}


from observra.core import cim as _cim  # noqa: E402


def test_log_source_type_present_in_cold_path_event() -> None:
    """LOGID-01: cold-path events carry log_source_type from PRODUCT_ID constant."""
    e = create_event("tool_end", framework="unknown", model_name="claude-opus-4-7", tool_name="Bash")
    assert e.data is not None
    assert e.data.get("log_source_type") == _cim.PRODUCT_ID


def test_log_source_type_preserved_on_hot_path_event() -> None:
    """LOGID-02: hot-path events preserve log_source_type (not nullified by redaction)."""
    for event_type in (
        "session_start",
        "session_end",
        "agent_start",
        "agent_end",
        "model_request",
        "cost_threshold_exceeded",
    ):
        e = create_event(event_type, framework="unknown", model_name="claude-opus-4-7")
        assert e.data is not None, f"{event_type} data must not be None"
        assert e.data.get("log_source_type") == _cim.PRODUCT_ID, (
            f"{event_type} log_source_type must be preserved on hot path"
        )
