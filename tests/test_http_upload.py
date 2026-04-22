"""Tests for the /api/splitsmart/upload endpoint.

Uses aiohttp's TestServer/TestClient rather than mocking request.multipart()
by hand — real multipart encoding catches framing bugs a hand-rolled mock
would miss. HomeAssistantView's auth indirection is stubbed by a small
test middleware that sets request["hass_user"] from a header.
"""

from __future__ import annotations

import pathlib
import uuid
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import MagicMock

import pytest
from aiohttp import FormData
from aiohttp import web as aiohttp_web
from aiohttp.test_utils import TestClient, TestServer

from custom_components.splitsmart.const import CONF_PARTICIPANTS, DOMAIN
from custom_components.splitsmart.coordinator import SplitsmartCoordinator
from custom_components.splitsmart.http import SplitsmartUploadView
from custom_components.splitsmart.storage import SplitsmartStorage

FIXTURES_DIR = pathlib.Path(__file__).parent / "fixtures" / "imports"

# These tests spin up a real aiohttp TCP server on 127.0.0.1. pytest-socket
# (activated by pytest-homeassistant-custom-component in CI) blocks socket
# creation by default — allow loopback so TestServer/TestClient can bind.
pytestmark = [pytest.mark.allow_hosts(["127.0.0.1"])]


# ------------------------------------------------------------------ fixtures


@pytest.fixture
async def storage(tmp_path: pathlib.Path) -> SplitsmartStorage:
    s = SplitsmartStorage(tmp_path / "splitsmart")
    await s.ensure_layout()
    return s


@pytest.fixture
async def coordinator(storage: SplitsmartStorage) -> SplitsmartCoordinator:
    hass = MagicMock()
    hass.bus = MagicMock()
    hass.bus.async_fire = MagicMock()
    coord = SplitsmartCoordinator(
        hass,
        storage,
        participants=["u1", "u2"],
        home_currency="GBP",
        categories=["Groceries"],
        config_entry=None,
    )
    coord.data = await coord._async_update_data()
    return coord


@pytest.fixture
async def http_client(
    storage: SplitsmartStorage, coordinator: SplitsmartCoordinator
) -> AsyncGenerator[tuple[TestClient, SplitsmartStorage], None]:
    entry = MagicMock()
    entry.data = {CONF_PARTICIPANTS: ["u1", "u2"]}
    entry.entry_id = "test_entry"

    hass = MagicMock()
    hass.data = {
        DOMAIN: {
            "test_entry": {"storage": storage, "coordinator": coordinator, "entry": entry},
        }
    }

    @aiohttp_web.middleware
    async def _test_auth(request: aiohttp_web.Request, handler: Any) -> Any:
        """Stub HA's auth middleware — set request["hass_user"] from a header.

        The view has requires_auth=True but that's just a class attribute
        consumed by HA's router; the real auth decision happens in HA's
        middleware. In tests, we fake it with X-Test-User.
        """
        user_id = request.headers.get("X-Test-User")
        if user_id:
            user = MagicMock()
            user.id = user_id
            request["hass_user"] = user
        return await handler(request)

    app = aiohttp_web.Application(middlewares=[_test_auth])
    app["hass"] = hass
    view = SplitsmartUploadView()
    app.router.add_post(view.url, view.post)

    async with TestClient(TestServer(app)) as client:
        yield client, storage


def _upload_form(fixture_name: str) -> FormData:
    form = FormData()
    form.add_field(
        "file",
        (FIXTURES_DIR / fixture_name).read_bytes(),
        filename=fixture_name,
        content_type="text/csv",
    )
    return form


# ------------------------------------------------------------------ happy path


async def test_upload_monzo_csv_returns_inspection(
    http_client: tuple[TestClient, SplitsmartStorage],
) -> None:
    client, storage = http_client
    resp = await client.post(
        "/api/splitsmart/upload",
        data=_upload_form("monzo_classic.csv"),
        headers={"X-Test-User": "u1"},
    )
    assert resp.status == 200
    body = await resp.json()
    assert body["version"] == 1
    assert body["extension"] == "csv"
    assert body["filename"] == "monzo_classic.csv"
    assert body["size_bytes"] > 0
    # uuid4 format check.
    uuid.UUID(body["upload_id"])
    # Inspection populated for CSV.
    assert body["inspection"] is not None
    assert body["inspection"]["preset"] == "Monzo"

    # File is on disk.
    expected = storage.upload_path(body["upload_id"], "csv")
    assert expected.exists()
    assert expected.stat().st_size == body["size_bytes"]


