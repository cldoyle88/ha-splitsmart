# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added – M1 Data Plane (2026-04-20)

**Integration skeleton**
- `manifest.json`, `const.py`, and `__init__.py` scaffolding; HACS-compatible with `python-ulid`, `aiofiles`, `openpyxl`, `ofxparse` requirements.

**Config flow**
- Four-step `ConfigFlow`: welcome, participants (multi-select, minimum 2), home currency (dropdown), categories (textarea, title-cased, deduplicated).
- `async_step_reconfigure` to update participants from the integrations page.
- `OptionsFlow` with menu routing to currency and categories sub-steps.
- Single-instance guard; translations in `translations/en.json`.

**Storage (`storage.py`)**
- Append-only JSONL primitives: `append`, `read_all`, `read_since` (cursor-based incremental reads), `iter_lines` (async generator).
- ULID-prefixed IDs via `new_id(prefix)` (`ex_`, `sl_`, `tb_`, `st_`).
- Per-path `asyncio.Lock` preventing concurrent-write corruption on Windows.
- `append_tombstone` helper; typed path properties for all four log files.
- `validate_root` guard refusing paths under `/config/www/`.

**Ledger (`ledger.py`)**
- `materialise_expenses` / `materialise_settlements`: tombstone-based filtering (Amendment 4 – no chain-following required).
- Split calculators: `equal`, `percentage`, `shares`, `exact`.
- `compute_balances`, `compute_pairwise_balances`: `Decimal` arithmetic throughout.
- `compute_monthly_spending`: per-user monthly totals with per-category breakdown.
- `build_expense_record` / `build_settlement_record`: canonical record constructors.
- Full validation suite (`validate_split`, `validate_allocation`, `validate_expense_record`, `validate_settlement_record`) raising `SplitsmartValidationError`.

**Coordinator (`coordinator.py`)**
- `SplitsmartData` dataclass holding materialised expenses, settlements, balances, pairwise map, and last-seen ID cursors.
- `SplitsmartCoordinator(DataUpdateCoordinator)`: full replay on startup via `_async_update_data`; incremental refresh via `async_note_write` (reads only new lines since last cursor); graceful fallback to full replay on error.
- `async_invalidate` resets cursors for a clean replay on options change.

**Services (`services.py`, `services.yaml`)**
- Six CRUD services: `add_expense`, `edit_expense`, `delete_expense`, `add_settlement`, `edit_settlement`, `delete_settlement`.
- All return `{"id": <record_id>}` via `SupportsResponse.OPTIONAL`.
- Edit handlers append new record before tombstone (Amendment 5 – safer crash failure mode).
- Guards: caller must be a participant; M1 rejects foreign currencies (`ServiceValidationError` M3).
- Voluptuous schemas with full UI selectors in `services.yaml`.

**Sensors (`sensor.py`)**
- `BalanceSensor`: net balance per participant; attributes include `per_partner` breakdown and `home_currency`.
- `SpendingMonthSensor`: current-month spend per participant; attributes include `by_category`, `month`, `home_currency`.
- `SpendingTotalMonthSensor`: household total for the current month.
- `LastExpenseSensor`: description of the most recent shared expense; attributes include `amount`, `date`, `paid_by`, `expense_id`.
- Month-rollover listener via `async_track_time_change`; unsubscribed via `entry.async_on_unload`.

**Tests**
- 92 tests, 0 failures across five modules (`test_storage`, `test_ledger`, `test_coordinator`, `test_services`, `test_sensors`).
- Mock-based approach avoids `pytest-homeassistant-custom-component` (Linux-only) on Windows.
- Config-flow tests (9) marked `ha_integration`, skipped by default; run with `pytest -m ha_integration` on Linux/CI.
