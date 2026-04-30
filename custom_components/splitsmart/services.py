"""Service handlers for Splitsmart."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .const import (
    DOMAIN,
    SERVICE_ADD_EXPENSE,
    SERVICE_ADD_SETTLEMENT,
    SERVICE_APPLY_RULES,
    SERVICE_DELETE_EXPENSE,
    SERVICE_DELETE_SETTLEMENT,
    SERVICE_EDIT_EXPENSE,
    SERVICE_EDIT_SETTLEMENT,
    SERVICE_IMPORT_FILE,
    SERVICE_MATERIALISE_RECURRING,
    SERVICE_PROMOTE_STAGING,
    SERVICE_SKIP_STAGING,
    SOURCE_STAGING,
    SOURCES,
    SPLIT_METHODS,
    TARGET_EXPENSE,
    TARGET_SETTLEMENT,
    TARGET_STAGING,
    TOMBSTONE_DELETE,
    TOMBSTONE_DISCARD,
    TOMBSTONE_EDIT,
    TOMBSTONE_PROMOTE,
)
from .fx import FxClient, FxUnsupportedCurrencyError
from .importer import parse_file
from .importer.dedup import partition_by_dedup
from .importer.mapping import save_mapping
from .importer.normalise import dedup_hash
from .importer.types import ImporterError, Mapping
from .ledger import (
    SplitsmartValidationError,
    build_expense_record,
    build_settlement_record,
    rescale_categories,
    validate_expense_record,
    validate_settlement_record,
)
from .rules import RuleParseError, build_match_payload, evaluate
from .storage import new_id

_LOGGER = logging.getLogger(__name__)

# ------------------------------------------------------------------ voluptuous schemas

SPLIT_SCHEMA = vol.Schema(
    {
        vol.Required("method"): vol.In(list(SPLIT_METHODS)),
        vol.Required("shares"): vol.All(
            cv.ensure_list,
            vol.Length(min=1),
            [
                vol.Schema(
                    {
                        vol.Required("user_id"): cv.string,
                        vol.Required("value"): vol.Coerce(float),
                    }
                )
            ],
        ),
    }
)

CATEGORY_ALLOCATION_SCHEMA = vol.Schema(
    {
        vol.Required("name"): cv.string,
        vol.Required("home_amount"): vol.Coerce(float),
        vol.Required("split"): SPLIT_SCHEMA,
    }
)

ADD_EXPENSE_SCHEMA = vol.Schema(
    {
        vol.Required("date"): cv.date,
        vol.Required("description"): vol.All(cv.string, vol.Length(min=1, max=200)),
        vol.Required("paid_by"): cv.string,
        vol.Required("amount"): vol.All(vol.Coerce(float), vol.Range(min=0.01)),
        vol.Optional("currency"): vol.All(cv.string, vol.Length(min=3, max=3)),
        vol.Required("categories"): vol.All(
            cv.ensure_list, vol.Length(min=1), [CATEGORY_ALLOCATION_SCHEMA]
        ),
        vol.Optional("notes"): vol.Any(None, cv.string),
        vol.Optional("receipt_path"): vol.Any(None, cv.string),
        vol.Optional("source", default="manual"): vol.In(list(SOURCES)),
        vol.Optional("staging_id"): vol.Any(None, cv.string),
        vol.Optional("fx_rate"): vol.All(vol.Coerce(float), vol.Range(min=0.000001)),
        vol.Optional("fx_date"): cv.date,
    }
)

ADD_SETTLEMENT_SCHEMA = vol.Schema(
    {
        vol.Required("date"): cv.date,
        vol.Required("from_user"): cv.string,
        vol.Required("to_user"): cv.string,
        vol.Required("amount"): vol.All(vol.Coerce(float), vol.Range(min=0.01)),
        vol.Optional("currency"): vol.All(cv.string, vol.Length(min=3, max=3)),
        vol.Optional("notes"): vol.Any(None, cv.string),
        vol.Optional("fx_rate"): vol.All(vol.Coerce(float), vol.Range(min=0.000001)),
        vol.Optional("fx_date"): cv.date,
    }
)

EDIT_EXPENSE_SCHEMA = ADD_EXPENSE_SCHEMA.extend(
    {
        vol.Required("id"): cv.string,
        vol.Optional("reason"): vol.Any(None, cv.string),
    }
)

EDIT_SETTLEMENT_SCHEMA = ADD_SETTLEMENT_SCHEMA.extend(
    {
        vol.Required("id"): cv.string,
        vol.Optional("reason"): vol.Any(None, cv.string),
    }
)

DELETE_EXPENSE_SCHEMA = vol.Schema(
    {
        vol.Required("id"): cv.string,
        vol.Optional("reason"): vol.Any(None, cv.string),
    }
)

DELETE_SETTLEMENT_SCHEMA = vol.Schema(
    {
        vol.Required("id"): cv.string,
        vol.Optional("reason"): vol.Any(None, cv.string),
    }
)

# ---- M3 staging services ----

PROMOTE_STAGING_SCHEMA = vol.Schema(
    {
        vol.Required("staging_id"): cv.string,
        vol.Required("paid_by"): cv.string,
        vol.Required("categories"): vol.All(
            cv.ensure_list, vol.Length(min=1), [CATEGORY_ALLOCATION_SCHEMA]
        ),
        vol.Optional("notes"): vol.Any(None, cv.string),
        vol.Optional("receipt_path"): vol.Any(None, cv.string),
        # Optional overrides let the reviewer rename the merchant or shift the
        # date at promotion time without editing the staging row first.
        vol.Optional("override_description"): vol.Any(None, cv.string),
        vol.Optional("override_date"): vol.Any(None, cv.date),
        vol.Optional("reason"): vol.Any(None, cv.string),
        # FX overrides — bypass the Frankfurter lookup when the caller already
        # knows the correct rate (e.g. M3-staged rows re-promoted with explicit rate).
        vol.Optional("fx_rate"): vol.All(vol.Coerce(float), vol.Range(min=0.000001)),
        vol.Optional("fx_date"): cv.date,
    }
)

SKIP_STAGING_SCHEMA = vol.Schema(
    {
        vol.Required("staging_id"): cv.string,
        vol.Optional("reason"): vol.Any(None, cv.string),
    }
)

IMPORT_FILE_SCHEMA = vol.Schema(
    {
        vol.Required("upload_id"): cv.string,
        # Mapping shape is validated by the importer's apply_mapping, not here —
        # voluptuous would have to mirror types.Mapping and drift as that evolves.
        vol.Optional("mapping"): vol.Any(None, dict),
        # rule_set is accepted but ignored in M3 — rules land in M5.
        vol.Optional("rule_set"): vol.Any(None, cv.string, dict),
        vol.Optional("remember_mapping", default=True): bool,
    }
)


# ------------------------------------------------------------------ helpers


def _get_entry_data(hass: HomeAssistant) -> tuple[Any, Any, list[str], str, set[str]]:
    """Return (storage, coordinator, participants, home_currency, known_categories).
    Finds the first (only) loaded config entry."""
    domain_data = hass.data.get(DOMAIN, {})
    if not domain_data:
        raise ServiceValidationError("Splitsmart integration is not loaded")
    entry_data = next(iter(domain_data.values()))
    storage = entry_data["storage"]
    coordinator = entry_data["coordinator"]
    participants: list[str] = coordinator.participants
    home_currency: str = coordinator.home_currency
    known_categories: set[str] = set(coordinator.categories)
    return storage, coordinator, participants, home_currency, known_categories


def _resolve_caller(call: ServiceCall, participants: list[str]) -> str:
    """Return the calling user's id. Raises if not a participant."""
    caller = call.context.user_id
    if caller is None:
        _LOGGER.debug("Service called without user context; defaulting to first participant")
        return participants[0]
    if caller not in participants:
        raise ServiceValidationError(f"User {caller!r} is not a configured Splitsmart participant")
    return caller


