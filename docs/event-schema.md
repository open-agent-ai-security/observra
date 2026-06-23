<!--
  Copyright 2026 Exabeam, Inc.
  SPDX-License-Identifier: Apache-2.0
-->
# Event Schema

The Common Information Model (CIM) defines the canonical event structure for all telemetry events emitted by observra.

## Schema Source

The single source of truth is [`schema/cim_schema.toml`](../schema/cim_schema.toml).

## Versioning

Events carry two independent version identifiers:

| Field | Source | Purpose |
|-------|--------|---------|
| `library_version` | Package `__version__` (semver) | Identifies the observra release that emitted the event |
| `cim_version` | `CIM_VERSION` in `core/cim.py` | Identifies which CIM schema the event conforms to |

These move independently. A library patch release does not change the schema version; a new optional CIM field bumps the schema minor without requiring a library major.

## Event Envelope

Every event serialized by observra contains:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `event_id` | string (ULID) | yes | Unique event identifier |
| `timestamp` | float (Unix epoch) | yes | Event timestamp |
| `trace_id` | string (ULID) | yes | Distributed trace identifier |
| `session_id` | string (ULID) | yes | Session identifier |
| `span_id` | string (ULID) | yes | Current span identifier |
| `event_type` | string | yes | One of the defined CIM event types |
| `framework` | string | no | Source framework (adk, claude, openai, langgraph, pydantic-ai, mcp) |
| `agent_name` | string | no | Name of the agent |
| `tool_name` | string | no | Name of the tool being called |
| `model_name` | string | no | Name of the model being used |
| `skill_name` | string | no | MCP skill identifier |
| `data` | object | no | Event-specific payload (CIM fields, detection annotations) |
| `cim_version` | string | yes | CIM schema version (e.g. "1.0") |
| `host` | string | no | Hostname of the emitting machine |
| `user` | string | no | OS user running the process |
| `os` | string | no | Operating system description |
| `arch` | string | no | CPU architecture (normalized) |
| `library_version` | string | no | observra package version |

## Serialization Formats

All backends serialize the same logical `TelemetryEvent` dataclass:

- **JSONL** (`backends/jsonl.py`): `dataclasses.asdict(event)` → one JSON object per line
- **Webhook** (`backends/webhook.py`): `dataclasses.asdict(event)` → HTTP POST body
- **OTel Spans** (`backends/otel.py`): Maps event fields to OpenTelemetry span attributes
- **OTel Logs** (`backends/otel_log.py`): Maps event fields to OTel LogRecord body
- **Exabeam** (`senders/exabeam.py`): Curated field subset via `build_payload()` / `build_raw_payload()`

The `cim_version` field is present in all serializations that use `asdict()` (JSONL, webhook). The Exabeam sender includes it only if explicitly added to its canonical field set.

## Event Types

See [CIM Schema Spec](CIM_SCHEMA_SPEC.md) for the full catalog of event types, actions, and classification rules.
