"""Shared pytest setup.

Registers `custom_components` and `custom_components.splitsmart` as proper
stub packages (with __path__) so sub-modules can be imported naturally by
Python without executing the HA-dependent __init__.py.

All test files then use normal `from custom_components.splitsmart.X import Y`
imports.  The HA-dependent __init__.py is never executed.
"""

from __future__ import annotations

import pathlib
import sys
import types

_ROOT = pathlib.Path(__file__).parent.parent
_CC_DIR = _ROOT / "custom_components"
_SS_DIR = _CC_DIR / "splitsmart"


def _make_stub_package(dotted: str, path: pathlib.Path) -> types.ModuleType:
    """Register a stub package in sys.modules with __path__ pointing to path."""
    if dotted in sys.modules:
        return sys.modules[dotted]
    mod = types.ModuleType(dotted)
    mod.__path__ = [str(path)]  # marks it as a package to Python
    mod.__package__ = dotted
    mod.__spec__ = None
    sys.modules[dotted] = mod
    return mod


# Register stub packages so sub-module imports resolve via the real filesystem
# without executing the HA-dependent __init__.py files.
_make_stub_package("custom_components", _CC_DIR)
_make_stub_package("custom_components.splitsmart", _SS_DIR)
