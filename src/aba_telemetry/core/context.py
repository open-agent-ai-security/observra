"""Context propagation for distributed tracing across async boundaries."""

import logging
from contextvars import ContextVar
from decimal import Decimal
from typing import Optional

from .utils import generate_ulid

logger = logging.getLogger(__name__)

# Module-level ContextVar declarations (prefixed with 'default.' for clarity)
trace_id_var: ContextVar[str] = ContextVar('default.trace_id')
session_id_var: ContextVar[str] = ContextVar('default.session_id')
span_id_var: ContextVar[str] = ContextVar('default.span_id')
session_cost_var: ContextVar[Decimal] = ContextVar('default.session_cost', default=Decimal('0'))


def create_scoped_context(framework: str) -> dict:
    """Create a framework-scoped set of ContextVars.

    Returns a dict with keys: trace_id, session_id, span_id, session_cost.
    Each ContextVar's debug name is prefixed with the framework name
    (e.g., 'adk.trace_id') to aid debugging, but isolation comes from
    each call creating NEW ContextVar objects (ContextVar identity is
    object identity, not name string).

    Args:
        framework: Framework name prefix (e.g., 'adk', 'claude').

    Returns:
        Dict mapping var names to fresh ContextVar instances.
    """
    return {
        'trace_id': ContextVar(f'{framework}.trace_id'),
        'session_id': ContextVar(f'{framework}.session_id'),
        'span_id': ContextVar(f'{framework}.span_id'),
        'session_cost': ContextVar(f'{framework}.session_cost', default=Decimal('0')),
    }


def initialize_trace() -> None:
    """Initialize trace context with new trace_id and span_id.

    Called in before_run_callback to start a new trace.
    """
    trace_id = generate_ulid()
    span_id = generate_ulid()
    trace_id_var.set(trace_id)
    span_id_var.set(span_id)
    logger.debug(f"Initialized trace: trace_id={trace_id}, span_id={span_id}")


def initialize_session(session_id: Optional[str] = None) -> None:
    """Initialize or update session context.

    Args:
        session_id: Optional session identifier. If None, generates new ULID.
    """
    if session_id is None:
        session_id = generate_ulid()
    session_id_var.set(session_id)
    logger.debug(f"Initialized session: session_id={session_id}")


def new_span() -> str:
    """Create a new span for nested operations.

    Returns:
        The newly generated span_id
    """
    span_id = generate_ulid()
    span_id_var.set(span_id)
    logger.debug(f"Created new span: span_id={span_id}")
    return span_id


def get_trace_id() -> str:
    """Get current trace_id from context.

    Returns:
        Current trace_id, or generates new one if not set (fallback safety)
    """
    try:
        return trace_id_var.get()
    except LookupError:
        logger.warning("trace_id not set, generating fallback")
        trace_id = generate_ulid()
        trace_id_var.set(trace_id)
        return trace_id


def get_session_id() -> str:
    """Get current session_id from context.

    Returns:
        Current session_id, or generates new one if not set (fallback safety)
    """
    try:
        return session_id_var.get()
    except LookupError:
        logger.warning("session_id not set, generating fallback")
        session_id = generate_ulid()
        session_id_var.set(session_id)
        return session_id


def get_span_id() -> str:
    """Get current span_id from context.

    Returns:
        Current span_id, or generates new one if not set (fallback safety)
    """
    try:
        return span_id_var.get()
    except LookupError:
        logger.warning("span_id not set, generating fallback")
        span_id = generate_ulid()
        span_id_var.set(span_id)
        return span_id


def get_session_cost() -> Decimal:
    """Get current session's accumulated cost.

    Returns:
        Current session cost in USD (Decimal)
    """
    return session_cost_var.get()


def add_to_session_cost(amount: Decimal) -> Decimal:
    """Add cost to current session's total.

    Args:
        amount: Cost amount to add (Decimal in USD)

    Returns:
        New session total cost (Decimal)
    """
    current = session_cost_var.get()
    new_total = current + amount
    session_cost_var.set(new_total)
    logger.debug(f"Session cost updated: ${current} + ${amount} = ${new_total}")
    return new_total


def reset_session_cost() -> None:
    """Reset session cost to zero.

    Called at the start of a new session or run to clear accumulated costs.
    """
    session_cost_var.set(Decimal('0'))
    logger.debug("Session cost reset to $0")
