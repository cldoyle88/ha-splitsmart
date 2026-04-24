"""Tests for importer.dedup — multiset duplicate detection.

Each test corresponds to a scenario in M3_PLAN.md §4 "Edge cases the
tests must cover", plus one degenerate empty-input case.
"""

from __future__ import annotations

from typing import Any

import pytest

from custom_components.splitsmart.importer.dedup import partition_by_dedup
from custom_components.splitsmart.importer.normalise import dedup_hash
from custom_components.splitsmart.importer.types import RawRow

# --------------------------------------------------------- helpers


def make_row(
    *,
    date: str = "2026-04-15",
    amount: float = 4.50,
    currency: str = "GBP",
    description: str = "Coffee",
) -> RawRow:
    return RawRow(
        date=date,
        amount=amount,
        currency=currency,
        description=description,
        category_hint=None,
        notes=None,
        raw={},
    )


def make_staging_record(row: RawRow) -> dict[str, Any]:
    """Simulate a materialised staging record as the coordinator would produce."""
    return {
        "id": f"st_{row['description']}_{row['date']}",
        "date": row["date"],
        "description": row["description"],
        "amount": row["amount"],
        "currency": row["currency"],
        "rule_action": "pending",
        "dedup_hash": dedup_hash(
            date=row["date"],
            amount=row["amount"],
            currency=row["currency"],
            description=row["description"],
        ),
    }


def make_shared_expense(row: RawRow) -> dict[str, Any]:
    """Shared expenses carry no dedup_hash in M1 — dedup recomputes from fields."""
    return {
        "id": f"ex_{row['description']}_{row['date']}",
        "date": row["date"],
        "description": row["description"],
        "amount": row["amount"],
        "currency": row["currency"],
    }


def make_discard_tombstone(row: RawRow) -> dict[str, Any]:
    return {
        "target_type": "staging",
        "operation": "discard",
        "previous_snapshot": make_staging_record(row),
    }


# --------------------------------------------------------- case 1: same-day dupes


def test_three_identical_coffees_all_import_the_first_time() -> None:
    coffees = [make_row() for _ in range(3)]
    to_import, to_skip = partition_by_dedup(
        coffees,
        existing_staging=[],
        existing_shared=[],
        skipped_staging_tombstones=[],
    )
    assert len(to_import) == 3
    assert to_skip == []


def test_reimport_of_same_file_skips_all_rows() -> None:
    coffees = [make_row() for _ in range(3)]
    # Simulate "already staged" state from the first import.
    existing = [make_staging_record(r) for r in coffees]
    to_import, to_skip = partition_by_dedup(
        coffees,
        existing_staging=existing,
        existing_shared=[],
        skipped_staging_tombstones=[],
    )
    assert to_import == []
    assert len(to_skip) == 3


# --------------------------------------------------------- case 2: one promoted


def test_one_promoted_reimport_accounts_for_all_three() -> None:
    """After first import of 3 coffees, user promotes one. Next re-import
    of the same 3-row file must see: 2 remaining staging + 1 shared = 3
    existing, so all 3 file rows are skipped as duplicates. The
    promote-tombstone is NOT counted — it's already represented by the
    shared expense. This is why promote tombstones use operation='promote'
    rather than 'discard'."""
    coffees = [make_row() for _ in range(3)]
    remaining_staging = [make_staging_record(r) for r in coffees[1:]]
    promoted_shared = [make_shared_expense(coffees[0])]

    to_import, to_skip = partition_by_dedup(
        coffees,
        existing_staging=remaining_staging,
        existing_shared=promoted_shared,
        skipped_staging_tombstones=[],
    )
    # 2 staging + 1 shared = 3 existing; file = 3 → 0 new imports, 3 skips.
    assert to_import == []
    assert len(to_skip) == 3


def test_three_coffees_one_promoted_one_additional_on_reimport() -> None:
    """When the incoming file has one more coffee than the previous import,
    the extra coffee must actually land."""
    previous_file = [make_row() for _ in range(3)]
    # User promoted one, leaving two staging + one shared.
    staging = [make_staging_record(r) for r in previous_file[1:]]
    shared = [make_shared_expense(previous_file[0])]

    # Next month's file contains the original 3 plus one new coffee.
    new_file = [*previous_file, make_row()]

    to_import, to_skip = partition_by_dedup(
        new_file,
        existing_staging=staging,
        existing_shared=shared,
        skipped_staging_tombstones=[],
    )
    assert len(to_import) == 1
    assert len(to_skip) == 3


# --------------------------------------------------------- case 3: one skipped


def test_one_skipped_reimport_skips_all_three() -> None:
    coffees = [make_row() for _ in range(3)]
    # After first import: 3 in staging, user skipped 1 — effective staging 2,
    # plus one discard tombstone.
    staging = [make_staging_record(r) for r in coffees[1:]]
    tombstones = [make_discard_tombstone(coffees[0])]

    to_import, to_skip = partition_by_dedup(
        coffees,
        existing_staging=staging,
        existing_shared=[],
        skipped_staging_tombstones=tombstones,
    )
    # 2 staging + 1 discard = 3 existing; file = 3 → 0 new.
    assert to_import == []
    assert len(to_skip) == 3


# --------------------------------------------------------- case 4: growing file


