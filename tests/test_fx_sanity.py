"""Tests for the FX sanity guard in _resolve_fx.

The guard compares the resolved historical rate to today's rate and raises
ServiceValidationError when they diverge by more than 50% — but only when
the expense date is within ±365 days of today and no explicit fx_rate was
supplied.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.exceptions import ServiceValidationError

from custom_components.splitsmart.fx import FxClient, FxResult, FxUnavailableError
from custom_components.splitsmart.services import _resolve_fx

# ------------------------------------------------------------------ helpers


def _make_fx_client(
    *,
    historical_rate: Decimal | None,
    today_rate: Decimal | None,
    today: dt.date | None = None,
) -> FxClient:
    """Return a mock FxClient with configurable per-date rates."""
    _today = today or dt.date.today()
    mock = MagicMock(spec=FxClient)

    async def _get_rate(*, date: dt.date, from_currency: str, to_currency: str) -> FxResult:
        if date == _today:
            if today_rate is None:
                raise FxUnavailableError("today's rate not available")
            return FxResult(rate=today_rate, fx_date=date, source="cache")
        if historical_rate is None:
            raise FxUnavailableError("historical rate not available")
        return FxResult(rate=historical_rate, fx_date=date, source="network")

    mock.get_rate = AsyncMock(side_effect=_get_rate)
    return mock


# ------------------------------------------------------------------ guard passes


@pytest.mark.asyncio
async def test_rate_within_50pct_passes(tmp_path):
    """Rate is exactly equal to today's — guard should not raise."""
    client = _make_fx_client(historical_rate=Decimal("0.8567"), today_rate=Decimal("0.8567"))
    yesterday = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    rate, _ = await _resolve_fx(
        client,
        currency="EUR",
        home_currency="GBP",
        date=yesterday,
        explicit_rate=None,
        explicit_fx_date=None,
    )
    assert rate == Decimal("0.8567")


@pytest.mark.asyncio
async def test_rate_49pct_higher_passes(tmp_path):
    """rate = today * 1.49 — just under the 1.5x threshold."""
    today_rate = Decimal("0.8000")
    historical_rate = today_rate * Decimal("1.49")
    client = _make_fx_client(historical_rate=historical_rate, today_rate=today_rate)
    yesterday = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    rate, _ = await _resolve_fx(
        client,
        currency="EUR",
        home_currency="GBP",
        date=yesterday,
        explicit_rate=None,
        explicit_fx_date=None,
    )
    assert rate == historical_rate


# ------------------------------------------------------------------ guard fires


@pytest.mark.asyncio
async def test_rate_more_than_15x_today_raises(tmp_path):
    """resolved_rate > 1.5x today's → sanity error."""
    today_rate = Decimal("0.8000")
    historical_rate = today_rate * Decimal("1.6")  # 60% higher
    client = _make_fx_client(historical_rate=historical_rate, today_rate=today_rate)
    yesterday = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    with pytest.raises(ServiceValidationError, match="diverges by more than 50%"):
        await _resolve_fx(
            client,
            currency="EUR",
            home_currency="GBP",
            date=yesterday,
            explicit_rate=None,
            explicit_fx_date=None,
        )


@pytest.mark.asyncio
async def test_rate_less_than_two_thirds_today_raises(tmp_path):
    """resolved_rate < 0.667x today's → sanity error."""
    today_rate = Decimal("0.8000")
    historical_rate = today_rate * Decimal("0.5")  # 50% of today = 50% lower
    client = _make_fx_client(historical_rate=historical_rate, today_rate=today_rate)
    yesterday = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    with pytest.raises(ServiceValidationError, match="diverges by more than 50%"):
        await _resolve_fx(
            client,
            currency="EUR",
            home_currency="GBP",
            date=yesterday,
            explicit_rate=None,
            explicit_fx_date=None,
        )


# ------------------------------------------------------------------ guard skipped: old date


@pytest.mark.asyncio
async def test_old_date_beyond_365_days_skips_guard(tmp_path):
    """Guard skips for dates beyond ±365 days — no error even if rate is absurd."""
    today_rate = Decimal("0.8000")
    # historical = 10x today — would fire the guard if in range
    historical_rate = today_rate * Decimal("10")
    client = _make_fx_client(historical_rate=historical_rate, today_rate=today_rate)
    old_date = (dt.date.today() - dt.timedelta(days=400)).isoformat()
    rate, _ = await _resolve_fx(
        client,
        currency="EUR",
        home_currency="GBP",
        date=old_date,
        explicit_rate=None,
        explicit_fx_date=None,
    )
    assert rate == historical_rate  # returned normally, no guard fired


# ------------------------------------------------------------------ guard skipped: today rate fails


@pytest.mark.asyncio
async def test_todays_lookup_fails_skips_guard(tmp_path):
    """When today's rate lookup raises, the guard is silently skipped.
    The primary lookup succeeded — paranoia must not block the write."""
    historical_rate = Decimal("0.8567")
    # today_rate=None → get_rate raises FxUnavailableError for today
    client = _make_fx_client(historical_rate=historical_rate, today_rate=None)
    yesterday = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    rate, _ = await _resolve_fx(
        client,
        currency="EUR",
        home_currency="GBP",
        date=yesterday,
        explicit_rate=None,
        explicit_fx_date=None,
    )
    assert rate == historical_rate


# ------------------------------------------------------------------ guard skipped: explicit rate


@pytest.mark.asyncio
async def test_explicit_rate_bypasses_guard(tmp_path):
    """Caller supplied explicit fx_rate — no lookup, no guard."""
    # This client would raise if touched — if the guard ran it would call get_rate.
    mock = MagicMock(spec=FxClient)
    mock.get_rate = AsyncMock(side_effect=AssertionError("must not call get_rate"))
    yesterday = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    rate, fx_date = await _resolve_fx(
        mock,
        currency="EUR",
        home_currency="GBP",
        date=yesterday,
        explicit_rate=0.85,
        explicit_fx_date=None,
    )
    assert rate == Decimal("0.85")
    assert fx_date == yesterday


@pytest.mark.asyncio
async def test_resolve_fx_home_currency_with_explicit_rate_raises_exact_message():
    """fx_rate on a home-currency entry must raise the exact M4 error string.

    Automations in production may pattern-match on this message; it must not
    change without a breaking-change notice.
    """
    expected = (
        "fx_rate provided for a home-currency entry. "
        "Either remove fx_rate or change the currency."
    )
    mock = MagicMock(spec=FxClient)

    with pytest.raises(ServiceValidationError) as exc_info:
        await _resolve_fx(
            mock,
            currency="GBP",
            home_currency="GBP",
            date="2026-04-15",
            explicit_rate=1.15,
            explicit_fx_date=None,
        )

    assert str(exc_info.value) == expected
    mock.get_rate.assert_not_called()
