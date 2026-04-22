"""Service handlers for Splitsmart."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .const import (
    DOMAIN,
    SERVICE_ADD_EXPENSE,
    SERVICE_ADD_SETTLEMENT,
    SERVICE_DELETE_EXPENSE,
    SERVICE_DELETE_SETTLEMENT,
    SERVICE_EDIT_EXPENSE,
    SERVICE_EDIT_SETTLEMENT,
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
from .ledger import (
    SplitsmartValidationError,
    build_expense_record,
    build_settlement_record,
    validate_expense_record,
    validate_settlement_record,
)

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
    }
)

SKIP_STAGING_SCHEMA = vol.Schema(
    {
        vol.Required("staging_id"): cv.string,
        vol.Optional("reason"): vol.Any(None, cv.string),
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


def _guard_currency(currency: str, home_currency: str) -> None:
    """Reject foreign-currency entries until FX support lands in M4."""
    if currency != home_currency:
        raise ServiceValidationError(
            f"Foreign-currency entries ('{currency}') are not yet supported. "
            "Multi-currency support arrives in M4. Use the home currency "
            f"'{home_currency}' for now."
        )


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


# ------------------------------------------------------------------ handlers


async def _handle_add_expense(call: ServiceCall) -> dict[str, Any]:
    data = ADD_EXPENSE_SCHEMA(dict(call.data))
    storage, coordinator, participants, home_currency, known_cats = _get_entry_data(call.hass)
    caller = _resolve_caller(call, participants)

    currency = data.get("currency", home_currency)
    _guard_currency(currency, home_currency)

    date_str = data["date"].isoformat()
    record = build_expense_record(
        date=date_str,
        description=data["description"],
        paid_by=data["paid_by"],
        amount=data["amount"],
        currency=currency,
        home_currency=home_currency,
        categories=data["categories"],
        notes=data.get("notes"),
        source=data.get("source", "manual"),
        staging_id=data.get("staging_id"),
        receipt_path=data.get("receipt_path"),
        created_by=caller,
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


async def _handle_add_settlement(call: ServiceCall) -> dict[str, Any]:
    data = ADD_SETTLEMENT_SCHEMA(dict(call.data))
    storage, coordinator, participants, home_currency, _ = _get_entry_data(call.hass)
    caller = _resolve_caller(call, participants)

    currency = data.get("currency", home_currency)
    _guard_currency(currency, home_currency)

    date_str = data["date"].isoformat()
    record = build_settlement_record(
        date=date_str,
        from_user=data["from_user"],
        to_user=data["to_user"],
        amount=data["amount"],
        currency=currency,
        home_currency=home_currency,
        notes=data.get("notes"),
        created_by=caller,
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
    _guard_currency(currency, home_currency)

    date_str = data["date"].isoformat()
    new_record = build_expense_record(
        date=date_str,
        description=data["description"],
        paid_by=data["paid_by"],
        amount=data["amount"],
        currency=currency,
        home_currency=home_currency,
        categories=data["categories"],
        notes=data.get("notes"),
        source=existing.get("source", "manual"),
        staging_id=existing.get("staging_id"),
        # receipt_path is the single exception to the "complete replacement, not a patch" rule —
        # when omitted by the caller, the existing value is preserved. This saves callers from
        # having to re-send the receipt path for trivial edits.
        receipt_path=data.get("receipt_path", existing.get("receipt_path")),
        created_by=caller,
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
    _guard_currency(currency, home_currency)

    date_str = data["date"].isoformat()
    new_record = build_settlement_record(
        date=date_str,
        from_user=data["from_user"],
        to_user=data["to_user"],
        amount=data["amount"],
        currency=currency,
        home_currency=home_currency,
        notes=data.get("notes"),
        created_by=caller,
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


async def _handle_promote_staging(call: ServiceCall) -> dict[str, Any]:
    data = PROMOTE_STAGING_SCHEMA(dict(call.data))
    storage, coordinator, participants, home_currency, known_cats = _get_entry_data(call.hass)
    caller = _resolve_caller(call, participants)

    staging_id: str = data["staging_id"]
    staging_row = _find_live_staging_row(coordinator, staging_id, caller)

    # O4 foreign-currency guard: surface the user-facing message verbatim
    # per M3_PLAN §8. The staging row stays live — the user retries once
    # FX support ships in M4.
    if staging_row["currency"] != home_currency:
        raise ServiceValidationError("Foreign currency promotion arrives in M4. Row stays staged.")

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

    new_expense = build_expense_record(
        date=date_str,
        description=description,
        paid_by=data["paid_by"],
        amount=float(staging_row["amount"]),
        currency=staging_row["currency"],
        home_currency=home_currency,
        categories=data["categories"],
        notes=data.get("notes"),
        source=SOURCE_STAGING,
        staging_id=staging_id,
        receipt_path=data.get("receipt_path", staging_row.get("receipt_path")),
        created_by=caller,
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


# ------------------------------------------------------------------ registration


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
    ):
        hass.services.async_remove(DOMAIN, service)
    _LOGGER.debug("Splitsmart services deregistered")
