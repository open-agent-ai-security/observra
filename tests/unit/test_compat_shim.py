"""Tests for backward-compatible adk_telemetry import shim."""
import sys
import pytest


class TestCompatShim:
    """Verify adk_telemetry shim works with deprecation warning."""

    def test_import_adk_telemetry_warns(self):
        """Importing adk_telemetry fires DeprecationWarning."""
        # Clear cached module to force re-import and re-trigger warning
        sys.modules.pop("adk_telemetry", None)

        with pytest.warns(DeprecationWarning, match="adk_telemetry is deprecated"):
            import adk_telemetry  # noqa: F401

    def test_shim_exports_telemetry_plugin(self):
        """TelemetryPlugin is accessible from adk_telemetry."""
        from adk_telemetry import TelemetryPlugin  # noqa: F811
        from observra.adapters.adk.plugin import TelemetryPlugin as RealPlugin
        assert TelemetryPlugin is RealPlugin

    def test_shim_exports_telemetry_event(self):
        """TelemetryEvent is accessible from adk_telemetry."""
        from adk_telemetry import TelemetryEvent  # noqa: F811
        from observra.core.events import TelemetryEvent as RealEvent
        assert TelemetryEvent is RealEvent

    def test_shim_exports_initialize(self):
        """initialize() is accessible from adk_telemetry."""
        from adk_telemetry import initialize  # noqa: F811
        from observra import initialize as real_init
        assert initialize is real_init

    def test_shim_deprecation_message_targets_v2(self):
        """Deprecation message specifies 2.0 removal."""
        sys.modules.pop("adk_telemetry", None)

        with pytest.warns(DeprecationWarning, match="2.0"):
            import adk_telemetry  # noqa: F401, F811
