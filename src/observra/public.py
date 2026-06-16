"""Stable v1.0 API surface.

This module defines the stable v1.0 API surface. Import from here for
SemVer-guaranteed stability. Symbols not in this module are either
provisional (in observra.__all__ but not here) or internal.

Usage:
    from observra.public import initialize, TelemetryEvent, ADKAdapter
"""
from observra import (
    initialize,
    create_plugin,
    create_logging_handler,
    get_stats,
    TelemetryEvent,
)
from observra.core.storage import StorageBackend
from observra import observability

# Convenience re-export: stable get_metrics surface (OBS-01)
get_metrics = observability.get_metrics

# v1.0 framework adapters — guarded by try/except so importing public.py
# without a framework SDK installed does NOT raise ImportError.

try:
    from observra.adapters.adk import TelemetryPlugin as ADKAdapter
except ImportError:
    pass

try:
    from observra.adapters.claude import ClaudeAdapter
except ImportError:
    pass

try:
    from observra.adapters.openai import OpenAIAdapter
except ImportError:
    pass

try:
    from observra.adapters.langchain import LangChainAdapter
except ImportError:
    pass

try:
    from observra.adapters.pydantic_ai import PydanticAIAdapter
except ImportError:
    pass

# Additional adapters (Claude Code, Codex, Gemini, OpenClaw, MCP, Copilot)
# are available but not part of the v1.0 stable surface. Import directly
# from observra.adapters.<name> if needed.

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