def _get_fx_client(hass: HomeAssistant) -> FxClient:
    domain_data = hass.data.get(DOMAIN, {})
    if not domain_data:
        raise ServiceValidationError("Splitsmart integration is not loaded")
    entry_data = next(iter(domain_data.values()))
    return entry_data["fx"]


async def _resolve_fx(
    fx_client: FxClient,
    *,
    currency: str,
    home_currency: str,
    date: str,
    explicit_rate: float | None,
    explicit_fx_date: date | None,
) -> tuple[Decimal, str]:
    """Return (rate, fx_date_iso) for the write.

    Raises ServiceValidationError with a stable message on any FX failure so
    callers (UI, automations, Developer Tools) can surface it directly.
    """
    if currency == home_currency and explicit_rate is not None:
        raise ServiceValidationError(
            "fx_rate provided for a home-currency entry. "
            "Either remove fx_rate or change the currency."
        )

    if currency == home_currency:
        return Decimal("1"), date

    if explicit_rate is not None:
        fx_date_str = explicit_fx_date.isoformat() if explicit_fx_date else date
        return Decimal(str(explicit_rate)), fx_date_str

    # Live lookup via cache → Frankfurter
    import datetime as _dt

    expense_date = _dt.date.fromisoformat(date)
    today = _dt.date.today()

    try:
        result = await fx_client.get_rate(
            date=expense_date,
            from_currency=currency,
            to_currency=home_currency,
        )
    except FxUnsupportedCurrencyError as exc:
        raise ServiceValidationError(
            f"Currency '{currency}' is not supported by the FX provider. "
            "Provide fx_rate explicitly or choose a different currency."
        ) from exc
    except Exception as exc:
        _LOGGER.error("FX lookup failed for %s→%s on %s", currency, home_currency, date)
        raise ServiceValidationError(
            f"FX rate for {date} {currency}→{home_currency} is not cached and "
            "Frankfurter is unreachable. Try again when connectivity returns, "
            "or provide fx_rate explicitly."
        ) from exc

    # Sanity guard: compare resolved rate to today's rate when the date is
    # within ±365 days. Skipped for older dates — rates can legitimately differ
    # by more than 50% over longer periods.
    if abs((today - expense_date).days) <= 365:
        try:
            today_result = await fx_client.get_rate(
                date=today,
                from_currency=currency,
                to_currency=home_currency,
            )
            today_rate = today_result.rate
            if today_rate and today_rate != 0:
                ratio = result.rate / today_rate
                if ratio > Decimal("1.5") or ratio < Decimal("2") / Decimal("3"):
                    raise ServiceValidationError(
                        f"Resolved FX rate {result.rate} for {currency}→{home_currency} "
                        f"on {date} diverges by more than 50% from today's rate "
                        f"{today_rate}. If this is intentional, provide fx_rate explicitly."
                    )
        except ServiceValidationError:
            raise
        except Exception:
            # Today's lookup failed — swallow and skip the guard.
            # The primary lookup succeeded; don't turn paranoia into a write failure.
            _LOGGER.debug(
                "FX sanity guard skipped: today's rate lookup failed for %s→%s",
                currency,
                home_currency,
            )

    return result.rate, result.fx_date.isoformat()


