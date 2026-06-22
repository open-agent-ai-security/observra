# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Tests for OTelExportBackend.

Covers EXPT-01 (StorageBackend Protocol conformance) and EXPT-03 (GenAI semantic
convention attributes). All tests run without opentelemetry-sdk installed — conftest.py
stubs the entire OTel module hierarchy.

Spans are captured via the `captured_spans` fixture which patches _StubProvider.get_tracer()
to accumulate every span created by write() for assertion.
"""

import pytest

# conftest.py has already injected stubs before this import
from observra.backends.otel import OTelExportBackend
from observra.core.events import create_event

# ---------------------------------------------------------------------------
# Helper to create common TelemetryEvent instances
# ---------------------------------------------------------------------------


def _model_event(model_name="gpt-4o", framework="openai", **kwargs):
    """Create a model_response event with the given model/framework."""
    return create_event(
        "model_response",
        model_name=model_name,
        framework=framework,
        **kwargs,
    )


def _tool_event(tool_name="search", **kwargs):
    """Create a tool_call event."""
    return create_event("tool_end", tool_name=tool_name, **kwargs)


def _session_event(agent_name="my_agent", **kwargs):
    """Create a session_end event."""
    return create_event("session_end", agent_name=agent_name, **kwargs)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestOTelBackendInstantiation:
    """Construction and basic protocol conformance."""

    def test_otel_backend_instantiates(self):
        """Constructor succeeds with default args."""
        backend = OTelExportBackend()
        assert backend is not None
        assert backend.BACKEND_TYPE == "otel"

    def test_otel_backend_instantiates_with_explicit_endpoint(self):
        """Constructor succeeds with explicit endpoint."""
        backend = OTelExportBackend(
            endpoint="http://localhost:4318/v1/traces",
            service_name="test-service",
        )
        assert backend is not None


class TestSpanNaming:
    """Verify span names follow GenAI semantic conventions."""

    def test_write_model_response_span_name(self, captured_spans):
        """model_response events produce 'chat {model}' span names."""
        backend = OTelExportBackend()
        event = _model_event(model_name="gpt-4o")
        backend.write(event)

        assert len(captured_spans) == 1
        assert captured_spans[0].name == "chat gpt-4o"

    def test_write_tool_call_span_name(self, captured_spans):
        """tool_call events produce 'execute_tool {tool}' span names."""
        backend = OTelExportBackend()
        event = _tool_event(tool_name="search")
        backend.write(event)

        assert len(captured_spans) == 1
        assert captured_spans[0].name == "execute_tool search"

    def test_write_session_end_span_name(self, captured_spans):
        """session_end events produce 'invoke_agent {agent}' span names."""
        backend = OTelExportBackend()
        event = _session_event(agent_name="my_agent")
        backend.write(event)

        assert len(captured_spans) == 1
        assert captured_spans[0].name == "invoke_agent my_agent"

    def test_write_unknown_event_type_passthrough(self, captured_spans):
        """Unrecognized event types use the event_type string as span name."""
        backend = OTelExportBackend()
        event = create_event("custom_event")
        backend.write(event)

        assert len(captured_spans) == 1
        assert captured_spans[0].name == "custom_event"

    def test_write_model_response_missing_model_name(self, captured_spans):
        """model_name=None produces 'chat unknown' (not 'chat None')."""
        backend = OTelExportBackend()
        event = create_event("model_response", model_name=None, framework="openai")
        backend.write(event)

        assert len(captured_spans) == 1
        assert captured_spans[0].name == "chat unknown"


class TestGenAIAttributes:
    """Verify GenAI semantic convention attributes are set correctly (EXPT-03)."""

    def test_write_model_response_sets_gen_ai_attributes(self, captured_spans):
        """model_response events with full data set all GenAI attributes."""
        backend = OTelExportBackend()
        event = create_event(
            "model_response",
            model_name="gpt-4o",
            framework="openai",
            input_tokens=100,
            output_tokens=50,
        )
        backend.write(event)

        assert len(captured_spans) == 1
        attrs = captured_spans[0].attributes

        # GenAI model attributes
        assert attrs["gen_ai.request.model"] == "gpt-4o"
        # GenAI usage attributes
        assert attrs["gen_ai.usage.input_tokens"] == 100
        assert attrs["gen_ai.usage.output_tokens"] == 50
        # Provider attributes: BOTH current and deprecated must be set
        assert attrs["gen_ai.provider.name"] == "openai"
        assert attrs["gen_ai.system"] == "openai"

    def test_write_sets_custom_namespace_attributes(self, captured_spans):
        """Custom observra.* namespace attributes are always set."""
        backend = OTelExportBackend()
        event = _model_event()
        backend.write(event)

        assert len(captured_spans) == 1
        attrs = captured_spans[0].attributes

        # All 5 custom namespace attributes must be present
        assert "observra.event_id" in attrs
        assert "observra.event_type" in attrs
        assert "observra.trace_id" in attrs
        assert "observra.session_id" in attrs
        assert "observra.framework" in attrs

        # event_type should match what we wrote
        assert attrs["observra.event_type"] == "model_response"

    def test_write_cost_usd_attribute(self, captured_spans):
        """cost_usd in event.data is stored as observra.cost_usd."""
        backend = OTelExportBackend()
        event = create_event("model_response", model_name="gpt-4o", framework="openai", cost_usd=0.005)
        backend.write(event)

        assert len(captured_spans) == 1
        attrs = captured_spans[0].attributes
        assert abs(attrs["observra.cost_usd"] - 0.005) < 1e-9

    def test_write_error_type_attribute(self, captured_spans):
        """error_type in event.data is stored as error.type."""
        backend = OTelExportBackend()
        event = create_event(
            "tool_error",
            tool_name="fetch",
            framework="openai",
            error_type="TimeoutError",
        )
        backend.write(event)

        assert len(captured_spans) == 1
        attrs = captured_spans[0].attributes
        assert attrs["error.type"] == "TimeoutError"

    def test_gen_ai_provider_and_system_both_present(self, captured_spans):
        """Both gen_ai.provider.name (current) and gen_ai.system (deprecated) are emitted."""
        backend = OTelExportBackend()
        event = create_event("model_response", model_name="claude-3", framework="claude")
        backend.write(event)

        assert len(captured_spans) == 1
        attrs = captured_spans[0].attributes
        assert attrs.get("gen_ai.provider.name") == "claude"
        assert attrs.get("gen_ai.system") == "claude"


class TestInjectionAttributes:
    """Injection detection metadata surfaces as span attributes."""

    def test_injection_detected_attributes(self, captured_spans):
        """has_injection_patterns and injection_patterns are set on spans."""
        backend = OTelExportBackend()
        event = create_event(
            "user_message",
            framework="adk",
            has_injection_patterns=True,
            injection_patterns=["JAILBREAK_DAN", "BASE64_BLOB"],
        )
        backend.write(event)

        assert len(captured_spans) == 1
        attrs = captured_spans[0].attributes
        assert attrs["observra.has_injection_patterns"] is True
        assert attrs["observra.injection_patterns"] == "JAILBREAK_DAN,BASE64_BLOB"

    def test_no_injection_omits_patterns(self, captured_spans):
        """When no injection detected, patterns attribute is absent."""
        backend = OTelExportBackend()
        event = create_event(
            "user_message",
            framework="adk",
            has_injection_patterns=False,
        )
        backend.write(event)

        assert len(captured_spans) == 1
        attrs = captured_spans[0].attributes
        assert attrs["observra.has_injection_patterns"] is False
        assert "observra.injection_patterns" not in attrs


class TestStats:
    """Verify get_stats() tracking."""

    def test_get_stats_returns_backend_stats(self):
        """Write 3 events; get_stats() reflects event_count=3, backend_type='otel'."""
        backend = OTelExportBackend()
        for _ in range(3):
            backend.write(_model_event())

        stats = backend.get_stats()
        assert stats["event_count"] == 3
        assert stats["backend_type"] == "otel"

    def test_get_stats_initial_state(self):
        """Freshly instantiated backend reports event_count=0."""
        backend = OTelExportBackend()
        stats = backend.get_stats()
        assert stats["event_count"] == 0
        assert stats["oldest_event_ts"] is None
        assert stats["newest_event_ts"] is None


class TestQueryAndErrors:
    """Verify query() and error handling behavior."""

    def test_query_raises_not_implemented(self, captured_spans):
        """query() always raises NotImplementedError (OTel is write-only)."""
        backend = OTelExportBackend()
        with pytest.raises(NotImplementedError) as exc_info:
            backend.query()
        # Verify helpful message is included
        assert "OTelExportBackend" in str(exc_info.value)

    def test_write_error_increments_error_count(self, captured_spans, monkeypatch):
        """If span creation raises, _errors increments and write() does not raise."""

        backend = OTelExportBackend()

        # Patch the tracer on the already-created backend instance directly
        original_tracer = backend._tracer

        def _bad_start(*args, **kwargs):
            raise RuntimeError("span creation failed")

        monkeypatch.setattr(type(original_tracer), "start_as_current_span", _bad_start)

        # write() must not propagate the exception
        backend.write(_model_event())
        assert backend._errors == 1
        # event_count should NOT increment on error
        assert backend._events_written == 0
