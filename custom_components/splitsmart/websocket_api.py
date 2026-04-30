"""Splitsmart websocket API.

M2 commands:

- ``splitsmart/get_config``: one-shot. Returns participants (with active
  flag), home currency, categories, named splits, current user id.
- ``splitsmart/list_expenses``: one-shot. Returns the materialised expense
  list plus settlements, with optional ``month`` / ``category`` / ``paid_by``
  filters.
- ``splitsmart/list_expenses/subscribe``: long-lived subscription. Initial
  snapshot then delta events on every coordinator write.

M3 commands:

- ``splitsmart/list_staging``: one-shot. Returns the caller's materialised
  staging rows plus the tombstones that affect them. Rejects requests
  scoped to another user — staging is private to the uploader (SPEC §7).
- ``splitsmart/list_staging/subscribe``: long-lived subscription scoped to
  the caller's staging.
- ``splitsmart/list_presets``: one-shot. Static preset registry dump.
- ``splitsmart/save_mapping``: one-shot. Persists a user-authored column
  mapping under its file-origin hash.
- ``splitsmart/inspect_upload``: one-shot. Re-runs inspect on a previously
  uploaded file, returning its ``FileInspection`` payload.

M5 commands:

- ``splitsmart/list_rules``: one-shot. Returns the in-memory rule list,
  ``loaded_at``, ``source_path``, and any load errors.
- ``splitsmart/list_rules/subscribe``: long-lived. Init payload then delta
  on file-watcher reload (coordinator calls ``async_update_listeners``).
- ``splitsmart/draft_rule_from_row``: one-shot. Privacy-checked against the
  caller's staging; returns a YAML snippet + draft Rule dict.
- ``splitsmart/reload_rules``: one-shot. Forces ``async_reload_rules`` and
  returns the new counts.

Every response includes ``version: 1`` so the contract can evolve without
silently breaking older cards. Non-participant callers get ``permission_denied``.
"""

from __future__ import annotations

import logging
import re
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


def _resolve_storage(hass: HomeAssistant) -> Any | None:
    """Return the storage handle for the single configured Splitsmart entry.

    Separate from _resolve_entry because most M2 commands don't need storage
    (they read only from the coordinator projection). M3 save_mapping and
    inspect_upload do — they write to / read from disk.
    """
    store = hass.data.get(DOMAIN)
    if not store:
        return None
    for key, value in store.items():
        if key.startswith("_"):
            continue
        if isinstance(value, dict) and "storage" in value:
            return value["storage"]
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


# --------------------------------------------------------------------- M3 handlers


def _staging_tombstones_for_user(
    tombstones: list[dict[str, Any]], user_id: str
) -> list[dict[str, Any]]:
    """Staging tombstones (both promote and discard) whose previous_snapshot
    was uploaded by ``user_id``. The review UI needs both so it can show
    what disappeared from the queue and why."""
    out: list[dict[str, Any]] = []
    for tb in tombstones:
        if tb.get("target_type") != "staging":
            continue
        snapshot = tb.get("previous_snapshot") or {}
        if snapshot.get("uploaded_by") == user_id:
            out.append(tb)
    return out


async def _handle_list_staging(hass: HomeAssistant, connection: Any, msg: dict[str, Any]) -> None:
    resolved = _resolve_entry(hass)
    if resolved is None:
        _not_found(connection, msg["id"])
        return
    entry, coordinator = resolved

    caller_id = connection.user.id
    if caller_id not in entry.data[CONF_PARTICIPANTS]:
        _permission_denied(connection, msg["id"])
        return

    # user_id defaults to the caller. An explicit user_id != caller means
    # the client is asking for another user's staging — SPEC §7 forbids it.
    target_user_id: str = msg.get("user_id") or caller_id
    if target_user_id != caller_id:
        _permission_denied(connection, msg["id"])
        return

    data = coordinator.data
    rows = data.staging_by_user.get(caller_id, []) if data is not None else []
    tombstones = (
        _staging_tombstones_for_user(data.tombstones, caller_id) if data is not None else []
    )

    connection.send_result(
        msg["id"],
        {
            "version": API_VERSION,
            "rows": rows,
            "tombstones": tombstones,
            "total": len(rows),
        },
    )


async def _handle_list_staging_subscribe(
    hass: HomeAssistant, connection: Any, msg: dict[str, Any]
) -> None:
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

    def _snapshot() -> dict[str, dict[str, Any]]:
        data = coordinator.data
        if data is None:
            return {}
        return {r["id"]: r for r in data.staging_by_user.get(caller_id, [])}

    prev_rows = _snapshot()

    connection.send_result(msg_id)
    connection.send_message(
        {
            "id": msg_id,
            "type": "event",
            "event": {
                "version": API_VERSION,
                "kind": "init",
                "rows": list(prev_rows.values()),
            },
        }
    )

    @callback
    def _on_update() -> None:
        nonlocal prev_rows
        curr_rows = _snapshot()

        added: list[dict[str, Any]] = []
        updated: list[dict[str, Any]] = []
        deleted: list[str] = []

        for rid, row in curr_rows.items():
            if rid not in prev_rows:
                added.append(row)
            elif prev_rows[rid] != row:
                updated.append(row)
        for rid in prev_rows:
            if rid not in curr_rows:
                deleted.append(rid)

        prev_rows = curr_rows

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


