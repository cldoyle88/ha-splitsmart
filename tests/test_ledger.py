"""Unit tests for ledger.py — no HA event loop required."""

from __future__ import annotations

from decimal import Decimal

import pytest

# conftest.py loads ledger into sys.modules before any test file is imported
from custom_components.splitsmart.ledger import (
    SplitsmartValidationError,
    build_settlement_record,
    compute_balances,
    compute_monthly_spending,
    compute_pairwise_balances,
    compute_user_share,
    materialise_expenses,
    materialise_settlements,
    validate_expense_record,
    validate_settlement_record,
    validate_split,
)

# ------------------------------------------------------------------ helpers

USERS = {"u1", "u2"}
USERS3 = {"u1", "u2", "u3"}


def _equal_split(user_ids: list[str]) -> dict:
    return {
        "method": "equal",
        "shares": [{"user_id": uid, "value": 50} for uid in user_ids],
    }


def _exact_split(shares: list[tuple[str, float]]) -> dict:
    return {
        "method": "exact",
        "shares": [{"user_id": uid, "value": v} for uid, v in shares],
    }


def _expense(
    *,
    id_: str = "ex_1",
    date: str = "2026-04-15",
    paid_by: str = "u1",
    home_amount: float = 100.0,
    categories: list | None = None,
) -> dict:
    if categories is None:
        categories = [
            {
                "name": "Groceries",
                "home_amount": home_amount,
                "split": _equal_split(["u1", "u2"]),
            }
        ]
    return {
        "id": id_,
        "created_at": "2026-04-15T10:00:00+01:00",
        "date": date,
        "paid_by": paid_by,
        "home_amount": home_amount,
        "home_currency": "GBP",
        "categories": categories,
    }


def _settlement(
    *,
    id_: str = "sl_1",
    from_user: str = "u2",
    to_user: str = "u1",
    home_amount: float = 50.0,
    date: str = "2026-04-20",
) -> dict:
    return {
        "id": id_,
        "created_at": "2026-04-20T10:00:00+01:00",
        "date": date,
        "from_user": from_user,
        "to_user": to_user,
        "home_amount": home_amount,
    }


def _tombstone(target_id: str, operation: str = "delete") -> dict:
    return {
        "id": "tb_1",
        "target_id": target_id,
        "target_type": "expense",
        "operation": operation,
    }


# ------------------------------------------------------------------ materialise_expenses


def test_materialise_no_tombstones():
    expenses = [_expense(id_="ex_1"), _expense(id_="ex_2")]
    assert materialise_expenses(expenses, []) == expenses


def test_materialise_delete_removes_expense():
    expenses = [_expense(id_="ex_1"), _expense(id_="ex_2")]
    tombstones = [_tombstone("ex_1", "delete")]
    result = materialise_expenses(expenses, tombstones)
    assert len(result) == 1
    assert result[0]["id"] == "ex_2"


def test_materialise_edit_tombstone_removes_old():
    """Edit writes new record first, then tombstone on old. Old must be dropped."""
    old = _expense(id_="ex_old", home_amount=100.0)
    new = _expense(id_="ex_new", home_amount=120.0)
    tombstone = _tombstone("ex_old", "edit")
    result = materialise_expenses([old, new], [tombstone])
    assert len(result) == 1
    assert result[0]["id"] == "ex_new"


def test_materialise_double_edit():
    """Expense edited twice: only the last replacement survives."""
    e1 = _expense(id_="ex_1", home_amount=10.0)
    e2 = _expense(id_="ex_2", home_amount=20.0)
    e3 = _expense(id_="ex_3", home_amount=30.0)
    tombstones = [
        _tombstone("ex_1", "edit"),
        _tombstone("ex_2", "edit"),
    ]
    result = materialise_expenses([e1, e2, e3], tombstones)
    assert len(result) == 1
    assert result[0]["id"] == "ex_3"


def test_materialise_settlements():
    settlements = [_settlement(id_="sl_1"), _settlement(id_="sl_2")]
    tb = {"id": "tb_1", "target_id": "sl_1", "target_type": "settlement", "operation": "delete"}
    result = materialise_settlements(settlements, [tb])
    assert len(result) == 1
    assert result[0]["id"] == "sl_2"


# ------------------------------------------------------------------ compute_user_share


def test_share_equal_two_users():
    expense = _expense(
        home_amount=100.0,
        categories=[
            {"name": "Groceries", "home_amount": 100.0, "split": _equal_split(["u1", "u2"])}
        ],
    )
    assert compute_user_share(expense, "u1") == Decimal("50.00")
    assert compute_user_share(expense, "u2") == Decimal("50.00")


