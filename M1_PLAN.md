# M1 plan — data plane

Scope is the SPEC §19 M1 milestone: component skeleton, config flow, storage, coordinator, ledger calculators, core services for the **shared ledger** (expense and settlement CRUD), plus the sensors that can be driven from those. No staging, no rules, no FX, no import, no card. Everything here must be drivable end-to-end from Developer Tools → Services.

Deliberate omissions from M1:
- Staging services (`promote_staging`, `skip_staging`) — M4.
- Import services (`import_file`) — M5.
- FX lookup, `binary_sensor.splitsmart_fx_healthy`, `sensor.splitsmart_pending_count_<user>` — M3/M4.
- Telegram, vision — M6.
- Custom card — M2.
- Foreign-currency entries — M3. In M1, `currency` must equal `home_currency`; `home_amount`, `fx_rate=1.0`, `fx_date=date` are filled automatically.

Amendments applied (decisions from plan review):
1. `python-ulid>=2.2` added to requirements — no hand-rolling.
2. All write services use `SupportsResponse.OPTIONAL`, return `{"id": new_record_id}`.
3. `config.json` mirror dropped from M1.
4. Tombstone materialisation rule simplified — see §2.2.
5. `edit_*` handlers write the new record **before** the tombstone.
6. `async_track_time_change` cleaned up via `entry.async_on_unload`.
7. Options-change listener calls `coordinator.async_invalidate()` + refresh.

---

## 1. Config flow (`config_flow.py`)

Single instance only (enforce `_async_current_entries()` check on `async_step_user`). Flow uses modern `ConfigFlow` + `OptionsFlowHandler` patterns; no YAML config.

### Initial flow (first install)

| Step id | Shows | Validates | Writes to `config_entry.data` |
|---|---|---|---|
| `user` | Welcome copy + disclosure that data is stored under `/config/splitsmart/`. Single "Continue" button (a form with no user input fields). | — | `{}` (transient; collected across next steps) |
| `participants` | Multi-select of HA users from `hass.auth.async_get_users()`, filtered to non-system, non-owner-only-if-alone. Labelled with display name. | Min 2 selected; no duplicates. | `participants: list[str]` (HA user ids, order = display order) |
| `currency` | Single-select from an ISO-4217 list, common currencies pinned to the top (GBP, EUR, USD, CAD, AUD). Default GBP. | Valid 3-letter code. | `home_currency: str` |
| `categories` | Multi-line text input, prefilled with `Groceries, Utilities, Rent, Eating out, Transport, Household, Entertainment, Other`. Split on newlines or commas. | Min 1, no blanks, no duplicates (case-insensitive). Normalised to title case. | `categories: list[str]` |
| `finish` | Summary of choices + confirmation button. | — | Entry is created via `async_create_entry(title="Splitsmart", data=...)`. |

Written entry shape:
```python
{
    "participants": ["user_abc", "user_def"],
    "home_currency": "GBP",
    "categories": ["Groceries", "Utilities", ...],
    "named_splits": {},   # empty; populated by options flow in later milestones
}
```

### Options flow (re-enter via Integrations → Configure)

| Step id | Purpose |
|---|---|
| `init` | Menu: "Currency", "Categories", "Named splits" (stub for later). |
| `currency` | Same picker as initial; writes back to `entry.options["home_currency"]`. |
| `categories` | Same editor as initial. Adding categories: harmless. Removing a category used by historical expenses: warning but allowed (ledger treats unknown historical categories as a soft flag, per SPEC §9.6). Writes `entry.options["categories"]`. |
| `named_splits` | Stub that writes `{}` for M1 — real UI lands with rules in M4. |

Participants are **not** reconfigurable from options flow — SPEC §16 requires an integration reload. An `async_step_reconfigure` handler re-enters at the `participants` step and reloads the entry.

### Entry loading (`__init__.py`)

