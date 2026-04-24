"""Unit tests for importer.normalise — pure, no HA event loop."""

from __future__ import annotations

import pytest

from custom_components.splitsmart.importer.normalise import (
    dedup_hash,
    normalise_description,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Case + whitespace fold.
        ("WAITROSE ISLINGTON N1", "WAITROSE ISLINGTON N1"),
        ("Waitrose  Islington N1  ", "WAITROSE ISLINGTON N1"),
        # Leading asterisks (some card issuers prepend *).
        ("*NETFLIX.COM", "NETFLIX.COM"),
        ("**NETFLIX", "NETFLIX"),
        ("*  NETFLIX.COM", "NETFLIX.COM"),
        # Trailing dd/mm dates get stripped so daily-merchant charges collapse.
        ("TFL TRAVEL 15/04", "TFL TRAVEL"),
        ("TFL TRAVEL 16/04", "TFL TRAVEL"),
        ("TFL TRAVEL 16-04", "TFL TRAVEL"),
        ("TFL TRAVEL 16/04/26", "TFL TRAVEL"),
        ("TFL TRAVEL 16/04/2026", "TFL TRAVEL"),
        # Trailing ISO dates get stripped.
        ("TESCO METRO 2026-04-15", "TESCO METRO"),
        # Empty / whitespace-only.
        ("", ""),
        ("   ", ""),
        ("*", ""),
    ],
)
def test_normalise_description(raw: str, expected: str) -> None:
    assert normalise_description(raw) == expected


def test_uber_and_uber_eats_are_not_collapsed() -> None:
    # Intentional: no merchant-identity canonicalisation in v1.
    assert normalise_description("UBER") != normalise_description("UBER EATS")


def test_amazon_variants_are_not_collapsed() -> None:
    assert normalise_description("AMAZON") != normalise_description("AMZN MKTP")


def test_isolated_date_like_string_is_preserved() -> None:
    # A bare "15/04" should not be stripped to empty — the regex requires
    # whitespace before the date, so it only fires as a trailing suffix.
    assert normalise_description("15/04") == "15/04"


def test_dedup_hash_is_stable_across_presentation_differences() -> None:
    a = dedup_hash(date="2026-04-15", amount=47.83, currency="GBP", description="Waitrose")
    b = dedup_hash(date="2026-04-15", amount=47.83, currency="GBP", description="  waitrose  ")
    assert a == b


def test_dedup_hash_collapses_trailing_dates() -> None:
    a = dedup_hash(date="2026-04-15", amount=2.80, currency="GBP", description="TFL TRAVEL 15/04")
    b = dedup_hash(date="2026-04-15", amount=2.80, currency="GBP", description="TFL TRAVEL 16/04")
    assert a == b


def test_dedup_hash_separates_different_fields() -> None:
    base = dict(date="2026-04-15", amount=47.83, currency="GBP", description="Waitrose")
    h_base = dedup_hash(**base)
    assert dedup_hash(**{**base, "date": "2026-04-16"}) != h_base
    assert dedup_hash(**{**base, "amount": 47.84}) != h_base
    assert dedup_hash(**{**base, "currency": "EUR"}) != h_base
    assert dedup_hash(**{**base, "description": "Tesco"}) != h_base


def test_dedup_hash_rounds_amount_to_two_dp() -> None:
    # Float drift should not change the hash; 47.830001 rounds to 47.83.
    base = dict(date="2026-04-15", currency="GBP", description="Waitrose")
    assert dedup_hash(**base, amount=47.83) == dedup_hash(**base, amount=47.830001)


def test_dedup_hash_has_expected_prefix() -> None:
    h = dedup_hash(date="2026-04-15", amount=10.00, currency="GBP", description="Test")
    assert h.startswith("sha256:")
    assert len(h) == len("sha256:") + 64  # 32-byte digest in hex