def _find_live_staging_row(coordinator: Any, staging_id: str, caller: str) -> dict[str, Any]:
    """Return the caller's live staging row by id, or raise.

    Raises:
      - ServiceValidationError("permission_denied") if the row belongs to
        another user (SPEC §7 — staging is private to the uploader).
      - ServiceValidationError if the row doesn't exist in the uploader's
        live staging (either never existed or already tombstoned).
    """
    # Live (post-tombstone) view — already-tombstoned rows drop out here.
    staging_lists = coordinator.data.staging_by_user if coordinator.data is not None else {}

    for owner, rows in staging_lists.items():
        for row in rows:
            if row["id"] == staging_id:
                if owner != caller:
                    # SPEC §7: another user's staging is not reachable via
                    # any service, even if the caller is a participant.
                    raise ServiceValidationError("permission_denied")
                return row

    raise ServiceValidationError(f"Staging row '{staging_id}' not found")


# ------------------------------------------------------------------ error guard


def _service_guard(service_name: str):
    """Decorator that converts unhandled exceptions to ServiceValidationError.

    ServiceValidationError, HomeAssistantError, and vol.Invalid already carry
    user-readable messages and pass through unchanged. Everything else becomes
    a structured bug-report prompt so callers never see HA's generic
    "Unknown error (unknown_error)".
    """
    from collections.abc import Callable
    from functools import wraps

    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        async def wrapper(call: ServiceCall) -> dict[str, Any]:
            try:
                return await fn(call)
            except (ServiceValidationError, HomeAssistantError, vol.Invalid):
                raise
            except Exception as err:
                _LOGGER.error("Internal error in %s: %s", service_name, err, exc_info=True)
                raise ServiceValidationError(
                    f"Internal error in {service_name}: {err}. Please report this as a bug."
                ) from err

        return wrapper

    return decorator


# ------------------------------------------------------------------ handlers


@_service_guard("add_expense")
async def _handle_add_expense(call: ServiceCall) -> dict[str, Any]:
    data = ADD_EXPENSE_SCHEMA(dict(call.data))
    storage, coordinator, participants, home_currency, known_cats = _get_entry_data(call.hass)
    caller = _resolve_caller(call, participants)

    currency = data.get("currency", home_currency)
    date_str = data["date"].isoformat()
    fx_rate, fx_date_str = await _resolve_fx(
        _get_fx_client(call.hass),
        currency=currency,
        home_currency=home_currency,
        date=date_str,
        explicit_rate=data.get("fx_rate"),
        explicit_fx_date=data.get("fx_date"),
    )

    total_home = (Decimal(str(data["amount"])) * fx_rate).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    record = build_expense_record(
        date=date_str,
        description=data["description"],
        paid_by=data["paid_by"],
        amount=data["amount"],
        currency=currency,
        home_currency=home_currency,
        categories=rescale_categories(data["categories"], fx_rate, total_home),
        notes=data.get("notes"),
        source=data.get("source", "manual"),
        staging_id=data.get("staging_id"),
        receipt_path=data.get("receipt_path"),
        created_by=caller,
        fx_rate=fx_rate,
        fx_date=fx_date_str,
    )

    try:
        validate_expense_record(
            record,
            participants=set(participants),
            home_currency=home_currency,
            known_categories=known_cats,
        )
    except SplitsmartValidationError as err:
        raise ServiceValidationError(str(err)) from err

    await storage.append(storage.expenses_path, record)
    await coordinator.async_note_write()

    return {"id": record["id"]}


@_service_guard("add_settlement")
async def _handle_add_settlement(call: ServiceCall) -> dict[str, Any]:
    data = ADD_SETTLEMENT_SCHEMA(dict(call.data))
    storage, coordinator, participants, home_currency, _ = _get_entry_data(call.hass)
    caller = _resolve_caller(call, participants)

    currency = data.get("currency", home_currency)
    date_str = data["date"].isoformat()
    fx_rate, fx_date_str = await _resolve_fx(
        _get_fx_client(call.hass),
        currency=currency,
        home_currency=home_currency,
        date=date_str,
        explicit_rate=data.get("fx_rate"),
        explicit_fx_date=data.get("fx_date"),
    )

    record = build_settlement_record(
        date=date_str,
        from_user=data["from_user"],
        to_user=data["to_user"],
        amount=data["amount"],
        currency=currency,
        home_currency=home_currency,
        notes=data.get("notes"),
        created_by=caller,
        fx_rate=fx_rate,
        fx_date=fx_date_str,
    )

    try:
        validate_settlement_record(
            record,
            participants=set(participants),
            home_currency=home_currency,
        )
    except SplitsmartValidationError as err:
        raise ServiceValidationError(str(err)) from err

    await storage.append(storage.settlements_path, record)
    await coordinator.async_note_write()

    return {"id": record["id"]}