def test_share_equal_absent_user_returns_zero():
    expense = _expense(
        home_amount=100.0,
        categories=[
            {"name": "Groceries", "home_amount": 100.0, "split": _equal_split(["u1", "u2"])}
        ],
    )
    assert compute_user_share(expense, "u3") == Decimal("0")


def test_share_exact_split():
    expense = _expense(
        home_amount=100.0,
        categories=[
            {
                "name": "Groceries",
                "home_amount": 100.0,
                "split": _exact_split([("u1", 70.0), ("u2", 30.0)]),
            }
        ],
    )
    assert compute_user_share(expense, "u1") == Decimal("70.00")
    assert compute_user_share(expense, "u2") == Decimal("30.00")


def test_share_shares_method():
    expense = _expense(
        home_amount=90.0,
        categories=[
            {
                "name": "Groceries",
                "home_amount": 90.0,
                "split": {
                    "method": "shares",
                    "shares": [
                        {"user_id": "u1", "value": 2},
                        {"user_id": "u2", "value": 1},
                    ],
                },
            }
        ],
    )
    assert compute_user_share(expense, "u1") == Decimal("60.00")
    assert compute_user_share(expense, "u2") == Decimal("30.00")


def test_share_percentage_method():
    expense = _expense(
        home_amount=100.0,
        categories=[
            {
                "name": "Groceries",
                "home_amount": 100.0,
                "split": {
                    "method": "percentage",
                    "shares": [
                        {"user_id": "u1", "value": 60},
                        {"user_id": "u2", "value": 40},
                    ],
                },
            }
        ],
    )
    assert compute_user_share(expense, "u1") == Decimal("60.00")
    assert compute_user_share(expense, "u2") == Decimal("40.00")


def test_share_multi_category():
    """SPEC §9.3 Tesco example — exact numeric match."""
    expense = {
        "id": "ex_tesco",
        "date": "2026-04-15",
        "paid_by": "u1",
        "home_amount": 82.40,
        "home_currency": "GBP",
        "categories": [
            {
                "name": "Groceries",
                "home_amount": 55.20,
                "split": _equal_split(["u1", "u2"]),
            },
            {
                "name": "Household",
                "home_amount": 18.70,
                "split": _equal_split(["u1", "u2"]),
            },
            {
                "name": "Alcohol",
                "home_amount": 8.50,
                "split": _exact_split([("u1", 8.50), ("u2", 0.00)]),
            },
        ],
    }
    # u1 share: 27.60 + 9.35 + 8.50 = 45.45
    # u2 share: 27.60 + 9.35 + 0.00 = 36.95
    assert compute_user_share(expense, "u1") == Decimal("45.45")
    assert compute_user_share(expense, "u2") == Decimal("36.95")


# ------------------------------------------------------------------ compute_balances


def test_balances_simple_50_50():
    expense = _expense(paid_by="u1", home_amount=100.0)
    # u1 paid 100, owes 50 → net +50
    # u2 paid 0, owes 50 → net -50
    balances = compute_balances([expense], [])
    assert balances["u1"] == Decimal("50.00")
    assert balances["u2"] == Decimal("-50.00")


def test_balances_settlement_reduces_debt():
    expense = _expense(paid_by="u1", home_amount=100.0)
    settlement = _settlement(from_user="u2", to_user="u1", home_amount=50.0)
    balances = compute_balances([expense], [settlement])
    assert balances["u1"] == Decimal("0.00")
    assert balances["u2"] == Decimal("0.00")


def test_balances_tombstoned_expense_excluded():
    expense = _expense(id_="ex_1", paid_by="u1", home_amount=100.0)
    # Materialise first — tombstoned expenses should not be passed to compute_balances
    materialised = materialise_expenses([expense], [_tombstone("ex_1")])
    balances = compute_balances(materialised, [])
    assert balances.get("u1", Decimal("0")) == Decimal("0")
    assert balances.get("u2", Decimal("0")) == Decimal("0")


def test_balances_tesco_example():
    """SPEC §9.3: u1 paid 82.40, u2 owes 36.95."""
    expense = {
        "id": "ex_tesco",
        "date": "2026-04-15",
        "paid_by": "u1",
        "home_amount": 82.40,
        "home_currency": "GBP",
        "categories": [
            {"name": "Groceries", "home_amount": 55.20, "split": _equal_split(["u1", "u2"])},
            {"name": "Household", "home_amount": 18.70, "split": _equal_split(["u1", "u2"])},
            {
                "name": "Alcohol",
                "home_amount": 8.50,
                "split": _exact_split([("u1", 8.50), ("u2", 0.00)]),
            },
        ],
    }
    balances = compute_balances([expense], [])
    assert balances["u1"] == Decimal("36.95")  # u1 paid 82.40, owes 45.45 → +36.95
    assert balances["u2"] == Decimal("-36.95")