def test_growing_file_imports_only_the_delta() -> None:
    # First import: 2 coffees.
    week_one = [make_row() for _ in range(2)]
    staging_after_week_one = [make_staging_record(r) for r in week_one]

    # Next statement: same 2 coffees plus 1 new one.
    week_two = [*week_one, make_row()]

    to_import, to_skip = partition_by_dedup(
        week_two,
        existing_staging=staging_after_week_one,
        existing_shared=[],
        skipped_staging_tombstones=[],
    )
    assert len(to_import) == 1
    assert len(to_skip) == 2


# --------------------------------------------------------- case 5: normalisation


def test_normalisation_collision_counts_both_as_same_hash() -> None:
    """Two rows differing only by a trailing date suffix collapse to one
    hash. The normalisation is the whole point of the dedup recipe."""
    row_a = make_row(description="TFL TRAVEL 15/04")
    row_b = make_row(description="TFL TRAVEL 16/04")
    # Both must hash identically after normalisation.
    assert dedup_hash(
        date=row_a["date"],
        amount=row_a["amount"],
        currency=row_a["currency"],
        description=row_a["description"],
    ) == dedup_hash(
        date=row_b["date"],
        amount=row_b["amount"],
        currency=row_b["currency"],
        description=row_b["description"],
    )
    # File-side: 2 rows, same hash. Existing: 0. Should import both.
    to_import, to_skip = partition_by_dedup(
        [row_a, row_b],
        existing_staging=[],
        existing_shared=[],
        skipped_staging_tombstones=[],
    )
    assert len(to_import) == 2
    assert to_skip == []

    # With one already in staging: import 1, skip 1.
    existing = [make_staging_record(row_a)]
    to_import, to_skip = partition_by_dedup(
        [row_a, row_b],
        existing_staging=existing,
        existing_shared=[],
        skipped_staging_tombstones=[],
    )
    assert len(to_import) == 1
    assert len(to_skip) == 1


# --------------------------------------------------------- case 6: cross-user privacy


def test_cross_user_staging_is_caller_filtered_not_dedup_concern() -> None:
    """Privacy is a caller responsibility — the service handler passes only
    this user's staging. Dedup should import when existing lists are empty,
    regardless of what another user may have in their own staging."""
    netflix = make_row(description="Netflix", amount=15.99)
    to_import, to_skip = partition_by_dedup(
        [netflix],
        existing_staging=[],  # this user's staging is empty even though user A has it
        existing_shared=[],
        skipped_staging_tombstones=[],
    )
    assert len(to_import) == 1
    assert to_skip == []


# --------------------------------------------------------- case 7: promoted then deleted


def test_promoted_then_deleted_shared_allows_reimport() -> None:
    """If the shared expense gets deleted by the user, effective_shared is
    empty (the caller passes the post-tombstone materialised list). The
    promote tombstone is not in skipped_staging_tombstones (it's a
    promote, not a discard). Result: the row can land again."""
    netflix = make_row(description="Netflix", amount=15.99)
    to_import, _ = partition_by_dedup(
        [netflix],
        existing_staging=[],
        existing_shared=[],  # promoted then deleted → materialised list is empty
        skipped_staging_tombstones=[],  # no discard tombstone for this row
    )
    assert len(to_import) == 1


# --------------------------------------------------------- case 9: empty inputs


def test_empty_file_rows_returns_empty_tuple() -> None:
    """OFX with zero transactions — caller must be able to hand dedup an
    empty file list without special-casing."""
    to_import, to_skip = partition_by_dedup(
        file_rows=[],
        existing_staging=[make_staging_record(make_row())],
        existing_shared=[],
        skipped_staging_tombstones=[],
    )
    assert to_import == []
    assert to_skip == []


def test_empty_everything_returns_empty_tuple() -> None:
    to_import, to_skip = partition_by_dedup(
        file_rows=[],
        existing_staging=[],
        existing_shared=[],
        skipped_staging_tombstones=[],
    )
    assert to_import == []
    assert to_skip == []


# --------------------------------------------------------- ordering / preservation


def test_import_order_matches_file_order() -> None:
    """When only some of a hash group imports, file order is preserved:
    the first N are imported, the rest skipped. Keeps the user-facing
    "imported N of M" report readable."""
    row_1 = make_row(date="2026-04-15", amount=4.50, description="Coffee")
    row_2 = make_row(date="2026-04-15", amount=4.50, description="Coffee")
    row_3 = make_row(date="2026-04-15", amount=4.50, description="Coffee")
    # One matching row already exists.
    existing = [make_staging_record(row_1)]
    to_import, to_skip = partition_by_dedup(
        [row_1, row_2, row_3],
        existing_staging=existing,
        existing_shared=[],
        skipped_staging_tombstones=[],
    )
    # First row skipped, next two imported.
    assert len(to_skip) == 1
    assert len(to_import) == 2


# --------------------------------------------------------- invariant


@pytest.mark.parametrize(
    ("n_existing", "n_file"),
    [(0, 0), (0, 3), (3, 0), (2, 3), (3, 2), (5, 5), (1, 7)],
)
def test_partition_invariant_import_plus_skip_equals_file_length(
    n_existing: int, n_file: int
) -> None:
    """Every file row must end up in exactly one of the two buckets.
    A property guard against off-by-one and double-counting."""
    rows = [make_row() for _ in range(n_file)]
    existing = [make_staging_record(make_row()) for _ in range(n_existing)]
    to_import, to_skip = partition_by_dedup(
        rows,
        existing_staging=existing,
        existing_shared=[],
        skipped_staging_tombstones=[],
    )
    assert len(to_import) + len(to_skip) == n_file
