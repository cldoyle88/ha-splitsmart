# ha-splitsmart — specification

A Home Assistant custom integration (HACS-packaged) for splitting household expenses between two or more people, with a native Lovelace custom card, a staging-first import pipeline, and Telegram receipt ingestion via vision OCR.

Primary targets on install: (a) replace Splitwise for everyday couple / housemate use; (b) be installable from HACS by any HA user with two clicks and a config flow.

Repo: `github.com/cldoyle88/ha-splitsmart`. HACS slug: `splitsmart`. Python package name: `splitsmart`. Frontend card element name: `splitsmart-card`.

---

## 1. Vision in one paragraph

Every household expense starts private. Card statements, Telegram receipt photos and manual entries all land in the uploader's private staging inbox. The uploader decides — per row or via rules — whether each row becomes a shared expense (split with their partner), stays ignored, or waits for later review. Once promoted to the shared ledger, expenses contribute to live balance entities that HA dashboards, automations and the mobile companion can use like any other sensor. No cloud dependency beyond an optional FX rate feed and optional vision OCR API.

## 2. Non-goals for v1

- Receipt itemisation (line-item splitting within a single receipt).
- Debt simplification across groups of 3+ (our maths handles arbitrary participants, but we do not optimise repayment graphs).
- Card-linked auto-import (Plaid / Open Banking). Users import statement files manually.
- Payment provider integrations (PayPal, Venmo, etc.).
- Personal expense tracking beyond the staging inbox. Rows that aren't shared are ignored, not retained as a personal ledger.
- Mobile apps beyond the HA companion app. The custom card works on mobile; that's the mobile story.

## 3. Identity and differentiation from Splitwise

Splitwise's core model assumes every entry is a candidate shared expense. Splitsmart inverts this: every entry is private until promoted. Concrete consequences:

1. A user can upload a full credit card statement without exposing every line to their partner.
2. Rules can auto-promote obvious shared expenses (Netflix, groceries) without review.
3. The review queue is always "things I need to decide", not "everything I've ever entered".
4. Telegram receipt photos flow into the same staging pipeline, not a separate inbox.

## 4. Technology stack

**Backend (HA custom component):**
- Python 3.12 (HA 2026.x min).
- `homeassistant.helpers.update_coordinator.DataUpdateCoordinator` for ledger state.
- `aiofiles` for async file IO.
- `voluptuous` for schema validation (HA-standard).
- `aiohttp` (HA-bundled) for Frankfurter FX calls and vision API calls.
- No external storage engine. JSONL files on disk. Recorder-backed where appropriate for sensors.

**Frontend (Lovelace custom card):**
- Lit 3 + TypeScript.
- Rollup build → single ES module bundle.
- No external CSS framework. DM Sans / DM Mono via Google Fonts. CSS variables read from HA theme (`--primary-text-color`, `--card-background-color`, etc.) so light / dark follows HA.
- No date-picker libraries. Native `<input type="date">` with CSS styling.

**Tooling:**
- `ruff` for Python lint + format (HA convention).
- `pytest` + `pytest-homeassistant-custom-component` for backend tests.
- `vitest` + Lit testing utilities for the card.
- GitHub Actions: lint, typecheck, test on PR. Release workflow publishes the card bundle to GitHub Releases for HACS.

## 5. Repository layout

```
ha-splitsmart/
├── custom_components/splitsmart/
│   ├── __init__.py            # Integration setup / unload
│   ├── manifest.json          # HACS / HA metadata
│   ├── config_flow.py         # UI setup + options flow
│   ├── const.py               # Keys, defaults, event names
│   ├── coordinator.py         # DataUpdateCoordinator reading JSONL
│   ├── storage.py             # Append-only JSONL read/write primitives
│   ├── ledger.py              # Pure balance/split calculators
│   ├── rules.py               # Rules engine (match + action)
│   ├── fx.py                  # Frankfurter client + cache
│   ├── importer/
│   │   ├── __init__.py
│   │   ├── csv_parser.py
│   │   ├── xlsx_parser.py
│   │   ├── ofx_parser.py
│   │   ├── qif_parser.py
│   │   ├── presets.py         # Monzo / Starling / Revolut / Splitwise mappings
│   │   └── dedup.py           # Multiset duplicate detection
│   ├── telegram_ingest.py     # Listens for telegram_command events
│   ├── vision.py              # Anthropic / OpenAI vision clients
│   ├── services.yaml          # Service schemas
│   ├── sensor.py              # Balance / spending entities
│   ├── http.py                # aiohttp views for file uploads
│   └── frontend/
│       └── splitsmart-card.js # Built bundle, committed or release-published
├── frontend/                  # Source for the custom card
│   ├── package.json
│   ├── rollup.config.js
│   ├── tsconfig.json
│   └── src/
│       ├── splitsmart-card.ts
│       ├── views/             # Entry, staging, balances, settings
│       ├── components/        # Primitives: amount input, split picker, row card
│       ├── api.ts             # HA service + websocket wrapper
│       ├── types.ts
│       └── styles.ts
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_storage.py
│   ├── test_ledger.py
│   ├── test_rules.py
│   ├── test_dedup.py
│   ├── test_importers.py
│   ├── test_fx.py
│   ├── test_services.py
│   └── fixtures/
├── .github/workflows/
│   ├── test.yml
│   └── release.yml
├── hacs.json
├── README.md
├── SPEC.md
├── CLAUDE.md
├── CHANGELOG.md
└── LICENSE                    # MIT
```

