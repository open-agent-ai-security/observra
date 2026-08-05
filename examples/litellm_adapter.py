# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0

"""How to add telemetry to any LiteLLM application.

Install:
    pip install observra[litellm]

BEFORE (your existing code):
    import litellm
    response = litellm.completion(model="gpt-4o", messages=[...])

AFTER (3 lines added):
    from observra import create_plugin, initialize        # 1. import
    initialize(backend="jsonl", path="telemetry.jsonl")   # 2. init pipeline
    plugin = create_plugin("litellm")                     # 3. create adapter

    # Use LiteLLM normally — every call is captured automatically.
    response = litellm.completion(model="gpt-4o", messages=[...])

That's it. Every model call is captured across all 100+ providers.
"""

import litellm

from observra import create_plugin, initialize

# ── Step 1: Initialize the telemetry pipeline ─────────────────────

initialize(backend="jsonl", path="litellm_telemetry.jsonl")

# ── Step 2: Create the adapter ────────────────────────────────────

plugin = create_plugin("litellm", agent_name="demo-agent")

# ── Step 3: Use LiteLLM normally ──────────────────────────────────

# Any provider works — OpenAI, Anthropic, Gemini, Mistral, Ollama, etc.
# Using mock_response so this example runs without API keys.

response = litellm.completion(
    model="gpt-4o",
    messages=[{"role": "user", "content": "What is 2+2?"}],
    mock_response="2+2 equals 4.",
)
print(f"Response: {response.choices[0].message.content}")

# Try a different provider (also mocked)
response = litellm.completion(
    model="anthropic/claude-3-haiku-20240307",
    messages=[{"role": "user", "content": "Hello!"}],
    mock_response="Hello! How can I help?",
)
print(f"Response: {response.choices[0].message.content}")

# ── View captured telemetry ───────────────────────────────────────

print()
print("Telemetry captured:")
print(f"  Events: {plugin.get_adapter_stats()['events_captured']}")
print("  File: litellm_telemetry.jsonl")
print()
print("View events:")
print("  cat litellm_telemetry.jsonl | python -m json.tool")
