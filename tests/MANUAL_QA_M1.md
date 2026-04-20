# M1 Manual QA Checklist

Prerequisites: integration loaded, two HA users configured. This checklist uses
Chris (user_id `abc123`) and Slav (user_id `def456`), home currency GBP.

> **Entity IDs.** Sensors are attached to a device named "Splitsmart". With
> `_attr_has_entity_name = True`, HA prepends the device name to form the entity_id.
> Display names are resolved from the HA user registry at setup time; the IDs below
> assume the two HA users are named **Chris** and **Slav**.
>
> | Sensor | entity_id |
> |---|---|
> | Chris's balance | `sensor.splitsmart_balance_chris` |
> | Slav's balance | `sensor.splitsmart_balance_slav` |
> | Chris's monthly spend | `sensor.splitsmart_spending_this_month_chris` |
> | Slav's monthly spend | `sensor.splitsmart_spending_this_month_slav` |
> | Household monthly total | `sensor.splitsmart_total_spending_this_month` |
> | Last expense | `sensor.splitsmart_last_expense` |
>
> If your HA user display names differ, substitute accordingly.

---

## Step 1 – Add expense: £40 Waitrose shop, all Groceries, 50/50

Paste in Developer Tools → Services:

```yaml
service: splitsmart.add_expense
data:
  date: "2026-04-20"
  description: "Waitrose shop"
  paid_by: "abc123"
  amount: 40.00
  categories:
    - name: "Groceries"
      home_amount: 40.00
      split:
        method: "equal"
        shares:
          - user_id: "abc123"
            value: 1
          - user_id: "def456"
            value: 1
```

Enable "Return response" — expect `{"id": "ex_<ulid>"}`.

**Expected sensor states after step 1:**

| Entity | State | Key attributes |
|---|---|---|
| `sensor.splitsmart_balance_chris` | `20.0` | `per_partner: {def456: 20.0}`, `home_currency: GBP` |
| `sensor.splitsmart_balance_slav` | `-20.0` | `per_partner: {}` (Slav owes, key is (def456, abc123)) |
| `sensor.splitsmart_spending_this_month_chris` | `20.0` | `by_category: {Groceries: 20.0}`, `month: 2026-04` |
| `sensor.splitsmart_spending_this_month_slav` | `20.0` | `by_category: {Groceries: 20.0}`, `month: 2026-04` |
| `sensor.splitsmart_total_spending_this_month` | `40.0` | `by_category: {Groceries: 40.0}`, `month: 2026-04` |
| `sensor.splitsmart_last_expense` | `"Waitrose shop"` | `amount: 40.0`, `date: 2026-04-20`, `paid_by: abc123` |

Notes on `per_partner`: the balance sensor exposes `per_partner[b]` only for pairs `(user, b)` where the current user is `a`. After this expense, Slav owes Chris £20, so the pairwise entry is keyed `(def456, abc123)`. `sensor.balance_abc123.per_partner` will therefore be `{def456: 20.0}` (Chris is owed £20 by Slav); `sensor.balance_def456.per_partner` will be `{}` because Slav is `b` in the pair, not `a`.

---

## Step 2 – Add settlement: Slav pays Chris £20 to clear the balance

```yaml
service: splitsmart.add_settlement
data:
  date: "2026-04-20"
  from_user: "def456"
  to_user: "abc123"
  amount: 20.00
```

Enable "Return response" — expect `{"id": "sl_<ulid>"}`.

**Expected sensor states after step 2:**

| Entity | State | Key attributes |
|---|---|---|
| `sensor.splitsmart_balance_chris` | `0.0` | `per_partner: {def456: 0.0}` or key absent |
| `sensor.splitsmart_balance_slav` | `0.0` | — |
| `sensor.splitsmart_spending_this_month_chris` | `20.0` | unchanged — settlements don't affect spending |
| `sensor.splitsmart_spending_this_month_slav` | `20.0` | unchanged |
| `sensor.splitsmart_total_spending_this_month` | `40.0` | unchanged |
| `sensor.splitsmart_last_expense` | `"Waitrose shop"` | unchanged |

---

## Step 3 – Read sensors at each step

To read any sensor value from Developer Tools → Services:

```yaml
# This is a read via the HA states API, not a service call.
# In Developer Tools → States, filter by entity_id.
# Or use Template:  {{ states('sensor.splitsmart_balance_chris') }}
```

Spot-check attributes in Developer Tools → States → click the entity:
- `home_currency` should be `GBP` on all monetary sensors.
- `month` on spending sensors should be `2026-04` when run in April 2026.
- `expense_id` on `sensor.splitsmart_last_expense` should match the `id` returned by `add_expense`.

---

## Deviations from M1_PLAN.md

### §1 Config flow – `finish` step removed

