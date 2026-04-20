# M1 Manual QA Checklist

Prerequisites: integration loaded, two HA users configured. This checklist uses
Chris (user_id `abc123`) and Slav (user_id `def456`), home currency GBP.

> **Entity ID note.** The code derives entity_ids from the sensor `name` property,
> not from the plan's documented pattern. The actual IDs are:
>
> | Sensor | Actual entity_id |
> |---|---|
> | Chris's balance | `sensor.balance_abc123` |
> | Slav's balance | `sensor.balance_def456` |
> | Chris's monthly spend | `sensor.spending_this_month_abc123` |
> | Slav's monthly spend | `sensor.spending_this_month_def456` |
> | Household monthly total | `sensor.total_spending_this_month` |
> | Last expense | `sensor.last_expense` |
>
> Substitute your real user_ids for `abc123` / `def456`.

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
| `sensor.balance_abc123` | `20.0` | `per_partner: {def456: 20.0}`, `home_currency: GBP` |
| `sensor.balance_def456` | `-20.0` | `per_partner: {}` (Slav owes, key is (def456, abc123)) |
| `sensor.spending_this_month_abc123` | `20.0` | `by_category: {Groceries: 20.0}`, `month: 2026-04` |
| `sensor.spending_this_month_def456` | `20.0` | `by_category: {Groceries: 20.0}`, `month: 2026-04` |
| `sensor.total_spending_this_month` | `40.0` | `by_category: {Groceries: 40.0}`, `month: 2026-04` |
| `sensor.last_expense` | `"Waitrose shop"` | `amount: 40.0`, `date: 2026-04-20`, `paid_by: abc123` |

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
| `sensor.balance_abc123` | `0.0` | `per_partner: {def456: 0.0}` or key absent |
| `sensor.balance_def456` | `0.0` | — |
| `sensor.spending_this_month_abc123` | `20.0` | unchanged — settlements don't affect spending |
| `sensor.spending_this_month_def456` | `20.0` | unchanged |
| `sensor.total_spending_this_month` | `40.0` | unchanged |
| `sensor.last_expense` | `"Waitrose shop"` | unchanged |

---

## Step 3 – Read sensors at each step

To read any sensor value from Developer Tools → Services:

```yaml
# This is a read via the HA states API, not a service call.
# In Developer Tools → States, filter by entity_id.
# Or use Template:  {{ states('sensor.balance_abc123') }}
```

Spot-check attributes in Developer Tools → States → click the entity:
- `home_currency` should be `GBP` on all monetary sensors.
- `month` on spending sensors should be `2026-04` when run in April 2026.
- `expense_id` on `sensor.last_expense` should match the `id` returned by `add_expense`.

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

> **Plan:**
> ```
> sensor.splitsmart_balance_<user>
> sensor.splitsmart_spending_<user>_month
> sensor.splitsmart_spending_total_month
> sensor.splitsmart_last_expense
> ```
>
> **Code** ([sensor.py:110](../custom_components/splitsmart/sensor.py#L110), [sensor.py:158](../custom_components/splitsmart/sensor.py#L158), [sensor.py:205](../custom_components/splitsmart/sensor.py#L205), [sensor.py:244](../custom_components/splitsmart/sensor.py#L244)): Names are `f"Balance {user_id}"`, `f"Spending this month {user_id}"`, `"Total spending this month"`, `"Last expense"`. No device_info is set, so `_attr_has_entity_name = True` does not add a "splitsmart" prefix. HA slugifies the name directly:
>
> | Plan | Actual |
> |---|---|
> | `sensor.splitsmart_balance_abc123` | `sensor.balance_abc123` |
> | `sensor.splitsmart_spending_abc123_month` | `sensor.spending_this_month_abc123` |
> | `sensor.splitsmart_spending_total_month` | `sensor.total_spending_this_month` |
> | `sensor.splitsmart_last_expense` | `sensor.last_expense` |
>
> **Assessment:** Unreconciled difference. The documented patterns are what automation authors and integration tests will reference. Either add a `device_info` with name "Splitsmart" to prefix the entity_ids, or update the plan and test assertions to match the actual slugs. Recommend resolving before M2.

---

### §4 Sensor name uses user_id, not display name

> **Plan:** "Display name is pulled from HA's user registry at entity-init time; if a user is later renamed the sensor updates on next restart."
>
> **Code** ([sensor.py:110](../custom_components/splitsmart/sensor.py#L110), [sensor.py:158](../custom_components/splitsmart/sensor.py#L158)): `return f"Balance {self._user_id}"` — raw user_id, not the HA display name. No call to `hass.auth.async_get_user(user_id)`.
>
> **Assessment:** Unreconciled difference. Sensors will be labelled `Balance abc123` rather than `Balance Chris`, which is poor UX and contradicts the plan. The fix is straightforward: resolve the display name during `async_setup_entry` and pass it into the sensor constructor. Recommend fixing before M2.

---

### §2.2 `build_settlement_record` drops `created_by`

> **Plan:** `build_settlement_record` signature includes `created_by: str`.
>
> **Code** ([ledger.py:394–418](../custom_components/splitsmart/ledger.py#L394)): The parameter is accepted but is not written into the returned dict. Settlement records have no `created_by` field on disk.
>
> **Assessment:** Unreconciled difference. The expense record does store `created_by` ([ledger.py:376](../custom_components/splitsmart/ledger.py#L376)), so settlements are inconsistent. Minor audit-trail gap. Fix before M2.

---

### §3 services.yaml – edit/delete fields lack descriptions and examples

> **Plan intent:** "I want to eyeball that every service renders usefully in Developer Tools → Services."
>
> **Code** ([services.yaml:100–222](../custom_components/splitsmart/services.yaml#L100)): `edit_expense`, `edit_settlement`, `delete_expense`, and `delete_settlement` fields beyond `id` and `reason` have `name` only — no `description`, no `example`. In Developer Tools, a tester filling in `edit_expense` will see unlabelled fields for date, paid_by, amount, categories, and notes.
>
> **Assessment:** Acceptable simplification for M1, but a usability gap. The `add_expense` fields' descriptions and examples should be copied across to `edit_expense`. Low effort; recommend doing before M2 release prep.

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
