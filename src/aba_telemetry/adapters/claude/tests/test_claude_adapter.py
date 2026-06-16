"""Co-located tests for the Claude adapter.

Validates Protocol conformance, all 5 hook callbacks, wrap_stream() for
model_response and session_end events, cost_threshold_exceeded emission
with only-once guard, token estimation, safe_serialize, error stats,
dropped events, queue routing, pricing config loading, native/estimated
token detection, and exception resilience.

All tests mock the Claude SDK to run without the optional claude-agent-sdk
dependency. This file is the canonical Phase 11 test suite.

Note on tiktoken: tiktoken's C extension is not compatible with Python 3.14+
(segfaults on initialization). Tests that exercise estimate_tokens() patch the
module-level _TOKENIZER to a mock tokenizer so the char/4 fallback or a mock
encode path is used, ensuring tests run reliably across Python versions.
"""

import time
import types
import warnings
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import aba_telemetry.adapters.utils as utils_module
from aba_telemetry.core.context import initialize_session, initialize_trace
from aba_telemetry.core.events import create_event
from aba_telemetry.adapters.claude.adapter import ClaudeAdapter
from aba_telemetry.adapters.utils import estimate_tokens, safe_serialize


# ---------------------------------------------------------------------------
# Global session fixture — valid context required for create_event()
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def session_context():
    """Initialize valid trace/session/span context for every test."""
    initialize_trace()
    initialize_session()


