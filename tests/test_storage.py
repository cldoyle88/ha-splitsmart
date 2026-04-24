"""Unit tests for storage.py — no HA event loop required."""

from __future__ import annotations

import asyncio
import json
import pathlib

import pytest

# conftest.py loads storage into sys.modules before any test file is imported
from custom_components.splitsmart.storage import (
    SplitsmartStorage,
    new_id,
    validate_root,
)

# ------------------------------------------------------------------ new_id


def test_new_id_prefix():
    id_ = new_id("ex")
    assert id_.startswith("ex_")
    assert len(id_) > 4


def test_new_id_sortable():
    ids = [new_id("ex") for _ in range(10)]
    assert ids == sorted(ids)


def test_new_id_unique():
    ids = {new_id("ex") for _ in range(100)}
    assert len(ids) == 100


# ------------------------------------------------------------------ validate_root


def test_validate_root_accepts_splitsmart(tmp_path: pathlib.Path):
    root = tmp_path / "splitsmart"
    validate_root(root)  # must not raise


def test_validate_root_rejects_www(tmp_path: pathlib.Path):
    # Simulate a path that contains /config/www/
    www = tmp_path / "config" / "www" / "splitsmart"
    with pytest.raises(ValueError, match="www"):
        validate_root(www)


def test_validate_root_rejects_relative():
    with pytest.raises(ValueError, match="absolute"):
        validate_root(pathlib.Path("relative/path"))


# ------------------------------------------------------------------ ensure_layout


@pytest.mark.asyncio
async def test_ensure_layout_creates_dirs(tmp_path: pathlib.Path):
    root = tmp_path / "splitsmart"
    storage = SplitsmartStorage(root)
    await storage.ensure_layout()
    assert (root / "shared").is_dir()
    assert (root / "staging").is_dir()
    assert (root / "receipts" / "incoming").is_dir()
    assert (root / "uploads").is_dir()


@pytest.mark.asyncio
async def test_ensure_layout_is_idempotent(tmp_path: pathlib.Path):
    root = tmp_path / "splitsmart"
    storage = SplitsmartStorage(root)
    await storage.ensure_layout()
    await storage.ensure_layout()  # second call must not raise


# ------------------------------------------------------------------ path helpers


def test_path_helpers(tmp_path: pathlib.Path):
    storage = SplitsmartStorage(tmp_path / "splitsmart")
    assert storage.expenses_path.name == "expenses.jsonl"
    assert storage.settlements_path.name == "settlements.jsonl"
    assert storage.tombstones_path.name == "tombstones.jsonl"
    assert storage.staging_path("user_abc").name == "user_abc.jsonl"
    # Staging paths must be isolated per user
    assert storage.staging_path("user_abc") != storage.staging_path("user_def")

    # M3 additions
    assert storage.uploads_dir.name == "uploads"
    assert storage.uploads_dir == tmp_path / "splitsmart" / "uploads"
    assert storage.mappings_path.name == "mappings.jsonl"
    assert storage.upload_path("abcd-1234", "csv").name == "abcd-1234.csv"
    # Extension normalisation: strip leading dot, lower-case.
    assert storage.upload_path("abcd-1234", ".XLSX").name == "abcd-1234.xlsx"


# ------------------------------------------------------------------ append + read_all


@pytest.mark.asyncio
async def test_append_read_all_roundtrip(tmp_path: pathlib.Path):
    root = tmp_path / "splitsmart"
    storage = SplitsmartStorage(root)
    await storage.ensure_layout()

    records = [{"id": new_id("ex"), "description": f"item {i}"} for i in range(3)]
    for r in records:
        await storage.append(storage.expenses_path, r)

    result = await storage.read_all(storage.expenses_path)
    assert result == records


@pytest.mark.asyncio
async def test_read_all_missing_file_returns_empty(tmp_path: pathlib.Path):
    root = tmp_path / "splitsmart"
    storage = SplitsmartStorage(root)
    await storage.ensure_layout()
    result = await storage.read_all(storage.expenses_path)
    assert result == []


@pytest.mark.asyncio
async def test_append_non_ascii(tmp_path: pathlib.Path):
    root = tmp_path / "splitsmart"
    storage = SplitsmartStorage(root)
    await storage.ensure_layout()

    record = {"id": new_id("ex"), "description": "Café – côté gauche"}  # noqa: RUF001
    await storage.append(storage.expenses_path, record)
    result = await storage.read_all(storage.expenses_path)
    assert result[0]["description"] == record["description"]


@pytest.mark.asyncio
async def test_append_does_not_rewrite(tmp_path: pathlib.Path):
    root = tmp_path / "splitsmart"
    storage = SplitsmartStorage(root)
    await storage.ensure_layout()

    r1 = {"id": new_id("ex"), "description": "first"}
    r2 = {"id": new_id("ex"), "description": "second"}
    await storage.append(storage.expenses_path, r1)
    await storage.append(storage.expenses_path, r2)

    result = await storage.read_all(storage.expenses_path)
    assert len(result) == 2
    assert result[0]["description"] == "first"
    assert result[1]["description"] == "second"


# ------------------------------------------------------------------ read_since


@pytest.mark.asyncio
async def test_read_since_none_returns_all(tmp_path: pathlib.Path):
    root = tmp_path / "splitsmart"
    storage = SplitsmartStorage(root)
    await storage.ensure_layout()

    records = [{"id": new_id("ex"), "v": i} for i in range(3)]
    for r in records:
        await storage.append(storage.expenses_path, r)

    result = await storage.read_since(storage.expenses_path, None)
    assert result == records


