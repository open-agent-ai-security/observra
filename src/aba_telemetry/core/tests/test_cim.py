"""Unit tests for ``aba_telemetry.core.cim``.

Mirrors the Rust ``rust/src/cim.rs`` test cases. If you change the
mapping table in either runtime, change it in both.
"""

from __future__ import annotations

import pytest

from aba_telemetry.core.cim import (
    PRODUCT_ID,
    action_for_event_type,
    build_data_for_event,
    classify_reversibility,
    default_result_for_event_type,
    vendor_from_model,
    vendor_from_model_or_framework,
)


def test_action_mapping_is_complete_for_known_event_types() -> None:
    for et in (
        "session_start",
        "session_end",
        "user",
        "user_message",
        "model_request",
        "model_response",
        "model_error",
        "turn",
        "turn_duration",
        "compact_boundary",
        "tool_start",
        "tool_end",
        "tool_error",
        "agent_start",
        "agent_end",
        "agent_handoff",
        "skill_invocation",
    ):
        assert action_for_event_type(et) != "unknown", (
            f"event_type {et} must have a mapped action"
        )


def test_default_result_only_set_for_terminals() -> None:
    assert default_result_for_event_type("tool_end") == "success"
    assert default_result_for_event_type("agent_end") == "success"
    assert default_result_for_event_type("turn") == "success"
    assert default_result_for_event_type("model_response") == "success"
    assert default_result_for_event_type("tool_error") == "failure"
    assert default_result_for_event_type("model_error") == "failure"
    assert default_result_for_event_type("agent_handoff_error") == "failure"
    assert default_result_for_event_type("tool_start") is None
    assert default_result_for_event_type("session_start") is None
    assert default_result_for_event_type("turn_duration") is None
    assert default_result_for_event_type("compact_boundary") is None


@pytest.mark.parametrize(
    "model,expected",
    [
        ("claude-opus-4-7", "anthropic"),
        ("claude-3-5-sonnet", "anthropic"),
        ("anthropic/claude-opus-4-7", "anthropic"),
        ("gpt-5.4", "openai"),
        ("gpt-4o", "openai"),
        ("o1-preview", "openai"),
        ("o3-mini", "openai"),
        ("openai/gpt-5", "openai"),
        ("gemini-2.5-pro", "google"),
        ("gemini-1.5-flash", "google"),
        ("vertex-gemini-pro", "google"),
        ("github-copilot", "microsoft"),
        ("llama-3-70b", "unknown"),
        ("", "unknown"),
        (None, "unknown"),
    ],
)
def test_vendor_from_model_recognizes_all_four_vendors(model, expected) -> None:
    assert vendor_from_model(model) == expected


def test_build_data_includes_mandatory_keys_no_result_for_non_terminal() -> None:
    d = build_data_for_event("session_start", "anthropic")
    assert d == {"action": "start_session", "vendor": "anthropic"}
    assert "result" not in d


def test_build_data_terminal_carries_default_result() -> None:
    d = build_data_for_event("tool_end", "openai")
    assert d == {"action": "tool_call", "vendor": "openai", "result": "success"}

    d = build_data_for_event("tool_error", "google")
    assert d["result"] == "failure"


def test_extras_can_override_default_result() -> None:
    # OpenClaw timeout case — caller-supplied "timeout" must win over the
    # default "success" so SIEM rules on result IN ('failure','timeout') work.
    d = build_data_for_event("agent_end", "anthropic", {"result": "timeout", "run_id": "r1"})
    assert d["result"] == "timeout"
    assert d["run_id"] == "r1"


@pytest.mark.parametrize(
    "model,framework,expected",
    [
        # Model wins when present.
        ("claude-opus-4-7", "openai",  "anthropic"),
        ("gpt-5",            None,      "openai"),
        # Framework fallback when model is None or not classifiable.
        (None,  "claude_code", "anthropic"),
        (None,  "codex_cli",   "openai"),
        (None,  "gemini_cli",  "google"),
        (None,  "copilot",     "microsoft"),
        # Multi-vendor wrappers stay unknown.
        (None,  "openclaw",    "unknown"),
        (None,  "langgraph",   "unknown"),
        (None,  "pydantic-ai", "unknown"),
        # No model + no framework + unknown framework.
        (None,  None,          "unknown"),
        (None,  "weird",       "unknown"),
        # Model that's already classifiable beats a multi-vendor wrapper.
        ("claude-3-5-sonnet", "openclaw", "anthropic"),
    ],
)
def test_vendor_from_model_or_framework_fallback(model, framework, expected) -> None:
    assert vendor_from_model_or_framework(model, framework) == expected


@pytest.mark.parametrize(
    "tool,expected",
    [
        ("send_email", False),
        ("delete_user", False),
        ("publish_post", False),
        ("read_file", True),
        ("fetch_data", True),
        ("draft_message", True),
        ("Bash", None),
        ("UnknownTool", None),
        (None, None),
        ("", None),
    ],
)
def test_classify_reversibility_matches_rust(tool, expected) -> None:
    assert classify_reversibility(tool) is expected


def test_product_id_constant_in_cim_module() -> None:
    """LOGID-04: PRODUCT_ID is generated from cim_schema.toml meta.product_id."""
    assert PRODUCT_ID == "aba-telemetry"
