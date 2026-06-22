# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Test configuration for OpenAI adapter tests.

Patches the agents.tracing modules into sys.modules before any test imports
happen, so the adapter can be imported without the optional openai-agents
package installed.

The stub TracingProcessor base class is a no-op with all 6 required methods
so OpenAIAdapter's __init_subclass__ and super() calls succeed.
"""

import sys
import types as _types

# ---------------------------------------------------------------------------
# Create stub agents.tracing module hierarchy
# ---------------------------------------------------------------------------


class _StubTracingProcessor:
    """Stub base class for TracingProcessor — no-op implementations of all 6 methods."""

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


# Build the fake module hierarchy
_agents_mod = _types.ModuleType("agents")
_agents_tracing_mod = _types.ModuleType("agents.tracing")
_agents_tracing_span_data_mod = _types.ModuleType("agents.tracing.span_data")

_agents_tracing_mod.TracingProcessor = _StubTracingProcessor
_agents_tracing_span_data_mod.AgentSpanData = _StubAgentSpanData
_agents_tracing_span_data_mod.GenerationSpanData = _StubGenerationSpanData
_agents_tracing_span_data_mod.FunctionSpanData = _StubFunctionSpanData
_agents_tracing_span_data_mod.HandoffSpanData = _StubHandoffSpanData

_agents_mod.tracing = _agents_tracing_mod
_agents_tracing_mod.span_data = _agents_tracing_span_data_mod

# Register all required module paths
sys.modules.setdefault("agents", _agents_mod)
sys.modules.setdefault("agents.tracing", _agents_tracing_mod)
sys.modules.setdefault("agents.tracing.span_data", _agents_tracing_span_data_mod)
