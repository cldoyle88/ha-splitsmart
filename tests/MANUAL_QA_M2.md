# M2 Manual QA Checklist

Prerequisites: M1 data plane loaded (see `MANUAL_QA_M1.md`), two HA users
configured (Chris `abc123`, Slav `def456`), home currency GBP. Frontend
bundle built (`cd frontend && npm run build` or `npm run build:prod`).
Lovelace in **storage mode** (default) unless the specific test calls
for YAML mode.

Before running: restart HA so the integration picks up
`async_register_static_paths` and the auto-registered Lovelace resource.

---

## 1 – First paint on a fresh dashboard

- [ ] Open any Lovelace dashboard → Edit → Add Card → Manual.
- [ ] Paste `type: custom:splitsmart-card` and save.
- [ ] Card renders without console errors.
- [ ] Browser DevTools → Network → confirm the bundle loads from
      `/splitsmart-static/splitsmart-card.js?v=<integration-version>`.
- [ ] Confirm fonts load from `/splitsmart-static/fonts/DMSans-variable.woff2`
      and `DMMono-{400,500}.woff2` with 200 status.
- [ ] Hero copy on first install: **"No expenses yet"** + caption
      "Add your first expense to get started."

## 2 – Theme coverage

- [ ] HA default **light** theme — card background white, text legible.
- [ ] HA default **Backend** dark theme (Profile → Theme → Backend) —
      card adapts, no hardcoded whites/blacks bleeding through.
- [ ] Apply a **custom** theme that overrides `--primary-color` and
      `--card-background-color`. Splitsmart accent (credit/debit badges)
      respects the overridden accent.

## 3 – Responsive layout / touch targets

- [ ] Desktop full-width (≥ 1280 px) — hero + balance strip + action
      buttons laid out in one column, no horizontal scroll.
- [ ] Lovelace column at ~400 px — still legible, buttons don't wrap
      into the hero.
- [ ] Mobile Safari (iPhone or responsive mode, ~390 px) — hero and
      amounts remain on one line each, buttons wrap if needed.
- [ ] Android Chrome (~360 px width) — tap-test every button, every
      filter chip, every row card. Nothing measures less than 44×44
      CSS pixels (DevTools → hit-test via Accessibility panel).

## 4 – Typography

- [ ] Headlines use **DM Sans** (DevTools → Computed → font-family).
- [ ] Amounts and date captions use **DM Mono** with
      `font-variant-numeric: tabular-nums` so columns of numbers align.
- [ ] `font-display: swap` in action — brief fallback to system sans
      on a cold cache, never FOIT.

## 5 – Two-person add expense (golden path)

- [ ] Tap **Add expense**.
- [ ] Fill: date today, amount £40.00, description "Waitrose", paid by
      Chris, category Groceries, split Equal 50/50.
- [ ] Save disabled until all required fields set; enabled at that point.
- [ ] Tap Save. The view routes to #ledger.
- [ ] **Balance sensor check**: `sensor.splitsmart_balance_chris` now reads
      `+20.00` and `sensor.splitsmart_balance_slav` reads `-20.00`.
- [ ] **Second browser tab** on a different device (or just a private
      window on the same machine) showing the same card updates inside
      one second, without a refresh.

## 6 – Multi-category Tesco shop (SPEC §9.3)

- [ ] Tap Add expense.
- [ ] Enter amount £82.40, description "Tesco Metro", paid by Chris.
- [ ] Toggle **Split across categories**.
- [ ] Add three rows: Groceries £55.20, Household £18.70, Alcohol £8.50.
- [ ] Remainder indicator turns green (£82.40 balanced) only when the
      sum matches.
- [ ] Toggle **Different split per category**.
- [ ] For Alcohol row, switch to **Exact**; set Chris £8.50, Slav £0.
- [ ] Leave Groceries and Household on Equal 50/50.
- [ ] Save (button is enabled only once every split validates).
- [ ] Ledger row shows `£82.40`.
- [ ] Tap the row → Detail sheet shows the three allocations with
      correct breakdown and Totals per person: Chris £45.45, Slav £36.95.
- [ ] Balance sensor: Slav now reads `-36.95` net of this expense only.

## 7 – Ledger filter

- [ ] Open **Ledger**.
- [ ] Current month is selected by default.
- [ ] Tap **All** month chip — previous months' expenses appear.
- [ ] Select a category chip (e.g. Groceries) — only expenses with that
      allocation show. Settlements hide when a category filter is active.
- [ ] Clear the category — settlements re-appear on their dates.
- [ ] Select a past month with no data → "No expenses match" empty state
      with **Clear filters** button; tap it to return to defaults.
- [ ] Inspect the URL hash — filters persist as query params
      (`#ledger?month=2026-04&category=Groceries`). Reload the tab;
      filters are restored.

