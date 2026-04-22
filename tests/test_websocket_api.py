"""Tests for the Splitsmart websocket API.

Handlers are tested by calling the underscored implementation functions
(``_handle_get_config`` etc.) with MagicMock ``connection`` objects —
matches the mock-based pattern used in test_services.py so the suite
runs on Windows without pytest-homeassistant-custom-component.
"""

from __future__ import annotations

import asyncio
import pathlib
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.splitsmart.const import (
    CONF_CATEGORIES,
    CONF_HOME_CURRENCY,
    CONF_NAMED_SPLITS,
    CONF_PARTICIPANTS,
    DOMAIN,
)
from custom_components.splitsmart.coordinator import SplitsmartCoordinator
from custom_components.splitsmart.services import _handle_add_expense
from custom_components.splitsmart.storage import SplitsmartStorage
from custom_components.splitsmart.websocket_api import (
    API_VERSION,
    _handle_get_config,
    _handle_inspect_upload,
    _handle_list_expenses,
    _handle_list_presets,
    _handle_list_staging,
    _handle_list_staging_subscribe,
    _handle_save_mapping,
    _handle_subscribe,
)

# ------------------------------------------------------------------ fixtures


@pytest.fixture
async def storage(tmp_path: pathlib.Path) -> SplitsmartStorage:
    s = SplitsmartStorage(tmp_path / "splitsmart")
    await s.ensure_layout()
    return s


@pytest.fixture
async def coordinator(storage: SplitsmartStorage) -> SplitsmartCoordinator:
    hass = MagicMock()
    hass.bus = MagicMock()
    hass.bus.async_fire = MagicMock()

    coord = SplitsmartCoordinator(
        hass,
        storage,
        participants=["u1", "u2"],
        home_currency="GBP",
        categories=["Groceries", "Household", "Alcohol"],
        config_entry=None,
    )
    coord.data = await coord._async_update_data()
    coord.async_note_write = AsyncMock(side_effect=coord.async_note_write)
    return coord


def _make_entry(
    participants: list[str] | None = None,
    home_currency: str = "GBP",
    categories: list[str] | None = None,
    named_splits: dict[str, Any] | None = None,
    options: dict[str, Any] | None = None,
) -> MagicMock:
    entry = MagicMock()
    entry.data = {
        CONF_PARTICIPANTS: participants or ["u1", "u2"],
        CONF_HOME_CURRENCY: home_currency,
        CONF_CATEGORIES: categories or ["Groceries", "Household", "Alcohol"],
        CONF_NAMED_SPLITS: named_splits or {},
    }
    entry.options = options or {}
    return entry


def _make_hass(
    storage: SplitsmartStorage | None,
    coordinator: SplitsmartCoordinator | None,
    entry: MagicMock | None = None,
    user_map: dict[str, str] | None = None,
) -> MagicMock:
    hass = MagicMock()
    if entry is not None and coordinator is not None and storage is not None:
        hass.data = {
            DOMAIN: {
                "test_entry": {
                    "storage": storage,
                    "coordinator": coordinator,
                    "entry": entry,
                },
            },
        }
    else:
        hass.data = {DOMAIN: {}}

    users = user_map or {"u1": "Chris", "u2": "Slav"}

    async def _async_get_user(uid: str) -> MagicMock | None:
        if uid in users:
            u = MagicMock()
            u.name = users[uid]
            return u
        return None

    hass.auth = MagicMock()
    hass.auth.async_get_user = _async_get_user
    return hass


def _make_connection(user_id: str = "u1") -> MagicMock:
    conn = MagicMock()
    conn.user = MagicMock()
    conn.user.id = user_id
    conn.send_result = MagicMock()
    conn.send_error = MagicMock()
    conn.send_message = MagicMock()
    conn.subscriptions = {}
    return conn


def _tesco_data() -> dict[str, Any]:
    return {
        "date": "2026-04-15",
        "description": "Tesco Metro",
        "paid_by": "u1",
        "amount": 82.40,
        "currency": "GBP",
        "categories": [
            {
                "name": "Groceries",
                "home_amount": 55.20,
                "split": {
                    "method": "equal",
                    "shares": [{"user_id": "u1", "value": 50}, {"user_id": "u2", "value": 50}],
                },
            },
            {
                "name": "Household",
                "home_amount": 18.70,
                "split": {
                    "method": "equal",
                    "shares": [{"user_id": "u1", "value": 50}, {"user_id": "u2", "value": 50}],
                },
            },
            {
                "name": "Alcohol",
                "home_amount": 8.50,
                "split": {
                    "method": "exact",
                    "shares": [{"user_id": "u1", "value": 8.50}, {"user_id": "u2", "value": 0.00}],
                },
            },
        ],
    }


