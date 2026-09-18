"""
Regression tests for object storage and the snapshot service (WBS 9.6).

storage_backend defaults to "local" (files on disk, no Docker) -- that path is
tested directly, no mocking needed. The "s3" backend is tested against moto
(mocked S3 in-process) since no real S3/MinIO instance runs anywhere here; the
same boto3 client code path runs against real S3 or MinIO later, only the
endpoint differs (settings.s3_endpoint_url).

Both fixtures directly exercise the done-when: a snapshot can be re-read from
object storage and reproduces the same figures as the original data.
"""

import json
import shutil
from pathlib import Path

import pytest
from moto import mock_aws
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.services.object_storage as object_storage
from app.calc.engine import compute_pipeline, portfolio_rollup
from app.db.base import Base
from app.services.object_storage import get_object, put_object
from app.services.snapshots import create_snapshot, read_snapshot_content

FIXTURE = Path(__file__).parent / "fixtures" / "sample_pipeline.json"


@pytest.fixture()
def local_backend(monkeypatch, tmp_path):
    """The default backend: files on disk, no external service at all."""
    monkeypatch.setattr(object_storage.settings, "storage_backend", "local")
    monkeypatch.setattr(object_storage, "LOCAL_STORAGE_ROOT", tmp_path / "objects")
    yield
    shutil.rmtree(tmp_path / "objects", ignore_errors=True)


@pytest.fixture()
def s3_backend(monkeypatch):
    """moto mocks the real AWS S3 endpoint, not a custom one -- point the client
    at default AWS resolution for the duration of the test and reset the cached
    client so it gets rebuilt inside the mock context."""
    monkeypatch.setattr(object_storage.settings, "storage_backend", "s3")
    monkeypatch.setattr(object_storage.settings, "s3_endpoint_url", None)
    object_storage._s3_client = None
    with mock_aws():
        yield
    object_storage._s3_client = None


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture(params=["local", "s3"])
def any_backend(request):
    """Runs a test once per backend so both are proven equivalent from the
    caller's point of view. Resolves only the fixture for the active param --
    requesting both directly would apply both monkeypatches unconditionally,
    letting whichever runs last silently win regardless of request.param."""
    request.getfixturevalue(f"{request.param}_backend")
    return request.param


def test_put_and_get_object_round_trip(any_backend):
    uri = put_object("some/key.txt", b"hello world")
    assert uri.startswith(f"{any_backend}://")
    assert get_object(uri) == b"hello world"


def test_get_object_rejects_unrecognised_uri(any_backend):
    with pytest.raises(ValueError):
        get_object("https://example.com/not-recognised")


def test_snapshot_round_trips_through_object_storage(any_backend, db_session):
    content = FIXTURE.read_bytes()
    snapshot = create_snapshot(db_session, content, "sample_pipeline.json", row_counts={"project_track": 9})
    db_session.commit()

    assert snapshot.sealed_at is not None
    assert snapshot.source_uri.startswith(f"{any_backend}://")

    reread = read_snapshot_content(db_session, snapshot.id)
    assert reread == content


def test_snapshot_reproduces_same_figures_after_round_trip(any_backend, db_session):
    """The literal WBS 9.6 done-when: re-reading a snapshot months later must
    reproduce the same figures, not merely the same bytes."""
    content = FIXTURE.read_bytes()
    original_data = json.loads(content)
    original_financials = compute_pipeline(original_data["project_track"])
    original_rollup = portfolio_rollup(original_financials)

    snapshot = create_snapshot(db_session, content, "sample_pipeline.json", row_counts={})
    db_session.commit()

    reread_content = read_snapshot_content(db_session, snapshot.id)
    reread_data = json.loads(reread_content)
    reread_financials = compute_pipeline(reread_data["project_track"])
    reread_rollup = portfolio_rollup(reread_financials)

    assert reread_rollup == original_rollup


def test_read_snapshot_detects_local_storage_corruption(local_backend, db_session):
    content = b'{"project_track": []}'
    snapshot = create_snapshot(db_session, content, "empty.json", row_counts={})
    db_session.commit()

    key = snapshot.source_uri[len("local://"):]
    (object_storage.LOCAL_STORAGE_ROOT / key).write_bytes(b"tampered")

    with pytest.raises(ValueError, match="does not match its recorded sha256"):
        read_snapshot_content(db_session, snapshot.id)


def test_read_snapshot_detects_s3_storage_corruption(s3_backend, db_session):
    content = b'{"project_track": []}'
    snapshot = create_snapshot(db_session, content, "empty.json", row_counts={})
    db_session.commit()

    bucket, key = object_storage._parse_s3_uri(snapshot.source_uri)
    object_storage.get_client().put_object(Bucket=bucket, Key=key, Body=b"tampered")

    with pytest.raises(ValueError, match="does not match its recorded sha256"):
        read_snapshot_content(db_session, snapshot.id)