## 8 – Detail sheet edit

- [ ] From Ledger, tap the Waitrose row.
- [ ] Hero shows amount, relative date ("Today"), breakdown, totals.
- [ ] Tap **Edit**.
- [ ] Change description to "Waitrose Islington".
- [ ] Save.
- [ ] Ledger row updates to the new description.
- [ ] `/config/splitsmart/shared/tombstones.jsonl` has one fresh
      `operation: edit` record with the previous snapshot.
- [ ] The new expense id is a fresh `ex_*` (sheet closes on Save so you
      can verify via the new row's DOM attribute or the JSONL).

## 9 – Detail sheet delete

- [ ] Open a non-critical expense from the Ledger.
- [ ] Tap **Delete** → confirmation panel appears.
- [ ] Tap **Yes, delete**.
- [ ] Row disappears from the Ledger instantly.
- [ ] Balance sensors recalculate to reflect the deletion.
- [ ] `tombstones.jsonl` has one `operation: delete` record.
- [ ] Tap Cancel on the confirmation — sheet returns to view mode
      without deleting.

## 10 – Settle up

- [ ] From Home, tap **Settle up**.
- [ ] From = Chris, To = Slav (default for the current user).
- [ ] Suggested amount pre-fills with the outstanding pairwise debt.
- [ ] Tap **⇄** — From and To swap, suggested amount updates to the
      now-opposite pairwise amount (if any).
- [ ] Override the amount manually; Save enables.
- [ ] Save — the view routes back to #home. Hero now reads "You're all
      square" if the settlement zeros the debt.
- [ ] The settlement appears inline in the Ledger for its date.
- [ ] Balance sensors reflect the settlement.

## 11 – Mobile companion

- [ ] Open the same dashboard in HA Companion on iOS.
- [ ] Card renders the same views; fonts look right (self-hosted so no
      cellular round-trip to Google).
- [ ] Repeat step 5 (add a tiny expense) from the phone — desktop tab
      updates within one second.
- [ ] Repeat on Android Companion.

## 12 – Two-device realtime

- [ ] Tab A on desktop, Tab B on phone (or two desktop tabs).
- [ ] Add an expense in B.
- [ ] A updates inside one second, no manual refresh.
- [ ] Edit the new expense in A → B updates.
- [ ] Delete in B → A updates.

## 13 – YAML-mode Lovelace fallback

- [ ] Temporarily switch Lovelace to YAML mode (Configuration →
      Dashboards → Take control).
- [ ] Restart HA.
- [ ] Check `home-assistant.log` for the INFO line from
      `frontend_registration.py`: it should contain the exact snippet
      with `url: /splitsmart-static/splitsmart-card.js?v=<ver>` and
      `type: module`.
- [ ] Paste that snippet into `ui-lovelace.yaml` under `resources:`.
- [ ] Add the card to a YAML dashboard and reload — card renders
      correctly.
- [ ] Switch back to storage mode when done.

## 14 – Placeholder tiles + coming-in-M5 badge

- [ ] Home view shows a **"Pending review"** tile with a "Coming in M5"
      badge at the bottom.
- [ ] The tile is not tappable and has `aria-disabled="true"`.
- [ ] Styling is visually distinct from active tiles (dashed border,
      muted colour) so users don't mistake it for broken interaction.

## 15 – Card options: `view`

- [ ] Edit the card YAML to `type: custom:splitsmart-card` and add
      `view: ledger` on a second line.
- [ ] Save and reload — card starts on the Ledger view instead of Home.
- [ ] Try `view: invalid` — Lovelace shows a config error ("Unknown
      view 'invalid'. Supported: home, ledger, add, settle.").
- [ ] Restore to `view: home` (or remove the field) for the rest of QA.

## 16 – Former participants

- [ ] Temporarily remove Slav from the Splitsmart integration
      (Integrations → Splitsmart → Configure → Reconfigure → unselect).
- [ ] Reload the card.
- [ ] Historical rows involving Slav still render.
- [ ] Slav's avatar appears at 60% opacity; labels read
      "Slav (former participant)".
- [ ] Add expense form's "Paid by" dropdown excludes Slav.
- [ ] Settle up form's From/To dropdowns exclude Slav.
- [ ] Re-add Slav when done.

## 17 – Deliberately NOT tested

These are out of scope for M2 per M2_PLAN.md §7 and deferred:

- Visual regression (pixel diffs) — M7 polish.
- Cross-browser IE / legacy Edge / legacy Safari.
- Automated WCAG 2.1 AA screen-reader audit.
- Load testing with 5000+ expenses (requires the M3 import pipeline).

Note anything else observed during QA that isn't in the list above in a
"Notes" section below, and open issues / PRs for anything surprising.
