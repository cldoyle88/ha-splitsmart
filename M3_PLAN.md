# M3 plan — import pipeline

Scope is the SPEC §19 M3 milestone plus the pieces of §12 (import), §6.2 (staging JSONL), §7 (privacy), §10 (services), §11 (pending-count sensor) and §15 (file upload endpoint) that the import loop depends on. M3 is backend-heavy; the card surface is one new sensor-driven tile on Home and a file-upload endpoint the import wizard will eventually consume. The full staging review UI, rules engine and rule-driven auto-promotion stay in M5.

End-to-end demo at the end of M3: upload a statement via `/api/splitsmart/upload`, call `splitsmart.import_file`, observe rows appear in `staging/<user>.jsonl` and on `sensor.splitsmart_pending_count_<user>`, call `splitsmart.promote_staging` (or `skip_staging`) row-by-row from Developer Tools, watch the pending count drop and the shared ledger gain an expense. All drivable without touching the card.

---

## 1. Scope fence

### In M3
The user's lean, endorsed with minor tightening:

1. **Parsers for CSV, XLSX, OFX, QIF.** Stub module already exists at `custom_components/splitsmart/importer/`; replace its one-line comment (currently mis-tagged "M5") with real parser modules per SPEC §5.
2. **Preset mappings for Monzo, Starling, Revolut, Splitwise CSV.** Header-row detection per SPEC §12.3. Presets ship as a static registry in `importer/presets.py`.
3. **Column-mapping persistence keyed on a stable file-origin hash.** When a user maps an unrecognised CSV/XLSX once, the next month's statement from the same issuer reuses the mapping automatically. Stored in `/config/splitsmart/mappings.jsonl` (append-only; newest entry per hash wins).
4. **Multiset duplicate detection** per SPEC §12.4, counting file-side occurrences against effective staging + effective shared + skipped-staging tombstones. Cross-bucket counting is non-negotiable for correctness.
5. **Staging JSONL read/write, per-user, privacy-enforced.** Writes through `SplitsmartStorage` (already has `staging_path(user_id)`). Reads go through a new coordinator attribute `staging_by_user` so the pending-count sensor stays a pure read against in-memory state.
6. **`splitsmart.import_file` service** — the entry point that ties upload → parser → dedup → staging write together.
7. **`splitsmart.promote_staging` / `splitsmart.skip_staging` services.** Moved into M3 (nominally M5 per SPEC §19) because without them the end-to-end flow has no terminator and the pending-count sensor can't be seen to drop. The *card* surface for these stays in M5; the services themselves are trivial wrappers around existing `add_expense` + tombstone primitives, and leaving them out would make M3 undemoable.
8. **`splitsmart/list_staging` websocket command.** User-scoped read. Matches the shape and envelope-versioning pattern of M2's `splitsmart/list_expenses`. Deltas via `splitsmart/list_staging/subscribe` — the coordinator already has a listener hook; we re-use it. **The full staging review UI lives in M5; the command lands in M3 so M5 can be a pure frontend milestone.**
9. **`splitsmart/list_presets` websocket command.** Static dump of the preset registry — `[{name, confidence}]`. The M5 wizard renders it as the "use preset" picker; in M3 it's used by tests and by any Developer Tools user who wants to check what's detectable. Details in §3.
10. **`splitsmart/save_mapping` websocket command.** Persists a `{file_origin_hash, mapping}` entry to `mappings.jsonl`. Called by M5's wizard on commit; in M3 callable via Developer Tools for power users. Details in §3.
11. **`splitsmart/inspect_upload` websocket command.** Re-inspection handler for a given `upload_id` — returns the same `inspection` payload the upload endpoint built at upload time. Included in M3 so M5 has a stable contract to build against. Details in §3.
12. **`sensor.splitsmart_pending_count_<user>`** per SPEC §11. State = count of effective staging rows whose `rule_action == "pending"`. Attributes include `last_imported_at`, `promotable_count`, `blocked_foreign_currency_count` — see §5 for the full shape.
13. **Home tile: live pending-count badge** replacing M2's "Coming in M5" placeholder. Reads `sensor.splitsmart_pending_count_<user>` directly through `hass.states`; tap still routes to a stub "Coming in M5" view because the review queue is genuinely M5. This is the single frontend change in M3: updating `placeholder-tile.ts` to render the live count and keeping the stub target.
14. **File upload endpoint** at `POST /api/splitsmart/upload` (SPEC §15). Auth via HA's built-in bearer token + participant check. Files land in `/config/splitsmart/uploads/<uuid>.<ext>`. Returns an `upload_id` plus a lightweight inspection payload so M5's import wizard can decide whether to jump straight to mapping or straight to import.
15. **Daily cleanup task** that purges uploads >24h old not referenced by any live staging row.

### Deferred (with rationale)

| Feature | Defer to | Why |
|---|---|---|
| Full staging review UI (queue, bulk mode, detail sheet, filters) | M5 | Review UI is the reward for having both import and rules; review without rules is a misleading preview that front-loads frontend complexity. SPEC §19 puts the UI at M5 deliberately. |
| Rules engine (`rules.yaml`, regex match, `always_split` / `always_ignore`) | M5 | SPEC §12.5 couples rules to the staging lifecycle; shipping rules without the review UI means the rule-learning loop has nowhere to land. |
| Telegram receipt OCR | M6 | Independent ingestion path, better tested in isolation. |
| FX on import (foreign-currency rows) | M4 | Until FX lands, foreign rows can enter staging but must be blocked at promotion. See §8 decision O4. |
| Column-mapping wizard UI | M5 | Card surface. M3 exposes `splitsmart/inspect_upload` so M5 can build against a stable backend contract, but doesn't render a wizard. Developer Tools users can still import unrecognised files by passing an explicit `mapping` to `splitsmart.import_file`. |
| CSV with `debit` / `credit` split columns that some banks use | M3 | Supported through the mapping: either column can be tagged `amount` with a sign modifier. Presets for Monzo/Starling/Revolut/Splitwise don't use this shape, so it's exercised only via generic-CSV mapping. |
| Recurring-bill materialisation | M4 | Orthogonal to imports; SPEC §19 owns the line. |