# ---------------------------------------------------------------------------
# Helper: suppress the startup warning that fires on every ClaudeAdapter()
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def suppress_startup_warning():
    """Suppress the 'token counts are estimated' startup warning in tests."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        yield


# ---------------------------------------------------------------------------
# Helper: mock tokenizer that avoids loading tiktoken C extension
# ---------------------------------------------------------------------------

class _MockTokenizer:
    """Minimal stand-in for tiktoken encoder for test isolation."""

    def encode(self, text: str) -> list:
        # Simple word-count approximation (deterministic for testing)
        return text.split() if text else []


@pytest.fixture(autouse=True)
def mock_tiktoken():
    """Patch the module-level _TOKENIZER to avoid tiktoken C extension crash.

    tiktoken's Rust/C extension segfaults on Python 3.14. We patch the cached
    tokenizer to a mock so estimate_tokens() uses the mock encode path rather
    than loading the real extension. The mock encode() returns a list (like
    tiktoken does), so len() calls produce a valid integer result.
    """
    original = utils_module._TOKENIZER
    utils_module._TOKENIZER = _MockTokenizer()
    yield
    utils_module._TOKENIZER = original


# ---------------------------------------------------------------------------
# 1. Protocol conformance
# ---------------------------------------------------------------------------

def test_claude_adapter_satisfies_protocol():
    """ClaudeAdapter must satisfy the FrameworkAdapter Protocol."""
    from aba_telemetry.core.adapter import FrameworkAdapter
    adapter = ClaudeAdapter(queue=None)
    assert isinstance(adapter, FrameworkAdapter), (
        "ClaudeAdapter does not satisfy FrameworkAdapter Protocol"
    )
    assert adapter.framework_name == "claude"


# ---------------------------------------------------------------------------
# 2. PreToolUse hook returns {} and emits before_tool event
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pre_tool_use_returns_empty_dict():
    """_on_pre_tool_use must return {} and emit a before_tool event."""
    adapter = ClaudeAdapter(queue=None)
    result = await adapter._on_pre_tool_use(
        {"tool_name": "test_tool", "tool_input": {"key": "val"}},
        "tool-123",
        None,
    )
    assert result == {}, f"Expected {{}}, got {result!r}"

    assert len(adapter._events) == 1
    event = adapter._events[0]
    assert event.event_type == "tool_start"
    assert event.tool_name == "test_tool"
    assert event.framework == "claude"


# ---------------------------------------------------------------------------
# 3. PostToolUse hook returns {} with duration
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_post_tool_use_returns_empty_dict_with_duration():
    """_on_post_tool_use must return {} and emit after_tool with duration_ms."""
    adapter = ClaudeAdapter(queue=None)
    # Simulate 500ms elapsed since PreToolUse
    adapter._tool_start_times["tool-123"] = time.monotonic() - 0.5

    result = await adapter._on_post_tool_use(
        {"tool_name": "test_tool", "tool_input": {}, "tool_response": "result"},
        "tool-123",
        None,
    )
    assert result == {}, f"Expected {{}}, got {result!r}"

    events = adapter._events
    assert len(events) == 1
    event = events[0]
    assert event.event_type == "tool_end"
    assert event.data is not None
    assert "duration_ms" in event.data
    # Allow 200ms tolerance (500ms simulated, events have overhead)
    assert 300 <= event.data["duration_ms"] <= 700, (
        f"Expected ~500ms duration, got {event.data['duration_ms']:.1f}ms"
    )


# ---------------------------------------------------------------------------
# 4. UserPromptSubmit hook
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_user_prompt_submit_returns_empty_dict():
    """_on_user_prompt_submit must return {} and emit user_prompt event."""
    adapter = ClaudeAdapter(queue=None)
    result = await adapter._on_user_prompt_submit(
        {"prompt": "Hello, Claude!"},
        None,
        None,
    )
    assert result == {}, f"Expected {{}}, got {result!r}"

    events = adapter._events
    assert len(events) == 1
    event = events[0]
    assert event.event_type == "user_message"
    assert event.data is not None
    assert event.data.get("user_message_text") == "Hello, Claude!"


# ---------------------------------------------------------------------------
# 5. Stop hook
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stop_returns_empty_dict():
    """_on_stop must return {} and emit agent_stop event."""
    adapter = ClaudeAdapter(queue=None)
    result = await adapter._on_stop({"stop_hook_active": True}, None, None)
    assert result == {}, f"Expected {{}}, got {result!r}"

    events = adapter._events
    assert len(events) == 1
    assert events[0].event_type == "agent_end"


# ---------------------------------------------------------------------------
# 6. SubagentStop hook
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_subagent_stop_returns_empty_dict():
    """_on_subagent_stop must return {} and emit subagent_stop event."""
    adapter = ClaudeAdapter(queue=None)
    result = await adapter._on_subagent_stop(
        {"stop_hook_active": True, "agent_id": "sub-1"},
        None,
        None,
    )
    assert result == {}, f"Expected {{}}, got {result!r}"

    events = adapter._events
    assert len(events) == 1
    assert events[0].event_type == "agent_end"


# ---------------------------------------------------------------------------
# 7. estimate_tokens uses tiktoken or fallback
# ---------------------------------------------------------------------------

def test_estimate_tokens_uses_tiktoken_or_fallback():
    """estimate_tokens() must return positive integers for valid text.

    The mock_tiktoken fixture patches _TOKENIZER to a mock encoder that uses
    word splitting — this confirms the tokenizer code path (len(tokenizer.encode(text)))
    is exercised. The tiktoken C extension is not available on Python 3.14 so we
    validate the function contract: positive int output for non-empty text.
    """
    result = estimate_tokens("Hello, world!")
    assert isinstance(result, int), "estimate_tokens must return int"
    assert result > 0, "estimate_tokens must return positive int for non-empty text"

    empty_result = estimate_tokens("")
    assert isinstance(empty_result, int)
    assert empty_result >= 0

    # For a long repetitive string, we expect a meaningful count
    long_text = " ".join(["word"] * 200)  # 200 tokens via word-split mock
    long_result = estimate_tokens(long_text)
    assert long_result > 10, (
        f"estimate_tokens for 200-word text should be > 10, got {long_result}"
    )


# ---------------------------------------------------------------------------
# 8. safe_serialize shared utility
# ---------------------------------------------------------------------------

def test_safe_serialize_shared_utility():
    """safe_serialize() must handle dicts, strings, and truncate long text."""
    dict_result = safe_serialize({"key": "value"})
    assert isinstance(dict_result, str)
    assert "key" in dict_result

    short_result = safe_serialize("short text")
    assert short_result == "short text"

    long_text = "x" * 10000
    long_result = safe_serialize(long_text)
    # Default max_length=4096, truncation suffix adds a few dozen chars
    assert len(long_result) <= 4096 + 50, (
        f"Truncated safe_serialize should be <= 4146 chars, got {len(long_result)}"
    )


# ---------------------------------------------------------------------------
# 9. Error stats increment on emit() failure
# ---------------------------------------------------------------------------

def test_adapter_error_stats_increment():
    """emit() failure must increment error_count; get_adapter_stats() reflects it."""
    adapter = ClaudeAdapter(queue=None)

    # Monkey-patch _events to raise on append
    bad_list = MagicMock()
    bad_list.append.side_effect = RuntimeError("boom")
    adapter._events = bad_list

    event = create_event(event_type="test", framework="claude")
    adapter.emit(event)

    assert adapter._error_count == 1

    stats = adapter.get_adapter_stats()
    assert stats["error_count"] == 1
    assert stats["framework"] == "claude"


# ---------------------------------------------------------------------------
# 10. Dropped events when disabled
# ---------------------------------------------------------------------------

def test_adapter_dropped_events_when_disabled():
    """emit() with _enabled=False must increment _dropped_events."""
    adapter = ClaudeAdapter(queue=None)
    adapter._enabled = False

    event = create_event(event_type="test", framework="claude")
    adapter.emit(event)

    assert adapter._dropped_events == 1


# ---------------------------------------------------------------------------
# 11. emit() routes to queue
# ---------------------------------------------------------------------------

def test_emit_routes_to_queue():
    """emit() with a queue must call queue.put_nowait with the event."""
    mock_queue = MagicMock()
    adapter = ClaudeAdapter(queue=mock_queue)

    event = create_event(event_type="test", framework="claude")
    adapter.emit(event)

    mock_queue.put_nowait.assert_called_once_with(event)


# ---------------------------------------------------------------------------
# 12. Pricing config loads Claude models
# ---------------------------------------------------------------------------

def test_pricing_config_loads_claude_models():
    """CostCalculator must load Claude pricing and compute non-zero costs."""
    from aba_telemetry.core.cost import CostCalculator

    pricing_path = Path(__file__).resolve().parent.parent / "pricing.json"
    calculator = CostCalculator(str(pricing_path))

    # Verify key Claude models are present
    assert "claude-opus-4-6" in calculator._pricing, "claude-opus-4-6 not in pricing"
    assert "claude-sonnet-4-6" in calculator._pricing, "claude-sonnet-4-6 not in pricing"
    assert "claude-haiku-4-5" in calculator._pricing, "claude-haiku-4-5 not in pricing"

    # Calculate cost for 1000 input + 500 output with claude-sonnet-4-6
    cost = calculator.calculate_cost(
        model_name="claude-sonnet-4-6",
        input_tokens=1000,
        output_tokens=500,
    )
    assert cost > 0, f"Expected non-zero cost for claude-sonnet-4-6, got {cost}"


# ---------------------------------------------------------------------------
# 13. _extract_tokens_or_estimate — native detection
# ---------------------------------------------------------------------------

def test_extract_tokens_or_estimate_native_detection():
    """Native token fields must be returned with is_estimated=False."""
    adapter = ClaudeAdapter(queue=None)
    count, is_estimated = adapter._extract_tokens_or_estimate(
        {"input_tokens": 42}, "some text"
    )
    assert count == 42, f"Expected 42 native tokens, got {count}"
    assert is_estimated is False, "Native tokens should set is_estimated=False"


# ---------------------------------------------------------------------------
# 14. _extract_tokens_or_estimate — fallback estimation
# ---------------------------------------------------------------------------

def test_extract_tokens_or_estimate_fallback():
    """Empty input_data must fall back to estimation with is_estimated=True."""
    adapter = ClaudeAdapter(queue=None)
    count, is_estimated = adapter._extract_tokens_or_estimate({}, "some text")
    assert count > 0, "Estimated count must be positive"
    assert is_estimated is True, "Fallback estimation should set is_estimated=True"


# ---------------------------------------------------------------------------
# 15. Hook exception still returns {}
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_hook_exception_still_returns_empty_dict():
    """Hook exceptions must be caught — callback must still return {}."""
    adapter = ClaudeAdapter(queue=None)
    # Monkey-patch emit to raise
    adapter.emit = MagicMock(side_effect=RuntimeError("bad emit"))

    result = await adapter._on_pre_tool_use({"tool_name": "tool"}, "id-1", None)
    assert result == {}, f"Expected {{}}, got {result!r}"


# ---------------------------------------------------------------------------
# 16. wrap_stream() emits model_response and session_end
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_wrap_stream_emits_model_response_for_text_blocks():
    """wrap_stream() must emit model_response for text blocks and session_end from ResultMessage."""
    adapter = ClaudeAdapter(queue=None)

    # Mock text content block
    text_block = types.SimpleNamespace(type="text", text="Hello from Claude")

    # Mock AssistantMessage
    assistant_msg = types.SimpleNamespace(content=[text_block])

    # Mock ResultMessage (detected via total_cost_usd attribute)
    result_msg = types.SimpleNamespace(
        total_cost_usd=0.005,
        num_turns=1,
        is_error=False,
        session_id="test-session",
        usage=None,
    )

    async def mock_stream():
        yield assistant_msg
        yield result_msg

    # Collect yielded messages
    yielded = []
    async for msg in adapter.wrap_stream(mock_stream()):
        yielded.append(msg)

    # Both messages must be yielded unchanged (pass-through)
    assert len(yielded) == 2
    assert yielded[0] is assistant_msg
    assert yielded[1] is result_msg

    # Check emitted events
    event_types = [e.event_type for e in adapter._events]
    assert "model_response" in event_types, f"Expected model_response event, got: {event_types}"
    assert "session_end" in event_types, f"Expected session_end event, got: {event_types}"

    # Verify model_response event content
    model_response_events = [e for e in adapter._events if e.event_type == "model_response"]
    assert len(model_response_events) == 1
    mr_event = model_response_events[0]
    assert mr_event.data is not None
    assert "Hello from Claude" in mr_event.data.get("response_text", ""), (
        f"Expected 'Hello from Claude' in response_text, got: {mr_event.data}"
    )
    assert mr_event.data.get("estimated") is True, (
        "model_response estimated flag must be True (no native token counts)"
    )

    # Verify session_end event content
    session_end_events = [e for e in adapter._events if e.event_type == "session_end"]
    assert len(session_end_events) == 1
    se_event = session_end_events[0]
    assert se_event.data is not None
    assert se_event.data.get("session_cost_usd") == 0.005, (
        f"Expected session_cost_usd=0.005, got: {se_event.data.get('session_cost_usd')}"
    )
    assert se_event.data.get("estimated") is False, (
        "session_end from ResultMessage must have estimated=False (exact SDK cost)"
    )


# ---------------------------------------------------------------------------
# 17. wrap_stream() exception does not interrupt stream
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_wrap_stream_exception_does_not_interrupt_stream():
    """Telemetry errors in wrap_stream() must not interrupt the stream."""
    adapter = ClaudeAdapter(queue=None)
    # Make emit raise
    adapter.emit = MagicMock(side_effect=RuntimeError("bad emit"))

    text_block = types.SimpleNamespace(type="text", text="Test response")
    assistant_msg = types.SimpleNamespace(content=[text_block])

    async def mock_stream():
        yield assistant_msg

    yielded = []
    async for msg in adapter.wrap_stream(mock_stream()):
        yielded.append(msg)

    # Stream must not be interrupted — message must still be yielded
    assert len(yielded) == 1
    assert yielded[0] is assistant_msg


# ---------------------------------------------------------------------------
# 18. cost_threshold_exceeded emitted once, only-once guard verified
# ---------------------------------------------------------------------------

def test_cost_threshold_exceeded_emitted_when_session_cost_exceeds_threshold():
    """cost_threshold_exceeded must fire once when cost >= threshold; not twice."""
    adapter = ClaudeAdapter(queue=None, cost_threshold_usd=Decimal("0.001"))

    # First ResultMessage — exceeds threshold
    result_msg_1 = types.SimpleNamespace(
        total_cost_usd=0.005,
        num_turns=1,
        is_error=False,
        session_id="test-session",
        usage=None,
    )
    adapter.handle_result_message(result_msg_1)

    event_types_1 = [e.event_type for e in adapter._events]
    assert "session_end" in event_types_1, "session_end must be emitted"
    assert "cost_threshold_exceeded" in event_types_1, (
        "cost_threshold_exceeded must be emitted when cost >= threshold"
    )

    # Verify cost_threshold_exceeded event data (hot path: strings stripped, but numerics preserved)
    threshold_events = [e for e in adapter._events if e.event_type == "cost_threshold_exceeded"]
    assert len(threshold_events) == 1
    te = threshold_events[0]
    assert te.data is not None
    assert te.data.get("session_cost_usd") == 0.005, (
        f"Expected session_cost_usd=0.005, got {te.data.get('session_cost_usd')}"
    )
    assert te.data.get("threshold_usd") == 0.001, (
        f"Expected threshold_usd=0.001, got {te.data.get('threshold_usd')}"
    )
    assert te.data.get("estimated") is False, (
        "cost_threshold_exceeded estimated flag must be False"
    )
    # Note: 'message' field is stripped by hot-path processing (cost_threshold_exceeded is HOT_PATH)

    event_count_after_first = len(adapter._events)

    # Second ResultMessage — also exceeds threshold, but only-once guard prevents re-emission
    result_msg_2 = types.SimpleNamespace(
        total_cost_usd=0.010,
        num_turns=2,
        is_error=False,
        session_id="test-session",
        usage=None,
    )
    adapter.handle_result_message(result_msg_2)

    event_types_2 = [e.event_type for e in adapter._events]
    new_threshold_events = [e for e in adapter._events if e.event_type == "cost_threshold_exceeded"]
    assert len(new_threshold_events) == 1, (
        "cost_threshold_exceeded must only fire once (only-once guard)"
    )
    # session_end should fire again on second call
    assert event_types_2.count("session_end") == 2, (
        "session_end must fire for each ResultMessage"
    )
