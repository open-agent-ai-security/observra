<!--
  Copyright 2026 Exabeam, Inc.
  SPDX-License-Identifier: Apache-2.0
-->

# observra Stability Contract

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
- **Event / CIM schema** carries its own version. On the production (OTel) path it
  is emitted on each record as `schema: observra:<MAJOR>.<MINOR>`; on the native
  `jsonl`/`webhook` dev/debug backends it is inferred from `library_version` (see
  [Output formats](#output-formats)). **Downstream consumers should pin to a schema
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
  field's type or required-ness. (Retiring an enum value — e.g. a `FinishReason`
  — is a schema MAJOR, not a minor.)

**Consumer rule:** pin to the schema **MAJOR** (e.g. `observra:1.*`) and tolerate
fields and enum values you don't recognize in your own parsing.

## Output formats

One logical event is serialized by several backends. **The schema rules above
apply to every serialization.** The self-describing `schema` anchor is carried by
the production (OTel) backends; the native dev/debug backends do not stamp it:

| Backend | Format | Schema version on the record |
|---|---|---|
| `otel` | OTel spans, `gen_ai.*` semantic conventions | `observra.schema` span attribute = `observra:<MAJOR>.<MINOR>` |
| `otel_log` | OTel log records, `gen_ai.*` semantic conventions | `schema` field = `observra:<MAJOR>.<MINOR>` |
| `jsonl` | native flat JSON (one object per line) | not stamped — local dev/debug; infer from `library_version` |
| `webhook` | native JSON POST body (same as JSONL) | not stamped — local dev/debug; infer from `library_version` |

This split is intentional: the production path (OTel → Dynatrace / Grafana / SIEM)
self-identifies its schema version, while `jsonl` and `webhook` are local
dev/debug backends where the schema can be inferred from the package
`library_version` carried on every record. The same schema-version convention is
shared with `agent-sensor`, so consumers see a consistent contract across both.

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

## Notes

- **Schema stamping is OTel-only, by design.** The `schema` anchor is carried by
  the production OTel backends; `jsonl` and `webhook` are local dev/debug backends
  and do not stamp it — infer the schema from `library_version` there. See
  [Output formats](#output-formats).
- **Cross-repo convention.** The event/CIM schema version is a shared convention:
  `agent-sensor` uses the same `schema_version` scheme, so downstream consumers see
  one consistent contract across both projects.
- **Follow-up (#10 / #14):** `docs/event-schema.md` should be reconciled with the
  actual emitted records so "the format" is documented once, accurately, across all
  serializations.

## Deprecation policy

API deprecations are marked with `@deprecated(removal_version=…)` (`core/deprecation.py`),
surfaced to callers at runtime, and introspected in CI. A symbol deprecated in a
minor is supported for at least the remainder of that package MAJOR and removed no
earlier than the next MAJOR. Schema fields/enums follow the schema rules above:
additive in a minor, removal only at a schema MAJOR.
