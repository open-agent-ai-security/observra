"""Unit tests for @tool and @model_call instrumentation decorators.

Note on tiktoken: tiktoken's C extension segfaults on Python 3.14+.
The mock_tiktoken fixture patches the cached _TOKENIZER to a lightweight
mock so estimate_tokens() uses the mock encode path rather than loading
the real extension. This ensures tests run reliably across Python versions.
"""

import asyncio
import pytest
from unittest.mock import MagicMock, patch

import observra
import observra.adapters.utils as utils_module
from observra import log
from observra.core.dedup import reset_dedup
from observra.core.events import EventType


# ---------------------------------------------------------------------------
# Mock tokenizer (avoids tiktoken C extension crash on Python 3.14)
# ---------------------------------------------------------------------------

class _MockTokenizer:
    """Minimal stand-in for tiktoken encoder for test isolation."""
    def encode(self, text: str) -> list:
        return text.split() if text else []


@pytest.fixture(autouse=True)
def mock_tiktoken():
    """Patch _TOKENIZER to prevent tiktoken C extension from loading."""
    original = utils_module._TOKENIZER
    utils_module._TOKENIZER = _MockTokenizer()
    yield
    utils_module._TOKENIZER = original


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FakeQueue:
    """Minimal queue stub that records put_nowait calls."""

    def __init__(self):
        self.events = []

    def put_nowait(self, event):
        self.events.append(event)

    def get_stats(self):
        return {"enqueued": len(self.events), "dropped": 0, "current_size": len(self.events)}


@pytest.fixture(autouse=True)
def _reset_state():
    """Reset log and dedup state between tests."""
    log._framework = "unknown"
    log._threshold_emitted_var.set(False)
    reset_dedup()
    yield
    log._framework = "unknown"


@pytest.fixture
def fake_queue():
    """Patch log module queue and return FakeQueue for inspection."""
    q = FakeQueue()
    proxy = MagicMock()
    proxy.put_nowait = q.put_nowait
    proxy.get_stats = q.get_stats
    with patch("observra.log._get_queue", return_value=proxy):
        yield q


# ---------------------------------------------------------------------------
# @tool — sync
# ---------------------------------------------------------------------------

def test_tool_decorator_bare(fake_queue):
    """@tool (no parens) emits tool_start + tool_end."""
    @observra.tool
    def my_func(x):
        return x * 2

    result = my_func(5)
    assert result == 10

    events = fake_queue.events
    assert len(events) == 2
    assert events[0].event_type == EventType.TOOL_START
    assert events[1].event_type == EventType.TOOL_END
    assert events[0].tool_name == "my_func"
    assert events[1].tool_name == "my_func"


def test_tool_decorator_with_name(fake_queue):
    """@tool(name=...) uses custom tool name."""
    @observra.tool(name="web_search")
    def search(query):
        return "results"

    search("hello")

    events = fake_queue.events
    assert events[0].tool_name == "web_search"
    assert events[1].tool_name == "web_search"


def test_tool_decorator_duration_ms(fake_queue):
    """tool_end event includes duration_ms > 0."""
    @observra.tool
    def slow_func():
        import time
        time.sleep(0.01)
        return "done"

    slow_func()

    tool_end = fake_queue.events[1]
    assert tool_end.event_type == EventType.TOOL_END
    assert tool_end.data is not None
    assert tool_end.data.get("duration_ms") is not None
    assert tool_end.data["duration_ms"] > 0


def test_tool_decorator_no_capture_data_by_default(fake_queue):
    """tool_args and tool_result are None when capture_data=False."""
    @observra.tool
    def search(query: str) -> str:
        return "secret result"

    search("my query")

    tool_start = fake_queue.events[0]
    tool_end = fake_queue.events[1]
    assert tool_start.data is None or tool_start.data.get("tool_args") is None
    assert tool_end.data is None or tool_end.data.get("tool_result") is None


def test_tool_decorator_capture_data(fake_queue):
    """capture_data=True serialises args and result."""
    @observra.tool(capture_data=True)
    def add(a: int, b: int) -> int:
        return a + b

    add(3, 4)

    tool_start = fake_queue.events[0]
    tool_end = fake_queue.events[1]
    # tool_args captured in start
    assert tool_start.data is not None
    assert tool_start.data.get("tool_args") is not None
    # tool_result captured in end
    assert tool_end.data is not None
    assert tool_end.data.get("tool_result") is not None


def test_tool_decorator_error_emits_tool_error(fake_queue):
    """On exception, emits tool_error and re-raises."""
    @observra.tool
    def failing_func():
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        failing_func()

    events = fake_queue.events
    assert len(events) == 2
    assert events[0].event_type == EventType.TOOL_START
    assert events[1].event_type == EventType.TOOL_ERROR
    assert events[1].tool_name == "failing_func"


