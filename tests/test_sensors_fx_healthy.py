"""Tests for binary_sensor.splitsmart_fx_healthy."""

from __future__ import annotations

import datetime as dt
import json
import pathlib
from unittest.mock import MagicMock

import pytest

from custom_components.splitsmart.binary_sensor import FxHealthySensor
from custom_components.splitsmart.fx import FxClient
from custom_components.splitsmart.storage import SplitsmartStorage

# ------------------------------------------------------------------ helpers


def _make_sensor(storage: SplitsmartStorage) -> FxHealthySensor:
    coordinator = MagicMock()
    coordinator.async_add_listener = MagicMock(return_value=lambda: None)
    entry = MagicMock()
    entry.entry_id = "test_entry"
    fx_client = MagicMock(spec=FxClient)
    sensor = FxHealthySensor(coordinator, entry, fx_client)
    sensor.hass = MagicMock()
    sensor.hass.async_create_task = MagicMock()
    return sensor


def _write_cache_row(storage: SplitsmartStorage, *, fetched_at: str) -> None:
    record = {
        "requested_date": "2026-04-15",
        "from_currency": "EUR",
        "to_currency": "GBP",
        "rate": "0.8567",
        "fx_date": "2026-04-15",
        "fetched_at": fetched_at,
    }
    with storage.fx_rates_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


# ------------------------------------------------------------------ is_on


def test_is_on_false_when_last_success_is_none():
    sensor = _make_sensor.__wrapped__ if hasattr(_make_sensor, "__wrapped__") else None
    coordinator = MagicMock()
    coordinator.async_add_listener = MagicMock(return_value=lambda: None)
    entry = MagicMock()
    entry.entry_id = "test_entry"
    fx_client = MagicMock(spec=FxClient)
    sensor = FxHealthySensor(coordinator, entry, fx_client)
    sensor._last_success = None
    assert sensor.is_on is False


def test_is_on_true_when_recent_success():
    coordinator = MagicMock()
    coordinator.async_add_listener = MagicMock(return_value=lambda: None)
    entry = MagicMock()
    entry.entry_id = "test_entry"
    fx_client = MagicMock(spec=FxClient)
    sensor = FxHealthySensor(coordinator, entry, fx_client)
    sensor._last_success = dt.datetime.now(tz=dt.UTC) - dt.timedelta(hours=1)
    assert sensor.is_on is True


def test_is_on_true_at_23h():
    coordinator = MagicMock()
    coordinator.async_add_listener = MagicMock(return_value=lambda: None)
    entry = MagicMock()
    entry.entry_id = "test_entry"
    fx_client = MagicMock(spec=FxClient)
    sensor = FxHealthySensor(coordinator, entry, fx_client)
    sensor._last_success = dt.datetime.now(tz=dt.UTC) - dt.timedelta(hours=23)
    assert sensor.is_on is True


def test_is_on_false_at_25h():
    coordinator = MagicMock()
    coordinator.async_add_listener = MagicMock(return_value=lambda: None)
    entry = MagicMock()
    entry.entry_id = "test_entry"
    fx_client = MagicMock(spec=FxClient)
    sensor = FxHealthySensor(coordinator, entry, fx_client)
    sensor._last_success = dt.datetime.now(tz=dt.UTC) - dt.timedelta(hours=25)
    assert sensor.is_on is False


# ------------------------------------------------------------------ extra_state_attributes


def test_extra_state_attributes_none_when_no_success():
    coordinator = MagicMock()
    coordinator.async_add_listener = MagicMock(return_value=lambda: None)
    entry = MagicMock()
    entry.entry_id = "test_entry"
    fx_client = MagicMock(spec=FxClient)
    sensor = FxHealthySensor(coordinator, entry, fx_client)
    sensor._last_success = None
    assert sensor.extra_state_attributes == {"last_checked": None}


def test_extra_state_attributes_iso_when_success():
    coordinator = MagicMock()
    coordinator.async_add_listener = MagicMock(return_value=lambda: None)
    entry = MagicMock()
    entry.entry_id = "test_entry"
    fx_client = MagicMock(spec=FxClient)
    sensor = FxHealthySensor(coordinator, entry, fx_client)
    ts = dt.datetime(2026, 4, 24, 14, 30, tzinfo=dt.UTC)
    sensor._last_success = ts
    attrs = sensor.extra_state_attributes
    assert attrs["last_checked"] == ts.isoformat()


# ------------------------------------------------------------------ async_added_to_hass


@pytest.mark.asyncio
async def test_async_added_reads_last_success(tmp_path: pathlib.Path):
    root = tmp_path / "splitsmart"
    root.mkdir(parents=True, exist_ok=True)
    storage = SplitsmartStorage(root)
    storage.fx_rates_path.touch()
    _write_cache_row(storage, fetched_at="2026-04-24T14:30:00+01:00")

    coordinator = MagicMock()
    coordinator.async_add_listener = MagicMock(return_value=lambda: None)
    entry = MagicMock()
    entry.entry_id = "test_entry"
    fx_client = FxClient(MagicMock(), storage)

    sensor = FxHealthySensor(coordinator, entry, fx_client)
    sensor.hass = MagicMock()
    sensor.hass.async_create_task = MagicMock()
    # Simulate async_added_to_hass by calling the coroutine that populates _last_success
    sensor._last_success = await fx_client.last_successful_fetch()

    assert sensor._last_success is not None
    assert "2026-04-24" in sensor._last_success.isoformat()