### Push-back on the user's lean
**One amendment, one clarification.**

- **Amendment:** The user's bullet list bundles `promote_staging` / `skip_staging` into M3 ("Staging JSONL read/write, per-user file" + "splitsmart.promote_staging / skip_staging services"). SPEC §19 nominally assigns them to M5. The user is right to pull them forward — M3 without them is untestable end-to-end from Developer Tools and the pending-count sensor has nothing to observe. The plan confirms this as an explicit M5→M3 lift and flags it in the CHANGELOG.
- **Clarification:** The user's "minimal card tile on Home" is really *two* things: (a) making the existing `<ss-placeholder-tile>` render a live `N pending rows` count; (b) keeping the tap-through target as a placeholder M5 view. M3 does (a) and keeps (b). No new view component, no new card primitive, no new test file on the frontend side. That matches the user's "feedback loop on imports before the review UI lands" framing.

### What M3 must NOT ship
- Any rules-engine behaviour. Every row imported in M3 lands with `rule_action: "pending"`, `rule_id: null`, `category_hint: null` (unless the preset contributes a hint).
- Any staging-review UI beyond the Home tile's number.
- Any auto-promotion or auto-ignore logic.
- Any FX conversion. Foreign-currency rows are staged but blocked at promote.
- Any Telegram or vision code paths.
- Any edits to `CHANGELOG.md` under released versions — only `Unreleased` is touched.

---

## 2. File upload endpoint

### Route and auth

```
POST /api/splitsmart/upload
Content-Type: multipart/form-data
Authorization: Bearer <long-lived HA token> | <session cookie>
```

Registered in a new module `custom_components/splitsmart/http.py`, wired once in `async_setup_entry` alongside the existing static-path registration:

```python
hass.http.register_view(SplitsmartUploadView(storage))
```

`SplitsmartUploadView` subclasses `homeassistant.components.http.HomeAssistantView`, setting `requires_auth = True` and `url = "/api/splitsmart/upload"`. This gets us HA's bearer-token auth for free (`request["hass_user"]` is a resolved `User`).

### Participant check
Identical semantics to services:

```python
user = request["hass_user"]
entry = _resolve_entry(hass)
if user.id not in entry.data[CONF_PARTICIPANTS]:
    return self.json({"error": "permission_denied"}, status_code=403)
```

### Limits

- **File size:** 25 MB request cap. Statements rarely exceed 2 MB; the ceiling is generous enough for big XLSX dumps while preventing accidental memory pressure. Enforced via aiohttp's `client_max_size` on the view plus an early `request.content_length` check.
- **Allowed extensions:** `.csv`, `.xlsx`, `.ofx`, `.qif`. Case-insensitive match on the client-declared filename suffix. Anything else: 415 Unsupported Media Type.
- **MIME types:** advisory only — we don't trust client-declared MIME. Extension + magic-byte sniff is authoritative. `openpyxl` / `ofxparse` will fail loudly on malformed content anyway.

### Storage path

Files land at `/config/splitsmart/uploads/<uuid4>.<ext>`. `uploads/` is added to `SplitsmartStorage.ensure_layout()`. The uuid (not the original filename) is the on-disk key so two users uploading `transactions.csv` don't collide. The original filename is preserved in the inspection response and forwarded to staging rows as `source_ref`.

### Response shape

```json
{
  "version": 1,
  "upload_id": "<uuid4>",
  "filename": "Statement Apr 2026.csv",
  "size_bytes": 41297,
  "extension": "csv",
  "inspection": {
    "preset": "Monzo" | null,
    "preset_confidence": "high" | "low" | null,
    "headers": ["Date", "Transaction Type", "Amount", ...],
    "sample_rows": [[...], [...], [...]],
    "file_origin_hash": "sha1:abc123...",
    "saved_mapping": { ... } | null
  }
}
```

`inspection` is populated only for CSV and XLSX (the two formats where mapping matters). OFX and QIF return `inspection: null` because their parsers take no mapping input. The card's M5 wizard can branch on `inspection.preset` / `inspection.saved_mapping` to decide whether to show the mapping step.

Error shape on inspection failure (corrupt file, unknown encoding): upload still succeeds, `inspection.preset: null`, `inspection.headers: []`, plus an `error_hint` string. The import step later surfaces the full exception to the caller.

### Cleanup

A new daily task in `__init__.py` via `async_track_time_interval(hass, _cleanup_uploads, timedelta(hours=1))` walks `uploads/`, deletes any file with `st_mtime` older than 24 hours that isn't referenced by a live (non-tombstoned) staging row's `source_ref_upload_id`. The 1-hour poll interval is cheap and keeps the window tight. Alternatively `async_track_time_change(..., hour=3)` for once-a-day at 3am; hourly is safer because it doesn't matter if the HA restart clock skews. **Decision in §7 open questions.**

### What the endpoint does NOT do

