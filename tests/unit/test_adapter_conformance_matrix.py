"""Cross-SDK adapter conformance matrix for shared telemetry guarantees."""

from __future__ import annotations

import importlib
import inspect
import sys
import types
import warnings
from unittest.mock import MagicMock

import pytest

from observra.core.adapter import FrameworkAdapter
from observra.core.events import EventType, create_event


def _install_openai_stubs() -> None:
    """Install minimal agents.tracing stubs for OpenAI adapter import."""
    if "agents.tracing" in sys.modules and "agents.tracing.span_data" in sys.modules:
        return

    class _StubTracingProcessor:
        def on_trace_start(self, trace):
            pass

        def on_trace_end(self, trace):
            pass

        def on_span_start(self, span):
            pass

        def on_span_end(self, span):
            pass

        def shutdown(self):
            pass

        def force_flush(self):
            pass

    class _StubAgentSpanData:
        pass

    class _StubGenerationSpanData:
        pass

    class _StubFunctionSpanData:
        pass

    class _StubHandoffSpanData:
        pass

    agents_mod = sys.modules.setdefault("agents", types.ModuleType("agents"))
    tracing_mod = sys.modules.setdefault("agents.tracing", types.ModuleType("agents.tracing"))
    span_data_mod = sys.modules.setdefault(
        "agents.tracing.span_data",
        types.ModuleType("agents.tracing.span_data"),
    )

    tracing_mod.TracingProcessor = getattr(tracing_mod, "TracingProcessor", _StubTracingProcessor)
    span_data_mod.AgentSpanData = getattr(span_data_mod, "AgentSpanData", _StubAgentSpanData)
    span_data_mod.GenerationSpanData = getattr(span_data_mod, "GenerationSpanData", _StubGenerationSpanData)
    span_data_mod.FunctionSpanData = getattr(span_data_mod, "FunctionSpanData", _StubFunctionSpanData)
    span_data_mod.HandoffSpanData = getattr(span_data_mod, "HandoffSpanData", _StubHandoffSpanData)

    agents_mod.tracing = tracing_mod
    tracing_mod.span_data = span_data_mod


def _install_langchain_stubs() -> None:
    """Install minimal langchain_core stubs for LangChain adapter import."""
    if "langchain_core.callbacks.base" in sys.modules:
        return

    class _StubBaseCallbackHandler:
        pass

    lc_mod = sys.modules.setdefault("langchain_core", types.ModuleType("langchain_core"))
    callbacks_mod = sys.modules.setdefault("langchain_core.callbacks", types.ModuleType("langchain_core.callbacks"))
    callbacks_base_mod = sys.modules.setdefault(
        "langchain_core.callbacks.base",
        types.ModuleType("langchain_core.callbacks.base"),
    )
    outputs_mod = sys.modules.setdefault("langchain_core.outputs", types.ModuleType("langchain_core.outputs"))

    callbacks_base_mod.BaseCallbackHandler = getattr(
        callbacks_base_mod,
        "BaseCallbackHandler",
        _StubBaseCallbackHandler,
    )
    outputs_mod.LLMResult = getattr(outputs_mod, "LLMResult", type("LLMResult", (), {}))

    lc_mod.callbacks = callbacks_mod
    callbacks_mod.base = callbacks_base_mod


def _install_pydantic_ai_stubs() -> None:
    """Install minimal OTel stubs for Pydantic AI adapter import."""
    if "opentelemetry.sdk.trace" in sys.modules:
        return

    class _StubSpanProcessor:
        def on_start(self, span, parent_context=None):
            pass

        def on_end(self, span):
            pass

        def shutdown(self):
            pass

        def force_flush(self, timeout_millis=None):
            return True

    otel_mod = sys.modules.setdefault("opentelemetry", types.ModuleType("opentelemetry"))
    otel_sdk_mod = sys.modules.setdefault("opentelemetry.sdk", types.ModuleType("opentelemetry.sdk"))
    otel_sdk_trace_mod = sys.modules.setdefault(
        "opentelemetry.sdk.trace",
        types.ModuleType("opentelemetry.sdk.trace"),
    )

    otel_sdk_trace_mod.SpanProcessor = getattr(otel_sdk_trace_mod, "SpanProcessor", _StubSpanProcessor)
    otel_sdk_trace_mod.ReadableSpan = getattr(otel_sdk_trace_mod, "ReadableSpan", type("ReadableSpan", (), {}))

    otel_mod.sdk = otel_sdk_mod
    otel_sdk_mod.trace = otel_sdk_trace_mod


def _install_adk_stubs() -> None:
    """Install minimal google.adk.plugins stubs for ADK adapter import."""
    if "google.adk.plugins" in sys.modules:
        return

    class _StubBasePlugin:
        def __init__(self, name: str = "") -> None:
            self.name = name

    google_mod = sys.modules.setdefault("google", types.ModuleType("google"))
    adk_mod = sys.modules.setdefault("google.adk", types.ModuleType("google.adk"))
    plugins_mod = sys.modules.setdefault("google.adk.plugins", types.ModuleType("google.adk.plugins"))

    plugins_mod.BasePlugin = getattr(plugins_mod, "BasePlugin", _StubBasePlugin)
    adk_mod.plugins = plugins_mod
    google_mod.adk = adk_mod


