"""Shared type definitions for aba_telemetry."""

from typing import TypedDict


class BackendStats(TypedDict):
    """Statistics returned by StorageBackend.get_stats().

    All backends must return at minimum these five fields.
    Fields that cannot be tracked by a backend return 0 (int fields)
    or None (timestamp fields).
    """
    bytes_written: int          # Total bytes written to storage (0 if not tracked)
    event_count: int            # Total events successfully stored
    backend_type: str           # e.g. "jsonl", "otel", "otel_log", "webhook", "multi"
    oldest_event_ts: float | None  # Unix timestamp of earliest stored event, None if empty
    newest_event_ts: float | None  # Unix timestamp of most recent stored event, None if empty
