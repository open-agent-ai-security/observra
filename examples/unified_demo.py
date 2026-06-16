#!/usr/bin/env python3
"""Unified 6-framework demo: every framework, same telemetry, same fields.

Runs mock sessions through all 6 REAL adapters (ADK, OpenAI, Claude,
LangGraph, Pydantic AI, Copilot) and writes all events to a shared JSONL
file. Prints cross-framework normalization table proving field identity.

No API keys needed. No GCP needed. Just run it.

Usage:
    python3 examples/unified_demo.py
    python3 examples/unified_demo.py --verbose    # show per-event detail
    python3 examples/unified_demo.py --output events.jsonl  # custom output path
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import logging
import os
import sys
import tempfile
import types
import uuid
from dataclasses import asdict

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.WARNING)

from aba_telemetry.core.events import create_event, EventType, TelemetryEvent
from aba_telemetry.core.context import (
    initialize_trace, initialize_session, new_span,
)

# ── Shared state ────────────────────────────────────────────────────────
_all_events: list[TelemetryEvent] = []

FRAMEWORK_ORDER = ["adk", "claude", "openai", "langgraph", "pydantic-ai", "copilot"]
FRAMEWORK_LABELS = {
    "adk": "ADK", "claude": "Claude", "openai": "OpenAI",
    "langgraph": "LangGraph", "pydantic-ai": "PydanticAI", "copilot": "Copilot",
}


# ========================================================================
# 1. ADK — TelemetryPlugin (BasePlugin)
# ========================================================================

def run_adk_session(verbose: bool = False) -> list[TelemetryEvent]:
    """Run ADK session through the real TelemetryPlugin."""
    print("\n── ADK (Gemini 2.5 Flash) ──")
    from aba_telemetry.adapters.adk.plugin import TelemetryPlugin

    plugin = TelemetryPlugin(queue=None)

    # Mock ADK objects
    ctx = types.SimpleNamespace(agent_name="threat_analyzer", user_id="demo-user")
    agent = types.SimpleNamespace(name="threat_analyzer")
    cb_ctx = types.SimpleNamespace()
    llm_req = types.SimpleNamespace(model="gemini-2.5-flash")

    # Mock usage_metadata on response
    usage = types.SimpleNamespace(
        prompt_token_count=1250, candidates_token_count=380, total_token_count=1630,
        cached_content_token_count=200, thoughts_token_count=45,
    )
    llm_resp = types.SimpleNamespace(usage_metadata=usage, model_version=None)

    # Mock tool
    tool = types.SimpleNamespace(name="search_cve_database")
    tool_ctx = types.SimpleNamespace()

    async def _run():
        await plugin.on_user_message_callback(invocation_context=ctx, user_message="Analyze CVE-2024-1234")
        await plugin.before_run_callback(invocation_context=ctx)
        await plugin.before_agent_callback(agent=agent, callback_context=cb_ctx)
        await plugin.before_model_callback(callback_context=cb_ctx, llm_request=llm_req)
        await plugin.after_model_callback(callback_context=cb_ctx, llm_response=llm_resp)
        await plugin.before_tool_callback(tool=tool, tool_args={}, tool_context=tool_ctx)
        await plugin.after_tool_callback(tool=tool, tool_args={}, tool_context=tool_ctx, result="CVE-2024-1234: Critical RCE")
        await plugin.after_agent_callback(agent=agent, callback_context=cb_ctx)
        await plugin.after_run_callback(invocation_context=ctx)
        await plugin.close()

    asyncio.run(_run())
    events = plugin.events
    if verbose:
        for e in events:
            print(f"  [{e.framework:>11}] {e.event_type}")
    return events


# ========================================================================
# 2. OpenAI — OpenAIAdapter (TracingProcessor)
# ========================================================================

# Stub SDK modules for mock mode
class _MockAgentSpanData:
    def __init__(self, **kw): self.__dict__.update(kw)

class _MockGenerationSpanData:
    def __init__(self, **kw): self.__dict__.update(kw)

class _MockFunctionSpanData:
    def __init__(self, **kw): self.__dict__.update(kw)

class _MockHandoffSpanData:
    def __init__(self, **kw): self.__dict__.update(kw)

def _ensure_openai_stubs():
    """Inject agents.tracing stubs if not installed."""
    if "agents.tracing" in sys.modules:
        return
    class _Stub:
        def on_trace_start(self, t): pass
        def on_trace_end(self, t): pass
        def on_span_start(self, s): pass
        def on_span_end(self, s): pass
        def shutdown(self): pass
        def force_flush(self): pass

    m = types.ModuleType("agents")
    mt = types.ModuleType("agents.tracing")
    msd = types.ModuleType("agents.tracing.span_data")
    mt.TracingProcessor = _Stub
    msd.AgentSpanData = _MockAgentSpanData
    msd.GenerationSpanData = _MockGenerationSpanData
    msd.FunctionSpanData = _MockFunctionSpanData
    msd.HandoffSpanData = _MockHandoffSpanData
    m.tracing = mt; mt.span_data = msd
    sys.modules["agents"] = m
    sys.modules["agents.tracing"] = mt
    sys.modules["agents.tracing.span_data"] = msd


def run_openai_session(verbose: bool = False) -> list[TelemetryEvent]:
    """Run OpenAI session through the real OpenAIAdapter."""
    print("\n── OpenAI (GPT-4o) ──")
    _ensure_openai_stubs()

    from aba_telemetry.adapters.openai.adapter import OpenAIAdapter
    import aba_telemetry.adapters.openai.adapter as mod
    mod.AgentSpanData = _MockAgentSpanData
    mod.GenerationSpanData = _MockGenerationSpanData
    mod.FunctionSpanData = _MockFunctionSpanData
    mod.HandoffSpanData = _MockHandoffSpanData

    initialize_trace(); initialize_session()
    adapter = OpenAIAdapter(queue=None, capture_tool_data=True)

    # Agent span start -> session_start
    agent_data = _MockAgentSpanData(name="triage_agent", tools=["ticket_lookup"], handoffs=[], output_type="str")
    agent_span = types.SimpleNamespace(span_id="s1", trace_id="t1", parent_id=None,
        started_at="2026-03-03T10:00:00Z", ended_at="2026-03-03T10:00:10Z",
        error=None, span_data=agent_data)
    adapter.on_span_start(agent_span)

    # Generation span -> model_response
    gen_data = _MockGenerationSpanData(model="gpt-4o", output=None, input=None,
        usage={"input_tokens": 800, "output_tokens": 250, "total_tokens": 1050,
               "input_tokens_details": {"cached_tokens": 0},
               "output_tokens_details": {"reasoning_tokens": 60}})
    gen_span = types.SimpleNamespace(span_id="s2", trace_id="t1", parent_id="s1",
        started_at="2026-03-03T10:00:01Z", ended_at="2026-03-03T10:00:02Z",
        error=None, span_data=gen_data)
    adapter.on_span_end(gen_span)

    # Function span -> tool_end
    func_data = _MockFunctionSpanData(name="ticket_lookup", input='{"id": 42}', output="Ticket #42: open")
    func_span = types.SimpleNamespace(span_id="s3", trace_id="t1", parent_id="s1",
        started_at="2026-03-03T10:00:02Z", ended_at="2026-03-03T10:00:02.500Z",
        error=None, span_data=func_data)
    adapter.on_span_end(func_span)

    # Agent span end -> session_end
    adapter.on_span_end(agent_span)
    adapter.shutdown()

    events = adapter._events.copy()
    if verbose:
        for e in events:
            print(f"  [{e.framework:>11}] {e.event_type}")
    return events


# ========================================================================
# 3. Claude — ClaudeAdapter (hooks + wrap_stream)
# ========================================================================

def run_claude_session(verbose: bool = False) -> list[TelemetryEvent]:
    """Run Claude session through the real ClaudeAdapter."""
    print("\n── Claude (Sonnet 4.6) ──")
    import aba_telemetry.adapters.utils as utils_mod
    utils_mod.TIKTOKEN_DISABLED = True

    initialize_trace(); initialize_session()
    from aba_telemetry.adapters.claude.adapter import ClaudeAdapter
    adapter = ClaudeAdapter(queue=None)

    async def _run():
        # UserPromptSubmit
        await adapter._on_user_prompt_submit(
            {"prompt": "Review this code for vulnerabilities"}, None, None)

        # PreToolUse + PostToolUse
        await adapter._on_pre_tool_use(
            {"tool_name": "code_review", "tool_input": {"file": "main.py"}}, "tu-001", None)
        await adapter._on_post_tool_use(
            {"tool_name": "code_review", "tool_input": {"file": "main.py"},
             "tool_response": "2 critical vulnerabilities found"}, "tu-001", None)

        # Stop hook
        await adapter._on_stop({"stop_hook_active": True}, None, None)

        # wrap_stream -> model_response + session_end
        text_block = types.SimpleNamespace(type="text", text="Found 2 critical vulns")
        assistant_msg = types.SimpleNamespace(content=[text_block])
        result_msg = types.SimpleNamespace(
            total_cost_usd=0.0042, num_turns=3, is_error=False,
            session_id="mock-001", usage=None)

        async def mock_stream():
            yield assistant_msg
            yield result_msg

        async for _ in adapter.wrap_stream(mock_stream()):
            pass

    asyncio.run(_run())
    events = adapter._events.copy()
    if verbose:
        for e in events:
            print(f"  [{e.framework:>11}] {e.event_type}")
    return events


# ========================================================================
# 4. LangGraph — LangChainAdapter (BaseCallbackHandler)
# ========================================================================

def _ensure_langchain_stubs():
    """Inject langchain_core stubs if not installed."""
    if "langchain_core" in sys.modules:
        return
    class _BCH:
        def on_llm_end(self, *a, **k): pass
        def on_llm_start(self, *a, **k): pass
        def on_llm_new_token(self, *a, **k): pass
        def on_chat_model_start(self, *a, **k): pass
        def on_tool_start(self, *a, **k): pass
        def on_tool_end(self, *a, **k): pass
        def on_tool_error(self, *a, **k): pass
        def on_chain_start(self, *a, **k): pass
        def on_chain_end(self, *a, **k): pass
        def on_chain_error(self, *a, **k): pass

    lc = types.ModuleType("langchain_core")
    lcb = types.ModuleType("langchain_core.callbacks")
    lcbb = types.ModuleType("langchain_core.callbacks.base")
    lco = types.ModuleType("langchain_core.outputs")
    lcbb.BaseCallbackHandler = _BCH
    lco.LLMResult = type("LLMResult", (), {})
    lc.callbacks = lcb; lcb.base = lcbb
    sys.modules.setdefault("langchain_core", lc)
    sys.modules.setdefault("langchain_core.callbacks", lcb)
    sys.modules.setdefault("langchain_core.callbacks.base", lcbb)
    sys.modules.setdefault("langchain_core.outputs", lco)


def run_langgraph_session(verbose: bool = False) -> list[TelemetryEvent]:
    """Run LangGraph session through the real LangChainAdapter."""
    print("\n── LangGraph (Gemini 2.5 Pro) ──")
    _ensure_langchain_stubs()

    initialize_trace(); initialize_session()
    from aba_telemetry.adapters.langchain.adapter import LangChainAdapter
    adapter = LangChainAdapter(queue=None, capture_tool_data=False)

    root_id = uuid.uuid4()
    llm_id = uuid.uuid4()
    tool_id = uuid.uuid4()

    # Chain start
    adapter.on_chain_start({"name": "research_graph"}, {}, run_id=root_id, parent_run_id=None)

    # Model start + end
    adapter.on_chat_model_start({"kwargs": {"model_name": "gemini-2.5-pro"}}, [[]], run_id=llm_id)
    mock_msg = types.SimpleNamespace(
        usage_metadata={"input_tokens": 2000, "output_tokens": 600, "total_tokens": 2600},
        response_metadata={"model_name": "gemini-2.5-pro"})
    mock_gen = types.SimpleNamespace(message=mock_msg, text="Research summary")
    llm_result = types.SimpleNamespace(
        generations=[[mock_gen]], llm_output={"model_name": "gemini-2.5-pro"})
    adapter.on_llm_end(llm_result, run_id=llm_id)

    # Tool start + end
    adapter.on_tool_start({"name": "web_search"}, '{"q": "AI safety"}', run_id=tool_id)
    adapter.on_tool_end("10 results found", run_id=tool_id)

    # Chain end
    adapter.on_chain_end({}, run_id=root_id, parent_run_id=None)

    events = adapter._events.copy()
    if verbose:
        for e in events:
            print(f"  [{e.framework:>11}] {e.event_type}")
    return events


# ========================================================================
# 5. Pydantic AI — PydanticAIAdapter (SpanProcessor)
# ========================================================================

def _ensure_otel_stubs():
    """Inject opentelemetry.sdk.trace stubs if not installed."""
    if "opentelemetry.sdk.trace" in sys.modules:
        return
    class _SP:
        def on_start(self, s, parent_context=None): pass
        def on_end(self, s): pass
        def shutdown(self): pass
        def force_flush(self, timeout_millis=None): return True

    o = types.ModuleType("opentelemetry")
    os_ = types.ModuleType("opentelemetry.sdk")
    ost = types.ModuleType("opentelemetry.sdk.trace")
    ost.SpanProcessor = _SP
    ost.ReadableSpan = type("ReadableSpan", (), {})
    o.sdk = os_; os_.trace = ost
    sys.modules.setdefault("opentelemetry", o)
    sys.modules.setdefault("opentelemetry.sdk", os_)
    sys.modules.setdefault("opentelemetry.sdk.trace", ost)


def run_pydantic_ai_session(verbose: bool = False) -> list[TelemetryEvent]:
    """Run Pydantic AI session through the real PydanticAIAdapter."""
    print("\n── Pydantic AI (GPT-4o) ──")
    _ensure_otel_stubs()

    initialize_trace(); initialize_session()
    from aba_telemetry.adapters.pydantic_ai.adapter import PydanticAIAdapter
    adapter = PydanticAIAdapter(capture_tool_data=True)

    # Model span
    model_span = types.SimpleNamespace(name="chat gpt-4o", attributes={
        "gen_ai.request.model": "gpt-4o", "gen_ai.response.model": "gpt-4o",
        "gen_ai.usage.input_tokens": 500, "gen_ai.usage.output_tokens": 200})
    adapter.on_end(model_span)

    # Tool span
    tool_span = types.SimpleNamespace(name="running tool", attributes={
        "gen_ai.tool.name": "calculator", "gen_ai.tool.parameters": '{"a": 2, "b": 3}'})
    adapter.on_end(tool_span)

    events = adapter._events.copy()
    if verbose:
        for e in events:
            print(f"  [{e.framework:>11}] {e.event_type}")
    return events


# ========================================================================
# 6. Copilot — CopilotAdapter (stub, emit via create_event)
# ========================================================================

def run_copilot_session(verbose: bool = False) -> list[TelemetryEvent]:
    """Run Copilot session through the real CopilotAdapter."""
    print("\n── Copilot (Azure GPT-4o) ──")
    from aba_telemetry.adapters.copilot.adapter import CopilotAdapter

    initialize_trace(); initialize_session()
    adapter = CopilotAdapter(queue=None)

    adapter.emit(create_event(EventType.SESSION_START, agent_name="customer_support_copilot", framework="copilot"))
    adapter.emit(create_event(EventType.USER_MESSAGE, agent_name="customer_support_copilot", framework="copilot", has_injection_patterns=False))

    new_span()
    adapter.emit(create_event(EventType.AGENT_START, agent_name="customer_support_copilot", framework="copilot"))
    adapter.emit(create_event(EventType.MODEL_REQUEST, model_name="gpt-4o", framework="copilot"))
    adapter.emit(create_event(EventType.MODEL_RESPONSE, model_name="gpt-4o", framework="copilot",
        input_tokens=420, output_tokens=180, total_tokens=600, cost_usd=0.00285))

    new_span()
    adapter.emit(create_event(EventType.TOOL_START, tool_name="search_knowledge_base", framework="copilot", tool_type="connector"))
    adapter.emit(create_event(EventType.TOOL_END, tool_name="search_knowledge_base", framework="copilot",
        tool_type="connector", duration_ms=890.3, tool_result="KB article: Reset password via SSO portal"))

    new_span()
    adapter.emit(create_event(EventType.TOOL_START, tool_name="enrich_customer_context", framework="copilot", tool_type="power-automate"))
    adapter.emit(create_event(EventType.TOOL_END, tool_name="enrich_customer_context", framework="copilot",
        tool_type="power-automate", duration_ms=1450.7))

    adapter.emit(create_event(EventType.MODEL_RESPONSE, model_name="gpt-4o", framework="copilot",
        input_tokens=680, output_tokens=220, cached_tokens=50, total_tokens=900, cost_usd=0.00388))
    adapter.emit(create_event(EventType.AGENT_END, agent_name="customer_support_copilot", framework="copilot"))
    adapter.emit(create_event(EventType.SESSION_END, agent_name="customer_support_copilot", framework="copilot"))
    adapter.emit(create_event(EventType.ADAPTER_CLOSE, framework="copilot"))

    events = adapter.events
    if verbose:
        for e in events:
            print(f"  [{e.framework:>11}] {e.event_type}")
    return events


# ========================================================================
# SIEM Schema Transform (same as PubSubBackend._transform_to_schema)
# ========================================================================

def _transform(event: TelemetryEvent) -> dict:
    raw = asdict(event)
    data = raw.get("data") or {}
    dur = data.pop("duration_ms", None)
    if dur is not None: dur = float(dur)
    success = data.pop("success", None)
    if success is not None: success = bool(success)
    err_type = data.pop("error_type", None)
    return {
        "event_id": raw["event_id"],
        "trace_id": raw["trace_id"],
        "session_id": raw["session_id"],
        "span_id": raw.get("span_id"),
        "timestamp": datetime.datetime.fromtimestamp(raw["timestamp"], tz=datetime.timezone.utc).isoformat(),
        "event_type": raw["event_type"],
        "framework": raw.get("framework") if raw.get("framework") != "unknown" else None,
        "model_name": raw.get("model_name"),
        "agent_name": raw.get("agent_name"),
        "tool_name": raw.get("tool_name"),
        "duration_ms": dur, "success": success, "error_type": err_type,
        "data": data if data else None,
    }


# ========================================================================
# Cross-Framework Normalization Table
# ========================================================================

def _fmt(val) -> str:
    if val is None: return "-"
    if isinstance(val, float):
        return f"{val:.6f}" if val < 0.01 else f"{val:.4f}"
    return str(val)

def _trunc(s: str, n: int) -> str:
    return s if len(s) <= n else s[:n-1] + "\u2026"

def _find(events, fw, et):
    for e in events:
        if e.framework == fw and e.event_type == et:
            return e
    return None

def print_normalization_table(events: list[TelemetryEvent]):
    for target_type, fields, tagline in [
        (EventType.MODEL_RESPONSE, [
            ("event_type",      lambda s: s.get("event_type")),
            ("framework",       lambda s: s.get("framework")),
            ("model_name",      lambda s: s.get("model_name")),
            ("input_tokens",    lambda s: (s.get("data") or {}).get("input_tokens")),
            ("output_tokens",   lambda s: (s.get("data") or {}).get("output_tokens")),
            ("cached_tokens",   lambda s: (s.get("data") or {}).get("cached_tokens")),
            ("reasoning_tokens",lambda s: (s.get("data") or {}).get("reasoning_tokens")),
            ("cost_usd",        lambda s: (s.get("data") or {}).get("cost_usd")),
            ("total_tokens",    lambda s: (s.get("data") or {}).get("total_tokens")),
        ], "Same field names. Same structure. Any framework. One SIEM rule."),
        (EventType.TOOL_END, [
            ("event_type",  lambda s: s.get("event_type")),
            ("framework",   lambda s: s.get("framework")),
            ("tool_name",   lambda s: s.get("tool_name")),
            ("duration_ms", lambda s: s.get("duration_ms")),
            ("tool_type",   lambda s: (s.get("data") or {}).get("tool_type")),
        ], "Connectors, Power Automate flows, MCP tools, functions \u2014 all normalized."),
    ]:
        print(f"\n{'═' * 3} CROSS-FRAMEWORK NORMALIZATION: {target_type} {'═' * 3}")
        schemas = {}
        for fw in FRAMEWORK_ORDER:
            ev = _find(events, fw, target_type)
            if ev:
                schemas[fw] = _transform(ev)

        label_w = 17
        col_w = {}
        for fw in FRAMEWORK_ORDER:
            col_w[fw] = max(len(FRAMEWORK_LABELS[fw]), 7)
            if fw in schemas:
                for _, ext in fields:
                    col_w[fw] = max(col_w[fw], min(len(_fmt(ext(schemas[fw]))), 12))

        # top
        print("┌─" + "─"*label_w + "─" + "".join("┬─" + "─"*col_w[f] + "─" for f in FRAMEWORK_ORDER) + "┐")
        print("│ " + "Field".ljust(label_w) + " " + "".join("│ " + FRAMEWORK_LABELS[f].ljust(col_w[f]) + " " for f in FRAMEWORK_ORDER) + "│")
        print("├─" + "─"*label_w + "─" + "".join("┼─" + "─"*col_w[f] + "─" for f in FRAMEWORK_ORDER) + "┤")
        for fname, ext in fields:
            row = "│ " + fname.ljust(label_w) + " "
            for fw in FRAMEWORK_ORDER:
                v = _trunc(_fmt(ext(schemas[fw])), col_w[fw]) if fw in schemas else "-"
                row += "│ " + v.ljust(col_w[fw]) + " "
            print(row + "│")
        print("└─" + "─"*label_w + "─" + "".join("┴─" + "─"*col_w[f] + "─" for f in FRAMEWORK_ORDER) + "┘")
        print(tagline)


# ========================================================================
# Main
# ========================================================================

def main():
    parser = argparse.ArgumentParser(description="Unified 6-framework telemetry demo")
    parser.add_argument("--verbose", action="store_true", help="Show per-event detail")
    parser.add_argument("--output", default=None, help="JSONL output path (default: temp file)")
    args = parser.parse_args()

    print("╔═══════════════════════════════════════════════════════════╗")
    print("║  UNIFIED TELEMETRY DEMO — 6 Frameworks, 1 Schema        ║")
    print("╚═══════════════════════════════════════════════════════════╝")

    # Pre-inject stubs that must be available before adapter imports
    _ensure_openai_stubs()
    _ensure_langchain_stubs()
    _ensure_otel_stubs()

    runners = [
        ("ADK",        run_adk_session),
        ("OpenAI",     run_openai_session),
        ("Claude",     run_claude_session),
        ("LangGraph",  run_langgraph_session),
        ("Pydantic AI",run_pydantic_ai_session),
        ("Copilot",    run_copilot_session),
    ]

    _all_events.clear()
    for label, runner in runners:
        try:
            events = runner(verbose=args.verbose)
            _all_events.extend(events)
            print(f"  → {len(events)} events captured via real {label} adapter")
        except Exception as e:
            print(f"  ✗ {label} FAILED: {e}")

    # Write all events to JSONL
    output_path = args.output or os.path.join(tempfile.gettempdir(), "unified_demo_events.jsonl")
    with open(output_path, "w") as f:
        for ev in _all_events:
            schema = _transform(ev)
            f.write(json.dumps(schema, default=str, separators=(",", ":")) + "\n")
    print(f"\n{'─' * 60}")
    print(f"Wrote {len(_all_events)} events to {output_path}")

    # Normalization table
    print_normalization_table(_all_events)

    # Summary
    fw_counts = {}
    for e in _all_events:
        fw_counts[e.framework] = fw_counts.get(e.framework, 0) + 1
    print(f"\n{'─' * 60}")
    print("Events per framework:")
    for fw in FRAMEWORK_ORDER:
        count = fw_counts.get(fw, 0)
        bar = "█" * min(count, 30)
        print(f"  {FRAMEWORK_LABELS[fw]:>11}  {bar} {count}")
    print(f"\nTotal: {len(_all_events)} events, {len(fw_counts)} frameworks, 1 unified schema")
    print(f"JSONL: {output_path}")
    print(f"\nEvery framework → same field names → same SIEM rules → one pane of glass.")


if __name__ == "__main__":
    main()
