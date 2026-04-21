"""Splitsmart integration setup."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import (
    CONF_CATEGORIES,
    CONF_HOME_CURRENCY,
    CONF_PARTICIPANTS,
    DOMAIN,
    FONTS_DIRNAME,
    STATIC_URL,
)
from .coordinator import SplitsmartCoordinator
from .storage import SplitsmartStorage, validate_root

if TYPE_CHECKING:
    pass

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Splitsmart from a config entry."""
    storage_root = Path(hass.config.path("splitsmart"))

    try:
        validate_root(storage_root)
    except ValueError as err:
        _LOGGER.error("Unsafe storage path %s: %s", storage_root, err)
        raise ConfigEntryNotReady(f"Unsafe storage path: {err}") from err

    storage = SplitsmartStorage(storage_root)
    await storage.ensure_layout()

    # Merge entry.data with entry.options (options override data for mutable fields)
    participants: list[str] = entry.data[CONF_PARTICIPANTS]
    home_currency: str = entry.options.get(CONF_HOME_CURRENCY, entry.data[CONF_HOME_CURRENCY])
    categories: list[str] = entry.options.get(CONF_CATEGORIES, entry.data[CONF_CATEGORIES])

    coordinator = SplitsmartCoordinator(
        hass,
        storage,
        participants=participants,
        home_currency=home_currency,
        categories=categories,
        config_entry=entry,
    )

    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception as err:
        raise ConfigEntryNotReady(f"Failed initial ledger load: {err}") from err

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "storage": storage,
        "coordinator": coordinator,
        "entry": entry,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register services once (guarded so reloads don't double-register)
    if not hass.services.has_service(DOMAIN, "add_expense"):
        from .services import async_register_services

        async_register_services(hass)

    # Register websocket commands once per HA instance.
    from .websocket_api import async_register_websocket_commands

    async_register_websocket_commands(hass)

    # Register the frontend fonts static path once per HA instance. The bundle
    # static path and Lovelace auto-registration land in step 4 of M2.
    if not hass.data[DOMAIN].get("_fonts_registered"):
        frontend_dir = Path(__file__).parent / "frontend"
        await hass.http.async_register_static_paths(
            [
                StaticPathConfig(
                    url_path=f"{STATIC_URL}/{FONTS_DIRNAME}",
                    path=str(frontend_dir / FONTS_DIRNAME),
                    cache_headers=True,
                ),
            ]
        )
        hass.data[DOMAIN]["_fonts_registered"] = True

    # Invalidate coordinator when options change
    async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
        new_home_currency = entry.options.get(CONF_HOME_CURRENCY, entry.data[CONF_HOME_CURRENCY])
        new_categories = entry.options.get(CONF_CATEGORIES, entry.data[CONF_CATEGORIES])
        coordinator.home_currency = new_home_currency
        coordinator.categories = new_categories
        await coordinator.async_invalidate()
        await coordinator.async_refresh()

    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
        # Deregister services when last entry unloads
        if not hass.data[DOMAIN]:
            from .services import async_unregister_services

            async_unregister_services(hass)

    return unload_ok
