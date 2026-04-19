# CLAUDE.md

This file is read automatically by Claude Code when working in this repo. It sets project context, conventions and constraints. Keep it concise; SPEC.md has the full specification.

## What this project is

`ha-splitsmart` — a Home Assistant custom integration (HACS-packaged) for splitting household expenses, with a Lit + TypeScript Lovelace custom card, a staging-first import pipeline, and Telegram receipt OCR. Full spec in `SPEC.md`. Read it end-to-end before the first substantive edit.

## What this project is not

- Not a generic finance tracker. Personal (non-shared) expenses are only in staging, never retained.
- Not a cloud service. Everything runs inside HA; only outbound calls are optional FX and optional vision OCR.
- Not a Splitwise clone. The privacy-first staging inbox is the differentiator; preserve it.

## House style

- **English:** British. `organise` not `organize`, `colour` not `color`. Guardian style guide for prose.
- **Punctuation:** no em dashes. Use spaced en dashes (` – `) or parentheses or full stops.
- **No AI clichés:** avoid "delve", "navigate the landscape", "it's important to note", "in today's fast-paced world", "furthermore", "in conclusion".
- **Tone:** direct, concise. Explain the why, not the what, in comments. Assume the reader knows Python and HA.

## Python conventions

- Python 3.12. Type hints required on all new code. `from __future__ import annotations` at the top of every module.
- Async by default. Use `aiofiles` for any file IO; never block the event loop.
- `ruff check` and `ruff format` must pass. Config is in `pyproject.toml`.
- No runtime dependencies beyond what's listed in `custom_components/splitsmart/manifest.json`. If adding one, update the manifest and justify it in the PR.
- Prefer pure functions in `ledger.py`, `rules.py`, `importer/dedup.py`. IO lives in `storage.py` and the services.
- Constants in `const.py`. Never hardcode event names, service names, or config keys inline.
- Log via `_LOGGER = logging.getLogger(__name__)`. No `print`. Log levels: DEBUG for noisy, INFO for lifecycle, WARNING for recoverable, ERROR for user-facing breakage.

## TypeScript conventions

- Strict mode on. `strictNullChecks`, `noImplicitAny`, all the usual. Config in `frontend/tsconfig.json`.
- Lit 3 with decorators. Reactive properties via `@property` / `@state`.
- No external UI libraries. Primitives are hand-rolled in `frontend/src/components/`.
- CSS in `static` / `css` template literals colocated with components. No separate `.css` files except the shared `styles.ts`.
- Pull HA theme values through CSS variables. Never hardcode colours except as fallbacks in `var(--x, #fallback)`.

## Storage and data integrity

- **Append-only everywhere.** Never rewrite a JSONL file in place. Edits and deletes are tombstones appended to `shared/tombstones.jsonl`.
- Every entry has an ID. Use ULIDs (`from ulid import ULID`). Prefix by type: `ex_` for expenses, `st_` for staging, `tb_` for tombstones, `sl_` for settlements, `r_` for rules.
- Never write outside `/config/splitsmart/`. Validate this on startup; refuse to run if the path falls under `/config/www/`.
- Timestamps are ISO-8601 with offset, in the HA instance's timezone. `datetime.now(tz=dt.timezone.utc).astimezone()` is fine.
- Money is stored as `float` rounded to 2dp at entry, converted to `Decimal` inside ledger calculations to avoid drift.

## Privacy rules

- Every service handler and HTTP view must check `context.user_id` (or `X-Hass-User` header) against the data being accessed.
- Staging is private to the uploader. Reading another user's staging file via any code path is a security bug.
- Shared ledger is visible to all participants. Tombstones of shared items are visible; tombstones of staging items are not.
- Never log full expense descriptions or amounts at INFO level — they may leak across users via the HA log. DEBUG is fine.

## HA integration conventions

- Use `DataUpdateCoordinator` for shared ledger state. Coordinators live on `hass.data[DOMAIN][entry_id]`.
- Sensors implement `CoordinatorEntity` and pull from the coordinator. No independent IO in sensor classes.
- Services are registered once per integration (not per config entry). Schemas live in `services.yaml` and are validated with `voluptuous`.
- Config flow uses modern patterns: `ConfigFlow`, `OptionsFlowHandler`, `async_step_user`, `async_step_reconfigure`. No YAML-based config.
- HTTP views register under `/api/splitsmart/*` via `hass.http.register_view`. Static files (the card bundle) via `async_register_static_paths` at `/splitsmart-static/`.
- Translations in `translations/en.json`. No hardcoded user-facing strings.

## Testing

- Use `pytest-homeassistant-custom-component`. Fixtures in `tests/conftest.py`.
- Every service gets an integration test that exercises it end-to-end against a tmp path.
- Pure modules (`ledger`, `rules`, `dedup`, `fx`) get exhaustive unit tests.
- Parser tests use real fixture files in `tests/fixtures/` — anonymised samples of Monzo, Starling, Revolut, Splitwise exports.
- Don't test HA internals. Test your own code.

## Git workflow

- Trunk: `main`. PRs from feature branches named `m<n>/<short>` (e.g. `m4/rules-engine`).
- Commits: imperative mood, sentence case, no trailing full stop. "Add multiset dedup" not "Added multiset dedup." or "adds multiset dedup".
- One logical change per commit. Squash noise before pushing.
- PR description: what changed, why, how to test, anything reviewers should know. Reference the milestone in the title: `[M4] Rules engine`.
- Never commit `secrets.yaml`, API keys, or real ledger data. Fixtures must be synthetic or anonymised.

## Build and run locally

- Backend only: `pytest tests/` from repo root.
- Frontend: `cd frontend && npm install && npm run build`. Output lands in `custom_components/splitsmart/frontend/splitsmart-card.js`.
- Full dev loop: mount repo into an HA dev container at `/config/custom_components/splitsmart`, restart HA, test via UI.
- A `dev.sh` script in the repo root does the above in one command. Create it if it doesn't exist.

## When asked to add a feature

1. Check SPEC.md — is it in scope? If it's a v2 item, push back and discuss.
2. Identify which milestone it belongs to. If we haven't reached that milestone yet, flag it.
3. Write the test first where practical.
4. Update SPEC.md if the feature changes the contract (schema, service signature, config key).
5. Update CHANGELOG.md under the `Unreleased` section.

## When something is ambiguous

Don't guess. Ask. The spec covers the shape, not every corner. If a decision would lock in an assumption that's hard to reverse (schema, service name, storage path, privacy boundary), raise it.

## Files to read before the first edit

1. `SPEC.md` — full specification.
2. `README.md` — user-facing intro.
3. The relevant module(s) for the task.
4. The existing tests for those modules.

## Files never to edit

- `.gitignore` without approval.
- `LICENSE`.
- Anything under `tests/fixtures/` (they're snapshots of real import formats; changing them invalidates tests).
- `CHANGELOG.md` entries under a released version. Only `Unreleased` is editable.

## Reference: the author's other HA repo

The garden-cam setup in `github.com/sailorshopuk/home-assistant-config` is worth reading for patterns on JSONL manifests, append-only storage, shell-command / webhook plumbing, and the gallery HTML. We're applying similar ideas at a higher level of polish — custom component + Lit card instead of shell scripts + vanilla HTML.
