"""Sample ADK agent with telemetry — works with `adk web`.

Run with telemetry:
    cd examples
    export ABA_TELEMETRY_BACKEND=jsonl
    export ABA_TELEMETRY_PATH=telemetry_live.jsonl
    adk web . --extra_plugins sample_agent.agent.telemetry_plugin

Run without telemetry:
    cd examples
    adk web .

After chatting, inspect your events:
    cat telemetry_live.jsonl | python3 -m json.tool

The agent is a simple research assistant with two tools: one to look up
a topic and one to save notes. Telemetry captures every LLM call, tool
use, cost, and anomaly automatically.
"""

import os

from google.adk.agents.llm_agent import Agent

from observra import create_plugin, initialize

# ── Tools ──────────────────────────────────────────────────────────


def lookup_topic(topic: str) -> dict:
    """Look up information about a topic.

    Args:
        topic: The topic to research.

    Returns:
        dict with topic info for the LLM to synthesize.
    """
    return {
        "topic": topic,
        "status": "success",
        "result": (
            f"Use your knowledge to provide a clear, concise overview of: {topic}. "
            "Summarize key facts in 2-3 paragraphs."
        ),
    }


def save_notes(title: str, content: str) -> dict:
    """Save research notes for later reference.

    Args:
        title: A short title for the notes.
        content: The notes content to save.

    Returns:
        dict confirming the notes were saved.
    """
    return {
        "status": "saved",
        "title": title,
        "content_length": len(content),
        "message": f"Notes '{title}' saved ({len(content)} chars).",
    }


# ── Telemetry (opt-in) ────────────────────────────────────────────
#
# Single backend:
#   export ABA_TELEMETRY_BACKEND=jsonl
#   export ABA_TELEMETRY_PATH=telemetry.jsonl
#
# Multi-backend (JSONL + OTel):
#   export ABA_TELEMETRY_BACKENDS='[{"type":"jsonl","path":"telemetry.jsonl"},{"type":"otel"}]'
#
# Without these env vars, telemetry is off and the agent runs normally.

telemetry_plugin = None
if os.environ.get("ABA_TELEMETRY_BACKENDS") or os.environ.get("ABA_TELEMETRY_BACKEND"):
    initialize(capture_tool_data=True)
    telemetry_plugin = create_plugin()


# ── Agent ──────────────────────────────────────────────────────────

root_agent = Agent(
    model="gemini-2.5-flash",
    name="research_assistant",
    description="A research assistant that looks up topics and saves notes.",
    instruction="""You are a research assistant. Help the user learn about topics.

When the user asks about a topic:
1. Use lookup_topic to gather information
2. Synthesize the results into a clear answer
3. If the user wants to save findings, use save_notes

Be concise and informative. Cite key facts. If you don't know something,
say so rather than guessing.""",
    tools=[lookup_topic, save_notes],
)
