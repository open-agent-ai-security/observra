# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0

"""How to add telemetry to an OpenAI Agents SDK agent.

Install:
    pip install observra[openai-agents]

BEFORE (your existing agent):
    from agents import Agent, Runner
    agent = Agent(name="my_agent", instructions="Be helpful")
    result = Runner.run_sync(agent, "Hello")

AFTER (3 lines added):
    from observra import create_plugin, initialize       # 1. import
    from agents import add_trace_processor
    initialize(backend="jsonl", path="telemetry.jsonl")          # 2. init storage
    adapter = create_plugin("openai")                           # 3. create adapter (wired to pipeline)
    add_trace_processor(adapter)                                # 4. register

    # Run your agent normally — telemetry is captured automatically:
    result = Runner.run_sync(agent, "Hello")

That's it. Every LLM call, tool use, and agent handoff is captured.
"""

# ── Step 0: Your existing OpenAI agent (unchanged) ──────────────

from agents import Agent, add_trace_processor, function_tool


@function_tool
def calculator(a: float, b: float) -> float:
    """Add two numbers."""
    return a + b


agent = Agent(
    name="math_assistant",
    instructions="You are a helpful math assistant. Use your tools.",
    tools=[calculator],
)


# ── Step 1: Add telemetry (3 lines) ─────────────────────────────

from observra import create_plugin, initialize  # noqa: E402

initialize(
    backend="jsonl",
    path="telemetry.jsonl",  # where events are stored
)
# create_plugin() connects the adapter to the pipeline initialize() built.
# Constructing OpenAIAdapter() directly leaves it unwired and events are dropped.
adapter = create_plugin("openai")
add_trace_processor(adapter)  # register alongside default processors


# ── Step 2: Run your agent normally ─────────────────────────────

# result = Runner.run_sync(agent, "What is 2 + 3?")
# print(result.final_output)

# The adapter captures these events automatically:
#   - session_start / session_end (from agent spans)
#   - model_response (with input/output tokens, cost)
#   - tool_call (with tool name, duration)
#   - handoff (multi-agent transitions with source/target)
#   - cost_threshold_exceeded (if configured)
#
# All events have framework="openai" for SIEM filtering.


# ── Optional: capture tool input/output payloads ────────────────
#
# adapter = create_plugin("openai", capture_tool_data=True)
#
# This enables tool_args and tool_result in event data.


# ── IMPORTANT: use add_trace_processor, NOT set_trace_processors ─
#
# add_trace_processor(adapter)      # CORRECT — adds alongside defaults
# set_trace_processors([adapter])   # WRONG — replaces all processors


# ── View your telemetry ─────────────────────────────────────────
#
# CLI dashboard:
#   observra dashboard
#
