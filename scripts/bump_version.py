#!/usr/bin/env python3
# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0
"""Bump the observra version (single source of truth: src/observra/__init__.py).

Usage:
    python scripts/bump_version.py patch     # 1.0.4 -> 1.0.5
    python scripts/bump_version.py minor     # 1.0.4 -> 1.1.0
    python scripts/bump_version.py major     # 1.0.4 -> 2.0.0
    python scripts/bump_version.py 1.2.3     # explicit

Updates `__version__` in src/observra/__init__.py and rolls the CHANGELOG
`[Unreleased]` section into a dated `[X.Y.Z]` heading. pyproject.toml reads the
version dynamically from `__version__`, so it is never edited.

After running, review the diff, commit, and push to main — the "Auto Release"
workflow tags v<version> and cuts the GitHub Release. See RELEASING.md.
"""

from __future__ import annotations

import datetime
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INIT = ROOT / "src" / "observra" / "__init__.py"
CHANGELOG = ROOT / "CHANGELOG.md"
_VERSION_RE = re.compile(r'^__version__ = "(\d+)\.(\d+)\.(\d+)"$', re.MULTILINE)


def current_version() -> tuple[int, int, int]:
    m = _VERSION_RE.search(INIT.read_text(encoding="utf-8"))
    if not m:
        sys.exit(f"bump_version: could not find __version__ in {INIT}")
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def compute(cur: tuple[int, int, int], arg: str) -> str:
    if re.fullmatch(r"\d+\.\d+\.\d+", arg):
        return arg
    major, minor, patch = cur
    if arg == "major":
        return f"{major + 1}.0.0"
    if arg == "minor":
        return f"{major}.{minor + 1}.0"
    if arg == "patch":
        return f"{major}.{minor}.{patch + 1}"
    sys.exit(f"bump_version: unknown bump {arg!r} (use major|minor|patch|X.Y.Z)")


def bump_init(new: str) -> None:
    text = INIT.read_text(encoding="utf-8")
    text, n = _VERSION_RE.subn(f'__version__ = "{new}"', text)
    assert n == 1, f"expected exactly one __version__ line, replaced {n}"
    INIT.write_text(text, encoding="utf-8")


def roll_changelog(new: str) -> None:
    text = CHANGELOG.read_text(encoding="utf-8")
    needle = "## [Unreleased]"
    if needle not in text:
        print(f"  warning: {needle!r} not found in CHANGELOG.md — add a release heading manually")
        return
    today = datetime.date.today().isoformat()
    text = text.replace(needle, f"## [Unreleased]\n\n## [{new}] — {today}", 1)
    CHANGELOG.write_text(text, encoding="utf-8")


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    cur = current_version()
    cur_str = ".".join(map(str, cur))
    new = compute(cur, sys.argv[1])
    if new == cur_str:
        sys.exit(f"bump_version: version is already {new}")

    bump_init(new)
    roll_changelog(new)

    print(f"Bumped {cur_str} -> {new}")
    print("Next steps:")
    print(f'  git add -A && git commit -m "bump version to {new}"')
    print(f"  git push origin main   # 'Auto Release' tags v{new} and cuts the GitHub Release")


if __name__ == "__main__":
    main()
