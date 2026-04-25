# M4 Manual QA Checklist

Run these checks against a live HA instance (dev container or Pi) with the M4 branch installed.
Tick each item before merging the PR.

---

## Prerequisites

- HA running with the `ha-splitsmart` integration loaded.
- At least two participants configured (`u1`, `u2` or real user IDs).
- `home_currency: GBP`.
- Developer Tools → Services tab open for service calls.

---

## 1 – Foreign-currency staging import

1. Upload a Revolut CSV containing GBP, EUR, and USD rows via the HTTP upload endpoint.
2. Call `splitsmart.import_file` on the upload.
3. Confirm: GBP rows land in staging as usual; EUR + USD rows also land in staging.
4. Confirm: the `pending_count` sensor's `blocked_foreign_currency_count` attribute reflects the EUR + USD count.

Pass criterion: counts match.

---

## 2 – Promote EUR row (live FX lookup)

1. Call `splitsmart.promote_staging` on an EUR staged row (no `fx_rate` override).
2. Confirm: `fx_rates.jsonl` contains a new entry for EUR → GBP on today's date.
3. Confirm: promoted expense's `home_amount` equals `amount × rate` rounded to 2 dp.
4. Confirm: expense appears in the Lovelace card's Ledger tab with the correct GBP figure.

Pass criterion: `home_amount` matches arithmetic; ledger card shows the entry.

---

## 3 – Cache hit on same-day promotion

1. Promote a second EUR staged row the same calendar day.
2. Check HA log (DEBUG level): no new Frankfurter network call logged.
3. Confirm: `fx_rates.jsonl` has only one entry for this date (no duplicate append).

Pass criterion: cache hit confirmed in log; no duplicate JSONL row.

---

## 4 – Offline add-expense fails gracefully

1. Disconnect the HA host from the internet (disable Wi-Fi or block DNS).
2. Call `splitsmart.add_expense` with `currency: USD` (not cached for today).
3. Confirm: service raises `ServiceValidationError` containing "Frankfurter" or "unreachable".
4. Confirm: no new expense record written.

Pass criterion: clean error, no partial write.

---

## 5 – Retry after reconnect

1. Restore internet access.
2. Retry the same `splitsmart.add_expense` call.
3. Confirm: expense written successfully; `home_amount` correct.

Pass criterion: success on retry.

---

## 6 – Edit GBP expense to EUR

1. Take an existing M1/M2 GBP expense.
2. Call `splitsmart.edit_expense` changing `currency` to EUR (no `fx_rate` override).
3. Confirm: tombstone written for the original; new expense written with `currency: EUR`.
4. Confirm: `home_amount` reflects the FX conversion; balance updates in the card.

Pass criterion: tombstone + new record; correct home_amount.

---

## 7 – Recurring materialisation (basic)

1. Write `recurring.yaml` (see example below) with one monthly entry due today.
2. Call `splitsmart.materialise_recurring` from Developer Tools.
3. Confirm: service returns `{"materialised": 1, "skipped_fx_failure": 0, "skipped_duplicate": 0}`.
4. Confirm: new expense in `expenses.jsonl` with `source: "recurring"` and `recurring_id` set.

Example `recurring.yaml`:
```yaml
recurring:
  - id: netflix
    description: Netflix
    amount: 15.99
    currency: GBP
    paid_by: u1
    categories:
      - name: Subscriptions
        home_amount: 15.99
        split:
          method: equal
          shares:
            - {user_id: u1, value: 50}
            - {user_id: u2, value: 50}
    schedule:
      kind: monthly
      day: <today's day>
    start_date: <today's date>
```

Pass criterion: 1 expense written with correct fields.

---

## 8 – Materialisation idempotency (state-file belt)

1. Call `splitsmart.materialise_recurring` a second time immediately.
2. Confirm: returns `{"materialised": 0, "skipped_fx_failure": 0, "skipped_duplicate": 0}`.
3. Confirm: `expenses.jsonl` still has exactly 1 entry for this recurring.

Pass criterion: second call is a no-op.

---

## 9 – Idempotency when state file deleted (expense-scan belt)

1. Delete `recurring_state.jsonl` from the splitsmart config directory.
2. Call `splitsmart.materialise_recurring` again.
3. Confirm: returns `{"materialised": 0, "skipped_duplicate": 1}`.
4. Confirm: no duplicate expense written.

Pass criterion: Belt 2 (expense scan) catches the duplicate.

---

## 10 – Foreign-currency recurring

1. Add a EUR recurring entry to `recurring.yaml` (e.g. a German streaming service, `currency: EUR`).
2. Call `splitsmart.materialise_recurring` with `recurring_id` set to the new entry's id.
3. Confirm: expense written with `currency: EUR`, `home_amount` = `amount × fx_rate`.
4. Confirm: `fx_rate` and `fx_date` fields populated in the expense record.

Pass criterion: FX resolved; home_amount correct.

---

## 11 – Malformed recurring.yaml (partial load)

1. Add a second entry to `recurring.yaml` with a missing `schedule` key.
2. Restart HA (or reload the integration).
3. Confirm: HA log contains ERROR mentioning the bad entry's id.
4. Confirm: the good entry (netflix) still fires when you call `splitsmart.materialise_recurring`.

Pass criterion: bad entry skipped with ERROR; good entry unaffected.

---

## 12 – binary_sensor.splitsmart_fx_healthy behaviour

1. Confirm the sensor is `on` when the integration has recently fetched FX rates.
2. Disconnect internet. Wait for the 5-minute coordinator tick (or force a manual expense add to
   trigger a live lookup attempt).
3. If no successful fetch within 24h, confirm sensor flips `off`.
4. Reconnect internet. Trigger a GBP expense (same-currency, shortcut — no FX call) then a
   foreign-currency expense (forces a network call). Confirm sensor returns `on`.
5. Confirm `extra_state_attributes` contains `last_checked` with an ISO-8601 timestamp.

Pass criterion: sensor state and attribute reflect network health.

---

## 13 – Sanity guard on suspicious FX rate

1. Call `splitsmart.promote_staging` on an EUR staged row with an explicit `fx_rate: 0.001`
   (far outside the ±50% band versus today's live rate) and `fx_date` within the last 365 days.
2. Confirm: service raises `ServiceValidationError` mentioning the sanity guard / suspicious rate.
3. Retry with a plausible explicit `fx_rate` (e.g. `1.15`).
4. Confirm: expense written successfully.

Pass criterion: implausible rate rejected; plausible rate accepted.

---

## 14 – Pi QA

Repeat items 1–13 from the Raspberry Pi (production HA instance), not just the dev container.
Pay particular attention to:

- File write latency under SD card I/O (JSONL appends should complete without timeout).
- `binary_sensor.splitsmart_fx_healthy` state across actual Wi-Fi disruptions.
- 03:00 materialisation task fires on the Pi's local time (check `recurring_state.jsonl` updated).

Pass criterion: all items 1–13 pass on Pi hardware.

---

## Not in scope for M4 QA

- Card UI regression — unchanged from M2; covered by M2 QA.
- Load testing (5000+ expenses × daily materialisation) — deferred.
- Accessibility audit — deferred to M7.
- `splitsmart.apply_rules` — not implemented until M5.
