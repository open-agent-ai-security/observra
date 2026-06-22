<!--
  Copyright 2026 Exabeam, Inc.
  SPDX-License-Identifier: Apache-2.0
-->
# Architecture

## Overview

observra is a Python SDK that instruments AI agent frameworks to capture structured telemetry events. Events are normalized to a Common Information Model (CIM) schema and routed to configurable backends.

## Components

```
┌─────────────────────────────────────────────────┐
│                  Agent Code                     │
│  (ADK / Claude / OpenAI / LangGraph / Pydantic) │
└─────────────────────┬───────────────────────────┘
                      │ framework callbacks
                      ▼
┌─────────────────────────────────────────────────┐
│              Adapter Layer                      │
│  adapters/{adk,claude,openai,langchain,...}     │
└─────────────────────┬───────────────────────────┘
                      │ normalized events
                      ▼
┌─────────────────────────────────────────────────┐
│              Core Pipeline                      │
│  CIM normalization → dedup → redaction → cost   │
└─────────────────────┬───────────────────────────┘
                      │ enriched events
                      ▼
┌─────────────────────────────────────────────────┐
│              Backend Layer                      │
│  jsonl / webhook / otel / multi                 │
└─────────────────────────────────────────────────┘
```

## Design Principles

- Zero-config for common cases (JSONL backend, auto-detect framework)
- Framework adapters are optional extras — only import what you use
- All events conform to CIM schema before reaching backends
- Thread-safe, async-compatible event pipeline
