"""Property-based CIM event generation tests (TEST-03).

Generates 10,000+ random valid CIM events using Hypothesis strategies
and validates that create_event produces well-formed TelemetryEvent
instances for every combination of event type, framework, and optional fields.

Run with:
    pytest tests/property/test_cim_generation.py -v --hypothesis-seed=0
"""

import dataclasses
import json

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from observra.core.events import TelemetryEvent, create_event

# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

cim_event_types = st.sampled_from(
    [
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
        "agent_handoff_error",
        "stream_event",
        "adapter_close",
        "forwarder_update_available",
        "forwarder_updated",
        "forwarder_update_failed",
    ]
)

cim_frameworks = st.sampled_from(
    [
        "claude_code",
        "openai",
        "gemini_cli",
        "langchain",
        "pydantic-ai",
        "adk",
        None,
    ]
)

cim_model_names = st.sampled_from(
    [
        "claude-opus-4-5",
        "claude-sonnet-4-5",
        "gpt-4o",
        "gemini-2.5-pro",
        "o3-mini",
        None,
    ]
)

cim_tool_names = st.sampled_from(
    [
        "read_file",
        "write_file",
        "bash",
        "delete_file",
        "list_files",
        None,
    ]
)

cim_agent_names = st.sampled_from(
    [
        "main-agent",
        "code-reviewer",
        "planner",
        None,
    ]
)

token_counts = st.integers(min_value=0, max_value=100000) | st.none()


# ---------------------------------------------------------------------------
# Property test 1: create_event always returns a TelemetryEvent
# ---------------------------------------------------------------------------


@given(
    event_type=cim_event_types,
    framework=cim_frameworks,
    model_name=cim_model_names,
    tool_name=cim_tool_names,
    agent_name=cim_agent_names,
)
@settings(max_examples=10000, suppress_health_check=[HealthCheck.too_slow])
def test_create_event_always_returns_telemetry_event(event_type, framework, model_name, tool_name, agent_name):
    """For any combination of event type and optional fields, create_event must return
    a valid TelemetryEvent with all required fields populated."""
    kwargs = {}
    if framework is not None:
        kwargs["framework"] = framework
    if model_name is not None:
        kwargs["model_name"] = model_name
    if tool_name is not None:
        kwargs["tool_name"] = tool_name
    if agent_name is not None:
        kwargs["agent_name"] = agent_name

    result = create_event(event_type=event_type, **kwargs)

    assert isinstance(result, TelemetryEvent)
    assert result.event_type == event_type
    assert isinstance(result.event_id, str) and len(result.event_id) > 0
    assert result.timestamp > 0
    assert isinstance(result.trace_id, str) and len(result.trace_id) > 0
    assert isinstance(result.session_id, str) and len(result.session_id) > 0


# ---------------------------------------------------------------------------
# Property test 2: event serializes to valid JSON with required keys
# ---------------------------------------------------------------------------


@given(
    event_type=cim_event_types,
    framework=cim_frameworks,
    model_name=cim_model_names,
)
@settings(max_examples=5000, suppress_health_check=[HealthCheck.too_slow])
def test_event_serializes_to_valid_json(event_type, framework, model_name):
    """Every event produced by create_event must be JSON-serializable and round-trip
    successfully, preserving required CIM fields."""
    kwargs = {}
    if framework is not None:
        kwargs["framework"] = framework
    if model_name is not None:
        kwargs["model_name"] = model_name

    event = create_event(event_type=event_type, **kwargs)
    # TelemetryEvent uses slots=True (no __dict__); use dataclasses.asdict() instead
    serialized = json.dumps(dataclasses.asdict(event), default=str)
    parsed = json.loads(serialized)

    assert "event_id" in parsed
    assert "event_type" in parsed
    assert "timestamp" in parsed


# ---------------------------------------------------------------------------
# Property test 3: data field contains CIM action and vendor
# ---------------------------------------------------------------------------


@given(
    event_type=cim_event_types,
    framework=cim_frameworks,
)
@settings(max_examples=5000, suppress_health_check=[HealthCheck.too_slow])
def test_data_field_contains_cim_action(event_type, framework):
    """Every event's data dict must contain the CIM-required 'action' and 'vendor'
    fields. These are injected by create_event regardless of the caller's kwargs."""
    kwargs = {}
    if framework is not None:
        kwargs["framework"] = framework

    event = create_event(event_type=event_type, **kwargs)

    assert isinstance(event.data, dict), (
        f"event.data must be a dict, got {type(event.data)} for event_type={event_type}"
    )
    assert "action" in event.data, f"CIM requires 'action' in event.data; got keys: {list(event.data.keys())}"
    assert "vendor" in event.data, f"CIM requires 'vendor' in event.data; got keys: {list(event.data.keys())}"
