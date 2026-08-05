<!--
  Copyright 2026 Exabeam, Inc.
  SPDX-License-Identifier: Apache-2.0
-->
# TUI Dashboard Setup

Watch your agent's telemetry in real time from the terminal.

## Install

```bash
pip install observra[tui]
```

## Prerequisites

The TUI reads from a SQLite database. Your agent must use the SQLite backend:

```python
import observra

observra.initialize(backend="sqlite", path="telemetry.db")
```

See [SQLite Backend](./sqlite.md) for full configuration options.

## Launch

```bash
python -m observra.tui --db telemetry.db
```

The dashboard opens in your terminal and live-updates as new events arrive.

## What you see

```
┌─ Observra Watch ────────────────────────────────────────────────────┐
│  Session: 01KXKGH11A...  │  Agent: my-research-agent               │
│  Events: 8  │  Cost: $0.0342  │  Tokens: 4,600 in / 310 out        │
├─────────────────────────────────────────────────────────────────────┤
│  Time      Type             Name/Model          Detail              │
│  09:15:01  session_start    my-research-agent                       │
│  09:15:02  model_request    gemini-2.5-flash    1,200 tokens        │
│  09:15:04  model_response   gemini-2.5-flash    $0.012  2.1s        │
│  09:15:04  tool_start       read_file                               │
│  09:15:05  tool_end         read_file           340ms               │
│  09:15:08  model_response   gemini-2.5-flash    $0.022  2.8s        │
│  09:15:08  session_end      —                   $0.034 total        │
├─────────────────────────────────────────────────────────────────────┤
│  ▌ watching... (polling every 0.5s)                                 │
└─────────────────────────────────────────────────────────────────────┘
```

### Header bar

Live counters at the top:
- **Session** — current session ID
- **Agent** — agent name (from first event)
- **Events** — total event count
- **Cost** — accumulated session cost
- **Tokens** — input/output token totals
- **Errors** — error event count

### Event table

Scrolling live tail of events with:
- **Time** — when the event occurred (UTC)
- **Type** — event type (color-coded)
- **Name/Model** — model name, tool name, or agent name
- **Detail** — context-dependent info (cost, duration, tokens)

### Color coding

| Color | Event types |
|-------|-------------|
| White/bold | `session_start`, `session_end` |
| Cyan | `model_request` |
| Green | `model_response` |
| Blue | `tool_start`, `tool_end` |
| Magenta | `user_message` |
| Red | `model_error`, `tool_error` |
| Yellow/bold | `cost_threshold_exceeded` |

## Options

```bash
python -m observra.tui --help
```

| Flag | Default | Description |
|------|---------|-------------|
| `--db` | `telemetry.db` | Path to SQLite database |
| `--poll-interval` | `0.5` | Polling interval in seconds |

## Keybindings

| Key | Action |
|-----|--------|
| `q` | Quit |
| `r` | Force refresh |

## Typical workflow

```bash
# Terminal 1: run your agent with SQLite backend
python my_agent.py

# Terminal 2: watch live
python -m observra.tui --db telemetry.db
```

The TUI connects as soon as the database file appears and starts showing
events in real time. If the database doesn't exist yet, it waits gracefully.

## Use with any adapter

The TUI works with any framework adapter — just ensure the backend is SQLite:

```python
import observra

# ADK agent
observra.initialize(backend="sqlite", path="telemetry.db")
plugin = observra.create_plugin("adk")

# Claude agent
observra.initialize(backend="sqlite", path="telemetry.db")
adapter = observra.create_plugin("claude")

# LiteLLM
observra.initialize(backend="sqlite", path="telemetry.db")
plugin = observra.create_plugin("litellm")

# Custom emit()
observra.initialize(backend="sqlite", path="telemetry.db")
observra.emit("model_response", model_name="gpt-4o", ...)
```

## Troubleshooting

**"Waiting for database..."** — the TUI can't find the DB file. Check the
`--db` path matches what your agent passes to `initialize(backend="sqlite", path=...)`.

**Events not appearing** — ensure your agent calls `flush()` or let the
background worker process events (it flushes periodically). Events appear
within one poll interval of being written.

**"ERROR: Textual is required"** — install with `pip install observra[tui]`.