async def test_upload_ofx_returns_null_inspection(
    http_client: tuple[TestClient, SplitsmartStorage],
) -> None:
    """OFX has a fixed schema — no mapping cascade, inspection is null."""
    client, _ = http_client
    form = FormData()
    form.add_field(
        "file",
        (FIXTURES_DIR / "sample.ofx").read_bytes(),
        filename="statement.ofx",
        content_type="application/x-ofx",
    )
    resp = await client.post(
        "/api/splitsmart/upload",
        data=form,
        headers={"X-Test-User": "u1"},
    )
    assert resp.status == 200
    body = await resp.json()
    assert body["extension"] == "ofx"
    assert body["inspection"] is None


async def test_upload_preserves_original_filename_on_response(
    http_client: tuple[TestClient, SplitsmartStorage],
) -> None:
    """The on-disk filename is a uuid, but the response echoes the client's
    filename so the card can show it in the import wizard.

    Note: aiohttp's client URL-encodes spaces in Content-Disposition per
    RFC 7578 when constructing multipart bodies. Real browsers use
    quoted-string form and preserve spaces. The test asserts round-trip
    (whatever the server received, it echoed back) plus the .csv suffix
    so the assertion stays robust across HTTP client behaviours.
    """
    client, _ = http_client
    form = FormData()
    form.add_field(
        "file",
        b"Date,Name,Amount,Currency,Emoji,Notes and #tags,Description,Category\n",
        filename="statement.csv",
        content_type="text/csv",
    )
    resp = await client.post(
        "/api/splitsmart/upload",
        data=form,
        headers={"X-Test-User": "u1"},
    )
    body = await resp.json()
    assert body["filename"] == "statement.csv"
    assert body["extension"] == "csv"


# ------------------------------------------------------------------ auth / authz


async def test_upload_rejects_missing_auth(
    http_client: tuple[TestClient, SplitsmartStorage],
) -> None:
    """Without the test auth header, request["hass_user"] is None → 401."""
    client, _ = http_client
    resp = await client.post(
        "/api/splitsmart/upload",
        data=_upload_form("monzo_classic.csv"),
    )
    assert resp.status == 401


async def test_upload_rejects_non_participant(
    http_client: tuple[TestClient, SplitsmartStorage],
) -> None:
    client, _ = http_client
    resp = await client.post(
        "/api/splitsmart/upload",
        data=_upload_form("monzo_classic.csv"),
        headers={"X-Test-User": "u_stranger"},
    )
    assert resp.status == 403
    body = await resp.json()
    assert body["error"] == "permission_denied"


async def test_upload_404_when_integration_not_loaded(
    tmp_path: pathlib.Path,
) -> None:
    """If hass.data doesn't have a Splitsmart entry, the view returns 404
    instead of a cryptic KeyError."""
    hass = MagicMock()
    hass.data = {}  # no DOMAIN entry

    @aiohttp_web.middleware
    async def _auth(request: aiohttp_web.Request, handler: Any) -> Any:
        user = MagicMock()
        user.id = "u1"
        request["hass_user"] = user
        return await handler(request)

    app = aiohttp_web.Application(middlewares=[_auth])
    app["hass"] = hass
    view = SplitsmartUploadView()
    app.router.add_post(view.url, view.post)

    async with TestClient(TestServer(app)) as client:
        resp = await client.post(
            "/api/splitsmart/upload",
            data=_upload_form("monzo_classic.csv"),
            headers={"X-Test-User": "u1"},
        )
        assert resp.status == 404


# ------------------------------------------------------------------ validation


async def test_upload_rejects_unsupported_extension(
    http_client: tuple[TestClient, SplitsmartStorage],
) -> None:
    client, _ = http_client
    form = FormData()
    form.add_field(
        "file",
        b"arbitrary",
        filename="statement.pdf",
        content_type="application/pdf",
    )
    resp = await client.post(
        "/api/splitsmart/upload",
        data=form,
        headers={"X-Test-User": "u1"},
    )
    assert resp.status == 415
    body = await resp.json()
    assert body["error"] == "unsupported_media_type"
    assert "csv" in body["allowed"]


