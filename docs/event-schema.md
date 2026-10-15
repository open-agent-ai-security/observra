<!--
  Copyright 2026 Exabeam, Inc.
  SPDX-License-Identifier: Apache-2.0
-->
# Event Schema

The Common Information Model (CIM) defines the canonical event structure for all telemetry events emitted by observra.

## Schema Source

The single source of truth is [`schema/cim_schema.toml`](../schema/cim_schema.toml).

## Versioning

observra has two independently-versioned surfaces (see [STABILITY.md](../STABILITY.md)):

| Surface | Source | How it reaches a record |
|---------|--------|-------------------------|
| Library / package version | `__version__` (semver) | the `library_version` field on every emitted record |
| CIM / event-schema version | `CIM_VERSION` in `core/cim.py` (from `schema/cim_schema.toml`) | the `schema` anchor (`observra:<major>.<minor>`) on the OTel backends; on native JSONL/webhook records, inferred from `library_version` |

These move independently: a library patch release does not change the schema version, and a new optional CIM field bumps the schema minor without requiring a library major.

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
| `host` | string | no | Hostname of the emitting machine |
| `user` | string | no | OS user running the process |
| `os` | string | no | Operating system description |
| `arch` | string | no | CPU architecture (normalized) |
| `library_version` | string | no | observra package version |

## Serialization Formats

All backends serialize the same logical `TelemetryEvent` dataclass:

- **JSONL** (`backends/jsonl.py`): one agent-sensor record per line (`record_format="native"` writes `dataclasses.asdict(event)` instead)
- **Webhook** (`backends/webhook.py`): agent-sensor record as the HTTP POST body (same `record_format` switch)
- **OTel Spans** (`backends/otel.py`): Maps event fields to OpenTelemetry span attributes
- **OTel Logs** (`backends/otel_log.py`): Maps event fields to OTel LogRecord body; `body_schema="sensor"` uses the agent-sensor record without prompt/response text
- **Exabeam** (`senders/exabeam.py`): Curated field subset via `build_payload()` / `build_raw_payload()`

The agent-sensor record (`core/sensor_record.py`) has the same field names as agent-sensor's `SimplifiedEvent`, so one SIEM parser reads output from both. Its top level is `ts`, `session`, `type`, `model`, `tool`, `agent`, `in`, `out`, `cache_read`, `cache_creation`, `stop`, `error`, `framework`, `host`, `user`, `os`, `arch`, `forwarder` and `schema`. Fields the sensor has no slot for (`event_id`, `trace_id`, `span_id`, `skill_name`) and the full session id (`session_key`) go under `data`.

The `schema` anchor (`observra:<major>.<minor>`) is on every agent-sensor record and on the OTel backends. Native `asdict()` records do not carry it; infer the schema version from `library_version`. See [STABILITY.md](../STABILITY.md) for the consumer contract.

## Event Types

See [`schema/cim_schema.toml`](../schema/cim_schema.toml) for the full catalog of event types, actions, and classification rules.
