"""Recurring-bill loader, validator, schedule helpers, and materialiser for Splitsmart."""

from __future__ import annotations

import calendar
import datetime as dt
import json
import logging
import pathlib
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Any

import aiofiles

if TYPE_CHECKING:
    pass

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
        raise vol.Invalid(f"weekday must be one of {sorted(WEEKDAYS)}, got '{value}'")
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
            _LOGGER.error("recurring.yaml: entry '%s' is invalid (%s) — skipping", entry_id, err)
            continue

        # Participant check for paid_by
        if validated["paid_by"] not in participants:
            _LOGGER.error(
                "recurring.yaml: entry '%s' paid_by '%s' is not a configured participant"
                " — skipping",
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


# ------------------------------------------------------------------ recurring state JSONL


async def load_recurring_state(path: pathlib.Path) -> dict[str, dt.date]:
    """Return {recurring_id: last_materialised_date} with newest-wins semantics."""
    state: dict[str, dt.date] = {}
    if not path.exists():
        return state
    async with aiofiles.open(path, encoding="utf-8") as fh:
        async for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
                rid = obj.get("recurring_id")
                date_raw = obj.get("last_materialised_date")
                if rid and date_raw:
                    state[rid] = dt.date.fromisoformat(date_raw)
            except (json.JSONDecodeError, ValueError):
                pass
    return state


async def append_recurring_state(
    path: pathlib.Path,
    *,
    recurring_id: str,
    last_materialised_date: dt.date,
) -> None:
    """Append a state row for ``recurring_id`` with newest-wins."""
    from .const import ID_PREFIX_RECURRING_STATE
    from .storage import new_id

    record = {
        "id": new_id(ID_PREFIX_RECURRING_STATE),
        "created_at": dt.datetime.now(tz=dt.UTC).astimezone().isoformat(),
        "recurring_id": recurring_id,
        "last_materialised_date": last_materialised_date.isoformat(),
    }
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
    async with aiofiles.open(path, mode="a", encoding="utf-8") as fh:
        await fh.write(line)
        await fh.flush()


# ------------------------------------------------------------------ materialiser


@dataclass
class MaterialiseResult:
    materialised: int = 0
    skipped_fx_failure: int = 0
    skipped_duplicate: int = 0


async def materialise_recurring(
    *,
    entries: list[RecurringEntry],
    state: dict[str, dt.date],
    existing_expenses: list[dict[str, Any]],
    fx_client: Any,
    home_currency: str,
    participants: set[str],
    known_categories: set[str],
    storage: Any,
    today: dt.date | None = None,
    filter_id: str | None = None,
) -> MaterialiseResult:
    """Materialise recurring entries that are due.

    Idempotent:
    - Belt 1: ``state[recurring_id]`` tracks last materialised date.
    - Belt 2: scan ``existing_expenses`` for (recurring_id, date) collisions.

    FX failures are logged at WARNING and the date is skipped; other dates in
    the same run still materialise. Only dates that successfully materialise
    advance ``last_materialised_date``.

    Privacy: only (recurring_id, date) logged at INFO. No amounts, no descriptions.
    """
    from .const import SOURCE_RECURRING
    from .fx import FxUnavailableError, FxUnsupportedCurrencyError
    from .ledger import SplitsmartValidationError, build_expense_record, validate_expense_record

    _today = today or dt.date.today()
    result = MaterialiseResult()

    # Pre-build a set of (recurring_id, date) that already exist for fast O(1) checks.
    existing_pairs: set[tuple[str, str]] = {
        (e.get("recurring_id", ""), e.get("date", ""))
        for e in existing_expenses
        if e.get("source") == SOURCE_RECURRING and e.get("recurring_id")
    }

    for entry in entries:
        if filter_id is not None and entry.id != filter_id:
            continue

        last = state.get(entry.id)
        floor = (last + dt.timedelta(days=1)) if last is not None else (entry.start_date or _today)
        ceiling = min(_today, entry.end_date or _today)

        if floor > ceiling:
            continue

        due_dates = dates_in_range(entry.schedule, floor=floor, ceiling=ceiling)
        if not due_dates:
            continue

        # Backfill advisory on first materialisation with more than 3 entries
        if last is None and len(due_dates) > 3:
            _LOGGER.info(
                "First materialisation of recurring '%s' will create %d backfill entries "
                "(start_date: %s). Review recurring_state.jsonl after the run.",
                entry.id,
                len(due_dates),
                entry.start_date,
            )

        highest_success: dt.date | None = None

        for due_date in due_dates:
            date_iso = due_date.isoformat()

            # Belt 2: scan for existing expense with same (recurring_id, date)
            if (entry.id, date_iso) in existing_pairs:
                _LOGGER.debug(
                    "Skipping duplicate recurring '%s' on %s (already in ledger)",
                    entry.id,
                    date_iso,
                )
                result.skipped_duplicate += 1
                continue

            # Resolve FX
            try:
                if entry.currency.upper() == home_currency.upper():
                    fx_rate = Decimal("1")
                    fx_date_iso = date_iso
                else:
                    fx_result = await fx_client.get_rate(
                        date=due_date,
                        from_currency=entry.currency,
                        to_currency=home_currency,
                    )
                    fx_rate = fx_result.rate
                    fx_date_iso = fx_result.fx_date.isoformat()
            except (FxUnavailableError, FxUnsupportedCurrencyError) as exc:
                _LOGGER.warning(
                    "FX failure for recurring '%s' on %s: %s — skipping date",
                    entry.id,
                    date_iso,
                    exc,
                )
                result.skipped_fx_failure += 1
                continue

            # Rescale category home_amounts by fx_rate
            # (categories in recurring.yaml are authored in original currency)
            total_home = (Decimal(str(entry.amount)) * fx_rate).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            categories = _rescale_categories(entry.categories, fx_rate, total_home)

            expense = build_expense_record(
                date=date_iso,
                description=entry.description,
                paid_by=entry.paid_by,
                amount=entry.amount,
                currency=entry.currency.upper(),
                home_currency=home_currency,
                categories=categories,
                notes=None,
                source=SOURCE_RECURRING,
                staging_id=None,
                receipt_path=None,
                created_by=entry.paid_by,
                fx_rate=fx_rate,
                fx_date=fx_date_iso,
                recurring_id=entry.id,
            )

            try:
                validate_expense_record(
                    expense,
                    participants=participants,
                    home_currency=home_currency,
                    known_categories=known_categories,
                )
            except SplitsmartValidationError as err:
                _LOGGER.warning(
                    "Recurring '%s' on %s failed validation: %s — skipping",
                    entry.id,
                    date_iso,
                    err,
                )
                result.skipped_fx_failure += 1  # treat validation failures as skip
                continue

            await storage.append(storage.expenses_path, expense)
            existing_pairs.add((entry.id, date_iso))  # prevent intra-run double-write
            highest_success = due_date
            result.materialised += 1

        # Update state once per recurring after processing all its dates
        if highest_success is not None:
            await append_recurring_state(
                storage.recurring_state_path,
                recurring_id=entry.id,
                last_materialised_date=highest_success,
            )
            state[entry.id] = highest_success

    return result


def _rescale_categories(
    categories: list[dict[str, Any]],
    fx_rate: Decimal,
    total_home: Decimal,
) -> list[dict[str, Any]]:
    """Return a new category list with home_amounts rescaled by fx_rate.

    The last allocation absorbs any rounding drift so sum(home_amounts) == total_home
    exactly. Splits are unchanged (they are dimensionless).
    """
    _cent = Decimal("0.01")
    rescaled = []
    running_sum = Decimal("0")

    for i, alloc in enumerate(categories):
        if i == len(categories) - 1:
            # Last allocation absorbs drift
            home_amount = float((total_home - running_sum).quantize(_cent, rounding=ROUND_HALF_UP))
        else:
            raw_home = Decimal(str(alloc["home_amount"])) * fx_rate
            home_amount = float(raw_home.quantize(_cent, rounding=ROUND_HALF_UP))
            running_sum += Decimal(str(home_amount))

        rescaled.append({**alloc, "home_amount": home_amount})

    return rescaled
