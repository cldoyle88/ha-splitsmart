"""Tests for rules.py — build_match_payload function."""

from __future__ import annotations

from decimal import Decimal

import pytest

from custom_components.splitsmart.rules import (
    RuleParseError,
    build_match_payload,
    evaluate,
    load_rules,
)

NAMED_SPLITS: dict = {
    "50_50": {
        "method": "equal",
        "shares": [{"user_id": "u1", "value": 50}, {"user_id": "u2", "value": 50}],
    },
    "70_30": {
        "method": "shares",
        "shares": [{"user_id": "u1", "value": 70}, {"user_id": "u2", "value": 30}],
    },
}

_SPLIT_YAML = """
rules:
  - id: r_netflix
    match: /netflix/i
    action: always_split
    category: Subscriptions
    split:
      method: equal
      preset: "50_50"

  - id: r_tfl
    match: /tfl/i
    action: always_ignore

  - id: r_deliveroo
    match: /deliveroo/i
    action: review_each_time
    category: Eating out

  - id: r_inline
    match: /waitrose/i
    action: always_split
    category: Groceries
    split:
      method: shares
      shares:
        - user_id: u1
          value: 70
        - user_id: u2
          value: 30
"""


def _load():
    rules, errors = load_rules(_SPLIT_YAML, named_splits=NAMED_SPLITS)
    assert errors == []
    return rules


# ------------------------------------------------------------------ always_split


def test_always_split_preset_resolves_to_categories_block():
    rules = _load()
    row = {"description": "NETFLIX SUBSCRIPTION", "amount": "9.99", "currency": "GBP"}
    match = evaluate(row, rules)
    assert match is not None

    payload = build_match_payload(
        match,
        home_currency="GBP",
        expense_amount=Decimal("9.99"),
        named_splits=NAMED_SPLITS,
    )
    assert payload is not None
    cats = payload["categories"]
    assert len(cats) == 1
    assert cats[0]["name"] == "Subscriptions"
    assert cats[0]["home_amount"] == pytest.approx(9.99)
    assert cats[0]["split"]["method"] == "equal"
    assert cats[0]["split"]["shares"][0]["user_id"] == "u1"


def test_always_split_home_amount_matches_expense_amount():
    rules = _load()
    match = evaluate({"description": "NETFLIX", "amount": "15.50", "currency": "GBP"}, rules)
    assert match is not None
    payload = build_match_payload(
        match,
        home_currency="GBP",
        expense_amount=Decimal("15.50"),
        named_splits=NAMED_SPLITS,
    )
    assert payload is not None
    assert payload["categories"][0]["home_amount"] == pytest.approx(15.50)


def test_always_split_inline_shares_no_preset():
    rules = _load()
    row = {"description": "WAITROSE ISLINGTON", "amount": "47.83", "currency": "GBP"}
    match = evaluate(row, rules)
    assert match is not None
    assert match.rule.id == "r_inline"

    payload = build_match_payload(
        match,
        home_currency="GBP",
        expense_amount=Decimal("47.83"),
        named_splits=NAMED_SPLITS,
    )
    assert payload is not None
    cats = payload["categories"]
    assert cats[0]["name"] == "Groceries"
    assert cats[0]["split"]["method"] == "shares"
    assert cats[0]["split"]["shares"][0]["value"] == 70


# ------------------------------------------------------------------ always_ignore


def test_always_ignore_returns_none():
    rules = _load()
    row = {"description": "TFL TRAVEL", "amount": "5.50", "currency": "GBP"}
    match = evaluate(row, rules)
    assert match is not None
    assert match.rule.action == "always_ignore"

    payload = build_match_payload(
        match,
        home_currency="GBP",
        expense_amount=Decimal("5.50"),
        named_splits=NAMED_SPLITS,
    )
    assert payload is None


# ------------------------------------------------------------------ review_each_time


def test_review_each_time_returns_none():
    rules = _load()
    row = {"description": "DELIVEROO ORDER", "amount": "22.00", "currency": "GBP"}
    match = evaluate(row, rules)
    assert match is not None
    assert match.rule.action == "review_each_time"

    payload = build_match_payload(
        match,
        home_currency="GBP",
        expense_amount=Decimal("22.00"),
        named_splits=NAMED_SPLITS,
    )
    assert payload is None


# ------------------------------------------------------------------ unknown preset


def test_unknown_preset_raises():
    rules, errors = load_rules(
        """
rules:
  - id: r_split
    match: /test/i
    action: always_split
    category: Groceries
    split:
      method: equal
      preset: "50_50"
""",
        named_splits=NAMED_SPLITS,
    )
    assert errors == []

    match = evaluate({"description": "TEST", "amount": "10.00", "currency": "GBP"}, rules)
    assert match is not None

    # Pass empty named_splits to simulate a missing preset at build time.
    with pytest.raises(RuleParseError, match="preset"):
        build_match_payload(
            match,
            home_currency="GBP",
            expense_amount=Decimal("10.00"),
            named_splits={},
        )


def test_unknown_preset_raises_when_named_splits_is_none():
    rules, _ = load_rules(
        """
rules:
  - id: r_split
    match: /test/i
    action: always_split
    category: Groceries
    split:
      method: equal
      preset: "50_50"
""",
        named_splits=NAMED_SPLITS,
    )
    match = evaluate({"description": "TEST", "amount": "10.00", "currency": "GBP"}, rules)
    assert match is not None

    with pytest.raises(RuleParseError, match="preset"):
        build_match_payload(
            match,
            home_currency="GBP",
            expense_amount=Decimal("10.00"),
            named_splits=None,
        )
