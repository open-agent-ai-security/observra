<!--
  Copyright 2026 Exabeam, Inc.
  SPDX-License-Identifier: Apache-2.0
-->
# Google ADK Setup

Capture every LLM call, tool use, cost, and error from a Google ADK agent.

## Install

```bash
pip install observra[adk]
```

## Prerequisites

observra observes your agent — it does not provide model credentials. Configure
ADK's model access as you normally would before adding telemetry, e.g. for
Gemini via AI Studio:

```bash
export GOOGLE_API_KEY=...          # or configure Vertex AI per the ADK docs
```

## Usage

ADK captures telemetry through a **plugin** that you register with your
`Runner`. This is two added lines plus one Runner argument — `initialize()`
alone does **not** capture anything until the plugin is attached.

```python
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService

from observra import create_plugin, initialize

# 1. Point telemetry at a backend (JSONL file shown here).
initialize(backend="jsonl", path="telemetry.jsonl")

# 2. Build the plugin connected to that pipeline.
plugin = create_plugin()  # framework="adk" is the default

# 3. Register the plugin with your Runner.
runner = Runner(
    agent=root_agent,  # your existing ADK agent, unchanged
    app_name="my_app",
    session_service=InMemorySessionService(),
    plugins=[plugin],  # <-- the only change to your Runner
)

# Run the agent normally — every lifecycle event is now captured.
```

Events are written to `telemetry.jsonl`, one JSON object per line:

```bash
cat telemetry.jsonl | jq   # install jq if it isn't already on your system
```

## How it works

`create_plugin()` returns a `BasePlugin` that ADK drives through its lifecycle.
The plugin implements the run, agent, model, and tool callbacks — plus the
model/tool error and user-message callbacks — and translates each into a
normalized CIM event. It is **observation-only**: the callbacks never modify
agent behavior or alter responses. Token counts come from the model's
`usage_metadata`, and cost is computed from observra's per-model pricing catalog.

### Running under `adk web`

When you launch with `adk web` instead of constructing your own `Runner`,
expose a module-level plugin and pass it with `--extra_plugins`:

```python
# in your agent module
from observra import create_plugin, initialize

initialize(backend="jsonl", path="telemetry.jsonl")
telemetry_plugin = create_plugin()
```

```bash
adk web . --extra_plugins your_module.telemetry_plugin
```

## Capturing tool arguments and results

By default, tool inputs/outputs are **not** recorded (to avoid logging
sensitive payloads). Opt in on the plugin — not on `initialize()`:

```python
plugin = create_plugin(capture_tool_data=True)
```

## Cost tracking

Each `model_response` carries `cost_usd` (computed from token counts and the
per-model pricing catalog) plus a running `session_cost_usd`. To alert when a
session crosses a budget, set a threshold on the plugin:

```python
plugin = create_plugin(cost_threshold_usd=5.00)
```

This emits a `cost_threshold_exceeded` event once per session when the total
crosses the configured limit.

## Configuration

All configuration is passed as arguments. observra does not read telemetry
settings from environment variables (aside from `ABA_TELEMETRY_KEY` for
encryption-at-rest), so set them explicitly:

```python
initialize(
    backend="jsonl",
    path="telemetry.jsonl",
    queue_size=1000,  # bounded, drop-oldest queue
)
plugin = create_plugin(
    capture_tool_data=False,  # opt in to record tool args/results
    cost_threshold_usd=None,  # alert when session cost crosses this
)
```

For OTel/Dynatrace/Datadog export and production tuning, see
[Production Deployment](../production-deployment.md).

## Captured Events

- `user_message` — user prompt submissions
- `model_request` / `model_response` — LLM calls with token counts and cost
- `turn_duration` — per-turn latency
- `tool_start` / `tool_end` — tool invocations with duration
- `agent_start` / `agent_end` — agent lifecycle with delegation depth
- `depth_exceeded` — sub-agent delegation exceeded observra's safe depth limit
- `model_error` / `tool_error` — failures with error classification
- `cost_threshold_exceeded` — session cost crossed the configured threshold
- `session_start` / `session_end` — session boundaries

All events have `framework="adk"` for SIEM filtering.

## Full example

See [`examples/sample_agent/`](../../examples/sample_agent/) for a complete
`adk web` agent, and
[`examples/add_telemetry_to_agent.py`](../../examples/add_telemetry_to_agent.py)
for the programmatic `Runner` integration.