- Does **not** parse or import. Import is a separate service call (`splitsmart.import_file`). This split lets the M5 wizard inspect → show mapping → commit without the import being a side effect of upload.
- Does **not** write any staging rows. The file just sits on disk until `import_file` is called.
- Does **not** auto-register itself under the `/api/splitsmart/*` namespace used by any future endpoints — we register this one explicitly. Future views (receipt upload in M6) will be separate views.

---

## 3. Parser module boundary

### Directory layout (expanding the existing stub)

```
custom_components/splitsmart/importer/
├── __init__.py              # Public API: inspect_file, parse_file, register_preset
├── types.py                 # TypedDicts: RawRow, Mapping, FileInspection, ImportResult
├── presets.py               # PRESETS registry + detection helpers
├── csv_parser.py            # CSV / TSV, charset sniff (utf-8 default, cp1252 fallback)
├── xlsx_parser.py           # openpyxl read-only iter_rows
├── ofx_parser.py            # ofxparse wrapper
├── qif_parser.py            # hand-rolled per SPEC §12.1
├── mapping.py               # file_origin_hash, load_saved_mapping, apply_mapping
├── dedup.py                 # multiset duplicate detection
└── normalise.py             # description normalisation (shared with dedup)
```

### Public types (`importer/types.py`)

```python
class RawRow(TypedDict, total=False):
    date: str                 # ISO-8601 YYYY-MM-DD
    description: str
    amount: float             # positive = expense (user paid); signage normalised
    currency: str             # ISO-4217
    category_hint: str | None
    notes: str | None
    raw: dict[str, Any]       # original row, for debugging / later re-parsing

class Mapping(TypedDict):
    # Per-column role assignment. Column keys are the header row's strings
    # for CSV/XLSX, or positional indices as strings for headerless files.
    date: str
    description: str
    amount: str | None           # single amount column
    debit: str | None            # or a debit/credit pair
    credit: str | None
    currency: str | None         # None => default currency
    currency_default: str        # three-letter code
    amount_sign: Literal["expense_positive", "expense_negative"]
    date_format: str             # strptime pattern; "auto" = try a short list
    notes_append: list[str]      # columns concatenated into `notes`
    category_hint: str | None    # column providing category hint, optional

class FileInspection(TypedDict):
    preset: str | None
    preset_confidence: Literal["high", "low"] | None
    headers: list[str]
    sample_rows: list[list[str]]
    file_origin_hash: str
    saved_mapping: Mapping | None

class ParseOutcome(TypedDict):
    rows: list[RawRow]
    errors: list[ParseError]     # per-row errors surfaced at import time
    row_count_raw: int           # including errored rows
```

### Parser contract

Every format-specific parser module exposes two coroutines:

```python
async def inspect(path: pathlib.Path) -> FileInspection: ...
async def parse(path: pathlib.Path, mapping: Mapping | None) -> ParseOutcome: ...
```

`inspect` never raises on mapping ambiguity; if it can't read the file at all it raises `ImporterError` with a user-facing message.

`parse` takes `mapping=None` only for formats where the schema is known (OFX, QIF). CSV / XLSX require a mapping — resolved beforehand by `importer/__init__.py` through the cascade below.

### Mapping resolution cascade (`importer/__init__.py`)

The public entry point `parse_file(path, *, user_mapping=None)` resolves the effective mapping in order:

1. **Explicit argument** — if `user_mapping` is provided, use it and skip detection.
2. **Preset detection** — `presets.detect(headers)` returns the first preset whose `detect(headers)` predicate returns `True`. If found, use that preset's mapping and record `preset_name` in the resulting staging rows as `source_preset`.
3. **Saved per-hash mapping** — load `mappings.jsonl`, find the newest entry whose `file_origin_hash` matches, use its stored mapping.
4. **No mapping** — raise `ImporterError(code="mapping_required", inspection=...)` so the service handler can return a structured error the M5 wizard or a Developer Tools caller can act on. The raised exception carries the `FileInspection` for echo-back.

OFX and QIF skip the cascade entirely — their parsers produce `RawRow`s directly from the file.

### Preset registry shape (`importer/presets.py`)

```python
@dataclass(frozen=True)
class Preset:
    name: str
    detect: Callable[[list[str]], bool]
    mapping: Mapping
    confidence: Literal["high", "low"]   # "low" for loose header matches

PRESETS: list[Preset] = [
    Preset("Monzo",       detect_monzo,       MONZO_MAPPING,    "high"),
    Preset("Starling",    detect_starling,    STARLING_MAPPING, "high"),
    Preset("Revolut",     detect_revolut,     REVOLUT_MAPPING,  "high"),
    Preset("Splitwise",   detect_splitwise,   SPLITWISE_MAP,    "high"),
]

def detect(headers: list[str]) -> Preset | None:
    for preset in PRESETS:
        if preset.detect(headers):
            return preset
    return None
```

Each detector is a tiny pure function — a subset of the expected headers, normalised (strip, lower). User contributions of further presets land as PRs that append to `PRESETS`.

### The stable API the M5 wizard builds against

M5 will wrap these backend commands (all reached via websocket):

- `splitsmart/inspect_upload` (new in M3) — takes `upload_id`, returns the upload endpoint's `inspection` payload on demand, so the wizard can re-inspect after the user picks a mapping or uploads a replacement.
- `splitsmart/list_presets` (new in M3) — static list of `[{name, description}]` so the wizard can render a "use preset" picker next to "manual mapping".
- `splitsmart/save_mapping` (new in M3) — takes `{file_origin_hash, mapping}`, appends to `mappings.jsonl`. Called once the user commits a mapping so next month's import is frictionless.

These three commands are built in M3 and exercised by Python-side tests; the card-side consumer code lands in M5.

