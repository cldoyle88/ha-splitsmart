"""Splitsmart websocket API.

Three commands (M2):

- ``splitsmart/get_config``: one-shot. Returns participants (with active
  flag), home currency, categories, named splits, current user id.
- ``splitsmart/list_expenses``: one-shot. Returns the materialised expense
  list plus settlements, with optional ``month`` / ``category`` / ``paid_by``
  filters.
- ``splitsmart/list_expenses/subscribe``: long-lived subscription. Initial
  snapshot then delta events on every coordinator write.

Every response includes ``version: 1`` so the contract can evolve without
silently breaking older cards. Non-participant callers get ``permission_denied``.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from .const import (
    CONF_CATEGORIES,
    CONF_HOME_CURRENCY,
    CONF_NAMED_SPLITS,
    CONF_PARTICIPANTS,
    DOMAIN,
)
from .coordinator import SplitsmartCoordinator

_LOGGER = logging.getLogger(__name__)

API_VERSION = 1


# --------------------------------------------------------------------- helpers


def _resolve_entry(hass: HomeAssistant) -> tuple[Any, SplitsmartCoordinator] | None:
    """Return (entry, coordinator) for the single configured Splitsmart entry.

    The config flow is single-instance-guarded, so we take the first (and
    only) entry. Returns ``None`` if the integration is not loaded.
    """
    store = hass.data.get(DOMAIN)
    if not store:
        return None
    for key, value in store.items():
        if key.startswith("_"):
            continue
        if isinstance(value, dict) and "coordinator" in value:
            return value["entry"], value["coordinator"]
    return None


def _historical_user_ids(
    expenses: list[dict[str, Any]], settlements: list[dict[str, Any]]
) -> set[str]:
    """Every user id that appears in historical data."""
    seen: set[str] = set()
    for exp in expenses:
        if exp.get("paid_by"):
            seen.add(exp["paid_by"])
        for alloc in exp.get("categories", []):
            for share in alloc.get("split", {}).get("shares", []):
                if share.get("user_id"):
                    seen.add(share["user_id"])
    for sl in settlements:
        if sl.get("from_user"):
            seen.add(sl["from_user"])
        if sl.get("to_user"):
            seen.add(sl["to_user"])
    return seen


async def _build_participants_payload(
    hass: HomeAssistant,
    configured_ids: list[str],
    historical_ids: set[str],
) -> list[dict[str, Any]]:
    """Return ``[{user_id, display_name, active}]`` including both configured
    and historical participants. ``active=False`` marks users removed via
    Reconfigure but still referenced by historical rows."""
    all_ids = list(configured_ids) + [uid for uid in historical_ids if uid not in configured_ids]
    out: list[dict[str, Any]] = []
    for uid in all_ids:
        user = await hass.auth.async_get_user(uid)
        display_name = user.name if user is not None else uid
        out.append(
            {
                "user_id": uid,
                "display_name": display_name,
                "active": uid in configured_ids,
            }
        )
    return out


def _filter_expenses(
    expenses: list[dict[str, Any]],
    *,
    month: str | None,
    category: str | None,
    paid_by: str | None,
) -> list[dict[str, Any]]:
    """Apply optional filters. ``month`` = ``YYYY-MM``, matches by date prefix."""
    out = expenses
    if month:
        out = [e for e in out if str(e.get("date", "")).startswith(month)]
    if category:
        out = [
            e
            for e in out
            if any(alloc.get("name") == category for alloc in e.get("categories", []))
        ]
    if paid_by:
        out = [e for e in out if e.get("paid_by") == paid_by]
    return out


def _permission_denied(connection: Any, msg_id: int) -> None:
    connection.send_error(msg_id, "permission_denied", "Caller is not a Splitsmart participant.")


def _not_found(connection: Any, msg_id: int) -> None:
    connection.send_error(msg_id, "not_found", "Splitsmart integration is not loaded.")


# --------------------------------------------------------------------- handlers


async def _handle_get_config(hass: HomeAssistant, connection: Any, msg: dict[str, Any]) -> None:
    resolved = _resolve_entry(hass)
    if resolved is None:
        _not_found(connection, msg["id"])
        return
    entry, coordinator = resolved

    caller_id = connection.user.id
    configured = list(entry.data[CONF_PARTICIPANTS])
    if caller_id not in configured:
        _permission_denied(connection, msg["id"])
        return

    data = coordinator.data
    expenses = data.expenses if data is not None else []
    settlements = data.settlements if data is not None else []
    historical = _historical_user_ids(expenses, settlements)
    participants = await _build_participants_payload(hass, configured, historical)

    home_currency = entry.options.get(CONF_HOME_CURRENCY, entry.data[CONF_HOME_CURRENCY])
    categories = entry.options.get(CONF_CATEGORIES, entry.data[CONF_CATEGORIES])
    named_splits = entry.options.get(CONF_NAMED_SPLITS, entry.data.get(CONF_NAMED_SPLITS, {}))

    connection.send_result(
        msg["id"],
        {
            "version": API_VERSION,
            "participants": participants,
            "home_currency": home_currency,
            "categories": list(categories),
            "named_splits": dict(named_splits),
            "current_user_id": caller_id,
        },
    )


async def _handle_list_expenses(hass: HomeAssistant, connection: Any, msg: dict[str, Any]) -> None:
    resolved = _resolve_entry(hass)
    if resolved is None:
        _not_found(connection, msg["id"])
        return
    entry, coordinator = resolved

    caller_id = connection.user.id
    if caller_id not in entry.data[CONF_PARTICIPANTS]:
        _permission_denied(connection, msg["id"])
        return

    data = coordinator.data
    expenses = data.expenses if data is not None else []
    settlements = data.settlements if data is not None else []

    filtered = _filter_expenses(
        expenses,
        month=msg.get("month"),
        category=msg.get("category"),
        paid_by=msg.get("paid_by"),
    )

    connection.send_result(
        msg["id"],
        {
            "version": API_VERSION,
            "expenses": filtered,
            "settlements": settlements,
            "total": len(filtered),
        },
    )


async def _handle_subscribe(hass: HomeAssistant, connection: Any, msg: dict[str, Any]) -> None:
    resolved = _resolve_entry(hass)
    if resolved is None:
        _not_found(connection, msg["id"])
        return
    entry, coordinator = resolved

    caller_id = connection.user.id
    if caller_id not in entry.data[CONF_PARTICIPANTS]:
        _permission_denied(connection, msg["id"])
        return

    msg_id = msg["id"]

    def _snapshot() -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
        data = coordinator.data
        expenses = data.expenses if data is not None else []
        settlements = data.settlements if data is not None else []
        return (
            {e["id"]: e for e in expenses},
            {s["id"]: s for s in settlements},
        )

    prev_expenses, prev_settlements = _snapshot()

    connection.send_result(msg_id)
    connection.send_message(
        {
            "id": msg_id,
            "type": "event",
            "event": {
                "version": API_VERSION,
                "kind": "init",
                "expenses": list(prev_expenses.values()),
                "settlements": list(prev_settlements.values()),
            },
        }
    )

    @callback
    def _on_update() -> None:
        nonlocal prev_expenses, prev_settlements
        curr_expenses, curr_settlements = _snapshot()

        added: list[dict[str, Any]] = []
        updated: list[dict[str, Any]] = []
        deleted: list[str] = []

        for eid, exp in curr_expenses.items():
            if eid not in prev_expenses:
                added.append({"kind": "expense", "record": exp})
            elif prev_expenses[eid] != exp:
                updated.append({"kind": "expense", "record": exp})
        for eid in prev_expenses:
            if eid not in curr_expenses:
                deleted.append(eid)

        for sid, sl in curr_settlements.items():
            if sid not in prev_settlements:
                added.append({"kind": "settlement", "record": sl})
            elif prev_settlements[sid] != sl:
                updated.append({"kind": "settlement", "record": sl})
        for sid in prev_settlements:
            if sid not in curr_settlements:
                deleted.append(sid)

        prev_expenses, prev_settlements = curr_expenses, curr_settlements

        if not added and not updated and not deleted:
            return

        connection.send_message(
            {
                "id": msg_id,
                "type": "event",
                "event": {
                    "version": API_VERSION,
                    "kind": "delta",
                    "added": added,
                    "updated": updated,
                    "deleted": deleted,
                },
            }
        )

    unsubscribe = coordinator.async_add_listener(_on_update)
    connection.subscriptions[msg_id] = unsubscribe


# --------------------------------------------------------------------- registered handlers


@websocket_api.websocket_command(
    {
        vol.Required("type"): "splitsmart/get_config",
    }
)
@websocket_api.async_response
async def handle_get_config(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return the card's bootstrap config."""
    await _handle_get_config(hass, connection, msg)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "splitsmart/list_expenses",
        vol.Optional("month"): str,
        vol.Optional("category"): str,
        vol.Optional("paid_by"): str,
    }
)
@websocket_api.async_response
async def handle_list_expenses(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return the filtered expense list and all settlements."""
    await _handle_list_expenses(hass, connection, msg)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "splitsmart/list_expenses/subscribe",
    }
)
@websocket_api.async_response
async def handle_subscribe(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Subscribe to coordinator updates. Sends init, then delta events."""
    await _handle_subscribe(hass, connection, msg)


# --------------------------------------------------------------------- registration


def async_register_websocket_commands(hass: HomeAssistant) -> None:
    """Register the Splitsmart websocket commands once per HA instance."""
    flag = "_ws_registered"
    if hass.data.setdefault(DOMAIN, {}).get(flag):
        return

    websocket_api.async_register_command(hass, handle_get_config)
    websocket_api.async_register_command(hass, handle_list_expenses)
    websocket_api.async_register_command(hass, handle_subscribe)

    hass.data[DOMAIN][flag] = True
