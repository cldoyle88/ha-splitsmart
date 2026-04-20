"""DataUpdateCoordinator for the Splitsmart shared ledger."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import COORDINATOR_UPDATE_INTERVAL_MINUTES, DOMAIN
from .ledger import (
    compute_balances,
    compute_pairwise_balances,
    materialise_expenses,
    materialise_settlements,
)
from .storage import SplitsmartStorage

_LOGGER = logging.getLogger(__name__)


@dataclass
class SplitsmartData:
    """In-memory projection of the on-disk log. Sensors read from here; never from disk."""

    raw_expenses: list[dict[str, Any]] = field(default_factory=list)
    raw_settlements: list[dict[str, Any]] = field(default_factory=list)
    tombstones: list[dict[str, Any]] = field(default_factory=list)

    expenses: list[dict[str, Any]] = field(default_factory=list)
    settlements: list[dict[str, Any]] = field(default_factory=list)

    balances: dict[str, Decimal] = field(default_factory=dict)
    pairwise: dict[tuple[str, str], Decimal] = field(default_factory=dict)

    last_expense_id: str | None = None
    last_settlement_id: str | None = None
    last_tombstone_id: str | None = None


class SplitsmartCoordinator(DataUpdateCoordinator[SplitsmartData]):
    """Caches the materialised ledger. Full replay on startup; incremental on writes."""

    def __init__(
        self,
        hass: HomeAssistant,
        storage: SplitsmartStorage,
        *,
        participants: list[str],
        home_currency: str,
        categories: list[str],
        config_entry: Any = None,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=timedelta(minutes=COORDINATOR_UPDATE_INTERVAL_MINUTES),
        )
        self.storage = storage
        self.participants = participants
        self.home_currency = home_currency
        self.categories = categories

    # DataUpdateCoordinator override — full replay every 5 min as a safety net.
    async def _async_update_data(self) -> SplitsmartData:
        """Full replay: read all three logs, materialise, compute balances."""
        try:
            raw_expenses = await self.storage.read_all(self.storage.expenses_path)
            raw_settlements = await self.storage.read_all(self.storage.settlements_path)
            tombstones = await self.storage.read_all(self.storage.tombstones_path)
        except Exception as err:
            raise UpdateFailed(f"Failed to read ledger files: {err}") from err

        return self._build(raw_expenses, raw_settlements, tombstones)

    def _build(
        self,
        raw_expenses: list[dict[str, Any]],
        raw_settlements: list[dict[str, Any]],
        tombstones: list[dict[str, Any]],
    ) -> SplitsmartData:
        expenses = materialise_expenses(raw_expenses, tombstones)
        settlements = materialise_settlements(raw_settlements, tombstones)
        balances = compute_balances(expenses, settlements)
        pairwise = compute_pairwise_balances(expenses, settlements)

        last_expense_id = raw_expenses[-1]["id"] if raw_expenses else None
        last_settlement_id = raw_settlements[-1]["id"] if raw_settlements else None
        last_tombstone_id = tombstones[-1]["id"] if tombstones else None

        return SplitsmartData(
            raw_expenses=raw_expenses,
            raw_settlements=raw_settlements,
            tombstones=tombstones,
            expenses=expenses,
            settlements=settlements,
            balances=balances,
            pairwise=pairwise,
            last_expense_id=last_expense_id,
            last_settlement_id=last_settlement_id,
            last_tombstone_id=last_tombstone_id,
        )

    async def async_note_write(self) -> None:
        """Incremental refresh: read only new lines since last known ids.
        Called by service handlers immediately after a successful append."""
        if self.data is None:
            await self.async_refresh()
            return

        try:
            new_expenses = await self.storage.read_since(
                self.storage.expenses_path, self.data.last_expense_id
            )
            new_settlements = await self.storage.read_since(
                self.storage.settlements_path, self.data.last_settlement_id
            )
            new_tombstones = await self.storage.read_since(
                self.storage.tombstones_path, self.data.last_tombstone_id
            )
        except Exception as err:
            _LOGGER.warning("Incremental refresh failed, falling back to full replay: %s", err)
            await self.async_refresh()
            return

        if not new_expenses and not new_settlements and not new_tombstones:
            return

        raw_expenses = self.data.raw_expenses + new_expenses
        raw_settlements = self.data.raw_settlements + new_settlements
        tombstones = self.data.tombstones + new_tombstones

        new_data = self._build(raw_expenses, raw_settlements, tombstones)
        self.async_set_updated_data(new_data)

    async def async_invalidate(self) -> None:
        """Force a full replay on the next refresh call."""
        if self.data is not None:
            # Reset last-seen ids so _async_update_data does a clean read
            self.data.last_expense_id = None
            self.data.last_settlement_id = None
            self.data.last_tombstone_id = None
