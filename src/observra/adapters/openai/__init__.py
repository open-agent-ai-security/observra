# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0

"""OpenAI Agents SDK adapter for agent telemetry.

Requires: pip install observra[openai-agents]
"""

try:
    from .adapter import OpenAIAdapter

    __all__ = ["OpenAIAdapter"]
except ImportError:
    # openai-agents not installed — base install is unaffected
    pass
