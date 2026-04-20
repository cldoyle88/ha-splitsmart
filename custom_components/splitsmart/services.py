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
    SOURCES,
    SPLIT_METHODS,
    TARGET_EXPENSE,
    TARGET_SETTLEMENT,
    TOMBSTONE_DELETE,
    TOMBSTONE_EDIT,
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
    """Reject foreign-currency entries until M3 FX support lands."""
    if currency != home_currency:
        raise ServiceValidationError(
            f"Foreign-currency entries ('{currency}') are not yet supported. "
            "Multi-currency support arrives in M3. Use the home currency "
            f"'{home_currency}' for now."
        )


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
    ):
        hass.services.async_remove(DOMAIN, service)
    _LOGGER.debug("Splitsmart services deregistered")
