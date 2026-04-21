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
    _handle_list_expenses,
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