async def _seed_tesco(hass: MagicMock, user_id: str = "u1") -> None:
    call = MagicMock()
    call.hass = hass
    call.data = _tesco_data()
    call.context = MagicMock()
    call.context.user_id = user_id
    await _handle_add_expense(call)


# ------------------------------------------------------------------ get_config


async def test_get_config_happy_path(
    storage: SplitsmartStorage, coordinator: SplitsmartCoordinator
):
    entry = _make_entry()
    hass = _make_hass(storage, coordinator, entry)
    conn = _make_connection("u1")

    await _handle_get_config(hass, conn, {"id": 1, "type": "splitsmart/get_config"})

    conn.send_result.assert_called_once()
    msg_id, payload = conn.send_result.call_args.args
    assert msg_id == 1
    assert payload["version"] == API_VERSION
    assert payload["home_currency"] == "GBP"
    assert payload["categories"] == ["Groceries", "Household", "Alcohol"]
    assert payload["named_splits"] == {}
    assert payload["current_user_id"] == "u1"

    ids = [p["user_id"] for p in payload["participants"]]
    assert ids == ["u1", "u2"]
    assert all(p["active"] for p in payload["participants"])
    assert payload["participants"][0]["display_name"] == "Chris"
    assert payload["participants"][1]["display_name"] == "Slav"


async def test_get_config_reads_options_over_data(
    storage: SplitsmartStorage, coordinator: SplitsmartCoordinator
):
    entry = _make_entry(
        home_currency="GBP",
        categories=["Old"],
        options={CONF_HOME_CURRENCY: "EUR", CONF_CATEGORIES: ["New"]},
    )
    hass = _make_hass(storage, coordinator, entry)
    conn = _make_connection("u1")

    await _handle_get_config(hass, conn, {"id": 7, "type": "splitsmart/get_config"})

    _, payload = conn.send_result.call_args.args
    assert payload["home_currency"] == "EUR"
    assert payload["categories"] == ["New"]


async def test_get_config_includes_historical_inactive_users(
    storage: SplitsmartStorage, coordinator: SplitsmartCoordinator
):
    entry = _make_entry()
    hass = _make_hass(
        storage,
        coordinator,
        entry,
        user_map={"u1": "Chris", "u2": "Slav", "u_ghost": "Old Flatmate"},
    )
    await _seed_tesco(hass)
    # Inject a historical settlement involving a non-configured user.
    coordinator.data.settlements.append(
        {
            "id": "sl_ghost",
            "from_user": "u_ghost",
            "to_user": "u1",
            "amount": 10.0,
            "currency": "GBP",
            "home_amount": 10.0,
            "date": "2026-01-01",
        }
    )

    conn = _make_connection("u1")
    await _handle_get_config(hass, conn, {"id": 2, "type": "splitsmart/get_config"})

    _, payload = conn.send_result.call_args.args
    by_id = {p["user_id"]: p for p in payload["participants"]}
    assert by_id["u1"]["active"] is True
    assert by_id["u2"]["active"] is True
    assert by_id["u_ghost"]["active"] is False
    assert by_id["u_ghost"]["display_name"] == "Old Flatmate"


async def test_get_config_permission_denied_for_non_participant(
    storage: SplitsmartStorage, coordinator: SplitsmartCoordinator
):
    entry = _make_entry()
    hass = _make_hass(storage, coordinator, entry)
    conn = _make_connection("u_stranger")

    await _handle_get_config(hass, conn, {"id": 3, "type": "splitsmart/get_config"})

    conn.send_result.assert_not_called()
    conn.send_error.assert_called_once()
    assert conn.send_error.call_args.args[1] == "permission_denied"


async def test_get_config_not_found_when_integration_unloaded():
    hass = MagicMock()
    hass.data = {}
    conn = _make_connection("u1")

    await _handle_get_config(hass, conn, {"id": 9, "type": "splitsmart/get_config"})

    conn.send_error.assert_called_once()
    assert conn.send_error.call_args.args[1] == "not_found"


# ------------------------------------------------------------------ list_expenses


