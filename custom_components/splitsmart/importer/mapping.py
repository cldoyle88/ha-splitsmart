"""File-origin hashing, mapping persistence, and raw-row translation.

Three concerns live here:

1. ``file_origin_hash`` — a stable identifier for "this kind of file"
   (same bank export, same shape) so a mapping the user committed once
   can be re-used next month without re-asking.

2. ``save_mapping`` / ``load_saved_mappings`` — append-only persistence
   under ``/config/splitsmart/mappings.jsonl``. Newest entry per hash wins.

3. ``apply_mapping`` — translate one raw row (column name -> cell value)
   into a canonical ``RawRow``, using a ``Mapping`` to resolve which
   columns hold which role and to normalise amount signage + dates.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime
from typing import Any

from ..storage import SplitsmartStorage
from .types import Mapping, RawRow

_LOGGER = logging.getLogger(__name__)


# ------------------------------------------------------ file_origin_hash


def file_origin_hash(
    *,
    headers: list[str],
    extension: str,
    first_row_column_count: int,
) -> str:
    """Stable identifier for this file's schema.

    Month-to-month exports from the same bank share headers; different
    banks differ. Schema changes within a bank (e.g. Monzo Classic vs
    Monzo Plus) produce different hashes because at least one column
    differs. SHA-1 is fine — this is a fingerprint, not a secret.
    """
    normalised = "\n".join(h.strip().lower() for h in headers)
    canonical = f"{normalised}|{first_row_column_count}|{extension.lstrip('.').lower()}"
    digest = hashlib.sha1(canonical.encode("utf-8"), usedforsecurity=False).hexdigest()
    return f"sha1:{digest}"


# ------------------------------------------------------ persistence


async def save_mapping(
    storage: SplitsmartStorage,
    origin_hash: str,
    mapping: Mapping,
) -> None:
    """Append a mapping entry; the newest entry per hash wins on read."""
    record: dict[str, Any] = {
        "file_origin_hash": origin_hash,
        "mapping": mapping,
        "saved_at": datetime.now(tz=UTC).astimezone().isoformat(),
    }
    await storage.append(storage.mappings_path, record)


async def load_saved_mappings(storage: SplitsmartStorage) -> dict[str, Mapping]:
    """Return {hash: newest mapping}. Later entries overwrite earlier."""
    records = await storage.read_all(storage.mappings_path)
    out: dict[str, Mapping] = {}
    for record in records:
        out[record["file_origin_hash"]] = record["mapping"]
    return out


# ------------------------------------------------------ apply_mapping

# Tried in order. UK-first because the primary deployment is UK.
_DATE_FORMATS = (
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%d/%m/%y",
    "%d-%m-%Y",
    "%Y/%m/%d",
    "%d %b %Y",
    "%d %B %Y",
)


def _parse_date(value: str, date_format: str) -> str:
    """Parse a date cell and return ISO-8601 YYYY-MM-DD.

    `date_format` may be a strptime pattern or the literal "auto", in
    which case the short try-list above is walked until one matches.
    Time-bearing ISO strings (Starling sometimes emits "2026-04-15T14:30:00Z")
    fall back to fromisoformat after stripping a trailing Z.
    """
    raw = value.strip()
    if date_format != "auto":
        return datetime.strptime(raw, date_format).date().isoformat()

    # Try fromisoformat first — handles "2026-04-15", "2026-04-15T14:30:00",
    # and (on 3.11+) "...Z" in some forms.
    try:
        return datetime.fromisoformat(raw.rstrip("Z")).date().isoformat()
    except ValueError:
        pass

    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"could not parse date {value!r}")


def _coerce_amount(value: str) -> float:
    """Parse a money string like "1,234.56" or "-£47.83" into a float."""
    cleaned = value.strip().replace(",", "").replace("£", "").replace("$", "").replace("€", "")
    # Some banks wrap negatives in parens: "(47.83)" => -47.83
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = "-" + cleaned[1:-1]
    return float(cleaned)


def apply_mapping(
    row: dict[str, str],
    mapping: Mapping,
) -> RawRow:
    """Translate one raw row to a RawRow, applying amount signage and
    date parsing. Raises ValueError on any field that cannot be parsed;
    the caller wraps in ParseError with row_index context.
    """
    date_col = mapping["date"]
    desc_col = mapping["description"]

    date = _parse_date(row[date_col], mapping.get("date_format", "auto"))
    description = row[desc_col].strip()

    # Amount: either a single signed column, or a debit/credit pair.
    amount_col = mapping.get("amount")
    debit_col = mapping.get("debit")
    credit_col = mapping.get("credit")
    if amount_col:
        raw_amount = _coerce_amount(row[amount_col])
        if mapping.get("amount_sign", "expense_negative") == "expense_negative":
            # Expenses stored as negative in the file → flip to positive.
            amount = -raw_amount
        else:
            amount = raw_amount
    elif debit_col and credit_col:
        debit = _coerce_amount(row[debit_col]) if row.get(debit_col, "").strip() else 0.0
        credit = _coerce_amount(row[credit_col]) if row.get(credit_col, "").strip() else 0.0
        # Debit is the expense amount; credit is income.
        amount = debit - credit
    else:
        raise ValueError("mapping must set either amount or the (debit, credit) pair")

    currency_col = mapping.get("currency")
    currency = (
        row[currency_col].strip()
        if currency_col and row.get(currency_col, "").strip()
        else mapping["currency_default"]
    ).upper()

    notes_parts: list[str] = []
    for col in mapping.get("notes_append", []):
        cell = row.get(col, "").strip()
        if cell:
            notes_parts.append(cell)
    notes = " · ".join(notes_parts) if notes_parts else None

    category_hint_col = mapping.get("category_hint")
    category_hint = (
        row[category_hint_col].strip() or None
        if category_hint_col and category_hint_col in row
        else None
    )

    return RawRow(
        date=date,
        description=description,
        amount=round(amount, 2),
        currency=currency,
        category_hint=category_hint,
        notes=notes,
        raw=dict(row),
    )
