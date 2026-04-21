# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added – M2 Lovelace Custom Card (2026-04-21)

**Build pipeline**
- `frontend/` Rollup + Lit 3 + TypeScript pipeline. Single ES module
  output to `custom_components/splitsmart/frontend/splitsmart-card.js`.
  `vitest` + `@open-wc/testing-helpers` for component and helper tests.
- Bundle and sourcemap are gitignored; CI builds reproducibly from
  `package-lock.json`. GitHub Releases ship the zipped integration.
- Frontend CI job enforces a 150 KB minified bundle-size budget. M2
  ships at ~117 KB (78% of budget).

**Self-hosted fonts**
- DM Sans (variable, covers 400/500/600/700) and DM Mono (400/500)
  served from `/splitsmart-static/fonts/` alongside the bundle. No
  runtime dependency on `fonts.googleapis.com`; pi-holed / offline /
  corporate-proxy HA installs render identically.
- `@font-face` injected into `document.head` on first element mount
  via `ensureFontsLoaded()` — shadow-root `@font-face` does not
  register fonts for the document.

**Backend websocket API (`websocket_api.py`)**
- `splitsmart/get_config`: bootstrap payload — participants (with
  `active` flag so former participants still render), home currency,
  categories, named splits, current user id.
- `splitsmart/list_expenses`: filtered expense + settlement read.
  Supports `month`, `category`, `paid_by` filters.
- `splitsmart/list_expenses/subscribe`: long-lived subscription.
  Initial snapshot then delta events (`added` / `updated` / `deleted`)
  driven by the DataUpdateCoordinator's listener hook — two devices
  watching the same household see updates within one second of any
  write.
- Every payload carries `version: 1` so the contract can evolve.
- Non-participant callers get `permission_denied`.

**Integration serving (`frontend_registration.py`)**
- `async_register_static_paths` for the bundle (no cache, versioned
  via `?v=` query string) and the fonts directory (cache_headers=True).
- Auto-registration of the Lovelace module resource in storage-mode
  Lovelace via `hass.data['lovelace'].resources`. YAML-mode Lovelace
  users receive an INFO log with the exact snippet to paste into
  `ui-lovelace.yaml`. Works on both the newer `LovelaceData` dataclass
  and the older dict shape.
- Guarded by `_static_registered` / `_resource_registered` flags so
  entry reloads never double-register.

**Custom card (`frontend/src/`)**
- `<splitsmart-card>`: root element. Owns `hass`, `_route`, the
  hydrated config, and the materialised expense / settlement lists.
  On mount calls `getConfig` + `listExpenses` and subscribes to
  deltas. Registers the gallery entry via `window.customCards`.
  Accepts optional `view: home|ledger|add|settle` config to pin a
  starting view.
- Hash-based router (`router.ts`): `#home`, `#ledger?month=...&category=...`,
  `#add`, `#settle`, `#expense/<id>`, `#settlement/<id>`. Browser
  back button and deep-linking both work. Unknown / malformed hashes
  fall back to home.
- Typed API wrapper (`api.ts`) — one function per websocket command
  and one per M1 service call. Payload types colocated.
- Design tokens at `:root` scope (`styles.ts`): --ss-space-1..8,
  typography scale (DM Sans display/title/body/button/caption, DM
  Mono display/amount/caption), motion tokens, credit/debit semantic
  pair, accent passthrough, --ss-touch-min 44 px.
- Base components: `<ss-icon>`, `<ss-button>` (primary / secondary /
  destructive), `<ss-modal>` (mobile slide-up, desktop dialog,
  escape/backdrop dismiss), `<ss-user-avatar>` (deterministic tint,
  former-participant opacity), `<ss-empty-state>`,
  `<ss-placeholder-tile>` (Staging "Coming in M5" on Home only).
- Form primitives: `<ss-amount-input>`, `<ss-category-picker>`,
  `<ss-split-picker>`, `<ss-allocation-editor>` (amount/percent
  toggle, last-row rounding absorption, live remainder indicator).
- Display components: `<ss-balance-strip>`, `<ss-row-card>`
  (default + compact variants).
- Views: `<ss-home-view>` (two-person and N≥3 hero phrasing, two
  distinct empty states, quick actions, Staging placeholder, latest-
  expense tile), `<ss-ledger-view>` (reverse-chronological timeline,
  inline month+category filter chips, settlements interleaved),
  `<ss-add-expense-view>` (single-category default, multi-category
  toggle, uniform-vs-per-category split toggle), `<ss-settle-up-view>`
  (auto-fills suggested amount from pairwise debt), and the detail
  sheets for expenses and settlements (view + edit + delete).
- Client-side ledger math (`util/balances.ts`) mirrors `ledger.py`
  so deltas re-render without a round-trip.

**Tests**
- 100 frontend tests across 12 suites: router (22), api (13),
  currency (21), date (12), balances (9), split-picker helpers (9),
  plus component smoke tests for button, icon, modal, user-avatar,
  empty-state, placeholder-tile.
- Backend tests expanded: 14 new `test_websocket_api.py` tests
  covering happy paths, historical-inactive-user resolution,
  permission_denied, not_found, and delta push on coordinator update.
  Python suite total: 108 tests.
- `tests/MANUAL_QA_M2.md` — 17-section Pi QA checklist covering
  first paint, theme coverage, responsive + touch, typography, two-
  person and multi-category add, Ledger filters, Detail sheet edit
  and delete, Settle up, mobile companion, two-device realtime,
  YAML-mode fallback, placeholder tiles, card `view` option,
  former participants.

**CI**
- Existing `test` job expanded with Python package discovery config
  for the new sibling directories.
- New `frontend` job: `npm ci`, `npm run typecheck`, `npm run test`,
  `npm run build:prod`, assert bundle size ≤ 150 KB.

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