async def test_list_expenses_returns_all(
    storage: SplitsmartStorage, coordinator: SplitsmartCoordinator
):
    entry = _make_entry()
    hass = _make_hass(storage, coordinator, entry)
    await _seed_tesco(hass)

    conn = _make_connection("u1")
    await _handle_list_expenses(hass, conn, {"id": 4, "type": "splitsmart/list_expenses"})

    _, payload = conn.send_result.call_args.args
    assert payload["version"] == API_VERSION
    assert payload["total"] == 1
    assert len(payload["expenses"]) == 1
    assert payload["expenses"][0]["description"] == "Tesco Metro"
    assert payload["settlements"] == []


async def test_list_expenses_filter_month(
    storage: SplitsmartStorage, coordinator: SplitsmartCoordinator
):
    entry = _make_entry()
    hass = _make_hass(storage, coordinator, entry)
    await _seed_tesco(hass)

    conn = _make_connection("u1")
    await _handle_list_expenses(
        hass, conn, {"id": 5, "type": "splitsmart/list_expenses", "month": "2026-03"}
    )
    _, payload = conn.send_result.call_args.args
    assert payload["total"] == 0

    conn2 = _make_connection("u1")
    await _handle_list_expenses(
        hass, conn2, {"id": 6, "type": "splitsmart/list_expenses", "month": "2026-04"}
    )
    _, payload2 = conn2.send_result.call_args.args
    assert payload2["total"] == 1


async def test_list_expenses_filter_category(
    storage: SplitsmartStorage, coordinator: SplitsmartCoordinator
):
    entry = _make_entry()
    hass = _make_hass(storage, coordinator, entry)
    await _seed_tesco(hass)

    conn = _make_connection("u1")
    await _handle_list_expenses(
        hass, conn, {"id": 7, "type": "splitsmart/list_expenses", "category": "Alcohol"}
    )
    _, payload = conn.send_result.call_args.args
    assert payload["total"] == 1

    conn2 = _make_connection("u1")
    await _handle_list_expenses(
        hass, conn2, {"id": 8, "type": "splitsmart/list_expenses", "category": "Rent"}
    )
    _, payload2 = conn2.send_result.call_args.args
    assert payload2["total"] == 0


async def test_list_expenses_filter_paid_by(
    storage: SplitsmartStorage, coordinator: SplitsmartCoordinator
):
    entry = _make_entry()
    hass = _make_hass(storage, coordinator, entry)
    await _seed_tesco(hass)

    conn = _make_connection("u1")
    await _handle_list_expenses(
        hass, conn, {"id": 9, "type": "splitsmart/list_expenses", "paid_by": "u1"}
    )
    _, payload = conn.send_result.call_args.args
    assert payload["total"] == 1

    conn2 = _make_connection("u1")
    await _handle_list_expenses(
        hass, conn2, {"id": 10, "type": "splitsmart/list_expenses", "paid_by": "u2"}
    )
    _, payload2 = conn2.send_result.call_args.args
    assert payload2["total"] == 0


async def test_list_expenses_permission_denied_for_non_participant(
    storage: SplitsmartStorage, coordinator: SplitsmartCoordinator
):
    entry = _make_entry()
    hass = _make_hass(storage, coordinator, entry)
    conn = _make_connection("u_stranger")

    await _handle_list_expenses(hass, conn, {"id": 11, "type": "splitsmart/list_expenses"})

    conn.send_result.assert_not_called()
    conn.send_error.assert_called_once()
    assert conn.send_error.call_args.args[1] == "permission_denied"


# ------------------------------------------------------------------ subscribe


async def test_subscribe_sends_init_event(
    storage: SplitsmartStorage, coordinator: SplitsmartCoordinator
):
    entry = _make_entry()
    hass = _make_hass(storage, coordinator, entry)
    await _seed_tesco(hass)

    conn = _make_connection("u1")
    await _handle_subscribe(hass, conn, {"id": 12, "type": "splitsmart/list_expenses/subscribe"})

    conn.send_result.assert_called_once_with(12)
    conn.send_message.assert_called_once()
    sent = conn.send_message.call_args.args[0]
    assert sent["type"] == "event"
    assert sent["event"]["kind"] == "init"
    assert sent["event"]["version"] == API_VERSION
    assert len(sent["event"]["expenses"]) == 1
    assert 12 in conn.subscriptions


