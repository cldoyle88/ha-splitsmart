"""Recurring-bill loader, validator, and schedule helpers for Splitsmart."""

from __future__ import annotations

import calendar
import datetime as dt
import logging
import pathlib
from dataclasses import dataclass, field
from typing import Any

import voluptuous as vol

_LOGGER = logging.getLogger(__name__)

# ------------------------------------------------------------------ constants

WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

# ------------------------------------------------------------------ voluptuous schemas


def _valid_weekday(value: str) -> str:
    lower = str(value).lower()
    if lower not in WEEKDAYS:
        raise vol.Invalid(
            f"weekday must be one of {sorted(WEEKDAYS)}, got '{value}'"
        )
    return lower


_SPLIT_SCHEMA = vol.Schema(
    {
        vol.Required("method"): vol.In(["equal", "percentage", "shares", "exact"]),
        vol.Required("shares"): vol.All(
            list,
            vol.Length(min=1),
            [
                vol.Schema(
                    {
                        vol.Required("user_id"): str,
                        vol.Required("value"): vol.Coerce(float),
                    }
                )
            ],
        ),
    }
)

_CATEGORY_SCHEMA = vol.Schema(
    {
        vol.Required("name"): str,
        vol.Required("home_amount"): vol.All(vol.Coerce(float), vol.Range(min=0.000001)),
        vol.Required("split"): _SPLIT_SCHEMA,
    }
)

_MONTHLY_SCHEDULE_SCHEMA = vol.Schema(
    {
        vol.Required("kind"): "monthly",
        vol.Required("day"): vol.All(vol.Coerce(int), vol.Range(min=1, max=31)),
    }
)

_WEEKLY_SCHEDULE_SCHEMA = vol.Schema(
    {
        vol.Required("kind"): "weekly",
        vol.Required("weekday"): _valid_weekday,
    }
)

_ANNUALLY_SCHEDULE_SCHEMA = vol.Schema(
    {
        vol.Required("kind"): "annually",
        vol.Required("month"): vol.All(vol.Coerce(int), vol.Range(min=1, max=12)),
        vol.Required("day"): vol.All(vol.Coerce(int), vol.Range(min=1, max=31)),
    }
)


def _validate_schedule(value: Any) -> dict:
    if not isinstance(value, dict):
        raise vol.Invalid("schedule must be a mapping")
    kind = value.get("kind")
    if kind == "monthly":
        return _MONTHLY_SCHEDULE_SCHEMA(value)
    if kind == "weekly":
        return _WEEKLY_SCHEDULE_SCHEMA(value)
    if kind == "annually":
        return _ANNUALLY_SCHEDULE_SCHEMA(value)
    raise vol.Invalid(f"schedule.kind must be monthly, weekly, or annually; got '{kind}'")


def _to_date(value: Any) -> dt.date | None:
    if value is None:
        return None
    if isinstance(value, dt.date):
        return value
    try:
        return dt.date.fromisoformat(str(value))
    except ValueError as err:
        raise vol.Invalid(f"Invalid date '{value}': {err}") from err


_RECURRING_ENTRY_SCHEMA = vol.Schema(
    {
        vol.Required("id"): vol.All(str, vol.Match(r"^[a-z0-9_]+$")),
        vol.Required("description"): vol.All(str, vol.Length(min=1)),
        vol.Required("amount"): vol.All(vol.Coerce(float), vol.Range(min=0.000001)),
        vol.Required("currency"): vol.All(str, vol.Length(min=3, max=3)),
        vol.Required("paid_by"): str,
        vol.Required("categories"): vol.All(list, vol.Length(min=1), [_CATEGORY_SCHEMA]),
        vol.Required("schedule"): _validate_schedule,
        vol.Optional("start_date"): _to_date,
        vol.Optional("end_date"): _to_date,
    }
)


# ------------------------------------------------------------------ dataclass


