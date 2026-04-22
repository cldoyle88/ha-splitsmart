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
    _handle_promote_staging,
    _handle_skip_staging,
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
    with pytest.raises(ServiceValidationError, match="M4"):
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


# ------------------------------------------------------------------ promote_staging / skip_staging


async def _seed_staging_row(
    storage: SplitsmartStorage,
    coordinator: SplitsmartCoordinator,
    *,
    uploaded_by: str = "u1",
    amount: float = 47.83,
    currency: str = "GBP",
    description: str = "Waitrose",
) -> dict[str, Any]:
    """Append a synthetic staging row and refresh the coordinator so the row
    is live in staging_by_user before the service call."""
    from custom_components.splitsmart.importer.normalise import dedup_hash
    from custom_components.splitsmart.storage import new_id

    row = {
        "id": new_id("st"),
        "uploaded_by": uploaded_by,
        "uploaded_at": "2026-04-22T10:00:00+01:00",
        "source": "csv",
        "source_ref": "statement.csv",
        "source_ref_upload_id": "upload-uuid-abc",
        "source_preset": "Monzo",
        "date": "2026-04-15",
        "description": description,
        "amount": amount,
        "currency": currency,
        "rule_action": "pending",
        "rule_id": None,
        "category_hint": "Groceries",
        "dedup_hash": dedup_hash(
            date="2026-04-15",
            amount=amount,
            currency=currency,
            description=description,
        ),
        "receipt_path": None,
        "notes": None,
    }
    await storage.append(storage.staging_path(uploaded_by), row)
    # Refresh so the coordinator projection includes the new row.
    coordinator.data = await coordinator._async_update_data()
    return row


def _waitrose_promote_payload(staging_id: str, paid_by: str = "u1") -> dict[str, Any]:
    """Single-category Groceries split 50/50 for the seeded £47.83 Waitrose row."""
    return {
        "staging_id": staging_id,
        "paid_by": paid_by,
        "categories": [
            {
                "name": "Groceries",
                "home_amount": 47.83,
                "split": {
                    "method": "equal",
                    "shares": [
                        {"user_id": "u1", "value": 50},
                        {"user_id": "u2", "value": 50},
                    ],
                },
            }
        ],
    }


async def test_promote_staging_happy_path(
    storage: SplitsmartStorage, coordinator: SplitsmartCoordinator
):
    row = await _seed_staging_row(storage, coordinator)
    hass = _make_hass(storage, coordinator)

    result = await _handle_promote_staging(_make_call(hass, _waitrose_promote_payload(row["id"])))

    assert result["expense_id"].startswith("ex_")
    assert result["staging_id"] == row["id"]

    # Expense landed.
    expenses = coordinator.data.expenses
    assert len(expenses) == 1
    assert expenses[0]["source"] == "staging"
    assert expenses[0]["staging_id"] == row["id"]

    # Staging row is no longer live (tombstoned via promote).
    assert coordinator.data.staging_by_user["u1"] == []

    # Tombstone carries operation=promote and replacement_id.
    tombstones = await storage.read_all(storage.tombstones_path)
    promote_tombstones = [tb for tb in tombstones if tb["operation"] == "promote"]
    assert len(promote_tombstones) == 1
    tb = promote_tombstones[0]
    assert tb["target_type"] == "staging"
    assert tb["target_id"] == row["id"]
    assert tb["replacement_id"] == result["expense_id"]


async def test_promote_staging_paid_by_may_differ_from_uploader(
    storage: SplitsmartStorage, coordinator: SplitsmartCoordinator
):
    """Uploaded by one participant, paid by the other — common for joint-
    account statements. The service must accept a paid_by that differs
    from uploaded_by as long as paid_by is a valid participant. Prevents
    a future 'default paid_by=uploaded_by' refactor from silently
    breaking the common flow."""
    row = await _seed_staging_row(storage, coordinator, uploaded_by="u1")
    hass = _make_hass(storage, coordinator)

    # u1 uploads; u2 actually paid.
    result = await _handle_promote_staging(
        _make_call(hass, _waitrose_promote_payload(row["id"], paid_by="u2"))
    )

    expense = next(e for e in coordinator.data.expenses if e["id"] == result["expense_id"])
    assert expense["paid_by"] == "u2"
    # Staging row was uploaded by u1; tombstone reflects that provenance.
    tombstones = await storage.read_all(storage.tombstones_path)
    promote_tb = next(tb for tb in tombstones if tb["operation"] == "promote")
    assert promote_tb["previous_snapshot"]["uploaded_by"] == "u1"


async def test_promote_staging_rejects_paid_by_non_participant(
    storage: SplitsmartStorage, coordinator: SplitsmartCoordinator
):
    row = await _seed_staging_row(storage, coordinator)
    hass = _make_hass(storage, coordinator)

    from homeassistant.exceptions import ServiceValidationError

    with pytest.raises(ServiceValidationError, match="not a configured participant"):
        await _handle_promote_staging(
            _make_call(hass, _waitrose_promote_payload(row["id"], paid_by="u_nobody"))
        )