## 6. Data model

### 6.1 Storage root

All data lives under `/config/splitsmart/`. Never under `/config/www/` — those files are web-accessible. The integration validates this path on startup and refuses to run if writing to `www`.

```
/config/splitsmart/
├── config.json                    # Cached config entry data
├── categories.json                # User-defined category list
├── rules.yaml                     # Rule library (user-editable on disk too)
├── staging/
│   └── <user_id>.jsonl            # Private to that user
├── shared/
│   ├── expenses.jsonl
│   ├── settlements.jsonl
│   └── tombstones.jsonl           # Edit/delete history
├── recurring.yaml                 # Recurring bill templates (user-authored)
├── recurring_state.jsonl          # Per-recurring last_materialised_date (machine-updated, newest-wins per id)
├── fx_rates.jsonl                 # Cached Frankfurter rates
└── receipts/
    ├── incoming/<uuid>.jpg        # Pre-OCR, private to uploader
    └── <yyyy>/<mm>/<expense_id>.jpg
```

### 6.2 File schemas

**`staging/<user_id>.jsonl`** — one JSON object per line:

```json
{
  "id": "st_01J9X...",
  "uploaded_by": "user_abc123",
  "uploaded_at": "2026-04-19T14:03:00+01:00",
  "source": "csv|xlsx|ofx|qif|telegram|manual",
  "source_ref": "statement_2026-04.csv",
  "source_ref_upload_id": "a1b2c3d4-e5f6-...",
  "source_preset": "Monzo",
  "date": "2026-04-15",
  "description": "WAITROSE ISLINGTON N1",
  "amount": 47.83,
  "currency": "GBP",
  "rule_action": "pending|always_split|always_ignore",
  "rule_id": "r_01J9X...",
  "category_hint": "Groceries",
  "dedup_hash": "sha256:...",
  "receipt_path": "receipts/incoming/abc.jpg",
  "notes": null
}
```

`source_ref_upload_id` links a staging row to the uploaded file it came from (the uuid filename under `/config/splitsmart/uploads/`). The daily cleanup task uses this reference to decide which uploads are still live. `null` for rows that did not originate from a file upload (e.g. `source=telegram` or `source=manual`).

`source_preset` records which import preset matched at parse time, or `null` when the row was imported via an explicit / saved mapping. Useful for audit and for one-click re-import UX.

**`shared/expenses.jsonl`** — canonical household ledger:

```json
{
  "id": "ex_01J9X...",
  "created_at": "2026-04-19T14:05:00+01:00",
  "created_by": "user_abc123",
  "date": "2026-04-15",
  "description": "Tesco Metro",
  "paid_by": "user_abc123",
  "amount": 82.40,
  "currency": "GBP",
  "home_amount": 82.40,
  "home_currency": "GBP",
  "fx_rate": 1.0,
  "fx_date": "2026-04-15",
  "categories": [
    {
      "name": "Groceries",
      "home_amount": 55.20,
      "split": {
        "method": "equal",
        "shares": [
          {"user_id": "user_abc123", "value": 50},
          {"user_id": "user_def456", "value": 50}
        ]
      }
    },
    {
      "name": "Household",
      "home_amount": 18.70,
      "split": {
        "method": "equal",
        "shares": [
          {"user_id": "user_abc123", "value": 50},
          {"user_id": "user_def456", "value": 50}
        ]
      }
    },
    {
      "name": "Alcohol",
      "home_amount": 8.50,
      "split": {
        "method": "exact",
        "shares": [
          {"user_id": "user_abc123", "value": 8.50},
          {"user_id": "user_def456", "value": 0.00}
        ]
      }
    }
  ],
  "source": "manual|staging|telegram|recurring",
  "staging_id": "st_01J9X...",
  "recurring_id": null,
  "receipt_path": "receipts/2026/04/ex_01J9X.jpg",
  "notes": null,
  "comments": []
}
```

**Split lives per allocation, not per expense.** This means a Tesco shop can split groceries 50/50 but charge 100% of the wine to one person. Uniform split (same split across every category) is the common case and the UI defaults to it — under the hood, the same split object is just cloned into each allocation, giving us one code path.

**Single-category expenses still use the list.** An entirely-Groceries £47.83 Waitrose shop stores as a list of one: `categories: [{name: "Groceries", home_amount: 47.83, split: {...}}]`. One code path, one schema.

**Invariants:**

- Sum of `categories[].home_amount` equals `home_amount` to 2dp.
- Each category's split shares validate against the category's `home_amount` (for `method: exact`) or to 100 / integer sum (for `equal`, `percentage`, `shares`).
- Every category has at least one participant with non-zero value.

