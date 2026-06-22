# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Tests for MultiBackend (EXPT-02: fan-out compositor).

Covers:
- Fan-out to multiple backends on write/flush/close
- Per-backend error isolation (one failure does not affect others)
- query() delegation to first supporting backend
- query() raises NotImplementedError if no backend supports it
- get_stats() aggregation and backend_type="multi"
- Constructor validation (requires at least one backend)

Uses simple inline mock classes (MockBackend, QueryableBackend, FailingBackend)
to avoid external mock dependencies.
"""

import pytest

from observra.backends.multi import MultiBackend
from observra.core.events import create_event
from observra.core.types import BackendStats

# ---------------------------------------------------------------------------
# Inline mock backend helpers
# ---------------------------------------------------------------------------


class MockBackend:
    """Minimal backend that records calls for assertion."""

    def __init__(self):
        self.events = []
        self.flushed = False
        self.closed = False

    def write(self, event):
        self.events.append(event)

    def flush(self):
        self.flushed = True

    def close(self):
        self.closed = True

    def get_stats(self):
        return BackendStats(
            bytes_written=0,
            event_count=len(self.events),
            backend_type="mock",
            oldest_event_ts=None,
            newest_event_ts=None,
        )

    def query(self, **kwargs):
        raise NotImplementedError("MockBackend does not support query()")


class QueryableBackend(MockBackend):
    """MockBackend that implements query() by returning its events."""

    def query(self, **kwargs):
        return iter(list(self.events))


class FailingBackend:
    """Backend that raises RuntimeError on every method call."""

    def write(self, event):
        raise RuntimeError("write failed")

    def flush(self):
        raise RuntimeError("flush failed")

    def close(self):
        raise RuntimeError("close failed")

    def get_stats(self):
        raise RuntimeError("stats failed")

    def query(self, **kwargs):
        raise RuntimeError("query failed")


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _event():
    """Create a minimal TelemetryEvent for testing."""
    return create_event("model_response", model_name="gpt-4o", framework="openai")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestConstruction:
    """MultiBackend construction validation."""

    def test_multi_backend_requires_at_least_one_backend(self):
        """Empty backend list raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            MultiBackend([])
        assert "at least one" in str(exc_info.value).lower()

    def test_multi_backend_accepts_single_backend(self):
        """Single backend list is valid."""
        backend = MockBackend()
        multi = MultiBackend([backend])
        assert multi is not None

    def test_multi_backend_accepts_multiple_backends(self):
        """Multiple backends list is valid."""
        backends = [MockBackend(), MockBackend(), MockBackend()]
        multi = MultiBackend(backends)
        assert multi is not None


class TestWriteFanOut:
    """write() fans out to all backends."""

    def test_write_fans_out_to_all_backends(self):
        """Write an event; verify both backends received it."""
        b1 = MockBackend()
        b2 = MockBackend()
        multi = MultiBackend([b1, b2])

        event = _event()
        multi.write(event)

        assert len(b1.events) == 1
        assert b1.events[0] is event
        assert len(b2.events) == 1
        assert b2.events[0] is event

    def test_write_error_isolation(self):
        """First backend raises on write(); second backend still receives the event."""
        failing = FailingBackend()
        good = MockBackend()
        multi = MultiBackend([failing, good])

        event = _event()
        multi.write(event)

        # Second backend should have received the event
        assert len(good.events) == 1
        assert good.events[0] is event
        # Error counter should be incremented
        assert multi._errors == 1

    def test_write_multiple_events_all_received(self):
        """Write 3 events; all backends receive all 3."""
        b1 = MockBackend()
        b2 = MockBackend()
        multi = MultiBackend([b1, b2])

        events = [_event() for _ in range(3)]
        for e in events:
            multi.write(e)

        assert len(b1.events) == 3
        assert len(b2.events) == 3


class TestFlushFanOut:
    """flush() fans out to all backends."""

    def test_flush_fans_out_to_all_backends(self):
        """Call flush(); verify all backends received flush call."""
        b1 = MockBackend()
        b2 = MockBackend()
        multi = MultiBackend([b1, b2])

        multi.flush()

        assert b1.flushed is True
        assert b2.flushed is True

    def test_flush_error_isolation(self):
        """One backend raises on flush(); others still flushed."""
        failing = FailingBackend()
        good = MockBackend()
        multi = MultiBackend([failing, good])

        multi.flush()

        assert good.flushed is True
        assert multi._errors == 1


class TestCloseFanOut:
    """close() fans out to all backends."""

    def test_close_fans_out_to_all_backends(self):
        """Call close(); verify all backends received close call."""
        b1 = MockBackend()
        b2 = MockBackend()
        multi = MultiBackend([b1, b2])

        multi.close()

        assert b1.closed is True
        assert b2.closed is True

    def test_close_error_isolation(self):
        """One backend raises on close(); others still closed."""
        failing = FailingBackend()
        good = MockBackend()
        multi = MultiBackend([failing, good])

        multi.close()

        assert good.closed is True
        assert multi._errors == 1


class TestGetStats:
    """get_stats() aggregation."""

    def test_get_stats_returns_multi_type(self):
        """get_stats() always returns backend_type='multi'."""
        multi = MultiBackend([MockBackend()])
        stats = multi.get_stats()
        assert stats["backend_type"] == "multi"

    def test_get_stats_sums_event_count(self):
        """event_count is summed across all backends."""
        b1 = MockBackend()
        b2 = MockBackend()
        multi = MultiBackend([b1, b2])

        # Write 2 events to b1, 2 events to b2 (fan-out writes to both)
        for _ in range(2):
            multi.write(_event())

        stats = multi.get_stats()
        # Both backends have 2 events each -> total = 4
        assert stats["event_count"] == 4

    def test_get_stats_handles_failing_backend(self):
        """get_stats() skips backends that raise and returns partial results."""
        good = MockBackend()
        multi = MultiBackend([good, FailingBackend()])

        multi.write(_event())

        # Should not raise — FailingBackend.get_stats() is skipped
        stats = multi.get_stats()
        assert stats["event_count"] == 1  # only from good backend


class TestQueryDelegation:
    """query() delegates to first supporting backend."""

    def test_query_delegates_to_first_supporting_backend(self):
        """First backend raises NotImplementedError; second returns results."""
        not_queryable = MockBackend()  # raises NotImplementedError on query
        queryable = QueryableBackend()
        multi = MultiBackend([not_queryable, queryable])

        # Write an event directly to queryable so query() has something to return
        event = _event()
        queryable.events.append(event)

        results = list(multi.query())
        assert len(results) == 1
        assert results[0] is event

    def test_query_all_raise_not_implemented(self):
        """All backends raise NotImplementedError; MultiBackend raises NotImplementedError."""
        b1 = MockBackend()
        b2 = MockBackend()
        multi = MultiBackend([b1, b2])

        with pytest.raises(NotImplementedError):
            list(multi.query())

    def test_query_skips_not_implemented_and_delegates(self):
        """Three backends: first two raise NotImplementedError, third returns results."""
        b1 = MockBackend()
        b2 = MockBackend()
        b3 = QueryableBackend()
        multi = MultiBackend([b1, b2, b3])

        event = _event()
        b3.events.append(event)

        results = list(multi.query())
        assert len(results) == 1
