"""Multiset duplicate detection for statement imports.

Per SPEC §12.4, imports use multiset accounting: re-importing a statement
never double-counts already-seen rows, while genuine same-day duplicates
(three coffees on the same date, same amount) still all land.

The function here is pure. Caller-side pre-filtering is load-bearing —
see :func:`partition_by_dedup`'s docstring for the contract.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from .normalise import dedup_hash
from .types import RawRow


def _hash_for_shared_expense(record: dict[str, Any]) -> str:
    """Shared expenses do not carry a ``dedup_hash`` field in M1's schema,
    so we recompute from ``date`` + ``amount`` + ``currency`` + ``description``.
    Must use the same recipe as staging rows and file rows for the multiset
    accounting to converge."""
    return dedup_hash(
        date=record["date"],
        amount=float(record["amount"]),
        currency=record["currency"],
        description=record["description"],
    )


def _hash_for_file_row(row: RawRow) -> str:
    return dedup_hash(
        date=row["date"],
        amount=float(row["amount"]),
        currency=row["currency"],
        description=row["description"],
    )


def partition_by_dedup(
    file_rows: list[RawRow],
    *,
    existing_staging: list[dict[str, Any]],
    existing_shared: list[dict[str, Any]],
    skipped_staging_tombstones: list[dict[str, Any]],
) -> tuple[list[RawRow], list[RawRow]]:
    """Partition ``file_rows`` into ``(to_import, to_skip_as_dup)``.

    Caller responsibilities (enforced by the service handler, not by this
    function — an unused validation parameter here would just be temptation):

    - ``existing_staging``: the uploader's staging, materialised
      (post-tombstone). Per SPEC §7, another participant's staging is
      **not** passed here.
    - ``existing_shared``: the coordinator's materialised expenses, visible
      to every participant.
    - ``skipped_staging_tombstones``: tombstones with ``target_type='staging'``
      and ``operation='discard'`` that target rows originally uploaded by
      this user. Promote tombstones are **not** included: the resulting
      shared expense is already in ``existing_shared``, so counting the
      promote tombstone too would double-count and block legitimate
      re-occurrences.

    Algorithm: multiset difference. For each dedup hash, the number of
    importable rows is ``max(0, file_count - existing_count)``. Within the
    file, the first N matching rows are imported and the rest are
    skipped, preserving file order for readability.
    """
    existing_counts: Counter[str] = Counter()

    for row in existing_staging:
        # Staging records carry dedup_hash on the record itself (SPEC §6.2).
        existing_counts[row["dedup_hash"]] += 1

    for row in existing_shared:
        existing_counts[_hash_for_shared_expense(row)] += 1

    for tb in skipped_staging_tombstones:
        # Tombstone's previous_snapshot is the whole pre-tombstone staging row,
        # so the dedup_hash travels with it.
        snapshot = tb.get("previous_snapshot") or {}
        h = snapshot.get("dedup_hash")
        if h:
            existing_counts[h] += 1

    to_import: list[RawRow] = []
    to_skip: list[RawRow] = []

    for row in file_rows:
        h = _hash_for_file_row(row)
        if existing_counts[h] > 0:
            existing_counts[h] -= 1
            to_skip.append(row)
        else:
            to_import.append(row)

    return to_import, to_skip