### `file_origin_hash`

Purpose: stable across month-to-month exports from the same bank, differs between banks, differs between distinct CSV schemas of the same bank (e.g. Monzo "Classic" vs Monzo "Plus" exports).

Recipe:
```
sha1(
    "\n".join(header_cells_normalised) + "|" +
    first_row_column_count + "|" +
    extension
)
```
Headers normalised: strip, lower. Not content-hashed — content changes month to month. 16 bytes of hex is plenty (`sha1:` prefix for clarity, not for security).

---

## 4. Multiset duplicate detection

### Hash shape

```python
DEDUP_HASH = sha256(
    f"{date}|{round(amount, 2):.2f}|{currency}|{normalised_description}"
).hexdigest()
```

Stored on every staging row as `dedup_hash` (matches SPEC §6.2 schema). The hash is computed by the importer, not by the parser — so `RawRow` doesn't need to know it exists.

### Description normalisation (`importer/normalise.py`)

```python
def normalise_description(raw: str) -> str:
    """Stable form for dedup hashing.

    Steps, in order:
      1. Strip outer whitespace.
      2. Drop leading '*' characters (some card issuers prepend *).
      3. Drop trailing trailing-date strings — issuer-appended dd/mm,
         dd/mm/yyyy, yyyy-mm-dd. Regex: \\s*\\d{1,2}[/-]\\d{1,2}([/-]\\d{2,4})?\\s*$
         and \\s*\\d{4}-\\d{2}-\\d{2}\\s*$.
      4. Upper-case.
      5. Collapse all runs of whitespace to a single space.
      6. Trim.
    """
```

Examples that should collapse to the same hash:
- `"WAITROSE ISLINGTON N1"` and `"Waitrose  Islington N1  "` → same.
- `"*NETFLIX.COM"` and `"NETFLIX.COM"` → same.
- `"TFL TRAVEL 15/04"` and `"TFL TRAVEL 16/04"` → same (trailing dates stripped).
- `"TESCO METRO 2026-04-15"` and `"TESCO METRO"` → same.

Examples that should NOT collapse:
- `"UBER"` and `"UBER EATS"` → different (intentional; stripping suffixes would be too aggressive).
- `"AMAZON"` and `"AMZN MKTP"` → different (no merchant-identity canonicalisation in v1; SPEC §21 roadmap).

### Treatment of tombstones (the multiset counting rule)

Per SPEC §12.4:

```
file_counts[hash]     = occurrences of hash in the file being imported
existing_counts[hash] = effective_staging_for_this_user[hash]
                      + effective_shared[hash]
                      + skipped_staging_tombstones[hash]
imported[hash]        = max(0, file_counts[hash] - existing_counts[hash])
skipped_as_dup[hash]  = file_counts[hash] - imported[hash]
```

Where:

- `effective_staging_for_this_user` — the uploader's staging file with all tombstones applied. **Only the uploader's staging is counted, per SPEC §7 privacy.** Another participant's staging is invisible.
- `effective_shared` — the coordinator's materialised `expenses` list (post-tombstone). Every participant sees the same thing.
- `skipped_staging_tombstones` — tombstones with `target_type="staging"` where the original staging row belonged to this user **and** which represent a skip, not a promote. See "tombstone operation taxonomy" below.

### Tombstone operation taxonomy for staging

The existing M1 constants (`TOMBSTONE_EDIT`, `TOMBSTONE_DELETE`, `TOMBSTONE_DISCARD`) need one extension for M3 to distinguish promote from skip. Two candidate designs:

**A (preferred).** Add a new operation value `TOMBSTONE_PROMOTE` (`"promote"`). `skip_staging` writes `operation="discard"`; `promote_staging` writes `operation="promote"` with a mandatory `replacement_id` pointing at the new shared expense. Dedup counts only `operation="discard"` tombstones.

**B.** Reuse `discard` for both. Add an optional `replacement_id` field on tombstones. Dedup counts `discard` tombstones with `replacement_id is None`.

**Decision: A.** Clearer logs, clearer dedup code, tiny schema extension. Implementation adds `TOMBSTONE_PROMOTE = "promote"` to `const.py`; `promote_staging` writes tombstones with `operation="promote"` and a mandatory `replacement_id` pointing at the new shared expense.

### Where dedup runs

Inside `importer/dedup.py`:

```python
def partition_by_dedup(
    file_rows: list[RawRow],
    *,
    existing_staging: list[dict[str, Any]],           # materialised, this user
    existing_shared: list[dict[str, Any]],            # materialised, all users
    skipped_staging_tombstones: list[dict[str, Any]], # this user, discard-only
    user_id: str,
) -> tuple[list[RawRow], list[RawRow]]:
    """Returns (to_import, to_skip_as_duplicate)."""
```

Pure function. `existing_*` lists are supplied by the caller (the service handler), read from the coordinator — so dedup doesn't do IO, and unit tests pass synthetic lists.

### Edge cases the tests must cover

