<!--
  Copyright 2026 Exabeam, Inc.
  SPDX-License-Identifier: Apache-2.0
-->
# Event Schema

The Common Information Model (CIM) defines the canonical event structure for all telemetry events emitted by observra.

## Schema Source

The single source of truth is [`schema/cim_schema.toml`](../schema/cim_schema.toml).

## Event Structure

Every event contains:

| Field | Type | Description |
|-------|------|-------------|
| `ts` | ISO 8601 string | Event timestamp |
| `event_type` | string | One of the defined CIM event types |
| `framework` | string | Source framework (adk, claude, openai, langchain, pydantic_ai) |
| `session_id` | string | Session identifier (ULID) |
| `data` | object | Event-specific payload |

## Event Types

See [CIM Schema Spec](CIM_SCHEMA_SPEC.md) for the full catalog of event types, actions, and classification rules.
