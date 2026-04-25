# M4 plan — FX and recurring bills

Scope is the SPEC §19 M4 milestone: FX on manual and promoted entries, recurring bills, and the `binary_sensor.splitsmart_fx_healthy` surface. M4 is backend-heavy; the card surface is untouched (no currency picker, no recurring editor — both deferred). The end-to-end demo: call `splitsmart.add_expense` with `currency: "EUR"` from Developer Tools, watch FX resolve and the expense land in the shared ledger; import a Revolut statement containing EUR rows, promote one, confirm FX lookup succeeds and the M3 "arrives in M4" error is gone; write a recurring.yaml entry, wait for 03:00, watch the bill appear; toggle the Wi-Fi off, restart FX lookup, see `binary_sensor.splitsmart_fx_healthy` flip off.

---

## 1. Scope fence

### In M4
The lean from the kickoff message, with the eight accepted refinements baked in:

1. **FX client module** (`custom_components/splitsmart/fx.py`) — Frankfurter HTTP client with append-only cache, timeout + one retry, error taxonomy distinguishing network failure from unsupported currency from no-cache-and-offline.
2. **FX on `splitsmart.add_expense`** — when `currency != home_currency` and caller hasn't supplied explicit `fx_rate`, look up via Frankfurter, store `fx_rate`, `fx_date`, `home_amount` on the expense. Sanity guard applied (see §5). Bubble any FX failure as `ServiceValidationError` with a clear user-facing message.
3. **FX on `splitsmart.add_settlement`** — same cascade as `add_expense`. Avoids an M5 footgun where rules or automations touch both services and hit a surprise "settlements are home-currency only" wall.
4. **FX on `splitsmart.edit_expense` / `splitsmart.edit_settlement`** — edits are full-replacement (M1 Amendment 5), so they re-enter the FX cascade with the new currency/date. No special path.
5. **FX on `splitsmart.promote_staging`** — the M3 O4 block at [services.py:510-511](custom_components/splitsmart/services.py#L510-L511) is removed. Promotion now invokes the same FX cascade as manual entry. Staged foreign-currency rows that have been waiting since M3 unblock automatically.
6. **`fx_rates.jsonl` cache** at `/config/splitsmart/fx_rates.jsonl` per SPEC §6.1. Append-only, newest-wins per `(from, to, requested_date)`. Cache is authoritative for historical rates (ECB rates are immutable once published); network is consulted on cache miss.
7. **Sanity guard** — when caller didn't supply explicit `fx_rate`, and `fx_date` is within ±365 days of today, compare the resolved rate against today's rate. If the ratio diverges by more than 50%, raise `ServiceValidationError` asking the caller to confirm via explicit `fx_rate`. Scoped narrowly (see §5) to avoid false positives on genuinely old dates.
8. **`binary_sensor.splitsmart_fx_healthy`** per SPEC §11. State `on` when the most recent FX lookup succeeded within the last 24h (reads `fx_rates.jsonl`'s newest `fetched_at`), `off` otherwise.
9. **Recurring bill definitions** in `/config/splitsmart/recurring.yaml`. User-authored, hand-editable, loaded at integration setup. Schedule kinds: `monthly`, `weekly`, `annually`.
10. **Recurring state** in `/config/splitsmart/recurring_state.jsonl`. Separate file, append-only, machine-updated on each materialisation. Newest entry per `recurring_id` wins on read. Keeps the YAML stable; keeps the state honest.
11. **Daily materialisation task at 03:00 local time** (`hass.config.time_zone`). Idempotent — if HA was down, the next run catches up missed dates between `last_materialised_date` and today.
12. **`splitsmart.materialise_recurring` service** per SPEC §10. Manually invokable from Developer Tools. Same code path as the 03:00 task. Aids debugging.

### Deferred (with rationale)

| Feature | Defer to | Why |
|---|---|---|
| Currency picker on the Add-expense form | M7 polish (or M5 if staging UI wants it) | Backend-focused milestone. FX exercised via Developer Tools + staging promotion + recurring bills. A currency UI can land independently. |
| Recurring-bills editor in the card | v2 | SPEC puts this in the v2 roadmap; YAML-first is the v1 story per SPEC §12.5 pattern. |
| FX provider alternative to Frankfurter | Never (v1) | SPEC §8 only lists Frankfurter. No alternative implemented means no `fx_provider` options-flow step. |
| Pre-warm scheduled FX refresh at 08:00 | Dropped per §8 refinement #5 | Fetch-on-demand plus a forever-cache for historical dates makes pre-warm save ~300ms per day at the cost of a scheduled task to test. Not worth it. |
| `fx_status: pending` + 15-minute retry task | Dropped per §8 refinement #4 + SPEC amendment | Simpler to fail at entry than to hold partial expense records and retry. Amend SPEC §8 to match. |
| `splitsmart.apply_rules` service | M5 | Rules engine ships in M5 per SPEC §19. |
| Telegram OCR | M6 | Unchanged. |
| Notifications (FX-feed unreachable alert per SPEC §17) | M7 | Notifications as a whole land in M7. |

### Push-back on the user's lean (all eight accepted)
1. `fx_cache.jsonl` → `fx_rates.jsonl` per SPEC §6.1 (no SPEC amendment needed).
2. Frankfurter host `api.frankfurter.dev/v1/{date}`; **amend SPEC §8 to match**.
3. Recurring definitions and state split into `recurring.yaml` + `recurring_state.jsonl`; **amend SPEC §6.1** to document `recurring_state.jsonl`.
4. Drop SPEC §8's `fx_status: pending` + 15-min retry; fail fast on cache miss + network failure; **amend SPEC §8** to match.
5. Keep `binary_sensor.splitsmart_fx_healthy`. Drop the 08:00 pre-warm.
6. Sanity guard scoped to `fx_date` within ±365 days of today; skip entirely when caller supplies explicit `fx_rate`.
7. No currency picker on Add form in M4.
8. FX cascade extended to settlements.

### What M4 adds vs the initial lean
- **FX for settlements.** Same cascade on `add_settlement` / `edit_settlement`.
- **`binary_sensor.splitsmart_fx_healthy`** — one extra file, ~30 lines of platform code.
- **`splitsmart.materialise_recurring` service** — manual trigger per SPEC §10.

### What M4 removes vs the initial lean
- **`fx_status: pending` partial-expense pattern** — never written. Fail fast, SPEC §8 amended.
- **Scheduled FX pre-warm at 08:00** — never written. Binary sensor observes cache freshness instead.
- **Bundled `recurring.jsonl`** — split into `recurring.yaml` + `recurring_state.jsonl`.

### What M4 must NOT ship
- Any UI for currency entry, FX rate override, or recurring-bills editing.
- Any pre-warming scheduled task for FX.
- Any change to the staging JSONL schema. Foreign-currency rows staged in M3 are unblocked by removing the promote-time guard; the rows themselves are unchanged.
- Any modification to expense records already on disk. M1/M2/M3 expenses have `fx_rate: 1.0`, `fx_date: <expense.date>` and stay that way.
- Any edit to `CHANGELOG.md` entries outside the `Unreleased` section.
- Any attempt to detect "the ECB is closed today" — Frankfurter already answers with the prior weekday's rate; we trust the returned `date` field.

---

## 2. SPEC amendments

Three amendments land in the same PR as the M4 code. One commit at the head of the PR so reviewers see the contract changes before the implementation.

**§6.1 — storage root layout.** Add `recurring_state.jsonl` alongside `recurring.yaml`:

```
├── recurring.yaml                 # Recurring bill templates (user-authored)
├── recurring_state.jsonl          # Per-recurring last_materialised_date (machine-updated)
```

**§8 — currency and FX.** Two changes.

*a)* Frankfurter endpoint path: `https://api.frankfurter.app/{date}...` → `https://api.frankfurter.dev/v1/{date}?from={ccy}&to={home}`.

*b)* Drop the `fx_status: pending` paragraph and the 15-minute retry. Replace with:

> **Failure model.** On a call to any write service that requires FX (non-home currency and no explicit `fx_rate`), the integration tries the cache first and Frankfurter on miss. If both fail, the write is rejected with `ServiceValidationError`; no partial or pending expense record is written. The caller (UI, automation, user at Developer Tools) retries when connectivity returns. `binary_sensor.splitsmart_fx_healthy` surfaces whether the most recent FX lookup succeeded within the last 24 hours.

The "daily rate cache" paragraph describing the 08:00 pre-warm is dropped. The cache is populated on-demand and kept forever for historical dates.

---

## 3. FX client module (`fx.py`)

### Public surface

```python
from __future__ import annotations

import asyncio
import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal


@dataclass(frozen=True)
class FxResult:
    rate: Decimal            # multiply source-currency amount to get home-currency
    fx_date: dt.date         # the date Frankfurter actually used (may differ on weekends)
    source: Literal["cache", "network"]


class FxError(Exception):
    """Base class for FX failures. Never leaks to users directly."""


class FxUnavailableError(FxError):
    """Cache miss AND network failure. User retries later."""


class FxUnsupportedCurrencyError(FxError):
    """Frankfurter returned 404 — the currency is not supported (e.g. VND)."""


class FxSanityError(FxError):
    """Resolved rate diverges >50% from today's rate (within ±365 days)."""


class FxClient:
    def __init__(self, hass, storage) -> None: ...

    async def get_rate(
        self,
        *,
        date: dt.date,
        from_currency: str,
        to_currency: str,
    ) -> FxResult:
        """Resolve the rate for (from → to) on `date`.

        Order of operations:
          1. If from == to, return FxResult(Decimal("1"), date, "cache") without IO.
          2. Read the cache. Newest entry matching (from, to, date) wins.
          3. On cache miss, fetch from Frankfurter with 5s timeout, one retry.
          4. On fetch success, append to cache and return FxResult(..., "network").
          5. On fetch failure with cache still empty, raise FxUnavailableError.
          6. Frankfurter 404 => FxUnsupportedCurrencyError (distinct from network fail).
        """

    async def last_successful_fetch(self) -> dt.datetime | None:
        """Most recent row's `fetched_at` from fx_rates.jsonl, or None if empty.
        Drives binary_sensor.splitsmart_fx_healthy."""
```

Exposed as `hass.data[DOMAIN][entry_id]["fx"]` on entry setup, alongside `storage` and `coordinator`. One client per entry; same single-entry-guard as the rest of the integration.

### Cache shape (`fx_rates.jsonl`)

One JSON object per line:

```json
{
  "requested_date": "2026-04-15",
  "from_currency": "EUR",
  "to_currency": "GBP",
  "rate": "0.8567",
  "fx_date": "2026-04-15",
  "fetched_at": "2026-04-24T14:30:00+01:00"
}
```

- `rate` stored as a string so Decimal round-trips without float drift.
- `fx_date` may differ from `requested_date` when the request falls on a weekend or bank holiday — Frankfurter returns the last preceding weekday's rate, and we record that so subsequent lookups for the same weekend hit cache.
- Read via the existing `SplitsmartStorage.read_all(fx_rates_path)` primitive. Storage gains `fx_rates_path: pathlib.Path` and `ensure_layout` creates the file alongside the existing ones.

### Network layer

```python
URL = "https://api.frankfurter.dev/v1/{date}?from={from_ccy}&to={to_ccy}"
TIMEOUT_SECONDS = 5
```

Uses `homeassistant.helpers.aiohttp_client.async_get_clientsession(hass)` — HA's shared session handles proxy, TLS and user-agent for us. No session management in the client.

Retry policy: **one retry after a 0.5s backoff**, only on `asyncio.TimeoutError` / `aiohttp.ClientError`. HTTP 4xx is terminal (no retry) — 404 is classified as `FxUnsupportedCurrencyError`, other 4xx as generic `FxUnavailableError` with the status logged at WARNING.

### Why cache-first, not network-first

The initial lean was "network first, cache as fallback". I'm flipping it — cache first, network on miss. Rationale:

- ECB reference rates are immutable once published. A cache hit for a historical date is authoritative.
- Today's rate: the first call fetches it; subsequent calls the same day reuse the cached entry. Frankfurter publishes once per day around 16:00 CET, so stale-within-day is expected behaviour, not a bug.
- Network-first hits Frankfurter on every expense entry, burning ~100-300ms of user-visible latency per write, and makes the integration network-dependent on every write. Cache-first takes the network out of the write path for ~99% of calls.
- Cost of the refinement: one line of documentation ("today's cached rate may be up to 24h stale; this is intentional").

The binary sensor still reflects network health via `fetched_at` — a machine that hasn't called Frankfurter in 24h flips `fx_healthy` to `off`, regardless of whether the reason is "no non-home-currency activity" or "ECB is unreachable". Acceptable ambiguity for M4; if users want a distinct "last successful fetch attempt" vs "last data freshness" pair, that's an M7 polish item.

### Logging
- DEBUG: every cache hit, every cache miss, every network fetch attempt, every retry.
- INFO: first successful fetch after startup (so the log shows the client came alive).
- WARNING: retry fired, Frankfurter 4xx that isn't 404, ambiguous response body.
- ERROR: never used directly from `fx.py` — callers decide whether to escalate. Service handlers log ERROR when `FxUnavailableError` is raised because that blocks a user-initiated write.

Per CLAUDE.md privacy rule: no amount or description is ever logged at INFO. Only the pair (from → to) and the date.

---

## 4. FX on writes

### `add_expense` cascade

