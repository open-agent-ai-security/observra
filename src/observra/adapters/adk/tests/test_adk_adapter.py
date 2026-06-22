"""Co-located ADK adapter tests.

Validates Protocol conformance, token normalization, error stats, observation-only
behavior, and queue routing. These tests are the canonical reference for Phase 10
requirements and serve as the template for future adapter test suites.

All imports use canonical paths:
  observra.adapters.adk.plugin  (not compat shim)
  observra.adapters.utils       (not direct ADK types)
"""

import types
from unittest.mock import MagicMock

import pytest

from observra.adapters.adk.plugin import TelemetryPlugin
from observra.adapters.utils import normalize_adk_tokens
from observra.core.adapter import FrameworkAdapter
from observra.core.events import create_event

# ---------------------------------------------------------------------------
# 1. Protocol conformance
# ---------------------------------------------------------------------------

def test_adk_adapter_satisfies_protocol():
    """TelemetryPlugin must satisfy the FrameworkAdapter Protocol."""
    plugin = TelemetryPlugin(queue=None)
    assert isinstance(plugin, FrameworkAdapter), (
        "TelemetryPlugin does not satisfy FrameworkAdapter Protocol"
    )
    assert plugin.framework_name == "adk"


# ---------------------------------------------------------------------------
# 2. Token normalization — full metadata
# ---------------------------------------------------------------------------

def test_normalize_adk_tokens_full():
    """All fields present — all NormalizedTokens fields must be populated."""
    metadata = types.SimpleNamespace(
        prompt_token_count=100,
        candidates_token_count=50,
        total_token_count=150,
        cached_content_token_count=20,
        thoughts_token_count=10,
    )
    result = normalize_adk_tokens(metadata)
    assert result is not None
    assert result.input_tokens == 100
    assert result.output_tokens == 50
    assert result.total_tokens == 150
    assert result.cached_tokens == 20
    assert result.reasoning_tokens == 10


# ---------------------------------------------------------------------------
# 3. Token normalization — None input
# ---------------------------------------------------------------------------

def test_normalize_adk_tokens_no_metadata():
    """None input must return None (no-op)."""
    result = normalize_adk_tokens(None)
    assert result is None


# ---------------------------------------------------------------------------
# 4. Token normalization — optional fields absent
# ---------------------------------------------------------------------------

def test_normalize_adk_tokens_optional_fields_none():
    """Required fields only — optional fields must be None, not 0."""
    metadata = types.SimpleNamespace(
        prompt_token_count=100,
        candidates_token_count=50,
        total_token_count=150,
    )
    result = normalize_adk_tokens(metadata)
    assert result is not None
    assert result.cached_tokens is None
    assert result.reasoning_tokens is None


# ---------------------------------------------------------------------------
# 5. Error stats increment on emit() failure
# ---------------------------------------------------------------------------

def test_adapter_error_stats_increment():
    """emit() failure must increment error_count; get_adapter_stats() reflects it."""
    plugin = TelemetryPlugin(queue=None)

    # Monkey-patch _events.append to raise
    bad_list = MagicMock()
    bad_list.append.side_effect = RuntimeError("boom")
    plugin._events = bad_list

    event = create_event(event_type="test", framework="adk")
    plugin.emit(event)

    assert plugin._error_count == 1

    stats = plugin.get_adapter_stats()
    assert stats["error_count"] == 1
    assert stats["framework"] == "adk"


# ---------------------------------------------------------------------------
# 6. Dropped events when disabled
# ---------------------------------------------------------------------------

def test_adapter_dropped_events_when_disabled():
    """emit() with _enabled=False must increment _dropped_events."""
    plugin = TelemetryPlugin(queue=None)
    plugin._enabled = False

    event = create_event(event_type="test", framework="adk")
    plugin.emit(event)

    assert plugin._dropped_events == 1


