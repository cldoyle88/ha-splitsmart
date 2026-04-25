"""Tests for the splitsmart.materialise_recurring service handler."""

from __future__ import annotations

import pathlib
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.splitsmart.const import DOMAIN
from custom_components.splitsmart.coordinator import SplitsmartCoordinator
from custom_components.splitsmart.services import _handle_materialise_recurring
from custom_components.splitsmart.storage import SplitsmartStorage

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
        categories=["Subscriptions", "Utilities", "Groceries"],
        config_entry=None,
    )
    coord.data = await coord._async_update_data()
    coord.async_refresh = AsyncMock()
    return coord


def _make_fx_client_gbp() -> MagicMock:
    from custom_components.splitsmart.fx import FxClient, FxResult

    mock = MagicMock(spec=FxClient)

    async def _get_rate(*, date, from_currency, to_currency):
        return FxResult(rate=Decimal("1"), fx_date=date, source="cache")

    mock.get_rate = AsyncMock(side_effect=_get_rate)
    return mock


def _make_hass(storage: SplitsmartStorage, coordinator: SplitsmartCoordinator) -> MagicMock:
    hass = MagicMock()
    hass.data = {
        DOMAIN: {
            "test_entry": {
                "storage": storage,
                "coordinator": coordinator,
                "fx": _make_fx_client_gbp(),
                "entry": None,
            }
        }
    }
    return hass


def _make_call(hass: MagicMock, data: dict) -> MagicMock:
    call = MagicMock()
    call.hass = hass
    call.data = data
    call.context = MagicMock()
    call.context.user_id = "u1"
    return call


# day=1 + start_date=2026-04-01 fires on Apr 1 which is in the past regardless of today's date
# (today is 2026-04-24 per CLAUDE.md context)
_NETFLIX_YAML = """
recurring:
  - id: netflix
    description: Netflix
    amount: 15.99
    currency: GBP
    paid_by: u1
    categories:
      - name: Subscriptions
        home_amount: 15.99
        split:
          method: equal
          shares:
            - {user_id: u1, value: 50}
            - {user_id: u2, value: 50}
    schedule:
      kind: monthly
      day: 1
    start_date: 2026-04-01
    end_date: 2026-04-01
"""


# ------------------------------------------------------------------ happy path


@pytest.mark.asyncio
async def test_materialise_recurring_service_writes_expense(storage, coordinator):
    storage.recurring_yaml_path.write_text(_NETFLIX_YAML, encoding="utf-8")
    hass = _make_hass(storage, coordinator)
    call = _make_call(hass, {})

    result = await _handle_materialise_recurring(call)

    assert result["materialised"] == 1
    assert result["skipped_fx_failure"] == 0
    assert result["skipped_duplicate"] == 0
    expenses = await storage.read_all(storage.expenses_path)
    assert len(expenses) == 1
    assert expenses[0]["recurring_id"] == "netflix"
    coordinator.async_refresh.assert_called_once()


@pytest.mark.asyncio
async def test_materialise_recurring_service_no_recurring_yaml(storage, coordinator):
    """No recurring.yaml — service returns zeros without error."""
    hass = _make_hass(storage, coordinator)
    call = _make_call(hass, {})
    result = await _handle_materialise_recurring(call)
    assert result["materialised"] == 0
    coordinator.async_refresh.assert_not_called()


@pytest.mark.asyncio
async def test_materialise_recurring_service_filter_id(storage, coordinator):
    """filter_id restricts materialisation to the named entry."""
    two_entries = (
        _NETFLIX_YAML
        + """
  - id: council
    description: Council tax
    amount: 210.00
    currency: GBP
    paid_by: u1
    categories:
      - name: Utilities
        home_amount: 210.00
        split:
          method: equal
          shares:
            - {user_id: u1, value: 50}
            - {user_id: u2, value: 50}
    schedule:
      kind: monthly
      day: 1
    start_date: 2026-04-01
    end_date: 2026-04-01
"""
    )
    storage.recurring_yaml_path.write_text(two_entries, encoding="utf-8")
    hass = _make_hass(storage, coordinator)
    call = _make_call(hass, {"recurring_id": "netflix"})

    result = await _handle_materialise_recurring(call)

    assert result["materialised"] == 1
    expenses = await storage.read_all(storage.expenses_path)
    assert all(e["recurring_id"] == "netflix" for e in expenses)


@pytest.mark.asyncio
async def test_materialise_recurring_service_unknown_filter_id_raises(storage, coordinator):
    """Requesting a non-existent recurring_id raises ServiceValidationError."""
    from homeassistant.exceptions import ServiceValidationError

    storage.recurring_yaml_path.write_text(_NETFLIX_YAML, encoding="utf-8")
    hass = _make_hass(storage, coordinator)
    call = _make_call(hass, {"recurring_id": "nonexistent"})

    with pytest.raises(ServiceValidationError, match="nonexistent"):
        await _handle_materialise_recurring(call)


@pytest.mark.asyncio
async def test_materialise_recurring_service_idempotent(storage, coordinator):
    """Second call returns 0 for all counts — Belt 1 (state file) skips entirely."""
    storage.recurring_yaml_path.write_text(_NETFLIX_YAML, encoding="utf-8")
    hass = _make_hass(storage, coordinator)

    await _handle_materialise_recurring(_make_call(hass, {}))
    coordinator.async_refresh.reset_mock()
    result = await _handle_materialise_recurring(_make_call(hass, {}))

    assert result["materialised"] == 0
    assert result["skipped_duplicate"] == 0
    assert result["skipped_fx_failure"] == 0
    coordinator.async_refresh.assert_not_called()
