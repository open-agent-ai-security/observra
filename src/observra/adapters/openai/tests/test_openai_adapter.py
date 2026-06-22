"""Co-located tests for the OpenAI adapter.

Validates Protocol conformance, all 4 span type handlers (AgentSpanData,
GenerationSpanData, FunctionSpanData, HandoffSpanData), token extraction
via normalize_openai_tokens(), pricing config loading, error resilience,
cost_threshold_exceeded with only-once guard, queue routing, and dropped events.

All tests mock span objects using stub classes (not SimpleNamespace) that are
patched into the adapter module via monkeypatch so isinstance() checks work
without requiring the optional openai-agents dependency.
"""

import types
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Stub span data classes — patched into adapter module so isinstance() works
# ---------------------------------------------------------------------------


class _MockAgentSpanData:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _MockGenerationSpanData:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _MockFunctionSpanData:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _MockHandoffSpanData:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


# ---------------------------------------------------------------------------
# Fixtures: patch span classes + initialize context for every test
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _patch_span_classes(monkeypatch):
    """Patch adapter's span data class imports so isinstance() works with mocks."""
    from observra.adapters.openai import adapter as adapter_mod

    monkeypatch.setattr(adapter_mod, "AgentSpanData", _MockAgentSpanData)
    monkeypatch.setattr(adapter_mod, "GenerationSpanData", _MockGenerationSpanData)
    monkeypatch.setattr(adapter_mod, "FunctionSpanData", _MockFunctionSpanData)
    monkeypatch.setattr(adapter_mod, "HandoffSpanData", _MockHandoffSpanData)


@pytest.fixture(autouse=True)
def _init_context():
    """Initialize valid trace/session context for every test."""
    from observra.core.context import initialize_session, initialize_trace

    initialize_trace()
    initialize_session()


# ---------------------------------------------------------------------------
# Mock span factories
# ---------------------------------------------------------------------------


def _make_agent_span(name="test_agent", tools=None, handoffs=None, output_type="str"):
    """Create a mock span with AgentSpanData."""
    data = _MockAgentSpanData(
        name=name,
        tools=tools or [],
        handoffs=handoffs,
        output_type=output_type,
    )
    return types.SimpleNamespace(
        span_id="span-agent-001",
        trace_id="trace-001",
        parent_id=None,
        started_at="2026-02-18T10:00:00Z",
        ended_at="2026-02-18T10:00:05Z",
        error=None,
        span_data=data,
    )


def _make_generation_span(model="gpt-4o", usage=None):
    """Create a mock span with GenerationSpanData."""
    default_usage = {
        "input_tokens": 100,
        "output_tokens": 50,
        "total_tokens": 150,
        "input_tokens_details": {"cached_tokens": 10},
        "output_tokens_details": {"reasoning_tokens": 0},
    }
    data = _MockGenerationSpanData(
        model=model,
        usage=usage or default_usage,
        output=None,
        input=None,
    )
    return types.SimpleNamespace(
        span_id="span-gen-001",
        trace_id="trace-001",
        parent_id="span-agent-001",
        started_at="2026-02-18T10:00:01Z",
        ended_at="2026-02-18T10:00:02Z",
        error=None,
        span_data=data,
    )


def _make_function_span(name="calculator", input_val="2+3", output_val="5", span_id="span-func-001"):
    """Create a mock span with FunctionSpanData."""
    data = _MockFunctionSpanData(name=name, input=input_val, output=output_val)
    return types.SimpleNamespace(
        span_id=span_id,
        trace_id="trace-001",
        parent_id="span-agent-001",
        started_at="2026-02-18T10:00:01Z",
        ended_at="2026-02-18T10:00:01.500Z",
        error=None,
        span_data=data,
    )


