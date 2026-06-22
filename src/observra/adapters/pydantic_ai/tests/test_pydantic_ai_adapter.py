# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Co-located tests for the Pydantic AI adapter.

Validates Protocol conformance, all span routing paths (model v2, tool v2/v3, agent skip),
token extraction (flat attributes, cached tokens, no-token fallback), model name prefix
stripping, error resilience, cost_threshold_exceeded once-guard, queue routing, pricing
config loading, and adapter stats.

All tests use types.SimpleNamespace to create mock ReadableSpan objects (duck-typed with
.name and .attributes fields) and run without pydantic-ai or opentelemetry-sdk installed
(conftest.py stubs the module hierarchy into sys.modules).
"""

import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Mock span factories
# ---------------------------------------------------------------------------

def _make_model_span(model="gpt-4o", input_tokens=500, output_tokens=200):
    """Mock 'chat {model}' span with token usage attributes."""
    return types.SimpleNamespace(
        name=f"chat {model}",
        attributes={
            "gen_ai.request.model": model,
            "gen_ai.response.model": model,
            "gen_ai.usage.input_tokens": input_tokens,
            "gen_ai.usage.output_tokens": output_tokens,
        },
    )


def _make_tool_span(tool_name="calculator", params='{"a": 2, "b": 3}'):
    """Mock 'running tool' span (v2) with tool name and parameters."""
    return types.SimpleNamespace(
        name="running tool",
        attributes={
            "gen_ai.tool.name": tool_name,
            "gen_ai.tool.parameters": params,
        },
    )


def _make_tool_span_v3(tool_name="lookup", params='{"key": "pi"}'):
    """Mock 'execute_tool {name}' span (v3+) with tool name and call arguments."""
    return types.SimpleNamespace(
        name=f"execute_tool {tool_name}",
        attributes={
            "gen_ai.tool.name": tool_name,
            "gen_ai.tool.call.arguments": params,
        },
    )


def _make_agent_span(agent_name="test_agent"):
    """Mock 'invoke_agent {name}' span (should be skipped by adapter)."""
    return types.SimpleNamespace(
        name=f"invoke_agent {agent_name}",
        attributes={"gen_ai.agent.name": agent_name},
    )


# ---------------------------------------------------------------------------
# Fixtures: initialize context for every test
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _init_context():
    """Initialize valid trace/session context for every test."""
    from observra.core.context import initialize_session, initialize_trace
    initialize_trace()
    initialize_session()


# ---------------------------------------------------------------------------
# 1. Protocol conformance
# ---------------------------------------------------------------------------

def test_protocol_conformance():
    """PydanticAIAdapter must satisfy FrameworkAdapter Protocol with framework_name='pydantic-ai'."""
    from observra.adapters.pydantic_ai.adapter import PydanticAIAdapter
    from observra.core.adapter import FrameworkAdapter

    adapter = PydanticAIAdapter()
    assert isinstance(adapter, FrameworkAdapter), (
        "PydanticAIAdapter does not satisfy FrameworkAdapter Protocol"
    )
    assert adapter.framework_name == "pydantic-ai"


# ---------------------------------------------------------------------------
# 2. Model span — OpenAI with tokens and cost
# ---------------------------------------------------------------------------

def test_model_span_emits_model_response():
    """'chat gpt-4o' span with gen_ai.usage.* attrs emits model_response with correct tokens and cost."""
    from observra.adapters.pydantic_ai.adapter import PydanticAIAdapter

    adapter = PydanticAIAdapter()
    span = _make_model_span("gpt-4o", input_tokens=500, output_tokens=200)
    adapter.on_end(span)

    assert len(adapter._events) == 1
    event = adapter._events[0]
    assert event.event_type == "model_response"
    assert event.model_name == "gpt-4o"
    assert event.framework == "pydantic-ai"
    assert event.data is not None
    assert event.data["input_tokens"] == 500
    assert event.data["output_tokens"] == 200
    assert event.data["cost_usd"] > 0


# ---------------------------------------------------------------------------
# 3. Model span — Anthropic pricing
# ---------------------------------------------------------------------------

def test_model_span_with_anthropic():
    """'chat claude-3-5-sonnet-20241022' span emits model_response with Anthropic pricing applied."""
    from observra.adapters.pydantic_ai.adapter import PydanticAIAdapter

    adapter = PydanticAIAdapter()
    span = _make_model_span("claude-3-5-sonnet-20241022", input_tokens=800, output_tokens=300)
    adapter.on_end(span)

    assert len(adapter._events) == 1
    event = adapter._events[0]
    assert event.event_type == "model_response"
    assert event.model_name == "claude-3-5-sonnet-20241022"
    assert event.data is not None
    assert event.data["input_tokens"] == 800
    assert event.data["output_tokens"] == 300
    assert event.data["cost_usd"] > 0


# ---------------------------------------------------------------------------
# 4. Model span without tokens
# ---------------------------------------------------------------------------

def test_model_span_without_tokens():
    """'chat unknown' span with no gen_ai.usage.* attrs emits model_response without token/cost fields."""
    from observra.adapters.pydantic_ai.adapter import PydanticAIAdapter

    adapter = PydanticAIAdapter()
    span = types.SimpleNamespace(
        name="chat unknown",
        attributes={
            "gen_ai.request.model": "unknown",
        },
    )
    adapter.on_end(span)

    assert len(adapter._events) == 1
    event = adapter._events[0]
    assert event.event_type == "model_response"
    assert event.model_name == "unknown"
    # Token/cost fields are always present but None when no usage data
    assert event.data is not None
    assert event.data.get("input_tokens") is None
    assert event.data.get("cost_usd") is None


# ---------------------------------------------------------------------------
# 5. Model span with cached tokens
# ---------------------------------------------------------------------------

def test_model_span_with_cached_tokens():
    """Span with gen_ai.usage.details.cache_read_tokens attr must include cached_tokens in event."""
    from observra.adapters.pydantic_ai.adapter import PydanticAIAdapter

    adapter = PydanticAIAdapter()
    span = types.SimpleNamespace(
        name="chat gpt-4o",
        attributes={
            "gen_ai.request.model": "gpt-4o",
            "gen_ai.response.model": "gpt-4o",
            "gen_ai.usage.input_tokens": 1000,
            "gen_ai.usage.output_tokens": 200,
            "gen_ai.usage.details.cache_read_tokens": 500,
        },
    )
    adapter.on_end(span)

    assert len(adapter._events) == 1
    event = adapter._events[0]
    assert event.event_type == "model_response"
    assert event.data is not None
    assert "cached_tokens" in event.data
    assert event.data["cached_tokens"] == 500


# ---------------------------------------------------------------------------
# 6. Tool span v2 — "running tool"
# ---------------------------------------------------------------------------

def test_tool_span_v2_running_tool():
    """'running tool' span with gen_ai.tool.name attr emits tool_call event."""
    from observra.adapters.pydantic_ai.adapter import PydanticAIAdapter

    adapter = PydanticAIAdapter()
    span = _make_tool_span("calculator")
    adapter.on_end(span)

    assert len(adapter._events) == 1
    event = adapter._events[0]
    assert event.event_type == "tool_end"
    assert event.tool_name == "calculator"
    assert event.framework == "pydantic-ai"


# ---------------------------------------------------------------------------
# 7. Tool span v3 — "execute_tool {name}"
# ---------------------------------------------------------------------------

def test_tool_span_v3_execute_tool():
    """'execute_tool calculator' span emits tool_call event with tool name extracted from attr and name."""
    from observra.adapters.pydantic_ai.adapter import PydanticAIAdapter

    adapter = PydanticAIAdapter()
    span = _make_tool_span_v3("calculator", '{"a": 2}')
    adapter.on_end(span)

    assert len(adapter._events) == 1
    event = adapter._events[0]
    assert event.event_type == "tool_end"
    assert event.tool_name == "calculator"
    assert event.framework == "pydantic-ai"


# ---------------------------------------------------------------------------
# 8. Tool data captured when enabled
# ---------------------------------------------------------------------------

def test_tool_data_captured_when_enabled():
    """capture_tool_data=True must serialize gen_ai.tool.parameters into tool_args."""
    from observra.adapters.pydantic_ai.adapter import PydanticAIAdapter

    adapter = PydanticAIAdapter(capture_tool_data=True)
    span = _make_tool_span("calculator", '{"a": 2, "b": 3}')
    adapter.on_end(span)

    assert len(adapter._events) == 1
    event = adapter._events[0]
    assert event.event_type == "tool_end"
    assert event.data is not None
    assert "tool_args" in event.data


# ---------------------------------------------------------------------------
# 9. Tool data not captured by default
# ---------------------------------------------------------------------------

def test_tool_data_not_captured_by_default():
    """capture_tool_data=False (default) must NOT include tool_args in tool_call event."""
    from observra.adapters.pydantic_ai.adapter import PydanticAIAdapter

    adapter = PydanticAIAdapter(capture_tool_data=False)
    span = _make_tool_span("calculator", '{"a": 2, "b": 3}')
    adapter.on_end(span)

    assert len(adapter._events) == 1
    event = adapter._events[0]
    assert event.event_type == "tool_end"
    # tool_args always present but None when capture_tool_data=False
    assert event.data is not None
    assert event.data.get("tool_args") is None


# ---------------------------------------------------------------------------
# 10. Agent run span skipped
# ---------------------------------------------------------------------------

def test_agent_run_span_skipped():
    """'agent run' span must produce no events (silently skipped)."""
    from observra.adapters.pydantic_ai.adapter import PydanticAIAdapter

    adapter = PydanticAIAdapter()
    span = types.SimpleNamespace(
        name="agent run",
        attributes={"gen_ai.agent.name": "test_agent"},
    )
    adapter.on_end(span)

    assert len(adapter._events) == 0, (
        f"'agent run' span must produce no events; got {len(adapter._events)}"
    )


# ---------------------------------------------------------------------------
# 11. Invoke_agent span skipped
# ---------------------------------------------------------------------------

def test_invoke_agent_span_skipped():
    """'invoke_agent test_agent' span must produce no events (silently skipped)."""
    from observra.adapters.pydantic_ai.adapter import PydanticAIAdapter

    adapter = PydanticAIAdapter()
    span = _make_agent_span("test_agent")
    adapter.on_end(span)

    assert len(adapter._events) == 0, (
        f"'invoke_agent *' span must produce no events; got {len(adapter._events)}"
    )


# ---------------------------------------------------------------------------
# 12. Model name prefix stripping
# ---------------------------------------------------------------------------

def test_model_name_prefix_stripping():
    """'chat openai:gpt-4o' span must strip provider prefix so model_name == 'gpt-4o'."""
    from observra.adapters.pydantic_ai.adapter import PydanticAIAdapter

    adapter = PydanticAIAdapter()
    span = types.SimpleNamespace(
        name="chat openai:gpt-4o",
        attributes={
            "gen_ai.request.model": "openai:gpt-4o",
            "gen_ai.response.model": "openai:gpt-4o",
            "gen_ai.usage.input_tokens": 100,
            "gen_ai.usage.output_tokens": 50,
        },
    )
    adapter.on_end(span)

    assert len(adapter._events) == 1
    event = adapter._events[0]
    assert event.event_type == "model_response"
    assert event.model_name == "gpt-4o", (
        f"Expected model_name='gpt-4o' after prefix stripping; got '{event.model_name}'"
    )


# ---------------------------------------------------------------------------
# 13. Error resilience
# ---------------------------------------------------------------------------

def test_error_resilience():
    """Span with .attributes that raises on access must increment _error_count without propagating."""
    from observra.adapters.pydantic_ai.adapter import PydanticAIAdapter

    adapter = PydanticAIAdapter()
    initial_error_count = adapter._error_count

    class _RaisingAttributes:
        def __iter__(self):
            raise RuntimeError("boom")

        def get(self, key, default=None):
            raise RuntimeError("boom")

    # A span whose name triggers model span routing, but attributes raise
    bad_span = types.SimpleNamespace(
        name="chat gpt-4o",
        attributes=_RaisingAttributes(),
    )

    # Must not raise
    adapter.on_end(bad_span)

    assert adapter._error_count >= initial_error_count + 1, (
        f"Expected _error_count to increment; was {initial_error_count}, now {adapter._error_count}"
    )


# ---------------------------------------------------------------------------
# 14. cost_threshold_exceeded — emitted exactly once
# ---------------------------------------------------------------------------

def test_cost_threshold_exceeded_once():
    """Large token span triggers cost_threshold_exceeded exactly once across multiple calls."""
    from observra.adapters.pydantic_ai.adapter import PydanticAIAdapter

    # Use a low threshold that will be exceeded with 100k/50k tokens at gpt-4o pricing
    adapter = PydanticAIAdapter(cost_threshold_usd=0.001)

    large_span = types.SimpleNamespace(
        name="chat gpt-4o",
        attributes={
            "gen_ai.request.model": "gpt-4o",
            "gen_ai.response.model": "gpt-4o",
            "gen_ai.usage.input_tokens": 100000,
            "gen_ai.usage.output_tokens": 50000,
        },
    )

    # First call — should trigger cost_threshold_exceeded
    adapter.on_end(large_span)

    event_types_1 = [e.event_type for e in adapter._events]
    assert "cost_threshold_exceeded" in event_types_1, (
        f"Expected cost_threshold_exceeded after first large span; got: {event_types_1}"
    )
    assert event_types_1.count("cost_threshold_exceeded") == 1

    # Second call — guard must prevent second emission
    adapter.on_end(large_span)

    event_types_2 = [e.event_type for e in adapter._events]
    assert event_types_2.count("cost_threshold_exceeded") == 1, (
        f"cost_threshold_exceeded must fire only once; fired {event_types_2.count('cost_threshold_exceeded')} times"
    )


# ---------------------------------------------------------------------------
# 15. emit() routes to queue
# ---------------------------------------------------------------------------

def test_emit_routes_to_queue():
    """emit() with a queue must call queue.put_nowait with the event."""
    from observra.adapters.pydantic_ai.adapter import PydanticAIAdapter
    from observra.core.events import create_event

    mock_queue = MagicMock()
    adapter = PydanticAIAdapter(queue=mock_queue)

    event = create_event(event_type="test", framework="pydantic-ai")
    adapter.emit(event)

    mock_queue.put_nowait.assert_called_once_with(event)


# ---------------------------------------------------------------------------
# 16. Pricing config loads
# ---------------------------------------------------------------------------

def test_pricing_config_loads():
    """CostCalculator must load co-located pricing.json and compute non-zero cost for gpt-4o."""
    from observra.core.cost import CostCalculator

    pricing_path = Path(__file__).resolve().parent.parent / "pricing.json"
    assert pricing_path.exists(), f"pricing.json not found at {pricing_path}"

    calculator = CostCalculator(str(pricing_path))
    cost = calculator.calculate_cost(
        model_name="gpt-4o",
        input_tokens=1000,
        output_tokens=500,
    )
    assert cost > 0, f"Expected non-zero cost for gpt-4o, got {cost}"


# ---------------------------------------------------------------------------
# 17. on_start is a no-op
# ---------------------------------------------------------------------------

def test_on_start_is_noop():
    """on_start() called with mock span must produce no events and no error."""
    from observra.adapters.pydantic_ai.adapter import PydanticAIAdapter

    adapter = PydanticAIAdapter()
    mock_span = types.SimpleNamespace(name="chat gpt-4o", attributes={})

    # Must not raise and must produce no events
    adapter.on_start(mock_span)

    assert len(adapter._events) == 0, (
        f"on_start must not emit events; got {len(adapter._events)}"
    )
    assert adapter._error_count == 0


# ---------------------------------------------------------------------------
# 18. get_adapter_stats returns correct counters
# ---------------------------------------------------------------------------

def test_get_adapter_stats():
    """After emitting events and triggering errors, stats dict has correct counters."""
    from observra.adapters.pydantic_ai.adapter import PydanticAIAdapter

    adapter = PydanticAIAdapter()

    # Emit a valid model event (captured in memory)
    adapter.on_end(_make_model_span("gpt-4o", 100, 50))

    # Trigger an error via bad attributes
    class _RaisingAttributes:
        def __iter__(self):
            raise RuntimeError("boom")

        def get(self, key, default=None):
            raise RuntimeError("boom")

    bad_span = types.SimpleNamespace(name="chat gpt-4o", attributes=_RaisingAttributes())
    adapter.on_end(bad_span)

    stats = adapter.get_adapter_stats()

    assert stats["framework"] == "pydantic-ai"
    assert stats["error_count"] >= 1, f"Expected at least 1 error; got {stats['error_count']}"
    assert stats["events_captured"] >= 1, f"Expected at least 1 event; got {stats['events_captured']}"
    assert "dropped_events" in stats