async def test_subscribe_sends_delta_on_coordinator_update(
    storage: SplitsmartStorage, coordinator: SplitsmartCoordinator
):
    entry = _make_entry()
    hass = _make_hass(storage, coordinator, entry)

    conn = _make_connection("u1")
    await _handle_subscribe(hass, conn, {"id": 13, "type": "splitsmart/list_expenses/subscribe"})
    # Drain the init message
    assert conn.send_message.call_count == 1
    conn.send_message.reset_mock()

    # Seed a new expense; async_note_write triggers async_set_updated_data
    # which fires every registered listener.
    await _seed_tesco(hass)
    # Give the event loop a tick so any scheduled callbacks run.
    await asyncio.sleep(0)

    assert conn.send_message.call_count >= 1
    delta = conn.send_message.call_args.args[0]
    assert delta["event"]["kind"] == "delta"
    assert delta["event"]["version"] == API_VERSION
    added_records = [a["record"] for a in delta["event"]["added"] if a["kind"] == "expense"]
    assert len(added_records) == 1
    assert added_records[0]["description"] == "Tesco Metro"


async def test_subscribe_permission_denied_for_non_participant(
    storage: SplitsmartStorage, coordinator: SplitsmartCoordinator
):
    entry = _make_entry()
    hass = _make_hass(storage, coordinator, entry)
    conn = _make_connection("u_stranger")

    await _handle_subscribe(hass, conn, {"id": 14, "type": "splitsmart/list_expenses/subscribe"})

    conn.send_result.assert_not_called()
    conn.send_error.assert_called_once()
    assert conn.send_error.call_args.args[1] == "permission_denied"
    assert 14 not in conn.subscriptions


async def test_subscribe_not_found_when_integration_unloaded():
    hass = MagicMock()
    hass.data = {}
    conn = _make_connection("u1")

    await _handle_subscribe(hass, conn, {"id": 15, "type": "splitsmart/list_expenses/subscribe"})

    conn.send_error.assert_called_once()
    assert conn.send_error.call_args.args[1] == "not_found"


# ------------------------------------------------------------------ M3 list_staging


async def _seed_staging(
    storage: SplitsmartStorage,
    coordinator: SplitsmartCoordinator,
    *,
    user_id: str,
    n: int = 1,
    currency: str = "GBP",
) -> list[dict[str, Any]]:
    """Append N synthetic staging rows for user_id and refresh the coordinator."""
    from custom_components.splitsmart.importer.normalise import dedup_hash
    from custom_components.splitsmart.storage import new_id

    rows: list[dict[str, Any]] = []
    for i in range(n):
        row = {
            "id": new_id("st"),
            "uploaded_by": user_id,
            "uploaded_at": "2026-04-22T10:00:00+01:00",
            "source": "csv",
            "date": "2026-04-15",
            "description": f"Merchant {i}",
            "amount": 4.50 + i,
            "currency": currency,
            "rule_action": "pending",
            "dedup_hash": dedup_hash(
                date="2026-04-15",
                amount=4.50 + i,
                currency=currency,
                description=f"Merchant {i}",
            ),
        }
        rows.append(row)
        await storage.append(storage.staging_path(user_id), row)
    coordinator.data = await coordinator._async_update_data()
    return rows


async def test_list_staging_returns_callers_rows(
    storage: SplitsmartStorage, coordinator: SplitsmartCoordinator
):
    await _seed_staging(storage, coordinator, user_id="u1", n=3)
    entry = _make_entry()
    hass = _make_hass(storage, coordinator, entry)
    conn = _make_connection("u1")

    await _handle_list_staging(hass, conn, {"id": 100, "type": "splitsmart/list_staging"})

    conn.send_result.assert_called_once()
    result = conn.send_result.call_args.args[1]
    assert result["version"] == API_VERSION
    assert result["total"] == 3
    assert len(result["rows"]) == 3


async def test_list_staging_includes_staging_tombstones(
    storage: SplitsmartStorage, coordinator: SplitsmartCoordinator
):
    """The review UI needs the tombstones to render auto-ignored/promoted tabs."""
    rows = await _seed_staging(storage, coordinator, user_id="u1", n=2)
    # Discard one of the rows.
    await storage.append_tombstone(
        created_by="u1",
        target_type="staging",
        target_id=rows[0]["id"],
        operation="discard",
        previous_snapshot=rows[0],
    )
    coordinator.data = await coordinator._async_update_data()

    entry = _make_entry()
    hass = _make_hass(storage, coordinator, entry)
    conn = _make_connection("u1")

    await _handle_list_staging(hass, conn, {"id": 101, "type": "splitsmart/list_staging"})

    result = conn.send_result.call_args.args[1]
    # Effective rows drop by 1; tombstone is listed separately.
    assert result["total"] == 1
    assert len(result["tombstones"]) == 1
    assert result["tombstones"][0]["target_id"] == rows[0]["id"]


