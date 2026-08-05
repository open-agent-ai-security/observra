<!--
  Copyright 2026 Exabeam, Inc.
  SPDX-License-Identifier: Apache-2.0
-->
# SQLite Backend Setup

Store telemetry in a local, queryable database — no infrastructure required.

## Install

```bash
pip install observra
```

No extras needed — the SQLite backend uses Python's stdlib `sqlite3`.

## Usage

```python
import observra

observra.initialize(backend="sqlite", path="telemetry.db")
plugin = observra.create_plugin("adk")  # or any adapter
```

That's it. Events are written to a local SQLite database that you can
query with any SQLite tool.

## Why SQLite?

- **Queryable** — SQL access to your telemetry without parsing JSONL
- **Persistent** — survives process restarts, unlike in-memory buffers
- **Zero infrastructure** — no collector, no cloud account, no docker
- **Development-friendly** — inspect agent behavior locally
- **TUI-compatible** — powers the `observra watch` terminal dashboard

## Querying your telemetry

Use any SQLite client to explore:

```bash
# Command line
sqlite3 telemetry.db "SELECT event_type, model_name, json_extract(data, '$.cost_usd') as cost FROM events ORDER BY timestamp DESC LIMIT 10"

# Or use Python
python -c "
import sqlite3, json
conn = sqlite3.connect('telemetry.db')
for row in conn.execute('SELECT * FROM events ORDER BY timestamp DESC LIMIT 5'):
    print(json.dumps(dict(zip([d[0] for d in conn.description], row)), indent=2))
"
```

## Schema

The database uses a single `events` table:

| Column | Type | Description |
|--------|------|-------------|
| `event_id` | TEXT (PK) | Unique event identifier (ULID) |
| `timestamp` | REAL | Unix timestamp |
| `session_id` | TEXT | Session grouping key |
| `trace_id` | TEXT | Distributed trace ID |
| `span_id` | TEXT | Span identifier |
| `event_type` | TEXT | Event type (model_response, tool_start, etc.) |
| `agent_name` | TEXT | Agent attribution |
| `tool_name` | TEXT | Tool name (for tool events) |
| `model_name` | TEXT | Model used |
| `framework` | TEXT | Source framework |
| `host` | TEXT | Host machine |
| `data` | TEXT | JSON blob with event-specific fields |
| `library_version` | TEXT | Observra version |

Indexes are created on `session_id`, `event_type`, and `timestamp`.

## Configuration

```python
observra.initialize(
    backend="sqlite",
    path="telemetry.db",  # database file path
    table_name="events",  # custom table name (default: "events")
    max_rows=100_000,  # auto-prune oldest events beyond this cap
)
```

### Row pruning

When `max_rows` is set, the oldest events are automatically deleted once
the cap is exceeded. This keeps disk usage bounded during long-running
development sessions:

```python
# Keep last 50,000 events — older ones are pruned on flush
observra.initialize(backend="sqlite", path="telemetry.db", max_rows=50_000)
```

## WAL mode

The database uses WAL (Write-Ahead Logging) mode, which allows concurrent
reads while the background worker writes. This means you can query the
database while your agent is running without blocking telemetry collection.

## File permissions

New database files are created with `0o600` permissions (owner read/write
only). The telemetry pipeline applies redaction before storage, but the
file still contains operational data — secure it appropriately.

## Programmatic queries

The backend also supports queries through the Python API:

```python
from observra.backends.sqlite import SQLiteBackend

backend = SQLiteBackend(path="telemetry.db")

# All model_response events from the last hour
import time

one_hour_ago = time.time() - 3600

for event in backend.query(event_type="model_response", from_ts=one_hour_ago):
    print(f"{event.model_name}: ${event.data.get('cost_usd', 0):.4f}")
```

## Pairing with the TUI dashboard

The SQLite backend powers the terminal dashboard. Run your agent with
SQLite, then watch it live:

```bash
# Terminal 1: run your agent
python my_agent.py

# Terminal 2: watch telemetry in real time
python -m observra.tui --db telemetry.db
```

See [TUI Dashboard](./tui.md) for the full dashboard guide.

## When to use SQLite vs JSONL

| Use case | Backend |
|----------|---------|
| Development / debugging | SQLite |
| Need to query by session, event type, time range | SQLite |
| Want the TUI dashboard | SQLite |
| Simple append-only log | JSONL |
| Streaming to external tools (jq, grep) | JSONL |
| Encrypted at rest | JSONL (with `encryption_key`) |
| Production → OTel collector | `otel` or `otel_log` |

## Full example

See [`examples/sqlite_backend.py`](../../examples/sqlite_backend.py) for
a complete walkthrough with queries.
