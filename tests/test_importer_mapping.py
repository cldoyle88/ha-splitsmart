"""Tests for importer.mapping — file_origin_hash, persistence, apply_mapping."""

from __future__ import annotations

import pathlib

import pytest

from custom_components.splitsmart.importer.mapping import (
    apply_mapping,
    file_origin_hash,
    load_saved_mappings,
    save_mapping,
)
from custom_components.splitsmart.importer.presets import (
    MONZO_MAPPING,
    REVOLUT_MAPPING,
    SPLITWISE_MAPPING,
    STARLING_MAPPING,
)
from custom_components.splitsmart.importer.types import Mapping
from custom_components.splitsmart.storage import SplitsmartStorage

# ------------------------------------------------------ file_origin_hash


def test_file_origin_hash_is_stable_across_calls() -> None:
    headers = ["Date", "Name", "Amount"]
    a = file_origin_hash(headers=headers, extension="csv", first_row_column_count=3)
    b = file_origin_hash(headers=headers, extension="csv", first_row_column_count=3)
    assert a == b


def test_file_origin_hash_ignores_header_case_and_whitespace() -> None:
    a = file_origin_hash(
        headers=["Date", "Name", "Amount"], extension="csv", first_row_column_count=3
    )
    b = file_origin_hash(
        headers=["  date  ", "NAME", "amount"], extension="csv", first_row_column_count=3
    )
    assert a == b


def test_file_origin_hash_differs_across_banks() -> None:
    monzo = file_origin_hash(
        headers=["Date", "Name", "Amount", "Emoji"],
        extension="csv",
        first_row_column_count=4,
    )
    starling = file_origin_hash(
        headers=["Date", "Counter Party", "Amount (GBP)"],
        extension="csv",
        first_row_column_count=3,
    )
    assert monzo != starling


def test_file_origin_hash_differs_across_extensions() -> None:
    csv_hash = file_origin_hash(headers=["Date", "Name"], extension="csv", first_row_column_count=2)
    xlsx_hash = file_origin_hash(
        headers=["Date", "Name"], extension="xlsx", first_row_column_count=2
    )
    assert csv_hash != xlsx_hash


def test_file_origin_hash_has_expected_prefix() -> None:
    h = file_origin_hash(headers=["Date"], extension="csv", first_row_column_count=1)
    assert h.startswith("sha1:")


# ------------------------------------------------------ persistence


@pytest.mark.asyncio
async def test_save_and_load_roundtrip(tmp_path: pathlib.Path) -> None:
    storage = SplitsmartStorage(tmp_path / "splitsmart")
    await storage.ensure_layout()

    await save_mapping(storage, "sha1:abc", MONZO_MAPPING)
    loaded = await load_saved_mappings(storage)
    assert loaded == {"sha1:abc": MONZO_MAPPING}


@pytest.mark.asyncio
async def test_load_returns_empty_when_file_missing(tmp_path: pathlib.Path) -> None:
    storage = SplitsmartStorage(tmp_path / "splitsmart")
    await storage.ensure_layout()

    loaded = await load_saved_mappings(storage)
    assert loaded == {}


@pytest.mark.asyncio
async def test_newest_mapping_per_hash_wins(tmp_path: pathlib.Path) -> None:
    storage = SplitsmartStorage(tmp_path / "splitsmart")
    await storage.ensure_layout()

    # First save: Monzo. Then user edits and re-saves Starling under the same hash.
    # Second save should supersede.
    await save_mapping(storage, "sha1:abc", MONZO_MAPPING)
    await save_mapping(storage, "sha1:abc", STARLING_MAPPING)

    loaded = await load_saved_mappings(storage)
    assert loaded["sha1:abc"] == STARLING_MAPPING


@pytest.mark.asyncio
async def test_multiple_hashes_coexist(tmp_path: pathlib.Path) -> None:
    storage = SplitsmartStorage(tmp_path / "splitsmart")
    await storage.ensure_layout()

    await save_mapping(storage, "sha1:monzo", MONZO_MAPPING)
    await save_mapping(storage, "sha1:splitwise", SPLITWISE_MAPPING)

    loaded = await load_saved_mappings(storage)
    assert loaded["sha1:monzo"] == MONZO_MAPPING
    assert loaded["sha1:splitwise"] == SPLITWISE_MAPPING


