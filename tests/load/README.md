<!--
  Copyright 2026 Exabeam, Inc.
  SPDX-License-Identifier: Apache-2.0
-->
# Load / Soak Test Harness

Phase 34 responsibility.

Purpose: Exercise both Python SDK and Rust forwarder under sustained load.
Minimum requirements (from REQUIREMENTS.md TEST-01):
- 1-hour soak test
- Memory profiling at intervals
- Monotonicity check: no event loss, no duplicate IDs

Scaffolded in Phase 28 so downstream phases have a landing directory.
