"""Error classification and delegation depth tracking for agent behavior analysis."""

import logging
import re
from contextvars import ContextVar
from typing import Literal

_HTTP_CODE_RE = re.compile(r"(?<!\d)(\d{3})(?!\d)")

logger = logging.getLogger(__name__)

# Error classification types
ErrorType = Literal["network", "auth", "rate_limit", "model_error", "tool_error", "unknown"]

# Delegation depth tracking
_delegation_depth_var: ContextVar[int] = ContextVar("delegation_depth", default=0)
MAX_DELEGATION_DEPTH = 5


def classify_error(error: Exception, context: str) -> tuple[ErrorType, bool]:
    """Classify error and determine if it's retryable.

    Args:
        error: Exception to classify
        context: Context where error occurred ("model" or "tool")

    Returns:
        Tuple of (error_type, is_retryable)
    """
    error_str = str(error)
    error_lower = error_str.lower()
    error_type_name = type(error).__name__

    # Extract standalone HTTP status codes (word-boundary match: "401" yes, "40112" no)
    http_codes = set(_HTTP_CODE_RE.findall(error_str))

    # Priority order for classification
    # 1. Rate limit errors (retryable)
    if "429" in http_codes or "rate" in error_lower or "quota" in error_lower:
        return ("rate_limit", True)

    # 2. Auth errors (not retryable)
    if "401" in http_codes or "403" in http_codes or "unauthorized" in error_lower:
        return ("auth", False)

    # 3. Network errors (retryable)
    if any(name in error_type_name for name in ["ConnectionError", "TimeoutError", "NetworkError"]):
        return ("network", True)

    # 4. Server errors (retryable, classified as network)
    if http_codes & {"500", "502", "503", "504"}:
        return ("network", True)

    # 5. Client errors (not retryable, context-specific)
    if http_codes & {"400", "404", "422"}:
        if context == "model":
            return ("model_error", False)
        else:
            return ("tool_error", False)

    # 6. Default: context-specific error type, not retryable
    if context == "model":
        return ("model_error", False)
    else:
        return ("tool_error", False)


def set_delegation_depth(depth: int) -> None:
    """Restore ContextVar to a specific delegation depth (session resume).

    Args:
        depth: The delegation depth to set.
    """
    _delegation_depth_var.set(depth)


def initialize_delegation_depth() -> int:
    """Initialize delegation depth to zero and return it.

    Called at the start of a new trace or session.

    Returns:
        0 (the initial depth value)
    """
    _delegation_depth_var.set(0)
    logger.debug("Delegation depth initialized to 0")
    return 0


def increment_delegation_depth() -> tuple[int, bool]:
    """Increment delegation depth and check if max exceeded.

    Returns:
        Tuple of (new_depth, depth_exceeded) where exceeded = new_depth > MAX_DELEGATION_DEPTH
    """
    current = _delegation_depth_var.get()
    new_depth = current + 1
    _delegation_depth_var.set(new_depth)
    exceeded = new_depth > MAX_DELEGATION_DEPTH
    logger.debug("Delegation depth incremented: %d -> %d (exceeded=%s)", current, new_depth, exceeded)
    return (new_depth, exceeded)


def decrement_delegation_depth() -> int:
    """Decrement delegation depth with underflow protection.

    Returns:
        New depth (minimum 0)
    """
    current = _delegation_depth_var.get()
    new_depth = max(0, current - 1)
    _delegation_depth_var.set(new_depth)
    logger.debug("Delegation depth decremented: %d -> %d", current, new_depth)
    return new_depth


def get_delegation_depth() -> int:
    """Get current delegation depth.

    Returns:
        Current depth value
    """
    return _delegation_depth_var.get()
