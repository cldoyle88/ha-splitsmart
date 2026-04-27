"""Regression tests for FX category rescaling in service handlers.

Pi QA M4 blocker: promote_staging (and add_expense / edit_expense) were passing
caller-supplied category home_amounts verbatim to the validator, which compared
them against the FX-rescaled expense home_amount and rejected the write.

Reproduction: staged Revolut row €4.50, EUR, 2026-04-15. FX rate ≈ 0.869 →
home_amount ≈ 3.91. Caller supplied categories summing to 4.50 (source currency).
Validator saw 4.50 ≠ 3.91 and raised SplitsmartValidationError.
"""

from __future__ import annotations

import datetime as dt
import pathlib
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.splitsmart.const import DOMAIN
from custom_components.splitsmart.coordinator import SplitsmartCoordinator
from custom_components.splitsmart.services import (
    _handle_add_expense,
    _handle_edit_expense,
    _handle_promote_staging,
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
        categories=["Groceries", "Household"],
        config_entry=None,
    )
    coord.data = await coord._async_update_data()
    coord.async_note_write = AsyncMock(side_effect=coord.async_note_write)
    return coord


def _make_fx_client(rate: str, fx_date_str: str = "2026-04-15") -> MagicMock:
    """Return a mock FxClient that always returns the given rate."""
    from custom_components.splitsmart.fx import FxClient

    result = MagicMock()
    result.rate = Decimal(rate)
    result.fx_date = dt.date.fromisoformat(fx_date_str)

    mock = MagicMock(spec=FxClient)
    mock.get_rate = AsyncMock(return_value=result)
    return mock


