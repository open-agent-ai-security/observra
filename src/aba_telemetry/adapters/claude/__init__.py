"""Claude Agent SDK adapter for agent telemetry.

Requires: pip install aba-telemetry[claude]
"""

try:
    from .adapter import ClaudeAdapter
    __all__ = ["ClaudeAdapter"]
except ImportError as e:
    raise ImportError(
        "Claude adapter requires claude-agent-sdk and tiktoken. "
        "Install with: pip install aba-telemetry[claude]"
    ) from e
