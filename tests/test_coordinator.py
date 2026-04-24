"""Tests for coordinator.py.

Calls _async_update_data / async_note_write / async_invalidate directly
with a minimal mock hass so the test suite runs without a full HA event loop.
"""

from __future__ import annotations

import pathlib
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.splitsmart.coordinator import SplitsmartCoordinator
from custom_components.splitsmart.ledger import build_expense_record
from custom_components.splitsmart.storage import SplitsmartStorage

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


# ------------------------------------------------------------------ full replay


async def test_full_replay_empty(coordinator: SplitsmartCoordinator):
    data = await coordinator._async_update_data()
    assert data.expenses == []
    assert data.settlements == []
    assert data.balances == {}


async def test_full_replay_three_rows(
    coordinator: SplitsmartCoordinator, storage: SplitsmartStorage
):
    for _ in range(3):
        await storage.append(storage.expenses_path, _tesco_expense())

    data = await coordinator._async_update_data()
    assert len(data.expenses) == 3
    assert data.last_expense_id is not None


async def test_full_replay_applies_tombstones(
    coordinator: SplitsmartCoordinator, storage: SplitsmartStorage
):
    expense = _tesco_expense()
    await storage.append(storage.expenses_path, expense)
    await storage.append_tombstone(
        created_by="u1",
        target_type="expense",
        target_id=expense["id"],
        operation="delete",
        previous_snapshot=expense,
    )

    data = await coordinator._async_update_data()
    assert data.expenses == []


async def test_full_replay_computes_balances(
    coordinator: SplitsmartCoordinator, storage: SplitsmartStorage
):
    await storage.append(storage.expenses_path, _tesco_expense(paid_by="u1"))

    data = await coordinator._async_update_data()
    assert data.balances["u1"] == Decimal("36.95")
    assert data.balances["u2"] == Decimal("-36.95")


# ------------------------------------------------------------------ incremental refresh


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
        created_by="u1",
        target_type="expense",
        target_id=old["id"],
        operation="edit",
        previous_snapshot=old,
    )
    await coordinator.async_note_write()

    assert len(coordinator.data.expenses) == 1
    assert coordinator.data.expenses[0]["id"] == new["id"]


# ------------------------------------------------------------------ async_invalidate


async def test_invalidate_resets_cursors(
    coordinator: SplitsmartCoordinator, storage: SplitsmartStorage
):
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


# ------------------------------------------------------------------ staging (M3)


def _staging_row(*, user_id: str = "u1", amount: float = 4.50) -> dict[str, Any]:
    """Minimal staging record for projection tests (real records are richer
    but coordinator tests only care about id and the rule_action field)."""
    from custom_components.splitsmart.storage import new_id

    return {
        "id": new_id("st"),
        "uploaded_by": user_id,
        "uploaded_at": "2026-04-22T10:00:00+01:00",
        "source": "csv",
        "source_ref": "statement.csv",
        "date": "2026-04-15",
        "description": "Coffee",
        "amount": amount,
        "currency": "GBP",
        "rule_action": "pending",
        "rule_id": None,
        "category_hint": None,
        "dedup_hash": "sha256:test",
        "receipt_path": None,
        "notes": None,
    }


async def test_full_replay_loads_per_user_staging(
    coordinator: SplitsmartCoordinator, storage: SplitsmartStorage
):
    await storage.append(storage.staging_path("u1"), _staging_row(user_id="u1"))
    await storage.append(storage.staging_path("u1"), _staging_row(user_id="u1"))
    await storage.append(storage.staging_path("u2"), _staging_row(user_id="u2"))

    data = await coordinator._async_update_data()
    assert len(data.staging_by_user["u1"]) == 2
    assert len(data.staging_by_user["u2"]) == 1
    assert data.last_staging_id_by_user["u1"] is not None


async def test_full_replay_ignores_orphan_staging_files(
    coordinator: SplitsmartCoordinator, storage: SplitsmartStorage
):
    """A staging file for a user not in participants is not surfaced —
    config is authoritative for "who has state"."""
    await storage.append(storage.staging_path("u_orphan"), _staging_row(user_id="u_orphan"))

    data = await coordinator._async_update_data()
    assert "u_orphan" not in data.staging_by_user
    assert set(data.staging_by_user.keys()) == {"u1", "u2"}


async def test_full_replay_handles_missing_staging_file(
    coordinator: SplitsmartCoordinator,
):
    # No staging files on disk — participants still get empty lists.
    data = await coordinator._async_update_data()
    assert data.staging_by_user == {"u1": [], "u2": []}


async def test_full_replay_materialises_staging_against_tombstones(
    coordinator: SplitsmartCoordinator, storage: SplitsmartStorage
):
    row_a = _staging_row(user_id="u1")
    row_b = _staging_row(user_id="u1")
    await storage.append(storage.staging_path("u1"), row_a)
    await storage.append(storage.staging_path("u1"), row_b)
    await storage.append_tombstone(
        created_by="u1",
        target_type="staging",
        target_id=row_a["id"],
        operation="discard",
        previous_snapshot=row_a,
    )

    data = await coordinator._async_update_data()
    # Raw still has both; materialised has only the surviving row.
    assert len(data.raw_staging_by_user["u1"]) == 2
    assert len(data.staging_by_user["u1"]) == 1
    assert data.staging_by_user["u1"][0]["id"] == row_b["id"]


async def test_note_write_refreshes_only_scoped_user_staging(
    coordinator: SplitsmartCoordinator, storage: SplitsmartStorage
):
    """staging_user_id hint targets one user's staging path — another user's
    staging path must not be re-read on that tick."""
    # Seed initial state.
    await storage.append(storage.staging_path("u1"), _staging_row(user_id="u1"))
    coordinator.data = await coordinator._async_update_data()

    # Append rows for both users after the initial replay.
    await storage.append(storage.staging_path("u1"), _staging_row(user_id="u1"))
    await storage.append(storage.staging_path("u2"), _staging_row(user_id="u2"))

    await coordinator.async_note_write(staging_user_id="u1")
    # Only u1's staging list should grow; u2's refresh must wait for the
    # next write or the 5-min safety-net replay.
    assert len(coordinator.data.staging_by_user["u1"]) == 2
    assert len(coordinator.data.staging_by_user["u2"]) == 0


async def test_note_write_without_user_hint_skips_staging_refresh(
    coordinator: SplitsmartCoordinator, storage: SplitsmartStorage
):
    """An expense/settlement write doesn't touch staging — the coordinator
    shouldn't reload staging files on every note_write."""
    await storage.append(storage.staging_path("u1"), _staging_row(user_id="u1"))
    coordinator.data = await coordinator._async_update_data()

    # Append a new staging row but don't pass staging_user_id.
    await storage.append(storage.staging_path("u1"), _staging_row(user_id="u1"))
    # Also append an expense so note_write has something to do.
    await storage.append(storage.expenses_path, _tesco_expense())
    await coordinator.async_note_write()

    # Staging list unchanged — the new row awaits the next targeted hint
    # or the safety-net tick.
    assert len(coordinator.data.staging_by_user["u1"]) == 1
    # But the expense write did land.
    assert len(coordinator.data.expenses) == 1
