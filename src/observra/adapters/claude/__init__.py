# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Claude Agent SDK adapter for agent telemetry.

Requires: pip install observra[claude]
"""

try:
    from .adapter import ClaudeAdapter

    __all__ = ["ClaudeAdapter"]
except ImportError as e:
    raise ImportError(
        "Claude adapter requires claude-agent-sdk and tiktoken. Install with: pip install observra[claude]"
    ) from e