@pytest.mark.asyncio
async def test_read_since_returns_records_after_id(tmp_path: pathlib.Path):
    root = tmp_path / "splitsmart"
    storage = SplitsmartStorage(root)
    await storage.ensure_layout()

    records = [{"id": new_id("ex"), "v": i} for i in range(5)]
    for r in records:
        await storage.append(storage.expenses_path, r)

    result = await storage.read_since(storage.expenses_path, records[1]["id"])
    assert result == records[2:]


@pytest.mark.asyncio
async def test_read_since_last_id_returns_empty(tmp_path: pathlib.Path):
    root = tmp_path / "splitsmart"
    storage = SplitsmartStorage(root)
    await storage.ensure_layout()

    records = [{"id": new_id("ex"), "v": i} for i in range(3)]
    for r in records:
        await storage.append(storage.expenses_path, r)

    result = await storage.read_since(storage.expenses_path, records[-1]["id"])
    assert result == []


@pytest.mark.asyncio
async def test_read_since_missing_file_returns_empty(tmp_path: pathlib.Path):
    root = tmp_path / "splitsmart"
    storage = SplitsmartStorage(root)
    await storage.ensure_layout()
    result = await storage.read_since(storage.expenses_path, "some_id")
    assert result == []


# ------------------------------------------------------------------ staging isolation


@pytest.mark.asyncio
async def test_staging_paths_are_isolated(tmp_path: pathlib.Path):
    root = tmp_path / "splitsmart"
    storage = SplitsmartStorage(root)
    await storage.ensure_layout()

    r_alice = {"id": new_id("st"), "user": "alice"}
    r_bob = {"id": new_id("st"), "user": "bob"}
    await storage.append(storage.staging_path("alice"), r_alice)
    await storage.append(storage.staging_path("bob"), r_bob)

    alice_rows = await storage.read_all(storage.staging_path("alice"))
    bob_rows = await storage.read_all(storage.staging_path("bob"))

    assert alice_rows == [r_alice]
    assert bob_rows == [r_bob]


# ------------------------------------------------------------------ concurrent appends


@pytest.mark.asyncio
async def test_concurrent_appends(tmp_path: pathlib.Path):
    root = tmp_path / "splitsmart"
    storage = SplitsmartStorage(root)
    await storage.ensure_layout()

    n = 100
    records = [{"id": new_id("ex"), "v": i} for i in range(n)]
    await asyncio.gather(*[storage.append(storage.expenses_path, r) for r in records])

    result = await storage.read_all(storage.expenses_path)
    assert len(result) == n
    # Every record must be parseable as valid JSON (no line truncation)
    ids_written = {r["id"] for r in records}
    ids_read = {r["id"] for r in result}
    assert ids_written == ids_read


# ------------------------------------------------------------------ tombstone helper


@pytest.mark.asyncio
async def test_append_tombstone(tmp_path: pathlib.Path):
    root = tmp_path / "splitsmart"
    storage = SplitsmartStorage(root)
    await storage.ensure_layout()

    snapshot = {"id": "ex_abc", "amount": 10.0}
    tb = await storage.append_tombstone(
        created_by="user_1",
        target_type="expense",
        target_id="ex_abc",
        operation="delete",
        previous_snapshot=snapshot,
        reason="test",
    )

    assert tb["id"].startswith("tb_")
    assert tb["target_id"] == "ex_abc"
    assert tb["operation"] == "delete"
    assert tb["previous_snapshot"] == snapshot

    on_disk = await storage.read_all(storage.tombstones_path)
    assert len(on_disk) == 1
    assert on_disk[0] == tb


@pytest.mark.asyncio
async def test_append_tombstone_no_reason(tmp_path: pathlib.Path):
    root = tmp_path / "splitsmart"
    storage = SplitsmartStorage(root)
    await storage.ensure_layout()

    tb = await storage.append_tombstone(
        created_by="user_1",
        target_type="expense",
        target_id="ex_xyz",
        operation="edit",
        previous_snapshot={"id": "ex_xyz"},
    )
    assert tb["reason"] is None


def test_tombstone_operation_constants_are_disjoint():
    # M3 adds TOMBSTONE_PROMOTE; guard against accidental value collision with
    # the existing operations now so dedup's operation filter stays honest.
    from custom_components.splitsmart.const import (
        TOMBSTONE_DELETE,
        TOMBSTONE_DISCARD,
        TOMBSTONE_EDIT,
        TOMBSTONE_PROMOTE,
    )

    assert TOMBSTONE_PROMOTE == "promote"
    values = {TOMBSTONE_EDIT, TOMBSTONE_DELETE, TOMBSTONE_DISCARD, TOMBSTONE_PROMOTE}
    assert len(values) == 4


# ------------------------------------------------------------------ JSON integrity


@pytest.mark.asyncio
async def test_file_is_valid_jsonl(tmp_path: pathlib.Path):
    """Each line in the file must be valid standalone JSON."""
    root = tmp_path / "splitsmart"
    storage = SplitsmartStorage(root)
    await storage.ensure_layout()

    for i in range(5):
        await storage.append(
            storage.expenses_path, {"id": new_id("ex"), "v": i, "nested": {"a": i}}
        )

    raw_lines = storage.expenses_path.read_text(encoding="utf-8").splitlines()
    for line in raw_lines:
        obj = json.loads(line)  # raises if malformed
        assert isinstance(obj, dict)
