<!--
  Copyright 2026 Exabeam, Inc.
  SPDX-License-Identifier: Apache-2.0
-->
# Custom Framework Setup

Instrument any agent — including custom stacks, in-house orchestration, or
frameworks Observra doesn't ship a native adapter for — using the public
`emit()` API.

## Install

```bash
pip install observra
```

No extras needed — `emit()` is part of the core package.

## Usage

Three functions give you full access to the telemetry pipeline:

```python
import observra

# 1. Start the pipeline.
observra.initialize(backend="jsonl", path="telemetry.jsonl")

# 2. Set session identity (groups all events in this run).
observra.initialize_session("my-session-id")

# 3. Emit events from your agent's lifecycle.
observra.emit(
    "model_response",
    agent_name="my-agent",
    model_name="deepseek-v4",
    framework="custom",
    input_tokens=1200,
    output_tokens=310,
    cost_usd=0.023,
    duration_ms=2100,
)
```

That's it. Every event you emit goes through the full Observra pipeline:
redaction, injection detection, cost tracking, deduplication, and CIM
normalization.

## When to use this

Use `emit()` when:

- Your agent uses a framework Observra doesn't have an adapter for
- You're building a custom orchestration layer
- You want to emit domain-specific events (handoffs, guardrail decisions)
- Your agent is in TypeScript/Go/Rust and you're sending events via webhook

If your agent uses ADK, Claude SDK, OpenAI, LangChain, Pydantic AI, or
LiteLLM — use the native adapter instead (it captures events automatically).

## Session identity

`initialize_session()` sets a stable session ID that threads through all
events in the current execution context. Without it, Observra generates a
random ULID once per context and reuses it — events are still grouped within
that run, but you can't correlate the session to your own run IDs.

```python
import observra

observra.initialize(backend="sqlite", path="telemetry.db")

# Use your own ID (deterministic, correlatable with your system)
observra.initialize_session("run-2026-07-15-user-alice")
```

Session IDs propagate via Python's `contextvars`, so they work correctly
in async code and across function boundaries.

## Common event types

```python
import observra

# Model call completed
observra.emit(
    "model_response",
    model_name="gpt-4o",
    agent_name="research-agent",
    framework="custom",
    input_tokens=2400,
    output_tokens=180,
    cost_usd=0.031,
    duration_ms=3200,
)

# Tool invocation
observra.emit(
    "tool_start",
    tool_name="web_search",
    agent_name="research-agent",
    framework="custom",
)

observra.emit(
    "tool_end",
    tool_name="web_search",
    agent_name="research-agent",
    framework="custom",
    duration_ms=450,
)

# Model error
observra.emit(
    "model_error",
    model_name="gpt-4o",
    agent_name="research-agent",
    framework="custom",
    error_message="Rate limit exceeded",
    duration_ms=100,
)

# Agent handoff
observra.emit(
    "agent_start",
    agent_name="code-reviewer",
    framework="custom",
    source_agent="research-agent",
)

# Session boundaries
observra.emit("session_start", agent_name="research-agent", framework="custom")
observra.emit("session_end", agent_name="research-agent", framework="custom", session_cost_usd=0.15)
```

## Injection detection

When you pass `user_message_text`, the pipeline automatically scans for
prompt injection patterns:

```python
observra.emit(
    "user_message",
    agent_name="my-agent",
    framework="custom",
    user_message_text=user_input,  # scanned for injection patterns
)
```

Flagged events include `has_injection_patterns: true` and the matched
pattern names in the event data.

## Cost tracking

For `model_response` events, if you provide `input_tokens` and
`output_tokens` but not `cost_usd`, Observra will attempt to calculate
cost using its built-in pricing catalogue (Gemini models). For other
providers, pass `cost_usd` explicitly:

```python
# Auto-calculated (Gemini models)
observra.emit("model_response", model_name="gemini-2.5-flash", input_tokens=1000, output_tokens=100)

# Explicit (any provider)
observra.emit("model_response", model_name="deepseek-v4", input_tokens=1000, output_tokens=100, cost_usd=0.008)
```

## Pipeline guarantees

Every event emitted through `emit()` gets the same treatment as events
from native adapters:

- **Redaction** — PII, secrets, and API keys scrubbed before storage
- **Injection detection** — on `user_message_text` fields
- **Cost tracking** — auto-calculated or pass-through
- **Deduplication** — no double-counting if an adapter also emits
- **CIM normalization** — consistent schema across all frameworks
- **Non-blocking** — events are queued, never blocks your agent

## Error safety

`emit()` never raises. If something goes wrong internally, the error is
logged and your agent continues unaffected.

## Real-world examples

### OpenClaw (TypeScript)

[OpenClaw](https://github.com/open-agent-ai-security/openclaw) is a
multi-channel personal AI assistant built in TypeScript. Since it's not
Python, use the webhook backend — OpenClaw's plugin SDK can forward events
over HTTP:

```python
# Python receiver side
observra.initialize(backend="webhook", url="http://localhost:8080/telemetry")
```

```typescript
// OpenClaw plugin — forward agent events to Observra's webhook
api.registerAgentEventSubscription({
    onTurnComplete: (event) => {
        fetch("http://localhost:8080/telemetry", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                event_type: "model_response",
                model_name: event.model,
                framework: "openclaw",
                input_tokens: event.usage.input,
                output_tokens: event.usage.output,
            }),
        });
    },
});
```

Alternatively, OpenClaw has built-in OpenTelemetry support
(`diagnostics.otel.enabled = true`) — configure it to emit to any OTLP
collector that Observra's OTel backend can consume from.

### Hermes (Python, custom orchestration)

Hermes is a custom Python agent with its own observer-hook contract. It
uses `emit()` directly with host-set session identity for usage accounting:

```python
import observra

observra.initialize(backend="jsonl", path="hermes_telemetry.jsonl")
observra.initialize_session("20260707_091500_ab12cd")  # deterministic, host-controlled

# After each LLM call in the agent loop:
observra.emit(
    "model_response",
    agent_name="hermes",
    model_name="deepseek-v4-pro",
    framework="custom",
    input_tokens=12400,
    output_tokens=310,
    cached_tokens=8100,
    cost_usd=0.0228,
    duration_ms=2100,
)
```

The stable session ID threads through all events, enabling downstream
rollups (total cost, token budget, multi-turn correlation) without relying
on Observra's random fallback.

## Full example

See [`examples/custom_emit.py`](../../examples/custom_emit.py) for a
complete walkthrough simulating a multi-step agent session.
