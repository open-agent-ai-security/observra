#!/usr/bin/env python3
"""Generate observra/core/cim.py from cim_schema.toml."""

from __future__ import annotations

import os
import sys
from pathlib import Path

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]


REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "schema" / "cim_schema.toml"
OUTPUT_PATH = REPO_ROOT / "src" / "observra" / "core" / "cim.py"


def load_schema() -> dict:
    with SCHEMA_PATH.open("rb") as f:
        return tomllib.load(f)


def indent(level: int) -> str:
    return "    " * level


def generate() -> str:
    schema = load_schema()

    lines: list[str] = []

    lines.append(
        '"""Cross-source CIM-aligned data block contract — GENERATED FROM cim_schema.toml. DO NOT EDIT."""'
    )
    lines.append("")
    lines.append("from __future__ import annotations")
    lines.append("")
    lines.append("from enum import Enum")
    lines.append("from typing import Any, Optional")
    lines.append("")
    version = schema["meta"]["version"]
    lines.append(f'CIM_VERSION = "{version}"')
    product_id = schema["meta"]["product_id"]
    lines.append(f'PRODUCT_ID = "{product_id}"')
    lines.append("")
    lines.append("")
    lines.append("# ---------------------------------------------------------------------------")
    lines.append("# Enumerations — canonical values for SIEM-friendly fields.")
    lines.append("# ---------------------------------------------------------------------------")
    lines.append("")

    # Action enum — derive from action_pattern actions, plus invoke_tool for backward compat.
    action_values = sorted({ap["action"] for ap in schema.get("action_pattern", [])})
    # Ensure invoke_tool is present for normalize_action fallback compatibility.
    if "invoke_tool" not in action_values:
        action_values.append("invoke_tool")
    action_values.append("unknown")

    lines.append("class Action(str, Enum):")
    for val in action_values:
        name = val.upper().replace(" ", "_")
        lines.append(f'    {name:<14} = "{val}"')
    lines.append("")

    # Vendor enum — derive from vendor_map, plus unknown.
    vendor_values = sorted({vm["vendor"] for vm in schema.get("vendor_map", [])})
    vendor_values.append("unknown")

    lines.append("class Vendor(str, Enum):")
    for val in vendor_values:
        name = val.upper().replace(" ", "_")
        lines.append(f'    {name:<14} = "{val}"')
    lines.append("")

    # ActionResult enum — preserve existing values for backward compat.
    lines.append("class ActionResult(str, Enum):")
    for val in ["success", "failure", "blocked", "timeout"]:
        lines.append(f'    {val.upper():<14} = "{val}"')
    lines.append("")

    # FinishReason enum — derive from finish_reason canonical values, plus error/timeout/unknown.
    finish_values = sorted({fr["canonical"] for fr in schema.get("finish_reason", [])})
    for extra in ["error", "timeout", "unknown"]:
        if extra not in finish_values:
            finish_values.append(extra)

    lines.append("class FinishReason(str, Enum):")
    for val in finish_values:
        name = val.upper().replace(" ", "_")
        lines.append(f'    {name:<14} = "{val}"')
    lines.append("")

    # _FINISH_REASON_MAP
    lines.append("_FINISH_REASON_MAP: dict[str, FinishReason] = {")
    for fr in schema.get("finish_reason", []):
        raw = fr["raw"]
        canonical = fr["canonical"]
        lines.append(f'    "{raw}": FinishReason.{canonical.upper()},')
    lines.append("}")
    lines.append("")

    # normalize_finish_reason
    lines.append("def normalize_finish_reason(raw: Optional[str]) -> FinishReason:")
    lines.append('    """Map platform finish_reason string to canonical FinishReason."""')
    lines.append("    if not raw:")
    lines.append("        return FinishReason.UNKNOWN")
    lines.append("    return _FINISH_REASON_MAP.get(raw, FinishReason.UNKNOWN)")
    lines.append("")
    lines.append("")
    lines.append("# ---------------------------------------------------------------------------")
    lines.append("# Tool name → action vocabulary.")
    lines.append("# ---------------------------------------------------------------------------")
    lines.append("")

    # _ACTION_PATTERNS sorted by priority ascending then pattern ascending.
    action_patterns = schema.get("action_pattern", [])
    action_patterns_sorted = sorted(
        action_patterns, key=lambda ap: (ap["priority"], ap["pattern"])
    )

    max_pat_len = max(len(ap["pattern"]) for ap in action_patterns_sorted) if action_patterns_sorted else 0
    lines.append("_ACTION_PATTERNS: list[tuple[str, Action]] = [")
    for ap in action_patterns_sorted:
        pattern = ap["pattern"]
        action = ap["action"]
        lines.append(f'    ("{pattern}",{" " * (max_pat_len - len(pattern))} Action.{action.upper()}),')
    lines.append("]")
    lines.append("")

    # normalize_action
    lines.append("def normalize_action(tool_name: Optional[str]) -> Action:")
    lines.append('    """Infer the canonical CIM action enum from a free-form tool name."""')
    lines.append("    if not tool_name:")
    lines.append("        return Action.UNKNOWN")
    lines.append("    lower = tool_name.lower()")
    lines.append("    for pattern, action in _ACTION_PATTERNS:")
    lines.append("        if pattern in lower:")
    lines.append("            return action")
    lines.append("    return Action.INVOKE_TOOL")
    lines.append("")
    lines.append("")
    lines.append("# ---------------------------------------------------------------------------")
    lines.append("# event_type → CIM action mapping.")
    lines.append("# ---------------------------------------------------------------------------")
    lines.append("")

    # _ACTION_FOR_EVENT_TYPE
    actions = schema.get("actions", {})
    lines.append("_ACTION_FOR_EVENT_TYPE: dict[str, str] = {")
    for event_type in sorted(actions.keys()):
        action = actions[event_type]["action"]
        lines.append(f'    "{event_type}": "{action}",')
    lines.append("}")
    lines.append("")

    # action_for_event_type
    lines.append("def action_for_event_type(event_type: str) -> str:")
    lines.append('    """Map a canonical event_type to its CIM action verb."""')
    lines.append('    return _ACTION_FOR_EVENT_TYPE.get(event_type, "unknown")')
    lines.append("")
    lines.append("")
    lines.append("# ---------------------------------------------------------------------------")
    lines.append("# Default result for terminal events. None for non-terminal events.")
    lines.append("# ---------------------------------------------------------------------------")
    lines.append("")

    # _DEFAULT_RESULT_FOR_EVENT_TYPE
    lines.append("_DEFAULT_RESULT_FOR_EVENT_TYPE: dict[str, str] = {")
    for event_type in sorted(actions.keys()):
        cfg = actions[event_type]
        if cfg.get("terminal") and "default_result" in cfg:
            dr = cfg["default_result"]
            lines.append(f'    "{event_type}": "{dr}",')
    lines.append("}")
    lines.append("")

    # default_result_for_event_type
    lines.append("def default_result_for_event_type(event_type: str) -> Optional[str]:")
    lines.append('    """Return the default data.result for terminal event types."""')
    lines.append("    return _DEFAULT_RESULT_FOR_EVENT_TYPE.get(event_type)")
    lines.append("")
    lines.append("")
    lines.append("# ---------------------------------------------------------------------------")
    lines.append("# Vendor derivation from model name.")
    lines.append("# ---------------------------------------------------------------------------")
    lines.append("")

    # vendor_from_model
    vendor_map = schema.get("vendor_map", [])
    lines.append("def vendor_from_model(model: Optional[str]) -> str:")
    lines.append('    """Classify a model identifier into a vendor."""')
    lines.append('    if not model:')
    lines.append('        return "unknown"')
    lines.append('    lower = model.lower()')
    for vm in vendor_map:
        patterns = vm["patterns"]
        vendor = vm["vendor"]
        # Build the condition string
        conds = [f'"{p}" in lower' for p in patterns]
        lines.append(f'    if {" or ".join(conds)}:')
        lines.append(f'        return "{vendor}"')
    lines.append('    return "unknown"')
    lines.append("")

    # _VENDOR_BY_FRAMEWORK
    framework_vendor = schema.get("framework_vendor", [])
    lines.append("_VENDOR_BY_FRAMEWORK: dict[str, str] = {")
    for fv in framework_vendor:
        fw = fv["framework"]
        vendor = fv["vendor"]
        lines.append(f'    "{fw}": "{vendor}",')
    lines.append("}")
    lines.append("")

    # vendor_from_model_or_framework
    lines.append("def vendor_from_model_or_framework(")
    lines.append("    model: Optional[str], framework: Optional[str]")
    lines.append(") -> str:")
    lines.append('    """Vendor classification with a framework-name fallback."""')
    lines.append("    v = vendor_from_model(model)")
    lines.append('    if v != "unknown":')
    lines.append("        return v")
    lines.append("    if framework:")
    lines.append("        return _VENDOR_BY_FRAMEWORK.get(framework, \"unknown\")")
    lines.append('    return "unknown"')
    lines.append("")
    lines.append("")
    lines.append("# ---------------------------------------------------------------------------")
    lines.append("# Tool reversibility classification.")
    lines.append("# ---------------------------------------------------------------------------")
    lines.append("")

    # reversibility patterns
    reversibility = schema.get("reversibility", {})
    irreversible = reversibility.get("irreversible", [])
    reversible = reversibility.get("reversible", [])

    lines.append("_IRREVERSIBLE_TOOL_PATTERNS: list[str] = [")
    for pattern in irreversible:
        lines.append(f'    "{pattern}",')
    lines.append("]")
    lines.append("")

    lines.append("_REVERSIBLE_TOOL_PATTERNS: list[str] = [")
    for pattern in reversible:
        lines.append(f'    "{pattern}",')
    lines.append("]")
    lines.append("")

    # classify_reversibility
    lines.append("def classify_reversibility(tool_name: Optional[str]) -> Optional[bool]:")
    lines.append('    """Classify a tool name as reversible / irreversible / unknown."""')
    lines.append("    if not tool_name:")
    lines.append("        return None")
    lines.append("    lower = tool_name.lower()")
    lines.append("    for pattern in _IRREVERSIBLE_TOOL_PATTERNS:")
    lines.append("        if pattern in lower:")
    lines.append("            return False")
    lines.append("    for pattern in _REVERSIBLE_TOOL_PATTERNS:")
    lines.append("        if pattern in lower:")
    lines.append("            return True")
    lines.append("    return None")
    lines.append("")
    lines.append("")
    lines.append("# ---------------------------------------------------------------------------")
    lines.append("# Builder")
    lines.append("# ---------------------------------------------------------------------------")
    lines.append("")

    # build_data_for_event
    lines.append("def build_data_for_event(")
    lines.append("    event_type: str,")
    lines.append("    vendor: str,")
    lines.append("    extras: Optional[dict[str, Any]] = None,")
    lines.append(") -> dict[str, Any]:")
    lines.append('    """Build the canonical data block for event_type."""')
    lines.append('    out: dict[str, Any] = {')
    lines.append('        "action": action_for_event_type(event_type),')
    lines.append('        "vendor": vendor,')
    lines.append("    }")
    lines.append("    result = default_result_for_event_type(event_type)")
    lines.append("    if result is not None:")
    lines.append('        out["result"] = result')
    lines.append("    if extras:")
    lines.append("        out.update(extras)")
    lines.append("    return out")
    lines.append("")

    return "\n".join(lines)


def main() -> int:
    if not SCHEMA_PATH.exists():
        print(f"Schema not found: {SCHEMA_PATH}", file=sys.stderr)
        return 1

    content = generate()

    tmp_path = OUTPUT_PATH.with_suffix(".py.tmp")
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path.write_text(content, encoding="utf-8")
    os.replace(str(tmp_path), str(OUTPUT_PATH))

    print(f"Generated {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
