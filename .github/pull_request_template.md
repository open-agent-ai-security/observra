<!--
  Copyright 2026 Exabeam, Inc.
  SPDX-License-Identifier: Apache-2.0
-->

<!--
  Thanks for sending a PR to observra.

  Sign off your commits under the Developer Certificate of Origin
  (`git commit -s`). See CONTRIBUTING.md.
-->

## Summary

<!-- What does this PR change, and why? Link issues with `Closes #N` / `Refs #N`. -->

## Testing

<!-- How did you verify it?
  - `pytest -q` — paste the one-line result.
  - For adapter changes: which framework/version you exercised it against.
  - Docs-only: "n/a — docs only" is fine. -->

## Stability impact

<!-- REQUIRED — observra has two versioned contracts (see STABILITY.md): the
public API (everything exported in `__all__`, plus backend/framework name
strings) and the event/CIM schema (`schema/cim_schema.toml`), which downstream
SIEM/analytics pipelines parse.

  - Neither touched → write "None."
  - Touched         → say which contract, whether the change is additive or
                      breaking, and the version implication (API semver vs
                      schema MAJOR.MINOR). -->

## Notes for reviewers

<!-- Anything to look at first, design choices worth flagging, deferred follow-up. Optional. -->
