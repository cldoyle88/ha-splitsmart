# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Initial specification and project scaffolding.
- M1 data plane: component skeleton, config flow (participants, currency, categories), append-only JSONL storage, DataUpdateCoordinator with incremental refresh, pure ledger calculators, six core services (`add_expense`, `add_settlement`, `edit_expense`, `edit_settlement`, `delete_expense`, `delete_settlement`) with `SupportsResponse.OPTIONAL`, and four sensor entities (`balance_<user>`, `spending_<user>_month`, `spending_total_month`, `last_expense`).
- Per-path asyncio locking in `SplitsmartStorage` to prevent concurrent-write corruption on Windows.
- Full unit test coverage for `storage.py` and `ledger.py`; integration tests for coordinator, services, and sensors.
