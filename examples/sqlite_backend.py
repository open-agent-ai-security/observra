# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0

"""How to use the SQLite backend for queryable local telemetry.

Install:
    pip install observra

Usage:
    python examples/sqlite_backend.py

This stores events in a local SQLite database that you can query
with SQL, the Python API, or the TUI dashboard.
"""


import observra
from observra.core.context import initialize_session, initialize_trace
from observra.core.events import create_event

# ── Step 1: Initialize with SQLite backend ────────────────────────

observra.initialize(
    backend="sqlite",
    path="example_telemetry.db",
    max_rows=10_000,  # auto-prune oldest events beyond this cap
)

# ── Step 2: Generate some sample events ───────────────────────────

initialize_trace()
initialize_session()

events_data = [
    {"event_type": "session_start", "agent_name": "demo-agent"},
    {
        "event_type": "model_response",
        "agent_name": "demo-agent",
        "model_name": "gpt-4o",
        "input_tokens": 1200,
        "output_tokens": 310,
        "cost_usd": 0.015,
        "duration_ms": 2100,
    },
    {"event_type": "tool_start", "agent_name": "demo-agent", "tool_name": "web_search"},
    {"event_type": "tool_end", "agent_name": "demo-agent", "tool_name": "web_search", "duration_ms": 450},
    {
        "event_type": "model_response",
        "agent_name": "demo-agent",
        "model_name": "gpt-4o",
        "input_tokens": 3200,
        "output_tokens": 180,
        "cost_usd": 0.021,
        "duration_ms": 2800,
    },
    {"event_type": "session_end", "agent_name": "demo-agent", "session_cost_usd": 0.036},
]

for data in events_data:
    event = create_event(framework="custom", **data)
    observra._worker._storage.write(event)

observra._worker._storage.flush()
print(f"Wrote {len(events_data)} events to example_telemetry.db")

# ── Step 3: Query the database ────────────────────────────────────

from observra.backends.sqlite import SQLiteBackend  # noqa: E402

backend = SQLiteBackend(path="example_telemetry.db")

print("\n--- All model_response events ---")
for event in backend.query(event_type="model_response"):
    cost = event.data.get("cost_usd", 0)
    tokens = event.data.get("input_tokens", 0) + event.data.get("output_tokens", 0)
    print(f"  {event.model_name}: {tokens} tokens, ${cost:.4f}")

print("\n--- Stats ---")
stats = backend.get_stats()
print(f"  Total events: {stats['event_count']}")
print(f"  Backend: {stats['backend_type']}")

backend.close()

# ── Step 4: Use with the TUI dashboard ────────────────────────────

print("\nTo watch live:")
print("  python -m observra.tui --db example_telemetry.db")
