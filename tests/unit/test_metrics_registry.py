"""Unit tests for aba_telemetry.core.metrics -- MetricsRegistry and RingBuffer."""

import threading

from aba_telemetry.core.metrics import MetricsRegistry, RingBuffer, _registry


class TestRingBuffer:
    """RingBuffer: fixed-size circular buffer for latency samples (D-04)."""

    def test_empty_percentile_returns_none(self):
        rb = RingBuffer(maxlen=100)
        assert rb.percentile(50) is None
        assert rb.percentile(99) is None

    def test_single_sample(self):
        rb = RingBuffer(maxlen=100)
        rb.push(0.005)
        assert rb.percentile(50) == 0.005
        assert rb.percentile(99) == 0.005

    def test_percentile_accuracy(self):
        rb = RingBuffer(maxlen=1000)
        # Push 1000 evenly-spaced values 0.001 .. 1.000
        for i in range(1, 1001):
            rb.push(i / 1000.0)
        p50 = rb.percentile(50)
        p99 = rb.percentile(99)
        p999 = rb.percentile(99.9)
        # p50 should be ~0.500, p99 ~0.990, p999 ~0.999
        assert 0.490 <= p50 <= 0.510
        assert 0.985 <= p99 <= 0.995
        assert 0.995 <= p999 <= 1.000

    def test_maxlen_eviction(self):
        rb = RingBuffer(maxlen=10)
        for i in range(20):
            rb.push(float(i))
        assert rb.count() == 10
        # Only values 10-19 should remain
        assert rb.percentile(0) == 10.0

    def test_count_and_sum(self):
        rb = RingBuffer(maxlen=100)
        rb.push(1.0)
        rb.push(2.0)
        rb.push(3.0)
        assert rb.count() == 3
        assert rb.sum() == 6.0


class TestMetricsRegistry:
    """MetricsRegistry: thread-safe singleton for counters, gauges, histograms."""

    def setup_method(self):
        """Reset the module-level registry before each test."""
        _registry.reset()

    def test_inc_counter_default_delta(self):
        reg = MetricsRegistry()
        reg.inc_counter("aba_telemetry_test_total")
        reg.inc_counter("aba_telemetry_test_total")
        assert reg.get_counter("aba_telemetry_test_total") == 2

    def test_inc_counter_custom_delta(self):
        reg = MetricsRegistry()
        reg.inc_counter("aba_telemetry_test_total", delta=5)
        assert reg.get_counter("aba_telemetry_test_total") == 5

    def test_get_counter_missing_returns_zero(self):
        reg = MetricsRegistry()
        assert reg.get_counter("aba_telemetry_nonexistent_total") == 0

    def test_set_gauge(self):
        reg = MetricsRegistry()
        reg.set_gauge("aba_telemetry_queue_depth", 42.0)
        assert reg.get_gauge("aba_telemetry_queue_depth") == 42.0

    def test_get_gauge_missing_returns_zero(self):
        reg = MetricsRegistry()
        assert reg.get_gauge("aba_telemetry_nonexistent") == 0.0

    def test_get_histogram_creates_ring_buffer(self):
        reg = MetricsRegistry()
        h = reg.get_histogram("aba_telemetry_write_latency_seconds")
        assert isinstance(h, RingBuffer)
        # Same instance on second call
        h2 = reg.get_histogram("aba_telemetry_write_latency_seconds")
        assert h is h2

    def test_reset_clears_all(self):
        reg = MetricsRegistry()
        reg.inc_counter("aba_telemetry_x_total")
        reg.set_gauge("aba_telemetry_y", 1.0)
        reg.get_histogram("aba_telemetry_z_seconds").push(0.1)
        reg.reset()
        assert reg.get_counter("aba_telemetry_x_total") == 0
        assert reg.get_gauge("aba_telemetry_y") == 0.0

    def test_labels_set_and_get(self):
        reg = MetricsRegistry()
        reg.set_label("framework", "adk")
        reg.set_label("sink", "jsonl")
        labels = reg.get_labels()
        assert labels == {"framework": "adk", "sink": "jsonl"}

    def test_get_labels_returns_copy(self):
        reg = MetricsRegistry()
        reg.set_label("framework", "claude")
        labels = reg.get_labels()
        labels["framework"] = "mutated"  # Mutate the copy
        assert reg.get_labels()["framework"] == "claude"  # Original unchanged

    def test_reset_clears_labels(self):
        reg = MetricsRegistry()
        reg.set_label("framework", "adk")
        reg.reset()
        assert reg.get_labels() == {}

    def test_concurrent_inc(self):
        """Verify thread-safety: 10 threads each increment 1000 times."""
        reg = MetricsRegistry()
        barrier = threading.Barrier(10)

        def worker():
            barrier.wait()
            for _ in range(1000):
                reg.inc_counter("aba_telemetry_concurrent_total")

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert reg.get_counter("aba_telemetry_concurrent_total") == 10000
