# M2 plan — Lovelace custom card

Scope is the SPEC §19 M2 milestone (with the completion-report reshuffle applied: the custom card lands in M2, the import pipeline moves to M3, FX and recurring move to M4, staging + rules move to M5, Telegram OCR stays in M6, polish in M7). This plan covers the frontend build pipeline, the card bundle's registration into HA, the data contract between card and backend, and the views shipped in M2. It does **not** touch Python other than the minimum needed to serve and auto-register the bundle, and to expose a read-only websocket command for the expense list.

Out of M2 entirely: FX (M4), recurring (M4), staging (M5), rules (M5), import (M3), Telegram OCR (M6). The card must not render UI for those features except as clearly labelled "coming in M<n>" placeholders where the absence would make M2 feel broken (e.g. a Staging tile on Home with a "coming in M5" badge is acceptable; a fully-styled staging queue pretending to work is not).

---

## 1. Scope fence

### In M2
The lean the user proposed, accepted as-is:

- **Home** — balance summary, single-line "You owe X £Y" / "X owes you £Y" headline, a per-user balance strip for N ≥ 2 participants, quick actions (Add expense, Settle up, Ledger). Pending-review tile is rendered as a "coming in M5" placeholder because it would be the natural hero CTA on Home once staging lands.
- **Ledger** — reverse-chronological list of shared expenses, filter chips for month (current, last, picker) and category (from `coordinator.categories`). Grouped by date, infinite-scroll virtualised once the list passes ~100 rows. Each row is the primitive `<ss-row-card>` and opens the Detail sheet on tap.
- **Add expense** — the full form from SPEC §14: date, description, paid_by, amount (single currency in M2 = home), category picker (single-category default), multi-category allocator (toggle), split picker (equal / percentage / shares / exact), uniform-split default with per-category override toggle, notes. Live remainder indicator. Save disabled until balanced. The M2 form deliberately covers the full allocation model from SPEC §9 so the Detail sheet can reuse the exact same component.
- **Settle up** — from/to picker (restricted to `participants`), date, amount, optional notes. Suggests the current pairwise debt as a pre-filled amount. Single-action screen, no extras.
- **Detail sheet (expense)** — modal opened from a Ledger expense row. View mode by default; Edit mode toggles the same Add-expense form prefilled, Save calls `splitsmart.edit_expense`, Delete calls `splitsmart.delete_expense` (confirm dialog).
- **Detail sheet (settlement)** — modal opened from a Ledger settlement row. View mode shows from/to/amount/date/notes; Edit mode reuses the Settle Up form prefilled, Save calls `splitsmart.edit_settlement`, Delete calls `splitsmart.delete_settlement` (confirm dialog). Included in M2 because M1 wired up the edit/delete settlement services and leaving them unreachable from UI is asymmetric.

### Deferred (with rationale)

| View | Defer to | Why |
|---|---|---|
| Staging queue | M5 | No staging backend exists yet; a placeholder tile on Home with a "coming in M5" badge covers the UX gap. |
| Import wizard | M3 | No parsers, no upload endpoint, no mapping schema. Keeps M2 testable without file I/O. |
| Rules editor | M5 | Depends on staging (rules only fire on staging rows) and the `rules.yaml` watcher. |
| Settings | M6 polish | Everything configurable in M2 lives in the HA options flow already — currency, categories. Revisiting in M6 gives us time to learn what actually needs a card-side surface (named splits, Telegram mapping, vision key). |
| FX toggle / foreign-currency entry in Add form | M4 | Backend rejects non-home currency in M1/M2. Form locks `currency` to home, no picker rendered. |

### Push-back on the lean
**None.** The proposed fence is internally consistent: Home → Ledger → Add/Settle up → Detail covers the full shared-ledger loop that M1 already supports end-to-end. The one clarification: the Add expense form in M2 must already implement multi-category allocation and per-category split, because SPEC §14 treats these as first-class and the Detail sheet's Edit mode has to round-trip them. Shipping a reduced "single category only" Add form and retrofitting later would be churn.

### What the card must NOT show in M2
- Any FX / foreign-currency UI.
- Any staging / pending-rows UI (other than the placeholder tile on Home).
- Any import / upload UI.
- Any rules UI.
- Any Telegram / vision UI.
- Any recurring-bills UI.

### Stretch (explicitly pushed back to M6/M7 polish, not M2)
- Activity feed on Home.
- Search over expenses.
- Category charts / spending-over-time graphs.
- CSV export.
- Deep-link handling from mobile notifications (there are no notifications until M7).

---

## 2. Build pipeline

### Toolchain
Per SPEC §4: Lit 3 + TypeScript, Rollup to a single ES module bundle. No external CSS framework.

### `frontend/package.json` — proposed contents

```json
{
  "name": "@splitsmart/card",
  "version": "0.2.0",
  "private": true,
  "type": "module",
  "scripts": {
    "build": "rollup -c",
    "watch": "rollup -c -w",
    "typecheck": "tsc --noEmit",
    "test": "vitest run",
    "test:watch": "vitest"
  },
  "dependencies": {
    "lit": "^3.2.0",
    "home-assistant-js-websocket": "^9.3.0"
  },
  "devDependencies": {
    "@rollup/plugin-node-resolve": "^15.2.0",
    "@rollup/plugin-typescript": "^12.1.0",
    "@rollup/plugin-terser": "^0.4.4",
    "rollup": "^4.20.0",
    "tslib": "^2.6.0",
    "typescript": "^5.5.0",
    "@types/node": "^20.0.0",
    "vitest": "^2.0.0",
    "@vitest/browser": "^2.0.0",
    "jsdom": "^25.0.0",
    "@open-wc/testing-helpers": "^3.0.0",
    "playwright": "^1.48.0"
  }
}
```