1. **3 coffees on the same day.** File has 3, existing has 0 → import 3. Re-import same file → import 0.
2. **3 coffees, 1 promoted, re-import.** Existing counts: 0 effective staging + 1 shared + 1 promote-tombstone (not counted) + 0 discard-tombstone = 1. File has 3. Import 2. (Regardless of whether the original imported rows were promoted, skipped or still pending, the accounting arrives at the right net.)
3. **3 coffees, 1 skipped, re-import.** Existing: 2 effective staging + 0 shared + 1 discard-tombstone = 3. File has 3. Import 0.
4. **2 coffees this week, 3 next week.** First import: 2 rows in. Second import (file now has 3): existing = 2 staging, file = 3 → import 1.
5. **Normalisation collision.** Two file rows differ only by trailing date → same hash → counted as 2 in file, behave as above.
6. **Cross-user shared dedup.** User A imports 1 Netflix. User B imports 1 Netflix in the same month. The Netflix in A's staging is only counted against A; B's import sees 0 A-staging, 0 shared (nothing promoted yet) → imports 1. Correct: staging is private.
7. **Promoted-but-then-deleted.** A Netflix is promoted, then someone deletes the shared expense. Effective shared = 0; tombstone on shared has `target_type=expense`, which dedup ignores. Promote-tombstone on staging not counted. Re-import lets the row back in (arguably correct — user deleted it, they can re-import).
8. **Discarded-but-then-undone.** If M3 adds "undo skip" (it doesn't; that's an M5 reach feature), we'd append an edit tombstone on the tombstone. Out of scope for M3; SPEC has no provision.

---

## 5. Staging lifecycle

### Record shape (matches SPEC §6.2, one minor addition)

```json
{
  "id": "st_01J9X...",
  "uploaded_by": "user_abc123",
  "uploaded_at": "2026-04-22T14:03:00+01:00",
  "source": "csv",
  "source_ref": "Statement Apr 2026.csv",
  "source_ref_upload_id": "a1b2c3d4-....",
  "source_preset": "Monzo",
  "date": "2026-04-15",
  "description": "WAITROSE ISLINGTON N1",
  "amount": 47.83,
  "currency": "GBP",
  "rule_action": "pending",
  "rule_id": null,
  "category_hint": "Groceries",
  "dedup_hash": "sha256:...",
  "receipt_path": null,
  "notes": null
}
```

Additions vs SPEC §6.2:
- `source_ref_upload_id` — the uuid filename under `uploads/` so the daily cleanup task knows which uploads are still alive.
- `source_preset` — preset name when detection fired, otherwise `null`. Useful for audit and for later "one-click reimport" UX.

Both are forward-compatible — SPEC §6.2 is a subset example rather than an exhaustive schema, per the existing M1/M2 pattern of richer records than the spec minimum.

### `splitsmart.import_file`

```yaml
name: Import file
description: Import rows from a previously uploaded statement.
fields:
  upload_id:
    required: true
    example: a1b2c3d4-...
  mapping:
    required: false
    description: Explicit column mapping. Omitted => preset/saved-hash resolution.
  rule_set:
    required: false
    description: Future — rules run at import time. In M3, ignored; every row lands pending.
  remember_mapping:
    required: false
    default: true
    description: Save the resolved mapping under this file's origin hash.
```

Handler steps, in order:
1. Resolve upload → `/config/splitsmart/uploads/<upload_id>.<ext>`. 404 → `ServiceValidationError`.
2. Caller identity from `call.context.user_id`; must be in participants.
3. Dispatch to parser based on extension. Apply mapping cascade (§3).
4. For every parsed row, compute `dedup_hash`.
5. Call `importer.dedup.partition_by_dedup(...)` to split into `to_import` + `to_skip_as_dup`.
6. For each `to_import` row, build a staging record (new ULID with `st_` prefix) and append to `staging/<uploader>.jsonl`. Single sequential loop — not parallel — so the coordinator's `async_note_write` only fires once at the end with clean last-id cursors.
7. Optionally persist the mapping to `mappings.jsonl` if `remember_mapping` and we went through the wizard path.
8. Refresh the coordinator's staging projection (see §6).
9. Return `{"upload_id": ..., "imported": N, "skipped_as_duplicate": M, "parse_errors": K, "blocked_foreign_currency": F, "preset": "Monzo"}` via `SupportsResponse.OPTIONAL`. Parse errors are included as a count plus a `first_error_hint`; full per-row errors are out of the service response (they can be fetched via a follow-on websocket command later if we find we need it). `blocked_foreign_currency` is a subset of `imported` — rows that staged successfully but will be rejected at promote until M4's FX lands. Reported here so a Developer Tools user knows up front how much of their import is "wait for M4".

Foreign-currency rows stage as-is with their original `currency`. Promotion is blocked by `promote_staging` (§5) with the user-friendly error `"Foreign currency promotion arrives in M4. Row stays staged."`; the staging row is not tombstoned, so the user can retry once M4 ships. Staging is cheap to hold; the user learns on promote. The `blocked_foreign_currency_count` sensor attribute (§5) surfaces the running total at any point without re-reading the file.

### `splitsmart.promote_staging`

```yaml
fields:
  staging_id:    required: true
  categories:    required: true       # same shape as add_expense
  paid_by:       required: true
  notes:         required: false
  receipt_path:  required: false
  override_description: required: false   # user can rename at promotion
  override_date:        required: false
```

Handler:
1. Load staging row; must exist in uploader's staging and not already tombstoned. **Privacy: if the caller is not the uploader, reject with `permission_denied` even if they're a participant.** The spec is explicit (§7).
2. **Foreign-currency guard.** If `staging_row["currency"] != home_currency`, raise `ServiceValidationError("Foreign currency promotion arrives in M4. Row stays staged.")` before any write. No tombstone, no expense record; the staging row is untouched and the user retries once M4 ships.
3. Build an expense record using `build_expense_record`; `source="staging"`, `staging_id=staging_id`. `paid_by` validated as a participant. Overrides applied if present.
4. Append the expense record first (see M1 amendment 5).
5. Append a staging tombstone: `target_type="staging"`, `target_id=staging_id`, `operation="promote"`, `replacement_id=<new_expense_id>`, `previous_snapshot=<full staging row>`.
6. Notify coordinator.
7. Return `{"expense_id": ex_..., "staging_id": st_...}`.