@_service_guard("edit_expense")
async def _handle_edit_expense(call: ServiceCall) -> dict[str, Any]:
    data = EDIT_EXPENSE_SCHEMA(dict(call.data))
    storage, coordinator, participants, home_currency, known_cats = _get_entry_data(call.hass)
    caller = _resolve_caller(call, participants)

    target_id = data["id"]
    existing = next(
        (
            e
            for e in (coordinator.data.expenses if coordinator.data else [])
            if e["id"] == target_id
        ),
        None,
    )
    if existing is None:
        raise ServiceValidationError(f"Expense '{target_id}' not found")

    currency = data.get("currency", home_currency)
    date_str = data["date"].isoformat()
    fx_rate, fx_date_str = await _resolve_fx(
        _get_fx_client(call.hass),
        currency=currency,
        home_currency=home_currency,
        date=date_str,
        explicit_rate=data.get("fx_rate"),
        explicit_fx_date=data.get("fx_date"),
    )

    total_home = (Decimal(str(data["amount"])) * fx_rate).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    new_record = build_expense_record(
        date=date_str,
        description=data["description"],
        paid_by=data["paid_by"],
        amount=data["amount"],
        currency=currency,
        home_currency=home_currency,
        categories=rescale_categories(data["categories"], fx_rate, total_home),
        notes=data.get("notes"),
        source=existing.get("source", "manual"),
        staging_id=existing.get("staging_id"),
        # receipt_path is the single exception to the "complete replacement, not a patch" rule —
        # when omitted by the caller, the existing value is preserved. This saves callers from
        # having to re-send the receipt path for trivial edits.
        receipt_path=data.get("receipt_path", existing.get("receipt_path")),
        created_by=caller,
        fx_rate=fx_rate,
        fx_date=fx_date_str,
    )

    try:
        validate_expense_record(
            new_record,
            participants=set(participants),
            home_currency=home_currency,
            known_categories=known_cats,
        )
    except SplitsmartValidationError as err:
        raise ServiceValidationError(str(err)) from err

    # New record first, then tombstone (amendment 5)
    await storage.append(storage.expenses_path, new_record)
    await storage.append_tombstone(
        created_by=caller,
        target_type=TARGET_EXPENSE,
        target_id=target_id,
        operation=TOMBSTONE_EDIT,
        previous_snapshot=existing,
        reason=data.get("reason"),
    )
    await coordinator.async_note_write()

    return {"id": new_record["id"]}


@_service_guard("delete_expense")
async def _handle_delete_expense(call: ServiceCall) -> dict[str, Any]:
    data = DELETE_EXPENSE_SCHEMA(dict(call.data))
    storage, coordinator, participants, _, _ = _get_entry_data(call.hass)
    caller = _resolve_caller(call, participants)

    target_id = data["id"]
    existing = next(
        (
            e
            for e in (coordinator.data.expenses if coordinator.data else [])
            if e["id"] == target_id
        ),
        None,
    )
    if existing is None:
        raise ServiceValidationError(f"Expense '{target_id}' not found")

    await storage.append_tombstone(
        created_by=caller,
        target_type=TARGET_EXPENSE,
        target_id=target_id,
        operation=TOMBSTONE_DELETE,
        previous_snapshot=existing,
        reason=data.get("reason"),
    )
    await coordinator.async_note_write()

    return {"id": target_id}


@_service_guard("edit_settlement")
async def _handle_edit_settlement(call: ServiceCall) -> dict[str, Any]:
    data = EDIT_SETTLEMENT_SCHEMA(dict(call.data))
    storage, coordinator, participants, home_currency, _ = _get_entry_data(call.hass)
    caller = _resolve_caller(call, participants)

    target_id = data["id"]
    existing = next(
        (
            s
            for s in (coordinator.data.settlements if coordinator.data else [])
            if s["id"] == target_id
        ),
        None,
    )
    if existing is None:
        raise ServiceValidationError(f"Settlement '{target_id}' not found")

    currency = data.get("currency", home_currency)
    date_str = data["date"].isoformat()
    fx_rate, fx_date_str = await _resolve_fx(
        _get_fx_client(call.hass),
        currency=currency,
        home_currency=home_currency,
        date=date_str,
        explicit_rate=data.get("fx_rate"),
        explicit_fx_date=data.get("fx_date"),
    )

    new_record = build_settlement_record(
        date=date_str,
        from_user=data["from_user"],
        to_user=data["to_user"],
        amount=data["amount"],
        currency=currency,
        home_currency=home_currency,
        notes=data.get("notes"),
        created_by=caller,
        fx_rate=fx_rate,
        fx_date=fx_date_str,
    )

    try:
        validate_settlement_record(
            new_record,
            participants=set(participants),
            home_currency=home_currency,
        )
    except SplitsmartValidationError as err:
        raise ServiceValidationError(str(err)) from err

    # New record first, then tombstone (amendment 5)
    await storage.append(storage.settlements_path, new_record)
    await storage.append_tombstone(
        created_by=caller,
        target_type=TARGET_SETTLEMENT,
        target_id=target_id,
        operation=TOMBSTONE_EDIT,
        previous_snapshot=existing,
        reason=data.get("reason"),
    )
    await coordinator.async_note_write()

    return {"id": new_record["id"]}


@_service_guard("delete_settlement")
async def _handle_delete_settlement(call: ServiceCall) -> dict[str, Any]:
    data = DELETE_SETTLEMENT_SCHEMA(dict(call.data))
    storage, coordinator, participants, _, _ = _get_entry_data(call.hass)
    caller = _resolve_caller(call, participants)

    target_id = data["id"]
    existing = next(
        (
            s
            for s in (coordinator.data.settlements if coordinator.data else [])
            if s["id"] == target_id
        ),
        None,
    )
    if existing is None:
        raise ServiceValidationError(f"Settlement '{target_id}' not found")

    await storage.append_tombstone(
        created_by=caller,
        target_type=TARGET_SETTLEMENT,
        target_id=target_id,
        operation=TOMBSTONE_DELETE,
        previous_snapshot=existing,
        reason=data.get("reason"),
    )
    await coordinator.async_note_write()

    return {"id": target_id}


