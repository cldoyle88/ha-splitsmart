# M3 Manual QA Checklist

Prerequisites: M1 data plane + M2 card loaded (see `MANUAL_QA_M1.md`
and `MANUAL_QA_M2.md`). Two HA users configured (Chris `abc123`, Slav
`def456`), home currency GBP. Frontend bundle rebuilt after M3
changes (`cd frontend && npm run build:prod`). Lovelace in storage
mode unless a specific test calls for YAML.

Before running: restart HA so the integration picks up M3's new HTTP
view (`/api/splitsmart/upload`), new services (`import_file`,
`promote_staging`, `skip_staging`), new websocket commands
(`splitsmart/list_staging`, `/list_staging/subscribe`,
`/list_presets`, `/save_mapping`, `/inspect_upload`), the pending-
count sensor, and the hourly cleanup task.

A long-lived access token is needed for the HTTP upload tests
(Profile → Long-lived access tokens → Create).

---

## 1 – Upload endpoint via `curl`

- [ ] `curl -X POST http://<ha>:8123/api/splitsmart/upload \
         -H "Authorization: Bearer <TOKEN>" \
         -F "file=@tests/fixtures/imports/monzo_classic.csv"` returns
       HTTP 200 with a JSON body containing `upload_id`, `filename`,
       `size_bytes`, `extension: "csv"`, and an `inspection` object with
       `preset: "Monzo"`.
- [ ] The file lands on disk at
      `/config/splitsmart/uploads/<upload_id>.csv`.
- [ ] POST without the Bearer header returns 401.
- [ ] POST with a bearer for a user not in `CONF_PARTICIPANTS`
      returns 403 `{"error": "permission_denied"}`.
- [ ] POST with `-F "file=@tests/fixtures/imports/generic_no_preset.csv"` —
      response 200, `inspection.preset: null`, `inspection.headers`
      contains the four header strings.
- [ ] POST of a `.pdf` returns 415 `{"error": "unsupported_media_type"}`.
- [ ] POST of a > 25 MB file (`dd if=/dev/zero of=/tmp/big.csv bs=1M
      count=30 && ...`) returns 413 `{"error": "payload_too_large"}`.

## 2 – `splitsmart.import_file` happy path

- [ ] Developer Tools → Services → `splitsmart.import_file`, paste
      `{"upload_id": "<from step 1>"}`, Call Service. Service returns
      `{"imported": 10, "skipped_as_duplicate": 0, "parse_errors": 0,
       "blocked_foreign_currency": 0, "preset": "Monzo"}`.
- [ ] `sensor.splitsmart_pending_count_chris` now reports `10`.
- [ ] `/config/splitsmart/staging/abc123.jsonl` has 10 lines; each
      carries `source_ref_upload_id` matching the upload uuid,
      `source_preset: "Monzo"`, `rule_action: "pending"`,
      `dedup_hash: "sha256:..."`.

## 3 – Re-import same file is fully deduped

- [ ] Upload the same `monzo_classic.csv` again (new `upload_id`).
- [ ] `splitsmart.import_file` returns
      `{"imported": 0, "skipped_as_duplicate": 10, ...}`.
- [ ] Staging file still has 10 lines. Pending count still 10.

## 4 – Promote a row end-to-end

- [ ] Developer Tools → `splitsmart.promote_staging` with
      `{"staging_id": "<pick one>", "paid_by": "abc123",
        "categories": [{"name": "Groceries", "home_amount": 47.83,
         "split": {"method": "equal",
          "shares": [{"user_id": "abc123", "value": 50},
                     {"user_id": "def456", "value": 50}]}}]}`.
- [ ] Service returns `{"expense_id": "ex_...", "staging_id": "st_..."}`.
- [ ] `sensor.splitsmart_balance_chris` updates on the card within 1 s.
- [ ] Pending count drops to 9.
- [ ] `/config/splitsmart/shared/tombstones.jsonl` has a new
      `operation: "promote"` line carrying `replacement_id: "ex_..."`.

## 5 – Skip a row

- [ ] `splitsmart.skip_staging` with `{"staging_id": "<pick one>"}`.
- [ ] Pending count drops by 1. Balance sensors unchanged.
- [ ] Tombstones log has an `operation: "discard"` entry whose
      `previous_snapshot.dedup_hash` matches what was on the staging
      row (the skip-is-sticky invariant).

## 6 – Uploader-paid-by-partner flow

