"""Tests for the uploads cleanup sweep.

``sweep_uploads`` is pure-ish — takes a directory + the coordinator's
materialised staging projection, returns the list of purged paths.
No HA event loop required.
"""

from __future__ import annotations

import pathlib
import time

from custom_components.splitsmart.cleanup import sweep_uploads


def _touch(path: pathlib.Path, *, mtime: float) -> pathlib.Path:
    path.write_bytes(b"test")
    import os

    os.utime(path, (mtime, mtime))
    return path


def _staging(*upload_ids: str) -> dict[str, list[dict[str, object]]]:
    """Build a materialised staging projection referencing the given upload ids."""
    return {
        "u1": [{"id": f"st_{i}", "source_ref_upload_id": uid} for i, uid in enumerate(upload_ids)]
    }


def test_sweep_noop_when_dir_missing(tmp_path: pathlib.Path) -> None:
    # Dir doesn't exist → return [] rather than raise.
    removed = sweep_uploads(tmp_path / "nope", staging_by_user={})
    assert removed == []


def test_sweep_removes_stale_unreferenced_file(tmp_path: pathlib.Path) -> None:
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    now = time.time()
    stale = _touch(uploads / "old.csv", mtime=now - 25 * 3600)

    removed = sweep_uploads(uploads, staging_by_user={}, now=now)

    assert removed == [stale]
    assert not stale.exists()


def test_sweep_keeps_fresh_files(tmp_path: pathlib.Path) -> None:
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    now = time.time()
    fresh = _touch(uploads / "new.csv", mtime=now - 2 * 3600)

    removed = sweep_uploads(uploads, staging_by_user={}, now=now)

    assert removed == []
    assert fresh.exists()


def test_sweep_keeps_stale_but_referenced_file(tmp_path: pathlib.Path) -> None:
    """Even if a file is 25h old, a live staging row referencing it means
    the user hasn't decided yet — keep the file."""
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    now = time.time()
    stale = _touch(uploads / "abcd.csv", mtime=now - 25 * 3600)

    removed = sweep_uploads(uploads, staging_by_user=_staging("abcd"), now=now)

    assert removed == []
    assert stale.exists()


def test_sweep_keeps_references_even_across_users(tmp_path: pathlib.Path) -> None:
    """Multi-user: upload_id in any user's staging protects the file."""
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    now = time.time()
    stale = _touch(uploads / "xyz.csv", mtime=now - 30 * 3600)

    staging = {
        "u1": [],
        "u2": [
            {"id": "st_other", "source_ref_upload_id": "xyz"},
        ],
    }
    removed = sweep_uploads(uploads, staging_by_user=staging, now=now)

    assert removed == []
    assert stale.exists()


def test_sweep_mixed_files(tmp_path: pathlib.Path) -> None:
    """Three files: stale+unref (purged), stale+ref (kept), fresh (kept)."""
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    now = time.time()
    stale_unref = _touch(uploads / "orphan.csv", mtime=now - 36 * 3600)
    stale_ref = _touch(uploads / "referenced.csv", mtime=now - 36 * 3600)
    fresh = _touch(uploads / "just_uploaded.csv", mtime=now - 60)

    removed = sweep_uploads(uploads, staging_by_user=_staging("referenced"), now=now)

    assert removed == [stale_unref]
    assert not stale_unref.exists()
    assert stale_ref.exists()
    assert fresh.exists()


def test_sweep_ignores_directories(tmp_path: pathlib.Path) -> None:
    """A subdirectory in uploads/ (unexpected but possible) is skipped."""
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    (uploads / "subdir").mkdir()

    removed = sweep_uploads(uploads, staging_by_user={}, now=time.time())

    assert removed == []


def test_sweep_ignores_rows_without_upload_id(tmp_path: pathlib.Path) -> None:
    """Staging rows from Telegram / manual entry carry no source_ref_upload_id —
    the sweep must not try to protect uuid='' or choke on missing keys."""
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    now = time.time()
    stale = _touch(uploads / "orphan.csv", mtime=now - 25 * 3600)

    staging = {
        "u1": [
            {"id": "st_telegram", "source_ref_upload_id": None},
            {"id": "st_manual"},  # key missing entirely
        ],
    }
    removed = sweep_uploads(uploads, staging_by_user=staging, now=now)

    assert removed == [stale]


def test_sweep_custom_retention(tmp_path: pathlib.Path) -> None:
    """Retention seconds is overridable so tests don't have to fake 24h clocks."""
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    now = time.time()
    hour_old = _touch(uploads / "recent.csv", mtime=now - 3700)

    # 30-minute retention → 1h-old file is stale.
    removed = sweep_uploads(uploads, staging_by_user={}, now=now, retention_seconds=1800)
    assert removed == [hour_old]
