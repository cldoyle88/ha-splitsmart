"""CSV parser — inspection (for the mapping cascade) + full parse.

The parser reads the file into memory (statements are small, capped at
25 MB by the upload endpoint) then iterates with the stdlib ``csv``
module. Encoding detection tries UTF-8 with BOM first and falls back
to cp1252, which is what Excel-on-Windows emits by default — far and
away the most common non-UTF-8 shape we see in real bank exports.
"""

from __future__ import annotations

import csv
import io
import logging
import pathlib

import aiofiles

from .mapping import apply_mapping, file_origin_hash
from .presets import detect as detect_preset
from .types import FileInspection, Mapping, ParseError, ParseOutcome, RawRow

_LOGGER = logging.getLogger(__name__)

_SAMPLE_ROWS = 10


# --------------------------------------------------------- encoding


async def _read_text(path: pathlib.Path) -> str:
    """Read the file as text, sniffing UTF-8-with-BOM / cp1252."""
    async with aiofiles.open(path, mode="rb") as fh:
        blob = await fh.read()
    try:
        return blob.decode("utf-8-sig")
    except UnicodeDecodeError:
        _LOGGER.debug("CSV at %s is not UTF-8; falling back to cp1252", path)
        return blob.decode("cp1252", errors="replace")


# --------------------------------------------------------- inspect


async def inspect(path: pathlib.Path) -> FileInspection:
    """Return the FileInspection payload the mapping cascade needs.

    Populates the preset match (if any), the header row, up to 10
    sample rows, and the stable file-origin hash. ``saved_mapping`` is
    left ``None``; the facade layer fills it from ``mappings.jsonl``.
    """
    text = await _read_text(path)
    reader = csv.reader(io.StringIO(text))
    try:
        headers = next(reader)
    except StopIteration:
        # Empty file — return an inspection that forces manual mapping.
        return FileInspection(
            preset=None,
            preset_confidence=None,
            headers=[],
            sample_rows=[],
            file_origin_hash=file_origin_hash(
                headers=[], extension=path.suffix.lstrip("."), first_row_column_count=0
            ),
            saved_mapping=None,
        )

    sample_rows: list[list[str]] = []
    for i, row in enumerate(reader):
        if i >= _SAMPLE_ROWS:
            break
        sample_rows.append(row)

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
    """Parse the full file with the supplied mapping.

    Per-row errors are collected into ``ParseOutcome.errors`` rather
    than raising, so a single malformed line does not abort the whole
    import. Row indices are 1-based and exclude the header, matching
    what a spreadsheet user would see.
    """
    text = await _read_text(path)
    reader = csv.DictReader(io.StringIO(text))

    outcome = ParseOutcome()
    for row_index, row in enumerate(reader, start=1):
        outcome.row_count_raw += 1
        # DictReader yields OrderedDict; normalise to plain dict of str:str.
        clean: dict[str, str] = {k: (v or "") for k, v in row.items() if k is not None}
        try:
            parsed: RawRow = apply_mapping(clean, mapping)
        except (ValueError, KeyError) as exc:
            outcome.errors.append(ParseError(row_index=row_index, message=str(exc)))
            continue
        outcome.rows.append(parsed)

    _LOGGER.debug(
        "CSV parse of %s: %d rows, %d errors",
        path.name,
        len(outcome.rows),
        len(outcome.errors),
    )
    return outcome