async def test_promote_staging_other_user_permission_denied(
    storage: SplitsmartStorage, coordinator: SplitsmartCoordinator
):
    """u2 cannot promote u1's staging row even though u2 is a participant.
    SPEC §7: staging is private to the uploader."""
    row = await _seed_staging_row(storage, coordinator, uploaded_by="u1")
    hass = _make_hass(storage, coordinator)

    from homeassistant.exceptions import ServiceValidationError

    with pytest.raises(ServiceValidationError, match="permission_denied"):
        # Call comes from u2.
        await _handle_promote_staging(
            _make_call(
                hass,
                _waitrose_promote_payload(row["id"], paid_by="u2"),
                user_id="u2",
            )
        )


async def test_promote_staging_foreign_currency_row_rejected_with_user_message(
    storage: SplitsmartStorage, coordinator: SplitsmartCoordinator
):
    """Per O4 decision — the row stays staged; the message is the
    verbatim user-facing copy in M3_PLAN §8."""
    row = await _seed_staging_row(storage, coordinator, currency="EUR")
    hass = _make_hass(storage, coordinator)

    from homeassistant.exceptions import ServiceValidationError

    with pytest.raises(
        ServiceValidationError,
        match=r"Foreign currency promotion arrives in M4\. Row stays staged\.",
    ):
        await _handle_promote_staging(_make_call(hass, _waitrose_promote_payload(row["id"])))

    # Row remains live: no tombstone, still in staging_by_user.
    assert len(coordinator.data.staging_by_user["u1"]) == 1
    tombstones = await storage.read_all(storage.tombstones_path)
    assert tombstones == []


async def test_promote_staging_missing_id_raises(
    storage: SplitsmartStorage, coordinator: SplitsmartCoordinator
):
    hass = _make_hass(storage, coordinator)

    from homeassistant.exceptions import ServiceValidationError

    with pytest.raises(ServiceValidationError, match="not found"):
        await _handle_promote_staging(
            _make_call(hass, _waitrose_promote_payload("st_does_not_exist"))
        )


async def test_skip_staging_tombstones_row_and_preserves_dedup_hash(
    storage: SplitsmartStorage, coordinator: SplitsmartCoordinator
):
    """The discard tombstone's previous_snapshot must carry the full staging
    row including dedup_hash — dedup reaches the hash via the tombstone, and
    losing it would silently break skip-is-sticky across re-imports."""
    row = await _seed_staging_row(storage, coordinator)
    hass = _make_hass(storage, coordinator)

    result = await _handle_skip_staging(_make_call(hass, {"staging_id": row["id"]}))
    assert result["staging_id"] == row["id"]

    # Row is no longer live.
    assert coordinator.data.staging_by_user["u1"] == []

    # Tombstone on disk carries operation=discard and the full snapshot.
    tombstones = await storage.read_all(storage.tombstones_path)
    discards = [tb for tb in tombstones if tb["operation"] == "discard"]
    assert len(discards) == 1
    discard_tb = discards[0]
    assert discard_tb["target_type"] == "staging"
    assert discard_tb["target_id"] == row["id"]
    # The dedup-sticky invariant — without this the next re-import would
    # resurrect the skipped row.
    assert discard_tb["previous_snapshot"]["dedup_hash"] == row["dedup_hash"]
    assert discard_tb["previous_snapshot"]["description"] == row["description"]
    assert discard_tb["previous_snapshot"]["amount"] == row["amount"]


async def test_skip_staging_other_user_permission_denied(
    storage: SplitsmartStorage, coordinator: SplitsmartCoordinator
):
    row = await _seed_staging_row(storage, coordinator, uploaded_by="u1")
    hass = _make_hass(storage, coordinator)

    from homeassistant.exceptions import ServiceValidationError

    with pytest.raises(ServiceValidationError, match="permission_denied"):
        await _handle_skip_staging(_make_call(hass, {"staging_id": row["id"]}, user_id="u2"))


async def test_skip_staging_missing_id_raises(
    storage: SplitsmartStorage, coordinator: SplitsmartCoordinator
):
    hass = _make_hass(storage, coordinator)

    from homeassistant.exceptions import ServiceValidationError

    with pytest.raises(ServiceValidationError, match="not found"):
        await _handle_skip_staging(_make_call(hass, {"staging_id": "st_nope"}))


async def test_skip_staging_double_call_second_raises(
    storage: SplitsmartStorage, coordinator: SplitsmartCoordinator
):
    """Once tombstoned, the row is no longer live, so a second skip fails
    with 'not found' rather than accidentally writing two tombstones."""
    row = await _seed_staging_row(storage, coordinator)
    hass = _make_hass(storage, coordinator)

    await _handle_skip_staging(_make_call(hass, {"staging_id": row["id"]}))

    from homeassistant.exceptions import ServiceValidationError

    with pytest.raises(ServiceValidationError, match="not found"):
        await _handle_skip_staging(_make_call(hass, {"staging_id": row["id"]}))


async def test_promote_override_description_and_date_take_effect(
    storage: SplitsmartStorage, coordinator: SplitsmartCoordinator
):
    row = await _seed_staging_row(storage, coordinator)
    hass = _make_hass(storage, coordinator)

    import datetime as dt

    payload = _waitrose_promote_payload(row["id"])
    payload["override_description"] = "Waitrose (corrected)"
    payload["override_date"] = dt.date(2026, 4, 16)

    result = await _handle_promote_staging(_make_call(hass, payload))
    expense = next(e for e in coordinator.data.expenses if e["id"] == result["expense_id"])
    assert expense["description"] == "Waitrose (corrected)"
    assert expense["date"] == "2026-04-16"
