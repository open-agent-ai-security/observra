"""ProcessPoolExecutor wrapper for StorageBackend write offload (PERF-04, PERF-05).

This module provides PooledWriter, which wraps any StorageBackend and offloads
write operations to a process pool, releasing the GIL during I/O-bound storage
writes (SQLite batch inserts, JSONL file writes).

Per CONTEXT.md decisions:
- Worker pool size: min(4, os.cpu_count())
- Serialization: pickle (frozen dataclasses are zero-config picklable)
- Crash isolation: catch BrokenProcessPool, recreate pool, retry batch once
- BoundedSemaphore gates concurrent batch submissions (PERF-05 requirement)
"""

from __future__ import annotations

import logging
import os
import threading
import time
from concurrent.futures import Future, ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from typing import Iterator

from .events import TelemetryEvent
from .metrics import _registry
from .types import BackendStats

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level subprocess functions (must be at module level for pickle)
# ---------------------------------------------------------------------------

# Global backend used inside each subprocess worker
_worker_backend = None


def _init_worker(backend_type: str, backend_kwargs: dict) -> None:
    """Initialize the per-process storage backend.

    Called once per subprocess when the ProcessPoolExecutor creates a new worker.
    Each subprocess gets its own independent backend connection.

    Args:
        backend_type: Backend type string ('jsonl', 'otel', etc.)
        backend_kwargs: Keyword arguments for the backend constructor
    """
    global _worker_backend
    # Import here to avoid circular imports in the subprocess
    from observra.core.storage import create_backend  # noqa: PLC0415
    _worker_backend = create_backend(backend_type, **backend_kwargs)


def _write_batch_in_worker(batch: list[TelemetryEvent]) -> int:
    """Execute in subprocess -- writes batch and flushes backend.

    This function runs in a subprocess worker. The global _worker_backend
    was initialized by _init_worker() when the process was created.

    Args:
        batch: List of TelemetryEvent instances to write

    Returns:
        Count of events written (for logging)
    """
    global _worker_backend
    assert _worker_backend is not None, "_init_worker must be called first"
    for event in batch:
        _worker_backend.write(event)
    _worker_backend.flush()
    return len(batch)


# ---------------------------------------------------------------------------
# PooledWriter class
# ---------------------------------------------------------------------------


