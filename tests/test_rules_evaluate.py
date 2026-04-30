"""Tests for rules.py — evaluate function."""

from __future__ import annotations

from custom_components.splitsmart.rules import load_rules

NAMED_SPLITS: dict = {
    "50_50": {
        "method": "equal",
        "shares": [{"user_id": "u1", "value": 50}, {"user_id": "u2", "value": 50}],
    }
}

_RULES_YAML = """
rules:
  - id: r_netflix
    match: /netflix|spotify/i
    action: always_split
    category: Subscriptions
    split:
      method: equal
      preset: "50_50"
    priority: 10

  - id: r_tfl
    match: /tfl|oyster/i
    action: always_ignore
    priority: 20

  - id: r_big_purchase
    match: /amazon/i
    action: always_ignore
    amount: "> 30"
    priority: 30

  - id: r_small_purchase
    match: /amazon/i
    action: review_each_time
    category: Shopping
    amount: "< 30"
    priority: 40

  - id: r_midrange
    match: /tescos?/i
    action: always_ignore
    amount: "10..50"
    priority: 50

  - id: r_gbp_only
    match: /local shop/i
    action: always_ignore
    currency_match: GBP
    priority: 60

  - id: r_deliveroo
    match: /deliveroo/i
    action: review_each_time
    category: Eating out
    priority: 70
"""


def _load():
    rules, errors = load_rules(_RULES_YAML, named_splits=NAMED_SPLITS)
    assert errors == []
    return rules


# ------------------------------------------------------------------ basic matching


def test_description_match_case_insensitive():
    rules = _load()
    from custom_components.splitsmart.rules import evaluate

    row = {"description": "NETFLIX MONTHLY", "amount": "9.99", "currency": "GBP"}
    match = evaluate(row, rules)
    assert match is not None
    assert match.rule.id == "r_netflix"


def test_no_match_returns_none():
    from custom_components.splitsmart.rules import evaluate

    rules = _load()
    row = {"description": "UNRELATED VENDOR", "amount": "10.00", "currency": "GBP"}
    assert evaluate(row, rules) is None


def test_first_rule_by_priority_wins():
    from custom_components.splitsmart.rules import evaluate

    rules = _load()
    # "netflix" and "spotify" both match r_netflix (priority 10) before r_tfl (priority 20)
    row = {"description": "SPOTIFY PREMIUM", "amount": "9.99", "currency": "GBP"}
    match = evaluate(row, rules)
    assert match is not None
    assert match.rule.id == "r_netflix"


def test_lower_priority_wins_over_higher():
    """r_netflix has priority 10; a different rule with priority 5 would win."""
    from custom_components.splitsmart.rules import evaluate, load_rules

    yaml_text = """
rules:
  - id: r_high_priority
    match: /netflix/i
    action: always_ignore
    priority: 5
  - id: r_low_priority
    match: /netflix/i
    action: always_ignore
    priority: 100
"""
    rules, _ = load_rules(yaml_text, named_splits={})
    row = {"description": "NETFLIX", "amount": "9.99", "currency": "GBP"}
    match = evaluate(row, rules)
    assert match is not None
    assert match.rule.id == "r_high_priority"


# ------------------------------------------------------------------ amount filter


def test_amount_gt_matches_above_threshold():
    from custom_components.splitsmart.rules import evaluate

    rules = _load()
    row = {"description": "AMAZON ORDER", "amount": "40.00", "currency": "GBP"}
    match = evaluate(row, rules)
    assert match is not None
    assert match.rule.id == "r_big_purchase"


def test_amount_gt_no_match_below_threshold():
    from custom_components.splitsmart.rules import evaluate

    rules = _load()
    row = {"description": "AMAZON ORDER", "amount": "20.00", "currency": "GBP"}
    match = evaluate(row, rules)
    # Falls to r_small_purchase (< 30, matches 20)
    assert match is not None
    assert match.rule.id == "r_small_purchase"


def test_amount_gt_exclusive_boundary():
    from custom_components.splitsmart.rules import evaluate

    rules = _load()
    # Exactly 30 — r_big_purchase uses "> 30" (exclusive), should NOT match.
    # r_small_purchase uses "< 30" (exclusive), also should NOT match at exactly 30.
    # So no amount-filtered rule matches; evaluate falls through to r_deliveroo etc.
    # Neither tesco nor deliveroo match "amazon", so result is None.
    row = {"description": "AMAZON ORDER", "amount": "30.00", "currency": "GBP"}
    match = evaluate(row, rules)
    assert match is None


def test_amount_range_matches_within():
    from custom_components.splitsmart.rules import evaluate

    rules = _load()
    row = {"description": "TESCO EXPRESS", "amount": "30.00", "currency": "GBP"}
    match = evaluate(row, rules)
    assert match is not None
    assert match.rule.id == "r_midrange"


def test_amount_range_no_match_above():
    from custom_components.splitsmart.rules import evaluate

    rules = _load()
    row = {"description": "TESCOS LARGE", "amount": "55.00", "currency": "GBP"}
    match = evaluate(row, rules)
    assert match is None


def test_amount_range_inclusive_boundaries():
    from custom_components.splitsmart.rules import evaluate

    rules = _load()
    # Exactly 10 (lower bound) and exactly 50 (upper bound) should match.
    row_lo = {"description": "TESCO", "amount": "10.00", "currency": "GBP"}
    row_hi = {"description": "TESCO", "amount": "50.00", "currency": "GBP"}
    assert evaluate(row_lo, rules) is not None
    assert evaluate(row_hi, rules) is not None


# ------------------------------------------------------------------ currency filter


def test_currency_match_gbp_row_matches():
    from custom_components.splitsmart.rules import evaluate

    rules = _load()
    row = {"description": "LOCAL SHOP", "amount": "5.00", "currency": "GBP"}
    match = evaluate(row, rules)
    assert match is not None
    assert match.rule.id == "r_gbp_only"


def test_currency_match_eur_row_no_match():
    from custom_components.splitsmart.rules import evaluate

    rules = _load()
    row = {"description": "LOCAL SHOP", "amount": "5.00", "currency": "EUR"}
    match = evaluate(row, rules)
    assert match is None


# ------------------------------------------------------------------ description normalisation


def test_partial_description_match():
    from custom_components.splitsmart.rules import evaluate

    rules = _load()
    row = {"description": "Waitrose Islington N1 — NETFLIX", "amount": "9.99", "currency": "GBP"}
    match = evaluate(row, rules)
    assert match is not None
    assert match.rule.id == "r_netflix"


def test_empty_rules_returns_none():
    from custom_components.splitsmart.rules import evaluate

    row = {"description": "NETFLIX", "amount": "9.99", "currency": "GBP"}
    assert evaluate(row, []) is None
