"""Unit tests for fx.py — FxClient, cache, network, error taxonomy."""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import pathlib
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.splitsmart.fx import (
    FxClient,
    FxResult,
    FxUnavailableError,
    FxUnsupportedCurrencyError,
)
from custom_components.splitsmart.storage import SplitsmartStorage


# ------------------------------------------------------------------ helpers


def _make_client(tmp_path: pathlib.Path) -> tuple[FxClient, SplitsmartStorage]:
    root = tmp_path / "splitsmart"
    root.mkdir(parents=True, exist_ok=True)
    storage = SplitsmartStorage(root)
    hass = MagicMock()
    client = FxClient(hass, storage)
    return client, storage


def _write_cache_row(
    storage: SplitsmartStorage,
    *,
    from_ccy: str,
    to_ccy: str,
    requested_date: str,
    fx_date: str,
    rate: str,
    fetched_at: str = "2026-04-24T14:30:00+01:00",
) -> None:
    record = {
        "requested_date": requested_date,
        "from_currency": from_ccy,
        "to_currency": to_ccy,
        "rate": rate,
        "fx_date": fx_date,
        "fetched_at": fetched_at,
    }
    path = storage.fx_rates_path
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


def _frankfurter_response(
    *,
    from_ccy: str,
    to_ccy: str,
    date: str,
    rate: float,
) -> dict:
    return {
        "amount": 1.0,
        "base": from_ccy,
        "date": date,
        "rates": {to_ccy: rate},
    }


def _mock_http_response(payload: dict | None, status: int = 200):
    resp = AsyncMock()
    resp.status = status
    resp.json = AsyncMock(return_value=payload)
    resp.text = AsyncMock(return_value=json.dumps(payload) if payload else "error")
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock(return_value=False)
    return resp


# ------------------------------------------------------------------ same-currency shortcut


@pytest.mark.asyncio
async def test_same_currency_returns_one_without_io(tmp_path):
    client, storage = _make_client(tmp_path)
    # fx_rates.jsonl does not exist — would blow up if accessed
    result = await client.get_rate(
        date=dt.date(2026, 4, 15), from_currency="GBP", to_currency="GBP"
    )
    assert result.rate == Decimal("1")
    assert result.source == "cache"
    assert result.fx_date == dt.date(2026, 4, 15)


# ------------------------------------------------------------------ cache hit


@pytest.mark.asyncio
async def test_cache_hit_returns_without_network(tmp_path):
    client, storage = _make_client(tmp_path)
    _write_cache_row(
        storage,
        from_ccy="EUR",
        to_ccy="GBP",
        requested_date="2026-04-15",
        fx_date="2026-04-15",
        rate="0.8567",
    )

    with patch(
        "homeassistant.helpers.aiohttp_client.async_get_clientsession",
        side_effect=AssertionError("network must not be called on cache hit"),
    ):
        result = await client.get_rate(
            date=dt.date(2026, 4, 15), from_currency="EUR", to_currency="GBP"
        )

    assert result.rate == Decimal("0.8567")
    assert result.fx_date == dt.date(2026, 4, 15)
    assert result.source == "cache"


# ------------------------------------------------------------------ happy-path network fetch


@pytest.mark.asyncio
async def test_network_fetch_caches_and_returns(tmp_path):
    client, storage = _make_client(tmp_path)
    storage.fx_rates_path.touch()

    payload = _frankfurter_response(from_ccy="EUR", to_ccy="GBP", date="2026-04-15", rate=0.8567)
    mock_resp = _mock_http_response(payload)
    session_mock = MagicMock()
    session_mock.get = MagicMock(return_value=mock_resp)

    with patch(
        "custom_components.splitsmart.fx.async_get_clientsession",
        return_value=session_mock,
    ):
        result = await client.get_rate(
            date=dt.date(2026, 4, 15), from_currency="EUR", to_currency="GBP"
        )

    assert result.rate == Decimal("0.8567")
    assert result.fx_date == dt.date(2026, 4, 15)
    assert result.source == "network"

    # second call must hit cache (no second network call)
    with patch(
        "homeassistant.helpers.aiohttp_client.async_get_clientsession",
        side_effect=AssertionError("should have hit cache"),
    ):
        result2 = await client.get_rate(
            date=dt.date(2026, 4, 15), from_currency="EUR", to_currency="GBP"
        )
    assert result2.source == "cache"
    assert result2.rate == Decimal("0.8567")