async def _handle_list_presets(hass: HomeAssistant, connection: Any, msg: dict[str, Any]) -> None:
    resolved = _resolve_entry(hass)
    if resolved is None:
        _not_found(connection, msg["id"])
        return
    entry, _ = resolved

    caller_id = connection.user.id
    if caller_id not in entry.data[CONF_PARTICIPANTS]:
        _permission_denied(connection, msg["id"])
        return

    from .importer.presets import PRESETS

    connection.send_result(
        msg["id"],
        {
            "version": API_VERSION,
            "presets": [{"name": p.name, "confidence": p.confidence} for p in PRESETS],
        },
    )


async def _handle_save_mapping(hass: HomeAssistant, connection: Any, msg: dict[str, Any]) -> None:
    resolved = _resolve_entry(hass)
    if resolved is None:
        _not_found(connection, msg["id"])
        return
    entry, _ = resolved

    caller_id = connection.user.id
    if caller_id not in entry.data[CONF_PARTICIPANTS]:
        _permission_denied(connection, msg["id"])
        return

    from .importer.mapping import save_mapping

    storage = _resolve_storage(hass)
    await save_mapping(storage, msg["file_origin_hash"], msg["mapping"])

    connection.send_result(
        msg["id"],
        {
            "version": API_VERSION,
            "file_origin_hash": msg["file_origin_hash"],
            "saved": True,
        },
    )


async def _handle_inspect_upload(hass: HomeAssistant, connection: Any, msg: dict[str, Any]) -> None:
    resolved = _resolve_entry(hass)
    if resolved is None:
        _not_found(connection, msg["id"])
        return
    entry, _ = resolved

    caller_id = connection.user.id
    if caller_id not in entry.data[CONF_PARTICIPANTS]:
        _permission_denied(connection, msg["id"])
        return

    from .importer import inspect_file

    storage = _resolve_storage(hass)
    upload_id: str = msg["upload_id"]

    # Re-use the same resolution logic as the import_file service handler.
    uploads_dir = storage.uploads_dir
    path = None
    if uploads_dir.exists():
        for candidate in uploads_dir.iterdir():
            if candidate.stem == upload_id and candidate.is_file():
                path = candidate
                break
    if path is None:
        connection.send_error(
            msg["id"],
            "not_found",
            f"Upload '{upload_id}' not found under /config/splitsmart/uploads/.",
        )
        return

    try:
        inspection = await inspect_file(path, storage=storage)
    except Exception as err:
        # Surface structured error to the caller; the only surprise here would
        # be a filesystem/encoding failure we haven't otherwise enumerated.
        connection.send_error(msg["id"], "inspect_failed", str(err))
        return

    connection.send_result(
        msg["id"],
        {
            "version": API_VERSION,
            "inspection": inspection,
        },
    )


# --------------------------------------------------------------------- M5 helpers


def _serialize_rule(rule: Any) -> dict[str, Any]:
    """Convert a Rule dataclass to a JSON-serialisable dict."""
    return {
        "id": rule.id,
        "description": rule.description,
        "pattern": rule.pattern.pattern,
        "currency_match": rule.currency_match,
        "amount_min": str(rule.amount_min) if rule.amount_min is not None else None,
        "amount_max": str(rule.amount_max) if rule.amount_max is not None else None,
        "action": rule.action,
        "category": rule.category,
        "split": rule.split,
        "priority": rule.priority,
    }


def _draft_regex(description: str) -> str:
    """Extract the longest alphabetic run from description as a regex literal."""
    runs = re.findall(r"[A-Za-z]+", description)
    if not runs:
        return re.escape(description.strip()) or ".*"
    return re.escape(max(runs, key=len))


def _build_yaml_snippet(
    *,
    description: str,
    action: str,
    pattern_str: str,
    category: str | None,
    split_preset: str | None,
) -> str:
    """Return a copy-pasteable YAML snippet for a new rule."""
    lines = [
        "rules:",
        f"  - id: r_{ULID_PLACEHOLDER}",
        f'    description: "Auto-generated from {description!r}"',
        f"    match: /{pattern_str}/i",
        f"    action: {action}",
    ]
    if category:
        lines.append(f"    category: {category}")
    if action == "always_split" and split_preset:
        lines.append("    split:")
        lines.append(f'      preset: "{split_preset}"')
    return "\n".join(lines)


