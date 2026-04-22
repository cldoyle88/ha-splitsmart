"""Unit tests for importer.presets — pure, no HA event loop."""

from __future__ import annotations

import pytest

from custom_components.splitsmart.importer.presets import PRESETS, detect

# Canonical header rows, as emitted by each bank's exporter.
MONZO_HEADERS = [
    "Transaction ID",
    "Date",
    "Time",
    "Type",
    "Name",
    "Emoji",
    "Category",
    "Amount",
    "Currency",
    "Local amount",
    "Local currency",
    "Notes and #tags",
    "Address",
    "Receipt",
    "Description",
    "Category split",
    "Money Out",
    "Money In",
]

STARLING_HEADERS = [
    "Date",
    "Counter Party",
    "Reference",
    "Type",
    "Amount (GBP)",
    "Balance (GBP)",
    "Spending Category",
    "Notes",
]

REVOLUT_HEADERS = [
    "Type",
    "Product",
    "Started Date",
    "Completed Date",
    "Description",
    "Amount",
    "Fee",
    "Currency",
    "State",
    "Balance",
]

SPLITWISE_HEADERS = [
    "Date",
    "Description",
    "Category",
    "Cost",
    "Currency",
    "User A",
    "User B",
]


@pytest.mark.parametrize(
    ("headers", "expected_name"),
    [
        (MONZO_HEADERS, "Monzo"),
        (STARLING_HEADERS, "Starling"),
        (REVOLUT_HEADERS, "Revolut"),
        (SPLITWISE_HEADERS, "Splitwise"),
    ],
)
def test_detect_matches_each_preset(headers: list[str], expected_name: str) -> None:
    preset = detect(headers)
    assert preset is not None
    assert preset.name == expected_name


def test_detect_returns_none_for_unknown_headers() -> None:
    assert detect(["foo", "bar", "baz"]) is None


def test_detect_is_case_insensitive() -> None:
    # Lowercase variant still matches Monzo.
    lower = [h.lower() for h in MONZO_HEADERS]
    preset = detect(lower)
    assert preset is not None
    assert preset.name == "Monzo"


def test_detect_tolerates_extra_columns() -> None:
    # Monzo may add columns over time; the existing detect set must still match.
    extra = [*MONZO_HEADERS, "New Column 2027"]
    assert detect(extra) is not None


def test_monzo_does_not_match_generic_date_name_amount() -> None:
    # Without the Emoji marker, a generic bank CSV must not masquerade as Monzo.
    generic = ["Date", "Name", "Amount", "Currency"]
    assert detect(generic) is None


def test_every_preset_has_all_required_mapping_keys() -> None:
    # Loose integration check: every shipped preset must define the keys
    # the CSV parser will ask for. Missing keys would surface at import time
    # instead of at module-load time without this.
    for preset in PRESETS:
        m = preset.mapping
        assert "date" in m
        assert "description" in m
        assert m.get("amount") or (m.get("debit") and m.get("credit"))
        assert "currency_default" in m
        assert "amount_sign" in m
