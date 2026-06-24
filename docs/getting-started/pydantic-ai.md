<!--
  Copyright 2026 Exabeam, Inc.
  SPDX-License-Identifier: Apache-2.0
-->
# Pydantic AI Setup

Capture every model call and tool use from a Pydantic AI agent via OpenTelemetry spans.

## Install

```bash
pip install observra[pydantic-ai]
```

## Prerequisites

observra observes your agent — it does not provide model credentials. Configure
your model provider credentials as you normally would before adding telemetry:

```bash
export OPENAI_API_KEY=...        # or ANTHROPIC_API_KEY, GEMINI_API_KEY, etc.
```

## Usage

The Pydantic AI adapter is an OTel `SpanProcessor` that reads spans emitted by
`Agent.instrument_all()`. Setup requires wiring the adapter into a
`TracerProvider` before any agent runs.

```python
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace import set_tracer_provider
from pydantic_ai import Agent

from observra import create_plugin, initialize

# 1. Point telemetry at a backend (JSONL file shown here).
initialize(backend="jsonl", path="telemetry.jsonl")

# 2. Create the adapter (wired to the pipeline).
adapter = create_plugin("pydantic-ai")

# 3. Wire into OpenTelemetry (order matters!).
provider = TracerProvider()
provider.add_span_processor(adapter)   # must happen BEFORE set_tracer_provider
set_tracer_provider(provider)

# 4. Enable Pydantic AI span generation.
Agent.instrument_all()                 # must call BEFORE any agent runs

# 5. Run your agent normally — telemetry is captured automatically.
agent = Agent("openai:gpt-4o")
result = agent.run_sync("Hello")
```

Events are written to `telemetry.jsonl`, one JSON object per line:

```bash
cat telemetry.jsonl | jq   # install jq if it isn't already on your system
```

## Setup order matters

The setup steps must happen in this exact order:

1. `TracerProvider()` — create provider
2. `provider.add_span_processor(adapter)` — register adapter
3. `set_tracer_provider(provider)` — set as global
4. `Agent.instrument_all()` — enable span generation
5. `Agent(...)` — create and run agents

Wrong order = missing events. The adapter must be registered before Pydantic AI
starts emitting spans.

## How it works

Pydantic AI's `instrument_all()` generates OTel spans for every model call and
tool invocation. The adapter is a `SpanProcessor` that reads those completed
spans in `on_end()` and converts them to observra telemetry events.

There is **no double-counting**: `instrument_all()` generates the spans, the
adapter reads them. Each model call produces exactly one `model_response` event.

Span routing:
- `chat *` spans → `model_response` events
- `running tool` / `execute_tool *` spans → `tool_end` events
- All other spans (agent run, etc.) → silently skipped

## Multi-provider support

Works with any Pydantic AI model provider — OpenAI, Anthropic, Gemini, etc.
Token counts and cost are extracted from span attributes regardless of provider.

## Capturing tool arguments

By default, tool inputs are **not** recorded (to avoid logging sensitive
payloads). Opt in on the adapter:

```python
adapter = create_plugin("pydantic-ai", capture_tool_data=True)
```

Payloads are truncated at 4KB and redacted for PII.

## Cost tracking

Token counts are extracted from OTel span attributes. Cost is computed using
co-located pricing data. To alert when a call exceeds a threshold:

```python
adapter = create_plugin("pydantic-ai", cost_threshold_usd=5.00)
```

This emits a `cost_threshold_exceeded` event when a model call's cost
crosses the configured limit.

## Configuration

```python
initialize(
    backend="jsonl",
    path="telemetry.jsonl",
    queue_size=1000,                  # bounded, drop-oldest queue
)
adapter = create_plugin(
    "pydantic-ai",
    capture_tool_data=False,          # opt in to record tool args
    cost_threshold_usd=None,          # cost alerting threshold
    payload_max_bytes=4096,           # max serialized tool data size
)
```

For OTel/Dynatrace/Datadog export and production tuning, see
[Production Deployment](../production-deployment.md).

## Captured Events

- `model_response` — model calls with input/output tokens and cost (any provider)
- `tool_end` — tool invocations with tool name and optional args
- `cost_threshold_exceeded` — cost alerting (if configured)

All events have `framework="pydantic-ai"` for SIEM filtering.

## Full example

See [`examples/pydantic_ai_adapter.py`](../../examples/pydantic_ai_adapter.py) for
a complete walkthrough including setup order and provider configuration.