- [ ] As Chris, upload and import a statement (`source_ref` reflects
      Chris's user_id).
- [ ] Promote one row with `paid_by: "def456"` (Slav paid on the
      joint card). Service accepts and writes an expense whose
      `paid_by == "def456"` while `source == "staging"` and the
      tombstone's `previous_snapshot.uploaded_by == "abc123"`.

## 7 – Foreign-currency accounting (O4)

- [ ] Upload and import `revolut_account.csv`.
- [ ] Service response carries `{"imported": 10,
      "blocked_foreign_currency": 5, "preset": "Revolut"}`.
- [ ] `sensor.splitsmart_pending_count_chris` state = 10;
      attributes:
      `promotable_count == 5`, `blocked_foreign_currency_count == 5`,
      `promotable_count + blocked_foreign_currency_count == state`.
- [ ] Developer Tools → `splitsmart.promote_staging` on one of the
      EUR rows → returns `ServiceValidationError` with the exact
      message **"Foreign currency promotion arrives in M4. Row stays
      staged."**. Staging row remains live (pending count unchanged).

## 8 – Mapping-required flow

- [ ] Upload `generic_no_preset.csv`. Call `splitsmart.import_file`
      with only `{"upload_id": "<uuid>"}`. Service fails with
      `mapping_required: ...` — the `err.inspection` payload has
      `headers: ["Posted", "Merchant", "Spent", "Note"]`.
- [ ] Re-call with an explicit mapping:
      ```
      {"upload_id": "<uuid>",
       "mapping": {"date": "Posted", "description": "Merchant",
                   "amount": "Spent", "currency_default": "GBP",
                   "amount_sign": "expense_positive",
                   "date_format": "auto", "notes_append": ["Note"]},
       "remember_mapping": true}
      ```
- [ ] Service returns `{"imported": 5, ...}`.
- [ ] `/config/splitsmart/mappings.jsonl` gains one entry with the
      supplied mapping keyed under the file's `sha1:` origin hash.

## 9 – Saved mapping re-used on next-month import

- [ ] Take the same generic-shape CSV, rename the file, upload again.
- [ ] Call `splitsmart.import_file` with ONLY `{"upload_id": ...}` —
      no `mapping` arg. Service succeeds (saved mapping resolved by
      hash). `preset` is still `null` in the response; `imported`
      reflects dedup state.

## 10 – OFX + QIF need no mapping

- [ ] Upload `sample.ofx`, `import_file` → `{"imported": 5, ...}`.
      Staging rows have `source: "ofx"`, `source_preset: null`.
- [ ] Upload `sample.qif`, `import_file` → `{"imported": 10, ...}`.
      Staging rows have `source: "qif"`.

## 11 – Malformed CSV surfaces errors, doesn't abort

- [ ] Upload `malformed.csv`, `import_file` → response carries
      `{"imported": 2, "parse_errors": 1, "first_error_hint": "..."}`.
      Pending count goes up by 2, not 3.

## 12 – Websocket commands via Developer Tools

- [ ] Developer Tools → WebSocket API → send
      `{"type": "splitsmart/list_staging"}`. Response carries
      `{"rows": [...], "tombstones": [...], "total": <count>}`
      scoped to the caller.
- [ ] Send `{"type": "splitsmart/list_staging", "user_id": "def456"}`
      as Chris → response is `{"error": "permission_denied"}`.
- [ ] `{"type": "splitsmart/list_presets"}` → four presets (Monzo,
      Starling, Revolut, Splitwise).
- [ ] `{"type": "splitsmart/inspect_upload", "upload_id": "<csv>"}`
      → response `inspection` matches what the upload endpoint
      returned.
- [ ] `{"type": "splitsmart/save_mapping", "file_origin_hash":
      "sha1:test", "mapping": {...}}` → `saved: true`.

## 13 – Home tile live count

- [ ] On the card, Home view shows the "Pending review" tile with
      caption **"You have N rows to review"** matching the pending-
      count sensor state.
- [ ] After a `promote_staging`, the caption decrements within 1 s.
- [ ] After a `skip_staging`, same — decrement only, no balance
      change.
- [ ] The tile's **"Coming in M5"** badge is still visible.
- [ ] Tapping the tile does nothing (aria-disabled stays — the
      review queue UI is still M5). Hover state remains subtle.
- [ ] After skipping/promoting everything, caption flips to
      **"You're all caught up."**.

## 14 – Cleanup task

- [ ] Upload a file, DO NOT import it.
- [ ] `touch -d "25 hours ago" /config/splitsmart/uploads/<uuid>.csv`
      to age the file.
- [ ] In Developer Tools → Services, or via `python -c`, call the
      cleanup function manually (or wait an hour) —
      `/config/splitsmart/uploads/<uuid>.csv` is gone.
- [ ] Repeat but with the file referenced by a live staging row
      (import it, then age the file) → file is **kept** despite
      being >24 h old.

## 15 – Two-device realtime pending count

- [ ] Open the card on desktop and mobile as Chris.
- [ ] From desktop call `import_file` on a fresh statement →
      within 1 s, the mobile Home tile shows the new count.
- [ ] From mobile call `skip_staging` → within 1 s, the desktop
      tile decrements.

## 16 – Per-user scoping

- [ ] As Chris, upload + import 5 rows. Chris's pending count = 5;
      Slav's pending count = 0.
- [ ] As Slav, `splitsmart/list_staging` → returns Slav's empty
      scope. Chris's staging rows are invisible.
- [ ] As Slav, attempt to `promote_staging` with one of Chris's
      `st_...` ids → `ServiceValidationError: permission_denied`.

## 17 – Sensor partition invariant

- [ ] Across any state of the system:
      `pending_count.state == promotable_count + blocked_foreign_currency_count`
      in the sensor attributes. Document any breach as a bug (this
      is the O4 guarantee).

---

## Known limitations deliberately out of M3 scope

- The card's full staging review UI (bulk mode, detail sheet,
  filters) lands in M5. M3's Home tile is a feedback loop, not a
  review queue.
- Foreign-currency rows are promotable once M4 ships FX. Until then,
  a Revolut import will stage EUR/USD rows but each promote call on
  one of them will raise the "arrives in M4" error.
- Column-mapping wizard (UI) lands in M5. Developer Tools power
  users can feed an explicit `mapping` to `splitsmart.import_file`;
  the saved mapping is then reused automatically next month.
- Rules-driven auto-promote / auto-skip lands in M5. Every M3 row
  lands `rule_action: "pending"`.
