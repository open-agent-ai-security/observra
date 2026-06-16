"""Thread-safe MetricsRegistry singleton and RingBuffer for self-observability.

This module provides the foundational metric collection infrastructure per D-01.
All components push counters/gauges/histograms into the module-level _registry
singleton. The observability facade (observability.py) reads from this registry.

Design constraints:
- stdlib-only imports (enforced by test_core_isolation.py zero-dep constraint)
- Thread-safe: all mutations and reads are guarded by threading.Lock
- Memory-bounded: RingBuffer uses a deque with fixed maxlen (default 1000 samples)
"""

import math
import threading
from collections import deque
from typing import Any


class RingBuffer:
    """Fixed-size circular buffer for latency samples (per D-04).

    Stores up to ``maxlen`` floating-point samples. When full, the oldest
    sample is automatically evicted by the underlying deque. Percentiles are
    computed on demand by sorting a snapshot — there is no pre-sorted index.

    Attributes:
        _buf: deque of float samples (auto-evicts oldest when maxlen reached)
        _lock: threading.Lock protecting all mutations and reads
    """

    def __init__(self, maxlen: int = 1000) -> None:
        """Create a RingBuffer with a fixed capacity.

        Args:
            maxlen: Maximum number of samples to retain (default 1000, ~8 KB).
        """
        self._buf: deque[float] = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def push(self, value: float) -> None:
        """Append a sample. If at capacity, the oldest sample is evicted.

        Args:
            value: Latency sample in seconds (or any float metric).
        """
        with self._lock:
            self._buf.append(value)

    def percentile(self, p: float) -> float | None:
        """Compute the p-th percentile from current samples.

        Args:
            p: Percentile in the range [0, 100] (e.g. 50, 99, 99.9).

        Returns:
            The computed percentile value, or None if the buffer is empty.
        """
        with self._lock:
            if not self._buf:
                return None
            sorted_vals = sorted(self._buf)
            n = len(sorted_vals)
            # Nearest-rank formula: maps p=0 → index 0, p=100 → index n-1.
            # ceil(n * p / 100) - 1 avoids the systematic high bias of the
            # floor formula (WR-01).
            idx = max(0, math.ceil(n * p / 100) - 1)
            idx = min(idx, n - 1)
            return sorted_vals[idx]

    def count(self) -> int:
        """Return the number of samples currently in the buffer.

        Returns:
            Current sample count (0 <= count <= maxlen).
        """
        with self._lock:
            return len(self._buf)

    def sum(self) -> float:
        """Return the sum of all samples currently in the buffer.

        Returns:
            Sum of current samples, or 0.0 if empty.
        """
        with self._lock:
            return sum(self._buf)


class MetricsRegistry:
    """Thread-safe registry for counters, gauges, and latency histograms (per D-01).

    All mutations (inc_counter, set_gauge, get_histogram, set_label) and reads
    (get_counter, get_gauge, get_labels) are guarded by a single threading.Lock.
    Histograms are created lazily on first access via get_histogram().

    Metric naming follows OpenMetrics conventions per OBS-03:
    - Counters end in ``_total``   (e.g. observra_events_dropped_total)
    - Gauges have no special suffix (e.g. observra_queue_depth)
    - Latency histograms end in ``_seconds`` (e.g. observra_write_latency_seconds)
    All names carry the ``observra_`` prefix.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, int] = {}
        self._gauges: dict[str, float] = {}
        self._histograms: dict[str, RingBuffer] = {}
        self._labels: dict[str, str] = {}

    # ── Counters ──────────────────────────────────────────────────────────────

    def inc_counter(self, name: str, delta: int = 1) -> None:
        """Increment a counter by delta (default 1).

        Args:
            name: Counter metric name (should end in ``_total`` per OBS-03).
            delta: Amount to increment (default 1).
        """
        with self._lock:
            self._counters[name] = self._counters.get(name, 0) + delta

    def get_counter(self, name: str) -> int:
        """Return the current counter value, defaulting to 0 if not set.

        Args:
            name: Counter metric name.

        Returns:
            Current integer counter value.
        """
        with self._lock:
            return self._counters.get(name, 0)

    # ── Gauges ────────────────────────────────────────────────────────────────

    def set_gauge(self, name: str, value: float) -> None:
        """Set a gauge to an absolute value.

        Args:
            name: Gauge metric name.
            value: New gauge value.
        """
        with self._lock:
            self._gauges[name] = value

    def get_gauge(self, name: str) -> float:
        """Return the current gauge value, defaulting to 0.0 if not set.

        Args:
            name: Gauge metric name.

        Returns:
            Current float gauge value.
        """
        with self._lock:
            return self._gauges.get(name, 0.0)

    # ── Histograms ────────────────────────────────────────────────────────────

    def get_histogram(self, name: str) -> RingBuffer:
        """Return the RingBuffer for this histogram, creating it if absent.

        The same RingBuffer instance is returned on subsequent calls with the
        same name — callers can hold a reference and call push() directly.

        Args:
            name: Histogram metric name (should end in ``_seconds`` per OBS-03).

        Returns:
            RingBuffer associated with this histogram name.
        """
        with self._lock:
            if name not in self._histograms:
                self._histograms[name] = RingBuffer()
            return self._histograms[name]

    # ── Labels ────────────────────────────────────────────────────────────────

    def set_label(self, name: str, value: str) -> None:
        """Set a metadata label (OBS-03 standard labels: framework, sink, event_type).

        Args:
            name: Label name (e.g. 'framework', 'sink', 'event_type').
            value: Label value string.
        """
        with self._lock:
            self._labels[name] = value

    def get_labels(self) -> dict[str, str]:
        """Return a copy of all labels currently set.

        Returns:
            Dict of label name -> value strings. Returns {} when no labels set.
        """
        with self._lock:
            return dict(self._labels)

    # ── Reset ─────────────────────────────────────────────────────────────────

    def reset(self) -> None:
        """Clear all metrics and labels. Intended for testing only.

        Resets counters, gauges, histograms, and labels to empty state.
        """
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._histograms.clear()
            self._labels.clear()


# Module-level singleton — single source of truth for all Python-side self-metrics (D-01, D-03).
# Components push into this registry; observability.get_metrics() reads from it.
_registry = MetricsRegistry()
