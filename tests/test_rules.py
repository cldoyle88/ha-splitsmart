"""Tests for rules.py — load_rules validation."""

from __future__ import annotations

from decimal import Decimal

from custom_components.splitsmart.rules import load_rules

NAMED_SPLITS_50_50: dict = {
    "50_50": {
        "method": "equal",
        "shares": [{"user_id": "u1", "value": 50}, {"user_id": "u2", "value": 50}],
    },
}


# ------------------------------------------------------------------ happy path


def test_load_two_rules_sorted_by_priority():
    yaml_text = """
rules:
  - id: r_tfl
    match: /tfl/i
    action: always_ignore
    priority: 100
  - id: r_netflix
    match: /netflix/i
    action: always_split
    category: Subscriptions
    split:
      method: equal
      preset: "50_50"
    priority: 50
"""
    rules, errors = load_rules(yaml_text, named_splits=NAMED_SPLITS_50_50)
    assert errors == []
    assert len(rules) == 2
    # priority 50 sorts first (lower wins)
    assert rules[0].id == "r_netflix"
    assert rules[1].id == "r_tfl"


def test_load_source_order_priority_when_omitted():
    yaml_text = """
rules:
  - id: r_a
    match: /alpha/i
    action: always_ignore
  - id: r_b
    match: /beta/i
    action: always_ignore
"""
    rules, errors = load_rules(yaml_text, named_splits={})
    assert errors == []
    # index 0 → priority 0, index 1 → priority 1000
    assert rules[0].id == "r_a"
    assert rules[1].id == "r_b"
    assert rules[0].priority == 0
    assert rules[1].priority == 1000


def test_load_all_three_actions():
    yaml_text = """
rules:
  - id: r_split
    match: /waitrose/i
    action: always_split
    category: Groceries
    split:
      method: equal
      preset: "50_50"
  - id: r_ignore
    match: /tfl/i
    action: always_ignore
  - id: r_review
    match: /deliveroo/i
    action: review_each_time
    category: Eating out
"""
    rules, errors = load_rules(yaml_text, named_splits=NAMED_SPLITS_50_50)
    assert errors == []
    ids = [r.id for r in rules]
    assert "r_split" in ids
    assert "r_ignore" in ids
    assert "r_review" in ids


def test_load_optional_description_and_currency_match():
    yaml_text = """
rules:
  - id: r_test
    description: Test rule
    match: /test/i
    action: always_ignore
    currency_match: GBP
"""
    rules, errors = load_rules(yaml_text, named_splits={})
    assert errors == []
    assert rules[0].description == "Test rule"
    assert rules[0].currency_match == "GBP"


def test_load_amount_gt():
    yaml_text = """
rules:
  - id: r_big
    match: /big/i
    action: always_ignore
    amount: "> 30"
"""
    rules, errors = load_rules(yaml_text, named_splits={})
    assert errors == []
    assert rules[0].amount_min == Decimal("30")
    assert rules[0].amount_max is None


def test_load_amount_lt():
    yaml_text = """
rules:
  - id: r_small
    match: /small/i
    action: always_ignore
    amount: "< 50"
"""
    rules, errors = load_rules(yaml_text, named_splits={})
    assert errors == []
    assert rules[0].amount_min is None
    assert rules[0].amount_max == Decimal("50")


def test_load_amount_range():
    yaml_text = """
rules:
  - id: r_range
    match: /range/i
    action: always_ignore
    amount: "10..50"
"""
    rules, errors = load_rules(yaml_text, named_splits={})
    assert errors == []
    assert rules[0].amount_min == Decimal("10")
    assert rules[0].amount_max == Decimal("50")


def test_load_amount_null_or_missing():
    yaml_text = """
rules:
  - id: r_null
    match: /null/i
    action: always_ignore
    amount: null
  - id: r_missing
    match: /missing/i
    action: always_ignore
"""
    rules, errors = load_rules(yaml_text, named_splits={})
    assert errors == []
    for rule in rules:
        assert rule.amount_min is None
        assert rule.amount_max is None