def test_tool_decorator_error_has_error_fields(fake_queue):
    """tool_error event has error_message and error_type_name."""
    @observra.tool
    def bad():
        raise RuntimeError("something went wrong")

    with pytest.raises(RuntimeError):
        bad()

    tool_error = fake_queue.events[1]
    assert tool_error.data is not None
    assert tool_error.data.get("error_message") is not None
    assert tool_error.data.get("error_type_name") == "RuntimeError"


def test_tool_decorator_preserves_return_value(fake_queue):
    """Decorated function returns the same value as undecorated."""
    @observra.tool
    def compute(n: int) -> list:
        return list(range(n))

    result = compute(5)
    assert result == [0, 1, 2, 3, 4]


def test_tool_decorator_preserves_metadata(fake_queue):
    """functools.wraps preserves __name__ and __doc__."""
    @observra.tool
    def documented_func():
        """Does something important."""
        pass

    assert documented_func.__name__ == "documented_func"
    assert documented_func.__doc__ == "Does something important."


# ---------------------------------------------------------------------------
# @tool — async
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tool_async_emits_start_end(fake_queue):
    """Async @tool emits tool_start + tool_end."""
    @observra.tool
    async def async_search(query: str) -> str:
        return f"results for {query}"

    result = await async_search("test")
    assert result == "results for test"

    events = fake_queue.events
    assert len(events) == 2
    assert events[0].event_type == EventType.TOOL_START
    assert events[1].event_type == EventType.TOOL_END


@pytest.mark.asyncio
async def test_tool_async_error_emits_tool_error(fake_queue):
    """Async @tool emits tool_error on exception."""
    @observra.tool
    async def async_bad():
        raise ConnectionError("network down")

    with pytest.raises(ConnectionError):
        await async_bad()

    events = fake_queue.events
    assert events[1].event_type == EventType.TOOL_ERROR


# ---------------------------------------------------------------------------
# @model_call — sync
# ---------------------------------------------------------------------------

def test_model_call_emits_request_response(fake_queue):
    """@model_call emits model_request + model_response."""
    @observra.model_call(model="gpt-4o")
    def ask(prompt: str) -> str:
        return "The answer is 42."

    ask("What is the answer?")

    events = fake_queue.events
    assert len(events) == 2
    assert events[0].event_type == EventType.MODEL_REQUEST
    assert events[1].event_type == EventType.MODEL_RESPONSE
    assert events[0].model_name == "gpt-4o"
    assert events[1].model_name == "gpt-4o"


def test_model_call_estimates_tokens(fake_queue):
    """model_response includes estimated input_tokens and output_tokens > 0."""
    @observra.model_call(model="claude-sonnet-4-6")
    def llm(prompt: str) -> str:
        return "A detailed response with many words and tokens."

    llm("Tell me about the universe and everything in it.")

    model_response = fake_queue.events[1]
    assert model_response.data is not None
    assert model_response.data.get("input_tokens", 0) > 0
    assert model_response.data.get("output_tokens", 0) > 0


def test_model_call_total_tokens(fake_queue):
    """total_tokens = input_tokens + output_tokens."""
    @observra.model_call(model="gpt-4o")
    def llm(prompt: str) -> str:
        return "Short reply."

    llm("Short prompt.")

    data = fake_queue.events[1].data
    assert data is not None
    expected_total = data.get("input_tokens", 0) + data.get("output_tokens", 0)
    assert data.get("total_tokens") == expected_total


def test_model_call_error_emits_model_error(fake_queue):
    """On exception, emits model_error and re-raises."""
    @observra.model_call(model="gpt-4o")
    def failing_llm(prompt: str) -> str:
        raise TimeoutError("API timed out")

    with pytest.raises(TimeoutError):
        failing_llm("hello")

    events = fake_queue.events
    assert len(events) == 2
    assert events[0].event_type == EventType.MODEL_REQUEST
    assert events[1].event_type == EventType.MODEL_ERROR


def test_model_call_default_model_name(fake_queue):
    """Without model= kwarg, model_name defaults to 'unknown'."""
    @observra.model_call
    def llm(prompt: str) -> str:
        return "response"

    llm("prompt")

    assert fake_queue.events[0].model_name == "unknown"


def test_model_call_prompt_arg_by_name(fake_queue):
    """prompt_arg='user_message' extracts named argument as prompt."""
    @observra.model_call(model="claude-sonnet-4-6", prompt_arg="user_message")
    def call_claude(system: str, user_message: str) -> str:
        return "Hello!"

    call_claude(system="You are helpful.", user_message="Tell me about Python.")

    # input_tokens should be estimated from "Tell me about Python."
    data = fake_queue.events[1].data
    assert data is not None
    assert data.get("input_tokens", 0) > 0


