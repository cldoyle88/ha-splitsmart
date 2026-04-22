"""Tests for the /api/splitsmart/upload endpoint.

Calls view.post() directly with mock requests — no real TCP server, so
these tests are compatible with pytest-homeassistant-custom-component's
socket-blocking fixture.
"""

from __future__ import annotations

import json
import pathlib
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.splitsmart.const import CONF_PARTICIPANTS, DOMAIN
from custom_components.splitsmart.coordinator import SplitsmartCoordinator
from custom_components.splitsmart.http import SplitsmartUploadView
from custom_components.splitsmart.storage import SplitsmartStorage

FIXTURES_DIR = pathlib.Path(__file__).parent / "fixtures" / "imports"


# ------------------------------------------------------------------ helpers


def _field(name: str, data: bytes, filename: str) -> MagicMock:
    """Fake aiohttp BodyPartReader yielding data in 4 K chunks then EOF."""
    chunks: list[bytes] = [data[i : i + 4096] for i in range(0, len(data), 4096)]
    chunks.append(b"")
    mock = MagicMock()
    mock.name = name
    mock.filename = filename
    mock.read_chunk = AsyncMock(side_effect=chunks)
    return mock


def _multipart(field: MagicMock | None) -> MagicMock:
    reader = MagicMock()
    reader.next = AsyncMock(return_value=field)
    return reader


def _request(
    hass: MagicMock,
    *,
    reader: MagicMock | None = None,
    user_id: str | None = None,
    content_length: int | None = None,
    multipart_raises: Exception | None = None,
) -> MagicMock:
    req = MagicMock()
    req.app = {"hass": hass}
    req.content_length = content_length
    if user_id is not None:
        user = MagicMock()
        user.id = user_id
        req.get = MagicMock(return_value=user)
    else:
        req.get = MagicMock(return_value=None)
    if multipart_raises is not None:
        req.multipart = AsyncMock(side_effect=multipart_raises)
    else:
        req.multipart = AsyncMock(return_value=reader)
    return req


def _body(response: object) -> dict:
    return json.loads(response.text)  # type: ignore[union-attr]


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
def hass_mock(storage: SplitsmartStorage, coordinator: SplitsmartCoordinator) -> MagicMock:
    entry = MagicMock()
    entry.data = {CONF_PARTICIPANTS: ["u1", "u2"]}
    entry.entry_id = "test_entry"
    hass = MagicMock()
    hass.data = {
        DOMAIN: {
            "test_entry": {
                "storage": storage,
                "coordinator": coordinator,
                "entry": entry,
            }
        }
    }
    return hass


@pytest.fixture
def view() -> SplitsmartUploadView:
    return SplitsmartUploadView()


# ------------------------------------------------------------------ happy path


async def test_upload_monzo_csv_returns_inspection(
    hass_mock: MagicMock,
    storage: SplitsmartStorage,
    view: SplitsmartUploadView,
) -> None:
    data = (FIXTURES_DIR / "monzo_classic.csv").read_bytes()
    req = _request(
        hass_mock,
        reader=_multipart(_field("file", data, "monzo_classic.csv")),
        user_id="u1",
    )
    resp = await view.post(req)
    assert resp.status == 200
    body = _body(resp)
    assert body["version"] == 1
    assert body["extension"] == "csv"
    assert body["filename"] == "monzo_classic.csv"
    assert body["size_bytes"] > 0
    uuid.UUID(body["upload_id"])
    assert body["inspection"] is not None
    assert body["inspection"]["preset"] == "Monzo"
    expected = storage.upload_path(body["upload_id"], "csv")
    assert expected.exists()
    assert expected.stat().st_size == body["size_bytes"]


async def test_upload_ofx_returns_null_inspection(
    hass_mock: MagicMock,
    view: SplitsmartUploadView,
) -> None:
    data = (FIXTURES_DIR / "sample.ofx").read_bytes()
    req = _request(
        hass_mock,
        reader=_multipart(_field("file", data, "statement.ofx")),
        user_id="u1",
    )
    resp = await view.post(req)
    assert resp.status == 200
    body = _body(resp)
    assert body["extension"] == "ofx"
    assert body["inspection"] is None


async def test_upload_preserves_original_filename_on_response(
    hass_mock: MagicMock,
    view: SplitsmartUploadView,
) -> None:
    payload = b"Date,Name,Amount,Currency,Emoji,Notes and #tags,Description,Category\n"
    req = _request(
        hass_mock,
        reader=_multipart(_field("file", payload, "statement.csv")),
        user_id="u1",
    )
    resp = await view.post(req)
    body = _body(resp)
    assert body["filename"] == "statement.csv"
    assert body["extension"] == "csv"


# ------------------------------------------------------------------ auth / authz


