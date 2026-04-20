"""Tests for sensor entities.

Instantiates sensor classes directly with mocked coordinator and entry —
no HA event loop required.
"""

from __future__ import annotations

import pathlib
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import pytest

from custom_components.splitsmart.const import DOMAIN
from custom_components.splitsmart.coordinator import SplitsmartCoordinator
from custom_components.splitsmart.ledger import build_expense_record
from custom_components.splitsmart.sensor import (
    BalanceSensor,
    LastExpenseSensor,
    SpendingMonthSensor,
    SpendingTotalMonthSensor,
)
from custom_components.splitsmart.storage import SplitsmartStorage

# ------------------------------------------------------------------ fixtures


@pytest.fixture
async def storage(tmp_path: pathlib.Path) -> SplitsmartStorage:
    s = SplitsmartStorage(tmp_path / "splitsmart")
    await s.ensure_layout()
    return s


@pytest.fixture
async def coordinator(storage: SplitsmartStorage) -> SplitsmartCoordinator:
    hass = MagicMock()
    hass.bus = MagicMock()
    hass.bus.async_fire = MagicMock()
    coord = SplitsmartCoordinator(
        hass,
        storage,
        participants=["u1", "u2"],
        home_currency="GBP",
        categories=["Groceries", "Household", "Alcohol"],
        config_entry=None,
    )
    coord.data = await coord._async_update_data()
    return coord


@pytest.fixture
def entry() -> MagicMock:
    e = MagicMock()
    e.entry_id = "test_entry"
    e.data = {"participants": ["u1", "u2"], "home_currency": "GBP", "categories": ["Groceries"]}
    return e


def _tesco_expense() -> dict[str, Any]:
    return build_expense_record(
        date="2026-04-15",
        description="Tesco Metro",
        paid_by="u1",
        amount=82.40,
        currency="GBP",
        home_currency="GBP",
        categories=[
            {
                "name": "Groceries",
                "home_amount": 55.20,
                "split": {
                    "method": "equal",
                    "shares": [{"user_id": "u1", "value": 50}, {"user_id": "u2", "value": 50}],
                },
            },
            {
                "name": "Household",
                "home_amount": 18.70,
                "split": {
                    "method": "equal",
                    "shares": [{"user_id": "u1", "value": 50}, {"user_id": "u2", "value": 50}],
                },
            },
            {
                "name": "Alcohol",
                "home_amount": 8.50,
                "split": {
                    "method": "exact",
                    "shares": [{"user_id": "u1", "value": 8.50}, {"user_id": "u2", "value": 0.00}],
                },
            },
        ],
        notes=None,
        source="manual",
        staging_id=None,
        receipt_path=None,
        created_by="u1",
    )


# ------------------------------------------------------------------ BalanceSensor


async def test_balance_sensor_positive_for_payer(
    coordinator: SplitsmartCoordinator, storage: SplitsmartStorage, entry: MagicMock
):
    expense = _tesco_expense()
    await storage.append(storage.expenses_path, expense)
    await coordinator.async_note_write()

    sensor = BalanceSensor(coordinator, entry, "u1", "u1", "GBP")
    assert sensor.native_value == 36.95


async def test_balance_sensor_negative_for_debtor(
    coordinator: SplitsmartCoordinator, storage: SplitsmartStorage, entry: MagicMock
):
    expense = _tesco_expense()
    await storage.append(storage.expenses_path, expense)
    await coordinator.async_note_write()

    sensor = BalanceSensor(coordinator, entry, "u2", "u2", "GBP")
    assert sensor.native_value == -36.95


def test_balance_sensor_none_when_no_data(coordinator: SplitsmartCoordinator, entry: MagicMock):
    coordinator.data = None  # type: ignore[assignment]
    sensor = BalanceSensor(coordinator, entry, "u1", "u1", "GBP")
    assert sensor.native_value is None
    assert sensor.extra_state_attributes == {}


