"""Shared pytest fixtures and HA-stub bootstrapping.

Pure-unit tests (storage, ledger) run without homeassistant installed.
We install minimal stubs into sys.modules so that importing
custom_components.splitsmart.storage / ledger works without triggering
the HA-dependent __init__.py.

Integration tests that actually need HA use pytest-homeassistant-custom-component
fixtures declared in this file once that package is available.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys
import types

_ROOT = pathlib.Path(__file__).parent.parent


def _load(dotted: str, rel_path: str):
    """Load a module from a file path, bypassing package __init__ execution."""
    path = _ROOT / rel_path
    spec = importlib.util.spec_from_file_location(dotted, path)
    mod = types.ModuleType(dotted)
    mod.__spec__ = spec  # type: ignore[assignment]
    sys.modules[dotted] = mod
    assert spec and spec.loader
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _stub_package(dotted: str) -> types.ModuleType:
    if dotted not in sys.modules:
        mod = types.ModuleType(dotted)
        sys.modules[dotted] = mod
    return sys.modules[dotted]


# Stub out the HA-dependent package root so sub-modules can be imported cleanly.
_stub_package("custom_components")
_stub_package("custom_components.splitsmart")

# Load const first (no external deps)
const = _load("custom_components.splitsmart.const", "custom_components/splitsmart/const.py")
# Attach to stub package so relative imports work
sys.modules["custom_components.splitsmart"].const = const  # type: ignore[attr-defined]

# Load storage (depends only on aiofiles + python-ulid + const)
storage = _load("custom_components.splitsmart.storage", "custom_components/splitsmart/storage.py")
sys.modules["custom_components.splitsmart"].storage = storage  # type: ignore[attr-defined]

# Load ledger (depends only on const + storage)
ledger = _load("custom_components.splitsmart.ledger", "custom_components/splitsmart/ledger.py")
sys.modules["custom_components.splitsmart"].ledger = ledger  # type: ignore[attr-defined]