def _make_handoff_span(from_agent="orchestrator", to_agent="specialist", error=None, parent_id="span-func-001"):
    """Create a mock span with HandoffSpanData."""
    data = _MockHandoffSpanData(from_agent=from_agent, to_agent=to_agent)
    return types.SimpleNamespace(
        span_id="span-handoff-001",
        trace_id="trace-001",
        parent_id=parent_id,
        started_at="2026-02-18T10:00:02Z",
        ended_at="2026-02-18T10:00:02Z",
        error=error,
        span_data=data,
    )


# ---------------------------------------------------------------------------
# 1. Protocol conformance
# ---------------------------------------------------------------------------


def test_openai_adapter_satisfies_protocol():
    """OpenAIAdapter must satisfy FrameworkAdapter Protocol."""
    from observra.adapters.openai.adapter import OpenAIAdapter
    from observra.core.adapter import FrameworkAdapter

    adapter = OpenAIAdapter()
    assert isinstance(adapter, FrameworkAdapter), "OpenAIAdapter does not satisfy FrameworkAdapter Protocol"
    assert adapter.framework_name == "openai"


# ---------------------------------------------------------------------------
# 2. AgentSpanData on_span_start -> session_start
# ---------------------------------------------------------------------------


def test_agent_span_emits_session_start_on_span_start():
    """on_span_start with AgentSpanData must emit session_start event."""
    from observra.adapters.openai.adapter import OpenAIAdapter

    adapter = OpenAIAdapter()
    adapter.on_span_start(_make_agent_span(name="test_agent"))

    assert len(adapter._events) == 1
    event = adapter._events[0]
    assert event.event_type == "session_start"
    assert event.agent_name == "test_agent"


# ---------------------------------------------------------------------------
# 3. AgentSpanData on_span_end -> session_end
# ---------------------------------------------------------------------------


def test_agent_span_emits_session_end_on_span_end():
    """on_span_start then on_span_end with AgentSpanData must produce session_end."""
    from observra.adapters.openai.adapter import OpenAIAdapter

    adapter = OpenAIAdapter()
    span = _make_agent_span(name="test_agent")
    adapter.on_span_start(span)
    adapter.on_span_end(span)

    event_types = [e.event_type for e in adapter._events]
    assert "session_start" in event_types
    assert "session_end" in event_types

    session_end = next(e for e in adapter._events if e.event_type == "session_end")
    assert session_end.agent_name == "test_agent"
    assert session_end.framework == "openai"


# ---------------------------------------------------------------------------
# 4. GenerationSpanData -> model_response with tokens and cost
# ---------------------------------------------------------------------------


def test_generation_span_emits_model_response_with_tokens_and_cost():
    """GenerationSpanData on_span_end must emit model_response with exact tokens and cost."""
    from observra.adapters.openai.adapter import OpenAIAdapter

    usage = {
        "input_tokens": 1000,
        "output_tokens": 500,
        "total_tokens": 1500,
        "input_tokens_details": {"cached_tokens": 100},
        "output_tokens_details": {"reasoning_tokens": 0},
    }
    adapter = OpenAIAdapter()
    adapter.on_span_end(_make_generation_span(model="gpt-4o", usage=usage))

    assert len(adapter._events) == 1
    event = adapter._events[0]
    assert event.event_type == "model_response"
    assert event.model_name == "gpt-4o"
    assert event.framework == "openai"
    assert event.data is not None
    assert event.data["input_tokens"] == 1000
    assert event.data["output_tokens"] == 500
    assert event.data["cached_tokens"] == 100
    assert event.data["cost_usd"] > 0


# ---------------------------------------------------------------------------
# 5. reasoning_tokens tracked separately
# ---------------------------------------------------------------------------


def test_generation_span_reasoning_tokens_tracked_separately():
    """reasoning_tokens must appear in model_response data when non-zero."""
    from observra.adapters.openai.adapter import OpenAIAdapter

    usage = {
        "input_tokens": 1000,
        "output_tokens": 500,
        "total_tokens": 1500,
        "input_tokens_details": {"cached_tokens": 0},
        "output_tokens_details": {"reasoning_tokens": 200},
    }
    adapter = OpenAIAdapter()
    adapter.on_span_end(_make_generation_span(model="gpt-4o", usage=usage))

    event = adapter._events[0]
    assert event.data["reasoning_tokens"] == 200