# ---- M3 staging handlers ----


@_service_guard("promote_staging")
async def _handle_promote_staging(call: ServiceCall) -> dict[str, Any]:
    data = PROMOTE_STAGING_SCHEMA(dict(call.data))
    storage, coordinator, participants, home_currency, known_cats = _get_entry_data(call.hass)
    caller = _resolve_caller(call, participants)

    staging_id: str = data["staging_id"]
    staging_row = _find_live_staging_row(coordinator, staging_id, caller)

    description: str = data.get("override_description") or staging_row["description"]
    date_value = data.get("override_date")
    date_str: str = date_value.isoformat() if date_value else staging_row["date"]

    # paid_by is free-form (subject to participant validation) — the uploader
    # and the payer are not necessarily the same person, e.g. Chris imports
    # the joint-account statement but some rows Slav actually paid for.
    if data["paid_by"] not in participants:
        raise ServiceValidationError(
            f"'paid_by' user {data['paid_by']!r} is not a configured participant"
        )

    currency = staging_row["currency"]
    fx_rate, fx_date_str = await _resolve_fx(
        _get_fx_client(call.hass),
        currency=currency,
        home_currency=home_currency,
        date=date_str,
        explicit_rate=data.get("fx_rate"),
        explicit_fx_date=data.get("fx_date"),
    )

    source_amount = float(staging_row["amount"])
    total_home = (Decimal(str(source_amount)) * fx_rate).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    new_expense = build_expense_record(
        date=date_str,
        description=description,
        paid_by=data["paid_by"],
        amount=source_amount,
        currency=currency,
        home_currency=home_currency,
        categories=rescale_categories(data["categories"], fx_rate, total_home),
        notes=data.get("notes"),
        source=SOURCE_STAGING,
        staging_id=staging_id,
        receipt_path=data.get("receipt_path", staging_row.get("receipt_path")),
        created_by=caller,
        fx_rate=fx_rate,
        fx_date=fx_date_str,
    )

    try:
        validate_expense_record(
            new_expense,
            participants=set(participants),
            home_currency=home_currency,
            known_categories=known_cats,
        )
    except SplitsmartValidationError as err:
        raise ServiceValidationError(str(err)) from err

    # New expense first, then tombstone — on crash between the two we get an
    # extra live expense (safer failure mode) rather than an orphaned staging
    # row with no corresponding shared record.
    await storage.append(storage.expenses_path, new_expense)
    # replacement_id lets dedup and future audit tooling walk from tombstone
    # to the promoted expense without re-scanning the expenses log.
    await storage.append_tombstone(
        created_by=caller,
        target_type=TARGET_STAGING,
        target_id=staging_id,
        operation=TOMBSTONE_PROMOTE,
        previous_snapshot=staging_row,
        reason=data.get("reason"),
        replacement_id=new_expense["id"],
    )
    await coordinator.async_note_write(staging_user_id=caller)

    return {"expense_id": new_expense["id"], "staging_id": staging_id}


@_service_guard("skip_staging")
async def _handle_skip_staging(call: ServiceCall) -> dict[str, Any]:
    data = SKIP_STAGING_SCHEMA(dict(call.data))
    storage, coordinator, participants, _, _ = _get_entry_data(call.hass)
    caller = _resolve_caller(call, participants)

    staging_id: str = data["staging_id"]
    staging_row = _find_live_staging_row(coordinator, staging_id, caller)

    # previous_snapshot must carry the full staging row including dedup_hash —
    # dedup relies on the hash travelling on the tombstone so re-imports of
    # the same file are skipped rather than silently resurrecting the row.
    await storage.append_tombstone(
        created_by=caller,
        target_type=TARGET_STAGING,
        target_id=staging_id,
        operation=TOMBSTONE_DISCARD,
        previous_snapshot=staging_row,
        reason=data.get("reason"),
    )
    await coordinator.async_note_write(staging_user_id=caller)

    return {"staging_id": staging_id}


# ---- M3 import_file ----


def _collect_discard_tombstones_for_user(
    tombstones: list[dict[str, Any]], user_id: str
) -> list[dict[str, Any]]:
    """Filter the shared tombstones log to staging-discard tombstones that
    target rows this user uploaded. Per M3_PLAN §4, promote tombstones are
    NOT included: the resulting shared expense is already counted in
    dedup's existing_shared bucket, and double-counting would block
    legitimate re-occurrences."""
    out: list[dict[str, Any]] = []
    for tb in tombstones:
        if tb.get("target_type") != TARGET_STAGING:
            continue
        if tb.get("operation") != TOMBSTONE_DISCARD:
            continue
        snapshot = tb.get("previous_snapshot") or {}
        if snapshot.get("uploaded_by") == user_id:
            out.append(tb)
    return out


def _find_upload_path(storage: Any, upload_id: str) -> Any:
    """Resolve upload_id to the file on disk; raises if no match.
    Searches for any file ``<upload_id>.<ext>`` under uploads/ — the
    endpoint stores files by uuid4 and we don't require the caller to
    remember the extension."""
    uploads_dir = storage.uploads_dir
    if uploads_dir.exists():
        for candidate in uploads_dir.iterdir():
            if candidate.stem == upload_id and candidate.is_file():
                return candidate
    raise ServiceValidationError(
        f"Upload '{upload_id}' not found under /config/splitsmart/uploads/. "
        "POST to /api/splitsmart/upload first, or check the upload hasn't been "
        "purged by the daily cleanup task."
    )


