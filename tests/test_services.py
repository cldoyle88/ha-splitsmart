"""Tests for service handlers.

Calls handler functions directly with mock ServiceCall objects — no HA
event loop or hass fixture needed.
"""

from __future__ import annotations

import pathlib
import shutil
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
    _handle_import_file,
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


def _make_mock_fx_client(storage: SplitsmartStorage) -> MagicMock:
    """Return a mock FxClient that raises FxUnavailableError for any foreign-currency lookup.

    All home-currency (GBP) tests go through the same-currency shortcut in
    _resolve_fx and never touch the FxClient, so this mock is only exercised by
    tests that explicitly pass a foreign currency.
    """
    from custom_components.splitsmart.fx import FxClient, FxUnavailableError

    mock = MagicMock(spec=FxClient)
    mock.get_rate = AsyncMock(side_effect=FxUnavailableError("mock: network unavailable"))
    return mock


def _make_hass(storage: SplitsmartStorage, coordinator: SplitsmartCoordinator) -> MagicMock:
    hass = MagicMock()
    hass.data = {
        DOMAIN: {
            "test_entry": {
                "storage": storage,
                "coordinator": coordinator,
                "fx": _make_mock_fx_client(storage),
                "entry": None,
            }
        }
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


async def test_add_expense_foreign_currency_network_down(
    storage: SplitsmartStorage, coordinator: SplitsmartCoordinator
):
    """When the FX client is unavailable, add_expense with a foreign currency fails.

    The M3 hard block is gone in M4; the failure now comes from the FX lookup.
    """
    from homeassistant.exceptions import ServiceValidationError

    hass = _make_hass(storage, coordinator)
    data = _tesco_data()
    data["currency"] = "USD"
    with pytest.raises(ServiceValidationError, match="Frankfurter"):
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


# ------------------------------------------------------------------ import_file


FIXTURES_DIR = pathlib.Path(__file__).parent / "fixtures" / "imports"


async def _stage_upload(
    storage: SplitsmartStorage, fixture_name: str, upload_id: str | None = None
) -> str:
    """Copy a test fixture into /config/splitsmart/uploads/ and return the
    upload_id the service expects. Short-circuits the HTTP upload endpoint
    (step 9) so import_file is testable end-to-end at step 6c."""
    import uuid

    src = FIXTURES_DIR / fixture_name
    ext = src.suffix.lstrip(".").lower()
    if upload_id is None:
        upload_id = str(uuid.uuid4())
    dest = storage.upload_path(upload_id, ext)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)
    return upload_id


async def test_import_file_monzo_happy_path(
    storage: SplitsmartStorage, coordinator: SplitsmartCoordinator
):
    upload_id = await _stage_upload(storage, "monzo_classic.csv")
    hass = _make_hass(storage, coordinator)

    result = await _handle_import_file(_make_call(hass, {"upload_id": upload_id}))

    assert result["imported"] == 10
    assert result["skipped_as_duplicate"] == 0
    assert result["parse_errors"] == 0
    assert result["preset"] == "Monzo"
    assert result["blocked_foreign_currency"] == 0

    # Staging rows landed with the right metadata.
    rows = coordinator.data.staging_by_user["u1"]
    assert len(rows) == 10
    first = rows[0]
    assert first["uploaded_by"] == "u1"
    assert first["source"] == "csv"
    assert first["source_preset"] == "Monzo"
    assert first["source_ref_upload_id"] == upload_id
    assert first["source_ref"].endswith(".csv")
    assert first["rule_action"] == "pending"
    assert first["dedup_hash"].startswith("sha256:")


