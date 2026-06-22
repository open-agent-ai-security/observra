<!--
  Copyright 2026 Exabeam, Inc.
  SPDX-License-Identifier: Apache-2.0
-->
# observra
**Framework-agnostic agent behavior analytics.**

[![License: Apache-2.0](https://img.shields.io/badge/license-Apache_2.0-blue.svg)](LICENSE.md)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)

Capture every meaningful agent action (token usage, tool calls, cost, errors) with structured context based on the Common Information Model (CIM).

Zero custom instrumentation per-agent. Answer "what happened, how much did it cost, and was it normal?" for any agent on any framework.

## Install

```bash
pip install observra
```

With framework extras:

```bash
pip install observra[adk]           # Google ADK
pip install observra[claude]        # Claude Agent SDK
pip install observra[openai-agents] # OpenAI Agents SDK
pip install observra[langchain]     # LangChain / LangGraph
pip install observra[pydantic-ai]   # Pydantic AI
```

With backend extras:

```bash
pip install observra[otel]          # OTel span + log export
```

Install everything:

```bash
pip install observra[all]
```

## Quick Start

```python
import observra
from observra import log

observra.initialize(backend="jsonl", path="telemetry.jsonl")
log.session_start(agent_name="my-agent")
log.model_response("gpt-4o", input_tokens=500, output_tokens=200)
log.session_end(agent_name="my-agent")
```

Sample output (one line per event in `telemetry.jsonl`):

```json
{"ts": "2025-01-15T10:23:45Z", "event_type": "model_response", "framework": "generic", "data": {"model": "gpt-4o", "in": 500, "out": 200, "cost_usd": 0.0035}}
```

## Supported Frameworks

| Framework | Install | Status | Captured Events |
|-----------|---------|--------|-----------------|
| [Google ADK](docs/getting-started/adk.md) | `[adk]` | Stable | LLM calls, tool calls, delegation depth, cost |
| [Claude SDK](docs/getting-started/claude.md) | `[claude]` | Stable | Tool calls, model responses, session cost |
| [OpenAI Agents SDK](docs/getting-started/openai.md) | `[openai-agents]` | Stable | Spans, tool calls, agent handoffs, cost |
| LangChain / LangGraph | `[langchain]` | Stable | Chain runs, tool calls, LLM calls, cost |
| Pydantic AI | `[pydantic-ai]` | Stable | Agent runs, tool calls, model calls |

## Backends

| Backend | Install | Description |
|---------|---------|-------------|
| JSONL | _(included)_ | Local JSON Lines file (default) |
| Webhook | _(included)_ | Generic HTTP webhook POST delivery |
| Multi | _(included)_ | Fan-out to multiple backends simultaneously |
| OTel Spans | `[otel]` | Export events as OTel spans via OTLP HTTP |
| OTel Logs | `[otel]` | Export events as OTel log records via OTLP HTTP |

### OTel Export (Dynatrace, Grafana, etc.)

```python
from observra.backends.otel import OTelExportBackend
from observra.backends.otel_log import OTelLogBackend
from observra.backends.multi import MultiBackend

# Spans only
span_backend = OTelExportBackend(
    endpoint="https://your-collector/v1/traces",
    headers={"Authorization": "Api-Token ..."},
    service_name="my-agent-svc",
)

# Logs only
log_backend = OTelLogBackend(
    endpoint="https://your-collector/v1/logs",
    headers={"Authorization": "Api-Token ..."},
    service_name="my-agent-svc",
)

# Both spans and logs
backend = MultiBackend([span_backend, log_backend])
```

## Key Features

- **Cost tracking** — per-session cost with model-specific pricing catalog and threshold alerts
- **PII redaction** — automatic secret/PII masking with configurable patterns
- **Non-blocking** — drop-oldest queue guarantees zero latency impact on the host agent
- **CIM-normalized** — structured events compatible with SIEM/analytics pipelines
- **Safe regex** — ReDoS-proof pattern matching via RE2 (optional: `[safe-regex]`)
- **Encryption at rest** — AES field-level encryption for sensitive telemetry (optional: `[encryption]`)
- **Prompt injection detection** — built-in heuristics for injection attempt classification
- **Observability** — `get_metrics()` / `get_stats()` for pipeline health introspection
- **Deduplication** — automatic event dedup across backends
- **Session context** — trace/span/session ID propagation with scoped contexts

## All Extras

| Extra | Dependencies |
|-------|-------------|
| `[adk]` | `google-adk>=1.0.0` |
| `[claude]` | `claude-agent-sdk>=0.1.37`, `tiktoken>=0.7.0` |
| `[openai-agents]` | `openai-agents>=0.9.0` |
| `[langchain]` | `langchain-core>=1.0.0`, `langgraph>=0.2.0` |
| `[pydantic-ai]` | `pydantic-ai<2.0.0`, `opentelemetry-sdk>=1.0.0` |
| `[otel]` | `opentelemetry-sdk>=1.0.0`, `opentelemetry-exporter-otlp-proto-http>=1.0.0` |
| `[exabeam]` | `requests>=2.32.0` |
| `[safe-regex]` | `google-re2>=1.1` |
| `[encryption]` | `cryptography>=41.0` |
| `[all]` | All of the above |

## Documentation

- [Getting Started](docs/getting-started/) — per-framework setup guides
- [API Reference](docs/api/) — public callables, config options, event examples
- [Event Schema](docs/event-schema.md) — CIM event contract
- [Architecture](docs/architecture.md) — system design overview
- [Compatibility](docs/COMPATIBILITY.md) — supported versions


## License

Apache 2.0 — see [LICENSE](LICENSE)