Replace the current `_guard_currency(currency, home_currency)` at [services.py:247](custom_components/splitsmart/services.py#L247) with an `_resolve_fx(...)` helper:

```python
async def _resolve_fx(
    fx_client: FxClient,
    *,
    currency: str,
    home_currency: str,
    date: str,                             # ISO-8601
    explicit_rate: float | None,           # caller-supplied override; skips lookup + guard
    explicit_fx_date: str | None,
) -> tuple[Decimal, str, str]:
    """Return (rate, fx_date_iso, status).
    status ∈ {"home", "explicit", "lookup"} — drives caller's logging only.
    Raises ServiceValidationError with a user-facing message on any FX failure."""
```

Behaviour:

1. `currency == home_currency` → `(Decimal("1"), date, "home")`. No cache write. No guard.
2. `explicit_rate is not None` → `(Decimal(str(explicit_rate)), explicit_fx_date or date, "explicit")`. No cache write. No guard — caller explicitly overrode, they're responsible.
3. Otherwise → call `fx_client.get_rate(date, currency, home_currency)`. Apply sanity guard (§5) if result was `"network"` sourced or even if from cache (the guard doesn't care about source — if the number's garbage, it's garbage). On `FxUnavailableError` / `FxUnsupportedCurrencyError` / `FxSanityError`, translate to `ServiceValidationError` with a message from §4.3.

Then `home_amount = round(amount * rate, 2)` (Decimal maths, then float to store per M1 boundary convention).

### Schema changes

`ADD_EXPENSE_SCHEMA` gains two optional fields:

```python
ADD_EXPENSE_SCHEMA = vol.Schema({
    # ...existing fields...
    vol.Optional("fx_rate"): vol.All(vol.Coerce(float), vol.Range(min=0.000001)),
    vol.Optional("fx_date"): cv.date,
})
```

Same for `ADD_SETTLEMENT_SCHEMA`, `EDIT_EXPENSE_SCHEMA`, `EDIT_SETTLEMENT_SCHEMA` (edits inherit via `.extend(ADD_*)` per M1).

`build_expense_record` signature gains `fx_rate: Decimal` and `fx_date: str` as required kwargs (callers always know the answer by now); the default `fx_rate=1.0, fx_date=date` path is preserved for home-currency writes. Same for `build_settlement_record`.

### `promote_staging`

Remove the M3 guard at [services.py:510-511](custom_components/splitsmart/services.py#L510-L511). After the ownership check and before `build_expense_record`, call `_resolve_fx(...)` with the staging row's `currency` and the caller-supplied `override_date` (or the row's original date) — staged foreign-currency rows accepted `fx_rate` / `fx_date` overrides via the promote service in M3's schema (they were dead-weight until now; add them to `PROMOTE_STAGING_SCHEMA` in M4).

Users who staged EUR rows under M3 and have been waiting: their first `promote_staging` call in M4 triggers a Frankfurter lookup on the staging row's `date`, caches, and returns. The row's expense lands with correct FX.

### `add_settlement` / `edit_settlement`

Same cascade. A settlement's `home_amount` is `amount * fx_rate`. The motivation — raised in the kickoff discussion — is that M5 rules might touch both paths and we want one invariant: any write that accepts `currency` also accepts `fx_rate` / `fx_date` and resolves via the same cascade.

### Error message surface

The caller-facing `ServiceValidationError` strings — stable because automations may match on them:

| Condition | Message |
|---|---|
| `FxUnavailableError` | `"FX rate for {date} {from}→{to} is not cached and Frankfurter is unreachable. Try again when connectivity returns, or provide fx_rate explicitly."` |
| `FxUnsupportedCurrencyError` | `"Currency '{code}' is not supported by the FX provider. Provide fx_rate explicitly or choose a different currency."` |
| `FxSanityError` | `"Resolved FX rate {rate} for {from}→{to} on {date} diverges by more than 50% from today's rate. If this is intentional, provide fx_rate explicitly."` |
| Explicit `fx_rate` but `currency == home_currency` | `"fx_rate provided for a home-currency entry. Either remove fx_rate or change the currency."` |

Messages are user-facing in the HA UI when Developer Tools surfaces `ServiceValidationError`. Flagged in the plan body as the canonical set; any tweaks land in a single commit.

---

## 5. Sanity guard

### Scope
- Applied only when the caller didn't supply explicit `fx_rate`.
- Applied only when `abs((today - fx_date).days) <= 365`.
- Compares the resolved rate against `fx_client.get_rate(date=today, from=..., to=...)`. The today-lookup caches normally, so the second and subsequent backdated entries on the same day don't incur a second network call.

### Threshold
- If `resolved_rate / today_rate > 1.5` or `resolved_rate / today_rate < 2/3`, raise `FxSanityError`. (50% symmetric: a rate that's >1.5× or <0.667× of today's is suspect.)
- Rationale: major currencies don't swing 50% within a year except in crisis scenarios, and in those cases the caller probably *does* want to double-check. Minor currencies with real 50% swings (TRY, ARS in recent years) can be entered with an explicit `fx_rate` to bypass — that's the whole point of the override.

### Failure modes
- Today's lookup itself raises `FxUnavailableError`: swallow, skip the guard, log DEBUG. The primary lookup succeeded, we're only being paranoid — don't promote paranoia failure to write failure.
- Today's lookup raises `FxUnsupportedCurrencyError`: impossible (if the currency is supported for a historical date, it's supported for today too). Log WARNING if it somehow happens; skip guard.
- `fx_date` beyond ±365 days: skip guard entirely. Old rates can legitimately differ. The caller backdated on purpose.

### Why not tighter?
20% would catch more errors but would false-positive on genuine volatility (GBP post-Brexit, TRY in 2022). 50% is a "this is almost certainly garbage or a typo in the date field" threshold.

---

## 6. Binary sensor `splitsmart_fx_healthy`

New platform file `custom_components/splitsmart/binary_sensor.py`. Registered in `__init__.py` via `PLATFORMS = ["sensor", "binary_sensor"]`.

```python
class FxHealthySensor(CoordinatorEntity[SplitsmartCoordinator], BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_name = "FX healthy"

    def __init__(self, coordinator, entry_id: str, fx_client: FxClient) -> None: ...

    @property
    def is_on(self) -> bool:
        last = self._last_success_cached
        if last is None:
            return False
        return (dt.datetime.now(tz=UTC) - last) <= timedelta(hours=24)

    @property
    def extra_state_attributes(self) -> dict:
        return {"last_checked": self._last_success_cached}
```

The `last_checked` attribute reads from `fx_client.last_successful_fetch()` (itself a tail-read of `fx_rates.jsonl`). Updates on every coordinator tick (every 5 minutes) plus whenever the coordinator pushes data via `async_note_write`. No separate polling task — the 5-minute cadence is fine for a diagnostic sensor.

Unique id: `f"{entry.entry_id}_fx_healthy"`. Shows up in the integration's device page alongside the four M1 sensors + M3 pending count sensors.

A subtle wrinkle: `is_on == True` requires an FX call to have happened. A fresh install with no foreign-currency activity reports `off`. That's wrong-feeling but factually correct — we have no data to judge health. SPEC §17 implies a notification fires on ">24h unreachable"; we debounce the first-ever transition by setting `is_on = True` on startup if the cache has any row from the last 24h, else `False`. No startup-specific "grace period" — if a user never makes a foreign-currency call, the sensor is permanently `off` and that's honest. Documented in README and in the sensor's description string in `translations/en.json`.

---

## 7. Recurring bills

### `recurring.yaml` shape (user-authored)

Lives at `/config/splitsmart/recurring.yaml`. Hand-editable; no card UI in M4. Loaded at integration setup and on options flow completion (conservative — reloading doesn't hurt).

```yaml
recurring:
  - id: netflix
    description: Netflix
    amount: 15.99
    currency: GBP
    paid_by: user_abc123
    categories:
      - name: Subscriptions
        home_amount: 15.99
        split:
          method: equal
          shares:
            - {user_id: user_abc123, value: 50}
            - {user_id: user_def456, value: 50}
    schedule:
      kind: monthly
      day: 15
    start_date: 2026-01-15
    end_date: null

  - id: council_tax
    description: Council tax
    amount: 210.00
    currency: GBP
    paid_by: user_abc123
    categories:
      - name: Utilities
        home_amount: 210.00
        split: {method: equal, shares: [{user_id: user_abc123, value: 50}, {user_id: user_def456, value: 50}]}
    schedule: {kind: monthly, day: 1}

  - id: tv_licence
    description: TV licence
    amount: 169.50
    currency: GBP
    paid_by: user_abc123
    categories:
      - {name: Household, home_amount: 169.50, split: {method: equal, shares: [{user_id: user_abc123, value: 50}, {user_id: user_def456, value: 50}]}}
    schedule: {kind: annually, month: 4, day: 1}
```

### Schedule kinds

| Kind | Required keys | Trigger |
|---|---|---|
| `monthly` | `day: 1..31` | Day-of-month matches, clamped to the last valid day when the month has fewer days. See decision Q1. |
| `weekly` | `weekday: monday..sunday` | Weekday matches. |
| `annually` | `month: 1..12`, `day: 1..31` | Both match, clamped when `month: 2, day: 29` in a non-leap year. See decision Q2. |

No `daily` kind in M4 — it's trivially expressible via `weekly` + seven entries, and "rent every day" isn't a real use case.

No `cron` expression support. If users want hourly Bitcoin purchases they can write a HA automation that calls `splitsmart.add_expense`.

### `recurring_state.jsonl`

Append-only. One line per materialisation event:

```json
{
  "id": "rs_01J9X...",
  "created_at": "2026-04-24T03:00:05+01:00",
  "recurring_id": "netflix",
  "last_materialised_date": "2026-04-15"
}
```

The materialiser reads the whole file into a `dict[recurring_id, last_materialised_date]` with newest-wins, the same pattern as `mappings.jsonl` from M3. Queried at startup and once per materialisation run. No runtime lock — the daily task is a single coroutine.

ULID prefix for state records: `rs_` (recurring-state). Added to `const.py`.

### Materialisation task

Runs at **03:00 local time** (`hass.config.time_zone`). Wired via `async_track_time_change(hass, _materialise, hour=3, minute=0, second=0)` in `__init__.py`, next to the cleanup task. Unsub stored on `entry.async_on_unload`.

Algorithm (idempotent, catches up missed days):

```
1. Load recurring.yaml. Empty / missing => noop.
2. Load recurring_state.jsonl => state_by_id.
3. today = dt.date.today() in HA's configured tz.
4. For each recurring in recurring.yaml:
     5. last = state_by_id.get(recurring.id, None)
     6. If last is None:
          floor = recurring.start_date or today
        else:
          floor = last + 1 day
     7. ceiling = min(today, recurring.end_date or today)
     8. If floor > ceiling: continue.
     9. For each date d in [floor..ceiling] that matches recurring.schedule:
          10. Idempotency check: scan coordinator.data.expenses for an existing
              expense where source == "recurring" AND recurring_id == recurring.id
              AND date == d.iso. If found, skip.
          11. Resolve FX via fx_client (cascade from §4) using d as the date.
              If FX fails, log WARNING with recurring_id + date, skip this date
              but continue with other recurrings. Do NOT update last_materialised_date
              for a skipped date.
          12. Build expense record via build_expense_record with:
                source="recurring", staging_id=None,
                plus a new top-level field "recurring_id" = recurring.id
              Validate via validate_expense_record.
              Append to storage.expenses_path.
    13. Append one state row to recurring_state.jsonl with the highest
        successfully-materialised date for this recurring.
14. Call coordinator.async_note_write() once after all recurrings processed.
```

Expense records gain a `recurring_id: str | None` field. Documented in SPEC §6.2 as part of the M4 amendment (unless reviewers object to adding a fourth schema amendment — I'll fold it into §2 if green-lit).

### Idempotency — why scan expenses?

Two belts on one trousers:

- **Belt 1:** `last_materialised_date` in `recurring_state.jsonl` prevents re-running the same date after a normal catch-up.
- **Belt 2:** Scanning expenses for `(recurring_id, date)` prevents a double-up if the state file is ever manually deleted, corrupted, or if two HA instances ever run against the same config directory (pathological but real).

Cost: O(expenses × recurrings × catch-up-days). At household scale with ~5 recurrings and a normal ≤1-day catch-up, cost is negligible. If a user adds a recurring with `start_date: 2024-01-01` and no `last_materialised_date` yet, the first run materialises ~27 months of entries — potentially slow. Q3 (§10) resolved in favour of backfilling; the advisory below softens the surprise.

### Backfill advisory (addendum from Q3 resolution)

When materialising a recurring whose `last_materialised_date` is `None` (i.e. first run ever for that `recurring_id`), count the dates the schedule would match between `start_date` and today inclusive. If that count exceeds **3**, log one INFO line before materialisation begins:

```
First materialisation of recurring '{id}' will create N backfill entries (start_date: {start_date}). Review recurring_state.jsonl after the run.
```

Fired exactly once per recurring_id (only when `last_materialised_date` transitions from `None` to non-`None`). Threshold of 3 chosen so a normal "started today" recurring with one match produces no log noise; anything larger is surprising enough to warrant a heads-up. Doesn't block, doesn't prompt — cheap visibility only.

### `splitsmart.materialise_recurring` service

```yaml
materialise_recurring:
  name: Materialise recurring bills
  description: Run the recurring-bills engine manually. Same as the 03:00 task.
  fields:
    recurring_id:
      required: false
      description: Optional — materialise just this one recurring. Omit for all.
```

Returns `{"materialised": N, "skipped_fx_failure": K, "skipped_duplicate": M}` via `SupportsResponse.OPTIONAL`. Useful for debugging and for the QA checklist.

### Validation (YAML load time)

Loader (`recurring.py`) validates each entry against a voluptuous schema. Invalid entries are **logged at ERROR and skipped**; valid entries still run. Rationale: a single typo shouldn't stop all recurrings from firing. The ERROR log names the offending entry's id + field so the user can fix it. Decision Q7 asks whether to go stricter (fail-fast on startup).

Required fields per entry:

- `id` — lowercase, `[a-z0-9_]+`, unique within the file.
- `description` — non-empty.
- `amount` — positive float.
- `currency` — 3-letter ISO code.
- `paid_by` — must be in `entry.data[CONF_PARTICIPANTS]`.
- `categories` — non-empty, each alloc with `name`, `home_amount`, `split` matching the expense schema.
- `schedule` — one of the three kinds above.
- `start_date` — optional; defaults to today.
- `end_date` — optional; null means forever.

The `home_amount` fields in `categories` are the user's authored split at the original currency — they sum to `amount`. At materialisation time, if `currency != home_currency`, each allocation's `home_amount` is rescaled by the resolved `fx_rate`. The final allocation gets any rounding drift so the allocation sum matches the expense's `home_amount` exactly.

---

## 8. Coordinator and concurrency

### Additions to `SplitsmartData`

None required for M4. FX state lives on the `FxClient` (via cache file); recurring state is read fresh at each materialisation. Expense/staging/tombstone projections unchanged.

### Additions to `SplitsmartStorage`

```python
@property
def fx_rates_path(self) -> pathlib.Path: ...
@property
def recurring_yaml_path(self) -> pathlib.Path: ...
@property
def recurring_state_path(self) -> pathlib.Path: ...
```

All three added to `ensure_layout`. `fx_rates.jsonl` and `recurring_state.jsonl` are created empty; `recurring.yaml` is NOT created (we don't want to place an empty YAML and pretend the user authored it — missing file just means "no recurrings").

Existing `asyncio.Lock` per-path registry covers the new files automatically. No new locking semantics.

### `async_note_write` path

Materialisation fires expense writes — same path as `splitsmart.add_expense` from the coordinator's perspective. One `async_note_write(staging_user_id=None)` call at the end of the materialisation batch, the incremental refresh path handles it.

### FX calls from services

`fx_client.get_rate` is a coroutine; service handlers `await` it inline. No task-offloading. Worst case (cache miss + network fetch + one retry): ~5.5 seconds, which is within HA's default service-call timeout (90s). Retry fires after 0.5s backoff so typical total latency on a bad network is ~5.5s.

---

## 9. Test plan

Mirrors M3_PLAN §7. New tests live in `tests/`; pure modules get unit tests, services get integration tests, fixtures are committed under `tests/fixtures/`.

### 9.1 Unit tests (no HA event loop)

**`tests/test_fx.py`** — FxClient against a mocked `aiohttp.ClientSession`:

- Happy path: network fetch for (2026-04-15, EUR, GBP) returns 0.8567 from Frankfurter; result cached; subsequent call hits cache.
- Cache hit: pre-populated cache row, `get_rate` returns it without touching the session.
- `from == to`: returns `(Decimal("1"), date, "cache")` without IO.
- Weekend date: requested date is 2026-04-12 (Sunday); Frankfurter returns rate dated 2026-04-10 (Friday); result stores `fx_date=2026-04-10`, `requested_date=2026-04-12` in cache.
- Follow-up call for the same Sunday: hits cache (keyed on requested_date), returns stored rate.
- Network timeout on first attempt: one retry fires after 0.5s; on retry success returns normally.
- Network timeout on both attempts + cache empty: raises `FxUnavailableError`.
- Network timeout on both attempts + cache populated: returns cached rate with `source="cache"`.
- Frankfurter HTTP 404: raises `FxUnsupportedCurrencyError`; no retry.
- Frankfurter HTTP 500: treated as generic network failure; retry fires.
- Ambiguous JSON response (missing `rates` key): raises `FxUnavailableError`; WARNING logged.
- `last_successful_fetch` returns the newest `fetched_at` from the cache file; `None` when empty.

**`tests/test_fx_sanity.py`**:

- Rate within 50% of today's: no error.
- Rate >1.5× today's: `FxSanityError`.
- Rate <0.667× today's: `FxSanityError`.
- `fx_date` 400 days ago: skip guard (no error even if rate is garbage).
- Explicit `fx_rate` override: guard skipped upstream (not called).
- Today's lookup fails: swallow, skip guard, log DEBUG.

**`tests/test_recurring_schedule.py`** — pure schedule-matching:

- Monthly `day: 15`: matches every 15th.
- Monthly `day: 31` in February 2026 (28-day): matches 28 Feb (clamped).
- Monthly `day: 31` in April (30-day): matches 30 Apr (clamped).
- Monthly `day: 29` in February 2024 (leap): matches 29 Feb.
- Monthly `day: 29` in February 2026 (non-leap): matches 28 Feb (clamped).
- Weekly `weekday: monday`: matches every Monday in the range.
- Annually `month: 2, day: 29` in 2026: matches 28 Feb.
- Annually `month: 4, day: 6`: matches 6 Apr each year.
- Range spanning a month with no matches (monthly day=31 in a 30-day month with a 1-day window): returns empty.

**`tests/test_recurring_materialise.py`** — pure materialisation logic:

- Empty state + `start_date == today` and today matches schedule: produces one expense.
- Empty state + `start_date == today - 30 days` and 3 schedule matches in between: produces 3 expenses.
- Existing `last_materialised_date` = yesterday + today matches: produces 1 expense, updates state to today.
- Existing `last_materialised_date` = today + today matches: produces 0 expenses, state unchanged.
- `end_date` in the past: produces 0 expenses even if schedule matches today.
- `end_date` mid-range: materialises up to and including end_date.
- Idempotency: scan finds an existing expense with same `(recurring_id, date)`; skips without writing a duplicate.
- FX failure for one date in the range: skips that date, logs WARNING, still materialises others; `last_materialised_date` reflects the highest successful date only.
- Multi-currency: EUR recurring with home GBP, rate 0.8567 — expense's `home_amount` = `amount * rate`, allocations rescaled; sum-of-allocations == home_amount invariant holds.
- Float drift edge case: amount=33.33, 3 allocations of 11.11 each, fx_rate=1.2345 — last allocation absorbs drift so the sum matches exactly.

**`tests/test_recurring_loader.py`**:

- Valid YAML with 3 entries: all loaded.
- Missing file: returns empty list, no error.
- One invalid entry (missing `schedule`): valid entries still loaded, ERROR logged naming the bad id.
- Duplicate `id` within file: second entry rejected with ERROR; first kept.
- `paid_by` not a participant: entry rejected, ERROR logged.
- `schedule.day` = 0 or 32: entry rejected.
- `schedule.weekday` = "tuseday" (typo): entry rejected.

### 9.2 Integration tests (HA event loop, tmp config dir)

**`tests/test_services_fx.py`**:

- `add_expense` with `currency="EUR"`, no `fx_rate`: calls FxClient, stores `fx_rate` + `home_amount` correctly.
- `add_expense` with `currency="EUR"`, explicit `fx_rate=0.85`: bypasses FxClient (no cache read, no network); stored values come from the override.
- `add_expense` with `currency="EUR"`, network down, cache empty: `ServiceValidationError` with the §4.3 message; no expense row written.
- `add_expense` with `currency="EUR"`, network returns HTTP 404 (simulated VND): `ServiceValidationError` with the unsupported-currency message.
- `add_expense` with `currency="EUR"` where resolved rate fails sanity: `ServiceValidationError` with the sanity message; user bypasses by resubmitting with explicit `fx_rate`.
- `add_expense` with `currency == home_currency` and explicit `fx_rate` supplied: `ServiceValidationError` per §4.3.
- `edit_expense` changing currency from GBP to EUR: full-replacement path re-enters FX cascade; old expense tombstoned, new expense has resolved FX.
- `add_settlement` with foreign currency: same cascade applies; symmetric with expense path.
- `promote_staging` on a M3-staged EUR row: the guard at [services.py:510-511](custom_components/splitsmart/services.py#L510-L511) is gone; FX resolves on `staging_row["date"]`; new expense lands.
- `promote_staging` on a EUR row with explicit `fx_rate` / `fx_date` in the call: bypasses FxClient.
- `promote_staging` on a EUR row with network down and cache empty: `ServiceValidationError`; staging row remains live (no tombstone); user retries later.

**`tests/test_services_recurring.py`**:

- `splitsmart.materialise_recurring` with one due recurring: creates 1 expense, updates state.
- Service called twice in a row on the same day: second call creates 0 expenses.
- Service called with `recurring_id` arg: only that one runs.
- Service called with no due recurrings: `{"materialised": 0, ...}`.
- Service with a foreign-currency recurring and cache miss + network down: `skipped_fx_failure: 1`.
- Service when `recurring.yaml` is missing: `{"materialised": 0}` with INFO log.

**`tests/test_recurring_daily_task.py`**:

- `async_track_time_change` wired to fire at 03:00 local time in `hass.config.time_zone`.
- Freezegun advance to 03:00:00: materialiser runs; expenses appear.
- Start HA with `last_materialised_date` 5 days stale, today is Monday and weekly=monday: catches up 1 expense.
- Start HA with `last_materialised_date` 35 days stale, monthly recurring: catches up 1 expense (the missed monthly date).

**`tests/test_sensors_fx_healthy.py`**:

- Fresh install, no FX calls ever: sensor `off`, `last_checked: None`.
- After one successful FX call: sensor `on`, `last_checked` set.
- 23h after a successful call: still `on`.
- 25h after a successful call: flips to `off`.
- Network failure after a prior success: sensor stays `on` until 24h elapses — reflects data freshness, not reachability. Documented behaviour.

**`tests/test_sensors_pending_count_unblock.py`** — a regression test for the M3→M4 boundary:

- Set up a EUR row in staging with `rule_action="pending"`.
- Before M4: `blocked_foreign_currency_count: 1`, `promotable_count: 0`.
- Call `promote_staging` on the row with network + cache providing a rate.
- After: row is gone, `blocked_foreign_currency_count: 0`, shared ledger has the new expense.

**`tests/test_coordinator_fx.py`**:

- `async_note_write` after a promote of a foreign-currency row refreshes balances correctly using the new expense's `home_amount`.
- `fx_rates.jsonl` is read by `FxClient`, not by the coordinator — confirm the coordinator doesn't try to materialise it.

### 9.3 Fixtures

New under `tests/fixtures/`:

- `fx/frankfurter_eur_gbp_2026-04-15.json` — captured Frankfurter response for a happy-path date. Committed as an immutable snapshot (per CLAUDE.md "Files never to edit").
- `fx/frankfurter_404.json` — response body for an unsupported currency.
- `recurring/netflix.yaml` — single-entry recurring.yaml for the schedule tests.
- `recurring/typical_household.yaml` — 3-entry recurring.yaml covering monthly, weekly, annually.
- `recurring/malformed.yaml` — valid YAML with one bad entry and one good entry, for loader tests.

### 9.4 Manual QA — `tests/MANUAL_QA_M4.md`

Produced at the end of M4. Checklist covers:

1. Upload a Revolut statement with GBP + EUR + USD rows. Import. Observe 3 of each land in staging; pending-count sensor's `blocked_foreign_currency_count` reflects the EUR + USD count.
2. Promote one EUR row via Developer Tools. Verify FX rate was looked up live (check `fx_rates.jsonl`); `home_amount` matches `amount * rate` to 2dp; new expense appears in card Ledger with correct GBP figure.
3. Promote the next EUR row the same day. Verify no new Frankfurter call (cache hit, confirmed via log).
4. Toggle Wi-Fi off. Add a new USD expense via Developer Tools (not yet cached). Verify `ServiceValidationError` with the unreachable message.
5. Toggle Wi-Fi back on. Retry. Succeeds.
6. Edit a M1/M2 GBP expense, change currency to EUR. Verify FX resolves, tombstone + new expense written, balance updates.
7. Write a `recurring.yaml` with one monthly entry due today. Wait (or call `splitsmart.materialise_recurring`). Verify 1 expense appears with `source: "recurring"`.
8. Call the service again — verify idempotency (0 new expenses).
9. Delete `recurring_state.jsonl` manually. Call the service. Verify the expense-scan idempotency check still prevents duplication.
10. Write a foreign-currency recurring (EUR). Verify it materialises with correct FX.
11. Write a malformed `recurring.yaml` (one good, one bad entry). Restart HA. Verify the good one fires at 03:00; the bad one logged ERROR on startup.
12. Observe `binary_sensor.splitsmart_fx_healthy` reflects reality across Wi-Fi toggles + time advances.
13. Try to promote a EUR row with an FX rate that diverges from today's rate by 60% (e.g. typo an old date 10 years ago but within 365 days). Verify sanity guard fires; resubmit with explicit `fx_rate`; succeeds.
14. Pi QA — all of the above from the Pi, not just local dev.

### 9.5 Deliberately NOT tested in M4
- Visual regression on the card — unchanged, M2 QA covers.
- Load testing (5000+ expenses × daily materialisation) — deferred.
- Accessibility audit — deferred to M7.
- `splitsmart.apply_rules` — doesn't exist yet (M5).

---

## 10. Decisions (resolved in plan body) and open questions

### Resolved in this plan (no user input needed)

**R1 — FX cache policy: cache-first, network on miss.** Flipped from the kickoff's "network-first, cache as fallback". Rationale in §3. Historical ECB rates are immutable; network-first wastes ~100-300ms per write.

**R2 — Cache key granularity.** Keyed on `(from_currency, to_currency, requested_date)`. Stores the Frankfurter-returned `fx_date` separately so weekend requests resolve without a second network call.

**R3 — FxClient placement.** One instance per config entry, stored at `hass.data[DOMAIN][entry_id]["fx"]`. Uses HA's shared aiohttp session.

**R4 — Binary sensor cadence.** Polls via the 5-minute coordinator tick. No event-driven push.

**R5 — Sanity guard threshold: 50% symmetric (>1.5× or <0.667×).** Within ±365 days of today. Explicit `fx_rate` bypasses. Today's-lookup failure silently skips the guard.

**R6 — FX cascade extension to settlements.** Same code path as expenses. Future-proofs against M5 rules that touch both.

**R7 — SPEC amendments.** Three, all in the first commit of the PR: Frankfurter host (§8), failure model (§8 — replace `fx_status: pending` paragraph), `recurring_state.jsonl` (§6.1). A fourth amendment for the `recurring_id` field on expense records (§6.2) lands in the same commit.

**R8 — Expense record schema addition.** `recurring_id: str | None` field added to expense records, populated by the materialisation task. Null for non-recurring-sourced expenses (M1-M3 rows stay valid — the field is optional).

**R9 — Recurring idempotency: two belts.** `recurring_state.jsonl` last-materialised-date check AND expense-scan for `(recurring_id, date)`. Cheap; defends against state-file corruption.

**R10 — Cache key semantics.** `FxClient.get_rate`'s docstring explicitly notes the cache is keyed on `requested_date` (what the caller asked for), not `fx_date` (what Frankfurter returned). This is how a re-query for the same Sunday hits cache: the first call stored `requested_date=2026-04-12, fx_date=2026-04-10`, and the second call's cache lookup on `2026-04-12` succeeds.

**R11 — Allocation drift absorption on FX rescale.** When FX rescales a multi-category recurring bill, the **last allocation in the `categories` array** (as written in `recurring.yaml`) absorbs rounding drift. Deterministic, user-controllable — the user can reorder their YAML entries to pick which category takes the drift. Not the smallest allocation, not the alphabetically-last.

### Formerly open questions (all resolved 2026-04-24)

**Q1 — Monthly `day: 31` in February.** Proposal: **clamp to last day of month** (monthly day=31 fires on 28 Feb in non-leap years, 29 Feb in leap years, 30 in April). Alternative: skip months where the day doesn't exist. Clamp matches common bill scheduling ("end-of-month rent"), but "skip" is defensible if users model "pay on the 31st literally".
**Resolved:** Clamp to last day of month.

**Q2 — Annually `month: 2, day: 29` in non-leap years.** Proposal: **clamp to 28 Feb**. Alternatives: skip (fire every 4 years only), advance to 1 Mar. Clamp matches the monthly rule and gives the user a predictable "once a year" cadence.
**Resolved:** Clamp to 28 Feb.

**Q3 — Backfill on first run of a newly-added recurring with a historical `start_date`.** Proposal: **backfill from `start_date`**. If a user adds a monthly recurring with `start_date: 2024-01-01` today, the first materialisation creates ~27 expenses at once. This could surprise a user who expected "start now". Alternative: start from today regardless of `start_date`, then advance normally. Safer but inconsistent with the `start_date` field's apparent meaning.
**Resolved:** Backfill from `start_date`, with an INFO log advisory on first run when the backfill will produce >3 entries (see §7 "Backfill advisory" addendum).

**Q4 — Materialisation path: direct write or through `splitsmart.add_expense`.** Proposal: **direct** — call `build_expense_record` + `storage.append(expenses_path, ...)` without going through the service. Rationale: no ServiceCall context to fake, simpler logging, no user_id assumption (the task runs with no caller). Cons: doesn't go through the voluptuous schema validator, so any bug in `build_expense_record` would slip through. Mitigated by `validate_expense_record` which both paths call.
**Resolved:** Direct write.

**Q5 — Frankfurter unsupported currency (e.g. VND).** Proposal: **distinct `FxUnsupportedCurrencyError` → distinct ServiceValidationError message** (per §4.3) so users understand it's a currency-coverage issue, not a connectivity issue. Alternative: treat as generic unavailable, one error surface.
**Resolved:** Distinct error class with its own user-facing message.

**Q6 — Sanity guard threshold.** Proposal: **50% symmetric (>1.5× or <0.667×)**, within ±365 days. 20% catches more errors but false-positives on real volatility (GBP post-Brexit). 100% only catches the truly absurd. 50% is the "this is almost certainly garbage" threshold.
**Resolved:** 50% symmetric, ±365 days.

**Q7 — Recurring YAML parse error strategy.** Proposal: **log ERROR and skip** the malformed entry; valid entries still fire. Alternative: fail-fast at integration setup — refuse to start until the YAML is clean. Fail-fast is stricter but means a typo in an obscure field takes all recurrings offline.
**Resolved:** Log ERROR and skip; valid entries still fire.

---

## 11. Implementation order

Branch `m4/fx` (already created). Each step is its own commit where sensible. Merge as a single PR tagged `v0.1.0-m4`.

1. **SPEC amendments** — commit touching SPEC.md §6.1 (add `recurring_state.jsonl`), §6.2 (add `recurring_id` field), §8 (Frankfurter host + failure model). Before any code — reviewers read the new contract first.
2. **Storage extensions** — `fx_rates_path`, `recurring_yaml_path`, `recurring_state_path` on `SplitsmartStorage`, `ensure_layout` updates, no schema changes to existing files.
3. **FX client (`fx.py`)** — module + cache read/write + network fetch with retry + error taxonomy. Full unit tests.
4. **FX on expense services** — `_resolve_fx` helper + schema changes + `build_expense_record` signature update. Remove `_guard_currency` from `add_expense` / `edit_expense`. Unit + integration tests.
5. **FX on settlement services** — same cascade on `add_settlement` / `edit_settlement`.
6. **FX on `promote_staging`** — remove the M3 guard. Schema gains `fx_rate` / `fx_date` optional fields. Regression test for the M3→M4 staging unblock.
7. **Sanity guard** — as a distinct commit so its tests are isolated.
8. **Binary sensor (`binary_sensor.py`)** — platform file + platform registration + tests + translations entry for the sensor description.
9. **Recurring loader (`recurring.py`)** — YAML parse + voluptuous validation + load helpers. Unit tests.
10. **Recurring state** — JSONL read/write with newest-wins; `rs_` id prefix in `const.py`.
11. **Recurring materialiser** — pure schedule + materialisation functions, unit tests for the edge-case matrix (Q1, Q2, Q3).
12. **Recurring daily task** — `async_track_time_change` wiring in `__init__.py`.
13. **`splitsmart.materialise_recurring` service** — wrapper around the materialiser, `services.yaml` entry, tests.
14. **Manual QA checklist** — `tests/MANUAL_QA_M4.md`.
15. **CHANGELOG** — `## Unreleased` block updated with the M4 summary.
