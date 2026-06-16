"""Token velocity tracking using sliding window for rate detection."""

import logging
import time
from collections import deque
from contextvars import ContextVar
from decimal import Decimal
from typing import Optional

logger = logging.getLogger(__name__)

# Configuration
VELOCITY_WINDOW_SECONDS = 60
VELOCITY_MAX_SAMPLES = 100

# Session-scoped token window
_token_window_var: ContextVar[Optional[deque]] = ContextVar('token_window', default=None)


def initialize_velocity_tracker() -> deque:
    """Initialize velocity tracker with empty deque and return it.

    Called at the start of a new trace or session.

    Returns:
        The newly created deque (caller may save it for session restore).
    """
    window = deque(maxlen=VELOCITY_MAX_SAMPLES)
    _token_window_var.set(window)
    logger.debug(
        "Velocity tracker initialized (window=%ds, max_samples=%d)",
        VELOCITY_WINDOW_SECONDS,
        VELOCITY_MAX_SAMPLES,
    )
    return window


def set_velocity_tracker(window: deque) -> None:
    """Restore ContextVar to an existing window (session resume).

    Args:
        window: The deque object from a prior call to initialize_velocity_tracker().
    """
    _token_window_var.set(window)


def record_token_usage(total_tokens: int) -> Decimal:
    """Record token usage and calculate current velocity.

    Args:
        total_tokens: Number of tokens used in this operation

    Returns:
        Current tokens/minute rate as Decimal
    """
    # Get or create window (fallback if not initialized)
    window = _token_window_var.get()
    if window is None:
        window = deque(maxlen=VELOCITY_MAX_SAMPLES)
        _token_window_var.set(window)
        logger.warning(
            "Velocity tracker auto-initialized — on_initialize() may not have run. "
            "This deque is not saved to _SessionState and will not persist across asyncio tasks."
        )

    # Record current usage
    now = time.time()
    window.append((now, total_tokens))

    # Filter entries within window
    cutoff = now - VELOCITY_WINDOW_SECONDS
    valid_entries = [(ts, tokens) for ts, tokens in window if ts >= cutoff]

    # Calculate velocity
    if not valid_entries:
        return Decimal('0')

    oldest_ts = valid_entries[0][0]
    time_span = now - oldest_ts

    if time_span == 0:
        return Decimal('0')

    total_tokens_in_window = sum(tokens for _, tokens in valid_entries)
    tokens_per_minute = Decimal(str(total_tokens_in_window)) / Decimal(str(time_span)) * Decimal('60')

    logger.debug(
        "Token velocity: %.2f tokens/min (%d samples)",
        tokens_per_minute,
        len(valid_entries),
    )
    return tokens_per_minute
