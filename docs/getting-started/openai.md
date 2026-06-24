<!--
  Copyright 2026 Exabeam, Inc.
  SPDX-License-Identifier: Apache-2.0
-->
# OpenAI Agents SDK Setup

Capture every LLM call, tool use, agent handoff, and cost from an OpenAI Agents SDK agent.

## Install

```bash
pip install observra[openai-agents]
```

## Prerequisites

observra observes your agent — it does not provide model credentials. Configure
your OpenAI API key as you normally would before adding telemetry:

```bash
export OPENAI_API_KEY=...
```

## Usage

The OpenAI adapter is a `TracingProcessor` that you register with the SDK's
tracing system. This is three added lines — your agent code stays unchanged.

```python
from agents import Agent, Runner, add_trace_processor

from observra import create_plugin, initialize

# 1. Point telemetry at a backend (JSONL file shown here).
initialize(backend="jsonl", path="telemetry.jsonl")

# 2. Create the adapter (wired to the pipeline).
adapter = create_plugin("openai")

# 3. Register it with the tracing system.
add_trace_processor(adapter)

# Run your agent normally — every lifecycle event is now captured.
agent = Agent(name="my_agent", instructions="Be helpful", tools=[...])
result = Runner.run_sync(agent, "Hello")
```

Events are written to `telemetry.jsonl`, one JSON object per line:

```bash
cat telemetry.jsonl | jq
```

## How it works

The adapter subclasses `TracingProcessor` from the OpenAI Agents SDK. It
receives span lifecycle callbacks (`on_span_start`, `on_span_end`) for all
span types — generation, function, handoff, agent, and custom spans. Token
data comes from `GenerationSpanData.usage` and is **exact** (not estimated).

## Important: use `add_trace_processor`

```python
add_trace_processor(adapter)       # ✅ CORRECT — adds alongside defaults
set_trace_processors([adapter])    # ❌ WRONG — replaces all processors
```

Using `add_trace_processor` ensures observra runs alongside any existing
trace processors (e.g. the SDK's default console tracer).

## Capturing tool arguments and results

By default, tool inputs/outputs are **not** recorded (to avoid logging
sensitive payloads). Opt in on the adapter:

```python
adapter = create_plugin("openai", capture_tool_data=True)
```

Payloads are truncated at 4KB and redacted for PII.

## Cost tracking

Token counts are exact (from SDK usage data). Cost is computed using
co-located pricing data for OpenAI models. To alert when session cost
exceeds a threshold:

```python
adapter = create_plugin("openai", cost_threshold_usd=5.00)
```

This emits a `cost_threshold_exceeded` event when a generation span's
cost crosses the configured limit.

## Configuration

```python
initialize(
    backend="jsonl",
    path="telemetry.jsonl",
    queue_size=1000,                  # bounded, drop-oldest queue
)
adapter = create_plugin(
    "openai",
    capture_tool_data=False,          # opt in to record tool args/results
    cost_threshold_usd=None,          # cost alerting threshold
    payload_max_bytes=4096,           # max serialized tool data size
)
add_trace_processor(adapter)
```

For OTel/Dynatrace/Datadog export and production tuning, see
[Production Deployment](../production-deployment.md).

## Captured Events

- `session_start` / `session_end` — agent span boundaries
- `model_response` — LLM calls with exact token counts, reasoning tokens, and cost
- `tool_end` — tool invocations with duration
- `agent_handoff` — multi-agent transitions with source/target agent names
- `cost_threshold_exceeded` — cost alerting (if configured)

All events have `framework="openai"` for SIEM filtering.

## Full example

See [`examples/openai_adapter.py`](../../examples/openai_adapter.py) for
a complete before/after walkthrough with a calculator tool agent.
