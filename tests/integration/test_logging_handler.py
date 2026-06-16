"""Integration tests for TelemetryLoggingHandler."""

import logging

from observra.core.logging_handler import TelemetryLoggingHandler
from observra.core.queue import DropOldestQueue


def test_handler_creates_event():
    """Test handler creates event without crashing (smoke test)."""
    handler = TelemetryLoggingHandler(queue=None)

    # Create log record
    record = logging.LogRecord(
        name="test_logger",
        level=logging.INFO,
        pathname="test.py",
        lineno=10,
        msg="Test message",
        args=(),
        exc_info=None
    )

    # Should not raise error (event created but not routed since no queue)
    try:
        handler.emit(record)
    except Exception as e:
        raise AssertionError(f"Handler should not crash: {e}")


def test_handler_routes_to_queue():
    """Test handler routes events to queue."""
    queue = DropOldestQueue(maxsize=10)
    handler = TelemetryLoggingHandler(queue=queue)

    # Create logger and attach handler
    logger = logging.getLogger("test_queue_routing")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    # Emit log message
    logger.info("Test message for queue routing")

    # Verify queue has event
    assert queue.qsize() == 1

    # Clean up
    logger.removeHandler(handler)


def test_handler_with_formatter():
    """Test handler respects formatter."""
    queue = DropOldestQueue(maxsize=10)
    handler = TelemetryLoggingHandler(queue=queue)

    # Set formatter
    formatter = logging.Formatter('%(levelname)s - %(message)s')
    handler.setFormatter(formatter)

    # Create log record
    record = logging.LogRecord(
        name="test_logger",
        level=logging.INFO,
        pathname="test.py",
        lineno=10,
        msg="Test message",
        args=(),
        exc_info=None
    )

    # Emit with formatter
    handler.emit(record)

    # Verify event was created and queued
    assert queue.qsize() == 1


def test_handler_error_handling():
    """Test handler error handling with broken queue."""
    # Create mock queue that raises on put_nowait
    class BrokenQueue:
        def put_nowait(self, item):
            raise RuntimeError("Queue is broken")

    handler = TelemetryLoggingHandler(queue=BrokenQueue())

    # Create log record
    record = logging.LogRecord(
        name="test_logger",
        level=logging.INFO,
        pathname="test.py",
        lineno=10,
        msg="Test message",
        args=(),
        exc_info=None
    )

    # Should not crash despite broken queue
    try:
        handler.emit(record)
    except Exception:
        raise AssertionError("Handler should handle errors gracefully")


def test_handler_log_levels():
    """Test handler respects level filtering."""
    queue = DropOldestQueue(maxsize=10)
    handler = TelemetryLoggingHandler(queue=queue, level=logging.WARNING)

    # Create logger and attach handler
    logger = logging.getLogger("test_level_filtering")
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)

    # Emit INFO log (should be filtered by handler)
    logger.info("This should not be captured")

    # Queue should be empty (handler level is WARNING, so INFO is filtered)
    assert queue.qsize() == 0

    # Emit WARNING log (should be captured)
    logger.warning("This should be captured")

    # Queue should now have 1 event
    assert queue.qsize() == 1

    # Clean up
    logger.removeHandler(handler)
