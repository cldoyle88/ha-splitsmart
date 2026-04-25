"""Frankfurter FX client with append-only cache."""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Literal

import aiofiles
from homeassistant.helpers.aiohttp_client import async_get_clientsession

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .storage import SplitsmartStorage

_LOGGER = logging.getLogger(__name__)

_FRANKFURTER_URL = "https://api.frankfurter.dev/v1/{date}?from={from_ccy}&to={to_ccy}"
_TIMEOUT_SECONDS = 5
_RETRY_BACKOFF_SECONDS = 0.5


# ------------------------------------------------------------------ public types


@dataclass(frozen=True)
class FxResult:
    rate: Decimal
    fx_date: dt.date
    source: Literal["cache", "network"]


class FxError(Exception):
    """Base class for FX failures. Never surfaced to users directly."""


class FxUnavailableError(FxError):
    """Cache miss AND network failure. Caller retries later."""


class FxUnsupportedCurrencyError(FxError):
    """Frankfurter returned 404 — currency not in ECB basket (e.g. VND)."""


class FxSanityError(FxError):
    """Resolved rate diverges by >50% from today's rate (within ±365 days)."""


# ------------------------------------------------------------------ client


class FxClient:
    """One instance per config entry, stored at hass.data[DOMAIN][entry_id]['fx']."""

    def __init__(self, hass: HomeAssistant, storage: SplitsmartStorage) -> None:
        self._hass = hass
        self._storage = storage
        self._first_fetch_done = False

    async def get_rate(
        self,
        *,
        date: dt.date,
        from_currency: str,
        to_currency: str,
    ) -> FxResult:
        """Resolve the rate for (from → to) on ``date``.

        Order of operations:
          1. Same-currency shortcut — no IO.
          2. Cache read — newest entry matching (from, to, requested_date) wins.
          3. Network fetch on cache miss — one retry on transient failure.
          4. On fetch success: append to cache, return with source='network'.
          5. On fetch failure with cache empty: raise FxUnavailableError.
          6. Frankfurter 404: raise FxUnsupportedCurrencyError.
        """
        from_ccy = from_currency.upper()
        to_ccy = to_currency.upper()
        date_iso = date.isoformat()

        if from_ccy == to_ccy:
            _LOGGER.debug("FX same-currency shortcut %s on %s", from_ccy, date_iso)
            return FxResult(Decimal("1"), date, "cache")

        # --- cache read ---
        cached = await self._read_cache(from_ccy, to_ccy, date_iso)
        if cached is not None:
            _LOGGER.debug("FX cache hit %s→%s on %s", from_ccy, to_ccy, date_iso)
            return cached

        _LOGGER.debug("FX cache miss %s→%s on %s, fetching", from_ccy, to_ccy, date_iso)

        # --- network fetch with one retry ---
        result = await self._fetch_with_retry(from_ccy, to_ccy, date_iso)
        # result is either FxResult or raises

        # persist to cache
        await self._write_cache(from_ccy, to_ccy, date_iso, result)

        if not self._first_fetch_done:
            _LOGGER.info("FX client: first successful fetch %s→%s", from_ccy, to_ccy)
            self._first_fetch_done = True

        return result

    async def last_successful_fetch(self) -> dt.datetime | None:
        """Most recent ``fetched_at`` from fx_rates.jsonl; None if the file is empty.

        Drives binary_sensor.splitsmart_fx_healthy.
        """
        path = self._storage.fx_rates_path
        if not path.exists():
            return None
        latest: str | None = None
        async with aiofiles.open(path, encoding="utf-8") as fh:
            async for raw in fh:
                raw = raw.strip()
                if raw:
                    try:
                        obj = json.loads(raw)
                        candidate = obj.get("fetched_at")
                        if candidate:
                            latest = candidate
                    except (json.JSONDecodeError, AttributeError):
                        pass
        if latest is None:
            return None
        try:
            return dt.datetime.fromisoformat(latest)
        except ValueError:
            return None

    # ---------------------------------------------------------------- private helpers

    async def _read_cache(
        self, from_ccy: str, to_ccy: str, date_iso: str
    ) -> FxResult | None:
        """Return the newest cache entry matching (from, to, requested_date), or None."""
        path = self._storage.fx_rates_path
        if not path.exists():
            return None

        best: dict | None = None
        async with aiofiles.open(path, encoding="utf-8") as fh:
            async for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if (
                    obj.get("from_currency") == from_ccy
                    and obj.get("to_currency") == to_ccy
                    and obj.get("requested_date") == date_iso
                ):
                    best = obj  # last-wins (newest in append order)

        if best is None:
            return None

        try:
            rate = Decimal(best["rate"])
            fx_date = dt.date.fromisoformat(best["fx_date"])
        except (KeyError, InvalidOperation, ValueError):
            _LOGGER.warning("Corrupt FX cache entry for %s→%s %s", from_ccy, to_ccy, date_iso)
            return None

        return FxResult(rate=rate, fx_date=fx_date, source="cache")

    async def _write_cache(
        self,
        from_ccy: str,
        to_ccy: str,
        requested_date: str,
        result: FxResult,
    ) -> None:
        record = {
            "requested_date": requested_date,
            "from_currency": from_ccy,
            "to_currency": to_ccy,
            "rate": str(result.rate),
            "fx_date": result.fx_date.isoformat(),
            "fetched_at": dt.datetime.now(tz=dt.UTC).astimezone().isoformat(),
        }
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
        path = self._storage.fx_rates_path
        async with aiofiles.open(path, mode="a", encoding="utf-8") as fh:
            await fh.write(line)
            await fh.flush()

    async def _fetch_with_retry(
        self, from_ccy: str, to_ccy: str, date_iso: str
    ) -> FxResult:
        """Fetch from Frankfurter; one retry on transient error. Raises on failure."""
        url = _FRANKFURTER_URL.format(date=date_iso, from_ccy=from_ccy, to_ccy=to_ccy)
        session = async_get_clientsession(self._hass)

        last_exc: Exception | None = None
        for attempt in range(2):
            if attempt > 0:
                _LOGGER.debug(
                    "FX retry attempt %d for %s→%s %s", attempt, from_ccy, to_ccy, date_iso
                )
                await asyncio.sleep(_RETRY_BACKOFF_SECONDS)
            try:
                async with session.get(url, timeout=_TIMEOUT_SECONDS) as resp:
                    if resp.status == 404:
                        raise FxUnsupportedCurrencyError(
                            f"Currency not supported by Frankfurter: {from_ccy}→{to_ccy}"
                        )
                    if resp.status >= 400:
                        body = await resp.text()
                        _LOGGER.warning(
                            "Frankfurter returned HTTP %d for %s→%s %s: %.200s",
                            resp.status, from_ccy, to_ccy, date_iso, body,
                        )
                        # 4xx (not 404) is terminal — don't retry
                        if resp.status < 500:
                            raise FxUnavailableError(
                                f"Frankfurter returned HTTP {resp.status}"
                            )
                        # 5xx — retryable
                        last_exc = FxUnavailableError(f"Frankfurter HTTP {resp.status}")
                        continue

                    try:
                        payload = await resp.json(content_type=None)
                    except Exception as exc:
                        _LOGGER.warning(
                            "FX ambiguous response body for %s→%s %s: %s",
                            from_ccy, to_ccy, date_iso, exc,
                        )
                        last_exc = FxUnavailableError("Unparseable response from Frankfurter")
                        continue

                    rates = payload.get("rates")
                    if not rates or to_ccy not in rates:
                        _LOGGER.warning(
                            "FX response missing rates key for %s→%s %s",
                            from_ccy, to_ccy, date_iso,
                        )
                        last_exc = FxUnavailableError("Missing 'rates' in Frankfurter response")
                        continue

                    raw_rate = rates[to_ccy]
                    try:
                        rate = Decimal(str(raw_rate))
                    except InvalidOperation:
                        _LOGGER.warning("FX unparseable rate value: %r", raw_rate)
                        last_exc = FxUnavailableError("Unparseable rate in Frankfurter response")
                        continue

                    # Frankfurter returns the actual date used (may be prior weekday)
                    fx_date_raw = payload.get("date", date_iso)
                    try:
                        fx_date = dt.date.fromisoformat(fx_date_raw)
                    except ValueError:
                        fx_date = dt.date.fromisoformat(date_iso)

                    return FxResult(rate=rate, fx_date=fx_date, source="network")

            except FxUnsupportedCurrencyError:
                raise
            except FxUnavailableError:
                raise
            except (TimeoutError, Exception) as exc:
                if attempt == 0:
                    _LOGGER.debug("FX fetch transient error on attempt 0: %s", exc)
                last_exc = exc

        raise FxUnavailableError(
            f"FX fetch failed for {from_ccy}→{to_ccy} on {date_iso}"
        ) from last_exc