def test_balances_three_participants():
    expense = {
        "id": "ex_1",
        "date": "2026-04-15",
        "paid_by": "u1",
        "home_amount": 90.0,
        "home_currency": "GBP",
        "categories": [
            {
                "name": "Groceries",
                "home_amount": 90.0,
                "split": {
                    "method": "equal",
                    "shares": [
                        {"user_id": "u1", "value": 33},
                        {"user_id": "u2", "value": 33},
                        {"user_id": "u3", "value": 34},
                    ],
                },
            }
        ],
    }
    balances = compute_balances([expense], [])
    # Sum of balances must be ~0
    total = sum(balances.values())
    assert abs(total) <= Decimal("0.02")


# ------------------------------------------------------------------ compute_pairwise_balances


def test_pairwise_two_users():
    expense = _expense(paid_by="u1", home_amount=100.0)
    pairwise = compute_pairwise_balances([expense], [])
    assert pairwise[("u2", "u1")] == Decimal("50.00")


def test_pairwise_settlement_reduces():
    expense = _expense(paid_by="u1", home_amount=100.0)
    settlement = _settlement(from_user="u2", to_user="u1", home_amount=30.0)
    pairwise = compute_pairwise_balances([expense], [settlement])
    assert pairwise[("u2", "u1")] == Decimal("20.00")


# ------------------------------------------------------------------ compute_monthly_spending


def test_monthly_spending_within_month():
    expense = _expense(date="2026-04-15", home_amount=100.0)
    result = compute_monthly_spending([expense], "u1", 2026, 4)
    assert result["total"] == Decimal("50.00")
    assert result["by_category"]["Groceries"] == Decimal("50.00")


def test_monthly_spending_household_total():
    expense = _expense(date="2026-04-15", home_amount=100.0)
    result = compute_monthly_spending([expense], None, 2026, 4)
    assert result["total"] == Decimal("100.00")


def test_monthly_spending_excludes_other_month():
    expense = _expense(date="2026-05-01", home_amount=100.0)
    result = compute_monthly_spending([expense], "u1", 2026, 4)
    assert result["total"] == Decimal("0")


def test_monthly_spending_tesco_attributes():
    """SPEC §9.3 Tesco: per-category attributes for u1."""
    expense = {
        "id": "ex_tesco",
        "date": "2026-04-15",
        "paid_by": "u1",
        "home_amount": 82.40,
        "home_currency": "GBP",
        "categories": [
            {"name": "Groceries", "home_amount": 55.20, "split": _equal_split(["u1", "u2"])},
            {"name": "Household", "home_amount": 18.70, "split": _equal_split(["u1", "u2"])},
            {
                "name": "Alcohol",
                "home_amount": 8.50,
                "split": _exact_split([("u1", 8.50), ("u2", 0.00)]),
            },
        ],
    }
    result = compute_monthly_spending([expense], "u1", 2026, 4)
    assert result["by_category"]["Groceries"] == Decimal("27.60")
    assert result["by_category"]["Household"] == Decimal("9.35")
    assert result["by_category"]["Alcohol"] == Decimal("8.50")


def test_monthly_spending_last_second_april():
    expense = _expense(date="2026-04-30", home_amount=100.0)
    assert compute_monthly_spending([expense], "u1", 2026, 4)["total"] == Decimal("50.00")
    assert compute_monthly_spending([expense], "u1", 2026, 5)["total"] == Decimal("0")


# ------------------------------------------------------------------ validate_split


def test_validate_split_equal_valid():
    split = _equal_split(["u1", "u2"])
    validate_split(split, allocation_amount=Decimal("100"), participants={"u1", "u2"})


def test_validate_split_equal_all_zero_fails():
    split = {"method": "equal", "shares": [{"user_id": "u1", "value": 0}]}
    with pytest.raises(SplitsmartValidationError, match="zero"):
        validate_split(split, allocation_amount=Decimal("100"), participants={"u1"})


def test_validate_split_exact_sum_mismatch():
    split = _exact_split([("u1", 60.0), ("u2", 30.0)])  # sum 90, not 100
    with pytest.raises(SplitsmartValidationError, match="90"):
        validate_split(split, allocation_amount=Decimal("100"), participants={"u1", "u2"})


def test_validate_split_exact_correct():
    split = _exact_split([("u1", 70.0), ("u2", 30.0)])
    validate_split(split, allocation_amount=Decimal("100"), participants={"u1", "u2"})