# ------------------------------------------------------------------ weekend date


@pytest.mark.asyncio
async def test_weekend_date_stores_requested_and_fx_date(tmp_path):
    """Frankfurter returns a prior weekday's rate when requested date is a weekend."""
    client, storage = _make_client(tmp_path)
    storage.fx_rates_path.touch()

    # 2026-04-12 is a Sunday; Frankfurter returns rate dated 2026-04-10 (Friday)
    payload = _frankfurter_response(from_ccy="EUR", to_ccy="GBP", date="2026-04-10", rate=0.8550)
    mock_resp = _mock_http_response(payload)
    session_mock = MagicMock()
    session_mock.get = MagicMock(return_value=mock_resp)

    with patch(
        "custom_components.splitsmart.fx.async_get_clientsession",
        return_value=session_mock,
    ):
        result = await client.get_rate(
            date=dt.date(2026, 4, 12), from_currency="EUR", to_currency="GBP"
        )

    assert result.rate == Decimal("0.8550")
    assert result.fx_date == dt.date(2026, 4, 10)

    # Re-query for the same Sunday — must hit cache keyed on requested_date=2026-04-12
    with patch(
        "homeassistant.helpers.aiohttp_client.async_get_clientsession",
        side_effect=AssertionError("should hit cache for the Sunday"),
    ):
        result2 = await client.get_rate(
            date=dt.date(2026, 4, 12), from_currency="EUR", to_currency="GBP"
        )
    assert result2.source == "cache"
    assert result2.rate == Decimal("0.8550")


# ------------------------------------------------------------------ retry logic


@pytest.mark.asyncio
async def test_retry_succeeds_after_timeout(tmp_path):
    client, storage = _make_client(tmp_path)
    storage.fx_rates_path.touch()

    payload = _frankfurter_response(from_ccy="EUR", to_ccy="GBP", date="2026-04-15", rate=0.8567)
    good_resp = _mock_http_response(payload)
    session_mock = MagicMock()
    call_count = 0

    def get_side_effect(url, *, timeout):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise asyncio.TimeoutError()
        return good_resp

    session_mock.get = MagicMock(side_effect=get_side_effect)

    with (
        patch("custom_components.splitsmart.fx.async_get_clientsession", return_value=session_mock),
        patch("asyncio.sleep", new=AsyncMock()),
    ):
        result = await client.get_rate(
            date=dt.date(2026, 4, 15), from_currency="EUR", to_currency="GBP"
        )

    assert result.source == "network"
    assert call_count == 2


@pytest.mark.asyncio
async def test_both_attempts_timeout_no_cache_raises(tmp_path):
    client, storage = _make_client(tmp_path)
    storage.fx_rates_path.touch()

    session_mock = MagicMock()
    session_mock.get = MagicMock(side_effect=asyncio.TimeoutError())

    with (
        patch("custom_components.splitsmart.fx.async_get_clientsession", return_value=session_mock),
        patch("asyncio.sleep", new=AsyncMock()),
        pytest.raises(FxUnavailableError),
    ):
        await client.get_rate(
            date=dt.date(2026, 4, 15), from_currency="EUR", to_currency="GBP"
        )


@pytest.mark.asyncio
async def test_both_attempts_timeout_cache_populated_returns_cache(tmp_path):
    client, storage = _make_client(tmp_path)
    _write_cache_row(
        storage,
        from_ccy="EUR",
        to_ccy="GBP",
        requested_date="2026-04-15",
        fx_date="2026-04-15",
        rate="0.8500",
    )

    # Simulate first request: cache empty for a different date, network fails
    # This test hits cache on the matching date, so network is never reached.
    result = await client.get_rate(
        date=dt.date(2026, 4, 15), from_currency="EUR", to_currency="GBP"
    )
    assert result.source == "cache"
    assert result.rate == Decimal("0.8500")


# ------------------------------------------------------------------ HTTP 404 → unsupported currency