_install_openai_stubs()
_install_langchain_stubs()
_install_pydantic_ai_stubs()
_install_adk_stubs()

TelemetryPlugin = importlib.import_module("observra.adapters.adk.plugin").TelemetryPlugin
ClaudeAdapter = importlib.import_module("observra.adapters.claude.adapter").ClaudeAdapter
OpenAIAdapter = importlib.import_module("observra.adapters.openai.adapter").OpenAIAdapter
LangChainAdapter = importlib.import_module("observra.adapters.langchain.adapter").LangChainAdapter
PydanticAIAdapter = importlib.import_module("observra.adapters.pydantic_ai.adapter").PydanticAIAdapter
AgentSpanData = importlib.import_module("agents.tracing.span_data").AgentSpanData


CANONICAL_EVENT_TYPES = {value for key, value in vars(EventType).items() if key.isupper() and isinstance(value, str)}

ADAPTER_MATRIX = [
    ("adk", TelemetryPlugin),
    ("claude", ClaudeAdapter),
    ("openai", OpenAIAdapter),
    ("langgraph", LangChainAdapter),
    ("pydantic-ai", PydanticAIAdapter),
]


def _new_adapter(adapter_cls, queue=None):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        return adapter_cls(queue=queue)


def _assert_required_fields(event, expected_framework: str) -> None:
    assert event.event_id
    assert event.trace_id
    assert event.session_id
    assert event.span_id
    assert event.timestamp > 0
    assert event.framework == expected_framework


async def _emit_smoke_event(framework: str, adapter) -> None:
    if framework == "adk":
        context = types.SimpleNamespace(agent_name="matrix-agent", user_id="user-1")
        await adapter.on_user_message_callback(invocation_context=context, user_message="hello")
        return

    if framework == "claude":
        await adapter._on_stop({"stop_hook_active": True}, "hook-1", None)
        return

    if framework == "openai":
        span_data = AgentSpanData(name="matrix-agent")
        span = types.SimpleNamespace(span_data=span_data)
        adapter.on_span_start(span)
        return

    if framework == "langgraph":
        adapter.on_chain_start({"name": "root-chain"}, {"prompt": "hello"}, run_id="run-1", parent_run_id=None)
        return

    if framework == "pydantic-ai":
        span = types.SimpleNamespace(
            name="execute_tool calculator",
            attributes={"gen_ai.tool.name": "calculator"},
        )
        adapter.on_end(span)
        return

    raise AssertionError(f"Unhandled framework: {framework}")


@pytest.mark.parametrize("framework,adapter_cls", ADAPTER_MATRIX)
def test_adapter_protocol_contract(framework, adapter_cls):
    """Every adapter must satisfy FrameworkAdapter and expose canonical framework name."""
    adapter = _new_adapter(adapter_cls, queue=None)
    assert isinstance(adapter, FrameworkAdapter)
    assert adapter.framework_name == framework

    stats = adapter.get_adapter_stats()
    assert stats["framework"] == framework
    assert "error_count" in stats
    assert "dropped_events" in stats


@pytest.mark.parametrize("framework,adapter_cls", ADAPTER_MATRIX)
def test_adapter_emit_routes_to_queue(framework, adapter_cls):
    """Every adapter must route events through queue.put_nowait when queue is provided."""
    mock_queue = MagicMock()
    adapter = _new_adapter(adapter_cls, queue=mock_queue)
    event = create_event(event_type=EventType.USER_MESSAGE, framework=framework)

    adapter.emit(event)
    mock_queue.put_nowait.assert_called_once_with(event)


@pytest.mark.parametrize("framework,adapter_cls", ADAPTER_MATRIX)
def test_adapter_emit_tracks_dropped_events(framework, adapter_cls):
    """Disabling an adapter must increment dropped_events instead of raising."""
    adapter = _new_adapter(adapter_cls, queue=None)
    before = adapter.get_adapter_stats()["dropped_events"]
    adapter._enabled = False

    adapter.emit(create_event(event_type=EventType.USER_MESSAGE, framework=framework))
    after = adapter.get_adapter_stats()["dropped_events"]
    assert after == before + 1


@pytest.mark.asyncio
@pytest.mark.parametrize("framework,adapter_cls", ADAPTER_MATRIX)
async def test_adapter_callback_smoke_emits_canonical_event(framework, adapter_cls):
    """Each adapter's native callback path must emit canonical event_type + required fields."""
    adapter = _new_adapter(adapter_cls, queue=None)
    before = len(adapter.events)

    result = _emit_smoke_event(framework, adapter)
    if inspect.isawaitable(result):
        await result

    assert len(adapter.events) == before + 1
    event = adapter.events[-1]
    assert event.event_type in CANONICAL_EVENT_TYPES
    _assert_required_fields(event, framework)