async def test_import_file_reimport_same_file_is_fully_deduped(
    storage: SplitsmartStorage, coordinator: SplitsmartCoordinator
):
    upload_id_1 = await _stage_upload(storage, "monzo_classic.csv")
    hass = _make_hass(storage, coordinator)

    first = await _handle_import_file(_make_call(hass, {"upload_id": upload_id_1}))
    assert first["imported"] == 10

    # Second upload of the same content → fresh upload_id but same dedup hashes.
    upload_id_2 = await _stage_upload(storage, "monzo_classic.csv")
    second = await _handle_import_file(_make_call(hass, {"upload_id": upload_id_2}))
    assert second["imported"] == 0
    assert second["skipped_as_duplicate"] == 10

    # Staging unchanged.
    assert len(coordinator.data.staging_by_user["u1"]) == 10


async def test_import_file_dedup_against_shared_ledger(
    storage: SplitsmartStorage, coordinator: SplitsmartCoordinator
):
    """After promoting a staging row, re-importing the same file skips that
    row via the shared-ledger side of dedup — the promote tombstone is
    intentionally not counted."""
    upload_id_1 = await _stage_upload(storage, "monzo_classic.csv")
    hass = _make_hass(storage, coordinator)

    first = await _handle_import_file(_make_call(hass, {"upload_id": upload_id_1}))
    assert first["imported"] == 10

    # Promote the first staging row.
    staging_rows = list(coordinator.data.staging_by_user["u1"])
    first_row = staging_rows[0]
    await _handle_promote_staging(
        _make_call(
            hass,
            {
                "staging_id": first_row["id"],
                "paid_by": "u1",
                "categories": [
                    {
                        "name": "Groceries",
                        "home_amount": first_row["amount"],
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
    # After promote: 9 staging + 1 shared.
    assert len(coordinator.data.staging_by_user["u1"]) == 9
    assert len(coordinator.data.expenses) == 1

    # Re-import the same file → all 10 accounted for, 0 imports.
    upload_id_2 = await _stage_upload(storage, "monzo_classic.csv")
    second = await _handle_import_file(_make_call(hass, {"upload_id": upload_id_2}))
    assert second["imported"] == 0
    assert second["skipped_as_duplicate"] == 10


async def test_import_file_dedup_against_skip_tombstone(
    storage: SplitsmartStorage, coordinator: SplitsmartCoordinator
):
    """After skipping a staging row, re-importing skips that row via the
    discard-tombstone bucket — skip-is-sticky across re-imports."""
    upload_id_1 = await _stage_upload(storage, "monzo_classic.csv")
    hass = _make_hass(storage, coordinator)

    await _handle_import_file(_make_call(hass, {"upload_id": upload_id_1}))
    skip_target = coordinator.data.staging_by_user["u1"][0]
    await _handle_skip_staging(_make_call(hass, {"staging_id": skip_target["id"]}))

    # Re-import → skipped row must not resurrect.
    upload_id_2 = await _stage_upload(storage, "monzo_classic.csv")
    second = await _handle_import_file(_make_call(hass, {"upload_id": upload_id_2}))
    assert second["imported"] == 0
    assert second["skipped_as_duplicate"] == 10
    # The skipped row is still gone from staging.
    ids = {r["id"] for r in coordinator.data.staging_by_user["u1"]}
    assert skip_target["id"] not in ids


async def test_import_file_revolut_blocked_foreign_currency_counted(
    storage: SplitsmartStorage, coordinator: SplitsmartCoordinator
):
    """Revolut fixture has EUR + USD rows. They stage fine but the response
    reports how many are FX-blocked (per O4)."""
    upload_id = await _stage_upload(storage, "revolut_account.csv")
    hass = _make_hass(storage, coordinator)

    result = await _handle_import_file(_make_call(hass, {"upload_id": upload_id}))
    assert result["preset"] == "Revolut"
    assert result["imported"] == 10
    # Fixture has 4 EUR + 1 USD rows = 5 FX-blocked.
    assert result["blocked_foreign_currency"] == 5


async def test_import_file_ofx_needs_no_mapping(
    storage: SplitsmartStorage, coordinator: SplitsmartCoordinator
):
    upload_id = await _stage_upload(storage, "sample.ofx")
    hass = _make_hass(storage, coordinator)

    result = await _handle_import_file(_make_call(hass, {"upload_id": upload_id}))
    assert result["imported"] == 5
    assert result["preset"] is None  # OFX has fixed schema, no preset
    rows = coordinator.data.staging_by_user["u1"]
    assert rows[0]["source"] == "ofx"


async def test_import_file_malformed_row_does_not_abort(
    storage: SplitsmartStorage, coordinator: SplitsmartCoordinator
):
    upload_id = await _stage_upload(storage, "malformed.csv")
    hass = _make_hass(storage, coordinator)

    # malformed.csv is a Monzo-shaped header (detects Monzo preset) with one
    # bad row of 3. Parse errors surface in the response but good rows land.
    result = await _handle_import_file(_make_call(hass, {"upload_id": upload_id}))
    assert result["imported"] == 2
    assert result["parse_errors"] == 1
    assert "first_error_hint" in result


async def test_import_file_no_preset_no_mapping_raises_mapping_required(
    storage: SplitsmartStorage, coordinator: SplitsmartCoordinator
):
    """A CSV whose headers don't match any preset and no saved mapping
    exists surfaces ImporterError(mapping_required) as a
    ServiceValidationError so Developer Tools callers can see the code."""
    upload_id = await _stage_upload(storage, "generic_no_preset.csv")
    hass = _make_hass(storage, coordinator)

    from homeassistant.exceptions import ServiceValidationError

    with pytest.raises(ServiceValidationError, match="mapping_required"):
        await _handle_import_file(_make_call(hass, {"upload_id": upload_id}))


async def test_import_file_with_explicit_mapping_persists_it(
    storage: SplitsmartStorage, coordinator: SplitsmartCoordinator
):
    """Supplying mapping + remember_mapping=True should write to
    mappings.jsonl so next month's re-import of the same-shape file
    resolves via saved-by-hash without a second mapping round trip."""
    upload_id = await _stage_upload(storage, "generic_no_preset.csv")
    hass = _make_hass(storage, coordinator)

    mapping: dict[str, Any] = {
        "date": "Posted",
        "description": "Merchant",
        "amount": "Spent",
        "debit": None,
        "credit": None,
        "currency": None,
        "currency_default": "GBP",
        "amount_sign": "expense_positive",
        "date_format": "auto",
        "notes_append": ["Note"],
        "category_hint": None,
    }
    result = await _handle_import_file(
        _make_call(hass, {"upload_id": upload_id, "mapping": mapping})
    )
    assert result["imported"] == 5

    # The mapping is now persisted — a re-upload without mapping resolves.
    from custom_components.splitsmart.importer.mapping import load_saved_mappings

    saved = await load_saved_mappings(storage)
    assert len(saved) == 1
    assert next(iter(saved.values())) == mapping


async def test_import_file_unknown_upload_id_raises(
    storage: SplitsmartStorage, coordinator: SplitsmartCoordinator
):
    hass = _make_hass(storage, coordinator)
    from homeassistant.exceptions import ServiceValidationError

    with pytest.raises(ServiceValidationError, match="not found"):
        await _handle_import_file(_make_call(hass, {"upload_id": "does-not-exist"}))


async def test_import_file_writes_to_caller_not_another_user(
    storage: SplitsmartStorage, coordinator: SplitsmartCoordinator
):
    """Upload scope is per-caller — rows land in the caller's staging file,
    not shared with other participants."""
    upload_id = await _stage_upload(storage, "monzo_classic.csv")
    hass = _make_hass(storage, coordinator)

    # Call as u2.
    await _handle_import_file(_make_call(hass, {"upload_id": upload_id}, user_id="u2"))

    # u2's staging has the rows; u1's is empty.
    assert len(coordinator.data.staging_by_user["u2"]) == 10
    assert coordinator.data.staging_by_user["u1"] == []
