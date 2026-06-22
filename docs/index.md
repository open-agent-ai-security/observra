<!--
  Copyright 2026 Exabeam, Inc.
  SPDX-License-Identifier: Apache-2.0
-->
# Overview

**observra** is framework-agnostic agent behavior analytics. It captures every
meaningful agent action — token usage, tool calls, cost, errors — as
CIM-normalized telemetry, with zero custom instrumentation per agent. Answer
"what happened, how much did it cost, and was it normal?" for any agent on any
framework.

## Start here

- [Getting Started · ADK](getting-started/adk.md) — wire observra into a Google ADK agent
- [Architecture](architecture.md) — how the capture → queue → backend pipeline fits together
- [Event Schema](event-schema.md) — the Common Information Model (CIM) event contract
- [Production Deployment](production-deployment.md) — backends, OTel export, and operational guidance
- [Compatibility](COMPATIBILITY.md) — supported Python and framework versions

## How it works

An adapter for your framework feeds events into a non-blocking, drop-oldest
queue; a background worker drains them to one or more backends (JSONL, webhook,
OTel spans/logs, or a SIEM). Events are normalized to a single CIM schema so the
same query works regardless of which framework produced them.

See the [Architecture](architecture.md) guide for the full picture.