class PooledWriter:
    """ProcessPoolExecutor wrapper for StorageBackend write offload (PERF-04, PERF-05).

    Wraps any StorageBackend and offloads write operations to a process pool,
    releasing the GIL during I/O-bound storage writes (SQLite batch inserts,
    JSONL file writes).

    Each subprocess worker creates its own independent backend instance via
    the initializer pattern, which avoids pickling the backend object itself
    (file handles are not picklable).

    Per CONTEXT.md decisions:
    - Worker pool size: min(4, os.cpu_count())
    - Serialization: pickle (frozen dataclasses are zero-config picklable)
    - Crash isolation: catch BrokenProcessPool, recreate pool, retry batch once
    - BoundedSemaphore gates concurrent batch submissions (value = max_workers)
    - Semaphore released via done callback (_on_batch_done) to prevent leaks

    PERF-05 semaphore behavior:
    - Semaphore value = max_workers (one slot per worker)
    - submit_batch() acquires before submitting; done callback releases
    - If all workers are busy, acquire(timeout=batch_timeout) provides backpressure
    - Semaphore timeout logs a warning but still submits (non-blocking fallback)
    - close() drains in-flight batches by acquiring all slots before shutdown

    Usage:
        pw = PooledWriter(
            backend_type="jsonl",
            backend_kwargs={"path": "telemetry.jsonl"},
        )
        pw.submit_batch([event1, event2, event3])
        pw.close()
    """

    def __init__(
        self,
        backend_type: str,
        backend_kwargs: dict,
        max_workers: int | None = None,
        batch_timeout: float = 0.5,
    ) -> None:
        """Initialize PooledWriter with process pool and main-process backend.

        Args:
            backend_type: Backend type string ('jsonl', 'otel', etc.)
            backend_kwargs: Keyword arguments for the backend constructor.
                Each subprocess worker creates its own instance using these kwargs.
            max_workers: Maximum subprocess workers. Defaults to min(4, cpu_count).
            batch_timeout: Timeout in seconds for BoundedSemaphore acquire.
                Same value as BackgroundWorker batch_timeout (500ms per CONTEXT.md).
                Also used as default by BackgroundWorker for consistency.
        """
        from .storage import create_backend  # Lazy import to avoid circular deps

        self._backend_type = backend_type
        self._backend_kwargs = backend_kwargs
        self._max_workers = max_workers if max_workers is not None else min(4, os.cpu_count() or 1)
        self._batch_timeout = batch_timeout

        # OBS-03: register the sink label so get_metrics()["labels"]["sink"] reflects backend type
        _registry.set_label("sink", backend_type)

        # Main-process backend for get_stats(), query(), flush(), close()
        # (These ops don't need GIL release and benefit from direct access)
        self._backend = create_backend(backend_type, **backend_kwargs)

        # Create the subprocess worker pool
        self._executor: ProcessPoolExecutor = self._create_pool()

        # BoundedSemaphore controls concurrent batch submissions to the pool.
        # Value = max concurrent in-flight batches (matches max_workers so each
        # worker can have one batch in-flight simultaneously).
        # PERF-05 requirement: semaphore acts as rate limiter for pool submissions.
        self._semaphore = threading.BoundedSemaphore(value=self._max_workers)

        # Counters for monitoring and stats
        # WR-05: _errors is written from the concurrent.futures callback thread;
        # use _stats_lock to avoid torn reads in get_stats().
        self._errors: int = 0
        self._batches_submitted: int = 0
        self._events_submitted: int = 0
        self._stats_lock = threading.Lock()

    def _create_pool(self) -> ProcessPoolExecutor:
        """Create a new ProcessPoolExecutor with backend initializer.

        Each subprocess worker runs _init_worker() on startup to create
        its own independent backend connection.

        Returns:
            New ProcessPoolExecutor with initializer configured
        """
        return ProcessPoolExecutor(
            max_workers=self._max_workers,
            initializer=_init_worker,
            initargs=(self._backend_type, self._backend_kwargs),
        )

    def _on_batch_done(self, future: Future) -> None:
        """Callback when a batch future completes -- releases semaphore.

        Registered via future.add_done_callback() immediately after submit.
        Called by the concurrent.futures thread pool (not the main thread).

        Error isolation: exceptions from worker subprocesses are logged
        but never re-raised. The main pipeline continues regardless.

        T-32-08 mitigation: errors logged with error level + batch content
        available via _errors counter in get_stats().
        T-32-09 mitigation: try/finally ensures semaphore is always released.
        """
        try:
            exc = future.exception(timeout=0)
            if exc is not None:
                logger.error(
                    "Batch write failed in worker: %s",
                    exc,
                    exc_info=exc,
                )
                with self._stats_lock:
                    self._errors += 1
                _registry.inc_counter("observra_backend_write_failure_total")
        except Exception:
            pass  # CancelledError or timeout -- semaphore still released below
        finally:
            # T-32-09: always release semaphore; catch ValueError on double-release
            # (can happen if timeout path already released before callback fires)
            try:
                self._semaphore.release()
            except ValueError:
                pass

    def submit_batch(self, batch: list[TelemetryEvent]) -> None:
        """Submit a batch of events to the process pool for writing.

        Uses BoundedSemaphore to gate concurrent batch submissions (PERF-05).
        The semaphore limits in-flight batches to max_workers, providing
        natural backpressure when the pool is saturated.

        Semaphore is acquired before submit and released via _on_batch_done
        callback when the future completes (success or failure).

        On BrokenProcessPool, the pool is recreated and the batch is retried once.
        If the retry also fails, logs an error without further retrying.

        T-32-06 mitigation: acquire(timeout=batch_timeout) prevents infinite block.

        Args:
            batch: List of TelemetryEvent instances to write.
                Empty list is a no-op.
        """
        if not batch:
            return

        # Acquire semaphore -- blocks if max concurrent batches in flight.
        # This is the PERF-05 "BoundedSemaphore threshold" trigger:
        # when all workers are busy, the semaphore blocks the calling thread
        # (BackgroundWorker daemon thread) which causes batch accumulation
        # to pause, providing natural backpressure.
        # T-32-06: timeout prevents deadlock if callback never fires.
        acquired = self._semaphore.acquire(timeout=self._batch_timeout)
        if not acquired:
            # Semaphore timed out -- pool may be overloaded. Log and continue
            # submission anyway (non-blocking fallback path).
            logger.warning(
                "Semaphore acquire timed out (%.1fs), pool may be overloaded",
                self._batch_timeout,
            )

        try:
            _t0 = time.perf_counter()
            future = self._executor.submit(_write_batch_in_worker, batch)
            # Register callback to release semaphore only if we acquired it.
            # When acquired=False (timeout path), the semaphore was never taken
            # so we must not release it — doing so would corrupt the semaphore
            # invariant by incrementing it above its bound (CR-02).
            if acquired:
                future.add_done_callback(self._on_batch_done)
            # Register latency callback: records elapsed wall time if no exception.
            # Always register this regardless of semaphore acquisition.
            def _record_latency(fut: Future, t0: float = _t0) -> None:
                if fut.exception() is None:
                    elapsed = time.perf_counter() - t0
                    _registry.get_histogram("observra_write_latency_seconds").push(elapsed)
            future.add_done_callback(_record_latency)
            with self._stats_lock:
                self._batches_submitted += 1
                self._events_submitted += len(batch)
            logger.debug(
                "Pool batch submitted: %d events (total batches: %d)",
                len(batch),
                self._batches_submitted,
            )
        except BrokenProcessPool:
            logger.warning(
                "ProcessPool broken, recreating pool and retrying batch once "
                "(batch size: %d)",
                len(batch),
            )
            # Release semaphore -- no callback will fire for the failed submit
            if acquired:
                try:
                    self._semaphore.release()
                except ValueError:
                    pass
            self._executor = self._create_pool()
            # Acquire semaphore again for the retry
            retry_acquired = self._semaphore.acquire(timeout=self._batch_timeout)
            try:
                future = self._executor.submit(_write_batch_in_worker, batch)
                future.add_done_callback(self._on_batch_done)
                self._batches_submitted += 1
                self._events_submitted += len(batch)
                logger.debug("Retry succeeded after pool recreation")
            except Exception as e:
                logger.error(
                    "Retry after pool recreation failed: %s -- batch of %d events lost",
                    e,
                    len(batch),
                )
                self._errors += 1
                if retry_acquired:
                    try:
                        self._semaphore.release()
                    except ValueError:
                        pass
        except Exception as e:
            logger.warning(
                "Pool submit failed: %s (batch size: %d)", e, len(batch)
            )
            with self._stats_lock:
                self._errors += 1
            if acquired:
                try:
                    self._semaphore.release()
                except ValueError:
                    pass

    # ------------------------------------------------------------------
    # StorageBackend protocol compliance
    # ------------------------------------------------------------------

    def write(self, event: TelemetryEvent) -> None:
        """Write a single event via submit_batch([event]) for uniform path.

        Args:
            event: TelemetryEvent to write
        """
        self.submit_batch([event])

    def flush(self) -> None:
        """Flush the main-process backend.

        Note: Subprocess workers flush after each batch submission in
        _write_batch_in_worker(). This flushes the main-process backend
        used for query/get_stats.
        """
        self._backend.flush()

    def close(self) -> None:
        """Shut down the process pool and close the main-process backend.

        Drains in-flight batches by acquiring all semaphore slots before
        calling executor.shutdown(). This ensures no batches are lost.

        T-32-07 mitigation: drains all in-flight batches before shutdown.
        """
        # Drain in-flight batches by acquiring all semaphore slots.
        # Each acquired slot means one fewer batch is in-flight.
        # After acquiring all slots, no batches are in-flight.
        acquired_count = 0
        for _ in range(self._max_workers):
            got = self._semaphore.acquire(timeout=5.0)
            if got:
                acquired_count += 1
        if acquired_count < self._max_workers:
            logger.warning(
                "close(): only acquired %d/%d semaphore slots within 5s timeout "
                "-- some in-flight batches may not complete",
                acquired_count,
                self._max_workers,
            )
        try:
            self._executor.shutdown(wait=True, cancel_futures=False)
        except Exception as e:
            logger.warning("Error shutting down process pool: %s", e)
        self._backend.close()

    def get_stats(self) -> BackendStats:
        """Get backend statistics, augmented with pool-specific counters.

        Returns:
            BackendStats dict from the underlying backend, with extra keys:
            - pool_errors: Number of batch write errors in workers
            - pool_batches: Number of batches successfully submitted to pool
            - pool_events: Number of events submitted across all batches
        """
        stats = self._backend.get_stats()
        # Inject pool stats as extra fields (BackendStats is a TypedDict but
        # callers can access extra keys via dict access).
        # WR-05: hold _stats_lock for a consistent snapshot.
        with self._stats_lock:
            stats["pool_errors"] = self._errors
            stats["pool_batches"] = self._batches_submitted
            stats["pool_events"] = self._events_submitted
        return stats

    def query(
        self,
        *,
        event_type: str | None = None,
        agent_id: str | None = None,
        from_ts: float | None = None,
        to_ts: float | None = None,
        limit: int = 1000,
    ) -> Iterator[TelemetryEvent]:
        """Query stored events via the main-process backend.

        Args:
            event_type: Filter by event type
            agent_id: Filter by agent name
            from_ts: Start of time range (Unix timestamp)
            to_ts: End of time range (Unix timestamp)
            limit: Maximum number of results

        Yields:
            TelemetryEvent matching the filters
        """
        yield from self._backend.query(
            event_type=event_type,
            agent_id=agent_id,
            from_ts=from_ts,
            to_ts=to_ts,
            limit=limit,
        )
