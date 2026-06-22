"""How to add telemetry to any ADK agent.

This is the simplest possible integration. You have an existing ADK agent
and want to capture what it does — every LLM call, tool use, error, and
how much it costs.

BEFORE (your existing agent):
    agent = Agent(model="gemini-2.5-flash", name="my_agent", ...)
    runner = Runner(agent=agent, app_name="my_app", session_service=session)
    runner.run(...)

AFTER (3 lines added):
    from observra import initialize, create_plugin      # 1. import
    initialize(backend="jsonl", path="telemetry.jsonl")       # 2. init
    plugin = create_plugin()                                  # 3. create plugin
    runner = Runner(agent=agent, plugins=[plugin], ...)       # pass to Runner

That's it. Every lifecycle event is now captured automatically.
"""

# ── Step 0: Your existing agent (unchanged) ────────────────────────

from google.adk.agents.llm_agent import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService

root_agent = Agent(
    model="gemini-2.5-flash",
    name="my_agent",
    description="A helpful assistant",
    instruction="You are a helpful AI assistant. Be concise.",
)


# ── Step 1: Add telemetry (3 lines) ───────────────────────────────

from observra import create_plugin, initialize  # noqa: E402

initialize(
    backend="jsonl",
    path="telemetry.jsonl",      # where events are stored
)
plugin = create_plugin()


# ── Step 2: Pass plugin to Runner ──────────────────────────────────

session_service = InMemorySessionService()

runner = Runner(
    agent=root_agent,
    app_name="my_app",
    session_service=session_service,
    plugins=[plugin],            # <-- this is the only change to your Runner
)


# ── That's it. Now run your agent normally. ────────────────────────
#
# Events are captured automatically:
#   - before_run / after_run
#   - before_model / after_model (with token counts + cost)
#   - before_tool / after_tool
#   - before_agent / after_agent (with delegation depth)
#   - model_error / tool_error (with error classification)
#   - user_message (with injection pattern detection)
#
# View your telemetry:
#   cat telemetry.jsonl | python -m json.tool


# ── Optional: environment variable config (zero code changes) ──────
#
# Instead of passing parameters to initialize(), set env vars:
#
#   export ABA_TELEMETRY_BACKEND=jsonl
#   export ABA_TELEMETRY_PATH=telemetry.jsonl
#
# Then just:
#   initialize()
#   plugin = create_plugin()
#
# This lets you enable/disable telemetry without touching code.


# ── Optional: advanced configuration ───────────────────────────────
#
# initialize(
#     backend="jsonl",
#     path="telemetry.jsonl",
#     cost_threshold_usd=5.00,             # alert when session > $5
#     max_delegation_depth=3,              # alert on deep delegation
#     custom_patterns=[                    # redact org-specific secrets
#         (r"ACME_TOKEN_\w+", "ACME_TOKEN"),
#     ],
# )
