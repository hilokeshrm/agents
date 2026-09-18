"""
Object storage (WBS 9.6): holds source workbooks, uploads and generated exports.
Uploaded files are retained because they are the evidence behind a snapshot
(app/db/models/snapshot.py, WBS 3.2), not a transient input -- the done-when for
this task is that a snapshot can be re-read from object storage months later and
reproduces the same figures.

Two backends behind the same put_object/get_object interface, selected by
settings.storage_backend:

- "local" (default): files live on disk under LOCAL_STORAGE_ROOT. No S3, no
  MinIO, no Docker -- this is what runs today in a plain venv.
- "s3": real S3, or MinIO (S3-compatible) once something provides it. Not
  exercised by default; set STORAGE_BACKEND=s3 (and the s3_* settings) once an
  actual endpoint exists. boto3 is lazily constructed so importing this module
  never requires live credentials or a reachable endpoint.

Callers (app/services/snapshots.py) never branch on which backend is active --
both return the same kind of opaque URI (local://... or s3://...) that gets
stored as snapshot.source_uri.
"""

from pathlib import Path

import boto3
from botocore.exceptions import ClientError

from app.core.config import settings

LOCAL_STORAGE_ROOT = Path(__file__).resolve().parents[2] / "data" / "objects"

_s3_client = None


def put_object(key: str, content: bytes) -> str:
    if settings.storage_backend == "local":
        return _local_put(key, content)
    return _s3_put(key, content)


def get_object(uri: str) -> bytes:
    if uri.startswith("local://"):
        return _local_get(uri)
    if uri.startswith("s3://"):
        return _s3_get(uri)
    raise ValueError(f"unrecognised object storage uri: {uri!r}")


# -- local disk backend ------------------------------------------------------

def _local_put(key: str, content: bytes) -> str:
    path = LOCAL_STORAGE_ROOT / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return f"local://{key}"


def _local_get(uri: str) -> bytes:
    key = uri[len("local://"):]
    return (LOCAL_STORAGE_ROOT / key).read_bytes()


# -- S3 / MinIO backend --------------------------------------------------------

def get_client():
    global _s3_client
    if _s3_client is None:
        _s3_client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name=settings.s3_region,
        )
    return _s3_client


def ensure_bucket() -> None:
    """Idempotent: creates the bucket if it does not already exist. Safe to call
    on every write rather than requiring a one-time provisioning step."""
    client = get_client()
    try:
        client.head_bucket(Bucket=settings.s3_bucket)
    except ClientError:
        client.create_bucket(Bucket=settings.s3_bucket)


def _s3_put(key: str, content: bytes) -> str:
    ensure_bucket()
    get_client().put_object(Bucket=settings.s3_bucket, Key=key, Body=content)
    return f"s3://{settings.s3_bucket}/{key}"


def _s3_get(uri: str) -> bytes:
    bucket, key = _parse_s3_uri(uri)
    resp = get_client().get_object(Bucket=bucket, Key=key)
    return resp["Body"].read()


def _parse_s3_uri(uri: str) -> tuple[str, str]:
    bucket, _, key = uri[len("s3://"):].partition("/")
    if not bucket or not key:
        raise ValueError(f"malformed s3:// uri: {uri!r}")
    return bucket, key