The expense-before-tombstone order matches M1's `edit_expense` invariant: a crash between the two leaves an extra expense, not a disappeared row.

### `splitsmart.skip_staging`

```yaml
fields:
  staging_id: required: true
  reason:     required: false
```

Handler:
1. Load + ownership check (as promote).
2. Append tombstone `target_type="staging"`, `operation="discard"`, `previous_snapshot=<full staging row>`, `reason=reason`.
3. Notify coordinator.
4. Return `{"staging_id": st_...}`.

### Mapping onto M1's service surface

Every M3 write goes through the existing `SplitsmartStorage.append` / `append_tombstone` primitives. No new storage mutation paths. The coordinator gains a fourth in-memory projection (staging), but its refresh path is the same pattern as `raw_expenses` / `raw_settlements` / `tombstones`:

```python
@dataclass
class SplitsmartData:
    # existing M1/M2 fields...
    raw_staging_by_user: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    staging_by_user: dict[str, list[dict[str, Any]]] = field(default_factory=dict)   # materialised
    last_staging_id_by_user: dict[str, str | None] = field(default_factory=dict)
```

On startup: full replay — iterate every `staging/<user>.jsonl` the storage layer knows about. On write: the touched user's staging plus the tombstones log get `read_since`-refreshed. The full-replay safety-net tick stays at 5 min.

`materialise_staging` is a new pure function in `ledger.py` — adjacent to `materialise_expenses` and `materialise_settlements`, since all three are the same-shape materialisation pass. Applies staging tombstones to the raw staging log: drop any row whose id appears as any tombstone's `target_id`. No chain-following needed; promote and skip both target the original staging id and both write the tombstone as the final step.

### `sensor.splitsmart_pending_count_<user>`

One per participant. `state = len([r for r in data.staging_by_user.get(user_id, []) if r["rule_action"] == "pending"])`. Attributes:

- `last_imported_at: <max uploaded_at>` (string or None)
- `home_currency`: string
- `oldest_pending_date: <min date>` — helps the M5 queue prioritise.
- `promotable_count: <N>` — pending rows whose `currency == home_currency` (eligible for promote today).
- `blocked_foreign_currency_count: <N>` — pending rows whose `currency != home_currency` (waiting on M4 FX). The two counts partition the `state` total: `state == promotable_count + blocked_foreign_currency_count`.

Follows M1's sensor conventions (`CoordinatorEntity`, `state_class = total`). Unique id `f"{entry.entry_id}_pending_count_{user_id}"`. Display name `"Splitsmart pending count (<display_name>)"` via the existing user-registry lookup.

### Websocket: `splitsmart/list_staging`

```
Request:  {type: "splitsmart/list_staging", user_id?: "user_..."}
Response: {version: 1, rows: [<staging record>, ...], tombstones: [...]}
```

`user_id` defaults to `connection.user.id`. If set to another user id, the command returns `permission_denied` — per-user staging is private. Non-participants get the same error. Shape is `rows` + `tombstones` so the M5 queue UI can compute its own materialised view if it wants to (symmetry with how `list_expenses` does it, and a nicety for debugging).

### Subscription: `splitsmart/list_staging/subscribe`

