"""Tests for recurring state and materialiser logic."""

from __future__ import annotations

import datetime as dt
import json
import pathlib
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.splitsmart.recurring import (
    RecurringEntry,
    MaterialiseResult,
    append_recurring_state,
    load_recurring_state,
    materialise_recurring,
)
from custom_components.splitsmart.storage import SplitsmartStorage


# ------------------------------------------------------------------ helpers


def _make_storage(tmp_path: pathlib.Path) -> SplitsmartStorage:
    root = tmp_path / "splitsmart"
    root.mkdir(parents=True, exist_ok=True)
    storage = SplitsmartStorage(root)
    storage.fx_rates_path.touch()
    storage.recurring_state_path.touch()
    # expenses.jsonl needs to exist for appends
    (root / "shared").mkdir(exist_ok=True)
    storage.expenses_path.touch()
    return storage


def _make_fx_client(rate: Decimal = Decimal("1")) -> MagicMock:
    from custom_components.splitsmart.fx import FxClient, FxResult

    mock = MagicMock(spec=FxClient)

    async def _get_rate(*, date, from_currency, to_currency):
        return FxResult(rate=rate, fx_date=date, source="cache")

    mock.get_rate = AsyncMock(side_effect=_get_rate)
    return mock


def _make_fx_client_unavailable() -> MagicMock:
    from custom_components.splitsmart.fx import FxClient, FxUnavailableError

    mock = MagicMock(spec=FxClient)
    mock.get_rate = AsyncMock(side_effect=FxUnavailableError("unavailable"))
    return mock


_SPLIT = {
    "method": "equal",
    "shares": [{"user_id": "u1", "value": 50}, {"user_id": "u2", "value": 50}],
}

_CATS_GBP = [{"name": "Subscriptions", "home_amount": 15.99, "split": _SPLIT}]

PARTICIPANTS = {"u1", "u2"}
KNOWN_CATS = {"Subscriptions", "Groceries", "Utilities", "Other"}


def _make_netflix(
    *,
    day: int = 15,
    start_date: dt.date | None = None,
    end_date: dt.date | None = None,
    currency: str = "GBP",
    categories: list | None = None,
) -> RecurringEntry:
    return RecurringEntry(
        id="netflix",
        description="Netflix",
        amount=15.99,
        currency=currency,
        paid_by="u1",
        categories=categories or _CATS_GBP,
        schedule={"kind": "monthly", "day": day},
        start_date=start_date,
        end_date=end_date,
    )


# ------------------------------------------------------------------ recurring state JSONL


@pytest.mark.asyncio
async def test_load_recurring_state_empty(tmp_path):
    storage = _make_storage(tmp_path)
    state = await load_recurring_state(storage.recurring_state_path)
    assert state == {}


@pytest.mark.asyncio
async def test_load_recurring_state_newest_wins(tmp_path):
    storage = _make_storage(tmp_path)
    await append_recurring_state(
        storage.recurring_state_path,
        recurring_id="netflix",
        last_materialised_date=dt.date(2026, 1, 15),
    )
    await append_recurring_state(
        storage.recurring_state_path,
        recurring_id="netflix",
        last_materialised_date=dt.date(2026, 2, 15),
    )
    state = await load_recurring_state(storage.recurring_state_path)
    assert state["netflix"] == dt.date(2026, 2, 15)


@pytest.mark.asyncio
async def test_append_recurring_state_uses_rs_prefix(tmp_path):
    storage = _make_storage(tmp_path)
    await append_recurring_state(
        storage.recurring_state_path,
        recurring_id="netflix",
        last_materialised_date=dt.date(2026, 4, 15),
    )
    rows = []
    with storage.recurring_state_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    assert len(rows) == 1
    assert rows[0]["id"].startswith("rs_")
    assert rows[0]["recurring_id"] == "netflix"
    assert rows[0]["last_materialised_date"] == "2026-04-15"


# ------------------------------------------------------------------ materialise: basic


@pytest.mark.asyncio
async def test_materialise_one_due_date(tmp_path):
    storage = _make_storage(tmp_path)
    entry = _make_netflix(day=15, start_date=dt.date(2026, 4, 15))
    state: dict[str, dt.date] = {}
    result = await materialise_recurring(
        entries=[entry],
        state=state,
        existing_expenses=[],
        fx_client=_make_fx_client(),
        home_currency="GBP",
        participants=PARTICIPANTS,
        known_categories=KNOWN_CATS,
        storage=storage,
        today=dt.date(2026, 4, 15),
    )
    assert result.materialised == 1
    assert result.skipped_fx_failure == 0
    expenses = await storage.read_all(storage.expenses_path)
    assert len(expenses) == 1
    assert expenses[0]["recurring_id"] == "netflix"
    assert expenses[0]["source"] == "recurring"
    assert expenses[0]["date"] == "2026-04-15"


