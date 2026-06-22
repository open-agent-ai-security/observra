"""Canonical JSON parity tests — Python and Rust emit byte-identical JSON."""

import json
import os
import subprocess
from unittest.mock import patch

from observra.core.events import TelemetryEvent, create_event

# ---------------------------------------------------------------------------
# Canonical JSON helpers
# ---------------------------------------------------------------------------


def canonical_json(obj: dict) -> bytes:
    """Serialize dict to canonical JSON bytes matching Rust serde_json output."""
    # Python 3.7+ preserves dict insertion order; Rust serde_json preserves struct field order.
    return json.dumps(
        strip_none_values(obj),
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def strip_none_values(d: dict) -> dict:
    """Recursively strip dict keys whose value is None (matches Rust skip_serializing_if)."""
    out = {}
    for k, v in d.items():
        if v is None:
            continue
        if isinstance(v, dict):
            nested = strip_none_values(v)
            if nested:
                out[k] = nested
        elif isinstance(v, list):
            out[k] = [strip_none_values(i) if isinstance(i, dict) else i for i in v if i is not None]
        else:
            out[k] = v
    return out


def _sort_nested_keys(d: dict) -> dict:
    """Recursively sort all nested dict keys alphabetically (top-level preserved)."""
    out = {}
    for k, v in d.items():
        if isinstance(v, dict):
            out[k] = _sort_nested_keys(v)
        elif isinstance(v, list):
            out[k] = [_sort_nested_keys(i) if isinstance(i, dict) else i for i in v]
        else:
            out[k] = v
    return out


def _to_dict(event: TelemetryEvent) -> dict:
    """Serialize TelemetryEvent dataclass to plain dict in Rust struct field order."""
    d = {
        "event_id": event.event_id,
        "timestamp": event.timestamp,
        "trace_id": event.trace_id,
        "session_id": event.session_id,
        "span_id": event.span_id,
        "event_type": event.event_type,
        "agent_name": event.agent_name,
        "tool_name": event.tool_name,
        "model_name": event.model_name,
        "data": event.data,
        "framework": event.framework,
        "skill_name": event.skill_name,
        "host": event.host,
        "user": event.user,
        "os": event.os,
        "arch": event.arch,
        "library_version": event.library_version,
    }
    # Sort nested dict keys to match Rust serde_json's BTreeMap ordering.
    if d["data"] is not None:
        d["data"] = dict(sorted(d["data"].items()))
    return d


# ---------------------------------------------------------------------------
# Deterministic monkey-patches for reproducible output
# ---------------------------------------------------------------------------

_DETERMINISTIC_PATCHES = {
    "observra.core.events.generate_ulid": "01HZTEST000000000000000000",
    "observra.core.events.generate_timestamp": 1714500000.0,
    "observra.core.events.get_trace_id": "trace-test-01",
    "observra.core.events.get_session_id": "sess-test-01",
    "observra.core.events.get_span_id": "span-test-01",
}


def _make_event(event_type, **kwargs):
    """Create an event with all stochastic fields patched to deterministic values."""
    with patch("observra.core.events.generate_ulid", return_value="01HZTEST000000000000000000"):
        with patch("observra.core.events.generate_timestamp", return_value=1714500000.0):
            with patch("observra.core.events.get_trace_id", return_value="trace-test-01"):
                with patch("observra.core.events.get_session_id", return_value="sess-test-01"):
                    with patch("observra.core.events.get_span_id", return_value="span-test-01"):
                        with patch("observra.core.events.get_host_context") as mock_ctx:
                            mock_ctx.return_value.host = "test-host"
                            mock_ctx.return_value.user = "test-user"
                            mock_ctx.return_value.os = "Linux"
                            mock_ctx.return_value.arch = "x86_64"
                            mock_ctx.return_value.library_version = "2.1.0"
                            return create_event(event_type=event_type, **kwargs)


# ---------------------------------------------------------------------------
# Rust oracle binary discovery
# ---------------------------------------------------------------------------

_RUST_ORACLE_PATHS = [
    "tests/property/target/release/parity-oracle",
    "tests/property/target/debug/parity-oracle",
]


def _find_oracle() -> str:
    for p in _RUST_ORACLE_PATHS:
        if os.path.isfile(p):
            return p
    # Try to build it
    subprocess.run(
        ["cargo", "build", "--manifest-path", "tests/property/Cargo.toml", "--release", "--bin", "parity-oracle"],
        check=True,
    )
    for p in _RUST_ORACLE_PATHS:
        if os.path.isfile(p):
            return p
    raise FileNotFoundError("parity-oracle binary not found after build")


def _rust_json_for_event(event_dict: dict) -> bytes:
    """Pipe a dict through the Rust parity-oracle binary and return canonical JSON bytes."""
    oracle = _find_oracle()
    payload = json.dumps(event_dict, separators=(",", ":"), ensure_ascii=False)
    result = subprocess.run(
        [oracle],
        input=payload + "\n",
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip().encode("utf-8")


# ---------------------------------------------------------------------------
# Parity tests
# ---------------------------------------------------------------------------


def test_canonical_json_strip_none():
    assert canonical_json({"a": 1, "b": None}) == b'{"a":1}'
    assert canonical_json({"c": {"d": 2, "e": None}}) == b'{"c":{"d":2}}'


def test_parity_session_start():
    event = _make_event("session_start")
    python_bytes = canonical_json(strip_none_values(_to_dict(event)))
    rust_bytes = _rust_json_for_event(strip_none_values(_to_dict(event)))
    assert python_bytes == rust_bytes, f"Mismatch:\nPython: {python_bytes}\nRust:  {rust_bytes}"


def test_parity_tool_end_read_file():
    event = _make_event("tool_end", tool_name="read_file", model_name="claude-opus-4-7", framework="claude_code")
    python_bytes = canonical_json(strip_none_values(_to_dict(event)))
    rust_bytes = _rust_json_for_event(strip_none_values(_to_dict(event)))
    assert python_bytes == rust_bytes, f"Mismatch:\nPython: {python_bytes}\nRust:  {rust_bytes}"


def test_parity_tool_error_delete_file():
    event = _make_event("tool_error", tool_name="delete_file", model_name="gpt-4o", framework="openai")
    python_bytes = canonical_json(strip_none_values(_to_dict(event)))
    rust_bytes = _rust_json_for_event(strip_none_values(_to_dict(event)))
    assert python_bytes == rust_bytes, f"Mismatch:\nPython: {python_bytes}\nRust:  {rust_bytes}"


def test_parity_agent_end():
    event = _make_event("agent_end", agent_name="test-agent", model_name="gemini-2.5-pro", framework="gemini_cli")
    python_bytes = canonical_json(strip_none_values(_to_dict(event)))
    rust_bytes = _rust_json_for_event(strip_none_values(_to_dict(event)))
    assert python_bytes == rust_bytes, f"Mismatch:\nPython: {python_bytes}\nRust:  {rust_bytes}"


def test_parity_model_response():
    event = _make_event(
        "model_response",
        model_name="claude-opus-4-7",
        framework="claude_code",
        input_tokens=100,
        output_tokens=50,
        cost_usd="0.003",
    )
    python_bytes = canonical_json(strip_none_values(_to_dict(event)))
    rust_bytes = _rust_json_for_event(strip_none_values(_to_dict(event)))
    assert python_bytes == rust_bytes, f"Mismatch:\nPython: {python_bytes}\nRust:  {rust_bytes}"


def test_parity_forwarder_update_available():
    event = _make_event("forwarder_update_available")
    python_bytes = canonical_json(strip_none_values(_to_dict(event)))
    rust_bytes = _rust_json_for_event(strip_none_values(_to_dict(event)))
    assert python_bytes == rust_bytes, f"Mismatch:\nPython: {python_bytes}\nRust:  {rust_bytes}"