# ---------------------------------------------------------------------------
# 7. after_model_callback uses normalized tokens
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_after_model_uses_normalized_tokens():
    """after_model_callback must use normalize_adk_tokens() for token fields."""
    plugin = TelemetryPlugin(queue=None)

    callback_context = types.SimpleNamespace()
    usage_metadata = types.SimpleNamespace(
        prompt_token_count=200,
        candidates_token_count=80,
        total_token_count=280,
        cached_content_token_count=0,
        thoughts_token_count=0,
    )
    llm_response = types.SimpleNamespace(
        model="gemini-2.5-flash",
        usage_metadata=usage_metadata,
    )

    await plugin.before_model_callback(
        callback_context=callback_context,
        llm_request=types.SimpleNamespace(model="gemini-2.5-flash"),
    )
    await plugin.after_model_callback(
        callback_context=callback_context,
        llm_response=llm_response,
    )

    events = plugin.events
    # before_model emits model_request, after_model emits model_response + turn_duration
    response_events = [e for e in events if e.event_type == "model_response"]
    assert len(response_events) == 1
    event = response_events[0]
    assert event.data["input_tokens"] == 200
    assert event.data["output_tokens"] == 80
    assert event.data["total_tokens"] == 280


# ---------------------------------------------------------------------------
# 7b. turn_duration emitted after model response
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_turn_duration_emitted():
    """after_model_callback must emit turn_duration with duration_ms after model_response."""
    plugin = TelemetryPlugin(queue=None)

    callback_context = types.SimpleNamespace()
    usage_metadata = types.SimpleNamespace(
        prompt_token_count=100,
        candidates_token_count=50,
        total_token_count=150,
        cached_content_token_count=0,
        thoughts_token_count=0,
    )
    llm_response = types.SimpleNamespace(
        model="gemini-2.5-flash",
        usage_metadata=usage_metadata,
    )

    await plugin.before_model_callback(
        callback_context=callback_context,
        llm_request=types.SimpleNamespace(model="gemini-2.5-flash"),
    )
    await plugin.after_model_callback(
        callback_context=callback_context,
        llm_response=llm_response,
    )

    duration_events = [e for e in plugin.events if e.event_type == "turn_duration"]
    assert len(duration_events) == 1
    event = duration_events[0]
    assert event.model_name == "gemini-2.5-flash"
    assert event.framework == "adk"
    assert "duration_ms" in event.data
    assert event.data["duration_ms"] >= 0


@pytest.mark.asyncio
async def test_turn_duration_not_emitted_without_before_model():
    """turn_duration must NOT be emitted if before_model_callback was not called."""
    plugin = TelemetryPlugin(queue=None)

    callback_context = types.SimpleNamespace()
    llm_response = types.SimpleNamespace(model="gemini-2.5-flash", usage_metadata=None)

    await plugin.after_model_callback(
        callback_context=callback_context,
        llm_response=llm_response,
    )

    duration_events = [e for e in plugin.events if e.event_type == "turn_duration"]
    assert len(duration_events) == 0


# ---------------------------------------------------------------------------
# 7c. turn_duration emitted on model error path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_turn_duration_emitted_on_error():
    """on_model_error_callback must emit turn_duration with duration_ms even on error."""
    plugin = TelemetryPlugin(queue=None)

    callback_context = types.SimpleNamespace()
    llm_request = types.SimpleNamespace(model="gemini-2.5-flash")

    await plugin.before_model_callback(
        callback_context=callback_context,
        llm_request=llm_request,
    )
    await plugin.on_model_error_callback(
        callback_context=callback_context,
        llm_request=llm_request,
        error=ValueError("model timeout"),
    )

    duration_events = [e for e in plugin.events if e.event_type == "turn_duration"]
    assert len(duration_events) == 1
    event = duration_events[0]
    assert event.model_name == "gemini-2.5-flash"
    assert event.framework == "adk"
    assert "duration_ms" in event.data
    assert event.data["duration_ms"] >= 0


# ---------------------------------------------------------------------------
# 8. emit() routes events to queue (ADPT-07 storage routing)
# ---------------------------------------------------------------------------

def test_emit_routes_to_queue():
    """emit() with a queue must call queue.put_nowait with the event."""
    mock_queue = MagicMock()
    plugin = TelemetryPlugin(queue=mock_queue)

    event = create_event(event_type="test", framework="adk")
    plugin.emit(event)

    mock_queue.put_nowait.assert_called_once_with(event)
