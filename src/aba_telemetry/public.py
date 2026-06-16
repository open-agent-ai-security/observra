"""Stable v1.0 API surface.

This module defines the stable v1.0 API surface. Import from here for
SemVer-guaranteed stability. Symbols not in this module are either
provisional (in aba_telemetry.__all__ but not here) or internal.

Usage:
    from aba_telemetry.public import initialize, TelemetryEvent, ADKAdapter
"""
from aba_telemetry import (
    initialize,
    create_plugin,
    create_logging_handler,
    get_stats,
    TelemetryEvent,
)
from aba_telemetry.core.storage import StorageBackend
from aba_telemetry import observability

# Convenience re-export: stable get_metrics surface (OBS-01)
get_metrics = observability.get_metrics

# v1.0 framework adapters — guarded by try/except so importing public.py
# without a framework SDK installed does NOT raise ImportError.

try:
    from aba_telemetry.adapters.adk import TelemetryPlugin as ADKAdapter
except ImportError:
    pass

try:
    from aba_telemetry.adapters.claude import ClaudeAdapter
except ImportError:
    pass

try:
    from aba_telemetry.adapters.openai import OpenAIAdapter
except ImportError:
    pass

try:
    from aba_telemetry.adapters.langchain import LangChainAdapter
except ImportError:
    pass

try:
    from aba_telemetry.adapters.pydantic_ai import PydanticAIAdapter
except ImportError:
    pass

# Additional adapters (Claude Code, Codex, Gemini, OpenClaw, MCP, Copilot)
# are available but not part of the v1.0 stable surface. Import directly
# from aba_telemetry.adapters.<name> if needed.

__all__ = [
    "initialize",
    "create_plugin",
    "create_logging_handler",
    "get_stats",
    "get_metrics",
    "observability",
    "TelemetryEvent",
    "StorageBackend",
    "ADKAdapter",
    "ClaudeAdapter",
    "OpenAIAdapter",
    "LangChainAdapter",
    "PydanticAIAdapter",
]