async def test_balance_sensor_per_partner_attribute(
    coordinator: SplitsmartCoordinator, storage: SplitsmartStorage, entry: MagicMock
):
    await storage.append(storage.expenses_path, _tesco_expense())
    await coordinator.async_note_write()

    sensor = BalanceSensor(coordinator, entry, "u1", "u1", "GBP")
    attrs = sensor.extra_state_attributes
    assert attrs["home_currency"] == "GBP"
    assert "per_partner" in attrs


# ------------------------------------------------------------------ SpendingMonthSensor


async def test_spending_month_sensor_current_month(
    coordinator: SplitsmartCoordinator, storage: SplitsmartStorage, entry: MagicMock
):
    # Use an expense dated to the actual current month so the sensor picks it up
    now = datetime.now(tz=UTC).astimezone()
    expense = build_expense_record(
        date=now.strftime("%Y-%m-15"),
        description="Supermarket",
        paid_by="u1",
        amount=100.00,
        currency="GBP",
        home_currency="GBP",
        categories=[
            {
                "name": "Groceries",
                "home_amount": 100.00,
                "split": {
                    "method": "equal",
                    "shares": [{"user_id": "u1", "value": 50}, {"user_id": "u2", "value": 50}],
                },
            }
        ],
        notes=None,
        source="manual",
        staging_id=None,
        receipt_path=None,
        created_by="u1",
    )
    await storage.append(storage.expenses_path, expense)
    await coordinator.async_note_write()

    sensor = SpendingMonthSensor(coordinator, entry, "u1", "u1", "GBP")
    assert sensor.native_value == 50.0
    attrs = sensor.extra_state_attributes
    assert "by_category" in attrs
    assert attrs["by_category"]["Groceries"] == 50.0
    assert attrs["home_currency"] == "GBP"
    assert "month" in attrs


async def test_spending_month_sensor_excludes_other_months(
    coordinator: SplitsmartCoordinator, storage: SplitsmartStorage, entry: MagicMock
):
    # Expense in January 2000 — definitely not current month
    expense = build_expense_record(
        date="2000-01-15",
        description="Ancient expense",
        paid_by="u1",
        amount=100.00,
        currency="GBP",
        home_currency="GBP",
        categories=[
            {
                "name": "Groceries",
                "home_amount": 100.00,
                "split": {
                    "method": "equal",
                    "shares": [{"user_id": "u1", "value": 50}, {"user_id": "u2", "value": 50}],
                },
            }
        ],
        notes=None,
        source="manual",
        staging_id=None,
        receipt_path=None,
        created_by="u1",
    )
    await storage.append(storage.expenses_path, expense)
    await coordinator.async_note_write()

    sensor = SpendingMonthSensor(coordinator, entry, "u1", "u1", "GBP")
    assert sensor.native_value == 0.0


# ------------------------------------------------------------------ SpendingTotalMonthSensor


async def test_spending_total_month_sensor_attributes(
    coordinator: SplitsmartCoordinator, storage: SplitsmartStorage, entry: MagicMock
):
    now = datetime.now(tz=UTC).astimezone()
    expense = build_expense_record(
        date=now.strftime("%Y-%m-15"),
        description="Shop",
        paid_by="u1",
        amount=60.00,
        currency="GBP",
        home_currency="GBP",
        categories=[
            {
                "name": "Groceries",
                "home_amount": 60.00,
                "split": {
                    "method": "equal",
                    "shares": [{"user_id": "u1", "value": 50}, {"user_id": "u2", "value": 50}],
                },
            }
        ],
        notes=None,
        source="manual",
        staging_id=None,
        receipt_path=None,
        created_by="u1",
    )
    await storage.append(storage.expenses_path, expense)
    await coordinator.async_note_write()

    sensor = SpendingTotalMonthSensor(coordinator, entry, "GBP")
    assert sensor.native_value == 60.0
    assert sensor.extra_state_attributes["home_currency"] == "GBP"
    assert "by_category" in sensor.extra_state_attributes


# ------------------------------------------------------------------ LastExpenseSensor