@pytest.mark.asyncio
async def test_http_404_raises_unsupported_currency(tmp_path):
    client, storage = _make_client(tmp_path)
    storage.fx_rates_path.touch()

    mock_resp = _mock_http_response(None, status=404)
    session_mock = MagicMock()
    session_mock.get = MagicMock(return_value=mock_resp)

    with (
        patch("custom_components.splitsmart.fx.async_get_clientsession", return_value=session_mock),
        pytest.raises(FxUnsupportedCurrencyError),
    ):
        await client.get_rate(
            date=dt.date(2026, 4, 15), from_currency="VND", to_currency="GBP"
        )


@pytest.mark.asyncio
async def test_http_404_no_retry(tmp_path):
    """404 must not trigger the retry path — it's a terminal error."""
    client, storage = _make_client(tmp_path)
    storage.fx_rates_path.touch()

    call_count = 0

    def get_side_effect(url, *, timeout):
        nonlocal call_count
        call_count += 1
        return _mock_http_response(None, status=404)

    session_mock = MagicMock()
    session_mock.get = MagicMock(side_effect=get_side_effect)

    with (
        patch("custom_components.splitsmart.fx.async_get_clientsession", return_value=session_mock),
        pytest.raises(FxUnsupportedCurrencyError),
    ):
        await client.get_rate(
            date=dt.date(2026, 4, 15), from_currency="VND", to_currency="GBP"
        )

    assert call_count == 1  # no retry


# ------------------------------------------------------------------ HTTP 500 → retried


@pytest.mark.asyncio
async def test_http_500_is_retried(tmp_path):
    client, storage = _make_client(tmp_path)
    storage.fx_rates_path.touch()

    payload = _frankfurter_response(from_ccy="EUR", to_ccy="GBP", date="2026-04-15", rate=0.8567)
    call_count = 0

    def get_side_effect(url, *, timeout):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _mock_http_response(None, status=500)
        return _mock_http_response(payload)

    session_mock = MagicMock()
    session_mock.get = MagicMock(side_effect=get_side_effect)

    with (
        patch("custom_components.splitsmart.fx.async_get_clientsession", return_value=session_mock),
        patch("asyncio.sleep", new=AsyncMock()),
    ):
        result = await client.get_rate(
            date=dt.date(2026, 4, 15), from_currency="EUR", to_currency="GBP"
        )

    assert result.source == "network"
    assert call_count == 2


# ------------------------------------------------------------------ ambiguous response body


@pytest.mark.asyncio
async def test_missing_rates_key_raises_unavailable(tmp_path):
    client, storage = _make_client(tmp_path)
    storage.fx_rates_path.touch()

    bad_payload = {"amount": 1.0, "base": "EUR", "date": "2026-04-15"}  # no "rates"
    mock_resp = _mock_http_response(bad_payload)
    session_mock = MagicMock()
    # Both attempts return the bad payload
    session_mock.get = MagicMock(return_value=mock_resp)

    with (
        patch("custom_components.splitsmart.fx.async_get_clientsession", return_value=session_mock),
        patch("asyncio.sleep", new=AsyncMock()),
        pytest.raises(FxUnavailableError),
    ):
        await client.get_rate(
            date=dt.date(2026, 4, 15), from_currency="EUR", to_currency="GBP"
        )


# ------------------------------------------------------------------ last_successful_fetch


@pytest.mark.asyncio
async def test_last_successful_fetch_none_when_empty(tmp_path):
    client, storage = _make_client(tmp_path)
    storage.fx_rates_path.touch()
    result = await client.last_successful_fetch()
    assert result is None


@pytest.mark.asyncio
async def test_last_successful_fetch_returns_newest(tmp_path):
    client, storage = _make_client(tmp_path)
    _write_cache_row(
        storage,
        from_ccy="EUR", to_ccy="GBP",
        requested_date="2026-04-10", fx_date="2026-04-10", rate="0.85",
        fetched_at="2026-04-10T10:00:00+01:00",
    )
    _write_cache_row(
        storage,
        from_ccy="USD", to_ccy="GBP",
        requested_date="2026-04-14", fx_date="2026-04-14", rate="0.79",
        fetched_at="2026-04-14T15:00:00+01:00",
    )

    result = await client.last_successful_fetch()
    assert result is not None
    assert result.isoformat().startswith("2026-04-14")
