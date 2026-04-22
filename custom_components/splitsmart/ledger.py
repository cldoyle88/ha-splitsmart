"""Pure balance calculators and record validators for Splitsmart.

No IO, no HA imports, no INFO-level logging. All money maths uses Decimal
internally; inputs and outputs cross the boundary as float (2dp) to match
on-disk storage.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, TypedDict

from .const import (
    ID_PREFIX_EXPENSE,
    ID_PREFIX_SETTLEMENT,
    SPLIT_METHOD_EQUAL,
    SPLIT_METHOD_EXACT,
    SPLIT_METHOD_PERCENTAGE,
    SPLIT_METHOD_SHARES,
    SPLIT_METHODS,
)
from .storage import new_id

_TWO_PLACES = Decimal("0.01")
_CENT = Decimal("0.01")


class SplitsmartValidationError(ValueError):
    """Raised when a record fails invariants. Message is user-facing."""


# ------------------------------------------------------------------ TypedDicts


class MonthlySpending(TypedDict):
    total: Decimal
    by_category: dict[str, Decimal]


# ------------------------------------------------------------------ materialisation


def materialise_expenses(
    raw_expenses: list[dict[str, Any]],
    tombstones: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return effective expense list. Drop any expense whose id appears as
    target_id in any tombstone — whether that tombstone is an edit or a delete.
    No chain-following needed: edit writes the new record first, tombstone second,
    so only the old id is ever targeted."""
    targeted: set[str] = {tb["target_id"] for tb in tombstones}
    return [e for e in raw_expenses if e["id"] not in targeted]


def materialise_settlements(
    raw_settlements: list[dict[str, Any]],
    tombstones: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return effective settlement list using the same tombstone rule."""
    targeted: set[str] = {tb["target_id"] for tb in tombstones}
    return [s for s in raw_settlements if s["id"] not in targeted]


def materialise_staging(
    raw_staging: list[dict[str, Any]],
    tombstones: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return effective staging list for one user.

    Drops any staging row whose id is the target of any tombstone —
    covering both ``discard`` (user skipped) and ``promote`` (user moved
    to the shared ledger). Staging ids have the ``st_`` prefix, which
    can't collide with expense (``ex_``) or settlement (``sl_``) ids, so
    passing the full tombstones list is safe without a target_type filter.
    """
    targeted: set[str] = {tb["target_id"] for tb in tombstones}
    return [r for r in raw_staging if r["id"] not in targeted]


# ------------------------------------------------------------------ share calculation


def _allocation_share(allocation: dict[str, Any], user_id: str) -> Decimal:
    """Return user_id's share of one category allocation in home currency."""
    split = allocation["split"]
    method = split["method"]
    home_amount = Decimal(str(allocation["home_amount"]))
    shares = split["shares"]

    if method in (SPLIT_METHOD_EQUAL, SPLIT_METHOD_PERCENTAGE):
        total_pct = sum(Decimal(str(s["value"])) for s in shares)
        if total_pct == 0:
            return Decimal("0")
        user_pct = next(
            (Decimal(str(s["value"])) for s in shares if s["user_id"] == user_id),
            Decimal("0"),
        )
        return (home_amount * user_pct / total_pct).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)

    if method == SPLIT_METHOD_SHARES:
        total_weight = sum(Decimal(str(s["value"])) for s in shares)
        if total_weight == 0:
            return Decimal("0")
        user_weight = next(
            (Decimal(str(s["value"])) for s in shares if s["user_id"] == user_id),
            Decimal("0"),
        )
        return (home_amount * user_weight / total_weight).quantize(
            _TWO_PLACES, rounding=ROUND_HALF_UP
        )

    if method == SPLIT_METHOD_EXACT:
        return Decimal(
            str(next((s["value"] for s in shares if s["user_id"] == user_id), 0))
        ).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)

    return Decimal("0")


def compute_user_share(expense: dict[str, Any], user_id: str) -> Decimal:
    """Sum of user_id's per-allocation share across every category."""
    return sum(
        (_allocation_share(alloc, user_id) for alloc in expense["categories"]),
        Decimal("0"),
    )


# ------------------------------------------------------------------ balance calculators