def test_validate_split_unknown_user():
    split = {"method": "equal", "shares": [{"user_id": "unknown", "value": 100}]}
    with pytest.raises(SplitsmartValidationError, match="unknown"):
        validate_split(split, allocation_amount=Decimal("100"), participants={"u1", "u2"})


def test_validate_split_negative_value():
    split = {"method": "equal", "shares": [{"user_id": "u1", "value": -10}]}
    with pytest.raises(SplitsmartValidationError, match="non-negative"):
        validate_split(split, allocation_amount=Decimal("100"), participants={"u1"})


def test_validate_split_invalid_method():
    split = {"method": "magic", "shares": [{"user_id": "u1", "value": 100}]}
    with pytest.raises(SplitsmartValidationError, match="method"):
        validate_split(split, allocation_amount=Decimal("100"), participants={"u1"})


# ------------------------------------------------------------------ validate_expense_record


def _valid_expense_record(**overrides) -> dict:
    base = {
        "id": "ex_1",
        "paid_by": "u1",
        "home_amount": 100.0,
        "home_currency": "GBP",
        "categories": [
            {
                "name": "Groceries",
                "home_amount": 100.0,
                "split": _equal_split(["u1", "u2"]),
            }
        ],
    }
    base.update(overrides)
    return base


def test_validate_expense_record_valid():
    validate_expense_record(
        _valid_expense_record(),
        participants=USERS,
        home_currency="GBP",
        known_categories={"Groceries"},
    )


def test_validate_expense_record_unknown_paid_by():
    with pytest.raises(SplitsmartValidationError, match="paid_by"):
        validate_expense_record(
            _valid_expense_record(paid_by="unknown"),
            participants=USERS,
            home_currency="GBP",
            known_categories={"Groceries"},
        )


def test_validate_expense_record_no_categories():
    with pytest.raises(SplitsmartValidationError, match="category"):
        validate_expense_record(
            _valid_expense_record(categories=[]),
            participants=USERS,
            home_currency="GBP",
            known_categories={"Groceries"},
        )


def test_validate_expense_record_sum_drift():
    record = _valid_expense_record(
        home_amount=100.0,
        categories=[
            {"name": "Groceries", "home_amount": 60.0, "split": _equal_split(["u1", "u2"])},
            {"name": "Household", "home_amount": 30.0, "split": _equal_split(["u1", "u2"])},
        ],
    )
    with pytest.raises(SplitsmartValidationError, match="90"):
        validate_expense_record(
            record,
            participants=USERS,
            home_currency="GBP",
            known_categories={"Groceries", "Household"},
        )


def test_validate_expense_record_negative_allocation():
    record = _valid_expense_record(
        home_amount=100.0,
        categories=[
            {"name": "Groceries", "home_amount": -100.0, "split": _equal_split(["u1", "u2"])},
        ],
    )
    with pytest.raises(SplitsmartValidationError):
        validate_expense_record(
            record, participants=USERS, home_currency="GBP", known_categories={"Groceries"}
        )


# ------------------------------------------------------------------ validate_settlement_record


def test_validate_settlement_valid():
    record = {"from_user": "u1", "to_user": "u2", "home_amount": 50.0}
    validate_settlement_record(record, participants=USERS, home_currency="GBP")


def test_validate_settlement_same_user():
    record = {"from_user": "u1", "to_user": "u1", "home_amount": 50.0}
    with pytest.raises(SplitsmartValidationError, match="different"):
        validate_settlement_record(record, participants=USERS, home_currency="GBP")


def test_validate_settlement_zero_amount():
    record = {"from_user": "u1", "to_user": "u2", "home_amount": 0.0}
    with pytest.raises(SplitsmartValidationError, match="positive"):
        validate_settlement_record(record, participants=USERS, home_currency="GBP")


def test_validate_settlement_unknown_user():
    record = {"from_user": "u1", "to_user": "unknown", "home_amount": 50.0}
    with pytest.raises(SplitsmartValidationError, match="to_user"):
        validate_settlement_record(record, participants=USERS, home_currency="GBP")


# ------------------------------------------------------------------ build_settlement_record


def test_build_settlement_record_includes_created_by():
    record = build_settlement_record(
        date="2026-04-20",
        from_user="u1",
        to_user="u2",
        amount=20.0,
        currency="GBP",
        home_currency="GBP",
        notes=None,
        created_by="u1",
    )
    assert record["created_by"] == "u1"
    assert record["from_user"] == "u1"
    assert record["to_user"] == "u2"
    assert record["amount"] == 20.0
    assert record["id"].startswith("sl_")
