# ha-splitsmart

> **Status: M2 (Lovelace custom card) complete – not yet released.**

Every household expense starts private. Card statements, Telegram receipt photos and manual entries all land in the uploader's private staging inbox. The uploader decides – per row or via rules – whether each row becomes a shared expense (split with their partner), stays ignored, or waits for later review. Once promoted to the shared ledger, expenses contribute to live balance entities that HA dashboards, automations and the mobile companion can use like any other sensor. No cloud dependency beyond an optional FX rate feed and optional vision OCR API.

---

- [Specification](SPEC.md)
- [Development guide](CLAUDE.md)
- [Changelog](CHANGELOG.md)

---

## What works today (M1 + M2)

The data plane and the Lovelace custom card both ship. You can install the integration, run the config flow, drop a `custom:splitsmart-card` onto any dashboard, and add / edit / delete expenses entirely from the UI.

| Capability | Status |
|---|---|
| Config flow (participants, home currency, categories) | ✓ |
| Options flow (change currency or categories after setup) | ✓ |
| Append-only JSONL ledger with tombstone-based edits/deletes | ✓ |
| `add_expense` / `edit_expense` / `delete_expense` services | ✓ |
| `add_settlement` / `edit_settlement` / `delete_settlement` services | ✓ |
| Balance sensors per participant (`sensor.splitsmart_balance_<user>`) | ✓ |
| Monthly spending sensors per participant (`sensor.splitsmart_spending_<user>_month`) | ✓ |
| Household total monthly spend sensor (`sensor.splitsmart_spending_total_month`) | ✓ |
| Last expense sensor (`sensor.splitsmart_last_expense`) | ✓ |
| Split methods: equal, percentage, shares, exact | ✓ |
| Multi-category expense splitting | ✓ |
| Lovelace custom card: Home / Ledger / Add / Settle Up / Detail sheets | ✓ |
| Two-device realtime updates (websocket subscription with delta events) | ✓ |
| Self-hosted DM Sans + DM Mono (no fonts.googleapis.com call) | ✓ |
| Statement import pipeline | Not started (M3) |
| FX rate conversion | Not started (M4) |
| Rules engine | Not started (M5) |
| Staging inbox review UX | Not started (M5) |
| Telegram receipt OCR | Not started (M6) |

## Install

> HACS install instructions will be added once the first release is tagged. For now, copy `custom_components/splitsmart/` into your HA config directory and restart.

## Configure

1. **Settings → Devices & services → Add integration → Splitsmart**
2. Step 1 – enter the HA user IDs of all participants (minimum 2).
3. Step 2 – choose your home currency.
4. Step 3 – enter your expense categories, one per line (e.g. `Groceries`, `Household`, `Alcohol`).
5. Sensors appear immediately; no restart required.

To change categories or currency after setup: **Settings → Devices & services → Splitsmart → Configure**.

## Usage

### Adding the card to a dashboard

After installing the integration, the Lovelace resource auto-registers on storage-mode dashboards. Edit any dashboard → *Add Card* → search `Splitsmart`. Paste the following YAML for a fully-configured card (or leave it at just the `type` line to start on Home):

```yaml
type: custom:splitsmart-card
view: home    # optional: home | ledger | add | settle
```

YAML-mode Lovelace users: the integration logs the exact `resources:` snippet to paste into `ui-lovelace.yaml` on first load. See [tests/MANUAL_QA_M2.md §13](tests/MANUAL_QA_M2.md) for step-by-step.

The card covers the full loop: a balance strip with per-person totals, a ledger with month + category filter chips, a full add-expense form with multi-category allocation and per-category splits, settle-up with auto-filled pairwise-debt suggestions, and view / edit / delete sheets reachable from any ledger row.

### Recording an expense from automations

The add / edit / delete services also remain callable from automations, scripts, and Developer Tools:

```yaml
service: splitsmart.add_expense
data:
  date: "2026-04-20"
  description: "Tesco Metro"
  paid_by: "user_id_of_payer"
  amount: 82.40
  currency: GBP
  categories:
    - name: Groceries
      home_amount: 55.20
      split:
        method: equal
        shares:
          - user_id: alice
            value: 50
          - user_id: bob
            value: 50
    - name: Alcohol
      home_amount: 8.50
      split:
        method: exact
        shares:
          - user_id: alice
            value: 8.50
          - user_id: bob
            value: 0.00
```

The service returns `{"id": "ex_<ulid>"}` so automations can store the ID for later edits.

### Settling up

```yaml
service: splitsmart.add_settlement
data:
  date: "2026-04-20"
  from_user: "bob"
  to_user: "alice"
  amount: 36.95
```

### Editing or deleting

Pass the `id` returned by `add_expense` / `add_settlement` to `edit_expense`, `edit_settlement`, `delete_expense`, or `delete_settlement`. Edits create a new record; the original is tombstoned (append-only storage is never rewritten).

## Architecture overview

```
custom_components/splitsmart/
  storage.py               — async append-only JSONL read/write, per-path locking
  ledger.py                — pure functions: materialise, split, balance, monthly totals
  coordinator.py           — DataUpdateCoordinator: full replay on boot, incremental refresh on writes
  services.py              — six CRUD service handlers, voluptuous-validated
  websocket_api.py         — three websocket commands (config, list, subscribe)
  sensor.py                — four CoordinatorEntity sensor classes
  config_flow.py           — ConfigFlow + OptionsFlow (participants, currency, categories)
  frontend_registration.py — bundle + font static paths, Lovelace resource auto-register

frontend/
  src/      — Lit 3 + TypeScript sources for the custom card
  tests/    — vitest unit + component tests (jsdom)
```

Data lives in `<ha_config>/splitsmart/shared/`:
- `expenses.jsonl` – shared expense records
- `settlements.jsonl` – settlement records
- `tombstones.jsonl` – edit/delete markers (append-only audit trail)

## Development

```bash
# Install Python dependencies
pip install -e ".[test]"

# Run the Python suite (~108 tests, ~2 s)
pytest

# Lint and format
ruff check . && ruff format --check .

# Build the card bundle (outputs to custom_components/splitsmart/frontend/splitsmart-card.js)
cd frontend && npm ci && npm run build:prod

# Run the card test suite (~109 tests across 14 jsdom suites)
cd frontend && npm test
```

Config-flow tests require `pytest-homeassistant-custom-component` (Linux only). They are marked `ha_integration` and skipped by default:

```bash
pytest -m ha_integration   # Linux / CI only
```
