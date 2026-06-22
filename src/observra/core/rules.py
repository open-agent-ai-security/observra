# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Detection rule evaluation for agent telemetry events.

Rules are evaluated at event creation time (against unredacted values) and
stored in event.data as ``triggered_rules`` (list[str]) and ``max_severity``
(str | None). This makes rule matches visible in ALL backends — JSONL, SQLite,
Pub/Sub, BigQuery, OTel — without needing a separate SIEM rule engine.

Rules mirror the ``detection_rules`` section of ``examples/siem_parser.json``.
Update both files when adding or changing rules.

Example output in event.data::

    {
        "has_injection_patterns": True,
        "triggered_rules": ["Prompt Injection Detected"],
        "max_severity": "high",
        ...
    }
"""

from __future__ import annotations

from typing import Any

# Severity ordering for max_severity resolution
_SEVERITY_RANK: dict[str, int] = {"high": 3, "medium": 2, "low": 1}

# Detection rules — each entry has:
#   name      : human-readable rule name (matches siem_parser.json)
#   severity  : "high" | "medium" | "low"
#   check     : callable(event_type: str, data: dict) -> bool
#               Must be safe to call with any data dict (may be empty).
#               Never raise — exceptions are silently ignored.
_DETECTION_RULES: list[dict[str, Any]] = [
    {
        "name": "Prompt Injection Detected",
        "severity": "high",
        "check": lambda et, d: d.get("has_injection_patterns") is True,
    },
    {
        "name": "Cost Threshold Exceeded",
        "severity": "medium",
        "check": lambda et, d: et == "cost_threshold_exceeded",
    },
    {
        "name": "Agent Depth Exceeded",
        "severity": "medium",
        "check": lambda et, d: et == "depth_exceeded",
    },
    {
        "name": "Model Error - Rate Limited",
        "severity": "low",
        "check": lambda et, d: et == "model_error" and d.get("error_class") == "rate_limit",
    },
    {
        "name": "Model Error - Auth Failure",
        "severity": "high",
        "check": lambda et, d: et == "model_error" and d.get("error_class") == "auth",
    },
    {
        "name": "Tool Error",
        "severity": "low",
        "check": lambda et, d: et == "tool_error",
    },
    {
        "name": "Agent Handoff Error",
        "severity": "medium",
        "check": lambda et, d: et == "agent_handoff_error",
    },
    {
        "name": "High Token Usage",
        "severity": "low",
        "check": lambda et, d: et == "model_response" and (d.get("total_tokens") or 0) > 10000,
    },
    {
        "name": "High Single-Call Cost",
        "severity": "medium",
        "check": lambda et, d: et == "model_response" and (d.get("cost_usd") or 0) > 0.50,
    },
    {
        "name": "Suspicious Tool Sequence",
        "severity": "medium",
        "check": lambda et, d: d.get("suspicious_sequence") is True,
    },
]


def evaluate_rules(event_type: str, data: dict[str, Any] | None) -> dict[str, Any]:
    """Evaluate all detection rules against an event and return matched annotations.

    Called by ``create_event()`` against the *unredacted* merged data dict so
    that boolean/numeric fields (``has_injection_patterns``, ``error_class``,
    ``total_tokens``, ``cost_usd``) retain their real values during evaluation,
    even for events that later go through hot-path string stripping.

    The returned dict is merged into ``event.data`` after redaction so the rule
    results themselves are never stripped.

    Args:
        event_type: Event type string (e.g. ``"tool_error"``).
        data: Merged kwargs dict before redaction. May be None or empty.

    Returns:
        Dict with ``triggered_rules`` (list[str]) and ``max_severity`` (str)
        when at least one rule fires. Empty dict when no rules match.
    """
    d = data or {}
    triggered: list[str] = []
    max_rank = 0
    max_sev: str | None = None

    for rule in _DETECTION_RULES:
        try:
            if rule["check"](event_type, d):
                triggered.append(rule["name"])
                rank = _SEVERITY_RANK.get(rule["severity"], 0)
                if rank > max_rank:
                    max_rank = rank
                    max_sev = rule["severity"]
        except Exception:
            # Never let a buggy rule check crash event creation
            pass

    if triggered:
        return {"triggered_rules": triggered, "max_severity": max_sev}
    return {}
