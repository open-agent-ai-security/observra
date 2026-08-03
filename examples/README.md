<!--
  Copyright 2026 Exabeam, Inc.
  SPDX-License-Identifier: Apache-2.0
-->
# observra examples

Runnable examples for instrumenting agents with observra. Each file has a
module docstring with a `Usage:` line and is self-contained.

## Setup

```bash
pip install observra                 # core (JSONL + webhook backends included)
pip install "observra[adk]"          # add a framework extra for adapter examples
```

The adapter examples additionally need the matching framework SDK and model
credentials (e.g. `GOOGLE_API_KEY`, `OPENAI_API_KEY`). observra observes your
agent; it does not supply model access.

## The two-step integration

Every framework follows the same shape:

```python
from observra import initialize, create_plugin

initialize(backend="jsonl", path="telemetry.jsonl")  # 1. choose a backend
plugin = create_plugin(framework="adk")  # 2. build the adapter
# 3. attach `plugin` to your framework (Runner/hooks/callbacks)
```

`initialize()` configures the global pipeline; `create_plugin()` returns the
framework adapter. They are separate calls on purpose — `initialize()` alone
captures nothing until the adapter is attached. observra does **not** read
telemetry settings from environment variables (the one exception is
`ABA_TELEMETRY_KEY` for encryption-at-rest); pass configuration as arguments.

## Core examples (no framework SDK required)

| Example | Shows | Run |
|---------|-------|-----|
| [`basic_jsonl.py`](basic_jsonl.py) | Simplest integration: events to a JSONL file | `python examples/basic_jsonl.py` |
| [`cost_tracking.py`](cost_tracking.py) | Per-session cost with threshold alerts | `python examples/cost_tracking.py` |
| [`custom_redaction.py`](custom_redaction.py) | Add org-specific PII/secret redaction patterns | `python examples/custom_redaction.py` |
| [`detection_signals.py`](detection_signals.py) | Error classification, injection detection, depth limits | `python examples/detection_signals.py` |
| [`logging_bridge.py`](logging_bridge.py) | Capture stdlib `logging` calls as telemetry | `python examples/logging_bridge.py` |
| [`unified_demo.py`](unified_demo.py) | Same events/fields across all adapters (mocked sessions) | `python examples/unified_demo.py` |

These write a `*.jsonl` file in the working directory. Inspect with:

```bash
cat telemetry.jsonl | python -m json.tool
```

## Framework adapter examples

Each shows a BEFORE/AFTER of adding telemetry to an existing agent. They
require the framework extra and model credentials.

| Example | Framework | Install | Notes |
|---------|-----------|---------|-------|
| [`sample_agent/`](sample_agent/) | Google ADK (`adk web`) | `observra[adk]` | Full agent; enable with `OBSERVRA_DEMO_TELEMETRY=1` (see below) |
| [`add_telemetry_to_agent.py`](add_telemetry_to_agent.py) | Google ADK (`Runner`) | `observra[adk]` | Programmatic Runner integration |
| [`claude_adapter.py`](claude_adapter.py) | Claude Agent SDK | `observra[claude]` | |
| [`openai_adapter.py`](openai_adapter.py) | OpenAI Agents SDK | `observra[openai-agents]` | |
| [`langgraph_adapter.py`](langgraph_adapter.py) | LangGraph / LangChain | `observra[langchain]` | |
| [`pydantic_ai_adapter.py`](pydantic_ai_adapter.py) | Pydantic AI | `observra[pydantic-ai]` | |

### ADK: two integration styles

ADK appears twice because there are two ways to register the plugin:

- **`add_telemetry_to_agent.py`** — you build your own `Runner`, so you pass
  `plugins=[plugin]` to it directly.
- **`sample_agent/`** — you launch with `adk web`, so the plugin is exposed at
  module level and passed via `--extra_plugins`:

  ```bash
  cd examples
  export OBSERVRA_DEMO_TELEMETRY=1
  adk web . --extra_plugins sample_agent.agent.telemetry_plugin
  ```

See [`docs/getting-started/adk.md`](../docs/getting-started/adk.md) for the
full walkthrough.

## Other files

- [`siem_parser.json`](siem_parser.json) — sample SIEM field-extraction parser
  for the CIM-normalized event schema.
