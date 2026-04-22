"""Tests for the importer facade — dispatch + mapping-resolution cascade."""

from __future__ import annotations

import pathlib

import pytest

from custom_components.splitsmart.importer import (
    inspect_file,
    parse_file,
)
from custom_components.splitsmart.importer.mapping import (
    file_origin_hash,
    save_mapping,
)
from custom_components.splitsmart.importer.presets import MONZO_MAPPING
from custom_components.splitsmart.importer.types import ImporterError, Mapping
from custom_components.splitsmart.storage import SplitsmartStorage

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "imports"


# --------------------------------------------------------- inspect_file


@pytest.mark.asyncio
async def test_inspect_file_dispatches_by_extension() -> None:
    # CSV with a preset match.
    inspection = await inspect_file(FIXTURES / "monzo_classic.csv")
    assert inspection["preset"] == "Monzo"
    # OFX has no headers, no preset — but still returns a valid inspection.
    ofx = await inspect_file(FIXTURES / "sample.ofx")
    assert ofx["preset"] is None
    assert ofx["headers"] == []


@pytest.mark.asyncio
async def test_inspect_file_populates_saved_mapping_when_storage_supplied(
    tmp_path: pathlib.Path,
) -> None:
    storage = SplitsmartStorage(tmp_path / "splitsmart")
    await storage.ensure_layout()

    # Compute the hash the generic-no-preset CSV will produce.
    generic_headers = ["Posted", "Merchant", "Spent", "Note"]
    origin_hash = file_origin_hash(
        headers=generic_headers, extension="csv", first_row_column_count=4
    )
    saved: Mapping = {
        "date": "Posted",
        "description": "Merchant",
        "amount": "Spent",
        "debit": None,
        "credit": None,
        "currency": None,
        "currency_default": "GBP",
        "amount_sign": "expense_positive",
        "date_format": "auto",
        "notes_append": ["Note"],
        "category_hint": None,
    }
    await save_mapping(storage, origin_hash, saved)

    inspection = await inspect_file(FIXTURES / "generic_no_preset.csv", storage=storage)
    assert inspection["saved_mapping"] == saved


@pytest.mark.asyncio
async def test_inspect_file_leaves_saved_mapping_none_without_storage() -> None:
    inspection = await inspect_file(FIXTURES / "monzo_classic.csv")
    assert inspection["saved_mapping"] is None


# --------------------------------------------------------- parse_file cascade


@pytest.mark.asyncio
async def test_parse_file_uses_preset_when_user_mapping_omitted() -> None:
    outcome = await parse_file(FIXTURES / "monzo_classic.csv")
    assert outcome.row_count_raw == 10
    assert len(outcome.errors) == 0
    # Preset's amount_sign=expense_negative flipped the sign: first row positive.
    assert outcome.rows[0]["amount"] == 47.83


@pytest.mark.asyncio
async def test_parse_file_explicit_mapping_wins_over_preset() -> None:
    # Force expense_positive on the Monzo file — amounts stay negative.
    override: Mapping = dict(MONZO_MAPPING)  # type: ignore[assignment]
    override["amount_sign"] = "expense_positive"
    outcome = await parse_file(FIXTURES / "monzo_classic.csv", user_mapping=override)
    assert outcome.rows[0]["amount"] == -47.83


@pytest.mark.asyncio
async def test_parse_file_uses_saved_mapping_when_no_preset(
    tmp_path: pathlib.Path,
) -> None:
    storage = SplitsmartStorage(tmp_path / "splitsmart")
    await storage.ensure_layout()

    origin_hash = file_origin_hash(
        headers=["Posted", "Merchant", "Spent", "Note"],
        extension="csv",
        first_row_column_count=4,
    )
    saved: Mapping = {
        "date": "Posted",
        "description": "Merchant",
        "amount": "Spent",
        "debit": None,
        "credit": None,
        "currency": None,
        "currency_default": "GBP",
        "amount_sign": "expense_positive",
        "date_format": "auto",
        "notes_append": [],
        "category_hint": None,
    }
    await save_mapping(storage, origin_hash, saved)

    outcome = await parse_file(FIXTURES / "generic_no_preset.csv", storage=storage)
    assert outcome.row_count_raw == 5
    assert len(outcome.errors) == 0
    assert outcome.rows[0]["description"] == "Waitrose"


@pytest.mark.asyncio
async def test_parse_file_raises_mapping_required_when_nothing_matches() -> None:
    with pytest.raises(ImporterError) as exc_info:
        await parse_file(FIXTURES / "generic_no_preset.csv")
    assert exc_info.value.code == "mapping_required"
    assert exc_info.value.inspection is not None
    # Inspection payload must be populated so the caller can surface the
    # column-picker without fetching it again.
    assert exc_info.value.inspection["headers"] == ["Posted", "Merchant", "Spent", "Note"]


@pytest.mark.asyncio
async def test_parse_file_ofx_needs_no_mapping() -> None:
    # OFX schema is fixed — no user_mapping, no storage, just parses.
    outcome = await parse_file(FIXTURES / "sample.ofx")
    assert outcome.row_count_raw == 5
    assert len(outcome.errors) == 0


@pytest.mark.asyncio
async def test_parse_file_qif_needs_no_mapping() -> None:
    outcome = await parse_file(FIXTURES / "sample.qif")
    assert outcome.row_count_raw == 10
    assert len(outcome.errors) == 0


@pytest.mark.asyncio
async def test_parse_file_rejects_unsupported_extension(tmp_path: pathlib.Path) -> None:
    bogus = tmp_path / "statement.pdf"
    bogus.write_bytes(b"%PDF-1.4\n")
    with pytest.raises(ImporterError) as exc_info:
        await parse_file(bogus)
    assert exc_info.value.code == "unsupported_format"


@pytest.mark.asyncio
async def test_inspect_file_rejects_unsupported_extension(tmp_path: pathlib.Path) -> None:
    bogus = tmp_path / "statement.pdf"
    bogus.write_bytes(b"%PDF-1.4\n")
    with pytest.raises(ImporterError) as exc_info:
        await inspect_file(bogus)
    assert exc_info.value.code == "unsupported_format"