# Placeholder string swapped out in the handler once we have an actual ULID.
ULID_PLACEHOLDER = "<unique-id>"


# --------------------------------------------------------------------- M5 handlers


async def _handle_list_rules(hass: HomeAssistant, connection: Any, msg: dict[str, Any]) -> None:
    resolved = _resolve_entry(hass)
    if resolved is None:
        _not_found(connection, msg["id"])
        return
    entry, coordinator = resolved

    caller_id = connection.user.id
    if caller_id not in entry.data[CONF_PARTICIPANTS]:
        _permission_denied(connection, msg["id"])
        return

    storage = _resolve_storage(hass)
    loaded_at = coordinator.rules_loaded_at.isoformat() if coordinator.rules_loaded_at else None

    connection.send_result(
        msg["id"],
        {
            "version": API_VERSION,
            "rules": [_serialize_rule(r) for r in coordinator.rules],
            "loaded_at": loaded_at,
            "source_path": str(storage.rules_yaml_path),
            "errors": list(coordinator.rules_errors),
        },
    )


async def _handle_list_rules_subscribe(
    hass: HomeAssistant, connection: Any, msg: dict[str, Any]
) -> None:
    resolved = _resolve_entry(hass)
    if resolved is None:
        _not_found(connection, msg["id"])
        return
    entry, coordinator = resolved

    caller_id = connection.user.id
    if caller_id not in entry.data[CONF_PARTICIPANTS]:
        _permission_denied(connection, msg["id"])
        return

    storage = _resolve_storage(hass)
    msg_id = msg["id"]

    def _current_loaded_at() -> str | None:
        return coordinator.rules_loaded_at.isoformat() if coordinator.rules_loaded_at else None

    prev_loaded_at = _current_loaded_at()

    connection.send_result(msg_id)
    connection.send_message(
        {
            "id": msg_id,
            "type": "event",
            "event": {
                "version": API_VERSION,
                "kind": "init",
                "rules": [_serialize_rule(r) for r in coordinator.rules],
                "loaded_at": prev_loaded_at,
                "source_path": str(storage.rules_yaml_path),
                "errors": list(coordinator.rules_errors),
            },
        }
    )

    @callback
    def _on_update() -> None:
        nonlocal prev_loaded_at
        curr_loaded_at = _current_loaded_at()
        if curr_loaded_at == prev_loaded_at:
            return
        prev_loaded_at = curr_loaded_at
        connection.send_message(
            {
                "id": msg_id,
                "type": "event",
                "event": {
                    "version": API_VERSION,
                    "kind": "reload",
                    "rules": [_serialize_rule(r) for r in coordinator.rules],
                    "loaded_at": curr_loaded_at,
                    "errors": list(coordinator.rules_errors),
                },
            }
        )

    unsubscribe = coordinator.async_add_listener(_on_update)
    connection.subscriptions[msg_id] = unsubscribe


async def _handle_draft_rule_from_row(
    hass: HomeAssistant, connection: Any, msg: dict[str, Any]
) -> None:
    resolved = _resolve_entry(hass)
    if resolved is None:
        _not_found(connection, msg["id"])
        return
    entry, coordinator = resolved

    caller_id = connection.user.id
    if caller_id not in entry.data[CONF_PARTICIPANTS]:
        _permission_denied(connection, msg["id"])
        return

    staging_id: str = msg["staging_id"]
    action: str = msg["action"]
    default_split_preset: str | None = msg.get("default_split_preset")

    data = coordinator.data
    rows = data.staging_by_user.get(caller_id, []) if data is not None else []
    row = next((r for r in rows if r.get("id") == staging_id), None)
    if row is None:
        connection.send_error(
            msg["id"],
            "not_found",
            f"Staging row '{staging_id}' not found in your inbox.",
        )
        return

    description: str = row.get("description") or ""
    pattern_str = _draft_regex(description)

    # Resolve category hint: prefer rule's category_hint, then default "Other".
    category_hint: str | None = row.get("category_hint")

    # Generate a short human-readable id suggestion.
    longest = max(re.findall(r"[A-Za-z]+", description), key=len, default=description) or "row"
    alpha_run = re.sub(r"[^a-z0-9]", "_", longest.lower())
    suggested_id = f"r_{alpha_run[:20]}"

    snippet = _build_yaml_snippet(
        description=description,
        action=action,
        pattern_str=pattern_str,
        category=category_hint,
        split_preset=default_split_preset,
    ).replace(ULID_PLACEHOLDER, alpha_run[:20])

    draft: dict[str, Any] = {
        "id": suggested_id,
        "description": f'Auto-generated from "{description}"',
        "pattern": f"/{pattern_str}/i",
        "action": action,
        "category": category_hint,
        "split": {"preset": default_split_preset} if default_split_preset else None,
        "priority": None,
    }

    connection.send_result(
        msg["id"],
        {
            "version": API_VERSION,
            "yaml_snippet": snippet,
            "draft": draft,
        },
    )


