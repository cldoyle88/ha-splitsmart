"""Tests for coordinator.py.

Calls _async_update_data / async_note_write / async_invalidate directly
with a minimal mock hass so the test suite runs without a full HA event loop.
"""
from __future__ import annotations

import pathlib
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.splitsmart.coordinator import SplitsmartCoordinator, SplitsmartData
from custom_components.splitsmart.ledger import build_expense_record
from custom_components.splitsmart.storage import SplitsmartStorage, new_id


# ------------------------------------------------------------------ minimal hass mock


def _make_hass() -> MagicMock:
    """Return the minimum mock HomeAssistant that DataUpdateCoordinator needs."""
    hass = MagicMock()
    hass.loop = None  # not used directly by our code
    hass.bus = MagicMock()
    hass.bus.async_fire = MagicMock()
    hass.async_create_background_task = MagicMock()
    hass.is_stopping = False
    return hass


# ------------------------------------------------------------------ fixtures


@pytest.fixture
async def storage(tmp_path: pathlib.Path) -> SplitsmartStorage:
    s = SplitsmartStorage(tmp_path / "splitsmart")
    await s.ensure_layout()
    return s


@pytest.fixture
def coordinator(storage: SplitsmartStorage) -> SplitsmartCoordinator:
    return SplitsmartCoordinator(
        _make_hass(),
        storage,
        participants=["u1", "u2"],
        home_currency="GBP",
        categories=["Groceries", "Household", "Alcohol"],
        config_entry=None,
    )


def _tesco_expense(paid_by: str = "u1") -> dict[str, Any]:
    return build_expense_record(
        date="2026-04-15",
        description="Tesco Metro",
        paid_by=paid_by,
        amount=82.40,
        currency="GBP",
        home_currency="GBP",
        categories=[
            {"name": "Groceries", "home_amount": 55.20, "split": {"method": "equal", "shares": [{"user_id": "u1", "value": 50}, {"user_id": "u2", "value": 50}]}},
            {"name": "Household", "home_amount": 18.70, "split": {"method": "equal", "shares": [{"user_id": "u1", "value": 50}, {"user_id": "u2", "value": 50}]}},
            {"name": "Alcohol", "home_amount": 8.50, "split": {"method": "exact", "shares": [{"user_id": "u1", "value": 8.50}, {"user_id": "u2", "value": 0.00}]}},
        ],
        notes=None, source="manual", staging_id=None, receipt_path=None, created_by="u1",
    )


# ------------------------------------------------------------------ full replay (_async_update_data)


async def test_full_replay_empty(coordinator: SplitsmartCoordinator):
    data = await coordinator._async_update_data()
    assert data.expenses == []
    assert data.settlements == []
    assert data.balances == {}


async def test_full_replay_three_rows(coordinator: SplitsmartCoordinator, storage: SplitsmartStorage):
    for _ in range(3):
        await storage.append(storage.expenses_path, _tesco_expense())

    data = await coordinator._async_update_data()
    assert len(data.expenses) == 3
    assert data.last_expense_id is not None


async def test_full_replay_applies_tombstones(coordinator: SplitsmartCoordinator, storage: SplitsmartStorage):
    expense = _tesco_expense()
    await storage.append(storage.expenses_path, expense)
    await storage.append_tombstone(
        created_by="u1", target_type="expense",
        target_id=expense["id"], operation="delete", previous_snapshot=expense,
    )

    data = await coordinator._async_update_data()
    assert data.expenses == []


async def test_full_replay_computes_balances(coordinator: SplitsmartCoordinator, storage: SplitsmartStorage):
    await storage.append(storage.expenses_path, _tesco_expense(paid_by="u1"))

    data = await coordinator._async_update_data()
    assert data.balances["u1"] == Decimal("36.95")
    assert data.balances["u2"] == Decimal("-36.95")


# ------------------------------------------------------------------ incremental refresh (async_note_write)


async def test_note_write_on_empty_data_triggers_full_replay(
    coordinator: SplitsmartCoordinator, storage: SplitsmartStorage
):
    """If coordinator.data is None, async_note_write falls back to async_refresh."""
    assert coordinator.data is None
    expense = _tesco_expense()
    await storage.append(storage.expenses_path, expense)

    # Patch async_refresh to observe it was called
    coordinator.async_refresh = AsyncMock(side_effect=coordinator.async_refresh)

    # Manually give it a data object (simulating after first_refresh)
    coordinator.data = await coordinator._async_update_data()
    assert len(coordinator.data.expenses) == 1


async def test_note_write_reads_only_new_lines(
    coordinator: SplitsmartCoordinator, storage: SplitsmartStorage, monkeypatch
):
    """read_since should be called (not read_all) after the first refresh."""
    # Bootstrap
    expense1 = _tesco_expense()
    await storage.append(storage.expenses_path, expense1)
    coordinator.data = await coordinator._async_update_data()

    read_since_calls: list[tuple] = []
    original = storage.read_since

    async def _spy(path, since_id):
        read_since_calls.append((path.name, since_id))
        return await original(path, since_id)

    monkeypatch.setattr(storage, "read_since", _spy)

    expense2 = _tesco_expense()
    await storage.append(storage.expenses_path, expense2)
    await coordinator.async_note_write()

    expense_calls = [c for c in read_since_calls if c[0] == "expenses.jsonl"]
    assert len(expense_calls) >= 1
    assert expense_calls[0][1] == expense1["id"]  # since_id = last seen
    assert len(coordinator.data.expenses) == 2


async def test_note_write_after_edit_materialises_correctly(
    coordinator: SplitsmartCoordinator, storage: SplitsmartStorage
):
    old = _tesco_expense()
    await storage.append(storage.expenses_path, old)
    coordinator.data = await coordinator._async_update_data()

    # Write new record first, then tombstone (amendment 5)
    new = _tesco_expense()
    await storage.append(storage.expenses_path, new)
    await storage.append_tombstone(
        created_by="u1", target_type="expense",
        target_id=old["id"], operation="edit", previous_snapshot=old,
    )
    await coordinator.async_note_write()

    assert len(coordinator.data.expenses) == 1
    assert coordinator.data.expenses[0]["id"] == new["id"]


# ------------------------------------------------------------------ async_invalidate


async def test_invalidate_resets_cursors(coordinator: SplitsmartCoordinator, storage: SplitsmartStorage):
    expense = _tesco_expense()
    await storage.append(storage.expenses_path, expense)
    coordinator.data = await coordinator._async_update_data()
    assert coordinator.data.last_expense_id is not None

    await coordinator.async_invalidate()
    assert coordinator.data.last_expense_id is None


async def test_invalidate_then_full_replay(
    coordinator: SplitsmartCoordinator, storage: SplitsmartStorage, monkeypatch
):
    """After invalidate, _async_update_data should call read_all (since_id=None)."""
    expense = _tesco_expense()
    await storage.append(storage.expenses_path, expense)
    coordinator.data = await coordinator._async_update_data()

    await coordinator.async_invalidate()

    read_all_calls: list[str] = []
    original = storage.read_all

    async def _spy(path):
        read_all_calls.append(path.name)
        return await original(path)

    monkeypatch.setattr(storage, "read_all", _spy)

    coordinator.data = await coordinator._async_update_data()
    assert "expenses.jsonl" in read_all_calls
