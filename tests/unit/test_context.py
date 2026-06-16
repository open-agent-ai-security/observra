"""Unit tests for context module."""

from decimal import Decimal

from observra.core.context import (
    initialize_session,
    initialize_trace,
    get_session_id,
    get_trace_id,
    get_span_id,
    new_span,
    reset_session_cost,
    add_to_session_cost,
    get_session_cost,
)


def test_initialize_session_default():
    """Test that initialize_session generates ULID by default."""
    initialize_session()
    session_id = get_session_id()

    assert session_id
    assert len(session_id) == 26  # ULID length


def test_initialize_session_custom():
    """Test that initialize_session accepts custom session_id."""
    initialize_session("my-session")
    session_id = get_session_id()

    assert session_id == "my-session"


def test_initialize_trace():
    """Test that initialize_trace sets trace_id and span_id."""
    initialize_trace()

    trace_id = get_trace_id()
    span_id = get_span_id()

    assert trace_id
    assert span_id
    assert len(trace_id) == 26
    assert len(span_id) == 26


def test_new_span_changes_span_id():
    """Test that new_span creates a different span_id."""
    initialize_trace()
    original_span_id = get_span_id()

    new_span_id = new_span()

    assert new_span_id != original_span_id
    assert get_span_id() == new_span_id


def test_session_cost_accumulation():
    """Test session cost accumulation."""
    reset_session_cost()
    add_to_session_cost(Decimal('1.50'))

    assert get_session_cost() == Decimal('1.50')

    add_to_session_cost(Decimal('0.75'))
    assert get_session_cost() == Decimal('2.25')


def test_session_cost_reset():
    """Test that reset_session_cost clears accumulated cost."""
    add_to_session_cost(Decimal('10.00'))
    assert get_session_cost() > 0

    reset_session_cost()
    assert get_session_cost() == Decimal('0')
