<!--
  Copyright 2026 Exabeam, Inc.
  SPDX-License-Identifier: Apache-2.0
-->
# Sample Telemetry Viewer

A static, searchable/filterable viewer for what observra's event output looks like — useful for
showing people the shape of the data without needing a live agent + API keys.

- `generate_data.py` — produces `data.js` and `data.jsonl`. Synthetic events from three sessions
  at a fictional company ("Atlas"), each run by a different agent, matching the real event envelope
  (`docs/event-schema.md`) and CIM `data` fields (`schema/cim_schema.toml`) — deliberately built so
  framework, model vendor, and agent identity don't collapse into one another:
  - `vpn-support-agent` (Claude Agent SDK, claude-sonnet-5) — a clean run.
  - `kb-research-agent` (Google ADK, claude-sonnet-5) — ADK is model-agnostic; this one runs
    Claude, not Gemini. Trips the prompt-injection detector, a rate limit, and a cost threshold.
  - `support-router-agent` hands off to `refund-processor-agent` (same OpenAI Agents SDK session,
    but the bounded refund task runs the cheaper gpt-5.1-mini, not the router's gpt-5.1) — fails
    on a payment-gateway timeout, then gets blocked delegating past the depth guard.
- `index.html` — the viewer itself. Pure HTML/CSS/vanilla JS, no build step; loads `data.js`
  directly via `<script src>` so it opens straight from disk (no local server needed).
- `data.js` / `data.jsonl` — generated output, committed so the page works without running Python.

To regenerate with different data, edit `generate_data.py` and run:

    python3 demo/generate_data.py