# ---------------------------------------------------------------------------
# 6. FunctionSpanData -> tool_call with duration
# ---------------------------------------------------------------------------


def test_function_span_emits_tool_call_with_duration():
    """FunctionSpanData on_span_end must emit tool_call with positive duration_ms."""
    from observra.adapters.openai.adapter import OpenAIAdapter

    adapter = OpenAIAdapter()
    adapter.on_span_end(_make_function_span(name="calculator"))

    assert len(adapter._events) == 1
    event = adapter._events[0]
    assert event.event_type == "tool_end"
    assert event.tool_name == "calculator"
    assert event.data is not None
    assert "duration_ms" in event.data
    assert event.data["duration_ms"] > 0


# ---------------------------------------------------------------------------
# 7. FunctionSpanData with capture_tool_data=True
# ---------------------------------------------------------------------------


def test_function_span_captures_tool_data_when_enabled():
    """capture_tool_data=True must include tool_args and tool_result in event data."""
    from observra.adapters.openai.adapter import OpenAIAdapter

    adapter = OpenAIAdapter(capture_tool_data=True)
    adapter.on_span_end(_make_function_span(name="lookup", input_val="pi", output_val="3.14159"))

    event = adapter._events[0]
    assert event.data is not None
    assert "tool_args" in event.data, "tool_args must be present when capture_tool_data=True"
    assert "tool_result" in event.data, "tool_result must be present when capture_tool_data=True"
    assert "pi" in event.data["tool_args"]
    assert "3.14159" in event.data["tool_result"]


# ---------------------------------------------------------------------------
# 8. FunctionSpanData with capture_tool_data=False (default)
# ---------------------------------------------------------------------------


def test_function_span_no_tool_data_when_disabled():
    """capture_tool_data=False (default) must NOT include tool_args or tool_result."""
    from observra.adapters.openai.adapter import OpenAIAdapter

    adapter = OpenAIAdapter(capture_tool_data=False)
    adapter.on_span_end(_make_function_span(name="calculator", input_val="2+3", output_val="5"))

    event = adapter._events[0]
    assert event.data is not None
    assert event.data.get("tool_args") is None, "tool_args must be None when capture_tool_data=False"
    assert event.data.get("tool_result") is None, "tool_result must be None when capture_tool_data=False"


# ---------------------------------------------------------------------------
# 9. HandoffSpanData -> handoff with source/target
# ---------------------------------------------------------------------------


def test_handoff_span_emits_handoff_event():
    """HandoffSpanData on_span_end must emit handoff event with source/target agents."""
    from observra.adapters.openai.adapter import OpenAIAdapter

    adapter = OpenAIAdapter()
    adapter.on_span_end(_make_handoff_span(from_agent="orchestrator", to_agent="specialist"))

    assert len(adapter._events) == 1
    event = adapter._events[0]
    assert event.event_type == "agent_handoff"
    assert event.data is not None
    assert event.data["source_agent"] == "orchestrator"
    assert event.data["target_agent"] == "specialist"


# ---------------------------------------------------------------------------
# 10. HandoffSpanData with error -> handoff_error
# ---------------------------------------------------------------------------


def test_handoff_error_emits_error_event():
    """HandoffSpanData with error must emit handoff AND handoff_error events."""
    from observra.adapters.openai.adapter import OpenAIAdapter

    error_obj = types.SimpleNamespace(message="connection refused")
    adapter = OpenAIAdapter()
    adapter.on_span_end(
        _make_handoff_span(
            from_agent="orchestrator",
            to_agent="specialist",
            error=error_obj,
        )
    )

    event_types = [e.event_type for e in adapter._events]
    assert "agent_handoff" in event_types, "handoff event must be emitted"
    assert "agent_handoff_error" in event_types, "handoff_error event must be emitted on error"

    handoff_error = next(e for e in adapter._events if e.event_type == "agent_handoff_error")
    assert handoff_error.data is not None
    assert handoff_error.data["source_agent"] == "orchestrator"
    assert handoff_error.data["target_agent"] == "specialist"


