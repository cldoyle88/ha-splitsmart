"""XLSX parser — same surface as csv_parser, different reader.

openpyxl is synchronous, so file IO runs in the default executor to
keep the HA event loop responsive. Cell values arrive as Python types
(datetime, float, int); we stringify before handing off to
``apply_mapping`` so the column-role logic stays identical to CSV.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import pathlib
from typing import Any

import openpyxl

from .mapping import apply_mapping, file_origin_hash
from .presets import detect as detect_preset
from .types import FileInspection, Mapping, ParseError, ParseOutcome, RawRow

_LOGGER = logging.getLogger(__name__)

_SAMPLE_ROWS = 10


def _stringify(cell: Any) -> str:
    """openpyxl cell → str. Preserves dates as ISO so apply_mapping's
    date parser picks them up on the first try."""
    if cell is None:
        return ""
    if isinstance(cell, dt.datetime):
        return cell.date().isoformat() if cell.time() == dt.time(0, 0) else cell.isoformat()
    if isinstance(cell, dt.date):
        return cell.isoformat()
    return str(cell)


def _read_sync(path: pathlib.Path) -> tuple[list[str], list[list[str]]]:
    """Read the headers + *all* rows. Runs in an executor."""
    wb = openpyxl.load_workbook(filename=str(path), read_only=True, data_only=True)
    try:
        ws = wb.active
        if ws is None:
            return [], []
        iterator = ws.iter_rows(values_only=True)
        try:
            header_row = next(iterator)
        except StopIteration:
            return [], []
        headers = [_stringify(c) for c in header_row]
        body = [[_stringify(c) for c in row] for row in iterator]
        return headers, body
    finally:
        wb.close()


async def _read(path: pathlib.Path) -> tuple[list[str], list[list[str]]]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _read_sync, path)


# --------------------------------------------------------- inspect


async def inspect(path: pathlib.Path) -> FileInspection:
    headers, body = await _read(path)
    sample_rows = body[:_SAMPLE_ROWS]
    preset = detect_preset(headers)
    origin_hash = file_origin_hash(
        headers=headers,
        extension=path.suffix.lstrip("."),
        first_row_column_count=len(headers),
    )
    return FileInspection(
        preset=preset.name if preset else None,
        preset_confidence=preset.confidence if preset else None,
        headers=headers,
        sample_rows=sample_rows,
        file_origin_hash=origin_hash,
        saved_mapping=None,
    )


# --------------------------------------------------------- parse


async def parse(path: pathlib.Path, mapping: Mapping) -> ParseOutcome:
    headers, body = await _read(path)
    outcome = ParseOutcome()
    for row_index, cells in enumerate(body, start=1):
        outcome.row_count_raw += 1
        # Pad short rows so a missing trailing cell doesn't throw off the zip.
        padded = list(cells) + [""] * (len(headers) - len(cells))
        row_dict: dict[str, str] = dict(zip(headers, padded, strict=False))
        try:
            parsed: RawRow = apply_mapping(row_dict, mapping)
        except (ValueError, KeyError) as exc:
            outcome.errors.append(ParseError(row_index=row_index, message=str(exc)))
            continue
        outcome.rows.append(parsed)

    _LOGGER.debug(
        "XLSX parse of %s: %d rows, %d errors",
        path.name,
        len(outcome.rows),
        len(outcome.errors),
    )
    return outcome