@pytest.mark.asyncio
async def test_materialise_catches_up_3_months(tmp_path):
    storage = _make_storage(tmp_path)
    entry = _make_netflix(day=15, start_date=dt.date(2026, 2, 15))
    state: dict[str, dt.date] = {}
    result = await materialise_recurring(
        entries=[entry],
        state=state,
        existing_expenses=[],
        fx_client=_make_fx_client(),
        home_currency="GBP",
        participants=PARTICIPANTS,
        known_categories=KNOWN_CATS,
        storage=storage,
        today=dt.date(2026, 4, 15),
    )
    assert result.materialised == 3  # Feb 15, Mar 15, Apr 15
    expenses = await storage.read_all(storage.expenses_path)
    dates = [e["date"] for e in expenses]
    assert "2026-02-15" in dates
    assert "2026-03-15" in dates
    assert "2026-04-15" in dates


@pytest.mark.asyncio
async def test_materialise_respects_last_materialised_date(tmp_path):
    storage = _make_storage(tmp_path)
    entry = _make_netflix(day=15)
    state = {"netflix": dt.date(2026, 3, 15)}
    result = await materialise_recurring(
        entries=[entry],
        state=state,
        existing_expenses=[],
        fx_client=_make_fx_client(),
        home_currency="GBP",
        participants=PARTICIPANTS,
        known_categories=KNOWN_CATS,
        storage=storage,
        today=dt.date(2026, 4, 15),
    )
    assert result.materialised == 1  # only Apr 15
    expenses = await storage.read_all(storage.expenses_path)
    assert expenses[0]["date"] == "2026-04-15"


@pytest.mark.asyncio
async def test_materialise_nothing_when_already_current(tmp_path):
    storage = _make_storage(tmp_path)
    entry = _make_netflix(day=15)
    state = {"netflix": dt.date(2026, 4, 15)}
    result = await materialise_recurring(
        entries=[entry],
        state=state,
        existing_expenses=[],
        fx_client=_make_fx_client(),
        home_currency="GBP",
        participants=PARTICIPANTS,
        known_categories=KNOWN_CATS,
        storage=storage,
        today=dt.date(2026, 4, 15),
    )
    assert result.materialised == 0
    expenses = await storage.read_all(storage.expenses_path)
    assert expenses == []


@pytest.mark.asyncio
async def test_materialise_end_date_past(tmp_path):
    storage = _make_storage(tmp_path)
    entry = _make_netflix(day=15, start_date=dt.date(2026, 1, 1), end_date=dt.date(2026, 1, 31))
    state: dict[str, dt.date] = {}
    result = await materialise_recurring(
        entries=[entry],
        state=state,
        existing_expenses=[],
        fx_client=_make_fx_client(),
        home_currency="GBP",
        participants=PARTICIPANTS,
        known_categories=KNOWN_CATS,
        storage=storage,
        today=dt.date(2026, 4, 15),
    )
    assert result.materialised == 1  # only Jan 15, which is <= end_date
    expenses = await storage.read_all(storage.expenses_path)
    assert expenses[0]["date"] == "2026-01-15"


@pytest.mark.asyncio
async def test_materialise_end_date_mid_range(tmp_path):
    storage = _make_storage(tmp_path)
    entry = _make_netflix(day=15, start_date=dt.date(2026, 1, 1), end_date=dt.date(2026, 2, 28))
    state: dict[str, dt.date] = {}
    result = await materialise_recurring(
        entries=[entry],
        state=state,
        existing_expenses=[],
        fx_client=_make_fx_client(),
        home_currency="GBP",
        participants=PARTICIPANTS,
        known_categories=KNOWN_CATS,
        storage=storage,
        today=dt.date(2026, 4, 15),
    )
    assert result.materialised == 2  # Jan 15 + Feb 15 (end_date = Feb 28)


# ------------------------------------------------------------------ idempotency


@pytest.mark.asyncio
async def test_materialise_idempotent_expense_scan(tmp_path):
    """Belt 2: existing expense with (recurring_id, date) prevents double-up."""
    storage = _make_storage(tmp_path)
    entry = _make_netflix(day=15, start_date=dt.date(2026, 4, 15))
    state: dict[str, dt.date] = {}
    existing_expenses = [
        {
            "id": "ex_existing",
            "source": "recurring",
            "recurring_id": "netflix",
            "date": "2026-04-15",
        }
    ]
    result = await materialise_recurring(
        entries=[entry],
        state=state,
        existing_expenses=existing_expenses,
        fx_client=_make_fx_client(),
        home_currency="GBP",
        participants=PARTICIPANTS,
        known_categories=KNOWN_CATS,
        storage=storage,
        today=dt.date(2026, 4, 15),
    )
    assert result.materialised == 0
    assert result.skipped_duplicate == 1
    # Nothing written
    expenses = await storage.read_all(storage.expenses_path)
    assert expenses == []


# ------------------------------------------------------------------ FX failure