Long-lived, user-scoped. The coordinator's listener hook fires on every write; the subscription filters deltas to the subscribed user's staging rows (including tombstones targeting that user's staging rows). Card code in M5 subscribes on mount of the review view; the Home tile doesn't subscribe — it reads `sensor.splitsmart_pending_count_<user>` through `hass.states` and updates for free.

---

## 6. Coordinator and concurrency

### Incremental refresh path

`async_note_write` gains a `user_id: str | None` hint so the coordinator can reload only the touched staging file. When `None`, it reloads every staging file (used by the startup replay and the 5-min safety-net tick).

### Concurrent imports — serialisation

M1 serialises writes per-file via an `asyncio.Lock` registry (`SplitsmartStorage._locks`). Import needs the lock on `staging/<user>.jsonl` plus `tombstones.jsonl` for the post-import tombstone writes. No change to the storage layer; the importer just calls `append` in sequence. Two simultaneous imports for the same user queue up; two simultaneous imports for two different users run in parallel (separate file locks).

### Listener-hook delivery for staging deltas

M2's subscription uses `coordinator.async_add_listener`. For M3's `list_staging/subscribe`, the handler filters the `SplitsmartData` diff to the subscribed user's staging scope. Since the diff is constructed from `last_*_id` cursors, we add per-user staging cursors (see `last_staging_id_by_user`) and thread them through.

### Pending-count sensor updates

No custom wiring; `CoordinatorEntity` re-renders on every `async_set_updated_data`. That's correct because every import / promote / skip goes through `async_note_write` and fires the same update hook.

---

## 7. Test plan

### Fixtures (`tests/fixtures/`)

New subdirectory `tests/fixtures/imports/`. Anonymised samples produced by hand (not pulled from real statements). Each fixture is small (~10 rows) and committed with a short README.md explaining what it represents and what it's intended to exercise. Per CLAUDE.md "Files never to edit" rule, once fixtures land they are immutable.

Files:

- `imports/monzo_classic.csv` — 10 rows covering expense + income + transfer, typical Monzo export columns.
- `imports/starling_standard.csv` — 10 rows with `Counter Party`, `Reference` columns, debit/credit single-column signed amount.
- `imports/revolut_account.csv` — 10 rows, foreign-currency rows included (EUR + USD) to exercise §8 O4.
- `imports/splitwise_export.csv` — 10 rows exported from Splitwise, "Date, Description, Category, Cost, Currency" columns.
- `imports/generic_headerless.csv` — ambiguous 10 rows to exercise explicit-mapping path.
- `imports/generic_debit_credit.csv` — split debit/credit columns to exercise that mapping shape.
- `imports/sample.ofx` — short synthetic OFX 2.x body.
- `imports/sample.qif` — ten QIF transactions covering `!Type:Bank` with date, amount, payee, memo lines.
- `imports/malformed.csv` — one row with non-numeric `Amount`, for parse-error surfacing tests.

### Unit tests (no HA event loop)

**`tests/test_importer_parsers.py`** — one test class per parser module:

- CSV parser round-trips each preset fixture; resulting `RawRow`s have canonical ISO dates, positive amounts, correct currency.
- XLSX parser round-trips a synthesised fixture (built at test time via openpyxl so we don't commit binary blobs that count as "fixtures"). Reads exactly the same logical rows as the Monzo CSV, to prove XLSX + CSV converge on the same `RawRow` shape.
- OFX parser reads `sample.ofx`; validates amount signage and date parsing.
- QIF parser reads `sample.qif`; validates memo concatenation and `!Type:CCard` handling.
- Malformed CSV surfaces per-row `ParseError` entries and still yields the good rows.

**`tests/test_importer_presets.py`**:

- `detect(headers)` returns the correct preset for each of Monzo, Starling, Revolut, Splitwise header sets.
- Unknown headers return `None`.
- Minor header variants (lowercase, whitespace, extra trailing column) still match — confidence flagged as `"low"` rather than `"high"` where appropriate.

**`tests/test_importer_normalise.py`** — the normalisation examples from §4.

**`tests/test_importer_dedup.py`** — the matrix from §4 "Edge cases the tests must cover". Every scenario gets a named test with explicit input/output.

**`tests/test_importer_mapping.py`**:

- `file_origin_hash` is stable across month-to-month fixtures with the same header row.
- `file_origin_hash` differs between Monzo and Starling.
- `load_saved_mapping` returns the newest entry per hash when multiple appended.
- Mapping resolution cascade: explicit arg wins; preset beats saved; saved beats nothing; no-match raises.

### Integration tests (HA event loop, tmp config dir)

**`tests/test_services_import.py`**:

- Happy path: upload a Monzo CSV via a mocked request to the view, call `splitsmart.import_file`, assert staging file has 10 rows, pending-count sensor is 10, no tombstones written.
- Re-import the same file: `imported=0, skipped_as_duplicate=10`, staging file unchanged, sensor still 10.
- Import same file with an overlap (remove 2 rows, add 3 new): `imported=3, skipped_as_duplicate=7`, sensor goes to 13.
- Import of a file containing EUR + USD rows returns `blocked_foreign_currency == <EUR+USD count>` in the service response, and the sensor's `blocked_foreign_currency_count` attribute matches.
- Foreign-currency row stages with original currency; promotion raises `ServiceValidationError("Foreign currency promotion arrives in M4. Row stays staged.")` — staging row remains live (no tombstone written), `promotable_count` unchanged.
- `promote_staging` happy path: appends shared expense AND staging tombstone with `operation="promote"` + `replacement_id`; pending-count sensor drops by 1; balance sensor updates.
- `promote_staging` with non-owner caller returns `permission_denied`.
- `skip_staging` happy path: appends staging tombstone with `operation="discard"`; pending count drops; no expense written.
- After promote, re-import the same file: dedup accounts for the shared expense, row is skipped as duplicate.
- After skip, re-import the same file: dedup accounts for the discard tombstone, row is skipped as duplicate.

**`tests/test_http_upload.py`** — direct tests of the view using `aiohttp_client`:

- POST with valid file → 200 and the full response shape.
- POST without auth → 401.
- POST with auth but non-participant user → 403.
- POST with an unsupported extension → 415.
- POST with an oversize file → 413.
- POST of a corrupt CSV succeeds but returns `inspection.preset: null` + `error_hint`.

**`tests/test_websocket_staging.py`**:

- `splitsmart/list_staging` scoped to caller; other user's staging is rejected.
- `splitsmart/list_staging/subscribe` sends initial snapshot, then pushes a delta after `splitsmart.import_file` succeeds.
- Delta payload contains only the caller's staging diffs — no cross-user leakage.

**`tests/test_sensors_pending_count.py`**:

- Entity exists for each participant.
- State updates on import, promote, skip without entity reload.
- `last_imported_at` attribute advances on each import.
- `promotable_count + blocked_foreign_currency_count == state` invariant holds after every import/promote/skip transition.
- Importing 3 GBP + 2 EUR rows (home currency GBP): `state=5`, `promotable_count=3`, `blocked_foreign_currency_count=2`.

**`tests/test_uploads_cleanup.py`**:

- An upload with `st_mtime` 25h old and no referring staging row gets purged on the cleanup tick.
- An upload with `st_mtime` 25h old but referenced by a live staging row is retained.
- An upload with `st_mtime` 2h old is retained regardless.

### Frontend tests (vitest)

Minimal — one file:

**`frontend/tests/components/placeholder-tile.test.ts`** — updated: renders `You have 3 rows to review` when the sensor state is `3`; renders `You're all caught up` when the state is `0`; renders `Coming in M5` with no count when the sensor is unavailable. Tap still navigates to the stub M5 target.

### Manual QA — `tests/MANUAL_QA_M3.md`

Produced when M3 is done. Covers:

1. Upload a 200-row Monzo statement via `curl -F file=@…` — response arrives in <2s, `uploads/` contains the file.
2. Call `splitsmart.import_file` from Developer Tools — response contains plausible `imported` and `skipped_as_duplicate` counts, sensor `pending_count` matches.
3. Re-upload + re-import — zero new rows.
4. Promote a single staging row via Developer Tools — balance sensor on the card updates within 1s on a second device.
5. Skip a single staging row — pending count drops, balance unchanged.
6. Upload an unrecognised CSV, call `import_file` without mapping — service returns structured `mapping_required` error.
7. Supply an explicit mapping — rows import.
8. Save the mapping, re-upload next-month statement (same headers) — `inspection.saved_mapping` is set, import without supplying mapping succeeds.
9. Upload `sample.ofx` and `sample.qif` — rows import, no mapping required.
10. Home tile on the card renders the live count; tapping still shows the "Coming in M5" placeholder view.
11. Upload a file, wait, confirm the daily cleanup task removes it (test via manually running the cleanup coroutine).
12. Windows QA from the Pi-dev-loop — concurrent imports by two users land in their respective staging files, no cross-contamination.

---

## 8. Decisions

Resolved 2026-04-22. Each maps to a concrete implementation consequence flagged in-plan above.

**O1 — Tombstone operation taxonomy for staging. Decision: A.**
Add `TOMBSTONE_PROMOTE = "promote"` to `const.py`. `promote_staging` writes tombstones with `operation="promote"` and a mandatory `replacement_id` pointing at the new shared expense. `skip_staging` keeps `operation="discard"`. Dedup counts only `discard` tombstones.

**O2 — Mapping persistence format. Decision: JSONL.**
`/config/splitsmart/mappings.jsonl`, append-only. Newest entry per `file_origin_hash` wins on read.

**O3 — Cleanup task cadence. Decision: hourly.**
`async_track_time_interval(hass, _cleanup_uploads, timedelta(hours=1))`. Resilient to restart clock skew; keeps the 24-hour window tight.

**O4 — Foreign-currency rows in imports. Decision: stage them, block at promote, with user-facing accounting.**
Rows stage with their original `currency`. Promotion raises `ServiceValidationError("Foreign currency promotion arrives in M4. Row stays staged.")` — the staging row is untouched, so the user retries once M4 ships. Two attributes on `sensor.splitsmart_pending_count_<user>` surface the partition: `promotable_count` (currency equals home) and `blocked_foreign_currency_count` (currency differs); together they equal `state`. The `splitsmart.import_file` service response adds a `blocked_foreign_currency: N` field so a Developer Tools user sees up front how much of the import is "wait for M4".

**O5 — `splitsmart/inspect_upload` scope. Decision: M3.**
Ships in M3 alongside `splitsmart/list_presets` and `splitsmart/save_mapping` so M5's wizard has a stable backend contract to build against.

**O6 — Upload file size cap. Decision: 25 MB.**
Enforced on the view via `client_max_size` plus an early `request.content_length` check.

**O7 — Staging record extra fields. Decision: amend SPEC §6.2.**
Adds `source_ref_upload_id` and `source_preset` to the documented staging schema example. The amendment lands in a dedicated commit early in implementation so subsequent code changes reference a spec that matches reality.

**O8 — Promote-time FX pre-reservation. Decision: no.**
The M3 promote tombstone carries `replacement_id` pointing at the expense record. Any FX details live on the expense (per SPEC §8), not on the tombstone, so M4 adds nothing to the tombstone payload.

**O9 — `validate_root` for `uploads/`. Decision: confirmed — no additional guard.**
`uploads/` is a subdirectory under the already-validated root, and the M1 guard protects the whole subtree.

**O10 — `materialise_staging` location. Decision: `ledger.py`.**
Sits next to `materialise_expenses` and `materialise_settlements`; same-shape pure pass, same invariants, same test file conventions.

### Implementation order

Implementation proceeds on branch `m3/import-pipeline` in this order, each step its own commit where sensible:

1. **Tombstone constant extension** — smallest-possible diff adding `TOMBSTONE_PROMOTE` to `const.py`.
2. **SPEC §6.2 amendment** — document `source_ref_upload_id` and `source_preset` on the staging schema example.
3. **Storage extensions** — `uploads/` in `ensure_layout`, typed path accessors for `uploads/`, `mappings.jsonl`, per-user staging replay helpers.
4. **Parsers** — `csv_parser.py`, `xlsx_parser.py`, `ofx_parser.py`, `qif_parser.py`, `presets.py`, `mapping.py`, `normalise.py`, `types.py`; fixtures.
5. **Dedup** — `dedup.py` with the multiset counting rule and edge-case tests from §4.
6. **Services** — `import_file`, `promote_staging`, `skip_staging` handlers + `services.yaml` entries; `materialise_staging` in `ledger.py`; coordinator extensions.
7. **Sensor** — `sensor.splitsmart_pending_count_<user>` with the `promotable_count` / `blocked_foreign_currency_count` attributes.
8. **Websocket commands** — `splitsmart/list_staging` + `/subscribe`, `splitsmart/list_presets`, `splitsmart/save_mapping`, `splitsmart/inspect_upload`.
9. **Upload endpoint** — `http.py` with `SplitsmartUploadView` and size/extension/participant guards.
10. **Cleanup task** — hourly `async_track_time_interval` purge of orphaned uploads.
11. **Home tile tweak** — `placeholder-tile.ts` renders the live pending count; tap target still the M5 stub.
12. **Tests** — per the §7 test plan, including `MANUAL_QA_M3.md`.
13. **Changelog** — `CHANGELOG.md` Unreleased section entries for M3.
