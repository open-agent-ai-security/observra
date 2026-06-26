#!/usr/bin/env bash
# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0
#
# Regenerate the API reference (guide/api/) with pdoc.
#
# Build-only: pdoc and the framework extras are NOT shipped with the package.
# This introspects the installed observra package + its docstrings and renders
# the public API as themed HTML under guide/api/. Run it when the public API or
# docstrings change, then commit guide/api/ (same generate-and-commit pattern as
# the rest of guide/).
#
#   make api-docs
#
# It creates a throwaway venv (.venv-apidocs, git-ignored), installs observra
# with the framework + backend extras so every adapter is importable, plus the
# pinned pdoc, then renders the public surface. Requires Python >= 3.10 (the
# library's floor); override the interpreter with PYTHON=python3.12 if needed.
set -euo pipefail
cd "$(dirname "$0")/.."

PY="${PYTHON:-python3}"
VENV=".venv-apidocs"
[ -d "$VENV" ] || "$PY" -m venv "$VENV"
"$VENV/bin/python" -m pip install -q --upgrade pip
# Framework + backend extras → all five adapters import cleanly for introspection.
"$VENV/bin/python" -m pip install -q -e ".[adk,claude,openai-agents,langchain,pydantic-ai,otel,exabeam]" "pdoc==16.0.0"

# Brand assets are referenced by absolute URL so they resolve at any page depth,
# both locally and on the deployed Pages site.
LOGO="https://open-agent-ai-security.github.io/observra/graphics/brand/observra-wordmark-dark-background.svg"
FAV="https://open-agent-ai-security.github.io/observra/graphics/web/favicon-32.png"
DOCS="https://open-agent-ai-security.github.io/observra/guide/index.html"

rm -rf guide/api
"$VENV/bin/pdoc" \
  --template-directory pdoc_template \
  --docformat google \
  --logo "$LOGO" --logo-link "$DOCS" --favicon "$FAV" \
  --footer-text "Observra API reference" \
  --no-show-source \
  -o guide/api \
  observra \
  observra.core.events observra.core.storage \
  observra.backends.jsonl observra.backends.webhook observra.backends.otel observra.backends.otel_log observra.backends.multi \
  observra.senders.exabeam \
  observra.adapters.adk.plugin observra.adapters.claude.adapter observra.adapters.openai.adapter observra.adapters.langchain.adapter observra.adapters.pydantic_ai.adapter

echo "Wrote guide/api/ — review locally, then commit it alongside guide/."