@pytest.mark.asyncio
async def test_materialise_fx_failure_skips_date_continues_others(tmp_path):
    """FX failure on EUR recurring: date is skipped, state not advanced to that date."""
    storage = _make_storage(tmp_path)
    eur_cats = [{"name": "Subscriptions", "home_amount": 15.99, "split": _SPLIT}]
    entry = RecurringEntry(
        id="netflix_eur",
        description="Netflix EUR",
        amount=15.99,
        currency="EUR",
        paid_by="u1",
        categories=eur_cats,
        schedule={"kind": "monthly", "day": 15},
        start_date=dt.date(2026, 3, 15),
    )
    result = await materialise_recurring(
        entries=[entry],
        state={},
        existing_expenses=[],
        fx_client=_make_fx_client_unavailable(),
        home_currency="GBP",
        participants=PARTICIPANTS,
        known_categories=KNOWN_CATS,
        storage=storage,
        today=dt.date(2026, 4, 15),
    )
    # Both Mar 15 and Apr 15 fail FX
    assert result.materialised == 0
    assert result.skipped_fx_failure == 2
    # State must NOT be updated since nothing materialised
    state = await load_recurring_state(storage.recurring_state_path)
    assert "netflix_eur" not in state


# ------------------------------------------------------------------ FX rescaling


@pytest.mark.asyncio
async def test_materialise_eur_rescales_home_amounts(tmp_path):
    """EUR recurring at rate 0.85: home_amount = 15.99 * 0.85 = 13.59."""
    storage = _make_storage(tmp_path)
    eur_cats = [{"name": "Subscriptions", "home_amount": 15.99, "split": _SPLIT}]
    entry = RecurringEntry(
        id="netflix_eur",
        description="Netflix EUR",
        amount=15.99,
        currency="EUR",
        paid_by="u1",
        categories=eur_cats,
        schedule={"kind": "monthly", "day": 15},
        start_date=dt.date(2026, 4, 15),
    )
    result = await materialise_recurring(
        entries=[entry],
        state={},
        existing_expenses=[],
        fx_client=_make_fx_client(Decimal("0.85")),
        home_currency="GBP",
        participants=PARTICIPANTS,
        known_categories=KNOWN_CATS,
        storage=storage,
        today=dt.date(2026, 4, 15),
    )
    assert result.materialised == 1
    expenses = await storage.read_all(storage.expenses_path)
    e = expenses[0]
    assert abs(e["home_amount"] - round(15.99 * 0.85, 2)) < 0.01
    assert abs(e["fx_rate"] - 0.85) < 0.0001


@pytest.mark.asyncio
async def test_materialise_float_drift_absorbed_by_last_allocation(tmp_path):
    """amount=33.33, 3 equal allocations of 11.11 each at fx_rate=1.2345.
    Sum of individually-rounded allocations may drift; last absorbs it."""
    storage = _make_storage(tmp_path)
    cats = [
        {"name": "A", "home_amount": 11.11, "split": _SPLIT},
        {"name": "B", "home_amount": 11.11, "split": _SPLIT},
        {"name": "C", "home_amount": 11.11, "split": _SPLIT},
    ]
    entry = RecurringEntry(
        id="drift_test",
        description="Drift test",
        amount=33.33,
        currency="EUR",
        paid_by="u1",
        categories=cats,
        schedule={"kind": "monthly", "day": 1},
        start_date=dt.date(2026, 4, 1),
    )
    result = await materialise_recurring(
        entries=[entry],
        state={},
        existing_expenses=[],
        fx_client=_make_fx_client(Decimal("1.2345")),
        home_currency="GBP",
        participants=PARTICIPANTS,
        known_categories={"A", "B", "C"},
        storage=storage,
        today=dt.date(2026, 4, 1),
    )
    assert result.materialised == 1
    expenses = await storage.read_all(storage.expenses_path)
    e = expenses[0]
    alloc_sum = sum(a["home_amount"] for a in e["categories"])
    # Allocation sum must equal home_amount to 2dp
    assert abs(alloc_sum - e["home_amount"]) < 0.005


# ------------------------------------------------------------------ filter_id


@pytest.mark.asyncio
async def test_materialise_filter_id_only_runs_that_one(tmp_path):
    storage = _make_storage(tmp_path)
    e1 = _make_netflix(day=15, start_date=dt.date(2026, 4, 15))
    e2 = RecurringEntry(
        id="council",
        description="Council tax",
        amount=210.00,
        currency="GBP",
        paid_by="u1",
        categories=[{"name": "Utilities", "home_amount": 210.00, "split": _SPLIT}],
        schedule={"kind": "monthly", "day": 1},
        start_date=dt.date(2026, 4, 1),
    )
    result = await materialise_recurring(
        entries=[e1, e2],
        state={},
        existing_expenses=[],
        fx_client=_make_fx_client(),
        home_currency="GBP",
        participants=PARTICIPANTS,
        known_categories=KNOWN_CATS | {"Utilities"},
        storage=storage,
        today=dt.date(2026, 4, 15),
        filter_id="netflix",
    )
    assert result.materialised == 1
    expenses = await storage.read_all(storage.expenses_path)
    assert expenses[0]["recurring_id"] == "netflix"
