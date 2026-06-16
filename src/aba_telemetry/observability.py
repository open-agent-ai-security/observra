"""Self-observability API for aba-telemetry.

Stable v1.0 API surface -- SemVer-covered per OBS-03.
Metric names and dict keys are part of the public contract.

Usage:
    from aba_telemetry import observability
    metrics = observability.get_metrics()
"""

from aba_telemetry.core.metrics import _registry


def get_metrics() -> dict:
    """Return current self-metrics for the active pipeline.

    Returns a dict with these guaranteed keys (OBS-01 success criteria):
      - drop_count: int -- events dropped due to backpressure
      - queue_depth: int -- current queue size
      - write_latency_p50: float | None -- median write latency in seconds
      - write_latency_p99: float | None -- 99th percentile write latency
      - write_latency_p999: float | None -- 99.9th percentile write latency
      - redaction_applied_count: int -- total redaction operations applied
      - backend_write_success: int -- successful backend writes
      - backend_write_failure: int -- failed backend writes
      - labels: dict -- OBS-03 standard labels (framework, sink, event_type) when set

    All values default to 0 (or None for latency, {} for labels) when no pipeline is active.
    This is safe to call at any time -- returns zeros rather than raising.
    """
    hist = _registry.get_histogram("aba_telemetry_write_latency_seconds")
    return {
        "drop_count": _registry.get_counter("aba_telemetry_events_dropped_total"),
        "queue_depth": int(_registry.get_gauge("aba_telemetry_queue_depth")),
        "write_latency_p50": hist.percentile(50),
        "write_latency_p99": hist.percentile(99),
        "write_latency_p999": hist.percentile(99.9),
        "redaction_applied_count": _registry.get_counter("aba_telemetry_redaction_applied_total"),
        "backend_write_success": _registry.get_counter("aba_telemetry_backend_write_success_total"),
        "backend_write_failure": _registry.get_counter("aba_telemetry_backend_write_failure_total"),
        "labels": _registry.get_labels(),
    }