**`shared/settlements.jsonl`**:

```json
{
  "id": "st_01J9X...",
  "created_at": "2026-04-19T14:10:00+01:00",
  "date": "2026-04-19",
  "from_user": "user_def456",
  "to_user": "user_abc123",
  "amount": 120.50,
  "currency": "GBP",
  "home_amount": 120.50,
  "notes": "April settle-up"
}
```

**`shared/tombstones.jsonl`** — edit / delete records for expenses, settlements and staging rows. Never rewrite an entry in place; always append a tombstone and a replacement:

```json
{
  "id": "tb_01J9X...",
  "created_at": "2026-04-19T14:15:00+01:00",
  "created_by": "user_abc123",
  "target_type": "expense|settlement|staging",
  "target_id": "ex_01J9X...",
  "operation": "edit|delete|discard",
  "previous_snapshot": { "...": "full prior state" },
  "reason": null
}
```

### 6.3 Append-only + tombstone pattern

Every mutation is an append. Effective state is computed by replaying the log and applying tombstones last. Benefits:

- Full audit history for free.
- Trivial restore of any deleted or edited entry.
- Safe concurrent writes (append is atomic up to OS page size; we keep lines well under 4 KB).
- Git-friendly if a user wants to version their ledger manually.

Performance: for a household logging 5000 expenses/year, the full log replays in under 100ms. We keep the coordinator's in-memory state warm so sensor reads are instant.

## 7. Privacy model

**Principle:** staging rows are private to the uploader. Shared ledger is visible to all configured participants. Tombstones of shared items are visible to all; tombstones of staging items are private.

**Enforcement:** every HA service call and aiohttp view checks `X-Hass-User` (or the equivalent internal `context.user_id`) against the data being requested. A user cannot read another user's staging file even by calling the service directly.

**Known limitation (documented in README):** HA admins can read files on disk via SSH or File Editor. Splitsmart does not encrypt at rest. The privacy guarantee is "the UI never exposes it, no other user can get to it via HA APIs". Users sharing an HA instance with someone they don't trust to that level shouldn't use the integration.

## 8. Currency and FX

**Home currency** set once in config flow (default GBP). All balances, monthly totals and dashboard entities render in home currency.

**Foreign-currency expenses** are optional per entry. When used, the expense stores:

- `amount` + `currency` (what the user paid)
- `home_amount` + `home_currency` + `fx_rate` + `fx_date` (converted once, locked in)

**Backdated entries** look up the historical rate from Frankfurter (`https://api.frankfurter.dev/v1/{date}?from={ccy}&to={home}`) at entry time. Rate + fx_date stored on the expense, never recalculated.

**Cache:** rates are cached in `fx_rates.jsonl` keyed on `(from, to, requested_date)`, newest-wins on read. Historical ECB rates are immutable once published, so the cache is authoritative for past dates; today's rate is cached on first call and reused for the remainder of the day. No pre-warming task — fetch-on-demand is sufficient at household scale.

**Failure model.** On a call to any write service that requires FX (non-home currency and no explicit `fx_rate`), the integration tries the cache first and Frankfurter on miss. If both fail, the write is rejected with `ServiceValidationError`; no partial or pending expense record is written. The caller (UI, automation, user at Developer Tools) retries when connectivity returns. `binary_sensor.splitsmart_fx_healthy` surfaces whether the most recent FX lookup succeeded within the last 24 hours.

## 9. Split and category allocation

Every expense is broken down into one or more **category allocations**, each of which has its own **per-person split**. Single-category expenses are a list of length 1. Uniform-split expenses (the common case) just clone the same split object into every allocation.

### 9.1 Category allocation

The `categories` field is a list of `{name, home_amount, split}` objects. Examples:

- A £47.83 pure-Groceries Waitrose shop: one allocation for £47.83 tagged Groceries.
- An £82.40 Tesco shop mixing food, cleaning supplies and wine: three allocations summing to £82.40.

**Invariant:** `sum(categories[].home_amount) == home_amount` to 2dp. Validated in `ledger.py` on every write.

**UI entry model:**

- Add-expense form shows a single category picker and a single split picker by default.
- "Split across categories" toggle reveals a multi-row allocator for amount-per-category.
- Two input modes for allocations: **amounts** (user types £20, £15, £10, UI validates the sum) or **percentages** (user types 50, 30, 20, UI computes amounts, last row absorbs rounding drift).
- Live remainder indicator is amber when drifted, green with tick when balanced. Save is disabled until balanced.

### 9.2 Per-allocation split

Each allocation carries a split object:

```json
{
  "method": "equal",
  "shares": [
    {"user_id": "u1", "value": 50},
    {"user_id": "u2", "value": 50}
  ]
}
```

Four methods, storage identical, UI rendering differs:

- **equal:** values are percentages, sum to 100, divide the allocation's `home_amount` proportionally.
- **percentage:** same storage as equal, different label (user explicitly chose non-equal percentages).
- **shares:** values are integer weights (e.g. 2, 1, 1 for a family of four). Share of allocation = value / sum(values).
- **exact:** values are absolute amounts in home currency, must sum to the allocation's `home_amount`.

