# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0

"""MultiBackend: fan-out compositor that writes to multiple StorageBackends.

All write/flush/close/query calls are forwarded to every registered backend
sequentially. A failure in one backend is isolated — all other backends
still receive the call.

No external dependencies — always importable without extras.
"""

from __future__ import annotations

import logging
from typing import Iterator, List

from observra.core.events import TelemetryEvent
from observra.core.types import BackendStats

logger = logging.getLogger(__name__)


class MultiBackend:
    """Fan-out compositor: fans out writes to multiple StorageBackends.

    Implements StorageBackend Protocol. All write/flush/close/query calls are
    forwarded to every backend sequentially. A failure in one backend is
    isolated — all other backends still receive the call.

    query() delegates to the first backend that supports it (does not raise
    NotImplementedError). If no backend supports query(), raises NotImplementedError.

    get_stats() aggregates event_count by summing counts from all backends,
    takes min of oldest_event_ts, max of newest_event_ts, and reports
    backend_type="multi".

    Usage::

        from observra.backends.jsonl import JSONLBackend
        from observra.backends.otel import OTelExportBackend
        from observra.backends.multi import MultiBackend

        multi = MultiBackend([
            JSONLBackend(path="telemetry.jsonl"),
            OTelExportBackend(),
        ])
        # Both backends receive every write()
        multi.write(event)

        # Querying is not supported in v1.

    Via factory::

        from observra.core.storage import create_backend
        jsonl = create_backend("jsonl", path="telemetry.jsonl")
        otel = create_backend("otel")
        multi = create_backend("multi", backends=[jsonl, otel])
    """

    BACKEND_TYPE = "multi"

    def __init__(self, backends: List) -> None:
        """Initialize MultiBackend with a list of backends.

        Args:
            backends: Non-empty list of StorageBackend instances to fan out to.

        Raises:
            ValueError: If backends is empty.
        """
        if not backends:
            raise ValueError(
                "MultiBackend requires at least one backend. Provide a non-empty list of StorageBackend instances."
            )
        self._backends = list(backends)
        self._errors: int = 0

    def write(self, event: TelemetryEvent) -> None:
        """Write event to all registered backends with per-backend error isolation.

        A failure in one backend does not prevent other backends from receiving
        the event. Errors are logged but not re-raised.

        Args:
            event: TelemetryEvent to write to all backends
        """
        for backend in self._backends:
            try:
                backend.write(event)
            except Exception as e:
                self._errors += 1
                logger.error(
                    "MultiBackend.write error in %s: %s",
                    type(backend).__name__,
                    e,
                    exc_info=True,
                )

    def flush(self) -> None:
        """Flush all backends with per-backend error isolation.

        Errors from individual backends are logged but not re-raised.
        """
        for backend in self._backends:
            try:
                backend.flush()
            except Exception as e:
                self._errors += 1
                logger.error(
                    "MultiBackend.flush error in %s: %s",
                    type(backend).__name__,
                    e,
                    exc_info=True,
                )

    def close(self) -> None:
        """Close all backends with per-backend error isolation.

        Errors from individual backends are logged but not re-raised.
        Each backend's close() is still called even if a previous one failed.
        """
        for backend in self._backends:
            try:
                backend.close()
            except Exception as e:
                self._errors += 1
                logger.error(
                    "MultiBackend.close error in %s: %s",
                    type(backend).__name__,
                    e,
                    exc_info=True,
                )

    def get_stats(self) -> BackendStats:
        """Return aggregated statistics across all backends.

        Aggregation strategy:
        - event_count: sum from all backends (total events written across all)
        - oldest_event_ts: minimum across all backends (earliest event seen)
        - newest_event_ts: maximum across all backends (most recent event seen)
        - bytes_written: 0 (not meaningful to sum across backends)
        - backend_type: "multi"

        Backends that raise during get_stats() are skipped (warning logged).

        Returns:
            BackendStats aggregated across all registered backends
        """
        total_events = 0
        oldest: float | None = None
        newest: float | None = None

        for backend in self._backends:
            try:
                stats = backend.get_stats()
                total_events += stats.get("event_count", 0)
                ts_old = stats.get("oldest_event_ts")
                ts_new = stats.get("newest_event_ts")
                if ts_old is not None and (oldest is None or ts_old < oldest):
                    oldest = ts_old
                if ts_new is not None and (newest is None or ts_new > newest):
                    newest = ts_new
            except Exception as e:
                logger.warning(
                    "MultiBackend.get_stats error from %s: %s",
                    type(backend).__name__,
                    e,
                )

        return BackendStats(
            bytes_written=0,
            event_count=total_events,
            backend_type=self.BACKEND_TYPE,
            oldest_event_ts=oldest,
            newest_event_ts=newest,
        )

    def query(
        self,
        *,
        event_type: str | None = None,
        agent_id: str | None = None,
        from_ts: float | None = None,
        to_ts: float | None = None,
        limit: int = 1000,
    ) -> Iterator[TelemetryEvent]:
        """Delegate query to the first backend that supports it.

        Iterates through backends in order. If a backend raises NotImplementedError,
        it is skipped and the next backend is tried. The first backend that returns
        without raising NotImplementedError provides the results.

        Args:
            event_type: Filter by event type (e.g., 'model_response', 'tool_call')
            agent_id: Filter by agent name
            from_ts: Start of time range (Unix timestamp)
            to_ts: End of time range (Unix timestamp)
            limit: Maximum number of results (default: 1000)

        Yields:
            TelemetryEvent matching the filters from the first supporting backend

        Raises:
            NotImplementedError: If no backend in the list supports query().
        """
        for backend in self._backends:
            try:
                return backend.query(
                    event_type=event_type,
                    agent_id=agent_id,
                    from_ts=from_ts,
                    to_ts=to_ts,
                    limit=limit,
                )
            except NotImplementedError:
                continue
        raise NotImplementedError("No backend in MultiBackend supports query(). Querying is not supported in v1.")