async def _try_auto_promote(
    storage: Any,
    staging_row: dict[str, Any],
    *,
    match: Any,
    caller: str,
    home_currency: str,
    fx_client: FxClient,
    named_splits: dict[str, Any],
    participants: list[str],
    known_cats: set[str],
) -> bool:
    """Attempt an auto-promote for an always_split rule match.

    Returns True if the expense was written; False on FX or validation failure.
    Staging row must already be on disk before this is called.
    """
    currency = staging_row["currency"]
    try:
        fx_rate, fx_date_str = await _resolve_fx(
            fx_client,
            currency=currency,
            home_currency=home_currency,
            date=staging_row["date"],
            explicit_rate=None,
            explicit_fx_date=None,
        )
    except ServiceValidationError as err:
        _LOGGER.warning(
            "Auto-promote staging %s deferred: FX unavailable (%s)",
            staging_row["id"],
            err,
        )
        return False

    source_amount = float(staging_row["amount"])
    total_home = (Decimal(str(source_amount)) * fx_rate).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

    try:
        payload = build_match_payload(
            match,
            home_currency=home_currency,
            expense_amount=total_home,
            named_splits=named_splits,
        )
    except RuleParseError as err:
        _LOGGER.warning(
            "Auto-promote staging %s deferred: rule payload error (%s)",
            staging_row["id"],
            err,
        )
        return False

    if payload is None:
        return False  # non-split action — caller shouldn't reach here

    new_expense = build_expense_record(
        date=staging_row["date"],
        description=staging_row["description"],
        paid_by=caller,
        amount=source_amount,
        currency=currency,
        home_currency=home_currency,
        categories=rescale_categories(payload["categories"], fx_rate, total_home),
        notes=staging_row.get("notes"),
        source=SOURCE_STAGING,
        staging_id=staging_row["id"],
        receipt_path=staging_row.get("receipt_path"),
        created_by=caller,
        fx_rate=fx_rate,
        fx_date=fx_date_str,
    )

    try:
        validate_expense_record(
            new_expense,
            participants=set(participants),
            home_currency=home_currency,
            known_categories=known_cats,
        )
    except SplitsmartValidationError as err:
        _LOGGER.warning(
            "Auto-promote staging %s deferred: validation failed (%s)",
            staging_row["id"],
            err,
        )
        return False

    await storage.append(storage.expenses_path, new_expense)
    await storage.append_tombstone(
        created_by=caller,
        target_type=TARGET_STAGING,
        target_id=staging_row["id"],
        operation=TOMBSTONE_PROMOTE,
        previous_snapshot=staging_row,
        replacement_id=new_expense["id"],
    )
    return True


