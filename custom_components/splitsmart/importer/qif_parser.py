"""QIF parser — hand-rolled, fixed schema.

QIF is a line-oriented format where each line starts with a single-character
code identifying the field. Records are terminated by a line containing
only ``^``. The type directive at the top (``!Type:Bank``, ``!Type:CCard``)
is ignored — we only care about the transaction body.

Field codes consumed:
  D — date
  T — transaction amount (signed; negative = debit/expense)
  P — payee
  M — memo
  L — category label

Other codes (``C`` cleared status, ``N`` reference, split lines) are
kept on ``RawRow.raw`` for audit but not otherwise consumed.
"""

from __future__ import annotations

import logging
import pathlib
from typing import Any

import aiofiles

from .mapping import coerce_amount, file_origin_hash, parse_date
from .types import FileInspection, ParseError, ParseOutcome, RawRow

_LOGGER = logging.getLogger(__name__)


def _inspection_payload(path: pathlib.Path) -> FileInspection:
    return FileInspection(
        preset=None,
        preset_confidence=None,
        headers=[],
        sample_rows=[],
        file_origin_hash=file_origin_hash(
            headers=[],
            extension=path.suffix.lstrip("."),
            first_row_column_count=0,
        ),
        saved_mapping=None,
    )


async def inspect(path: pathlib.Path) -> FileInspection:
    return _inspection_payload(path)


def _finalise_record(
    current: dict[str, str],
    row_index: int,
    outcome: ParseOutcome,
    *,
    currency: str,
) -> None:
    """Turn an accumulated {code: value} dict into a RawRow, or a ParseError."""
    outcome.row_count_raw += 1
    try:
        date_iso = parse_date(current.get("D", ""), "auto")
        amount_raw = coerce_amount(current.get("T", "0"))
        # QIF convention: negative = expense. Flip to the Splitsmart convention.
        amount = round(-amount_raw, 2)
        raw: dict[str, Any] = dict(current)
        outcome.rows.append(
            RawRow(
                date=date_iso,
                description=current.get("P", "").strip(),
                amount=amount,
                currency=currency,
                category_hint=current.get("L", "").strip() or None,
                notes=current.get("M", "").strip() or None,
                raw=raw,
            )
        )
    except (ValueError, KeyError) as exc:
        outcome.errors.append(ParseError(row_index=row_index, message=str(exc)))


async def parse(path: pathlib.Path, mapping: object = None) -> ParseOutcome:
    """QIF schema is fixed — ``mapping`` is accepted for surface symmetry
    but ignored. QIF carries no currency field; rows default to GBP and
    the user can edit at promotion if that's wrong."""
    del mapping
    currency = "GBP"
    outcome = ParseOutcome()

    async with aiofiles.open(path, encoding="utf-8") as fh:
        text = await fh.read()

    current: dict[str, str] = {}
    row_index = 0

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("!"):
            # Type directive — skipped; we treat all transaction types uniformly.
            continue
        if line == "^":
            if current:
                row_index += 1
                _finalise_record(current, row_index, outcome, currency=currency)
                current = {}
            continue
        code = line[0]
        value = line[1:]
        # Split-line codes (S, $, E, %) land on the parent record in `raw`
        # but don't change the primary fields; by overwriting we implicitly
        # keep only the last split, which is enough for the one-record shape
        # M3 writes into staging.
        current[code] = value

    # File may omit the trailing ^ on the last record.
    if current:
        row_index += 1
        _finalise_record(current, row_index, outcome, currency=currency)

    _LOGGER.debug(
        "QIF parse of %s: %d rows, %d errors",
        path.name,
        len(outcome.rows),
        len(outcome.errors),
    )
    return outcome