**Default:** 50/50 equal for two-person configs, equal for 3+.

**Named preset splits** (configured via options flow, e.g. `rent_split: 60/40`) can be referenced by rules and quick-picked in manual entry. Changing a preset does not retroactively alter historical expenses — the split is stored in full on each allocation.

**Uniform-split UI shortcut:** most expenses use the same split across every category. The entry form defaults to a single split picker that is cloned into every allocation at save time. To customise per category, the user toggles "Different split per category", which expands each allocation row to show its own split picker.

### 9.3 Worked example: the mixed Tesco shop

£82.40 Tesco shop, Chris paid. Splits:

- Groceries £55.20 split 50/50 → Chris £27.60, Slav £27.60.
- Household £18.70 split 50/50 → Chris £9.35, Slav £9.35.
- Alcohol £8.50 charged 100% to Chris → Chris £8.50, Slav £0.

Totals per person (what each person owes for this expense):

- Chris: £27.60 + £9.35 + £8.50 = £45.45.
- Slav: £27.60 + £9.35 + £0 = £36.95.

Since Chris paid, Slav owes Chris £36.95 for this expense. The balance entity updates accordingly.

Per-category spend sensors:

- `sensor.splitsmart_spending_chris_month` — Groceries attribute gains £27.60, Household gains £9.35, Alcohol gains £8.50.
- `sensor.splitsmart_spending_slav_month` — Groceries attribute gains £27.60, Household gains £9.35, Alcohol gains £0.

### 9.4 Arbitrary participants

The data model supports N participants from day one. UI is optimised for 2-person couples but does not assume it — 3+ participants render as a full share grid per allocation.

### 9.5 Rules interaction

Rules assign a single category name and (optionally) a preset split. A rule-matched expense therefore creates a single-category allocation with that preset split. Multi-category and per-category-split entries are always manual decisions during review or detail editing. Rationale: the vast majority of rule-matched expenses are single-category (Netflix, utilities, rent); forcing rules to express per-category splits would complicate the rules file for little gain.

### 9.6 Validation summary

Enforced in `ledger.py` on every write path (`add_expense`, `edit_expense`, `promote_staging`):

- At least one category allocation per expense.
- Every allocation's `name` is a known category (or flagged with a warning if renamed/deleted historically — historical rows don't break).
- Sum of allocation `home_amount`s equals expense `home_amount` to 2dp.
- Each allocation's split:
  - `equal` / `percentage` / `shares`: at least one non-zero value, sum > 0.
  - `exact`: values sum to the allocation's `home_amount` to 2dp.
- At least one user has a non-zero value in every split.

## 10. Services — HA API surface

All services are under the `splitsmart` domain. Exposed via `services.yaml` so they appear in Developer Tools and in automations.

### `splitsmart.add_expense`

Direct entry to shared ledger. Input: date, description, amount, currency, paid_by, split method/shares, category, notes. The service fills in FX and writes to `shared/expenses.jsonl`.

### `splitsmart.add_settlement`

Record a payment. Input: date, from_user, to_user, amount, currency, notes.

### `splitsmart.edit_expense` / `splitsmart.delete_expense`

Append tombstone + replacement. ID-driven.

### `splitsmart.edit_settlement` / `splitsmart.delete_settlement`

Same pattern.

### `splitsmart.promote_staging`

Move a staging row to shared ledger. Input: staging_id, split, category, overrides. The staging row is marked promoted (tombstone), a new expense row created in shared.

### `splitsmart.skip_staging`

Mark a staging row ignored. Tombstone only — no shared ledger write.

### `splitsmart.import_file`

