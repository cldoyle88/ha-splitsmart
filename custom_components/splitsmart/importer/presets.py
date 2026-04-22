"""Preset column-mappings for known statement exports.

Each preset carries a detector (run against the header row of an
incoming file) and a ``Mapping`` that tells the CSV / XLSX parsers
how to translate that file's columns into ``RawRow`` fields.

Presets we ship: Monzo, Starling, Revolut, Splitwise. Further presets
land as PRs appending to ``PRESETS``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from .types import Mapping


def _norm_set(headers: list[str]) -> set[str]:
    return {h.strip().lower() for h in headers if h is not None}


# --------------------------------------------------------- Monzo
# Monzo's CSV export spans several generations; the common subset
# across "Classic" / "Plus" / "Premium" exports is Date / Name / Amount
# plus an Emoji column that is very specific to Monzo. Emoji is required
# in the detect set so a generic "Date, Name, Amount" CSV does not get
# the Monzo mapping by accident.
def _detect_monzo(headers: list[str]) -> bool:
    cols = _norm_set(headers)
    return {"date", "name", "amount", "emoji"}.issubset(cols)


MONZO_MAPPING: Mapping = {
    "date": "Date",
    "description": "Name",
    "amount": "Amount",
    "debit": None,
    "credit": None,
    "currency": "Currency",
    "currency_default": "GBP",
    "amount_sign": "expense_negative",
    "date_format": "auto",
    "notes_append": ["Notes and #tags", "Description"],
    "category_hint": "Category",
}


# --------------------------------------------------------- Starling
# Starling's "Amount (GBP)" column name bakes the account currency into
# the header — the preset ships for GBP accounts. Non-GBP Starling
# accounts fall to manual mapping. "Counter Party" is very Starling-specific.
def _detect_starling(headers: list[str]) -> bool:
    cols = _norm_set(headers)
    return {"date", "counter party", "amount (gbp)"}.issubset(cols)


STARLING_MAPPING: Mapping = {
    "date": "Date",
    "description": "Counter Party",
    "amount": "Amount (GBP)",
    "debit": None,
    "credit": None,
    "currency": None,  # no currency column; assume GBP
    "currency_default": "GBP",
    "amount_sign": "expense_negative",
    "date_format": "auto",
    "notes_append": ["Reference", "Notes"],
    "category_hint": "Spending Category",
}


# --------------------------------------------------------- Revolut
# Revolut exports "Started Date" and "Completed Date" — use the started
# date because that's when the user made the transaction. Revolut is the
# preset most likely to carry foreign-currency rows, so Currency is wired.
def _detect_revolut(headers: list[str]) -> bool:
    cols = _norm_set(headers)
    return {"started date", "description", "amount", "currency", "product"}.issubset(cols)


REVOLUT_MAPPING: Mapping = {
    "date": "Started Date",
    "description": "Description",
    "amount": "Amount",
    "debit": None,
    "credit": None,
    "currency": "Currency",
    "currency_default": "GBP",
    "amount_sign": "expense_negative",
    "date_format": "auto",
    "notes_append": ["Type", "Product", "State"],
    "category_hint": None,
}


# --------------------------------------------------------- Splitwise
# Splitwise exports expenses with Cost (always positive) and an explicit
# Category column. Per-user share columns exist in real exports but we
# ignore them: the whole point of Splitsmart is to re-decide the split.
def _detect_splitwise(headers: list[str]) -> bool:
    cols = _norm_set(headers)
    return {"date", "description", "category", "cost", "currency"}.issubset(cols)


SPLITWISE_MAPPING: Mapping = {
    "date": "Date",
    "description": "Description",
    "amount": "Cost",
    "debit": None,
    "credit": None,
    "currency": "Currency",
    "currency_default": "GBP",
    "amount_sign": "expense_positive",
    "date_format": "auto",
    "notes_append": [],
    "category_hint": "Category",
}


# --------------------------------------------------------- registry

Confidence = Literal["high", "low"]


@dataclass(frozen=True)
class Preset:
    name: str
    detect: Callable[[list[str]], bool]
    mapping: Mapping
    confidence: Confidence


PRESETS: list[Preset] = [
    Preset("Monzo", _detect_monzo, MONZO_MAPPING, "high"),
    Preset("Starling", _detect_starling, STARLING_MAPPING, "high"),
    Preset("Revolut", _detect_revolut, REVOLUT_MAPPING, "high"),
    Preset("Splitwise", _detect_splitwise, SPLITWISE_MAPPING, "high"),
]


def detect(headers: list[str]) -> Preset | None:
    """Return the first preset whose detector matches, or None."""
    for preset in PRESETS:
        if preset.detect(headers):
            return preset
    return None
