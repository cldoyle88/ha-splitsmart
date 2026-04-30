# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added – M5 Staging, Rules, and Import (2026-04-30)

**Rules engine (`rules.py`)**
- Pure `Rule` dataclass with `id`, `description`, `pattern` (compiled regex),
  `currency_match`, `amount_min/max`, `action`, `category`, `split`,
  `priority`.
- `load_rules(path)` / `async_load_rules(path)` – parse and validate
  `rules.yaml`; errors are collected, not raised, so one bad rule doesn't
  block the rest.
- `apply_rules(rows, rules)` – pure function; returns `(auto_promoted,
  auto_ignored, review_each_time, still_pending)` counts.
- `build_categories_from_rule(rule, row)` – derives a single-category
  `CategoryAllocation` list from an `always_split` rule.

**Rules coordinator / services**
- `SplitsmartCoordinator.rules`, `rules_errors`, `rules_loaded_at`,
  `async_reload_rules()` wired into the coordinator.
- `splitsmart.apply_rules` service: runs the loaded rules against the
  caller's pending staging rows; returns auto-promoted, auto-ignored,
  auto-review, still-pending counts via `return_response`.

**Rules websocket commands**
- `splitsmart/list_rules` – one-shot read.
- `splitsmart/list_rules/subscribe` – push `init` on first connect, `reload`
  only when `rules_loaded_at` changes (not on every coordinator update).
- `splitsmart/reload_rules` – force a re-read from disk, returns version +
  counts + errors.
- `splitsmart/draft_rule_from_row` – generates a YAML snippet for a staging
  row (caller must own the row); action can be `always_split`,
  `always_ignore`, or `review_each_time`.

**30-second rules.yaml watcher (`__init__.py`)**
- `async_track_time_interval` polling `rules_yaml_path.stat().st_mtime`
  every 30 seconds; calls `coordinator.async_reload_rules()` on change.

**Staging websocket commands**
- `splitsmart/list_staging` – one-shot read, returns pending + review rows
  with tombstone list.
- `splitsmart/list_staging/subscribe` – live subscription with `init` + delta
  events (added / updated / deleted).

**Import services**
- `splitsmart.promote_staging` – promotes a staging row to an expense;
  accepts `paid_by`, `categories`, optional `override_description`,
  `override_date`, `notes`, `receipt_path`.
- `splitsmart.skip_staging` – tombstones a staging row (idempotent; row can
  be re-imported).
- `splitsmart.apply_rules` – see above.

**Frontend – Home view**
- `<ss-home-view>`: "Coming in M5" placeholder tile replaced by a live
  import tile; navigates to `#import`. Shows a pending-row badge when the
  `sensor.splitsmart_pending_count_<user>` sensor returns a non-zero value.

**Frontend – Import view (`ss-import-view`)**
- Drag-and-drop / file-browse area for CSV, OFX, QFX, XLSX.
- Uploads via `POST /api/splitsmart/upload` + `splitsmart/inspect_upload`.
- If a preset or saved mapping is found: imports immediately via
  `splitsmart.import_file`, shows summary, offers "Review pending" CTA.
- If no mapping: routes to the column-mapping wizard at `#wizard/<upload_id>`.

**Frontend – Column-mapping wizard (`ss-import-wizard-view`, `ss-column-role-picker`)**
- Three-step wizard: Preview (header + sample rows) → Roles (per-column
  `date | description | amount | debit | credit | currency | ignore`) →
  Commit (save mapping + import + navigate to staging).
- `<ss-column-role-picker>` primitive: column header, up to 3 sample values,
  native `<select>` for role.
- `defaultRoles()` auto-assigns common header names; `isReadyToCommit()`
  guards the Commit button (needs date + description + amount/debit+credit).

**Frontend – Rules view (`ss-rules-view`)**
- Live subscription to `splitsmart/list_rules/subscribe`.
- Read-only rule list with action badge (green = always-split, grey =
  always-ignore, yellow = review-each-time).
- Reload button calls `splitsmart/reload_rules`.
- Error list (red boxes) for YAML parse failures.
- Empty state shows a YAML snippet template.

