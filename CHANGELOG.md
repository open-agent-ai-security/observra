<!--
  Copyright 2026 Exabeam, Inc.
  SPDX-License-Identifier: Apache-2.0
-->

# Changelog

All notable changes to observra are recorded here. The format is based on
[Keep a Changelog](https://keepachangelog.com/), and this project adheres to
[Semantic Versioning](https://semver.org/). See [docs/RELEASING.md](docs/RELEASING.md)
for how releases are cut.

## [Unreleased]

## [1.1.0] — 2026-08-05

### Added
- Public `emit()` and `initialize_session()` APIs for custom hosts (PR #89).
- SQLite storage backend with WAL mode, queries, and row pruning (PR #105).
- Terminal dashboard TUI — `python -m observra.tui --db <path>` (PR #111).
- LiteLLM adapter — 100+ LLM providers via single integration (PR #112).
- Getting-started guides for LiteLLM, custom frameworks, SQLite, and TUI.

### Fixed
- Claude adapter: seed session_id in `get_hook_options()` (PR #99).
- Claude adapter: add `agent_name` attribution to all events (PR #99).
- LangChain adapter: handle `serialized=None` from LangGraph (PR #82).
- JSONL backend: pass all kwargs from `initialize()` (PR #84).
- `initialize()` warns on misrouted kwargs instead of silently dropping (PR #87).

## [1.0.6] — 2026-06-29

## [1.0.5] — 2026-06-27

### Added
- Release tooling: the version is single-sourced from `observra.__version__`
  (pyproject reads it dynamically), `scripts/bump_version.py` bumps it and rolls
  this changelog, the **Auto Release** workflow tags and cuts a GitHub Release on
  a version bump, and `docs/RELEASING.md` documents the flow.

### Changed
- `examples/langgraph_adapter.py` builds its graph lazily (`build_app()`) so the
  file imports for inspection without `langchain-openai` or an API key.

### Fixed
- The framework adapter examples listed event names the adapters never emit;
  corrected to the real `event_type`s (`tool_start`/`tool_end`,
  `agent_start`/`agent_end`, `session_start`/`session_end`, `user_message`,
  `agent_handoff`, …).
- `examples/basic_jsonl.py` crashed importing `get_session_cost` from the
  top-level package (it lives in `observra.core`).
- `examples/unified_demo.py` referenced a non-existent Copilot adapter and a
  self-injected OpenTelemetry stub that broke the ADK adapter; it now runs the
  five real frameworks and the stub only activates when OTel is genuinely absent.

### Removed
- Dead `docs/api/` and `CIM_SCHEMA_SPEC.md` documentation links (the latter
  repointed to `schema/cim_schema.toml`).

## [1.0.4] — 2026-06-25

### Changed
- Rewrote the Google ADK getting-started guide to show the real, runnable
  `create_plugin()` + `Runner` integration (the prior snippet captured nothing),
  with a model-auth prerequisite and a `capture_tool_data` note.
- Wired the framework adapter examples via `create_plugin()` so events actually
  reach the configured backend (constructing the adapter directly left it
  unconnected and silently dropped events).
- Aligned the README quickstart, landing page, and `docs/event-schema.md` with
  the real emitted output, and published getting-started guides for Claude,
  OpenAI, LangChain, and Pydantic AI to the docs site.
- Corrected examples and `production-deployment.md` that implied `initialize()`
  reads `ABA_TELEMETRY_*` environment variables (it does not) and documented the
  wrong MultiBackend / shutdown APIs.

### Added
- `examples/README.md` indexing every example with run instructions.
- `tests/unit/test_examples_smoke.py` guarding the documented ADK pattern and the
  shipped example files against regression.

### Fixed
- `get_stats()` raised `AttributeError` whenever a pipeline was active — it read
  non-existent `events_processed`/`errors` attributes on the worker instead of
  `_events_processed`/`_errors`.

### Removed
- Empty `examples/test_claude_interactive.py` stub.
- The dead `max_delegation_depth` parameter from the ADK plugin (it was accepted
  but ignored; the threshold is the fixed `MAX_DELEGATION_DEPTH`).

## [1.0.3] — 2026-06-23

### Changed
- Replaced the per-event `cim_version` field with a `schema` contract anchor
  (`observra:<major>.<minor>`), emitted by the OTel span and log backends.
  Consumers pin to the schema major and tolerate unknown fields.

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
