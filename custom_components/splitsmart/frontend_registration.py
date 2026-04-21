"""Serve the built card bundle and auto-register it as a Lovelace resource.

Runs once per HA instance, guarded via ``hass.data[DOMAIN]`` flags so
entry reloads do not double-register. The bundle URL carries a
``?v=<version>`` query string so browsers drop their cached copy when
the integration version changes.

Storage-mode Lovelace (the default) supports programmatic resource
registration via its collection. YAML-mode does not — when that is
detected, the integration logs the one-line snippet the user should
paste into their ``ui-lovelace.yaml``.
"""

from __future__ import annotations

import contextlib
import logging
from pathlib import Path
from typing import Any

from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from .const import BUNDLE_FILENAME, DOMAIN, FONTS_DIRNAME, STATIC_URL

_LOGGER = logging.getLogger(__name__)

_FLAG_STATIC = "_static_registered"
_FLAG_RESOURCE = "_resource_registered"


async def async_register_frontend(hass: HomeAssistant) -> None:
    """Register static paths and the Lovelace resource. Idempotent."""
    store = hass.data.setdefault(DOMAIN, {})

    if not store.get(_FLAG_STATIC):
        await _register_static_paths(hass)
        store[_FLAG_STATIC] = True

    if not store.get(_FLAG_RESOURCE):
        await _register_lovelace_resource(hass)
        # Flag is set regardless of mode so we don't retry on every reload.
        store[_FLAG_RESOURCE] = True


async def _register_static_paths(hass: HomeAssistant) -> None:
    """Serve the bundle and fonts under /splitsmart-static/."""
    frontend_dir = Path(__file__).parent / "frontend"
    configs = [
        StaticPathConfig(
            url_path=f"{STATIC_URL}/{BUNDLE_FILENAME}",
            path=str(frontend_dir / BUNDLE_FILENAME),
            # Bundle is versioned via query string; don't send a Cache-Control
            # max-age header that survives a version bump.
            cache_headers=False,
        ),
        StaticPathConfig(
            url_path=f"{STATIC_URL}/{FONTS_DIRNAME}",
            path=str(frontend_dir / FONTS_DIRNAME),
            cache_headers=True,
        ),
    ]
    await hass.http.async_register_static_paths(configs)


def _bundle_url_for(version: str) -> str:
    """``/splitsmart-static/splitsmart-card.js?v=<version>``."""
    return f"{STATIC_URL}/{BUNDLE_FILENAME}?v={version}"


async def _integration_version(hass: HomeAssistant) -> str:
    """Read version from manifest.json via HA's loader, falling back to 'dev'."""
    try:
        integration = await async_get_integration(hass, DOMAIN)
        return str(integration.version) if integration.version else "dev"
    except Exception:  # pragma: no cover — defensive only
        _LOGGER.debug("Could not resolve integration version; using 'dev'")
        return "dev"


async def _register_lovelace_resource(hass: HomeAssistant) -> None:
    """Add (or refresh) the module-type Lovelace resource pointing at the bundle.

    On YAML-mode Lovelace we can't mutate resources programmatically, so we
    log the snippet the user needs.
    """
    version = await _integration_version(hass)
    url = _bundle_url_for(version)

    lovelace: Any | None = hass.data.get("lovelace")
    resources = _lovelace_resources(lovelace)

    if resources is None:
        _LOGGER.info(
            "Lovelace is in YAML mode or unavailable — add this to your "
            "ui-lovelace.yaml resources:\n  - url: %s\n    type: module",
            url,
        )
        return

    # Some older / alternative collection implementations don't need or
    # expose async_load — suppress the one specific miss.
    with contextlib.suppress(AttributeError):
        await resources.async_load()

    items = list(_iter_resource_items(resources))
    base = f"{STATIC_URL}/{BUNDLE_FILENAME}"

    for item in items:
        if not isinstance(item, dict):
            continue
        existing_url = str(item.get("url", ""))
        if existing_url.split("?", 1)[0] == base:
            if existing_url == url:
                return  # Already current.
            await resources.async_update_item(item["id"], {"res_type": "module", "url": url})
            return

    await resources.async_create_item({"res_type": "module", "url": url})


def _lovelace_resources(lovelace: Any | None) -> Any | None:
    """Return the resources collection if Lovelace is in storage mode."""
    if lovelace is None:
        return None
    # Newer HA: hass.data['lovelace'] is a LovelaceData dataclass.
    resources = getattr(lovelace, "resources", None)
    if resources is None and isinstance(lovelace, dict):
        # Older shape.
        resources = lovelace.get("resources")
    if resources is None:
        return None

    # storage_collection.ResourceStorageCollection quacks with async_create_item;
    # YAML-mode YamlResourceCollection does not.
    if not hasattr(resources, "async_create_item"):
        return None
    return resources


def _iter_resource_items(resources: Any) -> Any:
    """Yield current items regardless of collection implementation detail."""
    if hasattr(resources, "async_items"):
        return resources.async_items()
    if hasattr(resources, "items"):
        data = resources.items
        return data() if callable(data) else data
    return []
