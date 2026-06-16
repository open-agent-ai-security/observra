"""Basic JSONL telemetry — capture agent events to a JSONL file.

Usage:
    python examples/basic_jsonl.py

This example shows the simplest integration: initialize with JSONL backend,
create a plugin, and inspect captured events. No running agent required —
uses the plugin's in-memory mode to demonstrate event creation.
"""

from observra import initialize, create_plugin, get_session_cost

# Initialize telemetry with JSONL storage
initialize(
    backend="jsonl",
    path="example_telemetry.jsonl",
    session_id="example-session-001",
)

# Create the plugin (pass to Runner in real usage)
plugin = create_plugin()

print(f"Plugin created: {plugin.name}")
print(f"Session cost: ${get_session_cost()}")
print()
print("In a real ADK application, pass this plugin to your Runner:")
print()
print("  from google.adk.runners import Runner")
print("  runner = Runner(agent=root_agent, plugins=[plugin])")
print("  runner.run(...)")
print()
print("Events will be written to: example_telemetry.jsonl")
