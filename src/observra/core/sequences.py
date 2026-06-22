# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Tool call sequence tracking for agent behavior pattern analysis."""

import logging
import time
from contextvars import ContextVar
from typing import Optional

logger = logging.getLogger(__name__)

# Session-scoped tool sequence
_tool_sequence_var: ContextVar[Optional[list]] = ContextVar('tool_sequence', default=None)


def initialize_tool_sequence() -> list:
    """Initialize tool sequence tracker with empty list and return it.

    Called at the start of a new trace or session.

    Returns:
        The newly created list (caller may save it for session restore).
    """
    seq: list = []
    _tool_sequence_var.set(seq)
    logger.debug("Tool sequence tracker initialized")
    return seq


def set_tool_sequence(sequence: list) -> None:
    """Restore ContextVar to an existing sequence (session resume).

    Args:
        sequence: The list object from a prior call to initialize_tool_sequence().
    """
    _tool_sequence_var.set(sequence)


def record_tool_call(tool_name: str) -> list[tuple[str, float]]:
    """Record a tool call and return current sequence snapshot.

    Args:
        tool_name: Name of the tool being called

    Returns:
        Copy of current sequence as list of (tool_name, timestamp) tuples
    """
    # Get or create sequence (fallback if not initialized)
    sequence = _tool_sequence_var.get()
    if sequence is None:
        sequence = []
        _tool_sequence_var.set(sequence)
        logger.warning(
            "Tool sequence tracker auto-initialized — on_initialize() may not have run. "
            "This list is not saved to _SessionState and will not persist across asyncio tasks."
        )

    # Record tool call with timestamp
    timestamp = time.time()
    sequence.append((tool_name, timestamp))
    logger.debug("Tool call recorded: %s at %s", tool_name, timestamp)

    # Return copy to prevent external mutation
    return sequence.copy()


# Suspicious pattern keywords for data exfiltration detection
_READ_KEYWORDS = frozenset({"read", "get", "fetch", "search", "list", "download", "open", "load"})
_EXTERNAL_KEYWORDS = frozenset({"http", "request", "post", "send", "call", "api", "webhook", "upload"})


def detect_suspicious_sequence(tool_names: list[str]) -> bool:
    """Detect if tool sequence matches a known suspicious pattern.

    Patterns:
    - Data exfiltration: any read-like tool + any external/outbound tool in same session

    Args:
        tool_names: List of tool names in session order.

    Returns:
        True if sequence matches a suspicious pattern. False for sequences shorter than 2 calls.
    """
    if len(tool_names) < 2:
        return False
    lowered = [n.lower() for n in tool_names]

    def _hit(name: str, keywords: frozenset) -> bool:
        return any(kw in name for kw in keywords)

    has_read = any(_hit(n, _READ_KEYWORDS) for n in lowered)
    has_external = any(_hit(n, _EXTERNAL_KEYWORDS) for n in lowered)
    return has_read and has_external


def get_tool_sequence() -> list[tuple[str, float]]:
    """Get current tool sequence.

    Returns:
        Copy of current sequence (empty list if not initialized)
    """
    sequence = _tool_sequence_var.get()
    if sequence is None:
        return []
    return sequence.copy()
