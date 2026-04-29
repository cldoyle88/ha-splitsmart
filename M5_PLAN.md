# M5 plan — staging review and rules

Scope is the SPEC §19 M5 milestone: the staging review UI on the card, the column-mapping wizard, and the rules engine. M3 shipped the backend contract (`splitsmart/list_staging` + subscribe, `list_presets`, `save_mapping`, `inspect_upload`, plus `import_file` / `promote_staging` / `skip_staging`) and M4 unblocked foreign-currency promote, so M5 is mostly a frontend milestone with one new pure-function backend module (`rules.py`), a small fan of new websocket commands, and one new service (`splitsmart.apply_rules`).

End-to-end demo at the end of M5: upload a Monzo CSV via the existing endpoint; rows that match `rules.yaml` auto-promote or auto-ignore at import time; remaining rows land in a per-row review queue on the card with one-tap promote / skip / open-detail; tap an unrecognised CSV's home tile banner, walk the column-mapping wizard, save mapping, import; create a rule from a pending row via "Always split rows like this" → preview → copy YAML → paste into `rules.yaml` → file watcher reloads → `splitsmart.apply_rules` re-runs rules over existing pending rows. Mobile-driveable; one-thumb-friendly.

---

## 1. Scope fence

### In M5

The user's lean, accepted with the push-backs in §1.3.

**Frontend — Staging review queue (`#staging` route):**

1. **Per-row review queue** under `#staging`. Routed from the Home tile's tap target (replacing the M3 stub). Lists pending rows for the current user from `splitsmart/list_staging/subscribe`. Filters: source, currency. Empty state with two CTAs (`Import file`, `Add expense`) when no rows pending.
2. **Per-row actions**: `Split 50/50` (promotes with single-category default 50/50 equal split using `category_hint` if present, else "Other"), `Ignore` (skips), `⋯` opens detail sheet. Body tap also opens detail sheet. 5-second undo toast after each action.
3. **Detail sheet for staging rows** (`#staging/<staging_id>`). Reuses the M2 multi-category allocator + per-allocation split picker exactly. Shows raw import metadata (source_ref, source_preset, dedup_hash) collapsed; promoting from here calls `splitsmart.promote_staging` with the full allocations; skipping calls `splitsmart.skip_staging`. Owns FX hint copy for foreign-currency rows ("FX will be resolved at promote time").
4. **Bulk mode (constrained — see push-back §1.3.B)**: long-press any row → checkbox mode. Top action bar: `Skip selected` + `Cancel`. No bulk promote, no bulk-edit-category. Skip is safe (idempotent, reversible via re-import).

**Frontend — Column-mapping wizard:**

5. **Mapping wizard** under `#import/wizard/<upload_id>`. Triggered when the upload endpoint's `inspection.preset` is null AND `inspection.saved_mapping` is null (the existing M3 endpoint already returns this enough payload). Three steps: preview (header row + 5 sample rows from `inspection`), role assignment (per-column `date | description | amount | debit | credit | currency | ignore`, plus currency default + amount sign), commit (calls `splitsmart/save_mapping` then `splitsmart.import_file` with the explicit mapping).
6. **Home banner / Import view entry-point.** When the user uploads a file (M5 ships the upload-from-card path too — see §4) and the inspection lands without a preset/saved-mapping, the card routes straight to the wizard instead of importing. Once the mapping is saved, next month's upload skips the wizard automatically (M3 backend already does this).

**Backend — Rules engine:**

