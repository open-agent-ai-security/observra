<!--
  Copyright 2026 Exabeam, Inc.
  SPDX-License-Identifier: Apache-2.0
-->
# Releasing observra

The version lives in **one** place — `__version__` in `src/observra/__init__.py`.
`pyproject.toml` reads it dynamically (`[tool.setuptools.dynamic]`), so the two
never drift and you only ever bump one file.

## Pre-Tag Checklist

Before cutting a release:

- [ ] `main` is green: `pytest tests/unit/`, `ruff check .`, `ruff format --check .`.
- [ ] `CHANGELOG.md`'s `[Unreleased]` section reflects exactly what's shipping —
      move anything already released out of it (otherwise the auto-generated
      release notes will be wrong).
- [ ] Cross-ecosystem version pins are aligned where they exist
      (`pyproject.toml` ⇄ `rust/Cargo.toml` ⇄ `npm/observra-installer/package.json`).
- [ ] Working tree is clean and you are on `main`.

## Version Bump Procedure

The version is single-source. Bump it with the script (never hand-edit two files):

```bash
python scripts/bump_version.py patch     # or: minor | major | X.Y.Z
```

This updates `__version__` in `src/observra/__init__.py` and rolls the
`CHANGELOG.md` `[Unreleased]` section into a dated `[X.Y.Z]` heading (leaving a
fresh `[Unreleased]` on top). `pyproject.toml` needs no edit — it derives the
version from `__version__`.

## Tag Push Flow

Commit the bump and push to `main`:

```bash
git add -A && git commit -m "bump version to X.Y.Z"
git push origin main
```

The **Auto Release** workflow (`.github/workflows/auto-release.yaml`) runs on the
push (it watches `src/observra/__init__.py`), reads `__version__`, and — if the
tag doesn't already exist — creates the git tag `vX.Y.Z` plus a GitHub Release
with generated notes. It is **idempotent**: re-runs do nothing once the tag
exists.

Publishing to PyPI is a **deliberate, manual** step: run the **Publish to PyPI**
workflow (`.github/workflows/publish.yaml`, `workflow_dispatch`; it also supports
a `testpypi` target for a dry run). PyPI uploads are irreversible, so this is
intentionally not automatic.

## Post-Publish Verification

After the tag, release, and PyPI publish:

- [ ] In a clean venv: `pip install observra==X.Y.Z` succeeds.
- [ ] `python -c "import observra; print(observra.__version__)"` prints `X.Y.Z`.
- [ ] The GitHub **Releases** page shows `vX.Y.Z` with the expected notes.
- [ ] `https://pypi.org/project/observra/X.Y.Z/` is live.

## Rollback Procedure

If a release is broken, roll it back most-visible-first:

```bash
# 1. Yank the PyPI release (hides it from new resolves; it can't be deleted)
twine yank observra==X.Y.Z              # or via the PyPI web UI

# 2. Unpublish the npm installer package, if one was published for this version
npm unpublish @observra/installer@X.Y.Z

# 3. Remove the GitHub Release and the tag
gh release delete vX.Y.Z --yes
git push --delete origin vX.Y.Z          # delete the remote tag
git tag -d vX.Y.Z                         # delete the local tag
```

Then fix forward: bump to the next patch and re-release. **Never** re-use a
yanked/deleted version number — PyPI permanently rejects re-uploads of an
existing version.

## Version History Note

observra follows [Semantic Versioning](https://semver.org/), single-sourced from
`src/observra/__init__.py`.

**Watch for PEP 440 pre-release shadowing.** Under
[PEP 440](https://peps.python.org/pep-0440/), a *final* release (`1.2.0`) sorts
**higher** than its pre-releases (`1.2.0rc1`, `1.2.0b1`), and `pip` won't install
a pre-release by default. The trap: if you burn a clean number on a test upload
(publishing `1.2.0` to PyPI as a trial), you can never ship the real `1.2.0` —
the number is gone, and any later artifact must use a *higher* version, which can
silently **shadow** the intended release for resolvers. Always use explicit
pre-release suffixes (`1.2.0rc1`) for trial builds / TestPyPI, and reserve the
clean `X.Y.Z` for the actual release.
