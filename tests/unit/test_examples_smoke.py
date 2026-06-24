# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Smoke tests for the documented ADK integration pattern and shipped examples.

These guard the getting-started docs and examples/ against silent rot. They
exist because docs/getting-started/adk.md once shipped a snippet that called
initialize() without create_plugin(), which captures nothing — see issue #32.

ADK is required (the [adk] extra). Tests skip cleanly when google-adk is absent.
"""

import os
import subprocess
import sys
import textwrap
import types
from pathlib import Path

import pytest

pytest.importorskip("google.adk", reason="requires the [adk] extra")

from google.adk.plugins import BasePlugin  # noqa: E402

import observra  # noqa: E402

EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "examples"


@pytest.fixture
def jsonl_pipeline(tmp_path):
    """Initialize the global pipeline against a temp JSONL file."""
    from observra.core.dedup import reset_dedup

    reset_dedup()  # emit() dedups on (event_type, span_id); start clean
    observra.initialize(backend="jsonl", path=str(tmp_path / "telemetry.jsonl"))


def test_create_plugin_returns_real_adk_plugin(jsonl_pipeline):
    """The documented `create_plugin()` step must yield a real ADK BasePlugin.

    This is the step the broken adk.md snippet omitted: initialize() alone does
    not produce anything to register with a Runner.
    """
    plugin = observra.create_plugin()  # framework="adk" is the default
    assert isinstance(plugin, BasePlugin)
    assert plugin.framework_name == "adk"


@pytest.mark.asyncio
async def test_documented_pattern_routes_telemetry_to_pipeline(jsonl_pipeline):
    """initialize() + create_plugin() + driving callbacks must enqueue telemetry.

    With a real pipeline the plugin routes events to the backend queue (not its
    in-memory list), so we assert the queue received them. This is exactly what
    the broken adk.md snippet failed to do: without create_plugin(), nothing is
    ever enqueued.
    """
    before = observra.get_stats().get("enqueued", 0)
    plugin = observra.create_plugin()

    callback_context = types.SimpleNamespace()
    usage_metadata = types.SimpleNamespace(
        prompt_token_count=120,
        candidates_token_count=40,
        total_token_count=160,
        cached_content_token_count=0,
        thoughts_token_count=0,
    )
    llm_response = types.SimpleNamespace(model="gemini-2.5-flash", usage_metadata=usage_metadata)

    await plugin.before_model_callback(
        callback_context=callback_context,
        llm_request=types.SimpleNamespace(model="gemini-2.5-flash"),
    )
    await plugin.after_model_callback(callback_context=callback_context, llm_response=llm_response)

    after = observra.get_stats().get("enqueued", 0)
    assert after > before, "driving the plugin callbacks enqueued no telemetry"


def test_capture_tool_data_is_a_create_plugin_kwarg(jsonl_pipeline):
    """capture_tool_data belongs on create_plugin(), not initialize().

    Guards the sample_agent bug where initialize(capture_tool_data=True)
    silently dropped the flag into the backend kwargs.
    """
    plugin = observra.create_plugin(capture_tool_data=True)
    assert plugin._capture_tool_data is True


def _run_example_driver(path: Path, asserts: str, tmp_path: Path, env_extra: dict | None = None):
    """Import an example file in a clean subprocess and run assertions on it.

    A subprocess gives a pristine sys.modules (other tests in the suite stub
    google.adk), and doubles as a check that the example runs as a script.
    """
    driver = textwrap.dedent(f"""
        import importlib.util
        spec = importlib.util.spec_from_file_location("example", r"{path}")
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        from google.adk.plugins import BasePlugin
        {asserts}
        print("OK")
    """)
    env = {"PATH": os.environ.get("PATH", "")}
    if env_extra:
        env.update(env_extra)
    result = subprocess.run(
        [sys.executable, "-c", driver],
        cwd=str(tmp_path),  # example writes its telemetry file here
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, f"example failed to run:\n{result.stderr}"
    assert "OK" in result.stdout


def test_add_telemetry_example_constructs(tmp_path):
    """examples/add_telemetry_to_agent.py must import and wire a Runner cleanly."""
    _run_example_driver(
        EXAMPLES_DIR / "add_telemetry_to_agent.py",
        asserts="assert isinstance(m.plugin, BasePlugin); assert m.runner is not None",
        tmp_path=tmp_path,
    )


def test_sample_agent_example_imports(tmp_path):
    """examples/sample_agent/agent.py must import and expose root_agent (telemetry off)."""
    _run_example_driver(
        EXAMPLES_DIR / "sample_agent" / "agent.py",
        asserts="assert m.root_agent is not None; assert m.telemetry_plugin is None",
        tmp_path=tmp_path,
    )
