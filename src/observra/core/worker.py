# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Background worker thread for async telemetry event processing.

This module provides BackgroundWorker, a daemon thread that consumes events
from a DropOldestQueue and writes them to a storage backend, with graceful
shutdown via atexit handler.

When the storage backend is a PooledWriter, BackgroundWorker accumulates events
into batches and submits them via PooledWriter.submit_batch() (100 events or
500ms elapsed, whichever comes first). Non-PooledWriter backends use the original
single-event write path, unchanged.
"""

import atexit
import logging
import queue
import threading
import time

from .events import TelemetryEvent
from .metrics import _registry
from .pool_writer import PooledWriter
from .queue import DropOldestQueue
from .storage import StorageBackend

logger = logging.getLogger(__name__)

# Sentinel value for graceful shutdown
_SHUTDOWN_SENTINEL = object()


class BackgroundWorker:
    """Background daemon thread that processes telemetry events.

    Continuously consumes events from a DropOldestQueue and writes them
    to a storage backend. Automatically starts on initialization and
    registers atexit handler for graceful shutdown.

    When the storage backend is a PooledWriter, events are accumulated into
    batches (up to batch_size events or batch_timeout seconds, whichever
    comes first) and submitted via PooledWriter.submit_batch(). This releases
    the GIL during batch writes to the subprocess pool.

    For non-PooledWriter backends, the original single-event write path
    is used unchanged (backward compatible).

    Attributes:
        events_processed: Total events successfully written to storage
        errors: Total write errors encountered
    """

    def __init__(
        self,
        event_queue: DropOldestQueue,
        storage_backend: StorageBackend,
        circuit_breaker_threshold: int = 5,
        circuit_breaker_cooldown: float = 30.0,
        batch_size: int = 100,
        batch_timeout: float = 0.5,
    ):
        """Initialize and start background worker.

        Args:
            event_queue: Queue to consume events from
            storage_backend: Storage backend to write events to
            circuit_breaker_threshold: Number of consecutive storage failures
                before the circuit breaker trips and enters cooldown.
                Defaults to 5.
            circuit_breaker_cooldown: Seconds to sleep after the circuit breaker
                trips before retrying storage writes. Defaults to 30.0.
            batch_size: Maximum batch size before submitting to pool.
                Only used when storage_backend is a PooledWriter. Defaults to 100.
            batch_timeout: Maximum seconds to accumulate events before submitting
                a partial batch. Only used with PooledWriter. Defaults to 0.5
                (500ms per CONTEXT.md decision).
        """
        self._queue = event_queue
        self._storage = storage_backend
        self._running = True
        self._events_processed = 0
        self._errors = 0

        # Circuit breaker configuration
        self._cb_threshold = circuit_breaker_threshold
        self._cb_cooldown = circuit_breaker_cooldown
        # Promoted from local variable in _run() to instance variable so
        # _flush_batch() can reset it on successful batch submission.
        self._consecutive_errors = 0

        # Batch accumulation (only active when backend is a PooledWriter)
        self._is_pooled: bool = isinstance(storage_backend, PooledWriter)
        self._batch_size = batch_size
        self._batch_timeout = batch_timeout
        self._batch: list[TelemetryEvent] = []
        self._last_batch_time: float = time.time()
        self._batches_submitted: int = 0

        # Create and start daemon thread
        self._thread = threading.Thread(target=self._run, daemon=True, name="observra-worker")
        self._thread.start()
        logger.info("BackgroundWorker started (pooled=%s)", self._is_pooled)

        # Register atexit handler for graceful shutdown
        atexit.register(self._shutdown)

    def _flush_batch(self) -> None:
        """Submit the current accumulated batch to the PooledWriter.

        Called when batch_size is reached, batch_timeout elapses, or on
        shutdown. Clears the batch and resets the timer regardless of
        success or failure to prevent OOM from unbounded accumulation.

        Only valid when self._is_pooled is True.
        """
        if not self._batch:
            return

        batch_to_send = self._batch.copy()
        self._batch.clear()
        self._last_batch_time = time.time()

        try:
            # submit_batch() is defined on PooledWriter -- safe cast
            self._storage.submit_batch(batch_to_send)  # type: ignore[attr-defined]
            self._events_processed += len(batch_to_send)
            _registry.inc_counter("observra_backend_write_success_total", len(batch_to_send))
            self._batches_submitted += 1
            self._consecutive_errors = 0  # Reset circuit breaker on success

            if self._batches_submitted % 10 == 0:
                logger.debug(
                    "Batch submitted: %d events (total batches: %d)",
                    len(batch_to_send),
                    self._batches_submitted,
                )
        except Exception as e:
            self._errors += len(batch_to_send)
            self._consecutive_errors += 1  # one batch failure = one consecutive error (WR-02)
            _registry.inc_counter("observra_backend_write_failure_total", len(batch_to_send))
            logger.warning(
                "Failed to submit batch of %d events: %s",
                len(batch_to_send),
                e,
                exc_info=True,
            )

    def _run(self) -> None:
        """Main worker loop - processes events until shutdown sentinel received.

        Continuously consumes events from queue and writes to storage.
        Handles errors gracefully without crashing the worker thread.

        When backend is PooledWriter:
          - Events are accumulated into self._batch
          - Batch is submitted when len >= batch_size OR elapsed >= batch_timeout
          - Idle queue timeout also triggers partial batch flush

        When backend is not PooledWriter:
          - Original single-event write path (unchanged)

        Circuit breaker: after _cb_threshold consecutive storage failures, the
        worker sleeps for _cb_cooldown seconds then resets the counter. This
        prevents log floods and CPU spin when the storage backend is down.
        """
        logger.debug("Worker thread running")

        while True:
            try:
                # Get event with timeout to allow periodic checks
                event = self._queue.get(timeout=1.0)

                # Check for shutdown sentinel
                if event is _SHUTDOWN_SENTINEL:
                    logger.debug("Shutdown sentinel received")
                    # Flush any remaining batch before exiting
                    if self._is_pooled and self._batch:
                        self._flush_batch()
                    break

                if self._is_pooled:
                    # Batch accumulation path (PooledWriter)
                    self._batch.append(event)
                    elapsed = time.time() - self._last_batch_time
                    if len(self._batch) >= self._batch_size or elapsed >= self._batch_timeout:
                        self._flush_batch()
                        # Check circuit breaker after batch failure
                        if self._consecutive_errors >= self._cb_threshold:
                            logger.error(
                                "Circuit breaker tripped after %d consecutive failures, cooling down %.1fs",
                                self._consecutive_errors,
                                self._cb_cooldown,
                            )
                            time.sleep(self._cb_cooldown)
                            self._consecutive_errors = 0
                else:
                    # Original single-event write path (non-PooledWriter backends)
                    try:
                        self._storage.write(event)
                        self._events_processed += 1
                        _registry.inc_counter("observra_backend_write_success_total")
                        self._consecutive_errors = 0  # Reset on success

                        if self._events_processed % 100 == 0:
                            logger.debug("Processed %d events", self._events_processed)

                    except Exception as e:
                        self._errors += 1
                        self._consecutive_errors += 1
                        _registry.inc_counter("observra_backend_write_failure_total")
                        logger.warning(
                            "Failed to write event to storage: %s",
                            e,
                            exc_info=True,
                        )

                        # Circuit breaker: trip after N consecutive failures
                        if self._consecutive_errors >= self._cb_threshold:
                            logger.error(
                                "Circuit breaker tripped after %d consecutive failures, cooling down %.1fs",
                                self._consecutive_errors,
                                self._cb_cooldown,
                            )
                            time.sleep(self._cb_cooldown)
                            self._consecutive_errors = 0

            except queue.Empty:
                # Queue idle — flush any pending partial batch or the backend's
                # internal buffer so trailing events land in storage promptly.
                if self._is_pooled and self._batch:
                    # Partial batch timeout: flush what we have
                    self._flush_batch()
                else:
                    # Non-pooled: flush backend's internal buffer
                    try:
                        self._storage.flush()
                    except Exception as e:
                        logger.warning("Idle flush failed: %s", e)
                continue
            except Exception as e:
                logger.error("Unexpected error in worker loop: %s", e, exc_info=True)

        # Flush any remaining batched events (non-pooled path)
        try:
            self._storage.flush()
            logger.debug("Final flush complete")
        except Exception as e:
            logger.error("Error during final flush: %s", e, exc_info=True)

    def shutdown(self) -> None:
        """Public graceful shutdown -- flushes queue and closes storage.

        Delegates to _shutdown(); exposed as a public method so external
        callers (e.g., signal handlers) don't reach into private internals.
        """
        self._shutdown()

    def _shutdown(self) -> None:
        """Graceful shutdown handler called by atexit.

        Sends shutdown sentinel, waits for worker thread to finish,
        flushes and closes storage backend.
        """
        if not self._running:
            logger.debug("Shutdown already called, skipping")
            return

        logger.info("BackgroundWorker shutting down")
        self._running = False

        try:
            # Send shutdown sentinel
            self._queue.put_sentinel(_SHUTDOWN_SENTINEL)

            # Wait for worker thread to finish (max 5 seconds)
            self._thread.join(timeout=5.0)

            if self._thread.is_alive():
                logger.warning("Worker thread did not finish within 5 seconds")

            # Final flush and close
            self._storage.flush()
            self._storage.close()

            logger.info(
                "BackgroundWorker shutdown complete. Processed: %d, Errors: %d, Batches: %d",
                self._events_processed,
                self._errors,
                self._batches_submitted,
            )

        except Exception as e:
            logger.error("Error during shutdown: %s", e, exc_info=True)

    def get_stats(self) -> dict:
        """Get worker statistics.

        Returns:
            Dictionary with events_processed, errors, alive status,
            circuit breaker configuration, and batch stats (if pooled).
        """
        return {
            "events_processed": self._events_processed,
            "errors": self._errors,
            "alive": 1 if self._thread.is_alive() else 0,
            "circuit_breaker_threshold": self._cb_threshold,
            "circuit_breaker_cooldown": self._cb_cooldown,
            "batches_submitted": self._batches_submitted,
            "batch_pending": len(self._batch),
        }
