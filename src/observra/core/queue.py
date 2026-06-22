# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Thread-safe queue with drop-oldest semantics for non-blocking telemetry.

This module provides DropOldestQueue, a wrapper around queue.Queue that
implements drop-oldest eviction when full, ensuring telemetry never blocks
agent execution.
"""

import logging
import queue
import threading
from typing import Any

from .metrics import _registry

logger = logging.getLogger(__name__)


class DropOldestQueue:
    """Thread-safe queue that drops oldest items when full.

    When the queue reaches maxsize and a new item is added, the oldest
    item is evicted to make room. put_nowait() never blocks, making this
    safe for use in performance-critical paths.

    Attributes:
        maxsize: Maximum number of items in queue

    Use get_stats() to access enqueued/dropped counters. The internal
    counters (_enqueued, _dropped) are private; do not access them directly.
    """

    def __init__(self, maxsize: int = 1000):
        """Initialize drop-oldest queue.

        Args:
            maxsize: Maximum queue size (default 1000)
        """
        self._queue: queue.Queue = queue.Queue(maxsize=maxsize)
        self._maxsize = maxsize
        self._enqueued = 0
        self._dropped = 0
        self._lock = threading.Lock()  # WR-03: protect check-evict-put sequence
        logger.debug(f"DropOldestQueue initialized with maxsize={maxsize}")

    def put_nowait(self, item: Any) -> bool:
        """Add item to queue without blocking, dropping oldest if full.

        If queue is full, removes the oldest item before adding the new one.
        This method NEVER blocks the calling thread.

        Args:
            item: Item to add to queue

        Returns:
            True if item was successfully added, False on failure
        """
        with self._lock:  # WR-03: serialize check-evict-put to keep counters consistent
            try:
                # If queue is full, try to evict oldest item
                if self._queue.full():
                    try:
                        self._queue.get_nowait()
                        self._dropped += 1
                        _registry.inc_counter("observra_events_dropped_total")
                        _registry.set_gauge("observra_queue_depth", float(self._queue.qsize()))
                        logger.debug(f"Dropped oldest item (total dropped: {self._dropped})")
                    except queue.Empty:
                        # Race condition: queue became empty between full() check and get_nowait()
                        pass

                # Try to put item (should succeed since we just made room or queue wasn't full)
                self._queue.put_nowait(item)
                self._enqueued += 1
                _registry.set_gauge("observra_queue_depth", float(self._queue.qsize()))
                logger.debug(f"Enqueued item (total enqueued: {self._enqueued})")
                return True

            except queue.Full:
                # Race condition: queue became full again between eviction and put
                logger.warning("Failed to enqueue item due to race condition")
                return False

    def get(self, timeout: float | None = None) -> Any:
        """Get item from queue, optionally with timeout.

        This is intended for use by the background worker thread only.

        Args:
            timeout: Optional timeout in seconds (None = block indefinitely)

        Returns:
            Item from queue

        Raises:
            queue.Empty: If timeout expires without getting an item
        """
        return self._queue.get(timeout=timeout)

    def put_sentinel(self, sentinel: Any) -> None:
        """Force-put sentinel value for shutdown.

        Blocks briefly (up to 5 seconds) to ensure sentinel is enqueued.
        Only used during graceful shutdown.

        Args:
            sentinel: Sentinel value to enqueue
        """
        self._queue.put(sentinel, block=True, timeout=5.0)
        logger.debug("Shutdown sentinel enqueued")

    def qsize(self) -> int:
        """Return approximate queue size.

        Returns:
            Number of items currently in queue
        """
        return self._queue.qsize()

    def get_stats(self) -> dict[str, int]:
        """Get queue statistics.

        Returns:
            Dictionary with enqueued, dropped, and current_size counts
        """
        return {
            "enqueued": self._enqueued,
            "dropped": self._dropped,
            "current_size": self.qsize(),
        }


class QueueProxy:
    """Stable proxy that delegates to the current real DropOldestQueue.

    Adapters and logging handlers hold a reference to this proxy instead of
    the raw queue. When ``initialize()`` replaces the pipeline, it calls
    ``set_target()`` so existing adapters automatically enqueue to the new
    queue without needing to be recreated.

    Only consumer-facing methods (``put_nowait``, ``get_stats``, ``qsize``)
    are exposed. ``BackgroundWorker`` receives the real queue directly because
    it needs ``get()`` and ``put_sentinel()``.
    """

    def __init__(self) -> None:
        self._target: DropOldestQueue | None = None

    def set_target(self, target: DropOldestQueue) -> None:
        """Point the proxy at a new real queue."""
        self._target = target

    def put_nowait(self, item: Any) -> bool:
        """Delegate to the current target queue.

        Returns False (and logs a warning) if no target has been set.
        """
        if self._target is None:
            logger.warning("QueueProxy has no target queue; event dropped")
            return False
        return self._target.put_nowait(item)

    def get_stats(self) -> dict[str, int]:
        """Delegate stats to the current target queue."""
        if self._target is None:
            return {"enqueued": 0, "dropped": 0, "current_size": 0}
        return self._target.get_stats()

    def qsize(self) -> int:
        """Delegate qsize to the current target queue."""
        if self._target is None:
            return 0
        return self._target.qsize()