**Frontend – Staging review queue (`ss-staging-view`)**
- Live subscription to `splitsmart/list_staging/subscribe`.
- Per-row quick actions: Split 50/50 (promotes with default equal split),
  Ignore (skips); FX rows have Split 50/50 disabled.
- Tap row body → navigates to `#staging/<id>` (detail sheet).
- Bulk mode: long-press (600 ms) → checkbox mode; "Skip selected" skips all
  checked rows sequentially.
- Filter chips by source_preset and foreign currency.
- 5-second auto-dismiss toast confirms each action.
- Empty state with "Import file" and "Add expense" CTAs.

**Frontend – Staging detail sheet (`ss-staging-detail-sheet`)**
- Per-row detail overlay at `#staging/<staging_id>`; self-subscribes to find
  its row by ID.
- Paid-by picker, category + split picker (single or multi-allocation via
  `<ss-allocation-editor>`).
- Collapsible "Override description / date / notes" and "Import metadata"
  sections.
- Promote → `splitsmart.promote_staging`. Skip → `splitsmart.skip_staging`.
- FX rows: home-amount input replaces quick split; FX banner explains the
  lookup happens at promote time.
- "Create rule from this row" section with three action buttons (always
  split / always ignore / review each time) that call
  `splitsmart/draft_rule_from_row` and open the rule-snippet sheet.

**Frontend – Rule snippet sheet (`ss-rule-snippet-sheet`)**
- Overlay showing the YAML snippet returned by `draft_rule_from_row`.
- Copy-to-clipboard with visual feedback; falls back to text-selection when
  the Clipboard API is unavailable.

**Frontend – Router + card wiring**
- Router: `'rules' | 'import' | 'wizard' | 'staging'` added to `RouteView`.
  `wizard` and `staging/<id>` support an optional param segment.
- `splitsmart-card.ts`: routes wired; staging detail overlay treated as a
  quasi-detail so `_backgroundRoute` stays at `#staging`.

**Manual QA checklist** — `tests/MANUAL_QA_M5.md` (items covering rules,
staging, import, and wizard flows).

### Fixed – M4.2 hotfix (2026-04-27)

**Bug A – `_resolve_fx` AttributeError on explicit `fx_date`**
- All service handlers were calling `.isoformat()` on the `datetime.date`
  from `cv.date` before passing it to `_resolve_fx`, which then called
  `.isoformat()` again on the resulting string.
- Fix: callers now pass the `datetime.date` object directly; `_resolve_fx`
  retains its `.isoformat()` call and its parameter type is updated to
  `date | None`.

**Bug B – unhandled exceptions surfaced as "Unknown error"**
- Any unexpected exception that escaped a service handler was wrapped by HA
  as the opaque `unknown_error` code with no actionable message.
- Fix: `_service_guard` decorator on every handler catches unexpected
  exceptions, logs the full traceback at ERROR, and re-raises as
  `ServiceValidationError("Internal error in <service>: …")`.
  `ServiceValidationError`, `HomeAssistantError`, and `vol.Invalid` pass
  through unchanged.

**Bug C – blocking I/O in `load_recurring`**
- `load_recurring` called `path.read_text()` synchronously inside the event
  loop; under SD card I/O latency this stalled other integrations.
- Fix: converted to `async def`, using `aiofiles.open` / `await fh.read()`
  to match the pattern used by `load_recurring_state`. Both callers
  (`__init__.py` daily materialiser and `services.py` on-demand handler)
  updated to `await`.

### Added – M4 FX and Recurring Bills (2026-04-24)

**FX client and cache (`fx.py`)**
- `FxClient(hass, storage)` resolves exchange rates via Frankfurter
  (`https://api.frankfurter.dev/v1/{date}?from=X&to=Y`). Cache-first:
  looks up `fx_rates.jsonl` by `(from_currency, to_currency,
  requested_date)` before hitting the network. Stores `fx_date`
  separately so weekend re-queries hit the cache without a second
  network call.
- 5-second timeout; one automatic retry after a 0.5-second backoff.
  Uses HA's shared `async_get_clientsession` session.
- Error taxonomy: `FxUnavailableError` (network/timeout),
  `FxUnsupportedCurrencyError` (404 from Frankfurter),
  `FxSanityError` (suspicious-rate sanity guard).
