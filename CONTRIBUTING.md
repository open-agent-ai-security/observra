<!--
  Copyright 2026 Exabeam, Inc.
  SPDX-License-Identifier: Apache-2.0
-->

# Contributing to observra

Thanks for your interest in improving observra. Contributions are welcome via
pull request.

## Branching & pull requests

observra is a **versioned PyPI library**: consumers install a pinned release
(`pip install observra==X.Y.Z`), so `main` moving never affects anyone until they
choose to upgrade. That makes `main` a safe staging line — **the published *tag* is
the product; `main` is where the next one is assembled.**

Because of that, the flow is single-track and lightweight:

- **Branch from `main`, target `main`.** There is no long-lived `dev` branch —
  open your PR against `main` directly.
- **Squash-merge, and delete the branch on merge.** Keep each PR to one logical
  change; write the squash summary as the changelog-worthy description.
- Releases are cut *from* `main` by bumping the version — see
  [docs/RELEASING.md](docs/RELEASING.md). A normal PR needs nothing special; just
  land your change on `main`.

### Before you open a PR

- **Green locally:** `pytest tests/unit/`, `ruff check .`, `ruff format --check .`.
- **Sign your commits** (DCO — see below): every non-merge commit needs a
  `Signed-off-by` line (`git commit -s`).
- **Update `CHANGELOG.md`'s `[Unreleased]` section** for anything user-facing.
- **For a new or changed public API,** update
  [`STABILITY.md`](STABILITY.md) — it lists the guaranteed `1.x` surface.

### Docs — you don't regenerate them

The GitHub Pages docs site (`guide/` + `sitemap.xml`, rendered from `docs/*.md`
by `docs_build.py`, plus the pdoc `guide/api/`) **tracks releases, not `main`.**

- **Edit `docs/*.md` only.** Do **not** run `docs_build.py` or commit `guide/` in
  your PR — the rendered output is refreshed **at release time**
  (`scripts/bump_version.py` regenerates it as part of the version bump), so the
  published site always matches the released package rather than bleeding-edge
  `main`. This is deliberate: publishing `main`'s docs immediately would advertise
  APIs that aren't in any installable release yet.
- Between releases, `main`'s `docs/*.md` may be **ahead** of what's live on Pages —
  that's expected. Your doc change goes live with the next release.
- Need a doc fix published to **already-released** content sooner? A maintainer can
  run the **Rebuild docs** workflow (Actions → *Rebuild docs*), which rebuilds from
  the latest tag and publishes to Pages — no full release required.

## Releasing

Maintainers: see [docs/RELEASING.md](docs/RELEASING.md) for how releases are cut —
bump the version with `python scripts/bump_version.py`, push to `main`, and the
**Auto Release** workflow tags the commit and publishes the GitHub Release.

## License

observra is licensed under the [Apache License, Version 2.0](LICENSE.md). By
contributing, you agree that your contributions will be licensed under the same
terms.

You must have the right to contribute the work you submit — for example, it must
be your own original work, or work you are otherwise authorized to contribute
under the project's license. If your contribution was created as part of your
employment, make sure you have permission to submit it.

## Developer Certificate of Origin (DCO)

We use the [Developer Certificate of Origin](https://developercertificate.org/)
instead of a Contributor License Agreement. The DCO is a lightweight way for you
to certify that you wrote the contribution, or otherwise have the right to submit
it under the project's license.

To certify, add a `Signed-off-by` line to every commit:

```
Signed-off-by: Your Name <your.email@example.com>
```

Git adds it for you with the `-s` flag:

```
git commit -s -m "Your commit message"
```

The name and email must match a real identity. Every non-merge commit in a pull
request is expected to carry a `Signed-off-by` line; PRs without one will be
asked to amend before merge.

The full text of the DCO:

```
Developer Certificate of Origin
Version 1.1

Copyright (C) 2004, 2006 The Linux Foundation and its contributors.

Everyone is permitted to copy and distribute verbatim copies of this license
document, but changing it is not allowed.


Developer's Certificate of Origin 1.1

By making a contribution to this project, I certify that:

(a) The contribution was created in whole or in part by me and I have the right
    to submit it under the open source license indicated in the file; or

(b) The contribution is based upon previous work that, to the best of my
    knowledge, is covered under an appropriate open source license and I have
    the right under that license to submit that work with modifications, whether
    created in whole or in part by me, under the same open source license
    (unless I am permitted to submit under a different license), as indicated in
    the file; or

(c) The contribution was provided directly to me by some other person who
    certified (a), (b) or (c) and I have not modified it.

(d) I understand and agree that this project and the contribution are public and
    that a record of the contribution (including all personal information I
    submit with it, including my sign-off) is maintained indefinitely and may be
    redistributed consistent with this project or the open source license(s)
    involved.
```