@dataclass
class RecurringEntry:
    id: str
    description: str
    amount: float
    currency: str
    paid_by: str
    categories: list[dict[str, Any]]
    schedule: dict[str, Any]
    start_date: dt.date | None = None
    end_date: dt.date | None = None


# ------------------------------------------------------------------ loader


def load_recurring(
    path: pathlib.Path,
    *,
    participants: list[str],
) -> list[RecurringEntry]:
    """Parse ``recurring.yaml`` and return valid entries.

    Invalid entries are skipped with an ERROR log; the file's absence is
    silently returned as an empty list. Duplicate ids cause the second entry
    to be rejected.
    """
    if not path.exists():
        _LOGGER.debug("recurring.yaml not found at %s — no recurrings configured", path)
        return []

    try:
        import yaml  # type: ignore[import]
        raw_text = path.read_text(encoding="utf-8")
        data = yaml.safe_load(raw_text)
    except Exception as err:
        _LOGGER.error("Failed to parse recurring.yaml: %s", err)
        return []

    if not data or "recurring" not in data:
        _LOGGER.debug("recurring.yaml has no 'recurring' key — returning empty list")
        return []

    raw_entries = data.get("recurring") or []
    if not isinstance(raw_entries, list):
        _LOGGER.error("recurring.yaml 'recurring' key must be a list")
        return []

    results: list[RecurringEntry] = []
    seen_ids: set[str] = set()

    for raw in raw_entries:
        if not isinstance(raw, dict):
            _LOGGER.error("recurring.yaml: entry is not a mapping, skipping")
            continue

        entry_id = raw.get("id", "<unknown>")

        # Validate against voluptuous schema
        try:
            validated = _RECURRING_ENTRY_SCHEMA(raw)
        except vol.Invalid as err:
            _LOGGER.error(
                "recurring.yaml: entry '%s' is invalid (%s) — skipping", entry_id, err
            )
            continue

        # Participant check for paid_by
        if validated["paid_by"] not in participants:
            _LOGGER.error(
                "recurring.yaml: entry '%s' paid_by '%s' is not a configured participant — skipping",
                entry_id,
                validated["paid_by"],
            )
            continue

        # Duplicate id check
        if validated["id"] in seen_ids:
            _LOGGER.error(
                "recurring.yaml: duplicate id '%s' — second entry skipped", validated["id"]
            )
            continue

        seen_ids.add(validated["id"])
        results.append(
            RecurringEntry(
                id=validated["id"],
                description=validated["description"],
                amount=float(validated["amount"]),
                currency=validated["currency"].upper(),
                paid_by=validated["paid_by"],
                categories=validated["categories"],
                schedule=validated["schedule"],
                start_date=validated.get("start_date"),
                end_date=validated.get("end_date"),
            )
        )

    return results


# ------------------------------------------------------------------ schedule matching


def _last_day_of_month(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def _clamp_day(year: int, month: int, day: int) -> int:
    return min(day, _last_day_of_month(year, month))


def schedule_matches(schedule: dict[str, Any], date: dt.date) -> bool:
    """Return True when ``date`` is a trigger day for ``schedule``."""
    kind = schedule["kind"]

    if kind == "monthly":
        target_day = _clamp_day(date.year, date.month, schedule["day"])
        return date.day == target_day

    if kind == "weekly":
        return date.weekday() == WEEKDAYS[schedule["weekday"]]

    if kind == "annually":
        target_day = _clamp_day(date.year, schedule["month"], schedule["day"])
        return date.month == schedule["month"] and date.day == target_day

    return False


def dates_in_range(
    schedule: dict[str, Any],
    *,
    floor: dt.date,
    ceiling: dt.date,
) -> list[dt.date]:
    """Return all dates in [floor..ceiling] that match the schedule, in order."""
    results: list[dt.date] = []
    current = floor
    while current <= ceiling:
        if schedule_matches(schedule, current):
            results.append(current)
        current += dt.timedelta(days=1)
    return results
