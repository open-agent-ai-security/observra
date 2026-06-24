<!--
  Copyright 2026 Exabeam, Inc.
  SPDX-License-Identifier: Apache-2.0
-->
# Production Deployment Guide

How to configure `observra` for production agent workloads running on
cloud infrastructure (Cloud Run, Kubernetes, VMs).

---

## Quick Start — OTel Backend (Recommended)

For most production deployments, the OTel backend is the right choice.
It pushes telemetry via OTLP HTTP to any compatible observability platform
(Dynatrace, Datadog, Grafana, Honeycomb, New Relic, etc.).

```python
import observra

observra.initialize(
    backend="otel_log",
    endpoint="https://your-platform.example.com/api/v2/otlp/v1/logs",
    headers={"Authorization": "Api-Token YOUR_TOKEN"},
    service_name="my-agent-svc",
)

plugin = observra.create_plugin()
# Pass plugin to your framework runner
```

**Why OTel for production:**
- Works from ephemeral containers (no filesystem persistence needed)
- Vendor-neutral — switch platforms with one config change
- Follows `gen_ai.*` OpenTelemetry semantic conventions
- Auto-indexed attributes for fast querying

---

## Configuration Patterns

### 1. OTel Logs — Single Observability Platform

Best for: teams with one observability platform (DT, Datadog, Grafana).

```python
import observra

observra.initialize(
    backend="otel_log",
    endpoint="https://your-instance.live.dynatrace.com/api/v2/otlp/v1/logs",
    headers={"Authorization": "Api-Token dt0c01.XXXX"},
    service_name="my-agent-svc",
)
```

**Using the standard OTel environment variables:**

observra's `initialize()` does not read telemetry settings from the
environment, so the backend must be selected in code. The underlying OTLP
exporter, however, honors the standard OpenTelemetry environment variables —
so you can keep endpoint, headers, and service name out of your source:

```bash
export OTEL_EXPORTER_OTLP_LOGS_ENDPOINT=https://your-instance.live.dynatrace.com/api/v2/otlp/v1/logs
export OTEL_EXPORTER_OTLP_HEADERS="Authorization=Api-Token dt0c01.XXXX"
```

```python
import observra

# The OTLP exporter reads endpoint + headers from the OTEL_* env vars above.
# service_name is set in code (defaults to "observra" if omitted).
observra.initialize(backend="otel_log", service_name="my-agent-svc")
```

### 2. OTel Spans — Distributed Tracing

Best for: multi-service architectures where you need trace correlation.

```python
import observra

observra.initialize(
    backend="otel",
    endpoint="https://your-instance.live.dynatrace.com/api/v2/otlp/v1/traces",
    headers={"Authorization": "Api-Token dt0c01.XXXX"},
    service_name="my-agent-svc",
)
```

### 3. MultiBackend — Observability + Local Debug

Best for: teams that need both real-time observability AND a local audit trail.

```python
from observra.backends.otel_log import OTelLogBackend
from observra.backends.jsonl import JSONLBackend
from observra.backends.multi import MultiBackend

import observra

# OTel leg: real-time dashboards and alerting
otel = OTelLogBackend(
    endpoint="https://your-instance.live.dynatrace.com/api/v2/otlp/v1/logs",
    headers={"Authorization": "Api-Token dt0c01.XXXX"},
    service_name="my-agent-svc",
)

# JSONL leg: local debugging and compliance audits
local = JSONLBackend(path="/data/telemetry.jsonl")

multi = MultiBackend([otel, local])

observra.initialize(backend=multi)
```

### 4. MultiBackend — OTel + Webhook (SIEM forwarding)

Best for: teams that need both observability push AND SIEM ingestion via webhook.

```python
from observra.backends.otel_log import OTelLogBackend
from observra.backends.webhook import WebhookBackend
from observra.backends.multi import MultiBackend

import observra

otel = OTelLogBackend(
    endpoint="https://your-instance.live.dynatrace.com/api/v2/otlp/v1/logs",
    headers={"Authorization": "Api-Token dt0c01.XXXX"},
    service_name="my-agent-svc",
)

# Webhook for SIEM ingestion
siem = WebhookBackend(url="https://your-siem/api/v1/events")

multi = MultiBackend([otel, siem])

observra.initialize(backend=multi)
```

### 5. stdout/Cloud Logging (GCP-native path)

Best for: GCP deployments where Cloud Logging is already integrated with
your observability platform (e.g., DT GCP integration auto-ingests).

```python
import observra

observra.initialize(
    backend="jsonl",
    path="/dev/stdout",
)
```

> **Note:** This writes the native `TelemetryEvent` schema as JSON lines to
> stdout. Cloud Run captures stdout as Cloud Logging entries. Your platform's
> GCP integration must be configured to ingest these logs. The event JSON lands
> in the `content` field as a string — your log processing pipeline must parse it.

---

## Backend Selection Guide

| Deployment | Recommended Backend | Why |
|------------|-------------------|-----|
| Cloud Run / serverless | `otel_log` | No filesystem; direct push |
| Kubernetes (GKE, EKS) | `otel_log` or `multi` | Push to platform; optional local JSONL on PV |
| VM / long-running | `multi` (otel + jsonl) | Push + local audit trail |
| GCP-native stack | `otel_log` or `jsonl` to stdout | Leverage Cloud Logging integrations |
| Multi-consumer (observability + SIEM) | `multi` (otel + webhook) | Each consumer gets its ideal format |
| Air-gapped / on-prem | `jsonl` | No external connectivity needed |

---

## Schema Differences by Backend

All backends receive the same `TelemetryEvent` dataclass. The serialized
output differs:

| Backend | Schema Format | Key Characteristics |
|---------|--------------|---------------------|
| `jsonl` | Native flat JSON | Full `data{}` dict preserved, `event_type`, `model_name`, `tool_name` as top-level keys |
| `webhook` | Native JSON POST body | Same schema as JSONL, delivered via HTTP |
| `otel` (spans) | OTel semantic conventions | `gen_ai.*` attributes, flat, strings |
| `otel_log` (logs) | OTel semantic conventions | `gen_ai.*` attributes, flat, strings |

**OTel backends remap fields to semantic conventions:**

```
Native → OTel
──────────────────────────────────────────────────
event_type          → observra.event_type
model_name          → gen_ai.request.model
tool_name           → gen_ai.tool.name
agent_name          → gen_ai.agent.name
session_id          → observra.session_id
data.input_tokens   → gen_ai.usage.input_tokens (string)
data.output_tokens  → gen_ai.usage.output_tokens (string)
data.cost_usd       → observra.cost_usd (string)
data.error_type     → error.type
framework           → observra.framework
```

**OTel backends are lossy:** only explicitly mapped fields from `data{}` are
exported as attributes. The full `data` dict is not preserved. If you need
the complete event payload downstream, use `multi` with a native backend leg.

---

## Platform-Specific Examples

### Dynatrace

```python
# OTel Logs (recommended)
observra.initialize(
    backend="otel_log",
    endpoint="https://{env-id}.live.dynatrace.com/api/v2/otlp/v1/logs",
    headers={"Authorization": "Api-Token dt0c01.XXXXX"},
    service_name="my-agent-svc",
)

# OTel Spans (if you need trace waterfall view)
observra.initialize(
    backend="otel",
    endpoint="https://{env-id}.live.dynatrace.com/api/v2/otlp/v1/traces",
    headers={"Authorization": "Api-Token dt0c01.XXXXX"},
    service_name="my-agent-svc",
)
```

### Datadog

```python
observra.initialize(
    backend="otel_log",
    endpoint="https://http-intake.logs.datadoghq.com/api/v2/otlp/v1/logs",
    headers={"DD-API-KEY": "your-api-key"},
    service_name="my-agent-svc",
)
```

### Grafana Cloud (Loki via OTLP)

```python
observra.initialize(
    backend="otel_log",
    endpoint="https://otlp-gateway-prod-us-east-0.grafana.net/otlp/v1/logs",
    headers={"Authorization": "Basic BASE64_ENCODED_USER:TOKEN"},
    service_name="my-agent-svc",
)
```

### Honeycomb

```python
observra.initialize(
    backend="otel",
    endpoint="https://api.honeycomb.io/v1/traces",
    headers={"x-honeycomb-team": "your-api-key"},
    service_name="my-agent-svc",
)
```

### Self-hosted OpenTelemetry Collector

```python
observra.initialize(
    backend="otel_log",
    endpoint="http://otel-collector.monitoring:4318/v1/logs",
    service_name="my-agent-svc",
)
```

---

## Production Checklist

- [ ] **Use environment variables for secrets** — never hardcode API tokens
- [ ] **Set `service_name`** — identifies your agent in multi-service environments
- [ ] **Configure cost thresholds** — get alerted on runaway LLM spend
- [ ] **Test with `backend="jsonl"` first** — verify events are captured before adding OTel
- [ ] **Use MultiBackend for dual-consumer** — don't force one schema on both observability and SIEM
- [ ] **Handle graceful shutdown** — call `observra.shutdown()` or use atexit hooks to flush buffered events
- [ ] **Set appropriate batch sizes** — larger batches reduce network calls but increase data-loss window on crash

---

## Graceful Shutdown

OTel backends use `BatchLogRecordProcessor` / `BatchSpanProcessor` which buffer
events. Ensure they flush on container shutdown:

```python
import atexit
import observra

observra.initialize(backend="otel_log", ...)

# Flush on shutdown (Cloud Run SIGTERM, K8s preStop)
atexit.register(observra.shutdown)
```

For frameworks with lifecycle hooks (FastAPI, Flask):

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    observra.shutdown()

app = FastAPI(lifespan=lifespan)
```

---

## Security Considerations

- **Redaction is on by default** — API keys, tokens, and common secret patterns
  are scrubbed from event payloads before they reach any backend
- **Add custom redaction patterns** for org-specific secrets:
  ```python
  observra.initialize(
      backend="otel_log",
      custom_patterns=[
          (r"sk-[a-zA-Z0-9]{48}", "OPENAI_KEY"),
          (r"ACME_TOKEN_[A-Z0-9]+", "ACME_TOKEN"),
      ],
  )
  ```
- **Encryption at rest** — JSONL backend supports optional AES encryption:
  ```python
  observra.initialize(
      backend="jsonl",
      path="telemetry.jsonl",
      encryption_key=os.environ["TELEMETRY_ENCRYPTION_KEY"].encode(),
  )
  ```
- **Never log prompts/responses in production** unless you have explicit consent
  and data residency compliance. The library redacts by default but scrub
  carefully when compliance is a concern.

---

## Monitoring the Telemetry Pipeline

Use the self-observability API to monitor the health of the telemetry pipeline
itself:

```python
from observra import observability

metrics = observability.get_metrics()
# {
#   "drop_count": 0,           # events lost to backpressure
#   "queue_depth": 3,          # pending events in buffer
#   "write_latency_p99": 0.02, # 99th percentile write latency (seconds)
#   "backend_write_success": 1547,
#   "backend_write_failure": 0,
# }
```

Expose these via your `/health` or `/metrics` endpoint to alert on pipeline issues.