async def test_upload_rejects_missing_auth(
    hass_mock: MagicMock,
    view: SplitsmartUploadView,
) -> None:
    req = _request(hass_mock, reader=_multipart(_field("file", b"x", "x.csv")))
    resp = await view.post(req)
    assert resp.status == 401


async def test_upload_rejects_non_participant(
    hass_mock: MagicMock,
    view: SplitsmartUploadView,
) -> None:
    req = _request(
        hass_mock,
        reader=_multipart(_field("file", b"x", "x.csv")),
        user_id="u_stranger",
    )
    resp = await view.post(req)
    assert resp.status == 403
    body = _body(resp)
    assert body["error"] == "permission_denied"


async def test_upload_404_when_integration_not_loaded(
    view: SplitsmartUploadView,
) -> None:
    hass = MagicMock()
    hass.data = {}
    req = _request(hass, reader=_multipart(_field("file", b"x", "x.csv")), user_id="u1")
    resp = await view.post(req)
    assert resp.status == 404


# ------------------------------------------------------------------ validation


async def test_upload_rejects_unsupported_extension(
    hass_mock: MagicMock,
    view: SplitsmartUploadView,
) -> None:
    req = _request(
        hass_mock,
        reader=_multipart(_field("file", b"arbitrary", "statement.pdf")),
        user_id="u1",
    )
    resp = await view.post(req)
    assert resp.status == 415
    body = _body(resp)
    assert body["error"] == "unsupported_media_type"
    assert "csv" in body["allowed"]


async def test_upload_rejects_missing_extension(
    hass_mock: MagicMock,
    view: SplitsmartUploadView,
) -> None:
    req = _request(
        hass_mock,
        reader=_multipart(_field("file", b"arbitrary", "statement")),
        user_id="u1",
    )
    resp = await view.post(req)
    assert resp.status == 415


async def test_upload_extension_check_is_case_insensitive(
    hass_mock: MagicMock,
    view: SplitsmartUploadView,
) -> None:
    data = (FIXTURES_DIR / "monzo_classic.csv").read_bytes()
    req = _request(
        hass_mock,
        reader=_multipart(_field("file", data, "Statement.CSV")),
        user_id="u1",
    )
    resp = await view.post(req)
    assert resp.status == 200
    body = _body(resp)
    assert body["extension"] == "csv"


async def test_upload_rejects_when_content_length_exceeds_cap(
    hass_mock: MagicMock,
    view: SplitsmartUploadView,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lower the cap for a single test so we don't have to upload 25 MB."""
    import custom_components.splitsmart.http as http_module

    monkeypatch.setattr(http_module, "_MAX_BYTES", 1024)
    req = _request(
        hass_mock,
        reader=_multipart(_field("file", b"x", "big.csv")),
        user_id="u1",
        content_length=2048,  # exceeds the lowered 1 KB cap
    )
    resp = await view.post(req)
    assert resp.status == 413
    body = _body(resp)
    assert body["error"] == "payload_too_large"


async def test_upload_malformed_csv_still_succeeds_with_error_hint(
    hass_mock: MagicMock,
    view: SplitsmartUploadView,
) -> None:
    """A parse failure during inspection doesn't abort the upload."""
    req = _request(
        hass_mock,
        reader=_multipart(_field("file", b"", "empty.csv")),
        user_id="u1",
    )
    resp = await view.post(req)
    assert resp.status == 200
    body = _body(resp)
    assert body["inspection"] is not None
    assert body["inspection"]["preset"] is None


async def test_upload_rejects_non_file_field(
    hass_mock: MagicMock,
    view: SplitsmartUploadView,
) -> None:
    """Form field named 'upload' instead of 'file' → 400."""
    req = _request(
        hass_mock,
        reader=_multipart(_field("upload", b"x", "x.csv")),
        user_id="u1",
    )
    resp = await view.post(req)
    assert resp.status == 400


async def test_upload_writes_to_uploads_dir_not_elsewhere(
    hass_mock: MagicMock,
    storage: SplitsmartStorage,
    view: SplitsmartUploadView,
) -> None:
    data = (FIXTURES_DIR / "monzo_classic.csv").read_bytes()
    req = _request(
        hass_mock,
        reader=_multipart(_field("file", data, "monzo_classic.csv")),
        user_id="u1",
    )
    resp = await view.post(req)
    body = _body(resp)

    uploaded = storage.upload_path(body["upload_id"], "csv")
    assert uploaded.parent == storage.uploads_dir
    assert uploaded.exists()
    assert not any(storage.staging_path("u1").parent.iterdir())


# Housekeeping: ensure fixtures are readable.
def test_fixture_files_exist() -> None:
    assert (FIXTURES_DIR / "monzo_classic.csv").exists()
    assert (FIXTURES_DIR / "sample.ofx").exists()