async def test_list_staging_rejects_request_for_another_users_staging(
    storage: SplitsmartStorage, coordinator: SplitsmartCoordinator
):
    """SPEC §7: a participant cannot read another user's staging even if
    they explicitly pass the user_id argument."""
    await _seed_staging(storage, coordinator, user_id="u1", n=2)
    entry = _make_entry()
    hass = _make_hass(storage, coordinator, entry)
    conn = _make_connection("u2")

    await _handle_list_staging(
        hass, conn, {"id": 102, "type": "splitsmart/list_staging", "user_id": "u1"}
    )

    conn.send_result.assert_not_called()
    conn.send_error.assert_called_once()
    assert conn.send_error.call_args.args[1] == "permission_denied"


async def test_list_staging_permission_denied_for_non_participant(
    storage: SplitsmartStorage, coordinator: SplitsmartCoordinator
):
    entry = _make_entry()
    hass = _make_hass(storage, coordinator, entry)
    conn = _make_connection("u_stranger")

    await _handle_list_staging(hass, conn, {"id": 103, "type": "splitsmart/list_staging"})

    conn.send_error.assert_called_once()
    assert conn.send_error.call_args.args[1] == "permission_denied"


async def test_list_staging_default_scope_is_caller(
    storage: SplitsmartStorage, coordinator: SplitsmartCoordinator
):
    """Both users seeded; the response only carries the caller's rows."""
    await _seed_staging(storage, coordinator, user_id="u1", n=3)
    await _seed_staging(storage, coordinator, user_id="u2", n=5)

    entry = _make_entry()
    hass = _make_hass(storage, coordinator, entry)

    # u1 sees 3 rows.
    conn_u1 = _make_connection("u1")
    await _handle_list_staging(hass, conn_u1, {"id": 104, "type": "splitsmart/list_staging"})
    assert conn_u1.send_result.call_args.args[1]["total"] == 3

    # u2 sees 5 rows.
    conn_u2 = _make_connection("u2")
    await _handle_list_staging(hass, conn_u2, {"id": 105, "type": "splitsmart/list_staging"})
    assert conn_u2.send_result.call_args.args[1]["total"] == 5


# ------------------------------------------------------------------ M3 list_staging/subscribe


async def test_list_staging_subscribe_init_and_delta(
    storage: SplitsmartStorage, coordinator: SplitsmartCoordinator
):
    await _seed_staging(storage, coordinator, user_id="u1", n=2)
    entry = _make_entry()
    hass = _make_hass(storage, coordinator, entry)
    conn = _make_connection("u1")

    await _handle_list_staging_subscribe(
        hass, conn, {"id": 110, "type": "splitsmart/list_staging/subscribe"}
    )

    # Init event delivered.
    assert conn.send_message.call_count == 1
    init = conn.send_message.call_args.args[0]
    assert init["event"]["kind"] == "init"
    assert len(init["event"]["rows"]) == 2

    # Append another row and fire the coordinator listener.
    await _seed_staging(storage, coordinator, user_id="u1", n=1)
    coordinator.async_update_listeners()
    await asyncio.sleep(0)

    # Delta delivered.
    assert conn.send_message.call_count == 2
    delta = conn.send_message.call_args.args[0]
    assert delta["event"]["kind"] == "delta"
    assert len(delta["event"]["added"]) == 1


async def test_list_staging_subscribe_does_not_leak_other_users(
    storage: SplitsmartStorage, coordinator: SplitsmartCoordinator
):
    """A subscription on u1 must not see u2's staging deltas."""
    entry = _make_entry()
    hass = _make_hass(storage, coordinator, entry)
    conn = _make_connection("u1")

    await _handle_list_staging_subscribe(
        hass, conn, {"id": 111, "type": "splitsmart/list_staging/subscribe"}
    )
    init_count = conn.send_message.call_count  # 1 (init)

    # Append to u2's staging — u1's subscription must not fire.
    await _seed_staging(storage, coordinator, user_id="u2", n=1)
    coordinator.async_update_listeners()
    await asyncio.sleep(0)

    assert conn.send_message.call_count == init_count  # no additional delta


# ------------------------------------------------------------------ M3 list_presets