async def _handle_reload_rules(hass: HomeAssistant, connection: Any, msg: dict[str, Any]) -> None:
    resolved = _resolve_entry(hass)
    if resolved is None:
        _not_found(connection, msg["id"])
        return
    entry, coordinator = resolved

    caller_id = connection.user.id
    if caller_id not in entry.data[CONF_PARTICIPANTS]:
        _permission_denied(connection, msg["id"])
        return

    await coordinator.async_reload_rules()

    loaded_at = coordinator.rules_loaded_at.isoformat() if coordinator.rules_loaded_at else None
    connection.send_result(
        msg["id"],
        {
            "version": API_VERSION,
            "loaded_at": loaded_at,
            "rules_count": len(coordinator.rules),
            "errors": list(coordinator.rules_errors),
        },
    )


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


@websocket_api.websocket_command(
    {
        vol.Required("type"): "splitsmart/list_staging",
        vol.Optional("user_id"): str,
    }
)
@websocket_api.async_response
async def handle_list_staging(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return the caller's staging rows + targeted tombstones."""
    await _handle_list_staging(hass, connection, msg)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "splitsmart/list_staging/subscribe",
    }
)
@websocket_api.async_response
async def handle_list_staging_subscribe(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Subscribe to the caller's staging-row deltas."""
    await _handle_list_staging_subscribe(hass, connection, msg)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "splitsmart/list_presets",
    }
)
@websocket_api.async_response
async def handle_list_presets(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return the static preset registry."""
    await _handle_list_presets(hass, connection, msg)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "splitsmart/save_mapping",
        vol.Required("file_origin_hash"): str,
        vol.Required("mapping"): dict,
    }
)
@websocket_api.async_response
async def handle_save_mapping(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Persist a mapping under its file-origin hash."""
    await _handle_save_mapping(hass, connection, msg)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "splitsmart/inspect_upload",
        vol.Required("upload_id"): str,
    }
)
@websocket_api.async_response
async def handle_inspect_upload(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Re-inspect a previously uploaded file."""
    await _handle_inspect_upload(hass, connection, msg)


# --------------------------------------------------------------------- M5 registered handlers


@websocket_api.websocket_command(
    {
        vol.Required("type"): "splitsmart/list_rules",
    }
)
@websocket_api.async_response
async def handle_list_rules(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return the in-memory rule list, load timestamp, and any errors."""
    await _handle_list_rules(hass, connection, msg)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "splitsmart/list_rules/subscribe",
    }
)
@websocket_api.async_response
async def handle_list_rules_subscribe(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Subscribe to rule reloads. Init payload then delta events on file-watcher reload."""
    await _handle_list_rules_subscribe(hass, connection, msg)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "splitsmart/draft_rule_from_row",
        vol.Required("staging_id"): str,
        vol.Required("action"): vol.In(["always_split", "always_ignore", "review_each_time"]),
        vol.Optional("default_split_preset"): str,
    }
)
@websocket_api.async_response
async def handle_draft_rule_from_row(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Generate a YAML snippet + draft Rule from a staging row the caller owns."""
    await _handle_draft_rule_from_row(hass, connection, msg)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "splitsmart/reload_rules",
    }
)
@websocket_api.async_response
async def handle_reload_rules(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Force a re-read of rules.yaml and return the new counts."""
    await _handle_reload_rules(hass, connection, msg)


# --------------------------------------------------------------------- registration


def async_register_websocket_commands(hass: HomeAssistant) -> None:
    """Register the Splitsmart websocket commands once per HA instance."""
    flag = "_ws_registered"
    if hass.data.setdefault(DOMAIN, {}).get(flag):
        return

    websocket_api.async_register_command(hass, handle_get_config)
    websocket_api.async_register_command(hass, handle_list_expenses)
    websocket_api.async_register_command(hass, handle_subscribe)
    # M3
    websocket_api.async_register_command(hass, handle_list_staging)
    websocket_api.async_register_command(hass, handle_list_staging_subscribe)
    websocket_api.async_register_command(hass, handle_list_presets)
    websocket_api.async_register_command(hass, handle_save_mapping)
    websocket_api.async_register_command(hass, handle_inspect_upload)
    # M5
    websocket_api.async_register_command(hass, handle_list_rules)
    websocket_api.async_register_command(hass, handle_list_rules_subscribe)
    websocket_api.async_register_command(hass, handle_draft_rule_from_row)
    websocket_api.async_register_command(hass, handle_reload_rules)

    hass.data[DOMAIN][flag] = True
