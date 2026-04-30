# M5 Manual QA Checklist

End-to-end test scenarios for the M5 milestone: staging review queue, rules
engine, column-mapping wizard, and import pipeline. Run these against a live
HA dev container with the integration loaded.

Prerequisite: two participant accounts (`alice`, `bob`) configured, GBP as
home currency.

---

## 1. Rules engine

### 1.1 rules.yaml hot-reload

- [ ] Create `config/splitsmart/rules.yaml` with one rule:
  ```yaml
  - id: r_test_01
    pattern: netflix
    action: always_ignore
  ```
- [ ] Wait 30 seconds (file watcher interval). Open **Rules** view.
- [ ] Verify the rule appears, action badge reads "Auto-ignore".

### 1.2 Bad YAML does not crash the integration

- [ ] Add a rule with a missing required key, e.g.:
  ```yaml
  - id: r_bad
    pattern: bad
    # action missing
  ```
- [ ] Wait 30 seconds. Rules view should show the valid rule(s) AND a red
  error box listing the parse failure.
- [ ] Fix the YAML, wait 30 seconds, verify the error box disappears.

### 1.3 Reload button

- [ ] Add a new rule to `rules.yaml` without waiting.
- [ ] Press **Reload** in the Rules view.
- [ ] Verify the new rule appears immediately and the status line shows the
  updated "last loaded" timestamp.

### 1.4 Apply rules service

- [ ] Import a CSV containing a row matching the `netflix` pattern from 1.1.
- [ ] Call `splitsmart.apply_rules` from Developer Tools → Services.
- [ ] Verify the matching row is removed from the staging queue (auto-ignored).

---

## 2. Import pipeline

### 2.1 CSV with known preset (auto-import)

- [ ] Download a Monzo CSV export.
- [ ] Open **Import statement** from the home tile or the Import view.
- [ ] Drop the CSV onto the upload zone (or click to browse).
- [ ] Verify the file is accepted, "Importing rows…" spinner appears, and the
  done screen shows counts (imported, auto-split, auto-ignored, pending review).
- [ ] If pending > 0: press **Review pending (N)** and verify the staging view
  opens with the correct number of rows.

### 2.2 CSV without a preset (wizard)

- [ ] Upload a CSV file from an unsupported bank.
- [ ] Verify the card navigates to the column-mapping wizard at `#wizard/<id>`.

### 2.3 Unsupported file type

- [ ] Try uploading a `.pdf` file.
- [ ] Verify an error message appears: "Unsupported file type .pdf. Use CSV,
  OFX, QFX, or XLSX."

### 2.4 Duplicate deduplication

- [ ] Import the same Monzo CSV twice.
- [ ] Verify the second import reports 0 duplicates added (dedup_hash matches).

---

## 3. Column-mapping wizard

### 3.1 Happy path

- [ ] Upload a CSV from an unknown bank.
- [ ] On the **Preview** step: verify the header row and sample rows display
  correctly.
- [ ] On the **Roles** step: assign `date`, `description`, and `amount` columns
  using the role pickers.
- [ ] Verify the **Commit** button is enabled.
- [ ] Press **Commit**. Verify the mapping is saved and the rows land in staging.
- [ ] Upload the same CSV again — verify the wizard is skipped (saved mapping
  detected) and rows import directly.

### 3.2 Missing required column

- [ ] On the **Roles** step: leave the `date` column set to "Ignore".
- [ ] Verify the **Commit** button is disabled.

### 3.3 Debit/credit pair

- [ ] Use a CSV with separate debit and credit columns; assign both roles.
- [ ] Verify the Commit button enables (amount is not required when
  debit+credit is provided).

---

## 4. Staging review queue

### 4.1 Queue populates after import

- [ ] Import a file with pending rows. Navigate to `#staging`.
- [ ] Verify the pending rows appear with description, date, and amount.

### 4.2 Quick Split 50/50

- [ ] Press **Split** on a home-currency row.
- [ ] Verify a toast appears ("Promoted …") and the row disappears from the
  queue.
- [ ] Open the ledger — verify the new expense is there with a 50/50 equal
  split.

### 4.3 Quick Ignore

- [ ] Press **Ignore** on a row.
- [ ] Verify a toast appears ("Ignored …") and the row disappears.

