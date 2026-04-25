"""Tests for recurring schedule matching and date-range expansion.

Pure logic tests — no IO, no HA event loop.
"""

from __future__ import annotations

import datetime as dt

from custom_components.splitsmart.recurring import dates_in_range, schedule_matches

# ------------------------------------------------------------------ monthly


def test_monthly_day_15_matches():
    sched = {"kind": "monthly", "day": 15}
    assert schedule_matches(sched, dt.date(2026, 4, 15))
    assert not schedule_matches(sched, dt.date(2026, 4, 14))
    assert not schedule_matches(sched, dt.date(2026, 4, 16))


def test_monthly_day_31_feb_non_leap_clamps_to_28():
    """Feb 2026 has 28 days; day=31 fires on Feb 28."""
    sched = {"kind": "monthly", "day": 31}
    assert schedule_matches(sched, dt.date(2026, 2, 28))
    assert not schedule_matches(sched, dt.date(2026, 2, 27))


def test_monthly_day_31_april_clamps_to_30():
    """April has 30 days; day=31 fires on Apr 30."""
    sched = {"kind": "monthly", "day": 31}
    assert schedule_matches(sched, dt.date(2026, 4, 30))
    assert not schedule_matches(sched, dt.date(2026, 4, 29))


def test_monthly_day_29_feb_leap_matches():
    """Feb 2024 is a leap year — day=29 fires on Feb 29."""
    sched = {"kind": "monthly", "day": 29}
    assert schedule_matches(sched, dt.date(2024, 2, 29))


def test_monthly_day_29_feb_non_leap_clamps_to_28():
    """Feb 2026 is not a leap year — day=29 fires on Feb 28."""
    sched = {"kind": "monthly", "day": 29}
    assert schedule_matches(sched, dt.date(2026, 2, 28))
    assert not schedule_matches(sched, dt.date(2026, 2, 27))


# ------------------------------------------------------------------ weekly


def test_weekly_monday_matches():
    sched = {"kind": "weekly", "weekday": "monday"}
    # 2026-04-20 is a Monday
    assert schedule_matches(sched, dt.date(2026, 4, 20))
    assert not schedule_matches(sched, dt.date(2026, 4, 21))  # Tuesday


def test_weekly_saturday_matches():
    sched = {"kind": "weekly", "weekday": "saturday"}
    # 2026-04-18 is a Saturday
    assert schedule_matches(sched, dt.date(2026, 4, 18))
    assert not schedule_matches(sched, dt.date(2026, 4, 19))  # Sunday


# ------------------------------------------------------------------ annually


def test_annually_apr_6_matches():
    sched = {"kind": "annually", "month": 4, "day": 6}
    assert schedule_matches(sched, dt.date(2026, 4, 6))
    assert not schedule_matches(sched, dt.date(2026, 4, 7))
    assert not schedule_matches(sched, dt.date(2027, 4, 5))
    assert schedule_matches(sched, dt.date(2027, 4, 6))


def test_annually_feb_29_non_leap_clamps_to_28():
    sched = {"kind": "annually", "month": 2, "day": 29}
    assert schedule_matches(sched, dt.date(2026, 2, 28))
    assert not schedule_matches(sched, dt.date(2026, 2, 27))


def test_annually_feb_29_leap_matches_feb_29():
    sched = {"kind": "annually", "month": 2, "day": 29}
    assert schedule_matches(sched, dt.date(2024, 2, 29))


# ------------------------------------------------------------------ dates_in_range


def test_dates_in_range_monthly():
    sched = {"kind": "monthly", "day": 15}
    # March + April 15
    result = dates_in_range(
        sched,
        floor=dt.date(2026, 3, 1),
        ceiling=dt.date(2026, 4, 30),
    )
    assert result == [dt.date(2026, 3, 15), dt.date(2026, 4, 15)]


def test_dates_in_range_monthly_day31_short_month():
    """Monthly day=31, window is only April (30 days); result is Apr 30."""
    sched = {"kind": "monthly", "day": 31}
    result = dates_in_range(
        sched,
        floor=dt.date(2026, 4, 1),
        ceiling=dt.date(2026, 4, 30),
    )
    assert result == [dt.date(2026, 4, 30)]


def test_dates_in_range_weekly():
    sched = {"kind": "weekly", "weekday": "monday"}
    # First two Mondays in April 2026: Apr 6, Apr 13
    result = dates_in_range(
        sched,
        floor=dt.date(2026, 4, 1),
        ceiling=dt.date(2026, 4, 15),
    )
    assert result == [dt.date(2026, 4, 6), dt.date(2026, 4, 13)]


def test_dates_in_range_annually_multi_year():
    sched = {"kind": "annually", "month": 4, "day": 1}
    result = dates_in_range(
        sched,
        floor=dt.date(2025, 1, 1),
        ceiling=dt.date(2027, 12, 31),
    )
    assert result == [dt.date(2025, 4, 1), dt.date(2026, 4, 1), dt.date(2027, 4, 1)]


def test_dates_in_range_empty_when_no_match():
    """Monthly day=31 in a 1-day window that is not the 31st."""
    sched = {"kind": "monthly", "day": 31}
    result = dates_in_range(
        sched,
        floor=dt.date(2026, 4, 29),
        ceiling=dt.date(2026, 4, 29),
    )
    assert result == []


def test_dates_in_range_floor_equals_ceiling():
    sched = {"kind": "monthly", "day": 15}
    result = dates_in_range(
        sched,
        floor=dt.date(2026, 4, 15),
        ceiling=dt.date(2026, 4, 15),
    )
    assert result == [dt.date(2026, 4, 15)]
