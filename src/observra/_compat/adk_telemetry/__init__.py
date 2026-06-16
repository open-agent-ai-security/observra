"""Backward-compatible shim for adk_telemetry package.

This module allows `from adk_telemetry import X` to continue working
with a DeprecationWarning. Will be removed in 2.0.
"""
import warnings

warnings.warn(
    "adk_telemetry is deprecated; use observra instead. Will be removed in 2.0.",
    DeprecationWarning,
    stacklevel=2,
)

# Re-export all public symbols from the real package
from observra import (
    TelemetryEvent,
    FrameworkAdapter,
    __version__,
    initialize,
    create_plugin,
    create_logging_handler,
    get_stats,
    get_session_cost,
    TelemetryLoggingHandler,
    create_event,
)
from observra.adapters.adk.plugin import TelemetryPlugin

__all__ = [
    "TelemetryPlugin",
    "TelemetryEvent",
    "FrameworkAdapter",
    "__version__",
    "initialize",
    "create_plugin",
    "create_logging_handler",
    "get_stats",
    "get_session_cost",
    "TelemetryLoggingHandler",
    "create_event",
]
