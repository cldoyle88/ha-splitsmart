"""Append-only JSONL storage primitives for Splitsmart."""

from __future__ import annotations

import asyncio
import json
import logging
import pathlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import aiofiles
from ulid import ULID

from .const import (
    EXPENSES_FILE,
    FX_RATES_FILE,
    ID_PREFIX_TOMBSTONE,
    MAPPINGS_FILE,
    RECEIPTS_DIR,
    RECURRING_STATE_FILE,
    RECURRING_YAML_FILE,
    SETTLEMENTS_FILE,
    SHARED_DIR,
    STAGING_DIR,
    TOMBSTONES_FILE,
    UPLOADS_DIR,
)

_LOGGER = logging.getLogger(__name__)


def new_id(prefix: str) -> str:
    """Return a ULID-based id with a typed prefix, e.g. 'ex_01J9X...'."""
    return f"{prefix}_{ULID()}"


def validate_root(root: pathlib.Path) -> None:
    """Raise ValueError if root is under /config/www/ or not an absolute path."""
    if not root.is_absolute():
        raise ValueError(f"Storage root must be an absolute path, got: {root}")
    # Normalise to catch symlink tricks
    try:
        resolved = root.resolve()
    except OSError:
        resolved = root
    parts = resolved.parts
    # Reject anything whose path contains 'www' as a direct child of 'config'
    for i, part in enumerate(parts):
        if part == "www" and i > 0 and parts[i - 1] in ("config", "homeassistant"):
            raise ValueError(
                f"Storage root {root!r} is inside /config/www/ — files there are "
                "web-accessible. Use /config/splitsmart/ instead."
            )
    # Belt-and-braces: reject the literal string
    root_str = str(resolved).replace("\\", "/")
    if "/config/www" in root_str or "/homeassistant/www" in root_str:
        raise ValueError(
            f"Storage root {root!r} appears to be inside /config/www/. "
            "Use /config/splitsmart/ instead."
        )


class SplitsmartStorage:
    """Append-only JSONL storage under /config/splitsmart/. All IO is async."""

    def __init__(self, root: pathlib.Path) -> None:
        validate_root(root)
        self._root = root
        self._locks: dict[pathlib.Path, asyncio.Lock] = {}

    # ------------------------------------------------------------------ layout

    async def ensure_layout(self) -> None:
        """Create the full directory tree if any part is missing."""
        dirs = [
            self._root,
            self._root / SHARED_DIR,
            self._root / STAGING_DIR,
            self._root / RECEIPTS_DIR,
            self._root / RECEIPTS_DIR / "incoming",
            self._root / UPLOADS_DIR,
        ]
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)

        # Touch empty JSONL files so readers never have to special-case missing files.
        # recurring.yaml is intentionally NOT created here — its absence means "no recurrings".
        for empty_file in (self.fx_rates_path, self.recurring_state_path):
            if not empty_file.exists():
                empty_file.touch()

        _LOGGER.debug("Storage layout verified at %s", self._root)

    # ------------------------------------------------------------ path helpers

    @property
    def expenses_path(self) -> pathlib.Path:
        return self._root / SHARED_DIR / EXPENSES_FILE

    @property
    def settlements_path(self) -> pathlib.Path:
        return self._root / SHARED_DIR / SETTLEMENTS_FILE

    @property
    def tombstones_path(self) -> pathlib.Path:
        return self._root / SHARED_DIR / TOMBSTONES_FILE

    def staging_path(self, user_id: str) -> pathlib.Path:
        return self._root / STAGING_DIR / f"{user_id}.jsonl"

    @property
    def uploads_dir(self) -> pathlib.Path:
        return self._root / UPLOADS_DIR

    def upload_path(self, upload_id: str, extension: str) -> pathlib.Path:
        ext = extension.lstrip(".").lower()
        return self._root / UPLOADS_DIR / f"{upload_id}.{ext}"

    @property
    def mappings_path(self) -> pathlib.Path:
        return self._root / MAPPINGS_FILE

    @property
    def fx_rates_path(self) -> pathlib.Path:
        return self._root / FX_RATES_FILE

    @property
    def recurring_yaml_path(self) -> pathlib.Path:
        return self._root / RECURRING_YAML_FILE

    @property
    def recurring_state_path(self) -> pathlib.Path:
        return self._root / RECURRING_STATE_FILE

    # --------------------------------------------------------- generic JSONL

    def _lock(self, path: pathlib.Path) -> asyncio.Lock:
        if path not in self._locks:
            self._locks[path] = asyncio.Lock()
        return self._locks[path]

    async def append(self, path: pathlib.Path, record: dict[str, Any]) -> None:
        """Serialise record as one JSON line and append-flush to path.
        Per-path lock serialises concurrent writes from the same process."""
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
        async with self._lock(path), aiofiles.open(path, mode="a", encoding="utf-8") as fh:
            await fh.write(line)
            await fh.flush()

    async def read_all(self, path: pathlib.Path) -> list[dict[str, Any]]:
        """Return every record in the file, in file order. Missing file → []."""
        if not path.exists():
            return []
        records: list[dict[str, Any]] = []
        async with aiofiles.open(path, encoding="utf-8") as fh:
            async for raw in fh:
                raw = raw.strip()
                if raw:
                    records.append(json.loads(raw))
        return records

    async def read_since(
        self,
        path: pathlib.Path,
        since_id: str | None,
    ) -> list[dict[str, Any]]:
        """Return records strictly after since_id (by id field). None → all."""
        if since_id is None:
            return await self.read_all(path)
        if not path.exists():
            return []
        results: list[dict[str, Any]] = []
        found = False
        async with aiofiles.open(path, encoding="utf-8") as fh:
            async for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                record = json.loads(raw)
                if found:
                    results.append(record)
                elif record.get("id") == since_id:
                    found = True
        return results

    async def iter_lines(self, path: pathlib.Path) -> AsyncIterator[dict[str, Any]]:
        """Stream records without materialising the full list."""
        if not path.exists():
            return
        async with aiofiles.open(path, encoding="utf-8") as fh:
            async for raw in fh:
                raw = raw.strip()
                if raw:
                    yield json.loads(raw)

    # --------------------------------------------------------- tombstone helper

    async def append_tombstone(
        self,
        *,
        created_by: str,
        target_type: str,
        target_id: str,
        operation: str,
        previous_snapshot: dict[str, Any],
        reason: str | None = None,
        replacement_id: str | None = None,
    ) -> dict[str, Any]:
        """Build, append, and return a tombstone record.

        ``replacement_id`` is written when the tombstone represents a morph
        rather than an end-of-life — notably ``operation="promote"`` on a
        staging row, where ``replacement_id`` is the new shared expense's
        id. Kept optional so expense/settlement edit/delete tombstones
        don't carry a ``None`` field.
        """
        record: dict[str, Any] = {
            "id": new_id(ID_PREFIX_TOMBSTONE),
            "created_at": datetime.now(tz=UTC).astimezone().isoformat(),
            "created_by": created_by,
            "target_type": target_type,
            "target_id": target_id,
            "operation": operation,
            "previous_snapshot": previous_snapshot,
            "reason": reason,
        }
        if replacement_id is not None:
            record["replacement_id"] = replacement_id
        await self.append(self.tombstones_path, record)
        return record
