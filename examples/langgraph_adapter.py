# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0

"""How to add telemetry to a LangGraph / LangChain agent.

Install:
    pip install observra[langchain] langchain-openai   # Step 0 below uses ChatOpenAI as the LLM

BEFORE (your existing agent):
    from langgraph.graph import StateGraph, MessagesState
    graph = StateGraph(MessagesState)
    # ... build graph ...
    app = graph.compile()
    result = app.invoke({"messages": [HumanMessage(content="Hello")]})

AFTER (3 lines added):
    from observra import create_plugin, initialize                 # 1. import
    initialize(backend="jsonl", path="telemetry.jsonl")              # 2. init storage
    adapter = create_plugin("langchain")                            # 3. create adapter (wired to pipeline)

    # Pass as callback when invoking the graph:
    result = app.invoke(
        {"messages": [HumanMessage(content="Hello")]},
        config={"callbacks": [adapter]},                            # <-- only change
    )

That's it. Every LLM call, tool use, and chain event is captured.
Works with any LLM provider (OpenAI, Anthropic, Gemini, etc.).
"""

# ── Step 0: Your existing LangGraph agent (unchanged) ───────────
#
# Building the graph needs `langchain-openai` + OPENAI_API_KEY (see Install).
# Wrapped in a function so this file imports for inspection without credentials.

from langgraph.graph import MessagesState, StateGraph


def build_app():
    from langchain_openai import ChatOpenAI

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    graph = StateGraph(MessagesState)

    def llm_node(state):
        return {"messages": [llm.invoke(state["messages"])]}

    graph.add_node("llm", llm_node)
    graph.set_entry_point("llm")
    graph.set_finish_point("llm")
    return graph.compile()


# app = build_app()   # uncomment to run (needs the deps + key above)


# ── Step 1: Add telemetry (3 lines) ─────────────────────────────

from observra import create_plugin, initialize  # noqa: E402

initialize(
    backend="jsonl",
    path="telemetry.jsonl",  # where events are stored
)
# create_plugin() connects the adapter to the pipeline initialize() built.
# Constructing LangChainAdapter() directly leaves it unwired and events are dropped.
adapter = create_plugin("langchain")


# ── Step 2: Pass adapter as a callback ──────────────────────────

# result = app.invoke(
#     {"messages": [HumanMessage(content="What is 2+3?")]},
#     config={"callbacks": [adapter]},
# )

# Or bind to the graph for all invocations:
# app_with_telemetry = app.with_config({"callbacks": [adapter]})
# result = app_with_telemetry.invoke({"messages": [...]})

# The adapter captures these events automatically:
#   - session_start / session_end (top-level graph lifecycle)
#   - agent_start / agent_end (nested chains / sub-graphs)
#   - model_response (with input/output tokens, cost per model)
#   - tool_start / tool_end (with tool name, duration)
#   - tool_error (with error classification)
#   - cost_threshold_exceeded (if configured)
#
# All events have framework="langgraph" for SIEM filtering.
# Token counts are extracted from any LLM provider (OpenAI, Anthropic, etc.).


# ── Optional: capture tool input/output payloads ────────────────
#
# adapter = create_plugin("langchain", capture_tool_data=True)
#
# This enables tool_args and tool_result in event data.


# ── Multi-provider support ──────────────────────────────────────
#
# The adapter extracts tokens from any LangChain LLM backend:
#   - ChatOpenAI (usage_metadata or legacy token_usage)
#   - ChatAnthropic (usage_metadata or llm_output["usage"])
#   - ChatGoogleGenerativeAI (usage_metadata)
#
# Pricing is calculated per-model regardless of provider.


# ── View your telemetry ─────────────────────────────────────────
#
# CLI dashboard:
#   observra dashboard
#
