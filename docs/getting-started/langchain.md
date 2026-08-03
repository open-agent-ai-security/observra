<!--
  Copyright 2026 Exabeam, Inc.
  SPDX-License-Identifier: Apache-2.0
-->
# LangChain / LangGraph Setup

Capture every LLM call, tool use, chain event, and cost from a LangChain or LangGraph agent.

## Install

```bash
pip install observra[langchain]
```

## Prerequisites

observra observes your agent — it does not provide model credentials. Configure
your LLM provider credentials as you normally would before adding telemetry:

```bash
export OPENAI_API_KEY=...        # or ANTHROPIC_API_KEY, GOOGLE_API_KEY, etc.
```

## Usage

The LangChain adapter is a `BaseCallbackHandler` that you pass to your graph
or chain via the `callbacks` config. This is three added lines plus one config
argument — your agent code stays unchanged.

```python
from langgraph.graph import StateGraph, MessagesState
from observra import create_plugin, initialize

# 1. Point telemetry at a backend (JSONL file shown here).
initialize(backend="jsonl", path="telemetry.jsonl")

# 2. Create the adapter (wired to the pipeline).
adapter = create_plugin("langchain")

# 3. Pass as a callback when invoking the graph.
result = app.invoke(
    {"messages": [HumanMessage(content="Hello")]},
    config={"callbacks": [adapter]},  # <-- the only change
)
```

Events are written to `telemetry.jsonl`, one JSON object per line:

```bash
cat telemetry.jsonl | jq   # install jq if it isn't already on your system
```

### Binding callbacks for all invocations

Instead of passing callbacks on every `invoke()`, bind them to the graph:

```python
app_with_telemetry = app.with_config({"callbacks": [adapter]})
result = app_with_telemetry.invoke({"messages": [...]})
```

## How it works

The adapter subclasses `BaseCallbackHandler` from `langchain-core`. It receives
synchronous callbacks for LLM starts/ends, tool starts/ends, and chain
starts/ends. Token extraction is provider-agnostic — works with any LangChain
LLM backend (OpenAI, Anthropic, Gemini, etc.) via `usage_metadata` or legacy
`token_usage` fields.

## Multi-provider support

The adapter extracts tokens from any LangChain LLM backend:

- `ChatOpenAI` — via `usage_metadata` or legacy `token_usage`
- `ChatAnthropic` — via `usage_metadata` or `llm_output["usage"]`
- `ChatGoogleGenerativeAI` — via `usage_metadata`

Pricing is calculated per-model regardless of provider.

## Capturing tool arguments and results

By default, tool inputs/outputs are **not** recorded (to avoid logging
sensitive payloads). Opt in on the adapter:

```python
adapter = create_plugin("langchain", capture_tool_data=True)
```

Payloads are truncated at 4KB and redacted for PII.

## Cost tracking

Token counts are extracted from the LLM response metadata (exact, not
estimated). Cost is computed using co-located pricing data. To alert when
a call exceeds a threshold:

```python
adapter = create_plugin("langchain", cost_threshold_usd=5.00)
```

This emits a `cost_threshold_exceeded` event when an LLM call's cost
crosses the configured limit.

## Configuration

```python
initialize(
    backend="jsonl",
    path="telemetry.jsonl",
    queue_size=1000,  # bounded, drop-oldest queue
)
adapter = create_plugin(
    "langchain",
    capture_tool_data=False,  # opt in to record tool args/results
    cost_threshold_usd=None,  # cost alerting threshold
    payload_max_bytes=4096,  # max serialized tool data size
)
```

For OTel/Dynatrace/Datadog export and production tuning, see
[Production Deployment](../production-deployment.md).

## Captured Events

- `session_start` / `session_end` — chain/graph lifecycle boundaries
- `model_response` — LLM calls with input/output tokens and cost (any provider)
- `tool_start` / `tool_end` — tool invocations with duration
- `tool_error` — tool failures with error classification
- `cost_threshold_exceeded` — cost alerting (if configured)

All events have `framework="langgraph"` for SIEM filtering.

## Full example

See [`examples/langgraph_adapter.py`](../../examples/langgraph_adapter.py) for
a complete before/after walkthrough with a LangGraph state machine agent.