- Sanity guard: if `abs((today − expense_date).days) ≤ 365` and the
  resolved rate diverges from today's live rate by more than 50%,
  `FxSanityError` is raised. Today's-lookup failure silently skips
  the guard so it can't block a write where the primary lookup
  succeeded.

**FX on services (`services.py`)**
- `_resolve_fx()` implements the cascade: same-currency shortcut →
  explicit `fx_rate` override → live cache/network lookup + sanity
  guard.
- `add_expense`, `edit_expense`, `add_settlement`, `edit_settlement`
  all pass through `_resolve_fx`; `home_amount` is now
  `amount × fx_rate` rounded to 2 dp.
- `promote_staging` no longer blocks foreign-currency rows with the
  M3 placeholder message; it invokes the same FX cascade.
- `add_expense` and `add_settlement` schemas gain optional `fx_rate`
  (float, > 0) and `fx_date` (date string) fields for explicit
  overrides.

**Expense and settlement records (`ledger.py`)**
- `build_expense_record` and `build_settlement_record` gain `fx_rate`
  and `fx_date` parameters; both fields are written to the JSONL
  record. `fx_date` defaults to the expense date when omitted.
- `recurring_id` field added to expense records (null for non-recurring).

**`binary_sensor.splitsmart_fx_healthy` (`binary_sensor.py`)**
- `BinarySensorDeviceClass.CONNECTIVITY`, `EntityCategory.DIAGNOSTIC`.
- `is_on` when the most recent successful Frankfurter fetch is within
  24 hours of now.
- `extra_state_attributes`: `{"last_checked": <ISO-8601 or null>}`.
- Refreshes on coordinator tick (every 5 minutes).

**Storage path helpers (`storage.py`, `const.py`)**
- `SplitsmartStorage` gains `.fx_rates_path`, `.recurring_yaml_path`,
  `.recurring_state_path`.
- `ensure_layout()` touches `fx_rates.jsonl` and
  `recurring_state.jsonl` on first run; `recurring.yaml` is
  intentionally user-created.

**Recurring bills (`recurring.py`)**
- `load_recurring(path, *, participants)` parses `recurring.yaml`
  with voluptuous. Schedules: `monthly` (day 1–31, clamped for short
  months), `weekly` (weekday name), `annually` (month + day, clamped
  for non-leap Feb). Invalid entries are skipped with ERROR; duplicate
  IDs reject the second entry.
- `schedule_matches(schedule, date)` and
  `dates_in_range(schedule, *, floor, ceiling)` are pure helpers.
- `load_recurring_state` / `append_recurring_state` manage
  `recurring_state.jsonl` with `rs_`-prefixed IDs and newest-wins
  semantics per `recurring_id`.
- `materialise_recurring()` two-belt idempotency: Belt 1 is the state
  file; Belt 2 scans existing expenses for `(recurring_id, date)`
  collisions. FX failures skip the date and leave state un-advanced
  for that entry. Last allocation in each expense absorbs rounding
  drift so `sum(category.home_amounts) == home_amount` exactly.
  First materialisation with > 3 due dates logs an INFO backfill
  advisory.

**Daily 03:00 materialisation (`__init__.py`)**
- `async_track_time_change(hour=3, minute=0, second=0)` fires
  `_materialise_daily` on each entry setup. Loads `recurring.yaml`,
  reads state, reads existing expenses, calls `materialise_recurring`,
  refreshes the coordinator if new expenses were written.

**`splitsmart.materialise_recurring` service**
- On-demand trigger for the 03:00 task. Accepts optional
  `recurring_id` to process a single entry; raises
  `ServiceValidationError` for unknown IDs. Returns
  `{materialised, skipped_fx_failure, skipped_duplicate}` via
  `SupportsResponse.OPTIONAL`.

**Tests (75 new tests; 356 backend total)**
- FX client (13): cache-first, network miss, timeout, retry, same-ccy
  shortcut, unsupported-currency 404, JSONL cache write.
- FX sanity (7): inside-window pass, outside-window block, edge
  thresholds, today-lookup-failure skips guard.
- `binary_sensor.splitsmart_fx_healthy` (7): on/off transitions, null
  last_checked, 24 h boundary.
