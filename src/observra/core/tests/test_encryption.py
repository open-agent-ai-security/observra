# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Tests for observra.core.encryption module.

TDD RED phase — all tests should FAIL before implementation.
"""

import json

import pytest

from observra.core.encryption import (
    EncryptionProvider,
    decrypt_line,
    encrypt_line,
    get_encryption_key,
)
from observra.core.events import TelemetryEvent

# ─── Helper ──────────────────────────────────────────────────────────────────


def _make_key(passphrase: str = "test-passphrase") -> bytes:
    """Derive a key from a passphrase (matches get_encryption_key with env var set)."""
    from observra.core.encryption import _derive_key_from_passphrase

    return _derive_key_from_passphrase(passphrase)


def _make_event() -> TelemetryEvent:
    return TelemetryEvent(
        event_id="01HZ000000000000000000001",
        timestamp=1000.0,
        trace_id="trace-001",
        session_id="sess-001",
        span_id="span-001",
        event_type="tool_call",
        agent_name="test-agent",
        data={"tool_name": "get_weather", "input_tokens": 100},
    )


# ─── Test 1: encrypt_line returns non-JSON ────────────────────────────────────


def test_encrypt_line_returns_non_json_output():
    """encrypt_line output must not be valid JSON."""
    key = _make_key()
    plaintext = '{"event_id": "abc", "tool_name": "x"}'
    ciphertext = encrypt_line(key, plaintext)

    # Must not be parseable as JSON
    with pytest.raises((json.JSONDecodeError, ValueError)):
        json.loads(ciphertext)

    # Must not contain readable JSON substrings
    assert "event_id" not in ciphertext
    assert "tool_name" not in ciphertext


# ─── Test 2: decrypt_line returns original plaintext ─────────────────────────


def test_decrypt_line_returns_original_plaintext():
    """decrypt_line(key, encrypt_line(key, text)) == text."""
    key = _make_key()
    plaintext = '{"event_id": "abc", "session_id": "sess-001"}'
    ciphertext = encrypt_line(key, plaintext)
    recovered = decrypt_line(key, ciphertext)
    assert recovered == plaintext


# ─── Test 3: wrong key raises on decrypt ─────────────────────────────────────


def test_decrypt_with_wrong_key_raises():
    """Decrypting with wrong key raises an exception (InvalidToken or similar)."""
    key1 = _make_key("passphrase-one")
    key2 = _make_key("passphrase-two")
    ciphertext = encrypt_line(key1, "some plaintext")

    with pytest.raises(Exception):
        decrypt_line(key2, ciphertext)


# ─── Test 4: get_encryption_key reads from env var ───────────────────────────


def test_get_encryption_key_from_env_var(monkeypatch):
    """get_encryption_key() returns bytes when ABA_TELEMETRY_KEY is set."""
    monkeypatch.setenv("ABA_TELEMETRY_KEY", "test-passphrase")
    key = get_encryption_key()
    assert key is not None
    assert isinstance(key, bytes)
    assert len(key) == 32


# ─── Test 5: get_encryption_key returns None when no source available ─────────


def test_get_encryption_key_returns_none_when_unavailable(monkeypatch):
    """get_encryption_key() returns None when env var absent and keyring unavailable."""
    monkeypatch.delenv("ABA_TELEMETRY_KEY", raising=False)
    # Stub keyring to simulate unavailability
    # Ensure keyring fails gracefully — either missing or returning None
    try:
        import keyring

        monkeypatch.setattr(keyring, "get_password", lambda *args: None)
    except ImportError:
        pass  # keyring not installed, which also means None is returned

    key = get_encryption_key()
    assert key is None


# ─── Test 6: JSONLBackend with encryption writes non-JSON lines ───────────────


def test_jsonl_backend_encrypted_writes_non_json(monkeypatch, tmp_path):
    """JSONLBackend with encryption_key writes lines that are not valid JSON."""
    from observra.backends.jsonl import JSONLBackend

    monkeypatch.setenv("ABA_TELEMETRY_KEY", "test-passphrase")
    key = get_encryption_key()

    output_path = tmp_path / "telemetry.jsonl"
    backend = JSONLBackend(path=str(output_path), encryption_key=key)
    event = _make_event()
    backend.write(event)
    backend.close()

    # Find the actual file (may have .enc extension)
    enc_path = tmp_path / "telemetry.jsonl.enc"
    if enc_path.exists():
        actual_path = enc_path
    else:
        actual_path = output_path

    content = actual_path.read_text(encoding="utf-8")
    lines = [line for line in content.splitlines() if line.strip()]
    assert len(lines) >= 1

    for line in lines:
        with pytest.raises((json.JSONDecodeError, ValueError)):
            json.loads(line)
        # Must not contain recognizable JSON event fields
        assert '{"event_id"' not in line
        assert "event_id" not in line


# ─── Test 7: Backends with encryption=False are unchanged ────────────────────


def test_backends_without_encryption_behave_normally(tmp_path):
    """Backends without encryption_key write normal JSON/SQL."""
    from observra.backends.jsonl import JSONLBackend

    output_path = tmp_path / "unencrypted.jsonl"
    backend = JSONLBackend(path=str(output_path))
    event = _make_event()
    backend.write(event)
    backend.close()

    content = output_path.read_text(encoding="utf-8")
    lines = [line for line in content.splitlines() if line.strip()]
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["event_id"] == event.event_id
    assert parsed["event_type"] == event.event_type


# ─── Test: EncryptionProvider round-trip ─────────────────────────────────────


def test_encryption_provider_round_trip():
    """EncryptionProvider.encrypt_line / decrypt_line round-trip."""
    key = _make_key()
    provider = EncryptionProvider(key)
    original = "hello encryption world"
    encrypted = provider.encrypt_line(original)
    assert encrypted != original
    assert original not in encrypted
    recovered = provider.decrypt_line(encrypted)
    assert recovered == original
