"""Test configuration for Pydantic AI adapter tests.

Patches the opentelemetry.sdk.trace module hierarchy into sys.modules before any test
imports happen, so the adapter can be imported without the optional opentelemetry-sdk
package installed.

The stub SpanProcessor has no-op implementations of all 4 required methods so
PydanticAIAdapter's super().__init__() and method overrides succeed.
"""

import sys
import types as _types

# ---------------------------------------------------------------------------
# Create stub opentelemetry.sdk.trace module hierarchy
# ---------------------------------------------------------------------------


class _StubSpanProcessor:
    """Stub SpanProcessor — no-op implementations of all 4 required methods."""

    def on_start(self, span, parent_context=None):
        pass

    def on_end(self, span):
        pass

    def shutdown(self):
        pass

    def force_flush(self, timeout_millis=None):
        return True


class _StubReadableSpan:
    pass


_otel_mod = _types.ModuleType("opentelemetry")
_otel_sdk_mod = _types.ModuleType("opentelemetry.sdk")
_otel_sdk_trace_mod = _types.ModuleType("opentelemetry.sdk.trace")

_otel_sdk_trace_mod.SpanProcessor = _StubSpanProcessor
_otel_sdk_trace_mod.ReadableSpan = _StubReadableSpan

_otel_mod.sdk = _otel_sdk_mod
_otel_sdk_mod.trace = _otel_sdk_trace_mod

sys.modules.setdefault("opentelemetry", _otel_mod)
sys.modules.setdefault("opentelemetry.sdk", _otel_sdk_mod)
sys.modules.setdefault("opentelemetry.sdk.trace", _otel_sdk_trace_mod)
