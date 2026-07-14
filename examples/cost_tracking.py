# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Cost tracking with threshold alerts.

Usage:
    python examples/cost_tracking.py

Demonstrates configuring cost threshold alerts. When the accumulated session
cost exceeds the threshold, a `cost_threshold_exceeded` event is emitted.
"""

from observra import create_plugin, initialize

# Initialize the pipeline
initialize(backend="jsonl", path="cost_tracking.jsonl")

# Configure cost threshold on the adapter (not initialize)
plugin = create_plugin("adk", cost_threshold_usd=5.00)

print("Cost tracking configured:")
print("  Threshold: $5.00")
print("  Pricing: bundled Gemini models (Flash, Pro, etc.)")
print()
print("How it works:")
print("  1. Every after_model event includes: input_tokens, output_tokens, cost_usd")
print("  2. Cost accumulates per session via ContextVar (async-safe)")
print("  3. When session total >= $5.00, emits cost_threshold_exceeded event (once)")
print()
print("Custom pricing example:")
print('  initialize(pricing_config="my_pricing.json", cost_threshold_usd=10.0)')
print()
print("Pricing JSON format:")
print("  {")
print('    "gemini-2.5-flash": {')
print('      "input_per_million": 0.075,')
print('      "output_per_million": 0.30,')
print('      "cached_input_per_million": 0.01875')
print("    }")
print("  }")