async def test_list_presets_returns_registry(
    storage: SplitsmartStorage, coordinator: SplitsmartCoordinator
):
    entry = _make_entry()
    hass = _make_hass(storage, coordinator, entry)
    conn = _make_connection("u1")

    await _handle_list_presets(hass, conn, {"id": 120, "type": "splitsmart/list_presets"})

    conn.send_result.assert_called_once()
    result = conn.send_result.call_args.args[1]
    names = {p["name"] for p in result["presets"]}
    assert names == {"Monzo", "Starling", "Revolut", "Splitwise"}


async def test_list_presets_permission_denied(
    storage: SplitsmartStorage, coordinator: SplitsmartCoordinator
):
    entry = _make_entry()
    hass = _make_hass(storage, coordinator, entry)
    conn = _make_connection("u_stranger")

    await _handle_list_presets(hass, conn, {"id": 121, "type": "splitsmart/list_presets"})

    conn.send_error.assert_called_once()
    assert conn.send_error.call_args.args[1] == "permission_denied"


# ------------------------------------------------------------------ M3 save_mapping


async def test_save_mapping_persists_to_disk(
    storage: SplitsmartStorage, coordinator: SplitsmartCoordinator
):
    from custom_components.splitsmart.importer.mapping import load_saved_mappings

    entry = _make_entry()
    hass = _make_hass(storage, coordinator, entry)
    conn = _make_connection("u1")

    mapping = {
        "date": "Posted",
        "description": "Merchant",
        "amount": "Spent",
        "currency_default": "GBP",
        "amount_sign": "expense_positive",
        "date_format": "auto",
        "notes_append": [],
    }
    await _handle_save_mapping(
        hass,
        conn,
        {
            "id": 130,
            "type": "splitsmart/save_mapping",
            "file_origin_hash": "sha1:abc123",
            "mapping": mapping,
        },
    )

    conn.send_result.assert_called_once()
    saved = await load_saved_mappings(storage)
    assert saved["sha1:abc123"] == mapping


async def test_save_mapping_permission_denied(
    storage: SplitsmartStorage, coordinator: SplitsmartCoordinator
):
    entry = _make_entry()
    hass = _make_hass(storage, coordinator, entry)
    conn = _make_connection("u_stranger")

    await _handle_save_mapping(
        hass,
        conn,
        {
            "id": 131,
            "type": "splitsmart/save_mapping",
            "file_origin_hash": "sha1:abc",
            "mapping": {},
        },
    )

    conn.send_error.assert_called_once()
    assert conn.send_error.call_args.args[1] == "permission_denied"


# ------------------------------------------------------------------ M3 inspect_upload


async def test_inspect_upload_returns_preset_and_headers(
    storage: SplitsmartStorage, coordinator: SplitsmartCoordinator, tmp_path: pathlib.Path
):
    import shutil
    import uuid

    fixture = pathlib.Path(__file__).parent / "fixtures" / "imports" / "monzo_classic.csv"
    upload_id = str(uuid.uuid4())
    dest = storage.upload_path(upload_id, "csv")
    shutil.copyfile(fixture, dest)

    entry = _make_entry()
    hass = _make_hass(storage, coordinator, entry)
    conn = _make_connection("u1")

    await _handle_inspect_upload(
        hass,
        conn,
        {"id": 140, "type": "splitsmart/inspect_upload", "upload_id": upload_id},
    )

    result = conn.send_result.call_args.args[1]
    assert result["inspection"]["preset"] == "Monzo"
    assert "Date" in result["inspection"]["headers"]


async def test_inspect_upload_not_found(
    storage: SplitsmartStorage, coordinator: SplitsmartCoordinator
):
    entry = _make_entry()
    hass = _make_hass(storage, coordinator, entry)
    conn = _make_connection("u1")

    await _handle_inspect_upload(
        hass,
        conn,
        {"id": 141, "type": "splitsmart/inspect_upload", "upload_id": "does-not-exist"},
    )

    conn.send_error.assert_called_once()
    assert conn.send_error.call_args.args[1] == "not_found"


async def test_inspect_upload_permission_denied(
    storage: SplitsmartStorage, coordinator: SplitsmartCoordinator
):
    entry = _make_entry()
    hass = _make_hass(storage, coordinator, entry)
    conn = _make_connection("u_stranger")

    await _handle_inspect_upload(
        hass,
        conn,
        {"id": 142, "type": "splitsmart/inspect_upload", "upload_id": "anything"},
    )

    conn.send_error.assert_called_once()
    assert conn.send_error.call_args.args[1] == "permission_denied"
