"""Deduplication registry for explicit log API + passive adapter coexistence.

Prevents duplicate events when both a passive adapter (e.g., ADK plugin) and
the explicit ``log.*()`` API emit the same event type within the same span.

The registry tracks which **source** ("log" or "adapter") first emitted each
(event_type, span_id) pair.  The *same* source may emit the pair again freely
(adapters legitimately emit the same event type multiple times in a span,
e.g. two ``session_end`` events from two ``ResultMessage`` calls).  A
*different* source is blocked — that's the actual dedup.

Uses a ContextVar so dedup state is per-request in concurrent servers.
"""

import logging
from contextvars import ContextVar

logger = logging.getLogger(__name__)

# Maps (event_type, span_id) -> source tag ("log" | "adapter")
_emitted_var: ContextVar[dict[tuple[str, str], str]] = ContextVar("dedup_emitted")


def register_emission(event_type: str, span_id: str, *, source: str = "adapter") -> bool:
    """Register that *event_type* was emitted in *span_id* by *source*.

    Args:
        event_type: The event type string (e.g. ``"session_start"``).
        span_id: The current span identifier.
        source: ``"log"`` for the explicit API, ``"adapter"`` for passive adapters.

    Returns:
        ``True`` if the caller should proceed (first emitter **or** same source).
        ``False`` if a **different** source already emitted this pair (skip).
    """
    try:
        emitted = _emitted_var.get()
    except LookupError:
        emitted: dict[tuple[str, str], str] = {}
        _emitted_var.set(emitted)

    key = (event_type, span_id)
    existing_source = emitted.get(key)

    if existing_source is not None and existing_source != source:
        logger.debug(f"Dedup: skipping {event_type} in span {span_id[:8]}... (already emitted by {existing_source})")
        return False

    # First emitter or same source — allow and record
    emitted[key] = source
    return True


def reset_dedup() -> None:
    """Clear the dedup registry.

    Called at trace initialisation and in tests to start fresh.
    """
    _emitted_var.set({})
    logger.debug("Dedup registry reset")