- Recurring loader (13): happy paths, missing file, malformed partial
  load, paid_by not participant, duplicate id, bad day/weekday.
- Recurring schedule (11): monthly clamping, weekly, annually,
  dates_in_range multi-year, edge cases.
- Recurring materialiser (14): one date, 3-month catch-up, state
  respects, already-current, end-date boundaries, Belt 2
  idempotency, FX failure, EUR rescaling, float drift, filter_id.
- Materialise service (5): write, no-yaml, filter_id, unknown id,
  idempotency.

**Manual QA checklist** — `tests/MANUAL_QA_M4.md` (14 items).

### Added – M3 Import Pipeline (2026-04-22)

**Parsers + mapping cascade (`custom_components/splitsmart/importer/`)**
- CSV, XLSX, OFX and QIF parsers with a uniform `inspect(path)` +
  `parse(path, mapping)` surface. CSV tries UTF-8-with-BOM and
  falls back to cp1252 so Excel-on-Windows exports round-trip
  cleanly. XLSX runs `openpyxl` under `run_in_executor` to keep
  the event loop responsive. OFX uses `ofxparse` under the same
  executor pattern; QIF is hand-rolled against the line-oriented
  format with D/T/P/M/L codes and a trailing-caret tolerance for
  real-world dialects. Per-row parse errors accumulate on
  `ParseOutcome.errors` instead of aborting the whole file.
