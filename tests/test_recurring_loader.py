"""Tests for the recurring.yaml loader and voluptuous validation."""

from __future__ import annotations

import datetime as dt
import pathlib

import pytest

from custom_components.splitsmart.recurring import RecurringEntry, load_recurring

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "recurring"
PARTICIPANTS = ["u1", "u2"]


# ------------------------------------------------------------------ happy path


def test_load_netflix_fixture():
    entries = load_recurring(FIXTURES / "netflix.yaml", participants=PARTICIPANTS)
    assert len(entries) == 1
    e = entries[0]
    assert e.id == "netflix"
    assert e.amount == 15.99
    assert e.currency == "GBP"
    assert e.paid_by == "u1"
    assert e.schedule == {"kind": "monthly", "day": 15}
    assert e.start_date == dt.date(2026, 1, 15)
    assert e.end_date is None


def test_load_typical_household_fixture():
    entries = load_recurring(FIXTURES / "typical_household.yaml", participants=PARTICIPANTS)
    assert len(entries) == 3
    ids = [e.id for e in entries]
    assert "netflix" in ids
    assert "weekly_shop" in ids
    assert "tv_licence" in ids


# ------------------------------------------------------------------ missing file


def test_missing_file_returns_empty(tmp_path: pathlib.Path):
    entries = load_recurring(tmp_path / "does_not_exist.yaml", participants=PARTICIPANTS)
    assert entries == []


# ------------------------------------------------------------------ malformed file


def test_malformed_valid_entry_still_loaded(caplog):
    """malformed.yaml has one valid + one invalid entry. Valid one must load."""
    import logging

    with caplog.at_level(logging.ERROR):
        entries = load_recurring(FIXTURES / "malformed.yaml", participants=PARTICIPANTS)

    assert len(entries) == 1
    assert entries[0].id == "valid_one"

    # An ERROR log was emitted for the bad entry
    errors = [r for r in caplog.records if r.levelname == "ERROR"]
    assert any("bad_no_schedule" in r.message for r in errors)


# ------------------------------------------------------------------ paid_by not a participant


def test_paid_by_not_participant_rejected(tmp_path: pathlib.Path, caplog):
    import logging

    yaml_content = """
recurring:
  - id: bad_paid_by
    description: Test
    amount: 10.00
    currency: GBP
    paid_by: stranger
    categories:
      - name: Other
        home_amount: 10.00
        split:
          method: equal
          shares:
            - {user_id: u1, value: 50}
            - {user_id: u2, value: 50}
    schedule:
      kind: monthly
      day: 1
"""
    p = tmp_path / "r.yaml"
    p.write_text(yaml_content, encoding="utf-8")

    with caplog.at_level(logging.ERROR):
        entries = load_recurring(p, participants=PARTICIPANTS)

    assert entries == []
    errors = [r for r in caplog.records if r.levelname == "ERROR"]
    assert any("paid_by" in r.message for r in errors)


# ------------------------------------------------------------------ duplicate id


def test_duplicate_id_second_rejected(tmp_path: pathlib.Path, caplog):
    import logging

    yaml_content = """
recurring:
  - id: dupe
    description: First
    amount: 10.00
    currency: GBP
    paid_by: u1
    categories:
      - name: Other
        home_amount: 10.00
        split:
          method: equal
          shares: [{user_id: u1, value: 50}, {user_id: u2, value: 50}]
    schedule: {kind: monthly, day: 1}

  - id: dupe
    description: Second (duplicate)
    amount: 20.00
    currency: GBP
    paid_by: u1
    categories:
      - name: Other
        home_amount: 20.00
        split:
          method: equal
          shares: [{user_id: u1, value: 50}, {user_id: u2, value: 50}]
    schedule: {kind: monthly, day: 1}
"""
    p = tmp_path / "r.yaml"
    p.write_text(yaml_content, encoding="utf-8")

    with caplog.at_level(logging.ERROR):
        entries = load_recurring(p, participants=PARTICIPANTS)

    assert len(entries) == 1
    assert entries[0].description == "First"
    errors = [r for r in caplog.records if r.levelname == "ERROR"]
    assert any("duplicate" in r.message for r in errors)


# ------------------------------------------------------------------ schedule validation


def test_invalid_day_0_rejected(tmp_path: pathlib.Path, caplog):
    import logging

    yaml_content = """
recurring:
  - id: bad_day
    description: Test
    amount: 10.00
    currency: GBP
    paid_by: u1
    categories:
      - name: Other
        home_amount: 10.00
        split:
          method: equal
          shares: [{user_id: u1, value: 50}, {user_id: u2, value: 50}]
    schedule: {kind: monthly, day: 0}
"""
    p = tmp_path / "r.yaml"
    p.write_text(yaml_content, encoding="utf-8")

    with caplog.at_level(logging.ERROR):
        entries = load_recurring(p, participants=PARTICIPANTS)

    assert entries == []


def test_invalid_weekday_typo_rejected(tmp_path: pathlib.Path, caplog):
    import logging

    yaml_content = """
recurring:
  - id: bad_weekday
    description: Test
    amount: 10.00
    currency: GBP
    paid_by: u1
    categories:
      - name: Other
        home_amount: 10.00
        split:
          method: equal
          shares: [{user_id: u1, value: 50}, {user_id: u2, value: 50}]
    schedule: {kind: weekly, weekday: tuseday}
"""
    p = tmp_path / "r.yaml"
    p.write_text(yaml_content, encoding="utf-8")

    with caplog.at_level(logging.ERROR):
        entries = load_recurring(p, participants=PARTICIPANTS)

    assert entries == []