# ------------------------------------------------------ apply_mapping


def test_apply_monzo_expense_row() -> None:
    row = {
        "Date": "15/04/2026",
        "Name": "Waitrose",
        "Amount": "-47.83",
        "Currency": "GBP",
        "Category": "Groceries",
        "Notes and #tags": "Weekly shop",
        "Description": "WAITROSE ISLINGTON",
    }
    parsed = apply_mapping(row, MONZO_MAPPING)
    assert parsed["date"] == "2026-04-15"
    assert parsed["description"] == "Waitrose"
    assert parsed["amount"] == 47.83
    assert parsed["currency"] == "GBP"
    assert parsed["category_hint"] == "Groceries"
    assert parsed["notes"] == "Weekly shop · WAITROSE ISLINGTON"


def test_apply_splitwise_uses_positive_cost() -> None:
    # Splitwise exports Cost as a positive number with amount_sign=expense_positive.
    row = {
        "Date": "2026-04-15",
        "Description": "Dinner",
        "Category": "Eating out",
        "Cost": "82.40",
        "Currency": "GBP",
    }
    parsed = apply_mapping(row, SPLITWISE_MAPPING)
    assert parsed["amount"] == 82.40


def test_apply_revolut_foreign_currency_row() -> None:
    row = {
        "Type": "CARD_PAYMENT",
        "Product": "Current",
        "Started Date": "2026-04-15",
        "Completed Date": "2026-04-16",
        "Description": "Cafe Paris",
        "Amount": "-4.50",
        "Fee": "0.00",
        "Currency": "EUR",
        "State": "COMPLETED",
        "Balance": "100.00",
    }
    parsed = apply_mapping(row, REVOLUT_MAPPING)
    assert parsed["currency"] == "EUR"
    assert parsed["amount"] == 4.50


def test_apply_handles_comma_thousands_separator() -> None:
    row = {
        "Date": "2026-04-15",
        "Name": "Big purchase",
        "Amount": "-1,234.56",
        "Currency": "GBP",
        "Notes and #tags": "",
        "Description": "",
        "Category": "Other",
    }
    parsed = apply_mapping(row, MONZO_MAPPING)
    assert parsed["amount"] == 1234.56


def test_apply_handles_parens_negative() -> None:
    row = {
        "Date": "2026-04-15",
        "Name": "Refund",
        "Amount": "(47.83)",  # accountant-style negative
        "Currency": "GBP",
        "Notes and #tags": "",
        "Description": "",
        "Category": "Other",
    }
    parsed = apply_mapping(row, MONZO_MAPPING)
    # (47.83) is -47.83 on the file, Monzo expense_negative flips to +47.83.
    assert parsed["amount"] == 47.83


def test_apply_debit_credit_mapping() -> None:
    mapping: Mapping = {
        "date": "Date",
        "description": "Payee",
        "amount": None,
        "debit": "Debit",
        "credit": "Credit",
        "currency": None,
        "currency_default": "GBP",
        "amount_sign": "expense_positive",
        "date_format": "auto",
        "notes_append": [],
        "category_hint": None,
    }
    expense_row = {"Date": "2026-04-15", "Payee": "Tesco", "Debit": "47.83", "Credit": ""}
    parsed = apply_mapping(expense_row, mapping)
    assert parsed["amount"] == 47.83

    credit_row = {"Date": "2026-04-15", "Payee": "Refund", "Debit": "", "Credit": "10.00"}
    parsed = apply_mapping(credit_row, mapping)
    assert parsed["amount"] == -10.00  # income → negative


def test_apply_notes_append_skips_blanks() -> None:
    row = {
        "Date": "2026-04-15",
        "Name": "Waitrose",
        "Amount": "-47.83",
        "Currency": "GBP",
        "Notes and #tags": "",  # empty
        "Description": "Weekly shop",
        "Category": "Groceries",
    }
    parsed = apply_mapping(row, MONZO_MAPPING)
    assert parsed["notes"] == "Weekly shop"


def test_apply_rejects_unparseable_date() -> None:
    row = {
        "Date": "not-a-date",
        "Name": "X",
        "Amount": "-1.00",
        "Currency": "GBP",
        "Notes and #tags": "",
        "Description": "",
        "Category": "",
    }
    with pytest.raises(ValueError):
        apply_mapping(row, MONZO_MAPPING)
