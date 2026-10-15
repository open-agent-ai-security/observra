# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Session id precedence and end-user id attribution."""

import contextvars

import observra
from observra.core.context import get_session_id, start_session
from observra.core.events import create_event


def _fresh(fn):
    return contextvars.Context().run(fn)


def test_framework_id_beats_app_id_beats_generated():
    def run():
        generated = start_session()
        assert len(generated) == 26  # ULID
        observra.set_session_id("app-conv")
        assert start_session() == "app-conv"
        assert start_session("framework-conv") == "framework-conv"
        assert get_session_id() == "framework-conv"

    _fresh(run)


def test_user_id_from_context_survives_redaction_and_hot_path():
    def run():
        observra.set_user_id("alice@example.com")
        cold = create_event("tool_end", tool_name="bash")
        hot = create_event("session_start")
        assert cold.data["user_id"] == "alice@example.com"
        assert hot.data["user_id"] == "alice@example.com"

    _fresh(run)


def test_adapter_user_id_wins_and_absent_when_unset():
    def run():
        assert "user_id" not in (create_event("tool_end").data or {})
        observra.set_user_id("ctx-user")
        assert create_event("user_message", user_id="adk-user").data["user_id"] == "adk-user"

    _fresh(run)
