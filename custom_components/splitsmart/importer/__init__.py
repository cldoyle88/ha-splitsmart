"""Importer facade — file-format dispatch + mapping-resolution cascade.

Callers outside the importer package (service handlers, the upload
endpoint) touch these two entry points:

- ``inspect_file(path, storage)`` returns a ``FileInspection`` with the
  detected preset, header row, sample rows, stable origin hash, and —
  when a storage handle is supplied — the user's previously-saved
  mapping for this origin hash (if any).

- ``parse_file(path, user_mapping=None, storage=None)`` runs the full
  parse. CSV / XLSX need a mapping; the cascade is explicit arg >
  preset > saved-by-hash. If nothing resolves, an ``ImporterError``
  with code ``mapping_required`` is raised, carrying the inspection
  so callers can surface a mapping UI without a second round trip.
  OFX / QIF ignore the mapping argument — their schemas are fixed.
"""

from __future__ import annotations

import logging
import pathlib

from ..storage import SplitsmartStorage
from . import csv_parser, ofx_parser, qif_parser, xlsx_parser
from .mapping import load_saved_mappings
from .presets import detect as detect_preset
from .types import FileInspection, ImporterError, Mapping, ParseOutcome

_LOGGER = logging.getLogger(__name__)

# Extension → parser module. TSV and CSV share the parser; the stdlib
# csv.DictReader sniffs the dialect so the tab-delimited case is free.
_PARSERS = {
    "csv": csv_parser,
    "tsv": csv_parser,
    "xlsx": xlsx_parser,
    "ofx": ofx_parser,
    "qif": qif_parser,
}

# Formats whose schema is user-defined (CSV / XLSX). OFX / QIF have
# fixed schemas and skip the mapping cascade entirely.
_MAPPING_REQUIRED: frozenset[str] = frozenset({"csv", "tsv", "xlsx"})


def _parser_for(path: pathlib.Path) -> tuple[object, str]:
    ext = path.suffix.lstrip(".").lower()
    parser = _PARSERS.get(ext)
    if parser is None:
        raise ImporterError(
            "unsupported_format",
            f"No parser for .{ext}. Supported: {', '.join(sorted(_PARSERS))}.",
        )
    return parser, ext


async def inspect_file(
    path: pathlib.Path,
    storage: SplitsmartStorage | None = None,
) -> FileInspection:
    """Inspect a file for preset + sample + origin hash.

    When ``storage`` is supplied, the returned inspection has
    ``saved_mapping`` populated from ``mappings.jsonl`` if one was
    previously committed under the same origin hash.
    """
    parser, _ = _parser_for(path)
    inspection: FileInspection = await parser.inspect(path)  # type: ignore[attr-defined]
    if storage is not None:
        saved = await load_saved_mappings(storage)
        inspection["saved_mapping"] = saved.get(inspection["file_origin_hash"])
    return inspection


async def parse_file(
    path: pathlib.Path,
    *,
    user_mapping: Mapping | None = None,
    storage: SplitsmartStorage | None = None,
) -> ParseOutcome:
    """Parse the whole file, resolving the effective mapping via cascade.

    Order of resolution for CSV / XLSX:
      1. ``user_mapping`` if supplied (wins everything).
      2. Preset whose detector matches the header row.
      3. Saved mapping keyed on the file origin hash (requires ``storage``).

    OFX / QIF skip the cascade and parse directly.

    Raises :class:`ImporterError` with code ``"mapping_required"`` when
    nothing matches, attaching the inspection so the caller can render
    a column-picker without a second round trip.
    """
    parser, ext = _parser_for(path)

    if ext not in _MAPPING_REQUIRED:
        return await parser.parse(path, None)  # type: ignore[attr-defined]

    if user_mapping is not None:
        _LOGGER.debug("parse_file: using explicit mapping for %s", path.name)
        return await parser.parse(path, user_mapping)  # type: ignore[attr-defined]

    inspection = await parser.inspect(path)  # type: ignore[attr-defined]
    preset = detect_preset(inspection["headers"])
    if preset is not None:
        _LOGGER.debug("parse_file: preset %s matched %s", preset.name, path.name)
        return await parser.parse(path, preset.mapping)  # type: ignore[attr-defined]

    if storage is not None:
        saved = await load_saved_mappings(storage)
        saved_mapping = saved.get(inspection["file_origin_hash"])
        if saved_mapping is not None:
            _LOGGER.debug("parse_file: using saved mapping for %s", path.name)
            inspection["saved_mapping"] = saved_mapping
            return await parser.parse(path, saved_mapping)  # type: ignore[attr-defined]

    raise ImporterError(
        "mapping_required",
        f"No preset matched {path.name} and no saved mapping exists for this "
        "file shape. Supply an explicit mapping via splitsmart.import_file or "
        "save one via the websocket command splitsmart/save_mapping first.",
        inspection=inspection,
    )