def test_model_call_prompt_arg_by_index(fake_queue):
    """prompt_arg=1 extracts positional argument at index 1 as prompt."""
    @observra.model_call(model="gpt-4o", prompt_arg=1)
    def call(system: str, user: str) -> str:
        return "OK"

    call("sys", "user message here")

    data = fake_queue.events[1].data
    assert data is not None
    assert data.get("input_tokens", 0) > 0


def test_model_call_preserves_return_value(fake_queue):
    """Decorated function returns the original value."""
    @observra.model_call(model="gpt-4o")
    def llm(prompt: str) -> dict:
        return {"answer": 42, "confidence": 0.99}

    result = llm("What is the answer?")
    assert result == {"answer": 42, "confidence": 0.99}


# ---------------------------------------------------------------------------
# @model_call — async
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_model_call_async_emits_request_response(fake_queue):
    """Async @model_call emits model_request + model_response."""
    @observra.model_call(model="gpt-4o")
    async def async_llm(prompt: str) -> str:
        return "Async answer."

    result = await async_llm("Async question?")
    assert result == "Async answer."

    events = fake_queue.events
    assert len(events) == 2
    assert events[0].event_type == EventType.MODEL_REQUEST
    assert events[1].event_type == EventType.MODEL_RESPONSE


@pytest.mark.asyncio
async def test_model_call_async_error(fake_queue):
    """Async @model_call emits model_error on exception."""
    @observra.model_call(model="gpt-4o")
    async def bad_llm(prompt: str) -> str:
        raise ValueError("model unavailable")

    with pytest.raises(ValueError):
        await bad_llm("hello")

    events = fake_queue.events
    assert events[1].event_type == EventType.MODEL_ERROR


# ---------------------------------------------------------------------------
# Response text extraction
# ---------------------------------------------------------------------------

def test_model_call_extracts_openai_chatcompletion(fake_queue):
    """Correctly extracts text from a mock OpenAI ChatCompletion object."""
    @observra.model_call(model="gpt-4o")
    def llm(prompt: str):
        # Simulate an OpenAI ChatCompletion response object
        msg = MagicMock()
        msg.content = "The capital of France is Paris."
        choice = MagicMock()
        choice.message = msg
        resp = MagicMock()
        resp.choices = [choice]
        return resp

    llm("What is the capital of France?")

    data = fake_queue.events[1].data
    assert data is not None
    # output_tokens estimated from "The capital of France is Paris."
    assert data.get("output_tokens", 0) > 0


def test_model_call_extracts_content_attr(fake_queue):
    """Correctly extracts text from an object with .content str attribute."""
    @observra.model_call(model="claude-sonnet-4-6")
    def llm(prompt: str):
        resp = MagicMock()
        resp.content = "This is the answer."
        resp.choices = None  # no choices attr shortcut
        del resp.choices
        return resp

    llm("Question?")

    data = fake_queue.events[1].data
    assert data is not None
    assert data.get("output_tokens", 0) > 0


def test_model_call_extracts_text_attr(fake_queue):
    """Correctly extracts text from an object with .text attribute."""
    @observra.model_call(model="gpt-4o")
    def llm(prompt: str):
        resp = MagicMock(spec=["text"])
        resp.text = "Response via .text attribute."
        return resp

    llm("Question?")

    data = fake_queue.events[1].data
    assert data is not None
    assert data.get("output_tokens", 0) > 0


# ---------------------------------------------------------------------------
# Dedup — @tool + passive adapter coexistence
# ---------------------------------------------------------------------------

def test_tool_decorator_emits_via_log_source(fake_queue):
    """@tool emits events with source='log', which coexists correctly with adapter source.

    The dedup registry blocks duplicate (event_type, span_id) pairs from DIFFERENT
    sources. When @tool fires (source='log') and a passive adapter fires (source='adapter')
    for the same span, one of them is suppressed. Here we verify that @tool correctly
    routes through log.tool_start, which registers source='log'.
    """
    from observra.core.dedup import register_emission
    from observra.core.context import get_span_id

    @observra.tool(name="dedup_test_tool")
    def my_tool() -> str:
        return "ok"

    my_tool()

    # @tool emitted tool_start (source='log') — now an 'adapter' trying to emit
    # the same (tool_start, span_id) should be suppressed
    span_id = get_span_id()
    # The log source already registered tool_start; adapter source should be blocked
    allowed = register_emission(EventType.TOOL_START, span_id, source="adapter")
    assert not allowed, "adapter tool_start should be deduped after log already emitted it"
