"""Uploaded-file cleanup task.

Every hour, sweep ``/config/splitsmart/uploads/`` and delete files
older than 24 hours that aren't referenced by any live staging row.
Per M3_PLAN.md O3, the cadence is intentionally hourly rather than
daily at 03:00: it's cheap, resilient to restart clock skew, and
keeps the 24-hour retention window tight.

``sweep_uploads`` is the pure-ish working function — no HA imports,
takes the storage handle and the coordinator's materialised staging
projection. The HA scheduler wiring lives in ``__init__.py`` and
calls this function on every tick.
"""

from __future__ import annotations

import logging
import pathlib
import time
from typing import Any

_LOGGER = logging.getLogger(__name__)

# 24-hour retention in seconds.
_RETENTION_SECONDS = 24 * 60 * 60


def _referenced_upload_ids(
    staging_by_user: dict[str, list[dict[str, Any]]],
) -> set[str]:
    """Collect source_ref_upload_id values from every live staging row.

    A staging row that originated from an HTTP upload carries its
    ``source_ref_upload_id``. Rows from other sources (Telegram, manual)
    have no uuid and skip this set.
    """
    out: set[str] = set()
    for rows in staging_by_user.values():
        for row in rows:
            upload_id = row.get("source_ref_upload_id")
            if upload_id:
                out.add(upload_id)
    return out


def sweep_uploads(
    uploads_dir: pathlib.Path,
    staging_by_user: dict[str, list[dict[str, Any]]],
    *,
    now: float | None = None,
    retention_seconds: int = _RETENTION_SECONDS,
) -> list[pathlib.Path]:
    """Delete stale upload files; return the list of paths that were removed.

    A file is stale when BOTH:
      - its mtime is older than ``retention_seconds`` ago, AND
      - no live staging row references its uuid via ``source_ref_upload_id``.

    Files younger than the retention window are kept regardless of
    reference. Files referenced by any live staging row are kept regardless
    of age (the row may outlive the 24-hour window — the user hasn't
    decided yet, and the tombstone trail would mean re-uploading).
    """
    if not uploads_dir.exists():
        return []

    current = now if now is not None else time.time()
    cutoff = current - retention_seconds
    referenced = _referenced_upload_ids(staging_by_user)

    removed: list[pathlib.Path] = []
    for path in uploads_dir.iterdir():
        if not path.is_file():
            continue
        upload_id = path.stem
        if upload_id in referenced:
            continue
        try:
            mtime = path.stat().st_mtime
        except OSError as err:
            _LOGGER.debug("cleanup: stat failed on %s: %s", path, err)
            continue
        if mtime >= cutoff:
            continue
        try:
            path.unlink()
        except OSError as err:
            _LOGGER.debug("cleanup: unlink failed on %s: %s", path, err)
            continue
        removed.append(path)

    if removed:
        _LOGGER.info("Splitsmart uploads cleanup: removed %d stale files", len(removed))
    return removed
