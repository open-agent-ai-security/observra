<!--
  Copyright 2026 Exabeam, Inc.
  SPDX-License-Identifier: Apache-2.0
-->
# Claude Agent SDK Setup

Capture every tool call, user prompt, model response, and session cost from a Claude Agent SDK agent.

## Install

```bash
pip install observra[claude]
```

## Prerequisites

observra observes your agent — it does not provide model credentials. Configure
your Anthropic API key as you normally would before adding telemetry:

```bash
export ANTHROPIC_API_KEY=...
```

## Usage

The Claude adapter hooks into the SDK's lifecycle events and wraps the message
stream to capture model responses. This is three added lines plus two small
changes to your existing client setup.

```python
from claude_agent_sdk import ClaudeSDKClient
from observra import create_plugin, initialize

# 1. Point telemetry at a backend (JSONL file shown here).
initialize(backend="jsonl", path="telemetry.jsonl")

# 2. Create the adapter (wired to the pipeline).
adapter = create_plugin("claude")

# 3. Pass hooks to the SDK client.
client = ClaudeSDKClient(options=adapter.get_hook_options())

# 4. Wrap the message stream to capture model responses.
async for msg in adapter.wrap_stream(client.stream("Hello")):
    print(msg)  # messages pass through unchanged
```

Events are written to `telemetry.jsonl`, one JSON object per line:

```bash
cat telemetry.jsonl | python -m json.tool
```

## How it works

The adapter integrates at two points:

1. **Hook callbacks** (`get_hook_options()`) — intercepts `PreToolUse`,
   `PostToolUse`, `UserPromptSubmit`, `Stop`, and `SubagentStop` events.
   All callbacks return `{}` (observation-only, never modifies agent behavior).

2. **Stream wrapper** (`wrap_stream()`) — captures `model_response` events
   from text content blocks and exact session cost from the `ResultMessage`.

## Capturing tool arguments and results

By default, tool inputs/outputs are **not** recorded (to avoid logging
sensitive payloads). Opt in on the adapter:

```python
adapter = create_plugin("claude", capture_tool_data=True)
```

Payloads are truncated at 4KB and redacted for PII.

## Cost tracking

Token costs are estimated via tiktoken during hook callbacks (flagged
`estimated=True`). Exact costs are available from `ResultMessage.total_cost_usd`
when using `wrap_stream()` or `handle_result_message()` — these are flagged
`estimated=False`.

To alert when session cost exceeds a threshold:

```python
adapter = create_plugin("claude", cost_threshold_usd=5.00)
```

This emits a `cost_threshold_exceeded` event when the session total crosses
the configured limit.

## Configuration

```python
initialize(
    backend="jsonl",
    path="telemetry.jsonl",
    queue_size=1000,                  # bounded, drop-oldest queue
)
adapter = create_plugin(
    "claude",
    capture_tool_data=False,          # opt in to record tool args/results
    cost_threshold_usd=None,          # cost alerting threshold
)
```

For OTel/Dynatrace/Datadog export and production tuning, see
[Production Deployment](../production-deployment.md).

## Captured Events

- `user_message` — user prompts with estimated token count
- `model_response` — model output with token counts and cost
- `tool_start` / `tool_end` — tool invocations with duration
- `session_end` — session boundaries with exact total cost
- `agent_end` — agent/subagent stop events
- `cost_threshold_exceeded` — cost alerting (if configured)

All events have `framework="claude"` for SIEM filtering.

## Full example

See [`examples/claude_adapter.py`](../../examples/claude_adapter.py) for
a complete before/after walkthrough.