def compute_balances(
    expenses: list[dict[str, Any]],
    settlements: list[dict[str, Any]],
) -> dict[str, Decimal]:
    """Net per user. Positive => owed to them. Negative => they owe.
    Inputs are materialised (post-tombstone) lists."""
    balances: dict[str, Decimal] = {}

    for expense in expenses:
        paid_by = expense["paid_by"]
        home_amount = Decimal(str(expense["home_amount"]))
        # Collect all participants in this expense
        participants: set[str] = {
            s["user_id"] for alloc in expense["categories"] for s in alloc["split"]["shares"]
        }
        participants.add(paid_by)

        for uid in participants:
            balances.setdefault(uid, Decimal("0"))

        # payer advanced the full amount
        balances[paid_by] += home_amount
        # each person owes their share
        for uid in participants:
            share = compute_user_share(expense, uid)
            balances[uid] -= share

    for settlement in settlements:
        from_user = settlement["from_user"]
        to_user = settlement["to_user"]
        amount = Decimal(str(settlement["home_amount"]))
        balances.setdefault(from_user, Decimal("0"))
        balances.setdefault(to_user, Decimal("0"))
        # payer's debt decreases (their negative balance improves)
        balances[from_user] += amount
        # recipient received money, so they've been repaid
        balances[to_user] -= amount

    return balances


def compute_pairwise_balances(
    expenses: list[dict[str, Any]],
    settlements: list[dict[str, Any]],
) -> dict[tuple[str, str], Decimal]:
    """Directed: result[(a, b)] = amount a currently owes b.
    For 2-person setups this reduces to the couple's single debt figure."""
    pairwise: dict[tuple[str, str], Decimal] = {}

    for expense in expenses:
        paid_by = expense["paid_by"]
        participants: set[str] = {
            s["user_id"] for alloc in expense["categories"] for s in alloc["split"]["shares"]
        }
        for uid in participants:
            if uid == paid_by:
                continue
            share = compute_user_share(expense, uid)
            if share == 0:
                continue
            key = (uid, paid_by)
            pairwise[key] = pairwise.get(key, Decimal("0")) + share

    for settlement in settlements:
        from_user = settlement["from_user"]
        to_user = settlement["to_user"]
        amount = Decimal(str(settlement["home_amount"]))
        key = (from_user, to_user)
        pairwise[key] = pairwise.get(key, Decimal("0")) - amount
        # Allow negative (overpaid), callers can normalise if needed

    return pairwise


# ------------------------------------------------------------------ monthly spending


def compute_monthly_spending(
    expenses: list[dict[str, Any]],
    user_id: str | None,
    year: int,
    month: int,
) -> MonthlySpending:
    """Return total and per-category spending for the calendar month.
    user_id=None returns household totals."""
    total = Decimal("0")
    by_category: dict[str, Decimal] = {}

    for expense in expenses:
        expense_date = expense.get("date", "")
        try:
            d = datetime.strptime(expense_date, "%Y-%m-%d")
        except ValueError:
            continue
        if d.year != year or d.month != month:
            continue

        for alloc in expense["categories"]:
            cat = alloc["name"]
            if user_id is None:
                amount = Decimal(str(alloc["home_amount"]))
            else:
                amount = _allocation_share(alloc, user_id)
            by_category[cat] = by_category.get(cat, Decimal("0")) + amount
            total += amount

    return MonthlySpending(total=total, by_category=by_category)


# ------------------------------------------------------------------ validation


def validate_split(
    split: dict[str, Any],
    *,
    allocation_amount: Decimal,
    participants: set[str],
) -> None:
    """Raise SplitsmartValidationError if the split is invalid."""
    method = split.get("method")
    if method not in SPLIT_METHODS:
        raise SplitsmartValidationError(
            f"Invalid split method {method!r}. Must be one of {sorted(SPLIT_METHODS)}."
        )
    shares = split.get("shares", [])
    if not shares:
        raise SplitsmartValidationError("Split must have at least one share entry.")

    for entry in shares:
        uid = entry.get("user_id")
        if uid not in participants:
            raise SplitsmartValidationError(f"User {uid!r} in split is not a known participant.")
        val = Decimal(str(entry.get("value", 0)))
        if val < 0:
            raise SplitsmartValidationError(
                f"Split value for {uid!r} must be non-negative, got {val}."
            )

    if method in (SPLIT_METHOD_EQUAL, SPLIT_METHOD_PERCENTAGE, SPLIT_METHOD_SHARES):
        total = sum(Decimal(str(s["value"])) for s in shares)
        if total <= 0:
            raise SplitsmartValidationError(
                f"Split method {method!r} requires at least one non-zero value; all are zero."
            )

    if method == SPLIT_METHOD_EXACT:
        total = sum(Decimal(str(s["value"])) for s in shares).quantize(
            _CENT, rounding=ROUND_HALF_UP
        )
        expected = allocation_amount.quantize(_CENT, rounding=ROUND_HALF_UP)
        if abs(total - expected) > _CENT:
            raise SplitsmartValidationError(
                f"Exact split shares sum to {total} but allocation amount is {expected}."
            )


