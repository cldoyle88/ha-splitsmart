# Import fixtures

Synthetic, anonymised statement exports used by the importer test
suites. Each file mirrors the shape the corresponding bank emits but
contains invented merchants and amounts — no real transactions.

Per CLAUDE.md "Files never to edit", these fixtures are immutable
once committed: tests assert exact parser output so changing a row
would invalidate the assertions. If a new bank ships a new schema,
land a new fixture alongside the existing one.

| Fixture                       | Purpose |
| ----------------------------- | ------- |
| `monzo_classic.csv`           | Monzo preset detection + parse, 10 rows incl. income + transfer |
| `starling_standard.csv`       | Starling preset, GBP account, 10 rows incl. a declined payment |
| `revolut_account.csv`         | Revolut preset with EUR + USD rows to exercise foreign-currency import |
| `splitwise_export.csv`        | Splitwise preset (positive `Cost`), 10 rows with category hints |
| `generic_debit_credit.csv`    | Generic CSV with split debit/credit columns (no preset match) |
| `generic_no_preset.csv`       | Headers no preset matches — forces explicit-mapping path |
| `malformed.csv`               | One row with a non-numeric amount; tests per-row error surfacing |
| `sample.ofx`                  | Minimal OFX 2.x body, no mapping needed |
| `sample.qif`                  | 10 QIF transactions with `!Type:Bank` |