# ---------------------------------------------------------------------------
# 11. Handoff trigger context from parent function span
# ---------------------------------------------------------------------------


def test_handoff_trigger_context_from_parent_function_span():
    """Handoff event must include trigger_tool from parent function span by parent_id."""
    from observra.adapters.openai.adapter import OpenAIAdapter

    adapter = OpenAIAdapter()

    # Emit a function span with span_id="span-func-trigger"
    trigger_span = _make_function_span(
        name="transfer_to_specialist",
        input_val='{"reason": "needs expert"}',
        span_id="span-func-trigger",
    )
    adapter.on_span_end(trigger_span)

    # Now emit a handoff span whose parent_id matches the function span's span_id
    handoff_span = _make_handoff_span(
        from_agent="orchestrator",
        to_agent="specialist",
        parent_id="span-func-trigger",
    )
    adapter.on_span_end(handoff_span)

    handoff_event = next(e for e in adapter._events if e.event_type == "agent_handoff")
    assert handoff_event.data is not None
    assert handoff_event.data.get("trigger_tool") == "transfer_to_specialist", (
        f"Expected trigger_tool='transfer_to_specialist', got: {handoff_event.data}"
    )


# ---------------------------------------------------------------------------
# 12. Error resilience in on_span_end
# ---------------------------------------------------------------------------


def test_error_resilience_in_on_span_end():
    """on_span_end with a bad span must not raise; _error_count must increment."""
    from observra.adapters.openai.adapter import OpenAIAdapter

    class _BadSpanData:
        @property
        def nonexistent(self):
            raise RuntimeError("kaboom")

    # span_data that raises when accessed
    _bad_span = types.SimpleNamespace(  # noqa: F841
        span_id="bad-001",
        span_data=_MockAgentSpanData(name="x", tools=[], handoffs=None, output_type="str"),
    )

    # Override span_data with an object whose isinstance check raises
    # The simplest way: patch the adapter to raise via a bad span_data attribute
    # Actually, let's make the span itself raise on span_data access
    class _RaisingSpan:
        @property
        def span_data(self):
            raise AttributeError("no span_data for you")

    adapter = OpenAIAdapter()
    initial_errors = adapter._error_count
    adapter.on_span_end(_RaisingSpan())

    # No exception should propagate
    assert adapter._error_count >= initial_errors + 1, (
        f"Expected _error_count to increment; was {initial_errors}, now {adapter._error_count}"
    )


# ---------------------------------------------------------------------------
# 13. Adapter error stats increment
# ---------------------------------------------------------------------------


def test_adapter_error_stats_increment():
    """emit() failure must increment _error_count."""
    from observra.adapters.openai.adapter import OpenAIAdapter
    from observra.core.events import create_event

    adapter = OpenAIAdapter()

    # Monkey-patch _events to raise on append
    bad_list = MagicMock()
    bad_list.append.side_effect = RuntimeError("boom")
    adapter._events = bad_list

    event = create_event(event_type="test", framework="openai")
    adapter.emit(event)

    assert adapter._error_count == 1


# ---------------------------------------------------------------------------
# 14. Dropped events when disabled
# ---------------------------------------------------------------------------


def test_adapter_dropped_events_when_disabled():
    """emit() with _enabled=False must increment _dropped_events."""
    from observra.adapters.openai.adapter import OpenAIAdapter
    from observra.core.events import create_event

    adapter = OpenAIAdapter()
    adapter._enabled = False

    event = create_event(event_type="test", framework="openai")
    adapter.emit(event)

    assert adapter._dropped_events == 1


# ---------------------------------------------------------------------------
# 15. emit() routes to queue
# ---------------------------------------------------------------------------


