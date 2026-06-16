"""ADK framework adapter for agent telemetry.

Requires: pip install observra[adk]
"""

try:
    from .plugin import TelemetryPlugin
    # ADKAdapter is an alias for TelemetryPlugin — the class name stays TelemetryPlugin
    # to preserve all existing code; ADKAdapter is the public multi-framework API name.
    ADKAdapter = TelemetryPlugin
    __all__ = ["TelemetryPlugin", "ADKAdapter"]
except ImportError as e:
    raise ImportError(
        "ADK adapter requires google-adk. "
        "Install with: pip install observra[adk]"
    ) from e
