"""Splitsmart binary sensor entities."""

from __future__ import annotations

import datetime as dt
import logging
from datetime import timedelta
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SplitsmartCoordinator
from .fx import FxClient

_LOGGER = logging.getLogger(__name__)

_FX_HEALTHY_WINDOW = timedelta(hours=24)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Splitsmart binary sensors from a config entry."""
    coordinator: SplitsmartCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    fx_client: FxClient = hass.data[DOMAIN][entry.entry_id]["fx"]

    async_add_entities([FxHealthySensor(coordinator, entry, fx_client)])


class FxHealthySensor(CoordinatorEntity[SplitsmartCoordinator], BinarySensorEntity):
    """Reports whether the FX feed was reachable in the last 24 hours.

    State is ``on`` when the newest ``fetched_at`` entry in fx_rates.jsonl is
    within 24 hours of now; ``off`` otherwise (including on fresh installs with
    no foreign-currency activity — that is honest, not a false alarm).
    """

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True
    _attr_name = "FX healthy"

    def __init__(
        self,
        coordinator: SplitsmartCoordinator,
        entry: ConfigEntry,
        fx_client: FxClient,
    ) -> None:
        super().__init__(coordinator)
        self._fx_client = fx_client
        self._entry = entry
        self._last_success: dt.datetime | None = None
        self._attr_unique_id = f"{entry.entry_id}_fx_healthy"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Splitsmart",
            manufacturer="Splitsmart",
        )

    @property
    def is_on(self) -> bool:
        if self._last_success is None:
            return False
        now = dt.datetime.now(tz=dt.UTC)
        last = self._last_success
        if last.tzinfo is None:
            last = last.replace(tzinfo=dt.UTC)
        return (now - last) <= _FX_HEALTHY_WINDOW

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "last_checked": self._last_success.isoformat() if self._last_success else None,
        }

    def _handle_coordinator_update(self) -> None:
        """Refresh the cached last-success timestamp on every coordinator tick."""
        self.hass.async_create_task(self._async_refresh_last_success())

    async def _async_refresh_last_success(self) -> None:
        self._last_success = await self._fx_client.last_successful_fetch()
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # Populate immediately on setup so the sensor isn't stuck in None until
        # the next coordinator tick.
        self._last_success = await self._fx_client.last_successful_fetch()