Trigger import of a previously uploaded file (uploaded via the custom card's file-upload endpoint). Input: file_id, mapping, rule_set. Returns count of rows imported + skipped-as-duplicate.

### `splitsmart.ingest_receipt`

Called internally by the Telegram flow, but exposed for scripting. Input: image_path, uploaded_by. Runs vision OCR, creates staging row, returns id.

### `splitsmart.apply_rules`

Re-run rules over existing pending staging rows. Useful after editing the rules file.

### `splitsmart.materialise_recurring`

Run the recurring-bills engine manually. Normally runs daily at 06:00.

## 11. Sensors and entities

Registered in `sensor.py` on integration setup. State values are all in home currency unless labelled.

| Entity | State | Attributes |
|---|---|---|
| `sensor.splitsmart_balance_<user>` | net balance (positive = owed, negative = owes) | per-partner breakdown |
| `sensor.splitsmart_spending_<user>_month` | user's share of shared spend this month | per-category breakdown |
| `sensor.splitsmart_spending_total_month` | household total this month | per-category breakdown |
| `sensor.splitsmart_pending_count_<user>` | count of pending rows in user's staging | last_imported_at |
| `sensor.splitsmart_last_expense` | description of most recent shared expense | amount, date, paid_by |
| `binary_sensor.splitsmart_fx_healthy` | on if FX feed reachable in last 24h | last_checked |

All sensors are `SensorDeviceClass.MONETARY` where appropriate, with `unit_of_measurement` set to the home currency symbol. `state_class: total` so they don't appear as cumulative on statistics graphs.

## 12. Import pipeline

### 12.1 Supported formats

| Format | Parser | Mapping required |
|---|---|---|
| CSV | built-in `csv` module | yes (or preset) |
| XLSX | `openpyxl` (read-only) | yes (or preset) |
| OFX | `ofxparse` | no (schema known) |
| QIF | hand-rolled parser | no (schema known) |
| Splitwise CSV | preset mapping | no |
| Monzo CSV | preset mapping | no |
| Starling CSV | preset mapping | no |
| Revolut CSV | preset mapping | no |

### 12.2 Column mapping UI

For CSV / XLSX without a matching preset, the card shows the first 10 rows of the file and asks the user to assign each column a role: `date`, `description`, `amount`, `currency`, `category` (optional), `ignore`. Roles that appear in every preset: date, description, amount. Currency defaults to home if absent. One-off: amount may be split into `debit` / `credit` columns — mapping supports both shapes.

Mappings are saved per file-origin hash so re-importing next month's statement uses the same mapping automatically.

### 12.3 Preset mappings (`importer/presets.py`)

Detected by looking at the header row. Each preset declares:

```python
{
  "name": "Monzo",
  "detect": lambda headers: {"Date", "Transaction Type", "Amount", "Name", "Notes"}.issubset(set(headers)),
  "mapping": {"Date": "date", "Name": "description", "Amount": "amount", "Notes": "notes_append"},
  "currency_col": None,
  "currency_default": "GBP",
  "amount_sign": "expense_positive"  # or "expense_negative"
}
```

Presets ship for: Splitwise export, Monzo, Starling, Revolut, generic OFX, generic QIF. Users can submit more via PR.

### 12.4 Duplicate detection (multiset)

Hash = `sha256(date + "|" + round(amount, 2) + "|" + currency + "|" + normalise(description))`.

Normalisation: upper, strip, collapse whitespace, strip leading `*` and trailing date strings that some issuers append to merchant names.

For each imported file:

1. Count occurrences of each hash in the file → `file_counts[hash]`.
2. Count occurrences of each hash already in staging + shared + discarded tombstones → `existing_counts[hash]`.
3. Import `max(0, file_counts[hash] - existing_counts[hash])` instances per hash.
4. Report `imported / skipped-as-duplicate` counts to the user.

Edge case covered: 3 identical coffees on the same day. Re-importing the same statement = 0 new rows. Adding 2 more coffees next week and re-importing = 2 new rows, regardless of which originals were promoted, skipped or still pending.

### 12.5 Rules engine

Defined in `/config/splitsmart/rules.yaml`. Evaluated in order, first match wins. Unmatched rows → `action: review_each_time`.

Rule schema:

```yaml
rules:
  - id: r_netflix
    name: Streaming subscriptions
    match: /netflix|spotify|disney|now tv|amazon prime/i
    amount: null            # optional: "> 10", "< 50", "10..50"
    action: always_split
    split:
      method: equal
      preset: 50_50
    category: Subscriptions

  - id: r_tfl
    match: /tfl|oyster|transport for london/i
    action: always_ignore

  - id: r_deliveroo_big
    match: /deliveroo|just eat|uber eats/i
    amount: "> 30"
    action: always_split
    split: {method: equal, preset: 50_50}
    category: Eating out

  - id: r_deliveroo_small
    match: /deliveroo|just eat|uber eats/i
    action: review_each_time
    category: Eating out
```

Three actions, in UI-friendly wording:

- `always_split` — auto-promote with the specified split + category.
- `always_ignore` — auto-skip, stays private, tombstoned so re-imports don't resurrect.
- `review_each_time` — lands in pending queue with category hint (not a commitment).

**Rule learning loop:** in the staging review UI, a kebab menu on any pending row offers "Always split rows like this" / "Always ignore rows like this". Opens the rule editor prefilled with a regex derived from the description (longest alphabetic run, case-insensitive). One click to save. Rules accumulate from real data rather than requiring upfront authoring.

**Rule testing:** rule editor shows a live count of rows in current staging the rule would match, so users can preview before committing.

## 13. Telegram OCR ingestion

**Motivation:** the fastest possible receipt capture is snapping a photo and sending it to a chat. No app-switching, no form-filling.

**Architecture:**

1. User configures HA's built-in Telegram Bot integration (out of scope for splitsmart). Each HA user's Telegram chat_id is mapped to their HA user_id in splitsmart's config flow.

2. Splitsmart subscribes to the `telegram_command` event (HA fires this on any Telegram message in a configured chat).

3. On receiving a photo: download via HA's Telegram helpers → save to `/config/splitsmart/receipts/incoming/<uuid>.jpg` → resolve sender to HA user → call vision API.

4. Vision API (default Anthropic Claude, optional OpenAI) returns structured JSON: `date`, `merchant`, `total`, `currency`, `confidence`.

5. Rule engine runs on the extracted row (matching against merchant string).

6. Bot replies with an inline keyboard:

   ```
   📷 Waitrose — £47.83 — 2026-04-15
   Category: Groceries (suggested)
   
   [Split 50/50]  [Ignore]  [Review later]  [Wrong, edit]
   ```

7. User taps one of the four. Choice maps to `promote_staging`, `skip_staging`, leave-pending, or open a follow-up dialog.

**Vision provider config:**

- `vision_provider: anthropic | openai | none`.
- API key stored in HA's config entry (encrypted by HA at rest).
- If `none`, photos still create staging rows with empty extraction, a placeholder description ("Telegram photo from 2026-04-19 14:03") and the photo attached — the user edits in the card.

**Prompt for vision call** (lives in `vision.py`):

```
You are an expense-extraction assistant. Extract structured data from this 
receipt image. Return ONLY valid JSON with these fields:
{
  "merchant": string (the business name, title case),
  "date": "YYYY-MM-DD" (prefer the transaction date; if unclear, null),
  "total": number (final amount paid, as a number not a string),
  "currency": "ISO 4217 code" (e.g. GBP, EUR, USD; guess from symbols/locale),
  "confidence": "high" | "medium" | "low",
  "notes": string or null (anything unusual the user should know)
}
If you cannot read the receipt, return:
{"confidence": "none", "notes": "<reason>"}
```

Low-confidence extractions still create a staging row but flag it in the bot reply: "⚠️ Low confidence — please check".

**Cost:** Anthropic Claude Haiku is sufficient for receipt extraction and costs ~$0.001 per image. A household snapping 100 receipts/month = ~10p/month. Users supply their own API key.

**Storage:** photo stays in `incoming/` until the row is promoted or skipped, then moves to `receipts/<yyyy>/<mm>/<expense_id>.jpg`. On skip, photo is deleted after 30 days (configurable).

## 14. Staging review UX (detailed spec for the card)

Pending queue view is the heart of the app. Optimise mercilessly for mobile, single-thumb operation.

**Row card:**

```
┌───────────────────────────────────────────┐
│ Waitrose                       £47.83     │
│ 15 Apr · Groceries                        │
│ [ Split 50/50 ]  [ Ignore ]  [ ⋯ ]        │
└───────────────────────────────────────────┘
```

- Tap "Split 50/50" → promotes with default 50/50 split, single-category allocation using the hint. Row slides out of queue with undo toast for 5s.
- Tap "Ignore" → tombstones, slides out with undo toast.
- Tap "⋯" → opens detail sheet: change split method, shares, category (single or multi-allocation), notes, view/attach receipt, view raw import data.
- Tap row body (not a button) → opens detail sheet in edit mode.

**Detail sheet category allocation:**

```
Category
┌───────────────────────────────────────────┐
│ ● Single category                         │
│   [ Groceries       ▾ ]                   │
│                                           │
│ ○ Split across categories                 │
└───────────────────────────────────────────┘

Split
┌───────────────────────────────────────────┐
│ [ Equal | % | Shares | Exact ]            │
│ Chris: 50%                                │
│ Slav:  50%                                │
└───────────────────────────────────────────┘
```

Toggle to "Split across categories":

```
Categories                           Mode: [ Amount | % ]
┌───────────────────────────────────────────┐
│ [ Groceries    ▾ ]  £ 55.20         [×]   │
│ [ Household    ▾ ]  £ 18.70         [×]   │
│ [ Alcohol      ▾ ]  £  8.50         [×]   │
│ + Add category                            │
│                                           │
│ Total: £82.40 ✓        Expense: £82.40    │
└───────────────────────────────────────────┘

Split
┌───────────────────────────────────────────┐
│ ● Same split for all categories           │
│   [ Equal | % | Shares | Exact ]          │
│   Chris 50% / Slav 50%                    │
│                                           │
│ ○ Different split per category            │
└───────────────────────────────────────────┘
```

Toggle to "Different split per category" — each allocation row expands with its own split picker:

```
Categories
┌───────────────────────────────────────────┐
│ ▾ Groceries                    £ 55.20    │
│   Split: [Equal]  Chris 50% / Slav 50%    │
│                                           │
│ ▾ Household                    £ 18.70    │
│   Split: [Equal]  Chris 50% / Slav 50%    │
│                                           │
│ ▾ Alcohol                      £  8.50    │
│   Split: [Exact]  Chris £8.50 / Slav £0   │
│                                           │
│ Total: £82.40 ✓                           │
└───────────────────────────────────────────┘
```

Each allocation row collapses/expands independently. Changing the split on one row doesn't affect others. Live remainder indicator (amber when drifted, green with tick when balanced) applies to both the amount sum and each allocation's split validity. Save disabled while anything is unbalanced.

**Bulk mode:**
- Long-press or "Select" button → checkboxes appear.
- Top action bar: "Split selected (12) / Ignore selected (12) / Bulk edit".
- Bulk edit lets user set category, split method, paid_by for all selected rows at once.

**Filters:**
- All pending / by source (CSV, Telegram, manual) / by date range.
- Search box filters by description substring.

**Empty state:**
- "No pending rows. Import a statement or add an expense manually."
- Two big buttons: "Import file" / "Add expense".

**Decided tabs (secondary):**
- "Auto-split (17)" — rows that auto-promoted today.
- "Auto-ignored (23)" — rows that auto-skipped today.
- Both support undo (reverses the tombstone, returns row to pending).

## 15. Frontend: Lovelace custom card

**Element name:** `splitsmart-card`.

**Views (routed by hash within the card):**

1. **Home:** balance summary + "You owe X" / "X owes you" headline + pending count chip + quick actions (add expense, import, review).
2. **Staging:** pending queue (section 14).
3. **Ledger:** shared expense list, filterable by month, category, paid_by.
4. **Add:** expense entry form (or open as modal sheet from home).
5. **Import:** upload file → mapping → preview → commit.
6. **Settle up:** record a payment, with balance suggestion.
7. **Rules:** list, edit, add, test.
8. **Settings:** categories, recurring bills, participants, Telegram chat IDs, vision provider.

**Visual design principles (the "AMAZING UI" brief):**

- Reads HA theme variables; light/dark follows automatically.
- DM Sans for UI, DM Mono for numbers and dates.
- Generous white space. Single focus per screen. No modal stacking.
- Numbers always right-aligned and tabular. Currency code next to amount for any non-home currency.
- Motion: 150-200ms ease-out on state transitions. No bouncy springs.
- Colour: accent = `var(--accent-color, #5b9f65)` with a green-for-credit / red-for-debit (colour-blind-friendly with icon backup).
- Touch targets minimum 44x44px throughout. No hover-only affordances.

**Registration:** the custom component serves the bundle via `async_register_static_paths` at `/splitsmart-static/splitsmart-card.js`, and registers it as a Lovelace resource automatically on setup. Users add `type: custom:splitsmart-card` to their dashboard; no manual resource-adding step.

## 16. Config flow

**Initial setup:**

1. Welcome + explain that data will be stored at `/config/splitsmart/`.
2. Participants: pick HA users who will share the ledger. At least 2.
3. Home currency: picker with common currencies at top.
4. Categories: prefilled (Groceries, Utilities, Rent, Eating out, Transport, Household, Entertainment, Other). Editable.
5. Named splits: optional, skip for 50/50 only.
6. FX provider: Frankfurter default, option to disable.
7. Vision provider: Anthropic / OpenAI / none. API key field if first two.
8. Telegram mapping: optional — map each participant to their Telegram chat_id.

**Options flow (reconfigurable after install):** all of the above except participants (changing those requires integration reload).

## 17. Notifications

Default notification targets are each participant's HA mobile companion. Events:

- New shared expense added by someone else.
- Settlement recorded.
- FX feed unreachable for >24h.
- Vision API rate-limited or failing.

All configurable per-participant in options flow. Notification payloads include a deep link that opens the relevant view in the card.

## 18. HACS packaging

**`hacs.json`:**

```json
{
  "name": "Splitsmart",
  "content_in_root": false,
  "render_readme": true,
  "zip_release": true,
  "filename": "splitsmart.zip",
  "homeassistant": "2026.1.0"
}
```

**`manifest.json`:**

```json
{
  "domain": "splitsmart",
  "name": "Splitsmart",
  "version": "0.1.0",
  "config_flow": true,
  "documentation": "https://github.com/cldoyle88/ha-splitsmart",
  "issue_tracker": "https://github.com/cldoyle88/ha-splitsmart/issues",
  "codeowners": ["@cldoyle88"],
  "requirements": [
    "aiofiles>=23.0",
    "openpyxl>=3.1",
    "ofxparse>=0.21"
  ],
  "iot_class": "local_push",
  "dependencies": ["http"]
}
```

**Release workflow:** GitHub Action on tag push builds the frontend bundle, zips `custom_components/splitsmart/` with the bundle inside, creates a GitHub Release with `splitsmart.zip` attached. HACS picks it up automatically.

## 19. Milestones

Each milestone is a PR target — tested, documented, self-contained.

The M1 completion report reshuffled milestones M2–M5: the Lovelace card landed first (so the data plane immediately got a driveable UI), the import pipeline moved earlier (bulk loading unlocks real-world usage), and FX / recurring / staging / rules slot in afterwards. Telegram OCR and polish keep their original positions. The current plan of record is:

### M1: Data plane (no UI) — ✓ Complete (2026-04-20)
- Component skeleton, config flow, storage layer, coordinator, ledger calculator, core services (`add_expense`, `add_settlement`, `edit_*`, `delete_*`), sensors.
- Drivable from Developer Tools → Services.
- Tests: storage, ledger, coordinator, services, sensors.

### M2: Lovelace custom card — ✓ Complete (2026-04-22)
- Build pipeline (Rollup + Lit 3 + TypeScript); single ES module bundle served from the integration.
- Websocket API: `get_config`, `list_expenses`, `list_expenses/subscribe` (init + delta events).
- Auto-registered Lovelace resource (storage mode) + INFO-logged snippet for YAML mode.
- Self-hosted DM Sans / DM Mono fonts (no external CDN calls).
- Views: Home (balance strip + quick actions), Ledger (filter chips, row cards), Add expense (full multi-category allocator, per-category splits), Settle up (pairwise-debt suggestion), expense + settlement detail sheets.
- Tests: ~109 jsdom component tests in vitest, ~108 Python tests, Pi QA checklist in `tests/MANUAL_QA_M2.md`.

### M3: Import pipeline
- CSV / XLSX / OFX / QIF parsers.
- Preset mappings (Monzo, Starling, Revolut, Splitwise).
- Column-mapping UI in the card.
- Multiset duplicate detection.
- Tests: each parser with fixture files, dedup matrix.

### M4: FX and recurring
- Frankfurter client with historical lookups, cache, daily refresh task.
- Recurring bills engine with daily materialisation.
- FX health binary sensor.
- Tests: FX mock HTTP, recurring edge cases (month-end, 29 Feb).

### M5: Staging + rules
- Staging storage + services (`promote_staging`, `skip_staging`).
- Rules engine with YAML file watcher.
- Staging view in card with one-tap actions and bulk mode.
- Rule editor view.
- Tests: rules engine, staging transitions.

### M6: Telegram OCR
- Telegram event subscriber.
- Vision client (Anthropic + OpenAI).
- Inline-keyboard reply flow.
- Config flow integration for Telegram mappings + vision key.
- Tests: vision client with mocked API, full flow with mock Telegram events.

### M7: Polish + release
- Notifications.
- Activity feed, search, category charts in card.
- README with screenshots / GIFs.
- HACS submission PR.
- v0.1.0 release.

## 20. Testing strategy

- **Unit:** pure functions (ledger, rules, dedup, FX conversion). Full coverage target.
- **Integration:** each service end-to-end against a temp `/config/splitsmart/` directory. Uses `pytest-homeassistant-custom-component`.
- **Frontend:** Vitest for component logic. Visual regression out of scope for v1.
- **Manual QA checklist** in `tests/MANUAL_QA.md` covering the review flows on mobile Safari and Android Chrome.

CI requires all of: `ruff check`, `ruff format --check`, `mypy` (soft), `pytest`, `vitest`. Coverage report posted on PR.

## 21. Open questions / v2 roadmap

Not in v1, tracked as issues:

- Itemised receipts (line-item splitting).
- Debt simplification for groups of 3+.
- Plaid / Open Banking auto-import.
- Payment provider settle-up (Monzo.me link, Revolut request).
- Cross-currency accounts (user paid EUR debts in EUR).
- Personal ledger (rejected from v1, may revisit if users ask).
- Receipt OCR via local model (Tesseract fallback when no API key).
- Budget tracking (per-category monthly budgets + alerts).
- CSV export of shared ledger.

## Appendix A: decision log

| Decision | Chosen | Alternative | Why |
|---|---|---|---|
| Storage format | Append-only JSONL | SQLite | Git-friendly, debuggable, adequate for scale, no locking. |
| Frontend | Lit + TS custom card | Standalone HTML | HACS expectation, native feel, future-proof. |
| Privacy | Per-user staging files | Single file with ACL | Simpler, admin access accepted as caveat. |
| Currency | Home + original stored | Convert on read | Stable historical balances. |
| Dedup | Multiset hash | Single-hash skip | Handles duplicate same-day purchases. |
| Rules | YAML file + 3 actions | UI-only config | Power users can version rules; 3 actions cover the space. |
| OCR | Vision API (optional) | Tesseract local | Quality gap too large on receipts. |
| Participants | Arbitrary N | Hardcode 2 | Trivial extra complexity, future-proof. |
| Multi-category | List of allocations, always | Single field + optional splits | One code path, one schema. Singleton lists are fine. |
| Split location | Per allocation | Per expense with per-category override | Removes inherit-vs-override logic. Uniform-split UI clones one picker under the hood. |

## Appendix B: glossary

- **Staging row:** imported but not yet decided. Private to uploader.
- **Promote:** move staging row to shared ledger with a split decision.
- **Skip / ignore:** tombstone a staging row; it stays private, doesn't appear anywhere, duplicates won't re-import.
- **Shared expense:** row in the shared ledger, affects balances.
- **Settlement:** payment between participants that reduces a balance.
- **Tombstone:** append-only record of an edit or delete.
- **Home currency:** the currency balances and sensors render in.
- **FX date:** the date the exchange rate was looked up (usually = expense date).
- **Preset split:** a named split (e.g. `rent_split: 60/40`) reusable in rules and manual entry.
- **Category allocation:** how a single expense's total is apportioned across one or more categories. Single-category expenses are a list of length 1. Each allocation carries its own per-person split.
- **Per-allocation split:** the share of an individual category allocation between participants. Default UI clones one split across every allocation ("same split for all"); users can opt into different splits per category.
- **Uniform split:** shorthand for an expense where every category allocation has the same split object. The UI default.
- **Allocation invariant:** the rule that category allocations on an expense must sum to the expense's home_amount to 2dp.
- **Pending row:** staging row with `rule_action: pending`, awaiting manual decision.