@_service_guard("import_file")
async def _handle_import_file(call: ServiceCall) -> dict[str, Any]:
    from .importer import inspect_file

    data = IMPORT_FILE_SCHEMA(dict(call.data))
    storage, coordinator, participants, home_currency, known_cats = _get_entry_data(call.hass)
    caller = _resolve_caller(call, participants)

    upload_id: str = data["upload_id"]
    path = _find_upload_path(storage, upload_id)
    user_mapping: Mapping | None = data.get("mapping")

    # One inspection pass: preset match for the source_preset field, origin
    # hash for mapping persistence. inspect is cheap (header row only).
    # Fixed-schema parsers (OFX/QIF) return empty headers and preset=None.
    inspection = await inspect_file(path, storage=storage)
    preset_name = inspection.get("preset")

    # Parse through the facade; the cascade handles
    # explicit user_mapping > preset > saved-by-hash > raise(mapping_required).
    try:
        outcome = await parse_file(path, user_mapping=user_mapping, storage=storage)
    except ImporterError as err:
        # Surface the structured code so Developer Tools users can see the
        # inspection payload (attached to err.inspection) and fix the mapping.
        raise ServiceValidationError(f"{err.code}: {err}") from err

    # Dedup against caller's private staging + the shared ledger +
    # caller's discard tombstones. Promote tombstones are intentionally
    # not included — the resulting shared expense covers them.
    existing_staging = coordinator.data.staging_by_user.get(caller, [])
    existing_shared = coordinator.data.expenses
    discard_tombstones = _collect_discard_tombstones_for_user(coordinator.data.tombstones, caller)
    to_import, to_skip = partition_by_dedup(
        outcome.rows,
        existing_staging=existing_staging,
        existing_shared=existing_shared,
        skipped_staging_tombstones=discard_tombstones,
    )

    uploaded_at = datetime.now(tz=UTC).astimezone().isoformat()
    staging_path = storage.staging_path(caller)
    blocked_foreign_currency = 0
    extension = path.suffix.lstrip(".").lower()
    fx_client = _get_fx_client(call.hass)
    rules = coordinator.rules
    named_splits = coordinator.named_splits

    # Rule evaluation counters.
    auto_promoted = 0
    auto_ignored = 0
    auto_review = 0
    still_pending = 0

    for row in to_import:
        currency = row["currency"]
        row_match = evaluate(
            {"description": row["description"], "amount": row["amount"], "currency": currency},
            rules,
        )
        rule_id: str | None = row_match.rule.id if row_match else None
        rule_action: str = row_match.rule.action if row_match else "pending"
        category_hint: str | None = (
            row_match.rule.category
            if row_match and row_match.rule.action == "review_each_time"
            else row.get("category_hint")
        )

        record: dict[str, Any] = {
            "id": new_id("st"),
            "uploaded_by": caller,
            "uploaded_at": uploaded_at,
            "source": extension,
            "source_ref": path.name,
            "source_ref_upload_id": upload_id,
            "source_preset": preset_name,
            "date": row["date"],
            "description": row["description"],
            "amount": round(float(row["amount"]), 2),
            "currency": currency,
            "rule_action": rule_action,
            "rule_id": rule_id,
            "category_hint": category_hint,
            "dedup_hash": dedup_hash(
                date=row["date"],
                amount=float(row["amount"]),
                currency=currency,
                description=row["description"],
            ),
            "receipt_path": None,
            "notes": row.get("notes"),
        }
        await storage.append(staging_path, record)
        if currency != home_currency:
            blocked_foreign_currency += 1

        # Apply rule action after staging write — staging row is the audit trail.
        if rule_action == "always_split" and row_match is not None:
            promoted = await _try_auto_promote(
                storage,
                record,
                match=row_match,
                caller=caller,
                home_currency=home_currency,
                fx_client=fx_client,
                named_splits=named_splits,
                participants=participants,
                known_cats=known_cats,
            )
            if promoted:
                auto_promoted += 1
            else:
                still_pending += 1
        elif rule_action == "always_ignore" and row_match is not None:
            await storage.append_tombstone(
                created_by=caller,
                target_type=TARGET_STAGING,
                target_id=record["id"],
                operation=TOMBSTONE_DISCARD,
                previous_snapshot=record,
            )
            auto_ignored += 1
        elif rule_action == "review_each_time":
            auto_review += 1
        else:
            still_pending += 1

    # Persist the user's mapping for next-month frictionless re-import. Only
    # when the caller supplied an explicit mapping — preset matches don't
    # need persistence, and saved-by-hash matches are already persisted.
    # Inspection headers are empty for OFX/QIF so the save is skipped there.
    if user_mapping is not None and data.get("remember_mapping", True) and inspection["headers"]:
        await save_mapping(storage, inspection["file_origin_hash"], user_mapping)

    # One coordinator refresh, scoped to this user's staging. Skip the
    # refresh entirely if nothing imported (pure-dedup run, or all-errors run).
    if to_import:
        await coordinator.async_note_write(staging_user_id=caller)

    response: dict[str, Any] = {
        "upload_id": upload_id,
        "imported": len(to_import),
        "skipped_as_duplicate": len(to_skip),
        "parse_errors": len(outcome.errors),
        "blocked_foreign_currency": blocked_foreign_currency,
        "preset": preset_name,
        "auto_promoted": auto_promoted,
        "auto_ignored": auto_ignored,
        "auto_review": auto_review,
        "still_pending": still_pending,
    }
    if outcome.errors:
        response["first_error_hint"] = outcome.errors[0].message
    return response


# ------------------------------------------------------------------ materialise_recurring


MATERIALISE_RECURRING_SCHEMA = vol.Schema(
    {
        vol.Optional("recurring_id"): vol.All(str, vol.Length(min=1)),
    }
)


@_service_guard("materialise_recurring")
async def _handle_materialise_recurring(call: ServiceCall) -> dict[str, Any]:
    """Run recurring materialisation on demand, optionally for a single entry."""
    from .recurring import load_recurring, load_recurring_state, materialise_recurring

    data = MATERIALISE_RECURRING_SCHEMA(dict(call.data))
    filter_id: str | None = data.get("recurring_id")

    storage, coordinator, participants, home_currency, known_categories = _get_entry_data(call.hass)
    fx_client = _get_fx_client(call.hass)

    recurring_entries = await load_recurring(
        storage.recurring_yaml_path,
        participants=list(participants),
    )

    if filter_id is not None:
        ids = {e.id for e in recurring_entries}
        if filter_id not in ids:
            raise ServiceValidationError(
                f"No recurring entry with id '{filter_id}' found in recurring.yaml"
            )

    state = await load_recurring_state(storage.recurring_state_path)
    existing_expenses = await storage.read_all(storage.expenses_path)

    result = await materialise_recurring(
        entries=recurring_entries,
        state=state,
        existing_expenses=existing_expenses,
        fx_client=fx_client,
        home_currency=home_currency,
        participants=set(participants),
        known_categories=known_categories,
        storage=storage,
        filter_id=filter_id,
    )

    if result.materialised:
        await coordinator.async_refresh()

    return {
        "materialised": result.materialised,
        "skipped_fx_failure": result.skipped_fx_failure,
        "skipped_duplicate": result.skipped_duplicate,
    }


# ------------------------------------------------------------------ registration


# ---- M5 apply_rules ----

APPLY_RULES_SCHEMA = vol.Schema(
    {
        vol.Optional("user_id"): vol.Any(None, cv.string),
    }
)


