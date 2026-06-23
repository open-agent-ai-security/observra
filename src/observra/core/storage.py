# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Storage backend protocol and factory for telemetry events."""

import logging
from typing import Iterator, Protocol, runtime_checkable

from .events import TelemetryEvent
from .types import BackendStats

logger = logging.getLogger(__name__)


@runtime_checkable
class StorageBackend(Protocol):
    """Protocol defining the storage backend interface.

    All storage backends must implement these methods to be compatible
    with the telemetry system.
    """

    def write(self, event: TelemetryEvent) -> None:
        """Write a single event to storage.

        May buffer internally for performance. Call flush() to ensure
        durability.

        Args:
            event: TelemetryEvent to write
        """
        ...

    def flush(self) -> None:
        """Flush any buffered writes to durable storage.

        Ensures all previously written events are persisted.
        """
        ...

    def close(self) -> None:
        """Close the backend and release all resources.

        Should call flush() internally to ensure no data loss.
        """
        ...

    def get_stats(self) -> BackendStats:
        """Get backend statistics.

        Returns:
            BackendStats with bytes_written, event_count, backend_type,
            oldest_event_ts, newest_event_ts.
        """
        ...

    def query(
        self,
        *,
        event_type: str | None = None,
        agent_id: str | None = None,
        from_ts: float | None = None,
        to_ts: float | None = None,
        limit: int = 1000,
    ) -> Iterator[TelemetryEvent]:
        """Query stored events with optional filters.

        All parameters are keyword-only to prevent accidental positional misuse.

        Args:
            event_type: Filter by event type (e.g., 'after_model', 'before_tool')
            agent_id: Filter by agent name
            from_ts: Start of time range (Unix timestamp). Use datetime.timestamp() to convert.
            to_ts: End of time range (Unix timestamp). Use datetime.timestamp() to convert.
            limit: Maximum number of results (default: 1000). Required to prevent
                accidentally loading millions of rows.

        Yields:
            TelemetryEvent matching the filters, ordered by timestamp ascending.

        Raises:
            NotImplementedError: If this backend does not support querying.
        """
        ...


def create_backend(backend_type: str, **kwargs) -> StorageBackend:
    """Factory function to create storage backends.

    Args:
        backend_type: Type of backend ('jsonl', 'otel', 'otel_log', 'webhook', or 'multi')
        **kwargs: Backend-specific configuration passed to constructor.
            For 'otel': endpoint, service_name, headers, timeout
            For 'multi': backends (list of StorageBackend instances)

    Returns:
        StorageBackend instance

    Raises:
        ValueError: If backend_type is unknown
        RuntimeError: If backend dependency is not installed

    Examples:
        >>> backend = create_backend('jsonl', path='telemetry.jsonl', max_bytes=10_485_760)
        >>> backend = create_backend('otel', endpoint='http://localhost:4318/v1/traces')
        >>> backend = create_backend('webhook', url='http://localhost:8080/events')
        >>> otel = create_backend('otel')
        >>> jsonl = create_backend('jsonl', path='telemetry.jsonl')
        >>> backend = create_backend('multi', backends=[jsonl, otel])
    """
    # Lazy imports to avoid circular dependencies
    if backend_type == "jsonl":
        from observra.backends.jsonl import JSONLBackend

        return JSONLBackend(**kwargs)
    elif backend_type == "otel":
        try:
            from observra.backends.otel import OTelExportBackend
        except ImportError:
            raise RuntimeError(
                "opentelemetry-exporter-otlp-proto-http and opentelemetry-sdk are required "
                "for the OTel export backend. Install with: pip install observra[otel]"
            )
        return OTelExportBackend(**kwargs)
    elif backend_type == "otel_log":
        try:
            from observra.backends.otel_log import OTelLogBackend
        except ImportError:
            raise RuntimeError(
                "opentelemetry-exporter-otlp-proto-http and opentelemetry-sdk are required "
                "for the OTel log backend. Install with: pip install observra[otel]"
            )
        return OTelLogBackend(**kwargs)
    elif backend_type == "webhook":
        from observra.backends.webhook import WebhookBackend

        return WebhookBackend(**kwargs)
    elif backend_type == "multi":
        from observra.backends.multi import MultiBackend

        backends_list = kwargs.pop("backends", [])
        return MultiBackend(backends_list)
    else:
        raise ValueError(
            f"Unknown backend type: {backend_type}. Supported types: 'jsonl', 'otel', 'otel_log', 'webhook', 'multi'"
        )
