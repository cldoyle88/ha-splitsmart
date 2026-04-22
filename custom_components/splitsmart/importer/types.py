"""Shared types for the import pipeline.

The importer is organised so parsers return a uniform ``RawRow`` shape and
mappings describe how to translate arbitrary CSV/XLSX column layouts into
that shape. OFX and QIF parsers bypass the mapping layer since their
schemas are fixed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict


class RawRow(TypedDict, total=False):
    """One parsed statement row, pre-dedup, pre-staging.

    `total=False` because different parsers populate different subsets; the
    importer facade fills defaults before a row is accepted.
    """

    date: str  # ISO-8601 YYYY-MM-DD
    description: str
    amount: float  # positive = expense (user paid); signage normalised
    currency: str  # ISO-4217 three-letter code
    category_hint: str | None
    notes: str | None
    raw: dict[str, Any]  # original row, for debugging and later re-parse


AmountSign = Literal["expense_positive", "expense_negative"]


class Mapping(TypedDict, total=False):
    """Column-to-role mapping for CSV/XLSX parsers.

    Keys here are the column names (headers) from the source file. `amount`
    and (`debit`, `credit`) are mutually exclusive: use `amount` for a
    single signed column, or the debit/credit pair for split columns.
    """

    date: str
    description: str
    amount: str | None
    debit: str | None
    credit: str | None
    currency: str | None  # column name; None => use currency_default
    currency_default: str
    amount_sign: AmountSign
    date_format: str  # strptime pattern, or "auto" for the short try-list
    notes_append: list[str]
    category_hint: str | None


class FileInspection(TypedDict):
    """Payload returned by the upload endpoint and by splitsmart/inspect_upload."""

    preset: str | None
    preset_confidence: Literal["high", "low"] | None
    headers: list[str]
    sample_rows: list[list[str]]
    file_origin_hash: str
    saved_mapping: Mapping | None


@dataclass(frozen=True)
class ParseError:
    """A single row-level parse failure. Aggregated onto ParseOutcome."""

    row_index: int  # 1-based, matches what a spreadsheet user sees
    message: str


@dataclass
class ParseOutcome:
    """Result of parsing a file: the good rows, plus per-row errors.

    `row_count_raw` includes errored rows so callers can surface
    "imported N of M rows" honestly.
    """

    rows: list[RawRow] = field(default_factory=list)
    errors: list[ParseError] = field(default_factory=list)
    row_count_raw: int = 0


class ImporterError(Exception):
    """Structured importer error that service handlers translate into
    ServiceValidationError with a stable error `code`.

    `inspection` is attached when the error originates in the mapping
    cascade (e.g. no preset matched and no saved mapping was found) so the
    caller can render the column-picker UI without a second round trip.
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        inspection: FileInspection | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.inspection = inspection
