# ha-splitsmart

> **Status: M1 (data plane) complete – not yet released.**

Every household expense starts private. Card statements, Telegram receipt photos and manual entries all land in the uploader's private staging inbox. The uploader decides – per row or via rules – whether each row becomes a shared expense (split with their partner), stays ignored, or waits for later review. Once promoted to the shared ledger, expenses contribute to live balance entities that HA dashboards, automations and the mobile companion can use like any other sensor. No cloud dependency beyond an optional FX rate feed and optional vision OCR API.

---

- [Specification](SPEC.md)
- [Development guide](CLAUDE.md)
- [Changelog](CHANGELOG.md)

---

## What works today (M1)

The data plane is complete and tested. You can install the integration, run the config flow, and interact with the shared ledger entirely via HA services.

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
| Split methods: equal, percentage, exact shares | ✓ |
| Multi-category expense splitting | ✓ |
| Lovelace custom card | Not started (M3) |
| Statement import pipeline | Not started (M2) |
| Rules engine | Not started (M4) |
| Telegram receipt OCR | Not started (M5) |
| FX rate conversion | Not started (M6) |

## Install

> HACS install instructions will be added once the first release is tagged. For now, copy `custom_components/splitsmart/` into your HA config directory and restart.

## Configure

1. **Settings → Devices & services → Add integration → Splitsmart**
2. Step 1 – enter the HA user IDs of all participants (minimum 2).
3. Step 2 – choose your home currency.
4. Step 3 – enter your expense categories, one per line (e.g. `Groceries`, `Household`, `Alcohol`).
4. Sensors appear immediately; no restart required.

To change categories or currency after setup: **Settings → Devices & services → Splitsmart → Configure**.

## Usage

### Recording an expense

Call the `splitsmart.add_expense` service from a dashboard button, an automation, or Developer Tools:

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
storage.py      — async append-only JSONL read/write, per-path locking
ledger.py       — pure functions: materialise, split, balance, monthly totals
coordinator.py  — DataUpdateCoordinator: full replay on boot, incremental refresh on writes
services.py     — six CRUD service handlers, voluptuous-validated
sensor.py       — four CoordinatorEntity sensor classes
config_flow.py  — ConfigFlow + OptionsFlow (participants, currency, categories)
```

Data lives in `<ha_config>/splitsmart/shared/`:
- `expenses.jsonl` – shared expense records
- `settlements.jsonl` – settlement records
- `tombstones.jsonl` – edit/delete markers (append-only audit trail)

## Development

```bash
# Install dependencies
pip install -e ".[test]"

# Run the test suite (92 tests, ~2 s)
pytest

# Lint and format
ruff check . && ruff format --check .
```

Config-flow tests require `pytest-homeassistant-custom-component` (Linux only). They are marked `ha_integration` and skipped by default:

```bash
pytest -m ha_integration   # Linux / CI only
```
