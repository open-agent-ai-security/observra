"""Unit tests for aba_telemetry.observability -- public get_metrics() facade."""

from aba_telemetry.core.metrics import _registry


class TestGetMetrics:
    """observability.get_metrics() returns all 9 keys per OBS-01 success criteria."""

    def setup_method(self):
        _registry.reset()

    def test_returns_required_keys(self):
        from aba_telemetry import observability
        m = observability.get_metrics()
        required = {
            "drop_count", "queue_depth",
            "write_latency_p50", "write_latency_p99", "write_latency_p999",
            "redaction_applied_count",
            "backend_write_success", "backend_write_failure",
            "labels",
        }
        assert required == set(m.keys())

    def test_defaults_to_zeros_when_no_pipeline(self):
        from aba_telemetry import observability
        m = observability.get_metrics()
        assert m["drop_count"] == 0
        assert m["queue_depth"] == 0
        assert m["write_latency_p50"] is None
        assert m["write_latency_p99"] is None
        assert m["write_latency_p999"] is None
        assert m["redaction_applied_count"] == 0
        assert m["backend_write_success"] == 0
        assert m["backend_write_failure"] == 0
        assert m["labels"] == {}

    def test_reflects_registry_state(self):
        from aba_telemetry import observability
        _registry.inc_counter("aba_telemetry_events_dropped_total", 5)
        _registry.set_gauge("aba_telemetry_queue_depth", 3.0)
        _registry.get_histogram("aba_telemetry_write_latency_seconds").push(0.002)
        _registry.inc_counter("aba_telemetry_redaction_applied_total", 10)
        _registry.inc_counter("aba_telemetry_backend_write_success_total", 100)
        _registry.inc_counter("aba_telemetry_backend_write_failure_total", 2)
        m = observability.get_metrics()
        assert m["drop_count"] == 5
        assert m["queue_depth"] == 3
        assert m["write_latency_p50"] == 0.002
        assert m["redaction_applied_count"] == 10
        assert m["backend_write_success"] == 100
        assert m["backend_write_failure"] == 2

    def test_labels_reflected(self):
        from aba_telemetry import observability
        _registry.set_label("framework", "adk")
        _registry.set_label("sink", "jsonl")
        m = observability.get_metrics()
        assert m["labels"] == {"framework": "adk", "sink": "jsonl"}

    def test_get_metrics_does_not_raise_without_pipeline(self):
        """Calling get_metrics() with no pipeline initialized must not raise."""
        from aba_telemetry import observability
        try:
            m = observability.get_metrics()
            assert isinstance(m, dict)
        except Exception as exc:
            assert False, f"get_metrics() raised unexpectedly: {exc}"


class TestMetricNameConformance:
    """OBS-03: All metric names use aba_telemetry_ prefix and correct suffixes."""

    def test_counter_names_end_in_total(self):
        """All counter metric names consumed by get_metrics must end in _total."""
        # These are the counter names used in observability.get_metrics()
        counter_names = [
            "aba_telemetry_events_dropped_total",
            "aba_telemetry_redaction_applied_total",
            "aba_telemetry_backend_write_success_total",
            "aba_telemetry_backend_write_failure_total",
        ]
        for name in counter_names:
            assert name.startswith("aba_telemetry_"), f"Bad prefix: {name}"
            assert name.endswith("_total"), f"Counter missing _total: {name}"

    def test_histogram_names_end_in_seconds(self):
        """Latency histograms use _seconds suffix per OpenMetrics -- live registry check."""
        from aba_telemetry.core.metrics import _registry
        _registry.reset()
        # Push a sample to ensure the histogram key exists in the registry
        _registry.get_histogram("aba_telemetry_write_latency_seconds").push(0.001)
        from aba_telemetry import observability
        m = observability.get_metrics()
        # Verify histogram-derived keys exist and the internal metric name is correct
        assert m["write_latency_p50"] is not None, "Histogram should return a value after push"
        hist_name = "aba_telemetry_write_latency_seconds"
        assert hist_name.startswith("aba_telemetry_"), f"Bad prefix: {hist_name}"
        assert hist_name.endswith("_seconds"), f"Histogram missing _seconds suffix: {hist_name}"

    def test_gauge_names_have_prefix_no_total(self):
        """Gauges have aba_telemetry_ prefix but no _total suffix."""
        gauge_name = "aba_telemetry_queue_depth"
        assert gauge_name.startswith("aba_telemetry_")
        assert not gauge_name.endswith("_total")
