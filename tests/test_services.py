"""Tests for service handlers.

Calls handler functions directly with mock ServiceCall objects — no HA
event loop or hass fixture needed.
"""

from __future__ import annotations

import pathlib
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.splitsmart.const import DOMAIN
from custom_components.splitsmart.coordinator import SplitsmartCoordinator

# Import handler functions directly
from custom_components.splitsmart.services import (
    _handle_add_expense,
    _handle_add_settlement,
    _handle_delete_expense,
    _handle_delete_settlement,
    _handle_edit_expense,
    _handle_edit_settlement,
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
    from unittest.mock import MagicMock

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
    # Patch async_note_write to call through (it updates coord.data in-place)
    coord.async_note_write = AsyncMock(side_effect=coord.async_note_write)
    return coord


def _make_hass(storage: SplitsmartStorage, coordinator: SplitsmartCoordinator) -> MagicMock:
    hass = MagicMock()
    hass.data = {
        DOMAIN: {"test_entry": {"storage": storage, "coordinator": coordinator, "entry": None}}
    }
    return hass


def _make_call(hass: MagicMock, data: dict[str, Any], user_id: str = "u1") -> MagicMock:
    call = MagicMock()
    call.hass = hass
    call.data = data
    call.context = MagicMock()
    call.context.user_id = user_id
    return call


def _tesco_data() -> dict[str, Any]:
    return {
        "date": "2026-04-15",
        "description": "Tesco Metro",
        "paid_by": "u1",
        "amount": 82.40,
        "currency": "GBP",
        "categories": [
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
    }


# ------------------------------------------------------------------ add_expense


async def test_add_expense_tesco(storage: SplitsmartStorage, coordinator: SplitsmartCoordinator):
    hass = _make_hass(storage, coordinator)
    result = await _handle_add_expense(_make_call(hass, _tesco_data()))

    assert result["id"].startswith("ex_")
    records = await storage.read_all(storage.expenses_path)
    assert len(records) == 1
    assert records[0]["description"] == "Tesco Metro"
    assert records[0]["home_amount"] == 82.40
    # Coordinator updated
    assert coordinator.data.balances["u1"] == Decimal("36.95")
    assert coordinator.data.balances["u2"] == Decimal("-36.95")


async def test_add_expense_monthly_spending_attributes(
    storage: SplitsmartStorage, coordinator: SplitsmartCoordinator
):
    hass = _make_hass(storage, coordinator)
    await _handle_add_expense(_make_call(hass, _tesco_data()))

    from custom_components.splitsmart.ledger import compute_monthly_spending

    result = compute_monthly_spending(coordinator.data.expenses, "u1", 2026, 4)
    assert result["by_category"]["Alcohol"] == Decimal("8.50")
    assert result["by_category"]["Groceries"] == Decimal("27.60")


async def test_add_expense_foreign_currency_rejected(
    storage: SplitsmartStorage, coordinator: SplitsmartCoordinator
):
    from homeassistant.exceptions import ServiceValidationError

    hass = _make_hass(storage, coordinator)
    data = _tesco_data()
    data["currency"] = "USD"
    with pytest.raises(ServiceValidationError, match="M3"):
        await _handle_add_expense(_make_call(hass, data))


async def test_add_expense_non_participant_paid_by_rejected(
    storage: SplitsmartStorage, coordinator: SplitsmartCoordinator
):
    from homeassistant.exceptions import ServiceValidationError

    hass = _make_hass(storage, coordinator)
    data = _tesco_data()
    data["paid_by"] = "stranger"
    with pytest.raises(ServiceValidationError):
        await _handle_add_expense(_make_call(hass, data))


async def test_add_expense_non_participant_caller_rejected(
    storage: SplitsmartStorage, coordinator: SplitsmartCoordinator
):
    from homeassistant.exceptions import ServiceValidationError

    hass = _make_hass(storage, coordinator)
    with pytest.raises(ServiceValidationError, match="participant"):
        await _handle_add_expense(_make_call(hass, _tesco_data(), user_id="intruder"))


# ------------------------------------------------------------------ add_settlement


async def test_add_settlement_reduces_balance(
    storage: SplitsmartStorage, coordinator: SplitsmartCoordinator
):
    hass = _make_hass(storage, coordinator)
    await _handle_add_expense(_make_call(hass, _tesco_data()))

    result = await _handle_add_settlement(
        _make_call(
            hass,
            {
                "date": "2026-04-20",
                "from_user": "u2",
                "to_user": "u1",
                "amount": 36.95,
            },
        )
    )
    assert result["id"].startswith("sl_")
    assert coordinator.data.balances.get("u1", Decimal("0")) == Decimal("0.00")
    assert coordinator.data.balances.get("u2", Decimal("0")) == Decimal("0.00")


# ------------------------------------------------------------------ edit_expense


async def test_edit_expense_new_record_before_tombstone(
    storage: SplitsmartStorage, coordinator: SplitsmartCoordinator
):
    hass = _make_hass(storage, coordinator)
    add_result = await _handle_add_expense(_make_call(hass, _tesco_data()))
    original_id = add_result["id"]

    edit_result = await _handle_edit_expense(
        _make_call(
            hass,
            {
                "id": original_id,
                "date": "2026-04-15",
                "description": "Tesco Metro (corrected)",
                "paid_by": "u1",
                "amount": 50.00,
                "categories": [
                    {
                        "name": "Groceries",
                        "home_amount": 50.00,
                        "split": {
                            "method": "equal",
                            "shares": [
                                {"user_id": "u1", "value": 50},
                                {"user_id": "u2", "value": 50},
                            ],
                        },
                    },
                ],
            },
        )
    )
    new_id = edit_result["id"]
    assert new_id != original_id

    # expenses.jsonl: original first, new appended after (new record written before tombstone)
    all_expenses = await storage.read_all(storage.expenses_path)
    assert len(all_expenses) == 2
    assert all_expenses[1]["id"] == new_id  # new appended after original

    # Tombstone exists and points to original
    tombstones = await storage.read_all(storage.tombstones_path)
    assert tombstones[0]["target_id"] == original_id
    assert tombstones[0]["operation"] == "edit"
    assert tombstones[0]["previous_snapshot"]["description"] == "Tesco Metro"

    # Coordinator sees only new record
    assert len(coordinator.data.expenses) == 1
    assert coordinator.data.expenses[0]["description"] == "Tesco Metro (corrected)"
    assert coordinator.data.balances["u1"] == Decimal("25.00")


async def test_edit_expense_nonexistent_raises(
    storage: SplitsmartStorage, coordinator: SplitsmartCoordinator
):
    from homeassistant.exceptions import ServiceValidationError

    hass = _make_hass(storage, coordinator)
    with pytest.raises(ServiceValidationError, match="not found"):
        await _handle_edit_expense(
            _make_call(
                hass,
                {
                    "id": "ex_ghost",
                    "date": "2026-04-15",
                    "description": "X",
                    "paid_by": "u1",
                    "amount": 10.00,
                    "categories": [
                        {
                            "name": "Groceries",
                            "home_amount": 10.00,
                            "split": {
                                "method": "equal",
                                "shares": [
                                    {"user_id": "u1", "value": 50},
                                    {"user_id": "u2", "value": 50},
                                ],
                            },
                        }
                    ],
                },
            )
        )


# ------------------------------------------------------------------ delete_expense


async def test_delete_expense_tombstones_and_zeros_balance(
    storage: SplitsmartStorage, coordinator: SplitsmartCoordinator
):
    hass = _make_hass(storage, coordinator)
    add_result = await _handle_add_expense(_make_call(hass, _tesco_data()))
    expense_id = add_result["id"]

    del_result = await _handle_delete_expense(_make_call(hass, {"id": expense_id}))
    assert del_result["id"] == expense_id

    # Original still on disk (append-only) but coordinator sees none
    assert coordinator.data.expenses == []
    assert coordinator.data.balances.get("u1", Decimal("0")) == Decimal("0")


async def test_delete_expense_nonexistent_raises(
    storage: SplitsmartStorage, coordinator: SplitsmartCoordinator
):
    from homeassistant.exceptions import ServiceValidationError

    hass = _make_hass(storage, coordinator)
    with pytest.raises(ServiceValidationError, match="not found"):
        await _handle_delete_expense(_make_call(hass, {"id": "ex_ghost"}))


# ------------------------------------------------------------------ edit/delete settlement


async def test_edit_settlement(storage: SplitsmartStorage, coordinator: SplitsmartCoordinator):
    hass = _make_hass(storage, coordinator)
    await _handle_add_expense(_make_call(hass, _tesco_data()))
    add_sl = await _handle_add_settlement(
        _make_call(
            hass,
            {
                "date": "2026-04-20",
                "from_user": "u2",
                "to_user": "u1",
                "amount": 20.00,
            },
        )
    )
    sl_id = add_sl["id"]

    edit_result = await _handle_edit_settlement(
        _make_call(
            hass,
            {
                "id": sl_id,
                "date": "2026-04-20",
                "from_user": "u2",
                "to_user": "u1",
                "amount": 36.95,
            },
        )
    )
    assert edit_result["id"] != sl_id

    tombstones = await storage.read_all(storage.tombstones_path)
    assert any(tb["target_id"] == sl_id for tb in tombstones)


async def test_delete_settlement(storage: SplitsmartStorage, coordinator: SplitsmartCoordinator):
    hass = _make_hass(storage, coordinator)
    await _handle_add_expense(_make_call(hass, _tesco_data()))
    add_sl = await _handle_add_settlement(
        _make_call(
            hass,
            {
                "date": "2026-04-20",
                "from_user": "u2",
                "to_user": "u1",
                "amount": 36.95,
            },
        )
    )
    sl_id = add_sl["id"]

    del_result = await _handle_delete_settlement(_make_call(hass, {"id": sl_id}))
    assert del_result["id"] == sl_id
    assert coordinator.data.settlements == []
    # Balance reverts
    assert coordinator.data.balances["u1"] == Decimal("36.95")