async def test_last_expense_sensor(
    coordinator: SplitsmartCoordinator, storage: SplitsmartStorage, entry: MagicMock
):
    expense = _tesco_expense()
    await storage.append(storage.expenses_path, expense)
    await coordinator.async_note_write()

    sensor = LastExpenseSensor(coordinator, entry)
    assert sensor.native_value == "Tesco Metro"
    attrs = sensor.extra_state_attributes
    assert attrs["expense_id"] == expense["id"]
    assert attrs["amount"] == 82.40
    assert attrs["paid_by"] == "u1"


def test_last_expense_sensor_none_when_empty(coordinator: SplitsmartCoordinator, entry: MagicMock):
    sensor = LastExpenseSensor(coordinator, entry)
    assert sensor.native_value is None
    assert sensor.extra_state_attributes == {}


# ------------------------------------------------------------------ state_class / device_class


def test_sensor_class_attributes(entry: MagicMock):
    from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass

    coord = MagicMock()
    coord.home_currency = "GBP"

    b = BalanceSensor(coord, entry, "u1", "u1", "GBP")
    assert b._attr_state_class == SensorStateClass.TOTAL
    assert b._attr_device_class == SensorDeviceClass.MONETARY
    assert b._attr_native_unit_of_measurement == "GBP"
    assert "u1" in b._attr_unique_id

    s = SpendingMonthSensor(coord, entry, "u1", "u1", "GBP")
    assert s._attr_native_unit_of_measurement == "GBP"
    assert "u1" in s._attr_unique_id

    t = SpendingTotalMonthSensor(coord, entry, "GBP")
    assert t._attr_native_unit_of_measurement == "GBP"

    le = LastExpenseSensor(coord, entry)
    assert "last_expense" in le._attr_unique_id


# ------------------------------------------------------------------ entity names and device


def test_entity_names_and_device_info(entry: MagicMock):
    """Assert names produce the expected entity_id slugs and all sensors share a device."""
    coord = MagicMock()
    coord.home_currency = "GBP"

    chris_balance = BalanceSensor(coord, entry, "abc123", "Chris", "GBP")
    slav_balance = BalanceSensor(coord, entry, "def456", "Slav", "GBP")
    chris_spending = SpendingMonthSensor(coord, entry, "abc123", "Chris", "GBP")
    slav_spending = SpendingMonthSensor(coord, entry, "def456", "Slav", "GBP")
    total_spending = SpendingTotalMonthSensor(coord, entry, "GBP")
    last_expense = LastExpenseSensor(coord, entry)

    # Names — HA combines device name "Splitsmart" with these to form entity_ids:
    #   sensor.splitsmart_balance_chris, sensor.splitsmart_balance_slav,
    #   sensor.splitsmart_spending_this_month_chris, sensor.splitsmart_spending_this_month_slav,
    #   sensor.splitsmart_total_spending_this_month, sensor.splitsmart_last_expense
    assert chris_balance.name == "Balance Chris"
    assert slav_balance.name == "Balance Slav"
    assert chris_spending.name == "Spending this month Chris"
    assert slav_spending.name == "Spending this month Slav"
    assert total_spending._attr_name == "Total spending this month"
    assert last_expense._attr_name == "Last expense"

    # unique_id is keyed on user_id — stable across display-name renames
    assert "abc123" in chris_balance._attr_unique_id
    assert "def456" in slav_balance._attr_unique_id
    assert "abc123" in chris_spending._attr_unique_id
    assert "def456" in slav_spending._attr_unique_id

    # All sensors share the same device, identified by (DOMAIN, entry_id)
    all_sensors = [
        chris_balance,
        slav_balance,
        chris_spending,
        slav_spending,
        total_spending,
        last_expense,
    ]
    for sensor in all_sensors:
        info = sensor.device_info
        assert info is not None
        assert (DOMAIN, "test_entry") in info["identifiers"]
        assert info["name"] == "Splitsmart"
        assert info["model"] == "Household finance"


# config_flow tests require Linux/phcc (ha_integration — pytest -m ha_integration)
