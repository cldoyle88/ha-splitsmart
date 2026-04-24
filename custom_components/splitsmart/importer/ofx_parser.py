"""OFX parser — fixed schema, no preset / mapping needed.

ofxparse handles OFX 1.x SGML and 2.x XML equivalently. We expose the
same inspect/parse surface as the CSV/XLSX parsers for symmetry; the
mapping argument on ``parse`` is accepted but ignored.

Signage: OFX stores expenses as negative amounts; we flip to positive
so every downstream consumer sees the same convention.
"""

from __future__ import annotations

import asyncio
import logging
import pathlib

import ofxparse

from .mapping import file_origin_hash
from .types import FileInspection, ParseError, ParseOutcome, RawRow

_LOGGER = logging.getLogger(__name__)


def _inspection_payload(path: pathlib.Path) -> FileInspection:
    """OFX inspection carries no headers / samples / preset — the schema
    is fixed, so the UI skips straight to parse."""
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


def _parse_sync(path: pathlib.Path) -> ParseOutcome:
    outcome = ParseOutcome()
    with open(path, "rb") as fh:
        ofx = ofxparse.OfxParser.parse(fh)

    for acc in ofx.accounts:
        statement = acc.statement
        currency = (getattr(statement, "currency", None) or "GBP").upper()
        for i, tx in enumerate(statement.transactions, start=1):
            outcome.row_count_raw += 1
            try:
                # OFX TRNAMT is signed: negative for debits. Flip to positive.
                amount = round(-float(tx.amount), 2)
                payee = (tx.payee or "").strip()
                memo = (tx.memo or "").strip() or None
                date_iso = tx.date.date().isoformat()
                outcome.rows.append(
                    RawRow(
                        date=date_iso,
                        description=payee,
                        amount=amount,
                        currency=currency,
                        category_hint=None,
                        notes=memo,
                        raw={
                            "fitid": getattr(tx, "id", None),
                            "type": getattr(tx, "type", None),
                        },
                    )
                )
            except (ValueError, AttributeError, TypeError) as exc:
                outcome.errors.append(ParseError(row_index=i, message=str(exc)))

    _LOGGER.debug(
        "OFX parse of %s: %d rows, %d errors",
        path.name,
        len(outcome.rows),
        len(outcome.errors),
    )
    return outcome


async def parse(path: pathlib.Path, mapping: object = None) -> ParseOutcome:
    """OFX schema is fixed — ``mapping`` is accepted for surface symmetry
    with the CSV/XLSX parsers but ignored."""
    del mapping  # intentional
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _parse_sync, path)
