"""Splitsmart sensor entities."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_PARTICIPANTS,
    DOMAIN,
    SENSOR_BALANCE,
    SENSOR_LAST_EXPENSE,
    SENSOR_SPENDING_MONTH,
    SENSOR_SPENDING_TOTAL_MONTH,
)
from .coordinator import SplitsmartCoordinator
from .ledger import compute_monthly_spending

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Splitsmart sensors from a config entry."""
    coordinator: SplitsmartCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    participants: list[str] = entry.data[CONF_PARTICIPANTS]
    home_currency: str = coordinator.home_currency

    # Resolve display names once at setup; fall back to user_id if user deleted.
    user_names: dict[str, str] = {}
    for user_id in participants:
        user = await hass.auth.async_get_user(user_id)
        user_names[user_id] = user.name if user is not None else user_id

    entities: list[SensorEntity] = []

    # Per-participant sensors
    for user_id in participants:
        display_name = user_names[user_id]
        entities.append(BalanceSensor(coordinator, entry, user_id, display_name, home_currency))
        entities.append(
            SpendingMonthSensor(coordinator, entry, user_id, display_name, home_currency)
        )

    # Integration-level sensors
    entities.append(SpendingTotalMonthSensor(coordinator, entry, home_currency))
    entities.append(LastExpenseSensor(coordinator, entry))

    async_add_entities(entities)

    # Month-rollover listener — fires at 00:00:01 on the first day of each month.
    # Unsubscribes on integration unload via entry.async_on_unload.
    @callback
    def _handle_month_rollover(now: datetime) -> None:
        if now.day == 1:
            for entity in entities:
                entity.async_write_ha_state()

    unsub = async_track_time_change(hass, _handle_month_rollover, hour=0, minute=0, second=1)
    entry.async_on_unload(unsub)


# ------------------------------------------------------------------ base


class _SplitsmartSensor(CoordinatorEntity[SplitsmartCoordinator], SensorEntity):
    """Common base for all Splitsmart sensors."""

    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(
        self,
        coordinator: SplitsmartCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Splitsmart",
            model="Household finance",
        )


# ------------------------------------------------------------------ balance


class BalanceSensor(_SplitsmartSensor):
    """Net balance for one participant. Positive = owed to them, negative = they owe."""

    _attr_device_class = SensorDeviceClass.MONETARY

    def __init__(
        self,
        coordinator: SplitsmartCoordinator,
        entry: ConfigEntry,
        user_id: str,
        display_name: str,
        home_currency: str,
    ) -> None:
        super().__init__(coordinator, entry)
        self._user_id = user_id
        self._display_name = display_name
        self._attr_unique_id = f"{entry.entry_id}_{SENSOR_BALANCE}_{user_id}"
        self._attr_native_unit_of_measurement = home_currency
        self._attr_translation_key = SENSOR_BALANCE

    @property
    def name(self) -> str:
        return f"Balance {self._display_name}"

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data is None:
            return None
        balance: Decimal = self.coordinator.data.balances.get(self._user_id, Decimal("0"))
        return float(balance.quantize(Decimal("0.01")))

    # NOTE: per_partner is unused by the M2 card (computePairwise in
    # frontend/src/util/balances.ts is the source of truth for Settle Up
    # suggestions). Retained for possible M7 use (dashboard entity cards,
    # voice assistants). If the two calculations drift, fix it here —
    # never prefer the sensor attribute over the frontend computation
    # during M2-M6.
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if self.coordinator.data is None:
            return {}
        pairwise = self.coordinator.data.pairwise
        per_partner: dict[str, float] = {}
        for (a, b), amount in pairwise.items():
            if a == self._user_id:
                per_partner[b] = float(amount.quantize(Decimal("0.01")))
        return {
            "per_partner": per_partner,
            "home_currency": self.coordinator.home_currency,
        }


# ------------------------------------------------------------------ monthly spending (per user)


class SpendingMonthSensor(_SplitsmartSensor):
    """User's share of shared spend for the current calendar month."""

    _attr_device_class = SensorDeviceClass.MONETARY

    def __init__(
        self,
        coordinator: SplitsmartCoordinator,
        entry: ConfigEntry,
        user_id: str,
        display_name: str,
        home_currency: str,
    ) -> None:
        super().__init__(coordinator, entry)
        self._user_id = user_id
        self._display_name = display_name
        self._attr_unique_id = f"{entry.entry_id}_{SENSOR_SPENDING_MONTH}_{user_id}"
        self._attr_native_unit_of_measurement = home_currency
        self._attr_translation_key = SENSOR_SPENDING_MONTH

    @property
    def name(self) -> str:
        return f"Spending this month {self._display_name}"

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data is None:
            return None
        now = datetime.now(tz=UTC).astimezone()
        result = compute_monthly_spending(
            self.coordinator.data.expenses, self._user_id, now.year, now.month
        )
        return float(result["total"].quantize(Decimal("0.01")))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if self.coordinator.data is None:
            return {}
        now = datetime.now(tz=UTC).astimezone()
        result = compute_monthly_spending(
            self.coordinator.data.expenses, self._user_id, now.year, now.month
        )
        return {
            "by_category": {
                k: float(v.quantize(Decimal("0.01"))) for k, v in result["by_category"].items()
            },
            "month": now.strftime("%Y-%m"),
            "home_currency": self.coordinator.home_currency,
        }


# ------------------------------------------------------------------ monthly spending (total)


class SpendingTotalMonthSensor(_SplitsmartSensor):
    """Household total shared spend for the current calendar month."""

    _attr_device_class = SensorDeviceClass.MONETARY

    def __init__(
        self,
        coordinator: SplitsmartCoordinator,
        entry: ConfigEntry,
        home_currency: str,
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_{SENSOR_SPENDING_TOTAL_MONTH}"
        self._attr_native_unit_of_measurement = home_currency
        self._attr_translation_key = SENSOR_SPENDING_TOTAL_MONTH
        self._attr_name = "Total spending this month"

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data is None:
            return None
        now = datetime.now(tz=UTC).astimezone()
        result = compute_monthly_spending(self.coordinator.data.expenses, None, now.year, now.month)
        return float(result["total"].quantize(Decimal("0.01")))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if self.coordinator.data is None:
            return {}
        now = datetime.now(tz=UTC).astimezone()
        result = compute_monthly_spending(self.coordinator.data.expenses, None, now.year, now.month)
        return {
            "by_category": {
                k: float(v.quantize(Decimal("0.01"))) for k, v in result["by_category"].items()
            },
            "month": now.strftime("%Y-%m"),
            "home_currency": self.coordinator.home_currency,
        }


# ------------------------------------------------------------------ last expense


class LastExpenseSensor(_SplitsmartSensor):
    """Description of the most recent shared expense."""

    _attr_state_class = None
    _attr_device_class = None

    def __init__(
        self,
        coordinator: SplitsmartCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_{SENSOR_LAST_EXPENSE}"
        self._attr_translation_key = SENSOR_LAST_EXPENSE
        self._attr_name = "Last expense"

    @property
    def native_value(self) -> str | None:
        if self.coordinator.data is None or not self.coordinator.data.expenses:
            return None
        last = max(
            self.coordinator.data.expenses,
            key=lambda e: e.get("created_at", ""),
        )
        return last.get("description")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if self.coordinator.data is None or not self.coordinator.data.expenses:
            return {}
        last = max(
            self.coordinator.data.expenses,
            key=lambda e: e.get("created_at", ""),
        )
        return {
            "amount": last.get("home_amount"),
            "date": last.get("date"),
            "paid_by": last.get("paid_by"),
            "expense_id": last.get("id"),
        }
