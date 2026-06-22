# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Benchmark-specific fixtures for tests/benchmarks/."""

from __future__ import annotations

import time

import pytest

from observra.core.events import TelemetryEvent


def _make_bench_event(i: int) -> TelemetryEvent:
    """Create a realistic ~500-byte TelemetryEvent for benchmark use (per D-02)."""
    return TelemetryEvent(
        event_id=f"evt-bench-{i:04d}",
        timestamp=time.time(),
        trace_id="trace-bench-abc123",
        session_id="session-bench-xyz456",
        span_id=f"span-bench-{i:04d}",
        event_type="model_response",
        data={
            "input_tokens": 500,
            "output_tokens": 200,
            "tool_input": "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig",
            "user_email": "bench@example.com",
            "session_id": "sess-abc-123",
            "model": "claude-opus-4-5",
        },
    )


@pytest.fixture
def realistic_batch():
    """10-event batch with realistic ~500-byte payloads for benchmark use (per D-02)."""
    return [_make_bench_event(i) for i in range(10)]
