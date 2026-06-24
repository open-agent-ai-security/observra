<!--
  Copyright 2026 Exabeam, Inc.
  SPDX-License-Identifier: Apache-2.0
-->

# Changelog

All notable changes to observra are recorded here. The format is based on
[Keep a Changelog](https://keepachangelog.com/), and this project adheres to
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Fixed
- `get_stats()` raised `AttributeError` whenever a pipeline was active — it read
  non-existent `events_processed`/`errors` attributes on the worker instead of
  `_events_processed`/`_errors`.

### Changed
- Rewrote the Google ADK getting-started guide to show the real, runnable
  `create_plugin()` + `Runner` integration (the prior snippet captured nothing),
  with a model-auth prerequisite and a `capture_tool_data` note.
- Corrected examples and `production-deployment.md` that implied `initialize()`
  reads `ABA_TELEMETRY_*` environment variables; it does not. The `sample_agent`
  example now wires telemetry via its own `OBSERVRA_DEMO_TELEMETRY` flag and
  passes `capture_tool_data` to `create_plugin()` (not `initialize()`).

### Added
- `examples/README.md` indexing every example with run instructions.
- `tests/unit/test_examples_smoke.py` guarding the documented ADK pattern and
  the shipped example files against regression.

### Removed
- Empty `examples/test_claude_interactive.py` stub.

## [1.0.1] — 2026-06-18

### Added
- Public API in `observra/__init__.py`: `initialize()`, `create_plugin()`,
  `create_logging_handler()`, `get_stats()`, and `get_metrics()`.
- Web analytics on the project site (GoatCounter + Cloudflare, with A/B support).
- `readme` field in `pyproject.toml` for the PyPI project description.

### Changed
- Added Exabeam as the package author.
- Refactored the publish workflow to use input-based target selection.
- Removed tests for unimplemented features.

## [1.0.0] — 2026-06-16

### Added
- Initial release: framework-agnostic agent behavior analytics with
  CIM-normalized telemetry.
- Framework adapters: Google ADK, Claude Agent SDK, OpenAI Agents SDK,
  LangChain / LangGraph, and Pydantic AI.
- Backends: JSONL, webhook, OTel spans, OTel logs, multi (fan-out), and Exabeam.
- Cost tracking, PII redaction, prompt-injection detection, deduplication,
  field-level encryption at rest, and pipeline observability.
