<!--
  Copyright 2026 Exabeam, Inc.
  SPDX-License-Identifier: Apache-2.0
-->
# LiteLLM Setup

Capture model calls across 100+ LLM providers with a single integration.

## Install

```bash
pip install observra[litellm]
```

## Prerequisites

observra observes your LLM calls — it does not provide model credentials.
Configure your provider API keys as you normally would:

```bash
export OPENAI_API_KEY=...
# or ANTHROPIC_API_KEY, AZURE_API_KEY, etc.
```

## Usage

LiteLLM provides a unified `completion()` interface to 100+ providers.
Observra hooks into it via LiteLLM's official callback system — two lines
added to your existing code:

```python
import litellm
from observra import create_plugin, initialize

# 1. Start the telemetry pipeline.
initialize(backend="jsonl", path="telemetry.jsonl")

# 2. Create the adapter (auto-registers into litellm.callbacks).
plugin = create_plugin("litellm")

# 3. Use LiteLLM normally — every call is captured automatically.
response = litellm.completion(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Explain quantum computing in one sentence"}],
)
print(response.choices[0].message.content)
```

Events are written to `telemetry.jsonl`, one JSON object per line:

```bash
cat telemetry.jsonl | jq
```

## How it works

The adapter subclasses LiteLLM's `CustomLogger` and registers itself into
`litellm.callbacks`. LiteLLM calls the adapter after every completion —
sync, async, and streaming — with the full response including token usage.

No monkey-patching. No code changes to your LLM calls. The adapter is
observation-only and never modifies request or response data.

## Supported providers

Any provider LiteLLM supports works automatically, including:

- OpenAI (GPT-4o, GPT-4, GPT-3.5)
- Anthropic (Claude 3.5, Claude 3)
- Azure OpenAI
- AWS Bedrock
- Google Gemini / Vertex AI
- Mistral AI
- Groq
- Ollama (local models)
- Cohere, Together AI, Replicate, and 90+ more

See [LiteLLM's provider list](https://docs.litellm.ai/docs/providers) for
the full catalogue.

## Cost tracking

Observra uses LiteLLM's built-in `completion_cost()` for pricing, which
covers all supported providers. Cost is included in every `model_response`
event as `cost_usd`.

```python
# View costs in your telemetry
cat telemetry.jsonl | jq 'select(.event_type == "model_response") | {model: .model_name, cost: .data.cost_usd}'
```

## Prompt injection detection

Enable content inspection to detect injection patterns in user messages:

```python
plugin = create_plugin("litellm", capture_content=True)
```

When enabled, user messages are scanned for injection patterns. Flagged
events include `has_injection_patterns: true` in the event data.

## Async and streaming

Both work automatically with no extra configuration:

```python
import asyncio
import litellm

# Async
response = asyncio.run(litellm.acompletion(
    model="gpt-4o",
    messages=[{"role": "user", "content": "hello"}],
))

# Streaming — events are captured after stream completes
response = litellm.completion(
    model="gpt-4o",
    messages=[{"role": "user", "content": "hello"}],
    stream=True,
)
for chunk in response:
    print(chunk.choices[0].delta.content or "", end="")
```

## Configuration

```python
initialize(
    backend="jsonl",
    path="telemetry.jsonl",
    queue_size=1000,
)
plugin = create_plugin(
    "litellm",
    agent_name="my-agent",       # attribution in events
    capture_content=False,       # opt in to injection detection
)
```

For OTel/Dynatrace/Datadog export and production tuning, see
[Production Deployment](../production-deployment.md).

## Captured Events

- `model_response` — every successful completion with tokens, cost, duration
- `model_error` — failures with error message and duration

All events have `framework="litellm"` for filtering.

## Full example

See [`examples/litellm_adapter.py`](../../examples/litellm_adapter.py) for
a complete walkthrough with multiple providers.