### 4.4 Foreign-currency row

- [ ] Import a CSV row in EUR.
- [ ] Verify the **Split** button is disabled on the queue row.
- [ ] Tap the row to open the detail sheet.
- [ ] Verify the FX banner is shown and a home-amount input is present.
- [ ] Enter a home amount, choose a category and split, press **Promote to expense**.
- [ ] Verify the expense appears in the ledger with the entered home amount.

### 4.5 Filter chips

- [ ] Import rows from two different source presets (e.g. Monzo + Starling).
- [ ] Verify filter chips for each preset appear at the top of the staging view.
- [ ] Tap a chip — verify only that preset's rows remain visible.
- [ ] Tap the chip again — verify the filter clears.

### 4.6 Bulk skip

- [ ] Long-press a row (hold for ~0.7 s) — verify checkbox mode activates.
- [ ] Select two or three rows.
- [ ] Press **Skip selected**.
- [ ] Verify the selected rows disappear and a toast confirms "Skipped N rows".

### 4.7 Bulk cancel

- [ ] Enter bulk mode, select some rows.
- [ ] Press **Cancel** — verify checkboxes disappear without skipping rows.

---

## 5. Staging detail sheet

### 5.1 Open and close

- [ ] Tap a row in the staging queue — verify the URL changes to
  `#staging/<id>` and a detail sheet opens.
- [ ] Press the close (×) button — verify the sheet closes and the URL returns
  to `#staging`.
- [ ] Press Escape — verify the same behaviour.

### 5.2 Promote with single category

- [ ] Open a detail sheet. Set paid-by, choose a category, verify the default
  equal split is pre-selected.
- [ ] Press **Promote to expense** — verify the sheet closes, the row leaves
  the queue, and the expense appears in the ledger.

### 5.3 Promote with multiple categories

- [ ] Press **Split across categories**.
- [ ] Add two category rows that sum to the total.
- [ ] Press **Promote to expense** — verify the expense has two category
  allocations.

### 5.4 Promote button blocked until valid

- [ ] Open a detail sheet. Clear the paid-by field (select no participant) or
  leave home amount at 0 for a foreign row.
- [ ] Verify the **Promote to expense** button is disabled.

### 5.5 Override description and date

- [ ] Expand "Override description, date, or notes".
- [ ] Enter a custom description and a date two days earlier.
- [ ] Promote — verify the expense has the overridden description and date.

### 5.6 Skip from detail sheet

- [ ] Press **Skip** in the detail sheet footer.
- [ ] Verify the sheet closes and the row is removed from the queue.

### 5.7 Create a rule – always ignore

- [ ] On a row with description "NETFLIX.COM", press **Always ignore** in the
  rule section.
- [ ] Verify the rule-snippet sheet opens with a YAML snippet containing a
  pattern that matches "netflix".
- [ ] Press **Copy YAML** — verify the clipboard text matches the snippet.
- [ ] Close the snippet sheet — verify the detail sheet is still open.

### 5.8 Create a rule – always split

- [ ] On a row, press **Always split**.
- [ ] Verify the YAML snippet contains `action: always_split`.

### 5.9 Import metadata collapsed by default

- [ ] Verify the "Import metadata" `<details>` block is collapsed on first
  open.
- [ ] Expand it — verify source_preset, source_ref, and/or dedup_hash appear.

---

## 6. Home view

### 6.1 Pending badge

- [ ] With rows in the staging queue, open the home view.
- [ ] Verify the import tile shows a numeric badge matching the pending count.

### 6.2 Import tile navigation

- [ ] Tap the import tile — verify navigation to `#import`.
- [ ] When the badge is visible and `pendingCount > 0`, verify the caption
  reads "N rows pending review".

### 6.3 Zero-pending state

- [ ] Promote or skip all pending rows.
- [ ] Return to the home view — verify the badge is gone and the caption reads
  "Upload a bank CSV, OFX, or XLSX file".

---

## 7. Regression

- [ ] Adding an expense manually still works (M2 add-expense-view).
- [ ] Editing an expense still works (expense-detail-sheet edit mode).
- [ ] Settling up still works (settle-up-view).
- [ ] Ledger filters still work (M2 ledger-view).
- [ ] Balance strip on home view updates after staging promote (new expense
  registered by the coordinator).