def _make_hass(
    storage: SplitsmartStorage,
    coordinator: SplitsmartCoordinator,
    fx_rate: str = "0.869",
) -> MagicMock:
    hass = MagicMock()
    hass.data = {
        DOMAIN: {
            "test_entry": {
                "storage": storage,
                "coordinator": coordinator,
                "fx": _make_fx_client(fx_rate),
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


async def _seed_eur_staging_row(
    storage: SplitsmartStorage,
    coordinator: SplitsmartCoordinator,
    *,
    amount: float = 4.50,
    description: str = "Revolut merchant",
) -> dict[str, Any]:
    from custom_components.splitsmart.importer.normalise import dedup_hash
    from custom_components.splitsmart.storage import new_id

    row = {
        "id": new_id("st"),
        "uploaded_by": "u1",
        "uploaded_at": "2026-04-22T10:00:00+01:00",
        "source": "csv",
        "source_ref": "revolut.csv",
        "source_ref_upload_id": "upload-uuid-xyz",
        "source_preset": "Revolut",
        "date": "2026-04-15",
        "description": description,
        "amount": amount,
        "currency": "EUR",
        "rule_action": "pending",
        "rule_id": None,
        "category_hint": "Groceries",
        "dedup_hash": dedup_hash(
            date="2026-04-15",
            amount=amount,
            currency="EUR",
            description=description,
        ),
        "receipt_path": None,
        "notes": None,
    }
    await storage.append(storage.staging_path("u1"), row)
    coordinator.data = await coordinator._async_update_data()
    return row


# ------------------------------------------------------------------ promote_staging


async def test_promote_staging_eur_single_category_rescaled(
    storage: SplitsmartStorage, coordinator: SplitsmartCoordinator
):
    """Pi QA reproduction: €4.50 staged, category home_amount=4.50 supplied in
    source currency, FX rate 0.869 → expense home_amount=3.91. After fix the
    category must be rescaled to 3.91, not left at 4.50."""
    row = await _seed_eur_staging_row(storage, coordinator, amount=4.50)
    # 4.50 * 0.8688... ≈ 3.91; use exact rate to hit the validator tolerance
    hass = _make_hass(storage, coordinator, fx_rate="0.86888888888")

    result = await _handle_promote_staging(
        _make_call(
            hass,
            {
                "staging_id": row["id"],
                "paid_by": "u1",
                # Caller supplies amount in source currency — this was the bug trigger.
                "categories": [
                    {
                        "name": "Groceries",
                        "home_amount": 4.50,
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

    assert result["expense_id"].startswith("ex_")
    expense = coordinator.data.expenses[0]

    expected_home = round(4.50 * 0.86888888888, 2)  # 3.91
    assert expense["home_amount"] == expected_home

    # Rescaled category must equal home_amount exactly (single category absorbs drift).
    assert len(expense["categories"]) == 1
    assert expense["categories"][0]["home_amount"] == expected_home
    # Confirm the original source value is gone.
    assert expense["categories"][0]["home_amount"] != 4.50


async def test_promote_staging_eur_multi_category_rescaled(
    storage: SplitsmartStorage, coordinator: SplitsmartCoordinator
):
    """Multi-category EUR promote: categories supplied in source currency (3.00 + 1.50
    = 4.50). After rescale they must sum to home_amount, with last category absorbing
    any rounding drift."""
    row = await _seed_eur_staging_row(storage, coordinator, amount=4.50)
    hass = _make_hass(storage, coordinator, fx_rate="0.869")

    await _handle_promote_staging(
        _make_call(
            hass,
            {
                "staging_id": row["id"],
                "paid_by": "u1",
                "categories": [
                    {
                        "name": "Groceries",
                        "home_amount": 3.00,
                        "split": {
                            "method": "equal",
                            "shares": [
                                {"user_id": "u1", "value": 50},
                                {"user_id": "u2", "value": 50},
                            ],
                        },
                    },
                    {
                        "name": "Household",
                        "home_amount": 1.50,
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

    expense = coordinator.data.expenses[0]
    expected_home = round(4.50 * 0.869, 2)  # 3.91

    assert expense["home_amount"] == expected_home

    cat_sum = round(sum(c["home_amount"] for c in expense["categories"]), 2)
    assert cat_sum == expected_home

    # Groceries: round(3.00 * 0.869, 2) = 2.61; Household absorbs drift: 3.91 - 2.61 = 1.30
    assert expense["categories"][0]["home_amount"] == round(3.00 * 0.869, 2)
    groceries_home = round(3.00 * 0.869, 2)
    assert expense["categories"][1]["home_amount"] == round(expected_home - groceries_home, 2)


# ------------------------------------------------------------------ add_expense


async def test_add_expense_eur_single_category_rescaled(
    storage: SplitsmartStorage, coordinator: SplitsmartCoordinator
):
    """add_expense with EUR: caller supplies category home_amount in source currency.
    After fix the category is rescaled to the GBP home_amount."""
    hass = _make_hass(storage, coordinator, fx_rate="0.86888888888")

    result = await _handle_add_expense(
        _make_call(
            hass,
            {
                "date": "2026-04-15",
                "description": "Aldi Berlin",
                "paid_by": "u1",
                "amount": 4.50,
                "currency": "EUR",
                "categories": [
                    {
                        "name": "Groceries",
                        "home_amount": 4.50,
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

    assert result["id"].startswith("ex_")
    expense = coordinator.data.expenses[0]

    expected_home = round(4.50 * 0.86888888888, 2)
    assert expense["home_amount"] == expected_home
    assert expense["categories"][0]["home_amount"] == expected_home


async def test_add_expense_gbp_categories_unchanged_by_rescale(
    storage: SplitsmartStorage, coordinator: SplitsmartCoordinator
):
    """For home-currency expenses (fx_rate=1) rescale_categories is a no-op:
    category amounts must be unchanged and validation must still pass."""
    from custom_components.splitsmart.fx import FxClient

    mock_fx = MagicMock(spec=FxClient)
    mock_fx.get_rate = AsyncMock(side_effect=AssertionError("should not call FX for GBP"))

    hass = MagicMock()
    hass.data = {
        DOMAIN: {
            "test_entry": {
                "storage": storage,
                "coordinator": coordinator,
                "fx": mock_fx,
                "entry": None,
            }
        }
    }

    await _handle_add_expense(
        _make_call(
            hass,
            {
                "date": "2026-04-15",
                "description": "Tesco",
                "paid_by": "u1",
                "amount": 10.00,
                "currency": "GBP",
                "categories": [
                    {
                        "name": "Groceries",
                        "home_amount": 6.00,
                        "split": {
                            "method": "equal",
                            "shares": [
                                {"user_id": "u1", "value": 50},
                                {"user_id": "u2", "value": 50},
                            ],
                        },
                    },
                    {
                        "name": "Household",
                        "home_amount": 4.00,
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

    expense = coordinator.data.expenses[0]
    assert expense["home_amount"] == 10.00
    # GBP rescale is a no-op: amounts unchanged (last category absorbs 0 drift).
    assert expense["categories"][0]["home_amount"] == 6.00
    assert expense["categories"][1]["home_amount"] == 4.00


# ------------------------------------------------------------------ edit_expense


async def test_edit_expense_eur_rescales_categories(
    storage: SplitsmartStorage, coordinator: SplitsmartCoordinator
):
    """edit_expense with EUR: same rescale bug existed there too. After fix,
    edited categories must sum to the FX-rescaled home_amount."""
    # First add a home-currency expense to edit.
    from custom_components.splitsmart.fx import FxClient

    gbp_fx = MagicMock(spec=FxClient)
    gbp_fx.get_rate = AsyncMock(side_effect=AssertionError("should not call for GBP"))
    hass_gbp = MagicMock()
    hass_gbp.data = {
        DOMAIN: {
            "test_entry": {
                "storage": storage,
                "coordinator": coordinator,
                "fx": gbp_fx,
                "entry": None,
            }
        }
    }
    add_result = await _handle_add_expense(
        _make_call(
            hass_gbp,
            {
                "date": "2026-04-15",
                "description": "Tesco",
                "paid_by": "u1",
                "amount": 10.00,
                "currency": "GBP",
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

    # Now edit it, switching to EUR with category sum in source currency.
    hass_eur = _make_hass(storage, coordinator, fx_rate="0.86888888888")
    edit_result = await _handle_edit_expense(
        _make_call(
            hass_eur,
            {
                "id": add_result["id"],
                "date": "2026-04-15",
                "description": "Lidl Berlin",
                "paid_by": "u1",
                "amount": 4.50,
                "currency": "EUR",
                "categories": [
                    {
                        "name": "Groceries",
                        "home_amount": 4.50,
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

    assert edit_result["id"].startswith("ex_")
    # Only the edited expense is live (original is tombstoned).
    assert len(coordinator.data.expenses) == 1
    expense = coordinator.data.expenses[0]

    expected_home = round(4.50 * 0.86888888888, 2)
    assert expense["home_amount"] == expected_home
    assert expense["categories"][0]["home_amount"] == expected_home
