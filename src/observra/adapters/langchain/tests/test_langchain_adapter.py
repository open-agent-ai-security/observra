# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Co-located tests for the LangChain adapter.

Validates Protocol conformance, all callback types (LLM, tool, chain), all 3
token extraction paths (usage_metadata, llm_output["token_usage"], llm_output["usage"]),
streaming deduplication (on_llm_new_token no-op), error resilience, cost_threshold_exceeded
with only-once guard, queue routing, and pricing config loading.

All tests use types.SimpleNamespace to create mock LLMResult objects and run without
langchain-core installed (conftest.py stubs the module hierarchy into sys.modules).
"""

import types
import uuid
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Mock LLMResult factories
# ---------------------------------------------------------------------------


def _make_llm_result_with_usage_metadata(input_tokens=500, output_tokens=200, model="gpt-4o"):
    """Mock LLMResult with modern usage_metadata path (provider-agnostic)."""
    mock_message = types.SimpleNamespace(
        usage_metadata={
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        },
        response_metadata={"model_name": model},
    )
    mock_gen = types.SimpleNamespace(message=mock_message, text="Test response")
    return types.SimpleNamespace(
        generations=[[mock_gen]],
        llm_output={"model_name": model},
    )


def _make_llm_result_openai_legacy(input_tokens=500, output_tokens=200, model="gpt-4o"):
    """Mock LLMResult with ChatOpenAI legacy llm_output['token_usage'] path."""
    mock_gen = types.SimpleNamespace(text="Test response")
    # No message attribute (no usage_metadata)
    return types.SimpleNamespace(
        generations=[[mock_gen]],
        llm_output={
            "model_name": model,
            "token_usage": {
                "prompt_tokens": input_tokens,
                "completion_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
            },
        },
    )


def _make_llm_result_anthropic(input_tokens=500, output_tokens=200, model="claude-sonnet-4-5"):
    """Mock LLMResult with ChatAnthropic llm_output['usage'] path."""
    mock_gen = types.SimpleNamespace(text="Test response")
    return types.SimpleNamespace(
        generations=[[mock_gen]],
        llm_output={
            "model_name": model,
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            },
        },
    )


def _make_run_id():
    """Generate a fresh UUID run_id for test isolation."""
    return uuid.uuid4()


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


def test_langchain_adapter_satisfies_protocol():
    """LangChainAdapter must satisfy FrameworkAdapter Protocol with framework_name='langgraph'."""
    from observra.adapters.langchain.adapter import LangChainAdapter
    from observra.core.adapter import FrameworkAdapter

    adapter = LangChainAdapter()
    assert isinstance(adapter, FrameworkAdapter), "LangChainAdapter does not satisfy FrameworkAdapter Protocol"
    assert adapter.framework_name == "langgraph"


# ---------------------------------------------------------------------------
# 2. on_llm_end — usage_metadata path (modern, provider-agnostic)
# ---------------------------------------------------------------------------


def test_on_llm_end_emits_model_response_with_usage_metadata():
    """on_llm_end with usage_metadata must emit model_response with correct tokens and cost."""
    from observra.adapters.langchain.adapter import LangChainAdapter

    adapter = LangChainAdapter()
    run_id = _make_run_id()
    response = _make_llm_result_with_usage_metadata(input_tokens=500, output_tokens=200, model="gpt-4o")

    adapter.on_chat_model_start({"kwargs": {"model_name": "gpt-4o"}}, [[]], run_id=run_id)
    adapter.on_llm_end(response, run_id=run_id)

    assert len(adapter._events) == 1
    event = adapter._events[0]
    assert event.event_type == "model_response"
    assert event.model_name == "gpt-4o"
    assert event.framework == "langgraph"
    assert event.data is not None
    assert event.data["input_tokens"] == 500
    assert event.data["output_tokens"] == 200
    assert event.data["cost_usd"] > 0


# ---------------------------------------------------------------------------
# 3. on_llm_end — OpenAI legacy llm_output["token_usage"] path
# ---------------------------------------------------------------------------


def test_on_llm_end_with_openai_legacy_llm_output():
    """on_llm_end with llm_output['token_usage'] must map prompt_tokens/completion_tokens correctly."""
    from observra.adapters.langchain.adapter import LangChainAdapter

    adapter = LangChainAdapter()
    run_id = _make_run_id()
    response = _make_llm_result_openai_legacy(input_tokens=300, output_tokens=100, model="gpt-4o")

    adapter.on_llm_end(response, run_id=run_id)

    assert len(adapter._events) == 1
    event = adapter._events[0]
    assert event.event_type == "model_response"
    assert event.data is not None
    assert event.data["input_tokens"] == 300
    assert event.data["output_tokens"] == 100
    assert event.data["cost_usd"] > 0


# ---------------------------------------------------------------------------
# 4. on_llm_end — Anthropic llm_output["usage"] path
# ---------------------------------------------------------------------------


def test_on_llm_end_with_anthropic_llm_output():
    """on_llm_end with llm_output['usage'] must map input_tokens/output_tokens correctly."""
    from observra.adapters.langchain.adapter import LangChainAdapter

    adapter = LangChainAdapter()
    run_id = _make_run_id()
    response = _make_llm_result_anthropic(input_tokens=600, output_tokens=250, model="claude-sonnet-4-5")

    adapter.on_llm_end(response, run_id=run_id)

    assert len(adapter._events) == 1
    event = adapter._events[0]
    assert event.event_type == "model_response"
    assert event.data is not None
    assert event.data["input_tokens"] == 600
    assert event.data["output_tokens"] == 250
    assert event.data["cost_usd"] > 0


# ---------------------------------------------------------------------------
# 5. on_llm_new_token — streaming dedup no-op
# ---------------------------------------------------------------------------


def test_on_llm_new_token_is_noop():
    """on_llm_new_token must not emit any events (streaming deduplication)."""
    from observra.adapters.langchain.adapter import LangChainAdapter

    adapter = LangChainAdapter()
    run_id = _make_run_id()

    adapter.on_llm_new_token("Hello", run_id=run_id)
    adapter.on_llm_new_token(" world", run_id=run_id)
    adapter.on_llm_new_token("!", run_id=run_id)

    assert len(adapter._events) == 0, f"on_llm_new_token must not emit events; got {len(adapter._events)}"


# ---------------------------------------------------------------------------
# 6. on_llm_end — no token data
# ---------------------------------------------------------------------------


def test_on_llm_end_without_tokens():
    """on_llm_end with empty llm_output must emit model_response without token/cost fields."""
    from observra.adapters.langchain.adapter import LangChainAdapter

    adapter = LangChainAdapter()
    run_id = _make_run_id()
    # No usage_metadata, no token_usage, no usage
    response = types.SimpleNamespace(
        generations=[[types.SimpleNamespace(text="response")]],
        llm_output={},
    )

    adapter.on_llm_end(response, run_id=run_id)

    assert len(adapter._events) == 1
    event = adapter._events[0]
    assert event.event_type == "model_response"
    # Token/cost fields are always present but None when no usage data
    assert event.data is not None
    assert event.data.get("input_tokens") is None
    assert event.data.get("cost_usd") is None


# ---------------------------------------------------------------------------
# 7. on_chat_model_start — model name capture
# ---------------------------------------------------------------------------


def test_on_chat_model_start_captures_model_name():
    """on_chat_model_start must store model name so on_llm_end uses it."""
    from observra.adapters.langchain.adapter import LangChainAdapter

    adapter = LangChainAdapter()
    run_id = _make_run_id()
    response = _make_llm_result_with_usage_metadata(model="gpt-4o-mini")

    adapter.on_chat_model_start({"kwargs": {"model_name": "gpt-4o-mini"}}, [[]], run_id=run_id)
    adapter.on_llm_end(response, run_id=run_id)

    event = adapter._events[0]
    assert event.model_name == "gpt-4o-mini"


# ---------------------------------------------------------------------------
# 8. on_llm_start — model name capture for legacy LLMs
# ---------------------------------------------------------------------------


def test_on_llm_start_captures_model_name_for_legacy():
    """on_llm_start must capture model name by run_id for on_llm_end retrieval."""
    from observra.adapters.langchain.adapter import LangChainAdapter

    adapter = LangChainAdapter()
    run_id = _make_run_id()
    response = _make_llm_result_openai_legacy(model="gpt-4o")

    adapter.on_llm_start({"kwargs": {"model_name": "gpt-4o"}}, ["Hello"], run_id=run_id)
    adapter.on_llm_end(response, run_id=run_id)

    event = adapter._events[0]
    assert event.model_name == "gpt-4o"


# ---------------------------------------------------------------------------
# 9. Tool start/end — events with duration
# ---------------------------------------------------------------------------


def test_tool_start_end_emits_events_with_duration():
    """on_tool_start then on_tool_end must emit tool_start and tool_end with duration_ms > 0."""
    from observra.adapters.langchain.adapter import LangChainAdapter

    adapter = LangChainAdapter()
    run_id = _make_run_id()

    adapter.on_tool_start({"name": "calculator"}, '{"a": 2, "b": 3}', run_id=run_id)
    adapter.on_tool_end("5", run_id=run_id)

    event_types = [e.event_type for e in adapter._events]
    assert "tool_start" in event_types
    assert "tool_end" in event_types

    tool_end = next(e for e in adapter._events if e.event_type == "tool_end")
    assert tool_end.data is not None
    assert "duration_ms" in tool_end.data
    assert tool_end.data["duration_ms"] >= 0


# ---------------------------------------------------------------------------
# 10. Tool data captured when enabled
# ---------------------------------------------------------------------------


def test_tool_data_captured_when_enabled():
    """capture_tool_data=True must include tool_args in tool_start and tool_result in tool_end."""
    from observra.adapters.langchain.adapter import LangChainAdapter

    adapter = LangChainAdapter(capture_tool_data=True)
    run_id = _make_run_id()

    adapter.on_tool_start({"name": "lookup"}, '{"key": "pi"}', run_id=run_id)
    adapter.on_tool_end("3.14159", run_id=run_id)

    tool_start = next(e for e in adapter._events if e.event_type == "tool_start")
    tool_end = next(e for e in adapter._events if e.event_type == "tool_end")

    assert tool_start.data is not None
    assert "tool_args" in tool_start.data

    assert tool_end.data is not None
    assert "tool_result" in tool_end.data


# ---------------------------------------------------------------------------
# 11. Tool data not captured by default
# ---------------------------------------------------------------------------


def test_tool_data_not_captured_by_default():
    """capture_tool_data=False (default) must NOT include tool_args or tool_result."""
    from observra.adapters.langchain.adapter import LangChainAdapter

    adapter = LangChainAdapter(capture_tool_data=False)
    run_id = _make_run_id()

    adapter.on_tool_start({"name": "calculator"}, '{"a": 2, "b": 3}', run_id=run_id)
    adapter.on_tool_end("5", run_id=run_id)

    tool_start = next(e for e in adapter._events if e.event_type == "tool_start")
    tool_end = next(e for e in adapter._events if e.event_type == "tool_end")

    # tool_args/tool_result always present but None when capture_tool_data=False
    assert tool_start.data is not None
    assert tool_start.data.get("tool_args") is None
    assert tool_end.data is not None
    assert tool_end.data.get("tool_result") is None


# ---------------------------------------------------------------------------
# 12. Chain start emits chain_start event
# ---------------------------------------------------------------------------


def test_chain_start_emits_agent_start_event():
    """on_chain_start with parent_run_id (nested) must emit agent_start event with framework='langgraph'."""
    from observra.adapters.langchain.adapter import LangChainAdapter

    adapter = LangChainAdapter()
    run_id = _make_run_id()
    parent_run_id = _make_run_id()  # non-None parent = nested chain

    adapter.on_chain_start(
        {"name": "test_chain"},
        {},
        run_id=run_id,
        parent_run_id=parent_run_id,
    )

    assert len(adapter._events) == 1
    event = adapter._events[0]
    assert event.event_type == "agent_start"
    assert event.framework == "langgraph"


# ---------------------------------------------------------------------------
# 13. Top-level chain initializes context
# ---------------------------------------------------------------------------


def test_top_level_chain_initializes_context():
    """on_chain_start with parent_run_id=None must initialize trace context."""
    from observra.adapters.langchain.adapter import LangChainAdapter

    adapter = LangChainAdapter()
    run_id = _make_run_id()

    adapter.on_chain_start(
        {"name": "langchain_test_graph"},
        {},
        run_id=run_id,
        parent_run_id=None,
    )

    assert len(adapter._events) == 1
    event = adapter._events[0]
    assert event.event_type == "session_start"
    # Verify trace context is initialized (event has valid trace_id)
    assert event.trace_id is not None
    assert len(event.trace_id) > 0


# ---------------------------------------------------------------------------
# 14. Error resilience in callbacks
# ---------------------------------------------------------------------------


def test_error_resilience_in_callbacks():
    """Callbacks that raise internally must not propagate; _error_count must increment."""
    from observra.adapters.langchain.adapter import LangChainAdapter

    adapter = LangChainAdapter()
    run_id = _make_run_id()
    initial_error_count = adapter._error_count

    # A bad response object that raises on attribute access
    class _RaisingResponse:
        @property
        def generations(self):
            raise RuntimeError("boom")

        @property
        def llm_output(self):
            raise RuntimeError("boom")

    # Should not raise
    adapter.on_llm_end(_RaisingResponse(), run_id=run_id)

    assert adapter._error_count >= initial_error_count + 1, (
        f"Expected _error_count to increment; was {initial_error_count}, now {adapter._error_count}"
    )


# ---------------------------------------------------------------------------
# 15. on_tool_error — emits tool_error event
# ---------------------------------------------------------------------------


def test_on_tool_error_emits_tool_error_event():
    """on_tool_start then on_tool_error must emit tool_error event with error string."""
    from observra.adapters.langchain.adapter import LangChainAdapter

    adapter = LangChainAdapter()
    run_id = _make_run_id()

    adapter.on_tool_start({"name": "failing_tool"}, '{"input": "bad"}', run_id=run_id)
    adapter.on_tool_error(ValueError("Something went wrong"), run_id=run_id)

    event_types = [e.event_type for e in adapter._events]
    assert "tool_start" in event_types
    assert "tool_error" in event_types

    tool_error = next(e for e in adapter._events if e.event_type == "tool_error")
    assert tool_error.data is not None
    assert "error_message" in tool_error.data
    assert "Something went wrong" in tool_error.data["error_message"]


# ---------------------------------------------------------------------------
# 16. cost_threshold_exceeded — emitted once (only-once guard)
# ---------------------------------------------------------------------------


def test_cost_threshold_exceeded_emitted_once():
    """cost_threshold_exceeded must fire exactly once even with multiple expensive calls."""
    from observra.adapters.langchain.adapter import LangChainAdapter

    # Large token usage to exceed $0.001 threshold
    adapter = LangChainAdapter(cost_threshold_usd=Decimal("0.001"))
    run_id_1 = _make_run_id()
    run_id_2 = _make_run_id()

    large_response = _make_llm_result_with_usage_metadata(input_tokens=100000, output_tokens=50000, model="gpt-4o")

    # First call — should emit cost_threshold_exceeded
    adapter.on_llm_end(large_response, run_id=run_id_1)

    event_types_1 = [e.event_type for e in adapter._events]
    assert "cost_threshold_exceeded" in event_types_1, f"Expected cost_threshold_exceeded; got: {event_types_1}"
    assert event_types_1.count("cost_threshold_exceeded") == 1

    # Second call — guard must prevent second emission
    adapter.on_llm_end(large_response, run_id=run_id_2)

    event_types_2 = [e.event_type for e in adapter._events]
    assert event_types_2.count("cost_threshold_exceeded") == 1, (
        f"cost_threshold_exceeded must fire only once; fired {event_types_2.count('cost_threshold_exceeded')} times"
    )


# ---------------------------------------------------------------------------
# 17. emit() routes to queue
# ---------------------------------------------------------------------------


def test_emit_routes_to_queue():
    """emit() with a queue must call queue.put_nowait with the event."""
    from observra.adapters.langchain.adapter import LangChainAdapter
    from observra.core.events import create_event

    mock_queue = MagicMock()
    adapter = LangChainAdapter(queue=mock_queue)

    event = create_event(event_type="test", framework="langgraph")
    adapter.emit(event)

    mock_queue.put_nowait.assert_called_once_with(event)


# ---------------------------------------------------------------------------
# 18. Pricing config loads and computes non-zero cost
# ---------------------------------------------------------------------------


def test_pricing_config_loads_models():
    """CostCalculator must load LangChain pricing.json and compute non-zero cost for gpt-4o."""
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
# 19. normalize_langchain_tokens — all paths
# ---------------------------------------------------------------------------


def test_normalize_langchain_tokens_all_paths():
    """normalize_langchain_tokens must handle all 3 extraction paths, None, and empty response."""
    from observra.adapters.utils import NormalizedTokens, normalize_langchain_tokens

    # (a) usage_metadata path
    result_a = normalize_langchain_tokens(_make_llm_result_with_usage_metadata(input_tokens=500, output_tokens=200))
    assert result_a is not None
    assert isinstance(result_a, NormalizedTokens)
    assert result_a.input_tokens == 500
    assert result_a.output_tokens == 200

    # (b) llm_output["token_usage"] path (ChatOpenAI legacy)
    result_b = normalize_langchain_tokens(_make_llm_result_openai_legacy(input_tokens=300, output_tokens=100))
    assert result_b is not None
    assert isinstance(result_b, NormalizedTokens)
    assert result_b.input_tokens == 300
    assert result_b.output_tokens == 100

    # (c) llm_output["usage"] path (ChatAnthropic)
    result_c = normalize_langchain_tokens(_make_llm_result_anthropic(input_tokens=600, output_tokens=250))
    assert result_c is not None
    assert isinstance(result_c, NormalizedTokens)
    assert result_c.input_tokens == 600
    assert result_c.output_tokens == 250

    # (d) None input -> None
    assert normalize_langchain_tokens(None) is None

    # (e) Empty response (no token data) -> None
    empty_response = types.SimpleNamespace(generations=[[]], llm_output={})
    result_e = normalize_langchain_tokens(empty_response)
    assert result_e is None