def test_load_always_ignore_ignores_category_and_split():
    yaml_text = """
rules:
  - id: r_ignore_extras
    match: /tfl/i
    action: always_ignore
    category: Transport
    split:
      method: equal
"""
    rules, errors = load_rules(yaml_text, named_splits={})
    # always_ignore should load fine even with extra fields present
    assert errors == []
    assert len(rules) == 1


def test_empty_rules_section():
    rules, errors = load_rules("rules: []", named_splits={})
    assert rules == []
    assert errors == []


def test_missing_rules_key():
    rules, errors = load_rules("{}", named_splits={})
    assert rules == []
    assert errors == []


def test_empty_yaml():
    rules, errors = load_rules("", named_splits={})
    assert rules == []
    assert errors == []


# ------------------------------------------------------------------ error cases


def test_bad_regex_skips_rule():
    yaml_text = """
rules:
  - id: r_bad
    match: /[unclosed/i
    action: always_ignore
  - id: r_good
    match: /netflix/i
    action: always_ignore
"""
    rules, errors = load_rules(yaml_text, named_splits={})
    assert len(rules) == 1
    assert rules[0].id == "r_good"
    assert len(errors) == 1
    assert "r_bad" in errors[0]


def test_bad_action_skips_rule():
    yaml_text = """
rules:
  - id: r_bad
    match: /test/i
    action: always_promote
  - id: r_good
    match: /good/i
    action: always_ignore
"""
    rules, errors = load_rules(yaml_text, named_splits={})
    assert len(rules) == 1
    assert rules[0].id == "r_good"
    assert any("always_promote" in e for e in errors)


def test_duplicate_id_rejects_second():
    yaml_text = """
rules:
  - id: r_dup
    match: /first/i
    action: always_ignore
  - id: r_dup
    match: /second/i
    action: always_ignore
"""
    rules, errors = load_rules(yaml_text, named_splits={})
    assert len(rules) == 1
    assert rules[0].pattern.pattern == "first"
    assert len(errors) == 1
    assert "duplicate" in errors[0]


def test_always_split_missing_category_skipped():
    yaml_text = """
rules:
  - id: r_no_cat
    match: /netflix/i
    action: always_split
    split:
      method: equal
      preset: "50_50"
"""
    rules, errors = load_rules(yaml_text, named_splits=NAMED_SPLITS_50_50)
    assert len(rules) == 0
    assert any("category" in e for e in errors)


def test_always_split_missing_split_skipped():
    yaml_text = """
rules:
  - id: r_no_split
    match: /netflix/i
    action: always_split
    category: Subscriptions
"""
    rules, errors = load_rules(yaml_text, named_splits=NAMED_SPLITS_50_50)
    assert len(rules) == 0
    assert any("split" in e for e in errors)


def test_review_each_time_missing_category_skipped():
    yaml_text = """
rules:
  - id: r_no_cat
    match: /deliveroo/i
    action: review_each_time
"""
    rules, errors = load_rules(yaml_text, named_splits={})
    assert len(rules) == 0
    assert any("category" in e for e in errors)


def test_bad_amount_format_skips_rule():
    yaml_text = """
rules:
  - id: r_bad_amount
    match: /test/i
    action: always_ignore
    amount: "between 10 and 20"
"""
    rules, errors = load_rules(yaml_text, named_splits={})
    assert len(rules) == 0
    assert len(errors) == 1


def test_unknown_preset_skips_rule():
    yaml_text = """
rules:
  - id: r_unknown_preset
    match: /netflix/i
    action: always_split
    category: Subscriptions
    split:
      method: equal
      preset: nonexistent_preset
"""
    rules, errors = load_rules(yaml_text, named_splits={})
    assert len(rules) == 0
    assert any("preset" in e or "nonexistent_preset" in e for e in errors)


def test_currency_match_uppercased():
    yaml_text = """
rules:
  - id: r_gbp
    match: /test/i
    action: always_ignore
    currency_match: gbp
"""
    rules, errors = load_rules(yaml_text, named_splits={})
    assert errors == []
    assert rules[0].currency_match == "GBP"


def test_inline_split_shares_no_preset():
    yaml_text = """
rules:
  - id: r_inline
    match: /test/i
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
    rules, errors = load_rules(yaml_text, named_splits={})
    assert errors == []
    assert rules[0].split is not None
    assert rules[0].split["shares"][0]["value"] == 70
