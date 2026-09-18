"""
Ties the snapshot table (WBS 3.2) to object storage (WBS 9.6): creating a snapshot
uploads the source bytes and records where they landed; reading one fetches them
back. A snapshot is sealed the moment it is created -- nothing here ever re-uploads
under the same id, which is what "immutable once sealed" (WBS 3.2's done-when) means
in practice, and it is why a run over the same snapshot is reproducible.
"""

import hashlib
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.models.snapshot import Snapshot
from app.services.object_storage import get_object, put_object


def create_snapshot(db: Session, content: bytes, source_filename: str, row_counts: dict) -> Snapshot:
    sha256 = hashlib.sha256(content).hexdigest()
    key = f"snapshots/{sha256}/{source_filename}"
    uri = put_object(key, content)

    snapshot = Snapshot(
        sha256=sha256,
        source_uri=uri,
        row_counts=row_counts,
        sealed_at=datetime.now(timezone.utc),
    )
    db.add(snapshot)
    db.flush()
    return snapshot


def read_snapshot_content(db: Session, snapshot_id: str) -> bytes:
    """Round-trips through object storage, not a cache -- this is the function the
    WBS 9.6 done-when means by "re-read months later": no in-process state, no
    reliance on the file still existing wherever it was first uploaded from."""
    snapshot = db.get(Snapshot, snapshot_id)
    if snapshot is None:
        raise ValueError(f"no such snapshot: {snapshot_id}")
    content = get_object(snapshot.source_uri)

    actual_sha256 = hashlib.sha256(content).hexdigest()
    if actual_sha256 != snapshot.sha256:
        raise ValueError(
            f"snapshot {snapshot_id} content does not match its recorded sha256 "
            f"(expected {snapshot.sha256}, got {actual_sha256}) -- object storage "
            "returned something other than what was sealed"
        )
    return content
