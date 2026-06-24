<!--
  Copyright 2026 Exabeam, Inc.
  SPDX-License-Identifier: Apache-2.0
-->

# observra Stability Contract

> **Status: DRAFT for review.** This is a first cut, authored after an internal
> discussion, to give the team something concrete to react to. Items marked
> _(for review)_ are not yet locked, and one part of the contract is not yet
> fully implemented (see [Current status & known gaps](#current-status--known-gaps)).
> Nothing here is binding until this document is merged.

From **1.0**, observra follows semantic versioning across **two independently
versioned surfaces**, because observra is two things at once:

- a **library you import** — break its API and *contributors' code* stops working; and
- a **producer of an event/log stream** other systems parse — break its format and
  *downstream SIEM/analytics pipelines* silently misparse data already in flight.

These fail differently and evolve independently, so each has its own version line:

| Surface | Version line | Source of truth | Current value |
|---|---|---|---|
| **Library / API** | package `__version__` (semver) | `src/observra/__init__.py` | `1.0.3` |
| **Event / CIM schema** | `schema` anchor `observra:<MAJOR>.<MINOR>` | `schema/cim_schema.toml` `[meta] version` → `CIM_VERSION` | `observra:1.0` |

**The key principle: an API major is not a schema major.** A pure library refactor
bumps the package, not the schema. A new optional log field bumps the schema
minor, not the API. **Anything not listed as Stable below is explicitly Evolving
and may change in a minor release.**

## Compatibility policy

- **Library / API** is versioned `MAJOR.MINOR.PATCH`. A breaking change to a Stable
  API surface (below) requires a package **MAJOR**. Deprecations get one minor's
  notice via `@deprecated` (machinery in `core/deprecation.py`, with CI
  introspection) and are removed no earlier than the next **MAJOR**.
- **Event / CIM schema** carries its own version, emitted on every record as
  `schema: observra:<MAJOR>.<MINOR>`. **Downstream consumers should pin to a schema
  MAJOR and tolerate unknown fields and unknown enum values**, since both may be
  added in a schema MINOR.
- **Security fixes** ship in the latest released line as PATCH releases.

## Stable — Library / API

Guaranteed for the life of the `1.x` **package** line. A breaking change requires
the next package MAJOR.

1. **Public callables and their signatures**, as exported from `observra/__init__.py`
   `__all__`: `initialize`, `create_plugin`, `create_logging_handler`, `get_stats`,
   `get_metrics`, `observability`, plus the types `TelemetryEvent` and
   `StorageBackend`.
2. **Backend name strings** accepted by `initialize(backend=...)`:
   `jsonl`, `webhook`, `otel`, `otel_log`, `multi`, `exabeam`.
3. **Framework name strings** accepted by `create_plugin(framework=...)`:
   `adk`, `claude`, `openai`, `langchain`, `pydantic-ai`.
4. **The public shape of `TelemetryEvent` and `StorageBackend`**, and **the keys
   returned by `get_stats()` and `get_metrics()`**.

## Stable — Event / CIM schema

Governed by the schema version (`CIM_VERSION`, currently `1.0`), **not** the package
version. The single source of truth is `schema/cim_schema.toml`. Within a schema
**MAJOR**, the published event stream is a stable contract:

**Frozen within a schema MAJOR**
- The **event envelope** — its required top-level fields.
- The **`event_type` vocabulary**.
- The **CIM enumerations**: `Action`, `Vendor`, `ActionResult`, `FinishReason`.
- The **canonical `data` keys** for each event type.

**Additive in a schema MINOR**
- New event types.
- New **optional** `data` keys.
- New enum values.

**Requires a schema MAJOR**
- Removing or renaming any field, enum value, or event type, or changing a
  field's type or required-ness. _(for review: confirm that retiring an enum
  value — e.g. a `FinishReason` — is a schema MAJOR, not a minor.)_

**Consumer rule:** pin to the schema **MAJOR** (e.g. `observra:1.*`) and tolerate
fields and enum values you don't recognize in your own parsing.

## Output formats

One logical event is serialized by several backends. **The intent is that every
serialization is gated by the single schema version above** _(for review)_:

| Backend | Format | Schema anchor |
|---|---|---|
| `jsonl` | native flat JSON (one object per line) | `schema` field — _pending, see gaps_ |
| `webhook` | native JSON POST body (same as JSONL) | `schema` field — _pending, see gaps_ |
| `otel` | OTel spans, `gen_ai.*` semantic conventions | `observra.schema` span attribute |
| `otel_log` | OTel log records, `gen_ai.*` semantic conventions | `schema` field |

The OTel attribute/field mapping (`gen_ai.*`, `observra.*`) is its **own
sub-contract**, documented in `docs/production-deployment.md`. OTel backends are
intentionally lossy (only mapped fields are exported); use `multi` with a native
leg if you need the full `data` payload downstream.

## Evolving — not covered by either contract

Do **not** build hard dependencies on these; they may change in any minor release:

- Everything under `core/` and all adapter internals — anything not exported in
  `__all__`.
- The exact byte layout / field ordering of a given backend's output.
- Host-context fields (`host`, `user`, `os`, `arch`, `library_version`) — these are
  best-effort metadata, may be absent, and are not part of the frozen envelope.
- The set of supported frameworks/backends *growing* (additions are not breaking);
  only the listed name strings are frozen.
- Model-derived values (token counts, computed `cost_usd`, latencies) — these are
  observations, not a stability surface.

## Current status & known gaps

This draft describes the **intended** contract. Two items are not yet true of the
code and should land before this document is considered binding:

1. **Schema stamping is OTel-only.** The `schema: observra:<…>` anchor is currently
   emitted by the OTel backends (`otel`, `otel_log`) but **not** by the default
   `jsonl` or `webhook` serializations — those records carry `library_version`
   (the *package* version) but no schema version. Until the anchor is stamped into
   the native serialization, the default stream does not self-describe its schema.
   Tracked in issue #10.
2. **Doc/output reconciliation.** `docs/event-schema.md` should be reconciled with
   the actual emitted records so "the format" is described once, accurately, across
   all serializations.

## Deprecation policy

API deprecations are marked with `@deprecated(removal_version=…)` (`core/deprecation.py`),
surfaced to callers at runtime, and introspected in CI. A symbol deprecated in a
minor is supported for at least the remainder of that package MAJOR and removed no
earlier than the next MAJOR. Schema fields/enums follow the schema rules above:
additive in a minor, removal only at a schema MAJOR.