@_service_guard("apply_rules")
async def _handle_apply_rules(call: ServiceCall) -> dict[str, Any]:
    """Re-run rule evaluation against pending staging rows for the caller."""
    data = APPLY_RULES_SCHEMA(dict(call.data))
    storage, coordinator, participants, home_currency, known_cats = _get_entry_data(call.hass)
    caller = _resolve_caller(call, participants)

    # Admins may target another participant; non-admins must target themselves.
    target_user: str = data.get("user_id") or caller
    if target_user != caller:
        user = await call.hass.auth.async_get_user(caller)
        if user is None or not user.is_admin:
            raise ServiceValidationError("permission_denied")

    rules = coordinator.rules
    named_splits = coordinator.named_splits
    fx_client = _get_fx_client(call.hass)

    staging_rows = coordinator.data.staging_by_user.get(target_user, [])
    staging_path = storage.staging_path(target_user)

    auto_promoted = 0
    auto_ignored = 0
    auto_review = 0
    still_pending = 0

    for old_row in staging_rows:
        rule_action = old_row.get("rule_action", "pending")
        existing_rule_id = old_row.get("rule_id")

        if rule_action == "always_split" and existing_rule_id:
            # FX-retry path: rule already matched but FX was unavailable.
            rule = next((r for r in rules if r.id == existing_rule_id), None)
            if rule is None:
                _LOGGER.warning(
                    "apply_rules: staging %s has rule_id %s which no longer exists — left pending",
                    old_row["id"],
                    existing_rule_id,
                )
                still_pending += 1
                continue
            from .rules import RuleMatch

            match = RuleMatch(rule=rule)
            promoted = await _try_auto_promote(
                storage,
                old_row,
                match=match,
                caller=target_user,
                home_currency=home_currency,
                fx_client=fx_client,
                named_splits=named_splits,
                participants=participants,
                known_cats=known_cats,
            )
            if promoted:
                auto_promoted += 1
            else:
                still_pending += 1
            continue

        if rule_action != "pending":
            # review_each_time, or already-ignored rows — not a target for re-evaluation.
            continue

        # First-time evaluation: evaluate rules and apply edit-tombstone pattern.
        match = evaluate(
            {
                "description": old_row.get("description", ""),
                "amount": old_row.get("amount"),
                "currency": old_row.get("currency", ""),
            },
            rules,
        )
        if match is None:
            still_pending += 1
            continue

        # Append new staging row with updated rule fields, then tombstone the old one.
        new_row: dict[str, Any] = {
            **old_row,
            "id": new_id("st"),
            "rule_id": match.rule.id,
            "rule_action": match.rule.action,
        }
        if match.rule.action == "review_each_time" and match.rule.category:
            new_row["category_hint"] = match.rule.category

        await storage.append(staging_path, new_row)
        await storage.append_tombstone(
            created_by=target_user,
            target_type=TARGET_STAGING,
            target_id=old_row["id"],
            operation=TOMBSTONE_EDIT,
            previous_snapshot=old_row,
            replacement_id=new_row["id"],
        )

        if match.rule.action == "always_split":
            promoted = await _try_auto_promote(
                storage,
                new_row,
                match=match,
                caller=target_user,
                home_currency=home_currency,
                fx_client=fx_client,
                named_splits=named_splits,
                participants=participants,
                known_cats=known_cats,
            )
            if promoted:
                auto_promoted += 1
            else:
                still_pending += 1
        elif match.rule.action == "always_ignore":
            await storage.append_tombstone(
                created_by=target_user,
                target_type=TARGET_STAGING,
                target_id=new_row["id"],
                operation=TOMBSTONE_DISCARD,
                previous_snapshot=new_row,
            )
            auto_ignored += 1
        elif match.rule.action == "review_each_time":
            auto_review += 1

    if auto_promoted + auto_ignored + auto_review > 0:
        await coordinator.async_note_write(staging_user_id=target_user)

    return {
        "auto_promoted": auto_promoted,
        "auto_ignored": auto_ignored,
        "auto_review": auto_review,
        "still_pending": still_pending,
    }


def async_register_services(hass: HomeAssistant) -> None:
    """Register all Splitsmart services. Called once when the first entry loads."""
    hass.services.async_register(
        DOMAIN,
        SERVICE_ADD_EXPENSE,
        _handle_add_expense,
        schema=None,  # schema validated inside handler for ServiceValidationError control
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_ADD_SETTLEMENT,
        _handle_add_settlement,
        schema=None,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_EDIT_EXPENSE,
        _handle_edit_expense,
        schema=None,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_EDIT_SETTLEMENT,
        _handle_edit_settlement,
        schema=None,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_DELETE_EXPENSE,
        _handle_delete_expense,
        schema=None,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_DELETE_SETTLEMENT,
        _handle_delete_settlement,
        schema=None,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_PROMOTE_STAGING,
        _handle_promote_staging,
        schema=None,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SKIP_STAGING,
        _handle_skip_staging,
        schema=None,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_IMPORT_FILE,
        _handle_import_file,
        schema=None,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_MATERIALISE_RECURRING,
        _handle_materialise_recurring,
        schema=None,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_APPLY_RULES,
        _handle_apply_rules,
        schema=None,
        supports_response=SupportsResponse.OPTIONAL,
    )
    _LOGGER.debug("Splitsmart services registered")


def async_unregister_services(hass: HomeAssistant) -> None:
    """Deregister all services when the last entry unloads."""
    for service in (
        SERVICE_ADD_EXPENSE,
        SERVICE_ADD_SETTLEMENT,
        SERVICE_EDIT_EXPENSE,
        SERVICE_EDIT_SETTLEMENT,
        SERVICE_DELETE_EXPENSE,
        SERVICE_DELETE_SETTLEMENT,
        SERVICE_PROMOTE_STAGING,
        SERVICE_SKIP_STAGING,
        SERVICE_IMPORT_FILE,
        SERVICE_MATERIALISE_RECURRING,
    ):
        hass.services.async_remove(DOMAIN, service)
    _LOGGER.debug("Splitsmart services deregistered")
