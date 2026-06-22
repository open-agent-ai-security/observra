# Copyright 2026 Exabeam, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Tests verifying all deprecated symbols carry required metadata for CI and docs tooling."""
import importlib
import inspect
import pkgutil

import observra


def test_all_deprecated_symbols_have_removal_metadata():
    """Every symbol with __deprecated__=True must have removal_version and alternative."""
    missing = []
    for importer, modname, ispkg in pkgutil.walk_packages(
        path=observra.__path__,
        prefix="observra.",
        onerror=lambda x: None,
    ):
        try:
            mod = importlib.import_module(modname)
        except BaseException:
            continue  # skip optional deps and test-infrastructure modules
        for name, obj in inspect.getmembers(mod, callable):
            if getattr(obj, "__deprecated__", False):
                if not getattr(obj, "__removal_version__", None):
                    missing.append(f"{modname}.{name}: missing __removal_version__")
                if not getattr(obj, "__deprecation_alternative__", None):
                    missing.append(f"{modname}.{name}: missing __deprecation_alternative__")
    assert not missing, "Deprecated symbols missing metadata:\n" + "\n".join(missing)