Version floors are conservative (lowest versions known to work against the current HA frontend at time of writing). `home-assistant-js-websocket` is a dev-time type aid — the real `HomeAssistant` object is injected by the parent card host at runtime — but bundling its types lets us stay honest about the shape of `hass.callWS`, `hass.callService`, and `hass.connection.subscribeMessage`. The actual runtime code it contributes is tiny and tree-shakes.

### `frontend/tsconfig.json` — proposed

```json
{
  "compilerOptions": {
    "target": "es2022",
    "module": "es2022",
    "moduleResolution": "bundler",
    "lib": ["es2022", "dom", "dom.iterable"],
    "strict": true,
    "noImplicitAny": true,
    "strictNullChecks": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "experimentalDecorators": true,
    "useDefineForClassFields": false,
    "forceConsistentCasingInFileNames": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "isolatedModules": true,
    "declaration": false,
    "sourceMap": true
  },
  "include": ["src/**/*.ts"],
  "exclude": ["node_modules", "dist", "tests"]
}
```

`useDefineForClassFields: false` is required for Lit 3 decorators to work correctly. `experimentalDecorators: true` keeps us on the TC39 stage-2 decorator path that Lit 3 supports today (Lit 3 added stage-3 support too, but sticking with the one that matches `lit` 3.2's docs is the safer choice).

### `frontend/rollup.config.js` — shape

```js
import resolve from '@rollup/plugin-node-resolve';
import typescript from '@rollup/plugin-typescript';
import terser from '@rollup/plugin-terser';

export default {
  input: 'src/splitsmart-card.ts',
  output: {
    file: '../custom_components/splitsmart/frontend/splitsmart-card.js',
    format: 'es',
    sourcemap: true,
    inlineDynamicImports: true,
  },
  plugins: [
    resolve({ browser: true }),
    typescript({ tsconfig: './tsconfig.json' }),
    process.env.NODE_ENV === 'production' && terser({
      format: { comments: false },
      compress: { passes: 2 },
    }),
  ].filter(Boolean),
  external: [],  // Lit must bundle; home-assistant host injects nothing.
};
```

Output filename matches SPEC §5: `custom_components/splitsmart/frontend/splitsmart-card.js`. Sourcemaps are written next to the bundle (`splitsmart-card.js.map`). We do **not** split the bundle — a single ES module is what HA's custom-card loader consumes.

### Commit vs release artifact — **the decision**

**Recommendation: gitignore the built bundle; CI publishes it as a release artifact.** Reasoning:

1. **Diff noise.** A minified ES module is effectively a binary from a reviewer's perspective. Committing it makes every frontend PR double in size and hides the real change in a ~100 KB noise patch. Source-only PRs are actually reviewable.
2. **Race conditions are real.** Two contributors (or one contributor on two machines) produce byte-different bundles for identical source because of Rollup's timestamp-embedding plugins, terser's non-determinism across node versions, and tsc's compiler cache. Committed bundles become a constant merge-conflict point that adds zero information.
3. **HACS expects a release artifact anyway.** SPEC §18 already declares `zip_release: true` with `filename: splitsmart.zip`. The release workflow has to build and package the bundle — committing the same bundle is duplicated work with the added cost of drift.
4. **Dev-loop friction is the counter-argument.** When a developer clones the repo and runs the integration locally (without HACS), they need the bundle on disk for HA to serve it. This is solvable: (a) `dev.sh` (per CLAUDE.md §"Build and run locally") runs `npm install && npm run build` before symlinking the component; (b) a clear "run `npm run build` before first use" note in README.md. Both are cheap.
5. **The tagged-release path stays clean.** On tag push, `.github/workflows/release.yml` runs `npm ci && npm run build` against the pinned `package-lock.json`, zips `custom_components/splitsmart/` (bundle now included because the build just produced it), uploads the zip as a GitHub Release asset. HACS consumes that zip. End users never see the unbuilt source; they get a bundle that was built reproducibly from the tagged commit.

Concretely, add to `.gitignore`:

```
# Built card bundle — produced by frontend/; shipped via GitHub Releases, not committed.
custom_components/splitsmart/frontend/splitsmart-card.js
custom_components/splitsmart/frontend/splitsmart-card.js.map

# Frontend dev artifacts
frontend/node_modules/
frontend/dist/
```

The directory `custom_components/splitsmart/frontend/` itself stays tracked via a `.gitkeep` so the integration's `async_register_static_paths` target path exists at clone time — otherwise a clean install without running the frontend build would fail at integration startup with a stat error.

### Bundle size budget
**150 KB minified** (before gzip), enforced in CI. The test-job step after `npm run build` measures the output and fails the job if `splitsmart-card.js` exceeds 150 KB. Lit 3 core is ~20 KB, `home-assistant-js-websocket` contributes near-zero runtime, our hand-rolled components should land well under the budget for M2 scope. The budget is intentionally generous to avoid penalising M4/M5 growth without re-examining the ceiling.

### CI workflow sketch

- `.github/workflows/test.yml` (existing, add frontend job): `cd frontend && npm ci && npm run typecheck && npm run test && npm run build` — build step catches regressions that typecheck misses (e.g. a missing dependency of Rollup itself). Final step asserts `$(wc -c < ../custom_components/splitsmart/frontend/splitsmart-card.js) -le 153600`.
- `.github/workflows/release.yml` (new in M2): on `push: tags: ['v*']`, checkout, `npm ci && npm run build` with `NODE_ENV=production`, zip `custom_components/splitsmart/` into `splitsmart.zip`, attach to the GitHub Release. HACS picks it up per SPEC §18. Tag naming: pre-1.0 milestones use `v0.1.0-m<n>` (M2 ships as `v0.1.0-m2`); the first HACS-visible release in M7 is `v0.1.0`.

---

## 3. Serving and registration

### Serving the bundle

In `custom_components/splitsmart/__init__.py`, on `async_setup_entry` (only once per HA instance — guarded by a flag on `hass.data[DOMAIN]`), register two static paths — the bundle and the font directory:

```python
from homeassistant.components.http import StaticPathConfig

STATIC_URL = "/splitsmart-static"
BUNDLE_FILE = "splitsmart-card.js"
FONTS_DIR = "fonts"

frontend_dir = Path(__file__).parent / "frontend"
await hass.http.async_register_static_paths([
    StaticPathConfig(
        url_path=f"{STATIC_URL}/{BUNDLE_FILE}",
        path=str(frontend_dir / BUNDLE_FILE),
        cache_headers=False,  # we version via query string instead
    ),
    StaticPathConfig(
        url_path=f"{STATIC_URL}/{FONTS_DIR}",
        path=str(frontend_dir / FONTS_DIR),
        cache_headers=True,  # fonts are immutable, long-cache them
    ),
])
```

Bundle URL the browser fetches: `https://<ha>/splitsmart-static/splitsmart-card.js`.
Font URLs: `https://<ha>/splitsmart-static/fonts/DMSans-{400,500,600,700}.woff2`, `https://<ha>/splitsmart-static/fonts/DMMono-{400,500}.woff2`.

### Multiple card instances
Multiple `<splitsmart-card>` instances on different dashboards (or on the same dashboard) are supported and isolated — each subscribes to the websocket independently, each maintains its own in-memory expense list. The backend config entry stays single-instance-guarded; only the card front-end allows repetition.

### Cache-busting
Include the integration version in the registered resource URL as a query string: `/splitsmart-static/splitsmart-card.js?v={INTEGRATION_VERSION}`. `INTEGRATION_VERSION` is read from `manifest.json` at startup. When we bump the version the browser drops its cached copy.

### Auto-registration as a Lovelace resource

`lovelace` uses its own storage mechanism. Reading / writing it from an integration is supported but underdocumented. The working pattern (confirmed against current HA source) is to use `hass.data["lovelace"].resources` (when the Lovelace collection is in storage mode) and append a module resource, then persist.

Pseudocode that handles both storage modes:

```python
async def _async_register_frontend_resource(hass: HomeAssistant, version: str) -> None:
    url = f"{STATIC_URL}/{BUNDLE_FILE}?v={version}"

    # Only storage-mode Lovelace supports programmatic resource registration.
    # YAML-mode users add the resource themselves; we log an INFO with the URL
    # and the one-line snippet they need.
    lovelace = hass.data.get("lovelace")
    if lovelace is None or lovelace.mode != "storage":
        _LOGGER.info(
            "Lovelace is in YAML mode; add this resource manually:\n"
            "  - url: %s\n    type: module",
            url,
        )
        return

    resources = lovelace.resources
    await resources.async_load()
    # Skip if our URL (ignoring ?v= suffix) is already registered.
    for item in resources.async_items():
        if item["url"].split("?")[0] == f"{STATIC_URL}/{BUNDLE_FILE}":
            # Update the version query so old-bundle caches flush.
            if item["url"] != url:
                await resources.async_update_item(item["id"], {"res_type": "module", "url": url})
            return
    await resources.async_create_item({"res_type": "module", "url": url})
```

Called once on the first `async_setup_entry`; guarded on `hass.data[DOMAIN]["_resource_registered"]` so reloads don't add duplicates.

### What the user does to get the card on a dashboard

After the integration is set up:

1. The resource is auto-registered (storage-mode Lovelace). No manual Resources step.
2. User opens any dashboard → Edit → Add Card → "Manual" → paste:
   ```yaml
   type: custom:splitsmart-card
   ```
   Or, if we ship a YAML snippet in README, they copy that.
3. Card renders.

On YAML-mode Lovelace (advanced users), they add the resource manually; the integration logs the exact snippet at INFO on first load so they can find it in `home-assistant.log`.

### What we don't do in M2
- A full card picker entry (the card-type gallery in Lovelace's "Add Card" dialog). Contributing to the dialog requires a separate registration via the `custom_card` global window hook; we set that hook inside `splitsmart-card.ts` on module load so the card does show up in the gallery, but the title/description/preview on the gallery entry is minimal ("Splitsmart") in M2 — full preview artwork comes in M7 polish.

---

## 4. Data flow

The card must react to state changes from anywhere (mobile companion, Developer Tools, another household member's session) within a second of the write, without polling or page reloads.

### Primitives HA gives us
1. **`hass.states`** — reactive snapshot of all entity states. A card re-renders on every `hass-changed` event via Lit's reactive properties on `this.hass`.
2. **`hass.callWS({type: ...})`** — one-shot websocket command.
3. **`hass.connection.subscribeMessage(cb, {type: ...})`** — server-push subscription keyed by a custom websocket command type.
4. **`hass.callService(domain, service, data, {return_response: true})`** — fire a service and optionally get the return value.

### Data the card needs

| Data | Where it lives in M1 | How the card reads it in M2 |
|---|---|---|
| Net balance per user | `sensor.splitsmart_balance_<user>` | `hass.states` — reactive, zero extra plumbing |
| Pairwise debt | `per_partner` attribute on balance sensor | `hass.states` |
| Monthly spend per user | `sensor.splitsmart_spending_<user>_month` | `hass.states` |
| Household monthly total | `sensor.splitsmart_spending_total_month` | `hass.states` |
| Most recent expense (id/desc/amount) | `sensor.splitsmart_last_expense` | `hass.states` (sufficient for Home's "last expense" tile) |
| Full expense list (Ledger view) | JSONL on disk, materialised by coordinator | **New websocket command `splitsmart/list_expenses`** |
| Full settlement list | Coordinator | **New websocket command `splitsmart/list_settlements`** |
| Expense by id (Detail sheet) | Coordinator | Subset of `splitsmart/list_expenses` by id, no separate command |
| Participants, categories, home_currency, named_splits | Config entry | **New websocket command `splitsmart/get_config`** (one-shot on card mount) |

### Why a websocket command, not a sensor, for the expense list
An expense list of 500-5000 rows as a sensor attribute is a bad idea: HA's state-change events recorder-write every attribute; attributes have size limits and show up in logbook / history noise. Sensors are right for "one scalar value that changes sometimes"; websocket commands are right for "a collection you read on demand". This matches the pattern CLAUDE.md already references (`/api/splitsmart/*` aiohttp views for uploads; websocket commands are the complementary read primitive).

### The two websocket commands

**`splitsmart/list_expenses`**

Request: `{type: "splitsmart/list_expenses", month?: "2026-04", category?: "Groceries", paid_by?: "user_abc123", since_id?: "ex_..."}`

Response (one-shot): `{version: 1, expenses: [...], settlements: [...], total: 237}` — both lists in one round-trip because the Ledger view shows settlements inline between expense rows. Pagination deferred to M7 if we even need it; at couple scale an unfiltered 5-year list is ~500 rows and fits in one message.

### Envelope versioning
Every websocket response (and every subscription delta message) includes `version: 1` at the top level. When the card's contract with the backend needs to evolve in a breaking way (e.g. new required fields, schema shape changes), we bump to `version: 2` and the server sends the matching shape — older cards fail fast on version mismatch rather than silently reading the wrong fields. This costs 12 bytes per message and buys us forward compatibility for free.

The `since_id` filter is for the subscription path (see below), not an end-user filter.

**`splitsmart/list_expenses/subscribe`** (pattern: use `async_register_command` with a subscription handler)

Long-lived subscription. On the server side, the command handler registers a listener with the coordinator's `async_add_listener(cb)` hook that `DataUpdateCoordinator` already gives us. Whenever `coordinator.async_note_write()` fires, the subscription pushes a `{version: 1, added: [...], updated: [...], deleted: [id, ...]}` delta message. On unsubscribe, the listener is removed.

The card subscribes on mount, keeps a local in-memory expense list, and applies deltas as they arrive. This guarantees the "two devices updating within one second" requirement: the same coordinator that services the write pushes to every subscribed client.

**`splitsmart/get_config`**

Request: `{type: "splitsmart/get_config"}`

Response: `{version: 1, participants: [{user_id, display_name, active: bool}, ...], home_currency, categories, named_splits, current_user_id}`.

One-shot on card mount. `current_user_id` is resolved from `connection.user.id` server-side — the card needs it to default "paid_by" to the current user and to decide which balance sensor is "me". `active: false` flags participants who have been removed via Reconfigure but still appear in historical expenses — the card renders them with "(former participant)" and a 60%-opacity avatar, and excludes them from `paid_by` / `from_user` / `to_user` dropdowns on new entries while keeping them visible in historical views.

### Writes

All writes use `hass.callService("splitsmart", "add_expense" | "edit_expense" | "delete_expense" | "add_settlement" | "edit_settlement" | "delete_settlement", data, {return_response: true})`. Services already exist from M1. Return values contain `{id: "ex_..."}`.

The card does **not** optimistically update its local expense list on write. It waits for the subscription delta to arrive. This is deliberate: the coordinator is the source of truth, and an optimistic update would have to be reconciled on delta arrival anyway. At single-digit-ms latency over a LAN websocket, the lag is invisible. **Revisit in M7** if users on Nabu Casa Cloud (where WAN round-trip can add 100-300ms) report perceived lag; optimistic-with-rollback is the straightforward upgrade if measurements warrant it.

### Backend: what M2 adds to Python

Minimum set:
- `custom_components/splitsmart/websocket_api.py` — new module. Registers the three websocket commands on `async_setup` (not per-entry; one per HA instance). Each handler resolves the entry from `hass.data[DOMAIN]` (there's only one entry since the config flow is single-instance-guarded). Each handler enforces participant authorisation on `connection.user.id` against `entry.data[CONF_PARTICIPANTS]` — non-participants get `permission_denied`.
- `__init__.py` — on first entry setup, call `async_register_websocket_commands(hass)` once (guarded).

### State subscription trade-off, documented

Small reactive values (balances, pending count, FX health) **stay as sensors.** They benefit from being visible to every HA surface (automations, voice, mobile companion glances, Lovelace statistic cards), they survive restart via the recorder, and the card gets them for free through `hass.states`.

Collection reads (expense list, settlement list, eventually the staging queue) **are websocket commands with subscriptions.** They are too large to be sensor attributes, they don't make sense in automations, and they need structured filters (month, category, paid_by) that don't translate to entity state.

This keeps the right data at the right layer and avoids the trap of inflating sensor attribute dicts into a second data model.

---

## 5. Component architecture

### File layout under `frontend/src/`

```
frontend/src/
├── splitsmart-card.ts           # <splitsmart-card> — top level, owns hass, owns router
├── router.ts                    # Hash-backed route parser + view registry
├── api.ts                       # Thin wrapper over hass.callWS / callService
├── types.ts                     # Shared TS types (Expense, Settlement, Split, ...)
├── styles.ts                    # Global CSS variables, typography reset, shared mixins
├── views/
│   ├── home-view.ts             # <ss-home-view>
│   ├── ledger-view.ts           # <ss-ledger-view>
│   ├── add-expense-view.ts      # <ss-add-expense-view>
│   ├── settle-up-view.ts        # <ss-settle-up-view>
│   └── detail-sheet.ts          # <ss-detail-sheet> (modal, not a route — overlay on any view)
├── components/
│   ├── amount-input.ts          # <ss-amount-input> — currency-aware number input
│   ├── category-picker.ts       # <ss-category-picker> — single-select dropdown
│   ├── split-picker.ts          # <ss-split-picker> — methods + share grid
│   ├── allocation-editor.ts     # <ss-allocation-editor> — multi-row amount/% allocator
│   ├── share-grid.ts            # <ss-share-grid> — N-user share inputs for one split
│   ├── row-card.ts              # <ss-row-card> — single expense row with description + amount
│   ├── user-avatar.ts           # <ss-user-avatar> — circle with initials/colour
│   ├── balance-strip.ts         # <ss-balance-strip> — per-user balance badges
│   ├── icon.ts                  # <ss-icon> — wraps ha-icon for our icon set
│   ├── button.ts                # <ss-button> — primary/secondary/destructive
│   ├── modal.ts                 # <ss-modal> — full-screen sheet with back/close
│   ├── filter-chip.ts           # <ss-filter-chip> — selected/unselected pill
│   ├── empty-state.ts           # <ss-empty-state> — illustration + copy + CTA
│   └── placeholder-tile.ts      # <ss-placeholder-tile> — "Coming in M<n>" tile for Home
└── util/
    ├── currency.ts              # format(amount, currency_code, locale) — uses Intl
    ├── date.ts                  # relative date ("Today", "Yesterday"), month picker helpers
    └── decimal.ts               # thin Decimal-like ops (avoid big.js for a 20KB save)
```

### State ownership

- `<splitsmart-card>` (root):
  - `@property({attribute: false}) hass: HomeAssistant` — injected by Lovelace, re-bound on every state change.
  - `@state() private _config: SplitsmartConfig | null` — fetched once via `splitsmart/get_config`.
  - `@state() private _expenses: Expense[]` — hydrated via `splitsmart/list_expenses`, kept fresh by the subscription. The root owns this so every view gets the same in-memory copy; no duplicate fetches.
  - `@state() private _settlements: Settlement[]` — same.
  - `@state() private _route: Route` — from the router.
  - `@state() private _openDetailId: string | null` — which expense is open in the Detail sheet (null = closed). Kept at root because the Detail sheet overlays any route.

- Each view component (`<ss-home-view>`, `<ss-ledger-view>`, etc.) is **stateless** with respect to data: it takes `expenses`, `settlements`, `config`, `hass` as reactive properties from the root and emits custom events (`ss-navigate`, `ss-open-detail`, `ss-request-add`) upward.

- Form views (`<ss-add-expense-view>`, `<ss-settle-up-view>`, Detail edit mode) own their own local form state via `@state()`. On submit they call `api.addExpense(...)` / `api.editExpense(...)` and navigate back; they don't write into the root's cached expense list — the subscription delta does.

### Routing

**Pick: hash-based router, owned by the root card.** Arguments for each option:

- **Hash (`#ledger`, `#add`, `#expense/ex_01J9X`):** survives deep-linking, browser back button works, mobile companion deep links work (`/lovelace/<view>#add`), no dependency, 50 lines of code. No conflict with Lovelace's own URL path which lives above the `#`.
- **Reactive property (view name as string):** simplest code but breaks back button and deep links. A card sitting on a sidebar dashboard wants "tap Back to get out of the Add form" to work — hash gives us that for free.
- **Router component:** unnecessary abstraction for 5 routes. Lit has no official router and pulling in `lit-router` or equivalent is more moving parts.

Hash format: `#<view>` or `#<view>/<param>`. Routes:
- `#home` (default when hash is empty)
- `#ledger`
- `#ledger?month=2026-04&category=Groceries` (query after `?`)
- `#add`
- `#settle`
- `#expense/ex_01J9X` — opens Detail sheet for that expense; navigating away returns to prior route

The router is ~60 lines: `window.addEventListener('hashchange', ...)`, parse, set `this._route`, each view listens for `ss-navigate` events and forwards to `location.hash = ...`.

### Primitives consumer check

Every primitive must be used by ≥ 2 views or it's premature. Audit:

| Primitive | Consumers |
|---|---|
| `<ss-amount-input>` | Add expense, Settle up, Detail (edit mode) — ✓ |
| `<ss-category-picker>` | Add expense (single + multi allocation), Ledger filter, Detail edit — ✓ |
| `<ss-split-picker>` | Add expense (uniform + per-category), Detail edit — ✓ |
| `<ss-allocation-editor>` | Add expense (only when multi-category toggled), Detail edit — ✓ |
| `<ss-share-grid>` | Used inside `<ss-split-picker>`, also Settle up for from/to (N=2 degenerates to a pair picker; justifies its own primitive). Consumers: split picker, settle-up — ✓ |
| `<ss-row-card>` | Ledger list, Home "last expense" tile (compact variant via `variant` prop) — ✓ |
| `<ss-user-avatar>` | Balance strip, Row card (paid-by badge), Share grid, Settle up — ✓ |
| `<ss-balance-strip>` | Home, Detail sheet (optional pairwise breakdown) — ✓ |
| `<ss-icon>` | Everywhere — ✓ |
| `<ss-button>` | Everywhere — ✓ |
| `<ss-modal>` | Detail sheet, future Import wizard (M3) — only one M2 consumer, but is fundamental infrastructure and used at least 2x even in M2 (Detail for view, Detail for edit mode) — ✓ |
| `<ss-filter-chip>` | Ledger filters (month + category) — only one view uses it in M2. **Push back: fold into Ledger as a private helper.** Can extract in M5 when Rules or Staging reuses filter UI. |
| `<ss-empty-state>` | Ledger (no expenses), Home (first-install and "you're all square" variants) — ✓ |
| `<ss-placeholder-tile>` | Home (staging placeholder), potentially Home (import placeholder, rules placeholder) — ✓ |

Decision: drop `<ss-filter-chip>` as a separate primitive for M2; Ledger owns the chip markup inline. A `// TODO(M5): extract to components/filter-chip.ts when Staging and Rules views reuse the pill-filter pattern` comment sits next to the inline markup in `ledger-view.ts` to flag the extraction point.

### Event flow

Lit's `@customEvent` pattern, all events bubble + compose:
- `ss-navigate` — `{route: string}` — root listens, sets `location.hash`.
- `ss-open-detail` — `{expense_id: string}` — root opens Detail sheet.
- `ss-close-detail` — root closes Detail sheet.
- `ss-request-add` — shortcut from Home; root sets hash to `#add`.
- `ss-toast` — `{message: string, action?: {label, cb}}` — root renders a global toast. Used for 5-second undo toasts after actions.

---

## 6. Design system

### HA theme variables we consume
Every value uses `var(--x, <fallback>)`. Fallbacks tuned to look reasonable on the default HA theme when the user has not configured any custom theme.

| CSS variable | Fallback | Used for |
|---|---|---|
| `--primary-text-color` | `#1a1a1a` | Body text, headers |
| `--secondary-text-color` | `#5a5a5a` | Labels, captions, metadata |
| `--card-background-color` | `#ffffff` | Primary card surface |
| `--secondary-background-color` | `#f5f5f5` | Subtle row striping, disabled bg |
| `--divider-color` | `#e0e0e0` | Hairlines between rows, form sections |
| `--primary-color` | `#03a9f4` | Non-semantic accent (links, toggles) |
| `--accent-color` | `#5b9f65` | Splitsmart brand accent |
| `--error-color` | `#db4437` | Delete buttons, validation errors |
| `--warning-color` | `#ffa600` | Amber "amount drifted" indicator |
| `--success-color` | `#43a047` | Green "balanced" tick |
| `--state-icon-color` | `--primary-color` | Icon tints that want to match theme tone |
| `--paper-item-icon-color` | `--state-icon-color` | `<ha-icon>` wrapped elements |
| `--mdc-theme-primary` | `--primary-color` | For any `<mwc-*>` that sneaks in |

We also expose three **Splitsmart-owned** tokens that downstream users can override from their theme, prefixed `--ss-`:
- `--ss-credit-color` (fallback `#2e7d32`) — green, money owed *to* the current user.
- `--ss-debit-color` (fallback `#c62828`) — red, money the current user owes.
- `--ss-accent-color` (fallback `var(--accent-color, #5b9f65)`) — Splitsmart brand; defaults to HA accent so the card matches user's theme unless they want to override.

### Colour-blind accessibility

Green / red are never the only signal.
- Credit balances carry an up-arrow icon AND the green colour.
- Debit balances carry a down-arrow icon AND the red colour.
- Toast success carries a tick icon; toast error carries an exclamation icon.
- The live remainder indicator on Add-expense shows text (`£0.00 remaining ✓` / `£2.34 over`) alongside colour.

### Typography tokens (DM Sans / DM Mono)

Fonts are **self-hosted** under `custom_components/splitsmart/frontend/fonts/` as woff2 (latin subset, hinted), served from `/splitsmart-static/fonts/`. No request to `fonts.googleapis.com`, so offline installs, pi-holed networks and corporate-proxy HA deployments all work.

Weights shipped:
- `DMSans-400.woff2`, `DMSans-500.woff2`, `DMSans-600.woff2`, `DMSans-700.woff2`
- `DMMono-400.woff2`, `DMMono-500.woff2`

Approximate footprint: ~95 KB total across all six woff2 files (latin subset only). `@font-face` declarations live in `styles.ts`:

```css
@font-face {
  font-family: 'DM Sans';
  src: url('/splitsmart-static/fonts/DMSans-400.woff2') format('woff2');
  font-weight: 400;
  font-style: normal;
  font-display: swap;
}
/* ...repeat for 500, 600, 700, DM Mono 400/500 */
```

`font-display: swap` avoids FOIT; the browser falls back to the system sans-serif while fetching. Because we set long cache headers on the font static path, the second paint reuses the cached files.

### Locale

`Intl.NumberFormat` and relative-date helpers read the locale from `this.hass.locale?.language ?? 'en-GB'`. If the HA instance has a locale configured, we use it; otherwise we fall back to `en-GB` (matches the primary target deployment). We do **not** add a separate `locale` field to the config flow in M2 — HA already has this concept, and a card-local duplicate would drift.

| Token | Family | Size | Weight | Line height | Use |
|---|---|---|---|---|---|
| `--ss-text-display` | DM Sans | 28px | 600 | 1.2 | Balance hero on Home |
| `--ss-text-title` | DM Sans | 20px | 600 | 1.3 | View titles |
| `--ss-text-body` | DM Sans | 16px | 400 | 1.5 | Body copy, labels |
| `--ss-text-button` | DM Sans | 15px | 500 | 1.4 | Buttons, chips |
| `--ss-text-caption` | DM Sans | 13px | 400 | 1.4 | Metadata, hints |
| `--ss-text-mono-amount` | DM Mono | 16px | 500 | 1.3 | Amounts in rows |
| `--ss-text-mono-display` | DM Mono | 28px | 500 | 1.2 | Hero amounts |
| `--ss-text-mono-caption` | DM Mono | 13px | 400 | 1.4 | Dates, small figures |

All `tabular-nums` enabled on mono tokens (`font-variant-numeric: tabular-nums`).

### Spacing scale
4-step geometric-ish scale: `4, 8, 12, 16, 24, 32, 48, 64` px. Exposed as CSS variables `--ss-space-1` through `--ss-space-8`. Nothing in the card uses raw pixel values for spacing.

### Motion tokens
- `--ss-duration-fast`: 120ms — micro-interactions (button press, toggle).
- `--ss-duration-base`: 180ms — sheet in/out, chip toggle, expand/collapse.
- `--ss-duration-slow`: 260ms — Detail sheet open/close.
- `--ss-easing-standard`: `cubic-bezier(0.2, 0, 0, 1)` (standard Material easing).
- `--ss-easing-enter`: `cubic-bezier(0, 0, 0, 1)` — decelerate.
- `--ss-easing-exit`: `cubic-bezier(0.4, 0, 1, 1)` — accelerate.
- No spring-based motion, per SPEC §15 ("No bouncy springs").

### Touch target minimum
44×44 CSS px throughout, per SPEC §15. Enforced via:
- `<ss-button>` base style sets `min-height: 44px; min-width: 44px`.
- `<ss-filter-chip>` (used inline in Ledger): `min-height: 36px` but with `padding: 8px 12px` and the entire container tappable, giving an effective hit area ≥ 44px; validated manually in QA.
- Iconic buttons (close, back, kebab) wrap their icon in a 44×44 transparent hit box.

### Dark mode
HA toggles `--card-background-color`, `--primary-text-color`, etc. We inherit automatically. We explicitly test the card against HA's Backend theme (default dark) in manual QA. The `--ss-credit-color` / `--ss-debit-color` fallbacks are dark-mode legible (WCAG AA on the default dark card bg of `#1c1c1c`); confirmed via contrast check.

### Iconography
- HA's built-in `<ha-icon>` plus MDI icon names. No custom SVG icon set in M2 (M7 polish territory).
- Icon set used: `mdi:plus-circle` (add), `mdi:swap-horizontal` (settle), `mdi:playlist-check` (ledger), `mdi:arrow-up` / `mdi:arrow-down` (credit/debit), `mdi:check-circle` (balanced), `mdi:alert` (drifted), `mdi:close` (dismiss), `mdi:chevron-left` (back), `mdi:dots-vertical` (kebab), `mdi:clock-outline` (coming-soon placeholder).

---

## 7. Test plan

### Vitest coverage (automated)

Pure logic and form validation. All tests live in `frontend/tests/`.

| File | What it covers |
|---|---|
| `router.test.ts` | Hash parse: `#home`, `#ledger?month=2026-04&category=Groceries`, `#expense/ex_01J9X`, empty hash → home, malformed hash → home, navigation side-effect updates `location.hash`. |
| `util/currency.test.ts` | `format(82.40, 'GBP', 'en-GB')` → `£82.40`; `format(82.4, 'GBP')` → `£82.40` (pad to 2dp); `format(1234567.89, 'GBP')` → `£1,234,567.89`; `format(-45.45, 'GBP')` → `-£45.45` with minus prefix; edge cases for EUR/USD. |
| `util/date.test.ts` | Relative date: today, yesterday, this week ("Tuesday"), this month ("15 Apr"), older ("15 Apr 2025"). Month picker yields current + last-12 months ordered reverse-chrono. |
| `util/decimal.test.ts` | Add, subtract, round-to-2dp, sum-of-array, comparison with `< 1p` drift tolerance matching backend. |
| `components/amount-input.test.ts` | Raw string → numeric coerce; rejects non-numeric; emits `ss-change` with Decimal-safe value; handles empty string (→ null); paste of `"1,234.56"` normalises. |
| `components/split-picker.test.ts` | Default 50/50 for 2-user config; switching method=shares recomputes; `exact` mode validates sum; all-zero values flagged; N=3 renders 3 rows. |
| `components/allocation-editor.test.ts` | Sum validation (amber when drifted, green when balanced); percentage mode redistributes rounding to last row; amount mode preserves typed values; adding / removing rows keeps total consistent; emits `ss-valid` / `ss-invalid`. |
| `views/add-expense-view.test.ts` | Uniform-split defaults: single split picker visible, per-category split collapsed. Toggle "different split per category" expands per-row pickers. Save disabled until sum balances AND every split passes `validate_split` equivalent logic. Cancel navigates to `#ledger`. Submits the expected payload shape to `api.addExpense`. |
| `views/settle-up-view.test.ts` | Pre-fills suggested amount from passed pairwise debt; from/to picker excludes same-user; submit calls `api.addSettlement`. |
| `views/ledger-view.test.ts` | Renders rows in reverse-chrono date order, groups by date header; filter chip for month narrows correctly; category chip narrows correctly; empty result shows `<ss-empty-state>`. |
| `api.test.ts` | Mocks `hass.callWS` and `hass.callService`; verifies each API helper posts the right payload shape; `subscribeExpenses` registers a handler and un-registers on disposal. |

Target: 100% line coverage on `util/*`, `router.ts`, `api.ts`. Best-effort on component tests — enough to catch regressions in form validation, not to gate visual changes.

### Manual QA on the Pi — `tests/MANUAL_QA_M2.md`

Produced when M2 is done. Checklist covers:

1. **First paint.** Card mounts on a fresh dashboard. Home renders with current balance from M1 data. No console errors. Bundle loads from `/splitsmart-static/splitsmart-card.js?v=<version>`.
2. **Theme.** Light theme, default dark theme, a custom theme the user supplies — all three look correct (no hardcoded colours bleeding through).
3. **Responsive.** Card at full width on desktop; card in a Lovelace column at ~400px; card on mobile Safari (iPhone) at ~390px; card on Android Chrome. Touch targets are ≥ 44×44.
4. **Fonts.** DM Sans + DM Mono actually load (network tab shows 200s from Google Fonts); tabular figures line up in the Ledger amounts column.
5. **Home → Add → save.** Add a £40 Waitrose expense, uniform 50/50, confirm balance sensor updates in <1s on this device AND on a second browser tab mounted on the same HA.
6. **Multi-category add.** Add an £82.40 Tesco shop with Groceries £55.20 / Household £18.70 / Alcohol £8.50 split per SPEC §9.3. Verify row card shows `£82.40`, Detail sheet shows three allocations with correct totals, balance sensor matches SPEC's £36.95 figure.
7. **Ledger filter.** Set month = current month, category = Groceries; only matching rows visible. Clear filter; all rows return.
8. **Detail edit.** Open a row, tap Edit, change description, Save → sensor description updates, prior expense id is tombstoned (check via `/config/splitsmart/shared/tombstones.jsonl`), new id appears.
9. **Detail delete.** Delete a row; confirm dialog fires; row removed from Ledger; balance recalculates.
10. **Settle up.** Pre-fills suggested amount matching the Home balance headline; submit; balance goes to £0.00; Ledger shows the settlement inline between expense rows on that date.
11. **Mobile companion app.** Open the card in HA Companion (iOS + Android); repeat a subset of flows; verify no layout breakage.
12. **Two-device realtime.** Open the card on desktop and mobile simultaneously; add an expense from mobile; desktop updates within 1s without refresh.
13. **YAML-mode Lovelace fallback.** Temporarily switch Lovelace to YAML mode, confirm integration logs the INFO with the resource snippet, add the snippet, reload, confirm card renders.
14. **Placeholder tiles.** Home shows a "Pending review — coming in M5" tile; it's clearly labelled as upcoming and not interactive beyond a subtle hover state.

### Empty-state copy (two distinct states)

Home view renders one of two empty states depending on ledger history:

- **First install — no expenses ever added.** Headline "No expenses yet", caption "Add your first expense to get started", primary CTA "Add expense", secondary CTA "Settle up".
- **All square — expenses exist but current balances are all zero.** Headline "You're all square", caption "Last settled <relative date> with <counterparty>", same CTAs. The caption pulls the most recent settlement from the settlements list.

These are distinct states with distinct copy because "welcome to the app" and "good job, you're paid up" feel very different to a returning user.

### Deliberately NOT tested in M2
- Visual regression (pixel diffs) — deferred to M7 polish. Too much moving design in M2 to pin down a golden screenshot set.
- Cross-browser compatibility beyond "works on current Chromium, current Safari, current Firefox" — IE / legacy Edge / legacy Safari out of scope. Documented in README.
- Accessibility audit (screen readers, WCAG 2.1 AA) — aimed for as a practice target (contrast, semantic HTML, keyboard navigation) but not formally tested with automated tools in M2. Deferred to M7.
- Load testing (5000+ expenses) — deferred to M3 when we can import real statement data. M2 tests with hand-written fixtures of ~50 expenses max.

---

## 8. Decisions

Resolved on 2026-04-21. Each maps to a concrete implementation consequence flagged in-plan above.

1. **Git tag naming.** M2 ships as `v0.1.0-m2`. All pre-HACS milestones stay pre-1.0 (`v0.1.0-m<n>`); the first HACS-visible release in M7 is `v0.1.0`.
2. **Multiple card instances.** Allowed and supported. Backend stays single-entry-guarded; front-end allows repetition — each mount subscribes independently and maintains its own in-memory list.
3. **Card config schema.** One optional field in M2: `view: home | ledger | add | settle` (default `home`) so users can pin a dashboard tile to a specific view. Nothing else.
4. **Card picker preview thumbnail.** Deferred to M7 polish. Register the `custom_card` hook in M2 with a minimal title/description; no preview artwork.
5. **Bundle size budget.** 150 KB minified, enforced in CI via a byte-count check after `npm run build`.
6. **Fonts.** Self-hosted DM Sans (400/500/600/700) + DM Mono (400/500) as woff2 under `/splitsmart-static/fonts/`. No Google Fonts `@import`. Step 2 of the implementation downloads and commits the woff2 files and wires the second static path.
7. **Locale.** `hass.locale?.language ?? 'en-GB'`. No locale field added to the config flow.
8. **Deleted participants.** Flagged as `active: false` in the `get_config` response. Card renders them with "(former participant)" suffix at 60% avatar opacity, excludes them from `paid_by` / `from_user` / `to_user` dropdowns on new entries, keeps them visible in historical views.
9. **Websocket envelope versioning.** `{version: 1, ...}` included from day one in every response and every subscription delta message.
10. **Home placeholder tiles.** Staging only, with a "Coming in M5" badge. Import / Rules / Settings get no M2 Home-screen placeholder (they're reached via their own workflows, not Home tiles).
11. **Settlement Detail sheet.** Minimal view + edit + delete in M2, reusing `<ss-modal>` and the Settle Up form.
12. **Empty-state copy.** Two distinct states on Home — "No expenses yet" + "Add your first expense to get started" on first install; "You're all square" + "Last settled <relative date> with <counterparty>" when balances are zero after use.

## 9. Plan amendments

Non-decisional notes incorporated alongside the decisions:

- **`<ss-filter-chip>` extraction point flagged.** `ledger-view.ts` will carry a `// TODO(M5): extract to components/filter-chip.ts when Staging and Rules reuse the pill-filter pattern` comment next to the inline chip markup, so the extraction is easy to find when M5 arrives.
- **"No optimistic updates" policy is deliberate.** The card waits for subscription deltas before updating local state — documented in §4 with the rationale (single source of truth, no reconciliation logic). **Revisit in M7** if users on Nabu Casa Cloud (where round-trip latency can be 100-300ms) report perceived lag; optimistic-with-rollback is the straightforward upgrade when measurements warrant it.
