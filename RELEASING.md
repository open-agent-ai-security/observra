<!--
  Copyright 2026 Exabeam, Inc.
  SPDX-License-Identifier: Apache-2.0
-->
# Releasing observra

The version lives in **one** place — `__version__` in `src/observra/__init__.py`.
`pyproject.toml` reads it dynamically (`[tool.setuptools.dynamic]`), so you never
edit two files or risk them drifting.

## Cut a release

1. **Bump the version and roll the changelog:**

   ```bash
   python scripts/bump_version.py patch     # or: minor | major | X.Y.Z
   ```

   This updates `__version__` and rolls `CHANGELOG.md`'s `[Unreleased]` section
   into a dated `[X.Y.Z]` heading (leaving a fresh `[Unreleased]` on top).

2. **Review, commit, and push to `main`:**

   ```bash
   git add -A && git commit -m "bump version to X.Y.Z"
   git push origin main
   ```

3. The **Auto Release** workflow (`.github/workflows/auto-release.yaml`) runs on
   that push, reads the new `__version__`, and — if the tag doesn't already
   exist — creates the git tag `vX.Y.Z` plus a GitHub Release with generated
   notes. It is **idempotent**: if the tag exists, it does nothing.

## Publishing to PyPI

PyPI publishing remains a **deliberate, manual step** — run the **Publish to
PyPI** workflow (`.github/workflows/publish.yaml`, `workflow_dispatch`), which
also supports a `testpypi` target for a dry run. PyPI uploads are irreversible,
so this is intentionally **not** automatic.

> If the team later wants fully hands-off publishing, trigger `publish.yaml` on
> `release: published` instead of `workflow_dispatch`.

## One-time backfill

There are currently no GitHub Releases for already-published versions
(`1.0.0`–`1.0.4` are on PyPI but untagged). To populate the Releases page for
the current version, run the **Auto Release** workflow once (it will tag and
release the current `__version__`). Backfilling older versions is optional and
would tag their historical commits.

Note: `CHANGELOG.md`'s `[Unreleased]` section still contains entries that
shipped in `1.0.x`; tidy it into the right release headings before the next bump
so the generated notes are accurate.
