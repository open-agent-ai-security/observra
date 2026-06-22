# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0

"""How to add telemetry to a Pydantic AI agent.

Install:
    pip install observra[pydantic-ai]

BEFORE (your existing agent):
    from pydantic_ai import Agent
    agent = Agent("openai:gpt-4o")
    result = agent.run_sync("Hello")

AFTER (5 lines added):
    from opentelemetry.sdk.trace import TracerProvider          # 1. OTel setup
    from opentelemetry.trace import set_tracer_provider
    from pydantic_ai import Agent
    from observra import initialize                      # 2. import
    from observra.adapters.pydantic_ai import PydanticAIAdapter

    initialize(backend="jsonl", path="telemetry.jsonl")          # 3. init storage
    adapter = PydanticAIAdapter()                               # 4. create adapter

    provider = TracerProvider()
    provider.add_span_processor(adapter)                        # 5. register
    set_tracer_provider(provider)
    Agent.instrument_all()                                      # 6. enable spans

    # Run your agent normally — telemetry is captured automatically:
    agent = Agent("openai:gpt-4o")
    result = agent.run_sync("Hello")

That's it. Every model call and tool use is captured via OpenTelemetry spans.
No double-counting — the adapter reads spans, it doesn't create them.
"""

# ── Step 0: OTel and Pydantic AI setup ──────────────────────────

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace import set_tracer_provider
from pydantic_ai import Agent

# ── Step 1: Add telemetry ────────────────────────────────────────
from observra import initialize
from observra.adapters.pydantic_ai import PydanticAIAdapter

initialize(
    backend="jsonl",
    path="telemetry.jsonl",        # where events are stored
)
adapter = PydanticAIAdapter()


# ── Step 2: Wire into OpenTelemetry (order matters!) ────────────

provider = TracerProvider()
provider.add_span_processor(adapter)    # must happen BEFORE set_tracer_provider
set_tracer_provider(provider)
Agent.instrument_all()                  # must call BEFORE any agent runs


# ── Step 3: Run your agent normally ─────────────────────────────

# agent = Agent("openai:gpt-4o")
# result = agent.run_sync("What is 2+3?")
# print(result.data)

# The adapter captures these events automatically:
#   - model_response (with input/output tokens, cost per model)
#   - tool_call (with tool name and optional args)
#   - cost_threshold_exceeded (if configured)
#
# All events have framework="pydantic-ai" for SIEM filtering.
# Works with any Pydantic AI model provider (OpenAI, Anthropic, Gemini).


# ── Optional: capture tool input/output payloads ────────────────
#
# adapter = PydanticAIAdapter(capture_tool_data=True)
#
# This enables tool_args in event data.


# ── IMPORTANT: setup order ──────────────────────────────────────
#
# 1. TracerProvider()                     -- create provider first
# 2. provider.add_span_processor(adapter) -- register adapter
# 3. set_tracer_provider(provider)        -- set as global
# 4. Agent.instrument_all()               -- enable span generation
# 5. Agent("openai:gpt-4o")              -- create and run agent
#
# Wrong order = missing events. The adapter must be registered
# before pydantic-ai starts emitting spans.


# ── No double-counting ─────────────────────────────────────────
#
# Using Agent.instrument_all() AND PydanticAIAdapter together is
# correct and required:
#   - instrument_all() generates the OTel spans
#   - PydanticAIAdapter reads those spans (SpanProcessor)
#   - Each model call produces exactly one model_response event


# ── View your telemetry ─────────────────────────────────────────
#
# CLI dashboard:
#   observra dashboard
#
