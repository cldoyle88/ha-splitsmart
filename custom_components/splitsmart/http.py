"""HTTP views for Splitsmart.

M3 ships a single endpoint:

    POST /api/splitsmart/upload

Receives a multipart file upload from the card's import wizard (or any
``curl -F`` caller). Validates the caller is a Splitsmart participant,
checks the extension and size, writes the payload to
``/config/splitsmart/uploads/<uuid4>.<ext>``, and returns a JSON body
that includes an inspection payload for CSV/XLSX files so the wizard
can skip straight to mapping without a second round trip.

``splitsmart.import_file`` consumes the returned ``upload_id``. Uploads
older than 24 hours that no staging row references are swept by the
hourly cleanup task (step 10).
"""

from __future__ import annotations

import contextlib
import logging
import uuid
from typing import Any

import aiofiles
from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .const import CONF_PARTICIPANTS, DOMAIN
from .importer import inspect_file
from .importer.types import FileInspection
from .storage import SplitsmartStorage

_LOGGER = logging.getLogger(__name__)

# Extension whitelist — anything else is 415 Unsupported Media Type.
_ALLOWED_EXTENSIONS: frozenset[str] = frozenset({"csv", "xlsx", "ofx", "qif"})

# 25 MB — rare real statements exceed 2 MB but multi-year archive exports can.
_MAX_BYTES: int = 25 * 1024 * 1024


def _resolve_entry(hass: HomeAssistant) -> tuple[Any, SplitsmartStorage] | None:
    """Return (entry, storage) for the single configured Splitsmart entry."""
    store = hass.data.get(DOMAIN)
    if not store:
        return None
    for key, value in store.items():
        if key.startswith("_"):
            continue
        if isinstance(value, dict) and "storage" in value:
            return value["entry"], value["storage"]
    return None


def _extension_from(filename: str) -> str:
    """Return the lower-cased extension from a client-supplied filename.
    Returns empty string if no extension — caller rejects."""
    if "." not in filename:
        return ""
    return filename.rsplit(".", 1)[-1].lower()


class SplitsmartUploadView(HomeAssistantView):
    """POST /api/splitsmart/upload — multipart file upload entry point."""

    requires_auth = True
    url = "/api/splitsmart/upload"
    name = "api:splitsmart:upload"

    async def post(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app["hass"]

        # Participant check. HomeAssistantView has already authenticated the
        # token and set request["hass_user"]; we only need the authorisation
        # step (is this user a configured Splitsmart participant?).
        user = request.get("hass_user")
        if user is None:
            return self.json({"error": "unauthorized"}, status_code=401)

        resolved = _resolve_entry(hass)
        if resolved is None:
            return self.json({"error": "not_found"}, status_code=404)
        entry, storage = resolved

        if user.id not in entry.data[CONF_PARTICIPANTS]:
            return self.json({"error": "permission_denied"}, status_code=403)

        # Early size check — cheap rejection before we start reading the body.
        content_length = request.content_length
        if content_length is not None and content_length > _MAX_BYTES:
            return self.json(
                {
                    "error": "payload_too_large",
                    "max_bytes": _MAX_BYTES,
                },
                status_code=413,
            )

        # Read the multipart body. We keep it simple: one file field only.
        try:
            reader = await request.multipart()
            field = await reader.next()
        except Exception as err:
            _LOGGER.debug("Upload: malformed multipart body: %s", err)
            return self.json({"error": "bad_request"}, status_code=400)

        if field is None or field.name != "file":
            return self.json(
                {"error": "bad_request", "detail": "expected a 'file' form field"},
                status_code=400,
            )

        filename: str = field.filename or ""
        extension = _extension_from(filename)
        if extension not in _ALLOWED_EXTENSIONS:
            return self.json(
                {
                    "error": "unsupported_media_type",
                    "allowed": sorted(_ALLOWED_EXTENSIONS),
                },
                status_code=415,
            )

        upload_id = str(uuid.uuid4())
        dest = storage.upload_path(upload_id, extension)

        # Stream to disk with a running size cap so a client that lies about
        # Content-Length can't fill the filesystem.
        size_bytes = 0
        async with aiofiles.open(dest, mode="wb") as fh:
            while True:
                chunk = await field.read_chunk()
                if not chunk:
                    break
                size_bytes += len(chunk)
                if size_bytes > _MAX_BYTES:
                    await fh.close()
                    with contextlib.suppress(OSError):
                        dest.unlink()
                    return self.json(
                        {"error": "payload_too_large", "max_bytes": _MAX_BYTES},
                        status_code=413,
                    )
                await fh.write(chunk)

        _LOGGER.info(
            "Splitsmart upload: %s → %s (%d bytes) for user %s",
            filename,
            dest.name,
            size_bytes,
            user.id,
        )

        # Inspection — only meaningful for CSV/XLSX, where the mapping
        # cascade might surface a preset match or saved mapping to the UI.
        # OFX/QIF have fixed schemas, so we return inspection=null for them.
        inspection: FileInspection | None = None
        error_hint: str | None = None
        if extension in {"csv", "xlsx"}:
            try:
                inspection = await inspect_file(dest, storage=storage)
            except Exception as err:
                # Upload still succeeds — the caller can retry with an
                # explicit mapping or re-upload a corrected file.
                _LOGGER.debug("Upload inspection failed for %s: %s", dest.name, err)
                error_hint = str(err)

        payload: dict[str, Any] = {
            "version": 1,
            "upload_id": upload_id,
            "filename": filename,
            "size_bytes": size_bytes,
            "extension": extension,
            "inspection": inspection,
        }
        if error_hint is not None:
            payload["error_hint"] = error_hint
        return self.json(payload, status_code=200)


def async_register_http(hass: HomeAssistant) -> None:
    """Register the upload view. Idempotent — guarded on hass.data so
    entry reloads don't add duplicate views."""
    flag = "_http_registered"
    store = hass.data.setdefault(DOMAIN, {})
    if store.get(flag):
        return
    hass.http.register_view(SplitsmartUploadView())
    store[flag] = True
