# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Test configuration for OTelExportBackend and MultiBackend tests.

This conftest injects stub OTel modules into sys.modules at collection time so that
observra.backends.otel can be imported in environments WITHOUT the
opentelemetry-sdk installed.

When opentelemetry-sdk IS installed (as on this machine), sys.modules.setdefault()
is a no-op (the real package is already in sys.modules). In that case the real
OTel SDK is used — the captured_spans fixture patches OTLPSpanExporter and
BatchSpanProcessor to prevent network calls and use synchronous in-memory capture.

Covers all 11 intermediate module levels required by otel.py:
  opentelemetry
  opentelemetry.trace
  opentelemetry.sdk
  opentelemetry.sdk.trace
  opentelemetry.sdk.trace.export
  opentelemetry.sdk.resources
  opentelemetry.exporter
  opentelemetry.exporter.otlp
  opentelemetry.exporter.otlp.proto
  opentelemetry.exporter.otlp.proto.http
  opentelemetry.exporter.otlp.proto.http.trace_exporter
"""

import sys
import types as _types

import pytest

# ---------------------------------------------------------------------------
# Stub classes (used as fallback when real OTel SDK is NOT installed)
# ---------------------------------------------------------------------------

class _StubSpan:
    """Stub OTel Span — context manager that collects attributes."""

    def __init__(self, name: str):
        self.name = name
        self.attributes: dict = {}

    def set_attribute(self, key: str, value) -> None:
        self.attributes[key] = value

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False


class _StubTracer:
    """Stub OTel Tracer — creates _StubSpan instances."""

    def __init__(self):
        self.created_spans: list = []

    def start_as_current_span(self, name: str, *args, **kwargs):
        span = _StubSpan(name)
        self.created_spans.append(span)
        return span


class _StubProvider:
    """Stub TracerProvider — returns _StubTracer instances."""

    def __init__(self, resource=None):
        self.resource = resource
        self._processors = []
        self._tracer = _StubTracer()

    def get_tracer(self, *args, **kwargs) -> "_StubTracer":
        return self._tracer

    def add_span_processor(self, processor) -> None:
        self._processors.append(processor)

    def force_flush(self, timeout_millis=None) -> None:
        pass

    def shutdown(self) -> None:
        pass


class _StubSpanExporter:
    """Stub OTLPSpanExporter — no-op export/shutdown/force_flush."""

    def __init__(self, endpoint=None, headers=None, timeout=None):
        self.endpoint = endpoint
        self.headers = headers
        self.timeout = timeout

    def export(self, spans):
        pass

    def shutdown(self) -> None:
        pass

    def force_flush(self, timeout_millis=None) -> None:
        pass


class _StubBatchSpanProcessor:
    """Stub BatchSpanProcessor — stores exporter, no-op otherwise."""

    def __init__(self, exporter):
        self.exporter = exporter

    def on_start(self, span, parent_context=None):
        pass

    def on_end(self, span):
        pass

    def shutdown(self):
        pass

    def force_flush(self, timeout_millis=None):
        return True


class _StubResource:
    """Stub Resource — static create() factory."""

    def __init__(self, attributes=None):
        self.attributes = attributes or {}

    @staticmethod
    def create(attributes=None) -> "_StubResource":
        return _StubResource(attributes=attributes)


# SpanKind stub — only INTERNAL is needed by otel.py
SpanKind = type("SpanKind", (), {"INTERNAL": "INTERNAL"})()


# ---------------------------------------------------------------------------
# Build and inject the stub module hierarchy
# (setdefault = no-op if real SDK is already installed)
# ---------------------------------------------------------------------------

# opentelemetry (top-level)
_otel_mod = _types.ModuleType("opentelemetry")

# opentelemetry.trace
_otel_trace_mod = _types.ModuleType("opentelemetry.trace")
_otel_trace_mod.SpanKind = SpanKind

# opentelemetry.sdk
_otel_sdk_mod = _types.ModuleType("opentelemetry.sdk")

# opentelemetry.sdk.trace
_otel_sdk_trace_mod = _types.ModuleType("opentelemetry.sdk.trace")
_otel_sdk_trace_mod.TracerProvider = _StubProvider

# opentelemetry.sdk.trace.export
_otel_sdk_trace_export_mod = _types.ModuleType("opentelemetry.sdk.trace.export")
_otel_sdk_trace_export_mod.BatchSpanProcessor = _StubBatchSpanProcessor

# opentelemetry.sdk.resources
_otel_sdk_resources_mod = _types.ModuleType("opentelemetry.sdk.resources")
_otel_sdk_resources_mod.Resource = _StubResource
_otel_sdk_resources_mod.SERVICE_NAME = "service.name"

# opentelemetry.exporter
_otel_exporter_mod = _types.ModuleType("opentelemetry.exporter")

# opentelemetry.exporter.otlp
_otel_exporter_otlp_mod = _types.ModuleType("opentelemetry.exporter.otlp")

# opentelemetry.exporter.otlp.proto
_otel_exporter_otlp_proto_mod = _types.ModuleType("opentelemetry.exporter.otlp.proto")

# opentelemetry.exporter.otlp.proto.http
_otel_exporter_otlp_proto_http_mod = _types.ModuleType("opentelemetry.exporter.otlp.proto.http")

# opentelemetry.exporter.otlp.proto.http.trace_exporter
_otel_exporter_trace_mod = _types.ModuleType("opentelemetry.exporter.otlp.proto.http.trace_exporter")
_otel_exporter_trace_mod.OTLPSpanExporter = _StubSpanExporter

# Link modules as attributes (BOTH sys.modules AND attribute links required)
_otel_mod.trace = _otel_trace_mod
_otel_mod.sdk = _otel_sdk_mod
_otel_mod.exporter = _otel_exporter_mod

_otel_sdk_mod.trace = _otel_sdk_trace_mod
_otel_sdk_mod.resources = _otel_sdk_resources_mod

_otel_sdk_trace_mod.export = _otel_sdk_trace_export_mod

_otel_exporter_mod.otlp = _otel_exporter_otlp_mod
_otel_exporter_otlp_mod.proto = _otel_exporter_otlp_proto_mod
_otel_exporter_otlp_proto_mod.http = _otel_exporter_otlp_proto_http_mod
_otel_exporter_otlp_proto_http_mod.trace_exporter = _otel_exporter_trace_mod

sys.modules.setdefault("opentelemetry", _otel_mod)
sys.modules.setdefault("opentelemetry.trace", _otel_trace_mod)
sys.modules.setdefault("opentelemetry.sdk", _otel_sdk_mod)
sys.modules.setdefault("opentelemetry.sdk.trace", _otel_sdk_trace_mod)
sys.modules.setdefault("opentelemetry.sdk.trace.export", _otel_sdk_trace_export_mod)
sys.modules.setdefault("opentelemetry.sdk.resources", _otel_sdk_resources_mod)
sys.modules.setdefault("opentelemetry.exporter", _otel_exporter_mod)
sys.modules.setdefault("opentelemetry.exporter.otlp", _otel_exporter_otlp_mod)
sys.modules.setdefault("opentelemetry.exporter.otlp.proto", _otel_exporter_otlp_proto_mod)
sys.modules.setdefault("opentelemetry.exporter.otlp.proto.http", _otel_exporter_otlp_proto_http_mod)
sys.modules.setdefault("opentelemetry.exporter.otlp.proto.http.trace_exporter", _otel_exporter_trace_mod)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def init_context():
    """Initialize trace/session context before each test so create_event() works."""
    from observra.core.context import initialize_session, initialize_trace
    initialize_trace()
    initialize_session()


@pytest.fixture(autouse=True)
def patch_otlp_exporter(monkeypatch):
    """Always patch OTLPSpanExporter in otel module to prevent network calls.

    Applied to every test in this package via autouse=True. If the real OTel SDK
    is installed, OTLPSpanExporter would try to connect to localhost:4318 on
    BatchSpanProcessor flush. This fixture replaces it with a no-op class.
    """
    try:
        from opentelemetry.sdk.trace.export import SpanExportResult

        import observra.backends.otel as otel_module

        class _NoOpExporter:
            """Null exporter — discards all spans without network calls."""
            def __init__(self, endpoint=None, headers=None, timeout=None):
                pass

            def export(self, spans):
                return SpanExportResult.SUCCESS

            def shutdown(self):
                pass

            def force_flush(self, timeout_millis=None):
                pass

        monkeypatch.setattr(otel_module, "OTLPSpanExporter", _NoOpExporter)
    except ImportError:
        pass  # Stub SDK path — no real network calls possible


@pytest.fixture
def captured_spans(monkeypatch):
    """Return a list that accumulates all spans created by OTelExportBackend.write().

    Strategy: patch OTLPSpanExporter and BatchSpanProcessor in otel module so
    spans are captured synchronously in-memory (no network calls, no threads).

    Works with the real opentelemetry-sdk (installed) and with stub providers
    (when SDK is not installed — stub path via ImportError fallback).

    Each entry is a span object with .name (str) and .attributes (dict-like).

    Usage::

        def test_something(captured_spans):
            backend = OTelExportBackend()
            backend.write(event)
            assert len(captured_spans) == 1
            assert captured_spans[0].attributes["gen_ai.request.model"] == "gpt-4o"
    """
    import observra.backends.otel as otel_module

    spans = []

    try:
        # Real OTel SDK path: replace exporter + processor with synchronous in-memory capture
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult

        class _CapturingExporter(SpanExporter):
            """Synchronous in-memory exporter: appends finished spans to the shared list."""
            def export(self, finished_spans):
                for span in finished_spans:
                    spans.append(span)
                return SpanExportResult.SUCCESS

            def shutdown(self):
                pass

        _capturing_exporter = _CapturingExporter()
        _capturing_processor = SimpleSpanProcessor(_capturing_exporter)

        # OTLPSpanExporter(endpoint=..., headers=..., timeout=...) -> return _capturing_exporter
        monkeypatch.setattr(
            otel_module,
            "OTLPSpanExporter",
            type("_NullExporterFactory", (), {
                "__init__": lambda self, endpoint=None, headers=None, timeout=None: None,
                "export": lambda self, spans: SpanExportResult.SUCCESS,
                "shutdown": lambda self: None,
            }),
        )
        # Replace BatchSpanProcessor with SimpleSpanProcessor wrapping our capturing exporter
        monkeypatch.setattr(
            otel_module,
            "BatchSpanProcessor",
            lambda exporter: _capturing_processor,
        )

    except ImportError:
        # Stub SDK path (OTel SDK not installed): track via _StubProvider/Tracer
        class _TrackingSpan(_StubSpan):
            def __init__(self, name: str):
                super().__init__(name)
                spans.append(self)

        class _TrackingTracer(_StubTracer):
            def start_as_current_span(self, name: str, *args, **kwargs):
                span = _TrackingSpan(name)
                self.created_spans.append(span)
                return span

        _tracking_tracer = _TrackingTracer()
        monkeypatch.setattr(_StubProvider, "get_tracer", lambda self, *a, **kw: _tracking_tracer)

    return spans
