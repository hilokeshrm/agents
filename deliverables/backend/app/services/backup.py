"""
Backup and restore (WBS 13.5) -- the drill behind the seven-year retention
promise. A backup is the database plus the object store (source workbooks and
exports) in one folder with a manifest that names what it holds and the hash
of each part. Restore refuses a manifest whose hashes do not match.

SQLite: the online backup API, so a live dev database copies consistently.
Postgres: pg_dump / pg_restore (custom format) via subprocess -- the tools
have to be on PATH; the code does not reinvent them.
"""

import hashlib
import json
import shutil
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import settings


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _sqlite_path(url: str) -> Path | None:
    if url.startswith("sqlite:///"):
        return Path(url[len("sqlite:///"):])
    return None


def backup(target_dir: str | Path, *, database_url: str | None = None, objects_dir: str | Path | None = None) -> dict:
    database_url = database_url or settings.database_url
    objects_dir = Path(objects_dir or "data/objects")
    target = Path(target_dir) / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target.mkdir(parents=True, exist_ok=False)
    parts = {}

    sqlite_file = _sqlite_path(database_url)
    if sqlite_file is not None:
        out = target / "database.sqlite"
        src = sqlite3.connect(str(sqlite_file))
        dst = sqlite3.connect(str(out))
        with dst:
            src.backup(dst)
        src.close()
        dst.close()
        parts["database.sqlite"] = _sha256(out)
    else:
        out = target / "database.pgdump"
        subprocess.run(["pg_dump", "--format=custom", f"--file={out}", database_url], check=True)
        parts["database.pgdump"] = _sha256(out)

    if objects_dir.exists():
        archive = shutil.make_archive(str(target / "objects"), "zip", root_dir=objects_dir)
        parts["objects.zip"] = _sha256(Path(archive))

    manifest = {"created_at": datetime.now(timezone.utc).isoformat(), "database_url_kind": "sqlite" if sqlite_file else "postgres",
                "parts": parts}
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return {"backup_dir": str(target), **manifest}


def verify(backup_dir: str | Path) -> dict:
    folder = Path(backup_dir)
    manifest = json.loads((folder / "manifest.json").read_text())
    mismatches = [name for name, digest in manifest["parts"].items() if _sha256(folder / name) != digest]
    return {"ok": not mismatches, "mismatches": mismatches, "parts": list(manifest["parts"])}


def restore(backup_dir: str | Path, *, database_url: str | None = None, objects_dir: str | Path | None = None) -> dict:
    """Restores into the given database and object folder. Refuses a backup
    that fails verification. For SQLite the target file is replaced; for
    Postgres pg_restore --clean is used."""
    check = verify(backup_dir)
    if not check["ok"]:
        raise ValueError(f"backup failed verification: {check['mismatches']}")
    folder = Path(backup_dir)
    database_url = database_url or settings.database_url
    objects_dir = Path(objects_dir or "data/objects")
    sqlite_file = _sqlite_path(database_url)
    if sqlite_file is not None:
        sqlite_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(folder / "database.sqlite", sqlite_file)
    else:
        subprocess.run(["pg_restore", "--clean", "--if-exists", f"--dbname={database_url}", str(folder / "database.pgdump")], check=True)
    if (folder / "objects.zip").exists():
        if objects_dir.exists():
            shutil.rmtree(objects_dir)
        shutil.unpack_archive(str(folder / "objects.zip"), str(objects_dir), "zip")
    return {"restored_from": str(folder), **check}