def test_emit_routes_to_queue():
    """emit() with a queue must call queue.put_nowait with the event."""
    from observra.adapters.openai.adapter import OpenAIAdapter
    from observra.core.events import create_event

    mock_queue = MagicMock()
    adapter = OpenAIAdapter(queue=mock_queue)

    event = create_event(event_type="test", framework="openai")
    adapter.emit(event)

    mock_queue.put_nowait.assert_called_once_with(event)


# ---------------------------------------------------------------------------
# 16. cost_threshold_exceeded emitted and only-once guard
# ---------------------------------------------------------------------------


def test_cost_threshold_exceeded_emitted_and_only_once():
    """cost_threshold_exceeded must fire once when cost >= threshold; not twice."""
    from observra.adapters.openai.adapter import OpenAIAdapter

    # Large usage that will definitely exceed $0.001 threshold
    large_usage = {
        "input_tokens": 100000,
        "output_tokens": 50000,
        "total_tokens": 150000,
        "input_tokens_details": {"cached_tokens": 0},
        "output_tokens_details": {"reasoning_tokens": 0},
    }

    adapter = OpenAIAdapter(cost_threshold_usd=Decimal("0.001"))
    adapter.on_span_end(_make_generation_span(model="gpt-4o", usage=large_usage))

    # First call: must emit cost_threshold_exceeded
    event_types = [e.event_type for e in adapter._events]
    assert "cost_threshold_exceeded" in event_types, f"Expected cost_threshold_exceeded event; got: {event_types}"
    threshold_events_count = event_types.count("cost_threshold_exceeded")
    assert threshold_events_count == 1

    # Second call with same large usage: guard must prevent second emission
    adapter.on_span_end(_make_generation_span(model="gpt-4o", usage=large_usage))

    event_types_2 = [e.event_type for e in adapter._events]
    threshold_events_count_2 = event_types_2.count("cost_threshold_exceeded")
    assert threshold_events_count_2 == 1, (
        f"cost_threshold_exceeded must only fire once (only-once guard); fired {threshold_events_count_2} times"
    )


# ---------------------------------------------------------------------------
# 17. Pricing config loads OpenAI models
# ---------------------------------------------------------------------------


def test_pricing_config_loads_openai_models():
    """CostCalculator must load OpenAI pricing.json and compute non-zero cost."""
    from observra.core.cost import CostCalculator

    pricing_path = Path(__file__).resolve().parent.parent / "pricing.json"
    assert pricing_path.exists(), f"pricing.json not found at {pricing_path}"

    calculator = CostCalculator(str(pricing_path))

    # Calculate cost for 1000/500 tokens with gpt-4o
    cost = calculator.calculate_cost(
        model_name="gpt-4o",
        input_tokens=1000,
        output_tokens=500,
    )
    assert cost > 0, f"Expected non-zero cost for gpt-4o, got {cost}"


# ---------------------------------------------------------------------------
# 18. normalize_openai_tokens utility
# ---------------------------------------------------------------------------


def test_normalize_openai_tokens():
    """normalize_openai_tokens must return correct NormalizedTokens shape."""
    from observra.adapters.utils import NormalizedTokens, normalize_openai_tokens

    # Full usage dict with nested details
    usage = {
        "input_tokens": 1000,
        "output_tokens": 500,
        "total_tokens": 1500,
        "input_tokens_details": {"cached_tokens": 100},
        "output_tokens_details": {"reasoning_tokens": 50},
    }
    result = normalize_openai_tokens(usage)
    assert result is not None
    assert isinstance(result, NormalizedTokens)
    assert result.input_tokens == 1000
    assert result.output_tokens == 500
    assert result.total_tokens == 1500
    assert result.cached_tokens == 100
    assert result.reasoning_tokens == 50

    # None -> None
    assert normalize_openai_tokens(None) is None

    # Empty dict -> None
    assert normalize_openai_tokens({}) is None
