# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0

"""forwarder_started / forwarder_stopped records, mirroring agent-sensor audit.rs."""

import json
import os

import observra
from observra.backends.webhook import WebhookBackend
from observra.core import host_context, lifecycle


def test_initialize_writes_started_then_stopped(tmp_path):
    path = tmp_path / "t.jsonl"
    observra.initialize(backend="jsonl", path=str(path))
    observra._worker._shutdown()

    started, stopped = (json.loads(line) for line in path.read_text().splitlines())
    assert started["type"] == "forwarder_started"
    assert started["session"] == "fwd-self"
    assert started["framework"] == "observra"
    assert started["data"]["action"] == "policy_event"
    assert started["data"]["pid"] == os.getpid()
    assert started["data"]["destinations"] == [f"jsonl:{path}"]
    assert stopped["type"] == "forwarder_stopped"
    assert stopped["data"]["uptime_secs"] >= 0
    assert stopped["data"]["pid"] == os.getpid()


def test_destination_url_drops_credentials_and_query():
    backend = WebhookBackend(url="https://user:pw@siem.example.com:8443/ingest?token=abc")
    assert lifecycle.destinations(backend) == ["webhook:https://siem.example.com:8443/ingest"]


def test_device_id_is_sha256_of_machine_id(monkeypatch):
    monkeypatch.setattr(host_context, "_read_machine_id", lambda: "abc123")
    assert host_context._read_device_id() == "6ca13d52ca70c883e0f0bb101e425a89e8624de51db2d2392593af6a84118090"
    monkeypatch.setattr(host_context, "_read_machine_id", lambda: None)
    assert host_context._read_device_id() is None