> **Plan:** Step `finish` shows a summary of choices + a confirmation button; entry created via `async_create_entry` from within that step.
>
> **Code** ([config_flow.py:289](../custom_components/splitsmart/config_flow.py#L289)): Entry is created directly at the end of `async_step_categories`. There is no separate `finish` step.
>
> **Assessment:** Acceptable simplification. The summary step adds no functional value and removing it reduces friction.

---

### §1 Config flow – `user` step welcome text

> **Plan:** "`user` step shows welcome copy + disclosure that data is stored under `/config/splitsmart/`. Single 'Continue' button."
>
> **Code** ([config_flow.py:226](../custom_components/splitsmart/config_flow.py#L226)): `async_show_form(step_id="user", data_schema=vol.Schema({}))` — no description text is set in the Python layer. Any text must come from `translations/en.json`.
>
> **Assessment:** Acceptable if `translations/en.json` supplies the copy. Review the translation file to confirm the welcome text and disclosure are present.

---

### §1 Config flow – options flow omits "Named splits" menu item

> **Plan:** Options menu shows "Currency", "Categories", "Named splits" (stub that writes `{}`).
>
> **Code** ([config_flow.py:352–355](../custom_components/splitsmart/config_flow.py#L352)): `menu_options=["currency", "categories"]` — `named_splits` is entirely absent.
>
> **Assessment:** Acceptable deferral. The plan called it a stub; omitting the stub is equivalent for M1. The underlying config key is still written as `{}` by the initial flow.

---

### §1 Config flow – participant filter doesn't implement "non-owner-only-if-alone"

> **Plan:** Users filtered to "non-system, non-owner-only-if-alone".
>
> **Code** ([config_flow.py:203–208](../custom_components/splitsmart/config_flow.py#L203)): Filters on `system_generated` and `is_active` only. No special owner exclusion for the sole-user edge case.
>
> **Assessment:** Acceptable simplification. The "owner-only-if-alone" case is pathological — if there's only one active non-system user, the min-2-participants validation will catch the attempt anyway.

---

### §2.3 Coordinator – `last_refresh_full` field absent from `SplitsmartData`

> **Plan:** `SplitsmartData` dataclass includes `last_refresh_full: bool = True`.
>
> **Code** ([coordinator.py:27–43](../custom_components/splitsmart/coordinator.py#L27)): Field is not present. The implemented dataclass has the seven fields listed in the plan minus this one.
>
> **Assessment:** Acceptable simplification. The field appears in the plan's dataclass sketch but is never consumed by any code path described in the plan. Likely a remnant from an earlier design iteration.

---

### §4 Sensor entity_id pattern

> **Resolved in post-M1 fix commit.**
>
> A `device_info` with `name="Splitsmart"`, `model="Household finance"`, and
> `identifiers={(DOMAIN, entry.entry_id)}` was added to `_SplitsmartSensor`. With
> `_attr_has_entity_name = True`, HA now prepends the device name to form entity_ids
> matching the plan's documented pattern.

---

### §4 Sensor name uses user_id, not display name

> **Resolved in post-M1 fix commit.**
>
> `async_setup_entry` now calls `await hass.auth.async_get_user(user_id)` for each
> participant and passes the resolved display name into the sensor constructor. Falls
> back to `user_id` if the user has been deleted. Unique IDs remain keyed on `user_id`
> (stable across renames).

---

### §2.2 `build_settlement_record` drops `created_by`

> **Resolved in post-M1 fix commit.**
>
> `build_settlement_record` now writes `"created_by": created_by` into the returned
> dict, consistent with `build_expense_record`. A test in `test_ledger.py` asserts the
> field is present on the returned record.

---

### §3 services.yaml – edit/delete fields lack descriptions and examples

> **Resolved in post-M1 fix commit.**
>
> All fields in `edit_expense`, `delete_expense`, `edit_settlement`, and
> `delete_settlement` now have `description` and `example` entries matching the style
> of `add_expense`.

---

### §3 services.yaml – no `supports_response` key

> **Plan amendment 2:** "All write services use `SupportsResponse.OPTIONAL`, return `{"id": ...}`."
>
> **Code** ([services.py:427](../custom_components/splitsmart/services.py#L427) et seq.): `SupportsResponse.OPTIONAL` is declared at registration time — correct. `services.yaml` has no `supports_response` or `response_fields` entry.
>
> **Assessment:** Not a gap. In HA 2024.x, `supports_response` is a registration-time flag; the "Return response" checkbox appears in Developer Tools automatically. No services.yaml declaration is required or expected.

---

### §3 `edit_expense` handler – `receipt_path` fall-through from existing record

> **Plan §3.3:** "The caller sends a complete new expense alongside the id being replaced."
>
> **Code** ([services.py:271](../custom_components/splitsmart/services.py#L271)): `receipt_path=data.get("receipt_path", existing.get("receipt_path"))` — if the caller omits `receipt_path`, the existing receipt_path is silently carried forward. This is a partial-patch for one field.
>
> **Assessment:** Acceptable improvement over strict full-replacement semantics. Callers shouldn't be required to re-specify a receipt path they didn't change. Worth documenting explicitly if the M2 card surfaces edit flows.