- Preset registry (`presets.py`) for Monzo, Starling, Revolut and
  Splitwise. Detectors require a distinctive column per preset
  (Monzo's Emoji, Starling's Counter Party, Revolut's Started
  Date + Product, Splitwise's Cost) so a generic "Date, Name,
  Amount" CSV doesn't masquerade as any of them. Case-insensitive;
  tolerates extra columns.
- `apply_mapping` translates one raw row to a canonical `RawRow`,
  handling commas, £/$/€, accountant-style parens on amounts, and
  a short UK-first list of date formats. ISO dates via
  `datetime.fromisoformat` first (covers Starling's timestamp
  cells); strptime fallback otherwise.
- `file_origin_hash` is a stable SHA-1 fingerprint over the
  normalised header row, column count and extension so next
  month's same-shape file resolves to the same key.
- `mappings.jsonl` persists user-authored column mappings keyed
  on the origin hash. Newest entry per hash wins on read.
- `importer.__init__.py` facade exposes `inspect_file(path,
  storage)` and `parse_file(path, *, user_mapping, storage)` — the
  mapping cascade is explicit arg > preset > saved-by-hash, and
  raises `ImporterError(code="mapping_required", inspection=...)`
  when nothing resolves so Developer Tools / the M5 wizard can
  surface a column-picker without a second round trip.

**Multiset dedup (`importer/dedup.py`)**
- `partition_by_dedup` is pure multiset arithmetic over three
  pre-filtered lists: caller's effective staging, effective
  shared ledger, caller's discard-only staging tombstones.
  Promote tombstones are intentionally excluded because the
  resulting shared expense already counts in `existing_shared` —
  this is why staging gets a new `TOMBSTONE_PROMOTE` operation
  rather than overloading `discard` with a `replacement_id` flag.
- Description normalisation (`normalise.py`) strips leading `*`,
  trailing dd/mm or yyyy-mm-dd date suffixes, upper-cases and
  collapses whitespace, so three coffees in a row all share one
  hash and `TFL TRAVEL 15/04` collapses with `TFL TRAVEL 16/04`.

**Staging lifecycle (`services.py`, `services.yaml`)**
- `splitsmart.import_file(upload_id, mapping?, remember_mapping?)`
  ties the upload endpoint, parser facade, dedup and staging
  write together. Response reports `imported`,
  `skipped_as_duplicate`, `parse_errors`, and `blocked_foreign_currency`
  (rows that staged but can't be promoted until M4 FX lands),
  plus the detected preset name. Foreign-currency rows stage with
  their original currency; the per-sensor partition in step 7
  surfaces the running total.
- `splitsmart.promote_staging` writes the new shared expense
  first, then a tombstone with `operation="promote"` and
  `replacement_id=<expense_id>`. `paid_by` is free-form subject
  to participant validation — the uploader and the payer are
  decoupled (Chris imports the joint-account statement, Slav
  paid some rows).
- `splitsmart.skip_staging` writes `operation="discard"`, with
  `previous_snapshot` carrying the full staging row including
  `dedup_hash` so skip-is-sticky survives re-imports.
- Both staging services reject cross-user access with
  `permission_denied` per SPEC §7; foreign-currency rows at
  promote surface the verbatim user-facing "Foreign currency
  promotion arrives in M4. Row stays staged." error.

**Materialisation + coordinator (`ledger.py`, `coordinator.py`)**
- `materialise_staging` lives next to its siblings, applying the
  shared tombstones log to any raw staging list. `st_` ids can't
  collide with `ex_` or `sl_` so no target_type filter is needed.
- `SplitsmartData` gains `raw_staging_by_user` / `staging_by_user`
  / `last_staging_id_by_user` fields keyed on HA user_id. Full
  replay iterates `entry.data[CONF_PARTICIPANTS]` — the config
  entry is authoritative for "who has staging state", so orphan
  staging files on disk for removed users are not surfaced.
- `async_note_write` gains a `staging_user_id` kwarg. Service
  handlers that wrote to a user's staging pass that user's id;
  the coordinator reloads only that user's staging file rather
  than every participant's. Writes that don't touch staging
  (add_expense, etc.) continue to pass no arg and skip the
  staging refresh entirely.

**File upload endpoint (`http.py`)**
- `POST /api/splitsmart/upload` accepts a multipart `file` field,
  validates the caller is a Splitsmart participant, checks the
  extension against `{csv,xlsx,ofx,qif}`, streams to
  `/config/splitsmart/uploads/<uuid4>.<ext>`. A pre-flight
  `Content-Length` check plus a running size counter during the
  stream enforce a 25 MB cap. Inspection payload populated for
  CSV/XLSX; null for OFX/QIF. Malformed-content inspection
  failures don't abort the upload — the wizard can retry with an
  explicit mapping.

**Hourly cleanup (`cleanup.py`)**
- `sweep_uploads` deletes files under `uploads/` that are BOTH
  older than 24 hours AND not referenced by any live staging
  row's `source_ref_upload_id`. `async_track_time_interval` fires
  the sweep hourly (O3 decision — resilient to restart clock
  skew, keeps the window tight). Pure function; `retention_seconds`
  and `now` injectable so tests don't have to fake clocks.

**Pending-count sensor (`sensor.py`)**
- `sensor.splitsmart_pending_count_<user>`, one per participant.
  State = count of `rule_action == "pending"` rows in that
  user's effective staging. Attributes include `user_id` (for
  frontend lookup), `promotable_count`, and
  `blocked_foreign_currency_count`; the partition invariant
  `state == promotable_count + blocked_foreign_currency_count`
  is asserted by tests. `last_imported_at` and
  `oldest_pending_date` round out the card's needs.

**Websocket API (`websocket_api.py`)**
- `splitsmart/list_staging`: one-shot, user-scoped. Returns the
  caller's materialised staging rows plus the staging tombstones
  targeting them. A request with `user_id != caller` returns
  `permission_denied` so the card cannot inadvertently request
  another participant's staging.
- `splitsmart/list_staging/subscribe`: long-lived, user-scoped.
  Delta events fire only when the caller's staging changes — u1's
  subscription doesn't see u2's writes.
- `splitsmart/list_presets`: static registry dump for the wizard.
- `splitsmart/save_mapping`: persists a mapping under its origin
  hash.
- `splitsmart/inspect_upload`: re-runs `inspect_file` on a prior
  `upload_id` so the wizard can re-render headers + samples
  without re-uploading.

**SPEC + constants**
- `TOMBSTONE_PROMOTE = "promote"` added to `const.py`. Tombstone
  records gain an optional `replacement_id` field on
  `append_tombstone`; written only for promote tombstones.
- SPEC §6.2 amended to document `source_ref_upload_id` and
  `source_preset` on the staging schema example (per O7).

**Home tile live count (frontend)**
- `<ss-placeholder-tile>` gains an optional `pendingCount`
  property. When set, the caption flips to "You have N rows to
  review" / "You have 1 row to review" / "You're all caught up"
  depending on the value; when null, the static caption stays.
  The "Coming in M5" badge and `aria-disabled="true"` styling
  stay regardless — the review queue UI is still M5.
- `<ss-home-view>` takes a `pendingCount` prop and threads it to
  the tile. The root card resolves the current user's sensor by
  scanning `hass.states` for
  `sensor.splitsmart_pending_count_*` entities and matching on
  the `user_id` attribute (simpler than slugging the display name
  into an entity_id).

**Tests (198 new tests; 285 backend + 114 frontend total)**
- Normalise (22): description recipe, hash stability, amount
  rounding, field separation.
- Presets (9): preset detection happy paths, case-insensitivity,
  extra-column tolerance, required-key schema check.
- Mapping (17): `file_origin_hash` stability and bucket
  separation, `save/load` round-trip, newest-wins, Monzo /
  Splitwise / Revolut / debit-credit translations, comma/parens
  parsing.
- Parsers (23): each bank's preset fixture + OFX/QIF sample, UTF-8
  BOM + cp1252 fallback, empty file, malformed row, XLSX
  datetime + short-row handling, QIF trailing-caret + type-
  directive tolerance.
- Facade (11): cascade resolution, `mapping_required` error,
  unsupported extension, OFX/QIF skip the cascade.
- Dedup (19): all eight M3_PLAN §4 edge cases plus empty inputs
  plus a parametrised partition-sum invariant.
- Services (20): happy path + re-import + partial dedup + skip
  sticky for `import_file`; uploader-paid-by-partner,
  cross-user rejection, foreign-currency message, override
  description/date for `promote_staging`; dedup-hash
  preservation, double-call rejection for `skip_staging`.
- Sensor (6): zero/empty, rule_action filter, partition invariant
  (3 GBP + 2 EUR + 1 USD → 3/3), per-user scoping, attribute
  metadata, unique id.
- Coordinator (6): per-user staging full replay, orphan-file
  ignore, scoped refresh via `staging_user_id` hint.
- HTTP upload (14): happy paths, auth/authz rejections, extension
  whitelist + case-insensitivity, `Content-Length` cap, write-
  target verification.
- Cleanup (9): retention window, reference protection across
  users, directory entries skipped, missing-field tolerance.
- Websocket (14): list_staging scoping + tombstone surfacing,
  subscribe cross-user isolation, presets dump, save_mapping
  round-trip, inspect_upload happy + not_found + permission.
- Frontend placeholder tile (+6): plural/singular/zero captions,
  null-fallback, badge + aria-disabled stability.

**Fixtures (`tests/fixtures/imports/`)**
- Anonymised samples committed as immutable test inputs (per
  CLAUDE.md): Monzo classic (10 rows with income + transfer),
  Starling GBP (10 rows incl. standing order), Revolut (10 rows
  spanning GBP/EUR/USD), Splitwise export (10 rows with category
  hints), generic debit/credit CSV, generic no-preset CSV,
  malformed CSV, minimal OFX 1.x SGML body, 10-transaction QIF.

### Pi QA outcome (2026-04-22)

M2 passed the 17-section Pi QA checklist (`tests/MANUAL_QA_M2.md`). Two intermittent symptoms observed once and not reproduced after a fresh session were filed as M7-polish issues rather than blockers:

- [#3](https://github.com/cldoyle88/ha-splitsmart/issues/3) – two-client edit race producing a "not found" toast when a stale tab submits after a delta has retired the id.
- [#4](https://github.com/cldoyle88/ha-splitsmart/issues/4) – multi-category Save button intermittently disabled. Float-drift root cause was investigated and ruled out (the 0.01 tolerance passes the Tesco case exactly). Awaits a reliable repro.

Related fixes shipped during QA (already squashed into M2):

- Removed `return_response: true` from `hass.callService` options — HA 2026.x rejects the older target-arg shape and the card doesn't consume the id (delta subscription delivers new records).
- `LastExpenseSensor` now explicitly sets `state_class = None` and `device_class = None` so HA 2026.x's strict non-numeric-state validation doesn't reject its string value.

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