7. **`rules.py`** — new pure-function module. `load_rules(yaml_text)` → `list[Rule]`, `evaluate(staging_row, rules)` → `RuleMatch | None`. Voluptuous schema validation per rule; invalid entries logged at ERROR and skipped (mirrors M4's recurring loader strategy).
8. **`/config/splitsmart/rules.yaml`** — user-authored, hand-editable. Schema per SPEC §12.5: `id`, `match` (regex), `amount` (optional `> N` / `< N` / `N..M`), `currency_match` (optional), `action` (`always_split` / `always_ignore` / `review_each_time`), `category` (string, required for `always_split` and `review_each_time`), `split` (object with `method` + `preset` reference, required for `always_split`). Loaded at integration setup; reloaded on options-flow changes; reloaded automatically when the file changes on disk (see §5.5).
9. **Rules at import time.** `splitsmart.import_file` (existing M3 handler) gains rule evaluation between row build and dedup. For each parsed row: evaluate against rules in priority order, first match wins. `always_split` → write the staging row with `rule_id` + `rule_action="always_split"`, then immediately invoke the same primitives `promote_staging` uses (build expense, append expense, append promote-tombstone with `replacement_id`). `always_ignore` → write the staging row with `rule_id` + `rule_action="always_ignore"`, then append a discard tombstone. `review_each_time` → write the staging row with `rule_id` + `rule_action="review_each_time"`, set `category_hint` from the rule. No match → `rule_action="pending"`, `rule_id=null`. The staging-row write is preserved in all cases for audit (see decision §8.O3).
10. **`splitsmart.apply_rules` service** — per SPEC §10. Re-runs rule evaluation against existing rows whose `rule_action == "pending"`. Useful after editing `rules.yaml`. Returns `{auto_promoted: N, auto_ignored: M, still_pending: K}`. Same code path as import-time evaluation.

**Frontend — Rules surface:**

11. **`#rules` view** (read-only). Lists rules from `splitsmart/list_rules`. Each row: `id`, `description`, regex literal, action badge, optional amount/currency conditions, optional category + split preset. Empty state pointing the user at `/config/splitsmart/rules.yaml` with a copy-paste snippet template. Reload-from-disk button (calls `splitsmart/reload_rules`) with a "last loaded at … – N rules" status line.
12. **"Create rule from this row"** button on the staging detail sheet. Calls `splitsmart/draft_rule_from_row` with the staging_id and the user's chosen action (`always_split` / `always_ignore`). Server returns a fully-formed YAML snippet (id auto-assigned, regex from longest alphabetic run in description, category + split preset). Card shows the snippet in a copy-to-clipboard sheet plus instructions: "Paste this under `rules:` in `/config/splitsmart/rules.yaml`. The integration reloads automatically." No live YAML editor in M5 (per SPEC §12.5 / decision matches recurring.yaml pattern).

**New websocket commands (all read-only, all carry `version: 1` envelope):**

13. `splitsmart/list_rules` — returns `{rules: [<rule>, ...], loaded_at: ISO, source_path: str}`. One-shot.
14. `splitsmart/list_rules/subscribe` — long-lived. Init payload + delta on file-watcher reload. Card's `#rules` view subscribes; doesn't poll.
15. `splitsmart/draft_rule_from_row` — input `{staging_id, action: "always_split" | "always_ignore", default_split_preset?: str}`. Returns `{yaml_snippet: str, draft: <Rule>}`. Caller is the staging row's owner (privacy check matches `list_staging`).
16. `splitsmart/reload_rules` — input `{}`. Forces re-read of `rules.yaml`. Returns `{loaded_at, rules_count, errors: [...]}`.

(Existing M3 commands `list_staging` + subscribe carry the review queue. We do **not** add a `list_pending_for_user` command — see push-back §1.3.D.)

**Backend ancillaries:**

17. **`SplitsmartData` extension**: `rules: list[Rule] = []`, `rules_loaded_at: datetime | None = None`. Coordinator owns the loaded rules; `__init__.py` registers a file watcher on `rules.yaml` that calls `coordinator.async_reload_rules()`. Tests don't depend on the watcher — they call the reload helper directly.
18. **CHANGELOG `Unreleased` entry** documenting all of the above.

### Deferred (with rationale)

| Feature | Defer to | Why |
|---|---|---|
| Live `rules.yaml` editor in card | v2 / M7 polish | YAML-first matches recurring.yaml from M4; the file watcher + draft-snippet flow gives 80% of the ergonomics with 10% of the surface area. SPEC §12.5 explicitly endorses YAML-first. |
| Bulk-promote-with-same-category | v2 | Promote requires per-row valid allocations; bulk-promoting needs the user to fix `category` AND validate `home_amount` AND pick a split for every selected row. Solving this well is its own feature; doing it badly creates broken expenses at scale. M5 ships bulk skip only. |
| Bulk-edit-category-and-paid_by-then-promote | v2 | Same reason — needs detail-sheet-level validation per row. |
| "Auto-split (N)" / "Auto-ignored (N)" tabs (SPEC §14) | v2 / M7 | Reverse-action of a tombstoned auto-row is non-trivial (re-write a row that was tombstoned); the data is in `tombstones.jsonl` for audit. M5 lists pending only. |
| Rule preview ("how many staging rows would this match?") | v2 / M7 | Useful but cheap to add later; ships when the editor ships. |
| Receipt-photo workflow integration | M6 | Telegram OCR is the M6 gate. |
| Visual polish across all views | M7 | Empty-state illustrations, animation, full theme audit live in M7. |
| `splitsmart.delete_expense` undo from auto-promote tombstone | v2 | Edge case. User can always re-import. |
| Rule from selected rows (multi-row regex inference) | v2 | Hard to get right; no clear win over per-row drafting in M5. |

### Push-back on the user's lean (explicit)

**A. "Edit-then-Promote" as a separate verb — drop.** The user's per-row action list includes `Promote`, `Skip`, `Edit-then-Promote`. The third is just "open detail sheet, tweak, tap Save". Adding a third button creates a hierarchy where the user's eye has to compare three options on a phone-width row card. M2 row-card primitive comfortably fits two action buttons + a kebab; M5 keeps that pattern: `Split 50/50`, `Ignore`, `⋯ → Detail sheet` (which has Save, equivalent to edit-then-promote).

**B. Bulk actions narrowed to skip-only.** The user proposed `Skip-all-from-source` and `Promote-all-with-same-category`. Bulk-promote is risky: each promote needs a valid set of category allocations summing to the row's amount, plus a valid split per allocation. A naive "single-category = whole amount, default 50/50 equal" works for most rows but breaks silently when the user actually wanted multi-category. Compounding 50 silent breakages on a Monzo statement is worse than 50 manual taps. M5 ships **bulk skip only** (safe, idempotent, undoable by re-import). Bulk-promote is a v2 problem to solve properly with row-level previews.

**C. Foreign-currency `home_amount` rescaling on the queue — drop the live rate.** The user proposed showing `home_amount` rescaled against today's rate from `fx_rates.jsonl`, with `—` on cache miss. Two issues: (1) the card has no synchronous filesystem access and must call a websocket command for every cached rate, which is a micro-fan-out for a number that's about to be wrong anyway (the actual promote-time rate will differ); (2) the displayed estimate competes for screen real-estate with the original-currency amount, which is the source of truth. **Decision: show `amount` and `currency` only on the queue. The detail sheet shows a small "FX will be looked up when you promote (estimate today: …)" line where we can afford the round-trip and the caveat.** Cleaner queue, fewer round-trips, no misleading numbers.

**D. `splitsmart/list_pending_for_user` — not needed.** M3's `list_staging` + subscribe already returns the caller's full staging list with rule_action. The review queue filters client-side to `rule_action == "pending"`. Adding a server-side filter is one extra command surface for a one-line array filter; punt.

**E. `splitsmart.apply_rules` is in-scope.** The user's bullet list elides this service — it's in SPEC §10 and M4_PLAN deferred it explicitly to M5. Without it, edits to `rules.yaml` only affect future imports; existing pending rows stay pending until the user clicks through them. That's a confusing UX. Ship the service; it's a thin wrapper around the same evaluator.

**F. Three rule actions, not two.** SPEC §12.5 specifies `always_split`, `always_ignore`, AND `review_each_time` (sets a category hint without committing to an action). The user's lean mentions only the first two. Skipping `review_each_time` would force a second-pass schema migration when M5+1 needs the hint. Ship all three; the third is functionally a no-op write at import time apart from setting `category_hint` and recording the rule_id, so it's free to support.

### What M5 must NOT ship

- Any change to the staging schema beyond using existing `rule_id` / `rule_action` fields. The fields exist since M3.
- Any change to the FX cascade. Promote-time FX is M4 territory, untouched.
- Any new HTTP endpoints. All new card commands go via websocket.
- Any modification to CHANGELOG entries outside `Unreleased`.
- Any change to the existing M3 `splitsmart/list_staging` shape. The card consumes it as-is.
- Any change to expense/settlement sensors. Pending-count sensor stays as M3 shipped it.
- Any rules editor / save-rules-from-card path. Read-only + draft-snippet only.
- Any rules-driven change to recurring or settlements. Rules apply only to staging at import (and via `apply_rules` to existing pending).
- Any breaking change to the websocket envelope version.

---

## 2. Rules engine (backend)

### Schema (`rules.yaml`)

```yaml
rules:
  - id: r_netflix
    description: Streaming subscriptions       # human-readable, optional
    match: /netflix|spotify|disney|now tv|amazon prime/i
    currency_match: GBP                        # optional ISO-4217; null/missing = any
    amount: null                               # null | "> 10" | "< 50" | "10..50"
    action: always_split
    category: Subscriptions
    split:
      method: equal
      preset: 50_50                            # references entry.options.named_splits
    priority: 100                              # optional; default = source order

  - id: r_tfl
    match: /tfl|oyster|transport for london/i
    action: always_ignore

  - id: r_deliveroo_review
    match: /deliveroo|just eat|uber eats/i
    action: review_each_time
    category: Eating out
```

### Schema invariants (validated at load)

- `id` is `[a-z0-9_]+`, unique within file. (Same convention as recurring.yaml.) The `r_` prefix is a soft convention, not enforced — `id` is treated as a free key, separate from the `r_<ulid>` prefix used for runtime-generated rule IDs (none in M5).
- `match` parses as a delimited regex literal: `/PATTERN/FLAGS`. Only `i` flag supported in M5. Compiled with `re.compile`; bad regex → log ERROR, skip rule (don't fail the whole file).
- `amount` parses as one of: `"> N"`, `"< N"`, `"N..M"` (inclusive both ends), `null`, missing. Anything else → ERROR + skip.
- `action` ∈ `{always_split, always_ignore, review_each_time}`.
- `always_split` requires `category` AND `split`. `split.method` ∈ split methods; `split.preset` must reference an entry in `entry.options.named_splits` OR be inline `shares: [{user_id, value}, ...]`.
- `review_each_time` requires `category` (sets `category_hint`); `split` ignored if present.
- `always_ignore` ignores `category` and `split` if present.
- `priority` integer; lower wins. Missing → priority = source order × 1000 (so explicit priorities override file order, matching the SPEC's "evaluated in order, first match wins" with an explicit override hatch).

### Staging tombstone operations

Staging tombstones (`target_type="staging"` in `shared/tombstones.jsonl`) carry one of three `operation` values, with the addition of `edit` in M5:

| Operation | Written by | Meaning |
|---|---|---|
| `promote` | `splitsmart.promote_staging`; import-time `always_split` rule match; `apply_rules` `always_split` match | Staging row is replaced by a shared expense. Tombstone carries `replacement_id` pointing at the new expense id. |
| `discard` | `splitsmart.skip_staging`; import-time `always_ignore` rule match; `apply_rules` `always_ignore` match | Staging row is skipped. No replacement. |
| `edit` | `apply_rules` `review_each_time` match; any future flow that refreshes rule fields without an action | Staging row's `rule_id` / `rule_action` / `category_hint` are refreshed. Tombstone carries `previous_snapshot`; a new staging row with a new id and the updated fields is appended in the same call. |

`materialise_staging` drops any row whose id appears as any tombstone's `target_id`, so all three operations round-trip through the same materialisation pass. `dedup` only counts `discard` tombstones for the multiset accounting (per M3 decision O1) — `edit` tombstones leave the row materialised under its new id, and `promote` tombstones are covered by the resulting shared expense.

SPEC §6.2 is amended in the first commit of M5 to document the `promote` and `edit` values explicitly. The SPEC's existing enum was `edit|delete|discard`; `promote` was added in M3 const.py without a SPEC update at the time, and `edit` is the new staging-tombstone operation introduced in M5.

### Public API (`rules.py`, pure)

```python
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal


@dataclass(frozen=True)
class Rule:
    id: str
    description: str | None
    pattern: re.Pattern[str]
    currency_match: str | None
    amount_min: Decimal | None
    amount_max: Decimal | None
    action: Literal["always_split", "always_ignore", "review_each_time"]
    category: str | None
    split: dict[str, Any] | None
    priority: int


@dataclass(frozen=True)
class RuleMatch:
    rule: Rule
    # No additional fields in M5 — placeholder for v2 enrichment (e.g. capture groups).


class RuleParseError(ValueError):
    """Raised by load_rules per-entry; logged at ERROR by the loader, then skipped."""


def load_rules(
    yaml_text: str,
    *,
    named_splits: dict[str, dict[str, Any]],
) -> tuple[list[Rule], list[str]]:
    """Parse and validate. Returns (valid_rules, errors). Sorted by priority."""


def evaluate(
    row: dict[str, Any],
    rules: list[Rule],
) -> RuleMatch | None:
    """First-match-wins. row is a parsed RawRow + currency + amount + description.
    No IO, no logging. Pure."""


def build_match_payload(
    match: RuleMatch,
    *,
    home_currency: str,
    expense_amount: Decimal,
) -> dict[str, Any] | None:
    """For always_split: returns the categories[] block ready for build_expense_record.
    Resolves the named-split preset against the entry's named_splits map.
    For always_ignore / review_each_time: returns None."""
```

`build_match_payload` is the bridge between rule and expense — single place that knows how a rule's `split.preset` maps onto the M1 `categories: [{name, home_amount, split}]` shape. Single-category allocation per SPEC §9.5.

### Where rules attach into `splitsmart.import_file`

Insert between the parse step and the dedup step at [services.py:851](custom_components/splitsmart/services.py#L851). The new flow:

1. Parse file (existing).
2. **Evaluate rules per row** — annotate each `RawRow` with `_rule_match: RuleMatch | None`. Pure call into `rules.evaluate`.
3. Compute `dedup_hash` per row (existing).
4. Dedup partition (existing). Dedup runs **before** action application — duplicates are skipped regardless of rule action, otherwise re-importing a statement would auto-promote the duplicate again.
5. For each `to_import` row:
   - Build the staging record with `rule_id` and `rule_action` set per the matched rule (or `null` / `"pending"` if no match).
   - Append the staging record (always — preserves audit).
   - If `rule_action == "always_split"`:
     - Resolve FX via the existing M4 cascade (`_resolve_fx`).
     - Build expense record via `build_expense_record` with the rule's categories block (rescaled via existing `rescale_categories`).
     - Append expense.
     - Append promote-tombstone with `replacement_id = expense.id`, `previous_snapshot = staging row`.
     - On FX failure (FxUnavailableError, etc.): log WARNING, leave the staging row with `rule_action="always_split"` and `rule_id` set. The user retries via `splitsmart.apply_rules` once connectivity returns. Mirrors M4's recurring-task FX-failure pattern.
   - If `rule_action == "always_ignore"`:
     - Append discard tombstone with `previous_snapshot = staging row`.
   - If `rule_action == "review_each_time"`:
     - Set `category_hint` from the rule's `category` field on the staging record (already written above; this means the record gets the hint at write time, not retroactively).
   - Counters tracked: `auto_promoted`, `auto_ignored`, `auto_review`, `still_pending`.
6. Single `coordinator.async_note_write(staging_user_id=caller)` at the end (unchanged).
7. Service response gains four counters: `{..., auto_promoted: N, auto_ignored: M, auto_review: K, still_pending: J}`.

Foreign-currency rule-matched `always_split` rows: same as the FX failure case above. Per CLAUDE.md, no special handling — just leave them in pending-with-rule-set state and let `apply_rules` (or a manual promote) finish the job once FX is reachable.

### `splitsmart.apply_rules` service handler

```yaml
apply_rules:
  name: Apply rules
  description: Re-evaluate rules against existing pending staging rows for the caller.
  fields:
    user_id:
      required: false
      description: |
        Defaults to the calling user. Admins can pass another participant's user_id;
        non-admin callers attempting this get permission_denied (matches list_staging).
```

Handler steps:

1. Resolve caller, participants, coordinator (existing pattern).
2. Validate `user_id` privacy (caller must equal target unless admin per HA's `user.is_admin`).
3. Load rules from coordinator (in-memory; reflects last file reload).
4. For each staging row in `coordinator.data.staging_by_user[user_id]` whose `rule_action == "pending"`:
   - Evaluate. No match → continue.
   - Match → write a tombstone-then-replacement pair: edit the staging row to set `rule_id` and `rule_action`, then apply the same action as import-time (promote / discard / hint).
   - For the edit-the-staging-row step: rather than mutate (forbidden by append-only), append a tombstone with `target_type="staging"`, `operation="edit"`, then a new staging row with the rule fields populated. M1's `materialise_staging` already drops tombstoned rows and the new row appears, so this round-trips correctly.
   - **Decision needed (§8.O5):** is the edit-then-replace cost worth it for `review_each_time` (where the only change is `category_hint`)? See open question.
5. `coordinator.async_note_write(staging_user_id=user_id)` once.
6. Return `{auto_promoted, auto_ignored, auto_review, still_pending}`.

### Pure-function boundary

`rules.py` has no HA imports, no IO, no logging at INFO+. All inputs are plain dicts / dataclasses. All outputs are dataclasses or plain dicts. The service handler is the only place that wires rules into the storage / coordinator path. This means:

- Rule evaluation is unit-testable with synthetic rows + synthetic rules: `pytest tests/test_rules.py`.
- Match-payload construction is unit-testable independently.
- Schema validation is unit-testable with raw YAML strings.

The only non-pure piece is the file-watcher reload helper, which lives on the coordinator (`async_reload_rules`) and is exercised by integration tests, not unit tests.

---

## 3. New websocket commands

All commands carry `version: 1`. Privacy: every command checks `connection.user.id` against `entry.data[CONF_PARTICIPANTS]`. Per-user scoping for `draft_rule_from_row` matches `list_staging` (caller must own the row).

### `splitsmart/list_rules` — one-shot

```
Request:  {type: "splitsmart/list_rules"}
Response: {
  version: 1,
  rules: [
    {
      id: "r_netflix",
      description: "Streaming subscriptions",
      match: "/netflix|spotify|...|amazon prime/i",
      currency_match: null,
      amount_min: null,
      amount_max: null,
      action: "always_split",
      category: "Subscriptions",
      split: {method: "equal", preset: "50_50"},
      priority: 100
    },
    ...
  ],
  loaded_at: "2026-04-29T14:00:00+01:00",
  source_path: "/config/splitsmart/rules.yaml",
  errors: []   // if the loader skipped any entries
}
```

Handler reads from `coordinator.rules` (in-memory). `errors` carries the same skipped-entry messages the ERROR log captured.

### `splitsmart/list_rules/subscribe` — long-lived

Init payload identical to one-shot. Delta payload `{kind: "reload", rules: [...], loaded_at, errors}` fired whenever `coordinator.async_reload_rules()` runs (file watcher, options-flow, manual reload). No incremental diff — rules.yaml is small enough to send wholesale on every reload.

### `splitsmart/draft_rule_from_row` — one-shot

```
Request: {
  type: "splitsmart/draft_rule_from_row",
  staging_id: "st_01J9X...",
  action: "always_split" | "always_ignore",
  default_split_preset: "50_50"   // optional; ignored for always_ignore
}
Response: {
  version: 1,
  yaml_snippet: "  - id: r_drafted_<short>\n    match: /WAITROSE/i\n    action: always_split\n    category: Groceries\n    split: {method: equal, preset: 50_50}\n",
  draft: { /* same shape as a list_rules entry */ }
}
```

Handler:

1. Privacy: `staging_id` must belong to the caller's staging file.
2. Look up the staging row in coordinator.
3. Generate id: `r_` + 8 lowercase chars from a slugified description. Collisions resolved by appending `_2`, `_3`.
4. Generate regex: longest run of alphabetic chars (length ≥ 3) from the description, lower-cased and bounded as `/WORD/i`. Fallback: the full description with regex special chars escaped.
5. Use the row's `category_hint` (or `Other`) for `category`. For `always_ignore`, omit `category` and `split`.
6. Render YAML via a single `yaml.safe_dump([draft], sort_keys=False)` then strip the leading `- ` and indent two spaces — produces a paste-ready snippet that fits under an existing `rules:` key.

### `splitsmart/reload_rules` — one-shot

```
Request:  {type: "splitsmart/reload_rules"}
Response: {version: 1, loaded_at, rules_count, errors: [...]}
```

Forces `coordinator.async_reload_rules()`. Useful for the `#rules` view's "Reload from disk" button when the file watcher missed a change (rare but possible on some Pi filesystems).

### Why no `splitsmart/save_rules`

The user's lean explicitly rules out a live editor. We follow that. Saving rules from the card would require a write path that races with the file watcher, and we'd need to handle malformed user input with structured errors — the cost-benefit is poor for a v1. Drafted snippets get pasted; users on mobile copy via a clipboard primitive. Document the limitation in `#rules` empty state.

---

## 4. Card view structure

### Routes added in M5

| Hash | View | Source |
|---|---|---|
| `#staging` | `<ss-staging-view>` | M5 — review queue |
| `#staging/<staging_id>` | `<ss-staging-view>` + `<ss-staging-detail-sheet>` overlay | M5 |
| `#rules` | `<ss-rules-view>` | M5 — read-only list |
| `#import` | `<ss-import-view>` | M5 — file picker + recent uploads |
| `#import/wizard/<upload_id>` | `<ss-import-wizard-view>` | M5 — column-mapping wizard |

### Router changes

`frontend/src/router.ts` is currently a closed enum; adds `'staging' | 'rules' | 'import'` to `RouteView`, plus parsing for the `import/wizard/<upload_id>` two-segment path. Single-line additions; M2's parse + serialise functions handle the rest. Extend `requiresParam` set to include `'staging'` (param optional — present means "open detail sheet for this id"; absent means queue) — same pattern as `expense` / `settlement`.

### Component tree (new files)

```
frontend/src/views/
├── staging-view.ts                # <ss-staging-view> — queue + filters + bulk-skip
├── staging-detail-sheet.ts        # <ss-staging-detail-sheet> — full row metadata + promote/skip via the M2 allocator
├── rules-view.ts                  # <ss-rules-view> — read-only list + reload button
├── import-view.ts                 # <ss-import-view> — file picker + upload + dispatch (preset → import / wizard / saved-mapping → import)
└── import-wizard-view.ts          # <ss-import-wizard-view> — three-step wizard
frontend/src/components/
├── filter-chip.ts                 # <ss-filter-chip> — extracted from ledger-view per M2 §5 TODO
├── undo-toast.ts                  # <ss-undo-toast> — single instance owned by root, reusable
├── column-role-picker.ts          # <ss-column-role-picker> — used per-column in the wizard
└── rule-snippet-sheet.ts          # <ss-rule-snippet-sheet> — copy-to-clipboard panel for drafted rules
```

### Component reuse audit (≥ 2 consumers)

| Primitive | M5 consumers | Verdict |
|---|---|---|
| `<ss-row-card>` | Ledger (existing), Staging queue (M5) — variant prop `staging` | ✓ reuse |
| `<ss-modal>` | Detail sheets (existing), Import wizard step container, Rule snippet sheet | ✓ reuse |
| `<ss-amount-input>` | Detail sheet edit mode (existing path), wizard "currency default" picker | ✓ reuse |
| `<ss-category-picker>` | Add (existing), Staging detail (existing on promote-form), Rules-view rendering | ✓ reuse |
| `<ss-allocation-editor>` | Staging detail sheet (promote with multi-cat) | ✓ reuse |
| `<ss-split-picker>` | Staging detail sheet, Rule preview | ✓ reuse |
| `<ss-empty-state>` | Staging empty, Rules empty | ✓ reuse |
| `<ss-filter-chip>` (new — extracted) | Ledger filters (refactor — see "TODO(M5)" comment in M2 §5), Staging filters | ✓ extract |
| `<ss-undo-toast>` (new) | Staging skip, Staging promote, Bulk skip | ✓ |
| `<ss-column-role-picker>` (new) | Wizard only (one consumer, but it's complex enough to deserve a primitive) | Acceptable — its single-view use is a deliberate concession; folding it into the wizard would inflate `import-wizard-view.ts` past 400 lines |
| `<ss-rule-snippet-sheet>` (new) | Detail sheet "Create rule from this row" only | Same — kept primitive for testability |

### State ownership

Root `<splitsmart-card>` gains:

- `@state() private _stagingRows: StagingRow[]` — hydrated via `splitsmart/list_staging/subscribe`. Replaces the M3 path of "no card knowledge of staging".
- `@state() private _rules: Rule[]` — hydrated via `splitsmart/list_rules/subscribe`.

Root subscribes to **both** subscriptions on mount, plus the existing `list_expenses/subscribe`. Three subscriptions × one HA websocket connection = trivial; HA's frontend uses dozens.

Filters on the staging view are local view state (`@state() _sourceFilter`, `@state() _currencyFilter`). Bulk selection is local view state (`@state() _selected: Set<string>`). Detail sheet open/close uses the existing `_openDetailId` pattern, extended with a discriminator (`_openDetail: {kind: 'expense' | 'settlement' | 'staging', id} | null`).

### Staging row card spec

```
┌──────────────────────────────────────────────┐
│ ▢  WAITROSE ISLINGTON N1            £47.83  │
│    15 Apr · Monzo · Groceries (hint)         │
│    [ Split 50/50 ]  [ Ignore ]  [ ⋯ ]        │
└──────────────────────────────────────────────┘
```

- Left checkbox visible only in bulk mode.
- Description tap-target = whole row except the three buttons.
- Foreign-currency rows: amount renders as `€47.83 EUR` (currency on the right), no rescale; `⋯` opens detail sheet which shows the FX hint.
- "Split 50/50" button only enabled when `currency == home_currency` AND a default category exists. Otherwise disabled with tooltip "Open detail to choose category". Foreign rows: button disabled with tooltip "Promote via detail sheet (FX lookup happens then)".
- "Ignore" always enabled.

### Detail sheet for staging

Reuses the M2 allocator and split picker components verbatim. Difference vs Add expense:

- Header: `Review pending row` (vs `Add expense`).
- Preselects `paid_by = current user`, `categories = [{name: hint, home_amount: row.amount, split: <default 50/50 equal>}]`, `description = row.description`, `date = row.date`, `notes = row.notes`. Currency locked to row's currency.
- Save button label: `Promote`. Cancel returns to queue.
- Below the form: collapsible "Raw import data" panel showing `source`, `source_ref`, `source_preset`, `source_ref_upload_id`, `dedup_hash`, `uploaded_at`. Read-only.
- Below that: two buttons — `Ignore this row` (calls skip), `Create rule from this row` (opens snippet sheet).

Foreign-currency rows additionally show a row above Save:

```
FX will be looked up when you promote.
Today's estimate: €47.83 ≈ £40.95 (rate 0.857).
```

The estimate fetches via a one-shot `splitsmart/list_expenses` query? No — better, a thin new helper in the existing FX cache surface: extend the `splitsmart/list_rules` pattern with a `splitsmart/quick_fx` command? **Decision in §8 open questions (O7).** Default leaning: don't ship a quick_fx command in M5; show the row card with the foreign currency, and on the detail sheet show the cached rate if one exists by reading the existing `splitsmart/list_expenses` response (it has historical rates). Simpler still: skip the live estimate entirely and trust the user to know roughly what €47.83 is.

### Bulk mode flow

1. Long-press any row → enter bulk mode. Row checkboxes appear; top action bar slides in.
2. Tap rows to select. Header shows `N selected`.
3. Tap `Skip selected` → confirm dialog ("Skip 12 rows? They can be re-imported.") → fire 12 sequential `splitsmart.skip_staging` calls. Subscription deltas remove rows as they tombstone.
4. Tap `Cancel` → exit bulk mode; selection cleared.

Sequential not parallel: `skip_staging` is fast (single tombstone append) but sequential keeps the coordinator's incremental refresh path coherent and matches the M3 import-loop pattern. Total time for 50 skips ≈ 1s on a Pi — acceptable.

---

## 5. Column-mapping wizard

### Trigger flow

Existing M3 contract — at upload time, the response carries `inspection: {preset, preset_confidence, headers, sample_rows, file_origin_hash, saved_mapping}`. M5 routes:

1. **Preset detected** (`inspection.preset != null`): auto-call `splitsmart.import_file` without mapping. Show progress, then route to staging. No wizard.
2. **Saved mapping found** (`inspection.preset == null && inspection.saved_mapping != null`): same as above — call `import_file` without mapping; the M3 cascade resolves the saved mapping by hash.
3. **Neither** (`inspection.preset == null && inspection.saved_mapping == null`): route to `#import/wizard/<upload_id>`.

### Wizard UI (three steps in a single `<ss-modal>`)

**Step 1 — Preview**

- Title: `Set up column mapping for <filename>`.
- Subtitle: `We don't recognise this file's format. Tell us what each column means.`
- Renders the `headers` array as a horizontal scroll table; first 5 rows from `sample_rows` below it.
- Currency-default picker (defaults to home currency) — for files with no currency column.
- Amount-sign toggle: `Expenses are positive` | `Expenses are negative` (defaults to negative for typical statements).
- `Cancel` (returns to `#import`); `Next` (advances).

**Step 2 — Role assignment**

- One row per header column. Each row: header name + `<ss-column-role-picker>` (single-select: `date | description | amount | debit | credit | currency | category | ignore`).
- Validation: exactly one `date`, exactly one `description`, AND (exactly one `amount`) OR (exactly one `debit` and exactly one `credit`). All other columns default to `ignore`. Error pill below table: `Pick a role for the date / description / amount column.` while invalid.
- Date format selector: dropdown of common patterns (`YYYY-MM-DD`, `DD/MM/YYYY`, `MM/DD/YYYY`, `auto`). Defaults to `auto`.
- `Back`; `Next` disabled until valid.

**Step 3 — Confirm and import**

- Summary of choices: rendered mapping in tabular form.
- "Save mapping for next time" toggle (default on; corresponds to M3 `remember_mapping`).
- `Back`; `Import N rows` button (calls `splitsmart.import_file` with the explicit mapping). On success, route to `#staging`. On `mapping_required` or other ImporterError, show the error inline and stay on step 3.

### Data flow

```
upload (existing http endpoint)
  ↓ inspection payload
import-view.ts
  ↓ if no preset and no saved-mapping
import-wizard-view.ts (steps 1-3)
  ↓ user assembles `mapping`
api.saveMapping(file_origin_hash, mapping)        [splitsmart/save_mapping]
  ↓
api.importFile(upload_id, mapping)                [splitsmart.import_file with explicit mapping]
  ↓ response
navigate to '#staging'
```

The save-mapping call happens **before** the import-file call so that an import-file failure doesn't lose the mapping. Cost of the redundancy: M3's import-file handler also persists the mapping when `remember_mapping=true`, so a successful import double-writes the mapping (newest-wins-on-read absorbs this — see M3 decision O2). Acceptable.

### Edge cases

- User cancels mid-wizard: the upload file remains on disk; the M3 hourly cleanup task removes it after 24h if no staging row references it.
- Network drops between save-mapping and import-file: mapping persisted; import retried via `#import/wizard/<upload_id>` (URL is bookmarkable; state is reconstituted from the saved mapping by re-running step 3's render).
- `file_origin_hash` collision (same headers but different banks): the saved mapping wins, even if it's wrong. M5 doesn't solve this; user can override by passing an explicit mapping to `splitsmart.import_file` from Developer Tools or by deleting the offending row from `mappings.jsonl` (documented in MANUAL_QA_M5).

---

## 6. Bundle deployment for QA

### Problem statement

M3 QA hit a "stale bundle on Pi" issue. M4 worked around it. M5 is the first card-heavy milestone since M2 — three new top-level views, a multi-step wizard, and a detail sheet. Pi QA will iterate on the bundle 5-15 times before merge. The current options:

- `git pull` on the Pi: doesn't transfer the bundle (gitignored per M2_PLAN §2 decision).
- HACS redownload: only fires on tagged releases.
- SCP manually: works but undocumented and easy to forget which file to copy.

### Push-back

The user asked "is SCPing manually each time wrong?" — yes, in the sense that it's friction we can remove for a milestone-bound cost. Manual SCP is fine **if** there's a script in the repo that hides the boilerplate and the README documents it once. Pre-tag publishing to GitHub-as-prerelease would also work but bloats the release feed with N pre-merge artefacts.

### Decision: ship `scripts/deploy-pi.sh`

A bash script in repo root that:

1. Reads target host + SSH user + remote path from env (`SPLITSMART_PI_HOST`, `SPLITSMART_PI_USER`, `SPLITSMART_PI_PATH=/config/custom_components/splitsmart`).
2. Runs `cd frontend && npm run build` (calls Rollup; pre-checks `node_modules` exists).
3. Confirms the bundle is fresh (`stat -c %Y` post-build > pre-build).
4. `rsync -av --delete --exclude='__pycache__' --exclude='*.pyc' custom_components/splitsmart/ "$SPLITSMART_PI_USER@$SPLITSMART_PI_HOST:$SPLITSMART_PI_PATH/"`.
5. Optional restart: `curl -X POST` to HA's REST API with a long-lived token (read from `SPLITSMART_PI_HA_TOKEN`). Skipped if token unset; user restarts via UI.
6. Echoes the bundle URL with a fresh cache-bust query: `https://<host>/splitsmart-static/splitsmart-card.js?v=$(date +%s)` so the user can verify in DevTools.

The script is the thinnest possible wrapper. README gets a short "Pi deploy" section. CI doesn't run it (Pi is private).

### Alternative considered (and rejected)

- **GitHub-released prereleases per commit**: bloats the release feed; HACS doesn't pick up arbitrary prereleases reliably; would need a separate "dev channel" tag pattern.
- **Local HACS-style zip**: the user would download a zip from a local web server on each iteration. More moving parts than rsync.
- **Webhook-driven bundle push**: HA-side script that pulls the latest bundle from a local URL on demand. Real engineering for a temporary problem.

### CHANGELOG note

`Unreleased` block will mention the script and reference `MANUAL_QA_M5.md` for usage. The script lives in the repo, runs from any dev machine with SSH access to the Pi, and works for M6 / M7 too.

---

## 7. Test plan

### Backend unit tests (no HA event loop)

**`tests/test_rules.py`** — new file:

- `load_rules` happy path: two rules, sorted by priority, one without explicit priority falls in source order.
- Bad regex (`/[unclosed/i`): rule skipped, error in returned list.
- Bad action (`always_promote`): skipped, error captured.
- Duplicate `id` within file: second rule rejected, first kept.
- `amount` formats: `> 30`, `< 50`, `10..50`, `null`, missing — all parse to correct min/max bounds. Bad format `"between 10 and 20"` → skipped.
- `always_split` missing `category`: skipped.
- `always_split` missing `split`: skipped.
- `review_each_time` missing `category`: skipped.
- `always_ignore` ignores both `category` and `split`.
- `currency_match` GBP: rule matches GBP rows only.
- Empty rules section: returns `[]`.

**`tests/test_rules_evaluate.py`**:

- Single-rule match against description (case-insensitive).
- Multiple rules; first by priority wins.
- `amount > 30` rule: matches £40, doesn't match £20.
- `amount 10..50` rule: matches £30, doesn't match £55.
- `currency_match: GBP` rule: matches GBP row, doesn't match EUR row.
- No rules match: returns None.
- Rule for `description:"WAITROSE"`, row with `"Waitrose Islington N1"`: matches (case-insensitive).
- Rule with priority 100, second rule with priority 50: priority 50 wins (lower).

**`tests/test_rules_match_payload.py`**:

- `always_split` with `split.preset: 50_50` resolves to a single-category allocation with the named split. `home_amount` matches expense `home_amount`.
- `always_ignore` returns None.
- `review_each_time` returns None.
- Inline `shares` (no preset) — also resolves to a valid split.
- Unknown preset name → raises (caught at load time, but defensive at build time too).

### Backend integration tests (HA event loop, tmp config dir)

**`tests/test_services_apply_rules.py`** (new):

- Setup: 5 pending staging rows, rules.yaml with two rules (Netflix → split, TFL → ignore). Call `splitsmart.apply_rules`. Expected: 2 rows auto-resolved, 3 still pending.
- `apply_rules` is idempotent: second call returns `{auto_promoted: 0, auto_ignored: 0, ...}`.
- `apply_rules` for another user: caller is non-admin → `permission_denied`.
- `apply_rules` after rules.yaml edit: new rule added → matching pending row auto-promotes.
- `apply_rules` with FX failure for a EUR `always_split` rule: row stays pending with `rule_id` + `rule_action="always_split"`; counter `still_pending` reflects it.

**`tests/test_services_import_rules.py`** (new):

- Import 10-row Monzo CSV with rules.yaml in place: rules apply at import time. 3 rows auto-promote, 2 auto-ignore, 5 stay pending. `import_file` response counters match. Expense-log gains 3 rows; tombstones gain 5 (3 promote + 2 discard).
- Re-import same file: dedup catches everything, no new rows, no rule firing.
- Foreign-currency rule-matched row + cache miss + network down: row stays in staging with rule_action set; expense not written; warning logged.
- Cross-user: user A imports a Netflix rule-matched row. The shared expense exists. User B imports the same Netflix row (their statement). Dedup against shared catches it; no new rows for user B. Confirms rules don't bypass dedup.

**`tests/test_websocket_rules.py`** (new):

- `splitsmart/list_rules` returns the loaded rules + loaded_at + source_path.
- Non-participant caller → `permission_denied`.
- `splitsmart/list_rules/subscribe` sends init then a delta on `coordinator.async_reload_rules()`.
- `splitsmart/draft_rule_from_row` for caller's row: returns a YAML snippet with the longest alphabetic run as the regex.
- `splitsmart/draft_rule_from_row` for another user's row: `permission_denied`.
- `splitsmart/draft_rule_from_row` for a non-existent row: `not_found`.
- `splitsmart/reload_rules` triggers reload; subscription delta fires.

**`tests/test_rules_reload.py`** (new):

- File watcher fires on rules.yaml mtime change → coordinator reloads.
- Malformed yaml after edit: previous rules kept; ERROR log.
- Empty rules.yaml after edit: rules list becomes empty.
- File deleted: rules list becomes empty.

### Frontend tests (vitest)

**`frontend/tests/components/staging-row-card.test.ts`**:

- Renders description, date, amount, currency.
- Foreign-currency row: amount rendered with currency suffix; "Split 50/50" disabled.
- "Ignore" always enabled.
- Tap "Split 50/50" emits `ss-promote` with the staging_id and a default categories block.
- Tap "Ignore" emits `ss-skip`.
- Tap row body emits `ss-open-detail` with the staging_id.

**`frontend/tests/views/staging-view.test.ts`**:

- Filters: source filter narrows to matching rows; currency filter same.
- Bulk mode: long-press selects a row; shift-click extends selection (desktop); Cancel exits.
- Bulk skip dispatches N skip calls in sequence.
- Empty state shows two CTAs.

**`frontend/tests/views/import-wizard-view.test.ts`**:

- Step 1 → Step 2 → Step 3 progression.
- Validation: Next disabled until role assignment is valid.
- "Import" calls `api.saveMapping` then `api.importFile`. On import failure, stays on step 3 with error pill.
- Cancel from any step → returns to `#import`.

**`frontend/tests/views/rules-view.test.ts`**:

- Renders rules list from `splitsmart/list_rules`.
- Reload button calls `splitsmart/reload_rules`.
- Empty state shows YAML template snippet.

**`frontend/tests/views/staging-detail-sheet.test.ts`**:

- Opens with row metadata pre-filled.
- Foreign-currency: shows FX hint copy.
- "Promote" calls promote_staging with the assembled categories block.
- "Create rule from this row" opens the snippet sheet.

**`frontend/tests/components/rule-snippet-sheet.test.ts`**:

- Renders the YAML text.
- Copy button calls `navigator.clipboard.writeText` (mocked).
- Close emits `ss-close`.

**`frontend/tests/api.test.ts`** — extend:

- `listRules`, `subscribeRules`, `draftRuleFromRow`, `reloadRules` post the right payloads.
- `applyRules` calls `splitsmart.apply_rules` service.

### Frontend integration smoke

**`frontend/tests/smoke.test.ts`** — extend the existing card-mounts-without-error harness with:

- Mount card; `_stagingRows` populated from mocked subscription.
- Navigate `#staging`; queue renders.
- Navigate `#rules`; rules list renders.
- Navigate `#import/wizard/abc-123` with mocked `inspect_upload`: wizard step 1 renders.

### Manual QA — `tests/MANUAL_QA_M5.md`

Produced when M5 is done. Covers:

1. Upload an unrecognised CSV → wizard opens → walk three steps → import; staging count rises.
2. Upload a Monzo CSV (preset matches) → no wizard; rows land in staging.
3. Re-upload the same Monzo CSV → 0 imported, 10 dedup-skipped.
4. Tap "Split 50/50" on a pending row → row vanishes; Ledger gains the expense; balance sensor updates within 1s.
5. Tap "Ignore" → row vanishes; tombstone present in `tombstones.jsonl`.
6. Undo toast: tap "Undo" within 5s → row returns. After 5s → undo gone.
7. Long-press a row → bulk mode → select 5 rows → Skip → confirmation dialog → 5 rows vanish.
8. Foreign-currency row: tap "Split 50/50" → button is disabled; tap row body → detail sheet opens with FX hint copy.
9. From detail sheet: promote a EUR row with network → expense written with correct `home_amount`; row vanishes from queue.
10. Detail sheet: tap "Create rule from this row" → snippet sheet opens with YAML; tap Copy → paste into `rules.yaml`. Reload via `#rules` → new rule appears.
11. Call `splitsmart.apply_rules` from Developer Tools → existing pending rows matching the new rule auto-promote/auto-ignore; counters match.
12. Edit `rules.yaml` on disk → file watcher reloads within 5s → `#rules` view reflects the change without a refresh.
13. Malformed `rules.yaml` (one bad rule + three good): rules list reflects three; ERROR log captures the bad one; no integration-startup failure.
14. Pi QA: redeploy via `scripts/deploy-pi.sh` → DevTools shows fresh bundle URL → repeat 1-13 from the Pi.
15. Two-device realtime: device A promotes a row; device B's queue updates within 1s.

---

## 8. Decisions

### Resolved during plan review (2026-04-29)

**O1 — Three rule actions.** RESOLVED: ship all three (`always_split`, `always_ignore`, `review_each_time`). Per SPEC §12.5; `review_each_time` sets `category_hint` and `rule_id` without committing to an action.

**O2 — Bulk-promote scope.** RESOLVED: bulk skip only in M5. Bulk-promote needs per-row valid allocations and is v2.

**O3 — `apply_rules` strategy.** RESOLVED: full edit-cycle. When `apply_rules` rewrites a pending row's rule fields, the integration appends a staging tombstone with `operation="edit"` and a replacement staging row carrying the resolved `rule_id` / `rule_action` (and `category_hint` for `review_each_time`). Audit-complete; matches M3/M4's expense-edit pattern.

**O4 — Foreign-currency rule + FX failure.** RESOLVED: surface in the review queue with a `(rule pending FX)` badge on the row card. The row stays pending from the user's perspective; the rule is recorded and will fire automatically when `apply_rules` (or a manual promote) runs with FX reachable. Hiding the row would force a workflow detour through `apply_rules` after every FX hiccup.

**O5 — File watcher.** RESOLVED: 30-second `async_track_time_interval` poll on `rules.yaml` mtime. Cheap, predictable, works on every Pi filesystem. The 5-minute coordinator tick stays as the safety net.

**O6 — `priority` field on rules.** RESOLVED: ship as optional. Default = source-order × 1000. Drafted snippets get heuristic priorities so they slot sensibly into existing rule lists:

| Action | Heuristic priority |
|---|---|
| `always_ignore` | 100 |
| `always_split` | 500 |
| `review_each_time` | 900 |

Lower wins. Drafted ignore-rules slot above drafted catch-all review rules; user-authored explicit priorities override.

**O7 — Live FX estimate on staging detail sheet.** RESOLVED: skip in M5. Foreign-currency rows show the row card with original currency only; the detail sheet shows the copy "FX will be looked up when you promote." No new websocket command, no misleading numbers. Revisit in M7 if QA shows it's a problem.

**O8 — Card upload path.** RESOLVED: card uses `fetch` against the existing `POST /api/splitsmart/upload` endpoint, forwarding HA's bearer token from `hass.auth.data.access_token` (the same token Lovelace uses for its own websocket connection). No new HTTP or websocket surface.

### Additional resolved decisions

**R-add-1 — Staging tombstone "edit" operation.** Staging tombstones carry one of three `operation` values: `promote`, `discard`, `edit`. The `edit` operation is new in M5, used by `apply_rules` to refresh `rule_id` / `rule_action` / `category_hint` on a pending staging row without committing to a terminal action. SPEC §6.2 is amended in step 1 of the implementation order to document this — same approach M3 used for `recurring_id`. The amendment also catches up the SPEC's tombstone-operation enum to include `promote` (M3 introduced it in const.py without a SPEC update at the time).

**R-add-2 — `scripts/deploy-pi.sh` is a first-class deliverable.** Shipped early in the implementation order (step 2) so the rest of M5 can be QAed iteratively against the Pi without manual SCP. Includes a README section documenting the env vars (`SPLITSMART_PI_HOST`, `SPLITSMART_PI_USER`, `SPLITSMART_PI_PATH`, optional `SPLITSMART_PI_HA_TOKEN`) and the deploy + restart flow. Not a follow-up; not optional.

---

## 9. Implementation order

Branch `m5/staging-and-rules` (already created off main). Each step is its own commit where sensible. Merge as a single PR tagged `v0.1.0-m5`.

1. **SPEC amendment** — touch SPEC §6.2 only. Add `promote` and `edit` to the staging-tombstone operation enum, with a one-line note explaining when each is used. No code.
2. **`scripts/deploy-pi.sh` + README section** — shipped early so subsequent steps are QA-able from the Pi without manual SCP. README's "Pi deploy" section documents env vars and the restart flow.
3. **`rules.py` + tests** — pure module: `Rule` dataclass, `RuleParseError`, `load_rules`, `evaluate`, `build_match_payload`. Full unit-test coverage from §7.
4. **Import-time rule integration** — wire rule evaluation into `splitsmart.import_file` between parse and dedup. Counters in service response. Foreign-currency `always_split` rows fall back to "rule pending FX" state per O4.
5. **`splitsmart.apply_rules` service** — handler + `services.yaml` entry + privacy check + counters. Uses the staging-edit tombstone path per O3.
6. **Websocket commands** — `splitsmart/list_rules` (+ subscribe), `splitsmart/draft_rule_from_row`, `splitsmart/reload_rules`. All carry `version: 1`.
7. **File watcher** — 30-second `async_track_time_interval` checking `rules.yaml` mtime; calls `coordinator.async_reload_rules()` on change. Wired in `__init__.py`, unsub via `entry.async_on_unload`.
8. **Frontend rules view + import wizard** — `<ss-rules-view>` (read-only list + reload button + snippet template empty state), `<ss-import-view>`, `<ss-import-wizard-view>` (three-step), `<ss-column-role-picker>`. Vitest covering each.
9. **Frontend staging view + detail sheet** — `<ss-staging-view>`, `<ss-staging-detail-sheet>`, `<ss-rule-snippet-sheet>`, `(rule pending FX)` badge wiring per O4. Extract `<ss-filter-chip>` from the inline ledger markup per the M2 TODO.
10. **Bulk skip + undo toast** — `<ss-undo-toast>`, long-press selection, sequential `skip_staging` calls, confirmation dialog.
11. **`MANUAL_QA_M5.md`** — checklist per §7 manual QA, including the Pi-deploy run-through.
12. **CHANGELOG `Unreleased` entry** — summary of M5 backend (`rules.py`, `splitsmart.apply_rules`, four new websocket commands, file watcher, SPEC amendment) and frontend (staging review queue, detail sheet, import wizard, rules view, deploy script).
