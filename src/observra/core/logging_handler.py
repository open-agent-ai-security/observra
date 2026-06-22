"""Custom logging handler that bridges stdlib logging to telemetry events."""

import logging
from typing import Optional

from .events import create_event
from .queue import DropOldestQueue


class TelemetryLoggingHandler(logging.Handler):
    """Logging handler that bridges stdlib log records to telemetry events.

    This handler converts standard library logging.LogRecord objects into
    telemetry events, allowing existing logging calls to be captured in
    the telemetry system without code changes.

    Args:
        queue: Optional DropOldestQueue for routing events. If None, events
               are created but not routed (handler-only mode).
        level: Minimum log level to handle (default: logging.NOTSET)

    Example:
        >>> import logging
        >>> from observra import create_logging_handler
        >>> handler = create_logging_handler(level=logging.INFO)
        >>> logger = logging.getLogger("myapp")
        >>> logger.addHandler(handler)
        >>> logger.info("User logged in")  # Creates telemetry event
    """

    def __init__(self, queue: Optional[DropOldestQueue] = None, level: int = logging.NOTSET):
        """Initialize the telemetry logging handler.

        Args:
            queue: Optional queue for event routing
            level: Minimum log level to handle
        """
        super().__init__(level)
        self._queue = queue

    def emit(self, record: logging.LogRecord) -> None:
        """Emit a log record as a telemetry event.

        Converts the LogRecord to a telemetry event with event_type='log_message'.
        The event's data field includes log level, logger name, module, function,
        and line number for debugging.

        Args:
            record: Log record to emit
        """
        try:
            # Format message using formatter if available
            msg = self.format(record) if self.formatter else record.getMessage()

            # Create telemetry event
            event = create_event(
                event_type="log_message",
                message=msg,
                level=record.levelname,
                logger_name=record.name,
                module=record.module,
                function=record.funcName,
                line=record.lineno,
            )

            # Route to queue if available
            if self._queue:
                self._queue.put_nowait(event)
            # Else: event created but not routed (acceptable for handler-only mode)

        except Exception:
            # Use built-in error handling (calls sys.stderr.write by default)
            self.handleError(record)
