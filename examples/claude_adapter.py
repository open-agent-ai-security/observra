"""How to add telemetry to a Claude Agent SDK agent.

Install:
    pip install observra[claude]

BEFORE (your existing agent):
    from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions
    client = ClaudeSDKClient(options=ClaudeAgentOptions(...))
    async for msg in client.stream("Hello"):
        print(msg)

AFTER (3 lines added):
    from observra import initialize                    # 1. import
    from observra.adapters.claude import ClaudeAdapter
    initialize(backend="jsonl", path="telemetry.jsonl")        # 2. init storage
    adapter = ClaudeAdapter()                                 # 3. create adapter

    # Pass hooks to SDK client:
    client = ClaudeSDKClient(options=adapter.get_hook_options())

    # Wrap the message stream to capture model responses:
    async for msg in adapter.wrap_stream(client.stream("Hello")):
        print(msg)  # messages pass through unchanged

That's it. Every tool call, user prompt, and model response is captured.
"""

# ── Step 0: Your existing Claude agent (unchanged) ──────────────

# from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions


# ── Step 1: Add telemetry ────────────────────────────────────────

from observra import initialize
from observra.adapters.claude import ClaudeAdapter

initialize(
    backend="jsonl",
    path="telemetry.jsonl",        # where events are stored
)
adapter = ClaudeAdapter()


# ── Step 2: Pass hooks to the Claude SDK client ─────────────────

# options = adapter.get_hook_options()
# client = ClaudeSDKClient(options=options)


# ── Step 3: Wrap the message stream ─────────────────────────────
#
# async for msg in adapter.wrap_stream(client.stream(prompt)):
#     handle_message(msg)  # messages pass through unchanged
#
# The adapter captures these events automatically:
#   - user_prompt (with estimated token count)
#   - before_tool / after_tool (with tool name, duration)
#   - model_response (from wrap_stream, with response text)
#   - session_end (with exact total cost from ResultMessage)
#   - agent_stop / subagent_stop
#   - cost_threshold_exceeded (if configured)
#
# All events have framework="claude" for SIEM filtering.


# ── Optional: capture tool input/output payloads ────────────────
#
# adapter = ClaudeAdapter(capture_tool_data=True)
#
# This enables tool_args and tool_result in event data (default: off
# for privacy). Payloads are truncated at 4KB and redacted.


# ── Optional: cost threshold alerting ───────────────────────────
#
# initialize(
#     backend="jsonl",
#     path="telemetry.jsonl",
#     cost_threshold_usd=5.00,  # alert when session cost > $5
# )


# ── View your telemetry ─────────────────────────────────────────
#
# CLI dashboard:
#   observra dashboard
#