async def test_upload_rejects_missing_extension(
    http_client: tuple[TestClient, SplitsmartStorage],
) -> None:
    client, _ = http_client
    form = FormData()
    form.add_field(
        "file",
        b"arbitrary",
        filename="statement",
        content_type="application/octet-stream",
    )
    resp = await client.post(
        "/api/splitsmart/upload",
        data=form,
        headers={"X-Test-User": "u1"},
    )
    assert resp.status == 415


async def test_upload_extension_check_is_case_insensitive(
    http_client: tuple[TestClient, SplitsmartStorage],
) -> None:
    """Clients on case-preserving filesystems often upload Statement.CSV."""
    client, _ = http_client
    form = FormData()
    form.add_field(
        "file",
        (FIXTURES_DIR / "monzo_classic.csv").read_bytes(),
        filename="Statement.CSV",
        content_type="text/csv",
    )
    resp = await client.post(
        "/api/splitsmart/upload",
        data=form,
        headers={"X-Test-User": "u1"},
    )
    assert resp.status == 200
    body = await resp.json()
    assert body["extension"] == "csv"


async def test_upload_rejects_when_content_length_exceeds_cap(
    http_client: tuple[TestClient, SplitsmartStorage],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lower the cap for a single test so we don't have to upload 25 MB."""
    import custom_components.splitsmart.http as http_module

    monkeypatch.setattr(http_module, "_MAX_BYTES", 1024)

    client, _ = http_client
    form = FormData()
    form.add_field(
        "file",
        b"x" * 2048,  # 2 KB exceeds the lowered 1 KB cap
        filename="big.csv",
        content_type="text/csv",
    )
    resp = await client.post(
        "/api/splitsmart/upload",
        data=form,
        headers={"X-Test-User": "u1"},
    )
    assert resp.status == 413
    body = await resp.json()
    assert body["error"] == "payload_too_large"


async def test_upload_malformed_csv_still_succeeds_with_error_hint(
    http_client: tuple[TestClient, SplitsmartStorage],
) -> None:
    """A parse failure during inspection doesn't abort the upload — the
    file lands, the response flags the hint, and the wizard can surface a
    'supply a mapping' UI."""
    client, _ = http_client
    form = FormData()
    form.add_field(
        "file",
        b"",  # empty — inspection returns empty headers but no exception
        filename="empty.csv",
        content_type="text/csv",
    )
    resp = await client.post(
        "/api/splitsmart/upload",
        data=form,
        headers={"X-Test-User": "u1"},
    )
    assert resp.status == 200
    body = await resp.json()
    # Empty CSV still parses an empty-header inspection — preset is null.
    assert body["inspection"] is not None
    assert body["inspection"]["preset"] is None


async def test_upload_rejects_non_file_field(
    http_client: tuple[TestClient, SplitsmartStorage],
) -> None:
    """Form field named 'upload' instead of 'file' → 400."""
    client, _ = http_client
    form = FormData()
    form.add_field(
        "upload",
        b"x",
        filename="x.csv",
        content_type="text/csv",
    )
    resp = await client.post(
        "/api/splitsmart/upload",
        data=form,
        headers={"X-Test-User": "u1"},
    )
    assert resp.status == 400


async def test_upload_writes_to_uploads_dir_not_elsewhere(
    http_client: tuple[TestClient, SplitsmartStorage],
    tmp_path: pathlib.Path,
) -> None:
    """The file must land under /config/splitsmart/uploads/ — not the
    staging dir, not somewhere under the test root."""
    client, storage = http_client
    resp = await client.post(
        "/api/splitsmart/upload",
        data=_upload_form("monzo_classic.csv"),
        headers={"X-Test-User": "u1"},
    )
    body = await resp.json()

    uploaded = storage.upload_path(body["upload_id"], "csv")
    assert uploaded.parent == storage.uploads_dir
    assert uploaded.exists()
    # Staging dir has no accidental file.
    assert not any(storage.staging_path("u1").parent.iterdir())


# Housekeeping: ensure fixtures are readable (guards against committed-
# fixture rot before more useful tests fail on content assertions).
def test_fixture_files_exist() -> None:
    assert (FIXTURES_DIR / "monzo_classic.csv").exists()
    assert (FIXTURES_DIR / "sample.ofx").exists()