On `async_setup_entry`:
1. Resolve `storage_root = Path(hass.config.path("splitsmart"))`.
2. `validate_root(storage_root)` — refuses if under `/config/www/`.
3. `storage = SplitsmartStorage(storage_root); await storage.ensure_layout()`.
4. `coordinator = SplitsmartCoordinator(hass, storage, participants=entry.data["participants"]); await coordinator.async_config_entry_first_refresh()`.
5. Store on `hass.data[DOMAIN][entry.entry_id] = {"storage": storage, "coordinator": coordinator, "entry": entry}`.
6. `await hass.config_entries.async_forward_entry_setups(entry, ["sensor"])`.
7. Register services once on `hass.data[DOMAIN]` (guarded so a second entry-load doesn't re-register).
8. `entry.async_on_unload(entry.add_update_listener(_async_options_updated))` — the listener calls `coordinator.async_invalidate()` then `coordinator.async_refresh()` so category/currency changes take effect without reloading the entry.

`async_unload_entry` tears down sensors and pops `hass.data[DOMAIN][entry.entry_id]`. Services deregister when the last entry unloads.

---

## 2. Public API signatures

All files use `from __future__ import annotations`. Signatures only; no bodies.

### 2.1 `storage.py`

```python
from __future__ import annotations

import pathlib
from collections.abc import AsyncIterator
from typing import Any


class SplitsmartStorage:
    """Append-only JSONL storage under /config/splitsmart/. All IO is async."""

    def __init__(self, root: pathlib.Path) -> None: ...

    # --- layout ---

    async def ensure_layout(self) -> None:
        """Create the directory tree if missing. Raises if `root` is unsafe."""

    # --- typed path accessors ---

    @property
    def expenses_path(self) -> pathlib.Path: ...
    @property
    def settlements_path(self) -> pathlib.Path: ...
    @property
    def tombstones_path(self) -> pathlib.Path: ...
    def staging_path(self, user_id: str) -> pathlib.Path: ...

    # --- generic JSONL primitives ---

    async def append(self, path: pathlib.Path, record: dict[str, Any]) -> None:
        """Serialise `record` as one JSON line and fsync-append it."""

    async def read_all(self, path: pathlib.Path) -> list[dict[str, Any]]:
        """Return every record in the file (order = file order). Missing file → []."""

    async def read_since(
        self,
        path: pathlib.Path,
        since_id: str | None,
    ) -> list[dict[str, Any]]:
        """Return records strictly after `since_id`. `None` → same as read_all."""

    async def iter_lines(self, path: pathlib.Path) -> AsyncIterator[dict[str, Any]]:
        """Stream records without materialising the full list."""

    # --- tombstone helper ---

    async def append_tombstone(
        self,
        *,
        created_by: str,
        target_type: str,        # "expense" | "settlement" | "staging"
        target_id: str,
        operation: str,          # "edit" | "delete" | "discard"
        previous_snapshot: dict[str, Any],
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Append a tombstone record; return the written record (with id + timestamp)."""


# --- module-level helpers ---

def new_id(prefix: str) -> str:
    """ULID with a typed prefix, e.g. 'ex_01J9X...'. Prefixes per CLAUDE.md."""

def validate_root(root: pathlib.Path) -> None:
    """Raise ValueError if `root` falls under /config/www/ or is otherwise unsafe."""
```

Notes:
- File locking: each coroutine opens its own `aiofiles` handle in append mode. Appends of lines < 4 KB are atomic on POSIX; on Windows we rely on the event-loop single-writer serialisation (only the coordinator writes, services await before scheduling further IO).
- No rewrite-in-place path. Period.

### 2.2 `ledger.py`

Pure. No HA, no IO, no logging at INFO. All money computations use `Decimal` internally; inputs and outputs at the boundary are plain floats (2dp) to match on-disk storage.

```python
from __future__ import annotations

from decimal import Decimal
from typing import Any, TypedDict


# --- errors ---

class SplitsmartValidationError(ValueError):
    """Raised when a record fails invariants. Message is user-facing."""


# --- materialisation (apply tombstones on top of raw logs) ---

def materialise_expenses(
    raw_expenses: list[dict[str, Any]],
    tombstones: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return effective expense list. Drop any expense whose id appears as
    target_id in any tombstone — whether that tombstone is an edit or a delete.
    No chain-following needed: edit writes the new record first, tombstone second,
    so only the old id is ever targeted."""

def materialise_settlements(
    raw_settlements: list[dict[str, Any]],
    tombstones: list[dict[str, Any]],
) -> list[dict[str, Any]]: ...


# --- balance calculators ---

def compute_user_share(expense: dict[str, Any], user_id: str) -> Decimal:
    """Sum of `user_id`'s per-allocation share across every category."""

def compute_balances(
    expenses: list[dict[str, Any]],
    settlements: list[dict[str, Any]],
) -> dict[str, Decimal]:
    """Net per user. Positive => owed to them. Negative => they owe.
    Inputs are materialised (post-tombstone) lists."""

def compute_pairwise_balances(
    expenses: list[dict[str, Any]],
    settlements: list[dict[str, Any]],
) -> dict[tuple[str, str], Decimal]:
    """Directed: result[(a, b)] = amount `a` currently owes `b`.
    For 2-person setups this reduces to the couple's single debt figure;
    kept general for N participants."""


# --- monthly spending ---

class MonthlySpending(TypedDict):
    total: Decimal
    by_category: dict[str, Decimal]

def compute_monthly_spending(
    expenses: list[dict[str, Any]],
    user_id: str | None,   # None => household total
    year: int,
    month: int,
) -> MonthlySpending: ...


# --- validation ---

def validate_expense_record(
    record: dict[str, Any],
    *,
    participants: set[str],
    home_currency: str,
    known_categories: set[str],
) -> None:
    """Enforces SPEC §9.6 on every write path. Raises SplitsmartValidationError."""

def validate_settlement_record(
    record: dict[str, Any],
    *,
    participants: set[str],
    home_currency: str,
) -> None: ...

def validate_allocation(
    allocation: dict[str, Any],
    *,
    participants: set[str],
) -> None: ...

def validate_split(
    split: dict[str, Any],
    *,
    allocation_amount: Decimal,
    participants: set[str],
) -> None: ...


# --- record builders (used by services to go from service call → record) ---

def build_expense_record(
    *,
    date: str,
    description: str,
    paid_by: str,
    amount: float,
    currency: str,
    home_currency: str,
    categories: list[dict[str, Any]],
    notes: str | None,
    source: str,
    staging_id: str | None,
    receipt_path: str | None,
    created_by: str,
) -> dict[str, Any]:
    """Populate id, created_at, home_amount, fx_rate=1.0, fx_date=date. M1 requires
    currency == home_currency (FX is M3)."""

def build_settlement_record(
    *,
    date: str,
    from_user: str,
    to_user: str,
    amount: float,
    currency: str,
    home_currency: str,
    notes: str | None,
    created_by: str,
) -> dict[str, Any]: ...
```

### 2.3 `coordinator.py`

```python
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .storage import SplitsmartStorage


@dataclass
class SplitsmartData:
    """Projection held in memory. Sensors read from this; never from disk."""
    raw_expenses: list[dict[str, Any]] = field(default_factory=list)
    raw_settlements: list[dict[str, Any]] = field(default_factory=list)
    tombstones: list[dict[str, Any]] = field(default_factory=list)

    expenses: list[dict[str, Any]] = field(default_factory=list)       # materialised
    settlements: list[dict[str, Any]] = field(default_factory=list)    # materialised

    balances: dict[str, Decimal] = field(default_factory=dict)
    pairwise: dict[tuple[str, str], Decimal] = field(default_factory=dict)

    last_expense_id: str | None = None
    last_settlement_id: str | None = None
    last_tombstone_id: str | None = None
    last_refresh_full: bool = True


class SplitsmartCoordinator(DataUpdateCoordinator[SplitsmartData]):
    """Caches the materialised ledger. Full replay on startup; incremental on writes."""

    storage: SplitsmartStorage
    participants: list[str]
    home_currency: str
    categories: list[str]

    def __init__(
        self,
        hass: HomeAssistant,
        storage: SplitsmartStorage,
        *,
        participants: list[str],
        home_currency: str,
        categories: list[str],
    ) -> None: ...

    # DataUpdateCoordinator override — invoked by first refresh and by the
    # safety-net poll (update_interval ~5 min).
    async def _async_update_data(self) -> SplitsmartData:
        """Full replay: read all three logs, materialise, compute balances."""

    # Called by services right after a successful write.
    async def async_note_write(self) -> None:
        """Incremental refresh: read_since each log, re-materialise, re-compute,
        then async_set_updated_data(new)."""

    # Explicit invalidation (used in tests and after options-flow edits).
    async def async_invalidate(self) -> None:
        """Force a full replay on next tick."""
```

Caching strategy:
- **Startup:** full replay via `async_config_entry_first_refresh()`.
- **Writes:** services call `await coordinator.async_note_write()` after the storage append succeeds. This reads only new lines using `last_*_id`, appends to the in-memory raw lists, re-runs `materialise_*` and `compute_balances`, then calls `async_set_updated_data`.
- **Safety net:** `update_interval = timedelta(minutes=5)` triggers a full replay — catches manual edits to the JSONL files.
- **Re-materialisation on tombstones** is cheap (O(n)) at household scale, so we don't bother with diff-application — tombstones are the one path that invalidates everything historical.

---

## 3. Services

Registered once per integration on first entry setup. Schemas in `services.yaml` for UI discoverability; Python-side validation via `voluptuous` in `services.py` (new file — keeps `__init__.py` thin).

Shared fragments:

```python
import voluptuous as vol
from homeassistant.helpers import config_validation as cv

SPLIT_SCHEMA = vol.Schema({
    vol.Required("method"): vol.In(["equal", "percentage", "shares", "exact"]),
    vol.Required("shares"): vol.All(
        cv.ensure_list,
        vol.Length(min=1),
        [vol.Schema({
            vol.Required("user_id"): cv.string,
            vol.Required("value"): vol.Coerce(float),
        })],
    ),
})

CATEGORY_ALLOCATION_SCHEMA = vol.Schema({
    vol.Required("name"): cv.string,
    vol.Required("home_amount"): vol.Coerce(float),
    vol.Required("split"): SPLIT_SCHEMA,
})
```

### 3.1 `splitsmart.add_expense`

```python
ADD_EXPENSE_SCHEMA = vol.Schema({
    vol.Required("date"): cv.date,
    vol.Required("description"): vol.All(cv.string, vol.Length(min=1, max=200)),
    vol.Required("paid_by"): cv.string,
    vol.Required("amount"): vol.All(vol.Coerce(float), vol.Range(min=0.01)),
    vol.Optional("currency"): vol.All(cv.string, vol.Length(min=3, max=3)),   # default = home
    vol.Required("categories"): vol.All(
        cv.ensure_list, vol.Length(min=1), [CATEGORY_ALLOCATION_SCHEMA]
    ),
    vol.Optional("notes"): vol.Any(None, cv.string),
    vol.Optional("receipt_path"): vol.Any(None, cv.string),
    vol.Optional("source", default="manual"): vol.In(
        ["manual", "staging", "telegram", "recurring"]
    ),
    vol.Optional("staging_id"): vol.Any(None, cv.string),
})
```

Handler: check `call.context.user_id` is a configured participant → `build_expense_record` → `validate_expense_record` → `storage.append(expenses_path, ...)` → `coordinator.async_note_write()`. Returns `{"id": record["id"]}` via `SupportsResponse.OPTIONAL`.

### 3.2 `splitsmart.add_settlement`

```python
ADD_SETTLEMENT_SCHEMA = vol.Schema({
    vol.Required("date"): cv.date,
    vol.Required("from_user"): cv.string,
    vol.Required("to_user"): cv.string,
    vol.Required("amount"): vol.All(vol.Coerce(float), vol.Range(min=0.01)),
    vol.Optional("currency"): vol.All(cv.string, vol.Length(min=3, max=3)),
    vol.Optional("notes"): vol.Any(None, cv.string),
})
```

Extra validation in handler: `from_user != to_user`, both in participants.

### 3.3 `splitsmart.edit_expense`

Full replacement semantics, not a patch. The caller sends a complete new expense alongside the id being replaced. This keeps the service pure and avoids half-merge ambiguity.

```python
EDIT_EXPENSE_SCHEMA = ADD_EXPENSE_SCHEMA.extend({
    vol.Required("id"): cv.string,
    vol.Optional("reason"): vol.Any(None, cv.string),
})
```

Handler: look up the existing expense from coordinator → validate new record → **append new expense record first** (new id) → **then append tombstone** (`operation="edit"`, `target_id=old_id`, full prior snapshot). This order means a crash between the two appends leaves an extra live expense at worst — the safer failure mode. Both writes happen before `coordinator.async_note_write()`. Returns `{"id": new_record_id}`.

### 3.4 `splitsmart.delete_expense`

```python
DELETE_EXPENSE_SCHEMA = vol.Schema({
    vol.Required("id"): cv.string,
    vol.Optional("reason"): vol.Any(None, cv.string),
})
```

Handler: look up existing → append tombstone `operation="delete"` with full snapshot → refresh. No new expense record. Returns `{"id": target_id}`.

### 3.5 `splitsmart.edit_settlement`

```python
EDIT_SETTLEMENT_SCHEMA = ADD_SETTLEMENT_SCHEMA.extend({
    vol.Required("id"): cv.string,
    vol.Optional("reason"): vol.Any(None, cv.string),
})
```

### 3.6 `splitsmart.delete_settlement`

```python
DELETE_SETTLEMENT_SCHEMA = vol.Schema({
    vol.Required("id"): cv.string,
    vol.Optional("reason"): vol.Any(None, cv.string),
})
```

### Common handler concerns

- **Caller identity:** every handler resolves `caller = call.context.user_id`. If absent (e.g. invoked from a script with no user context), falls back to the entry's first participant and logs DEBUG.
- **Participant authorisation:** caller must be in `entry.data["participants"]`. Otherwise `ServiceValidationError`.
- **Per-field privacy:** expenses and settlements are shared; any participant can add/edit/delete. (Per-user edit locks are out of scope for M1.)
- **Currency lock in M1:** `currency` defaults to and must equal `home_currency`. Attempting a different currency raises `ServiceValidationError("foreign currency arrives in M3")`.
- **Error surface:** invalid schema → `vol.Invalid` which HA wraps. Business-rule errors → `homeassistant.exceptions.ServiceValidationError` with a translatable message key.

---

## 4. Sensor entities (`sensor.py`)

M1 sensors only — the ones whose state can be fully derived from the expense / settlement / tombstone logs. All backed by `CoordinatorEntity[SplitsmartCoordinator]`, all `state_class: total` (so they're never shown as cumulative in the statistics graphs), device-class `MONETARY` where applicable, `native_unit_of_measurement = home_currency`.

| Entity id pattern | One per | State | Attributes | Driven by |
|---|---|---|---|---|
| `sensor.splitsmart_balance_<user>` | participant | `float(balances[user])`, 2dp, positive = owed to them, negative = they owe | `per_partner: {user_b: <decimal>, ...}`, `home_currency` | `coordinator.data.balances`, `coordinator.data.pairwise` |
| `sensor.splitsmart_spending_<user>_month` | participant | user's share of shared spend for the current calendar month | `by_category: {"Groceries": 27.60, ...}`, `month: "2026-04"`, `home_currency` | `compute_monthly_spending(expenses, user, year, month)` on coordinator data |
| `sensor.splitsmart_spending_total_month` | integration | household total for the current month | same shape as above, user-less | `compute_monthly_spending(expenses, None, year, month)` |
| `sensor.splitsmart_last_expense` | integration | description of most recent shared expense (or `None`) | `amount`, `date`, `paid_by`, `expense_id` | last item of `coordinator.data.expenses` sorted by `created_at` |

Month-rollover handling: the "monthly" sensors listen via `async_track_time_change(hass, callback, hour=0, minute=0, second=1)` at midnight on the first of each month, then call `async_write_ha_state()` so recorders capture the reset cleanly. The unsubscribe callable is registered with `entry.async_on_unload(unsub)` so it cleans up on integration reload. No custom storage of "last seen month" needed — the state is a pure function of the log.

Intentionally NOT in M1 (each deferred to the milestone that earns it):
- `sensor.splitsmart_pending_count_<user>` — needs staging (M4).
- `binary_sensor.splitsmart_fx_healthy` — needs FX client (M3).

Display name is pulled from HA's user registry at entity-init time; if a user is later renamed the sensor updates on next restart. Unique IDs use `f"{entry.entry_id}_balance_{user_id}"` etc., never the display name.

---

## 5. Test plan

Dependencies to add in M1: `pytest-homeassistant-custom-component`, `pytest-asyncio` (already implied by `asyncio_mode = "auto"` in `pyproject.toml`), `freezegun` for month-rollover tests. Nothing else.

### 5.1 Pure unit tests (no HA event loop)

**`tests/test_storage.py`**
- `ensure_layout` creates every expected directory; idempotent.
- `validate_root` rejects `/config/www/...`, accepts `/config/splitsmart`.
- `new_id` yields sortable ULIDs with the expected prefix.
- `append` + `read_all` round-trip for expenses, settlements, tombstones, per-user staging.
- `read_since` returns only records after a given id; `since_id=None` returns all; `since_id=<last>` returns `[]`.
- Staging paths are isolated per user (file names match `user_id`).
- Concurrent appends via `asyncio.gather` of 100 writes produce 100 readable records with no truncation.
- Append of a record containing non-ASCII (e.g. "Café") round-trips.

**`tests/test_ledger.py`**
- `compute_user_share` for each split method (equal, percentage, shares, exact) on single- and multi-category expenses.
- `compute_balances` for 2-person and 3-person scenarios; verifies that settlements reduce balances correctly; verifies tombstoned (deleted) expenses don't contribute.
- `compute_pairwise_balances` reconciles with `compute_balances` (sum of owed-to = net balance).
- SPEC §9.3 worked example (the mixed Tesco shop): exact numeric match on balances and per-category spending attributes.
- `compute_monthly_spending` honours the month boundary (last second of April in a row → inside; first second of May → outside).
- `materialise_expenses` applies the *latest* edit tombstone when an expense is edited twice; returns nothing for a deleted expense.
- `validate_expense_record` rejects: sum drift > 1p, unknown category, negative allocation, empty categories list, split method `exact` whose shares don't sum to the allocation, `equal` with all-zero shares, `shares` with all-zero values, unknown user in shares, unknown `paid_by`.

### 5.2 Integration tests (HA event loop, tmp config dir)

Using `pytest-homeassistant-custom-component`'s `hass` fixture and its `tmp_path`-backed config directory.

**`tests/conftest.py`** — fixtures:
- `storage_root` → `tmp_path / "splitsmart"`.
- `two_user_hass` → `hass` with two users set up in the auth registry.
- `loaded_entry` → a config entry already through initial setup with two participants and default categories.
- `sample_expense_call` → a builder that returns valid service-call data for `add_expense`.

**`tests/test_config_flow.py`**
- Happy path walks every step, creating the entry with the expected `data` dict.
- `participants` step rejects fewer than 2 users.
- `categories` step normalises to title case and strips duplicates.
- Reconfigure flow re-enters at the `participants` step and reloads the entry.
- Options flow round-trip for currency and categories.

**`tests/test_services.py`** — each service end-to-end:
- `add_expense` with the Tesco-shop example → JSONL line on disk matches the expected shape; coordinator sees the new expense; `sensor.splitsmart_balance_user_def456` now reads `-36.95` and `sensor.splitsmart_spending_user_abc123_month` has `Alcohol: 8.50` in attributes.
- `add_expense` with `currency != home_currency` raises `ServiceValidationError` (M1 guard).
- `add_expense` with a non-participant `paid_by` raises `ServiceValidationError`.
- `add_settlement` reduces the owed balance by the exact amount.
- `edit_expense` writes a tombstone AND a replacement; the replacement id differs from the original; balances reflect the new amount; the `read_all` of tombstones contains one `operation="edit"` record with the full prior snapshot.
- `delete_expense` writes a tombstone-only; balances recalculate as if the expense never existed.
- `edit_settlement` and `delete_settlement` mirror the expense versions.
- Non-participant caller gets `ServiceValidationError` before any write.
- Editing a non-existent id gets `ServiceValidationError`.

**`tests/test_coordinator.py`**
- Startup full replay: seed a `shared/expenses.jsonl` with 3 rows before `async_setup_entry`; verify `coordinator.data.expenses` has 3 materialised rows.
- Incremental refresh: after `add_expense`, verify only one additional line was read (spy on `storage.read_since` via monkeypatch).
- Safety-net full replay (force `update_interval` tick) recovers from a manual file append.
- Editing via `edit_expense` re-materialises correctly (old row absent, new row present).

**`tests/test_sensors.py`**
- All expected entities exist after setup. Entity ids match the documented pattern.
- States update via `async_write_ha_state` when the coordinator pushes new data.
- Month rollover: freeze time to 2026-04-30 23:59:59, add an expense, assert it's in April's total; advance to 2026-05-01 00:00:01, assert the April expense is no longer in the monthly total and `sensor.splitsmart_spending_*_month` reset cleanly.
- `sensor.splitsmart_last_expense` state updates to the newest `created_at` row.

### 5.3 CI

`pytest -q tests/` runs everything. Target: all green on every PR, no warnings, no skips. Coverage target for pure modules (`ledger`, `storage`): 100%. For services + coordinator: happy path + every documented validation error.

---

## 6. Decisions (resolved)

1. **ULID library** — `python-ulid>=2.2` added to `manifest.json` requirements.
2. **Service responses** — all write services use `SupportsResponse.OPTIONAL`, return `{"id": ...}`.
3. **`config.json` mirror** — dropped. HA config entry is canonical; the file can wait until a concrete consumer needs it.
4. **Tombstone materialisation** — simplified to "drop any row whose id appears as any tombstone's `target_id`". No chain-following. Safe because edit always writes the new record before the tombstone (amendment 5).
5. **Windows append atomicity** — mitigated by single-writer rule. Concurrent-append test guards against POSIX regression.
6. **`native_unit_of_measurement`** — ISO code (e.g. `"GBP"`). Card renders the symbol.