def validate_allocation(
    allocation: dict[str, Any],
    *,
    participants: set[str],
) -> None:
    """Validate one category allocation dict."""
    if not allocation.get("name"):
        raise SplitsmartValidationError("Category allocation must have a non-empty name.")
    home_amount = allocation.get("home_amount")
    if home_amount is None:
        raise SplitsmartValidationError("Category allocation must have a home_amount.")
    amount_dec = Decimal(str(home_amount))
    if amount_dec <= 0:
        raise SplitsmartValidationError(
            f"Category allocation home_amount must be positive, got {amount_dec}."
        )
    if "split" not in allocation:
        raise SplitsmartValidationError("Category allocation must have a split object.")
    validate_split(allocation["split"], allocation_amount=amount_dec, participants=participants)


def validate_expense_record(
    record: dict[str, Any],
    *,
    participants: set[str],
    home_currency: str,
    known_categories: set[str],
) -> None:
    """Enforce SPEC §9.6 invariants. Raises SplitsmartValidationError on failure."""
    paid_by = record.get("paid_by")
    if paid_by not in participants:
        raise SplitsmartValidationError(f"paid_by {paid_by!r} is not a known participant.")

    categories = record.get("categories")
    if not categories:
        raise SplitsmartValidationError("Expense must have at least one category allocation.")

    for alloc in categories:
        validate_allocation(alloc, participants=participants)
        # Soft warning for unknown category names — historical rows don't break
        cat_name = alloc.get("name", "")
        if cat_name and known_categories and cat_name not in known_categories:
            # Not a hard error per SPEC §9.6; just validate the allocation itself
            pass

    # Sum of allocation home_amounts must equal expense home_amount to 2dp
    alloc_sum = sum(Decimal(str(a["home_amount"])) for a in categories).quantize(
        _CENT, rounding=ROUND_HALF_UP
    )
    expense_home = Decimal(str(record.get("home_amount", 0))).quantize(
        _CENT, rounding=ROUND_HALF_UP
    )
    if abs(alloc_sum - expense_home) > _CENT:
        raise SplitsmartValidationError(
            f"Category allocations sum to {alloc_sum} but expense home_amount is {expense_home}."
        )


def validate_settlement_record(
    record: dict[str, Any],
    *,
    participants: set[str],
    home_currency: str,
) -> None:
    """Validate a settlement record."""
    from_user = record.get("from_user")
    to_user = record.get("to_user")
    if from_user not in participants:
        raise SplitsmartValidationError(f"from_user {from_user!r} is not a known participant.")
    if to_user not in participants:
        raise SplitsmartValidationError(f"to_user {to_user!r} is not a known participant.")
    if from_user == to_user:
        raise SplitsmartValidationError("from_user and to_user must be different.")
    amount = Decimal(str(record.get("home_amount", 0)))
    if amount <= 0:
        raise SplitsmartValidationError(f"Settlement home_amount must be positive, got {amount}.")


# ------------------------------------------------------------------ record builders


def build_expense_record(
    *,
    date: str,
    description: str,
    paid_by: str,
    amount: float,
    currency: str,
    home_currency: str,
    categories: list[dict[str, Any]],
    notes: str | None,
    source: str,
    staging_id: str | None,
    receipt_path: str | None,
    created_by: str,
) -> dict[str, Any]:
    """Build a fully-populated expense dict ready for disk.
    M1: currency must equal home_currency; fx_rate=1.0, home_amount=amount."""
    record_id = new_id(ID_PREFIX_EXPENSE)
    now = datetime.now(tz=UTC).astimezone().isoformat()
    return {
        "id": record_id,
        "created_at": now,
        "created_by": created_by,
        "date": date,
        "description": description,
        "paid_by": paid_by,
        "amount": round(amount, 2),
        "currency": currency,
        "home_amount": round(amount, 2),
        "home_currency": home_currency,
        "fx_rate": 1.0,
        "fx_date": date,
        "categories": categories,
        "source": source,
        "staging_id": staging_id,
        "receipt_path": receipt_path,
        "notes": notes,
        "comments": [],
    }


def build_settlement_record(
    *,
    date: str,
    from_user: str,
    to_user: str,
    amount: float,
    currency: str,
    home_currency: str,
    notes: str | None,
    created_by: str,
) -> dict[str, Any]:
    """Build a fully-populated settlement dict ready for disk."""
    record_id = new_id(ID_PREFIX_SETTLEMENT)
    now = datetime.now(tz=UTC).astimezone().isoformat()
    return {
        "id": record_id,
        "created_at": now,
        "created_by": created_by,
        "date": date,
        "from_user": from_user,
        "to_user": to_user,
        "amount": round(amount, 2),
        "currency": currency,
        "home_amount": round(amount, 2),
        "notes": notes,
    }
