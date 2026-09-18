"""
Dev tools (not a WBS task -- local debugging aid only, added on request). Lets
the running app introspect its own database, config and log files: every
table via SQLAlchemy's inspector (so a new model needs no change here to show
up), every *.log file under deliverables/logs/ discovered by globbing rather
than a fixed list (so a new role's frontend log shows up the same way), and a
one-shot /status summary for a dashboard tile.

Goes through the same Depends(get_db) every other router uses, not a raw global
engine import -- that is what lets the test suite's DB override reach this
router too, and it is the correct way to reach the live database either way.

Deliberately unauthenticated, matching the rest of this dev-only build (WBS 9.4
SSO doesn't exist yet). Do not expose this router past a local machine.
"""

import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db

router = APIRouter(prefix="/dev", tags=["dev"])

LOGS_DIR = Path(__file__).resolve().parents[4] / "logs"
BACKEND_DIR = Path(__file__).resolve().parents[3]

# Process start, for the uptime figure on /status -- this module is imported
# once at app boot, so this is as close to "server started" as it gets without
# threading a timestamp through main.py.
START_TIME = time.time()


# dev_up.ps1 always writes these two; kept as fixed entries so a source
# named "backend"/"frontend" 200s with an empty-lines note before the process
# has produced any output yet, rather than 404ing until the first line lands.
KNOWN_LOGS = {"backend": LOGS_DIR / "backend.log", "frontend": LOGS_DIR / "frontend.log"}


def _discover_logs() -> dict[str, Path]:
    """KNOWN_LOGS plus every *.log under logs/, keyed by filename with the
    .log suffix stripped (backend.log -> "backend", frontend-owner.err.log ->
    "frontend-owner.err"). Re-globbed on every call so a log started after
    boot -- a new role's frontend, say -- shows up without a restart."""
    found = {p.stem: p for p in sorted(LOGS_DIR.glob("*.log"))} if LOGS_DIR.is_dir() else {}
    return {**KNOWN_LOGS, **found}


@router.get("/tables")
def list_tables(db: Session = Depends(get_db)) -> list[dict]:
    inspector = inspect(db.get_bind())
    tables = []
    for name in sorted(inspector.get_table_names()):
        count = db.execute(text(f'SELECT COUNT(*) FROM "{name}"')).scalar()
        tables.append({"name": name, "row_count": count})
    return tables


@router.get("/tables/{table_name}")
def get_table(table_name: str, limit: int = 200, db: Session = Depends(get_db)) -> dict:
    inspector = inspect(db.get_bind())
    if table_name not in inspector.get_table_names():
        raise HTTPException(status_code=404, detail=f"No such table: {table_name!r}")

    columns = [c["name"] for c in inspector.get_columns(table_name)]
    result = db.execute(text(f'SELECT * FROM "{table_name}" LIMIT :limit'), {"limit": limit})
    rows = [[str(v) if v is not None else None for v in row] for row in result.fetchall()]
    return {"table": table_name, "columns": columns, "rows": rows}


@router.get("/logs")
def list_logs() -> list[dict]:
    out = []
    for source, path in _discover_logs().items():
        exists = path.exists()
        stat = path.stat() if exists else None
        out.append({
            "source": source,
            "path": str(path),
            "exists": exists,
            "size_bytes": stat.st_size if stat else 0,
            "modified_at": stat.st_mtime if stat else None,
        })
    return sorted(out, key=lambda r: r["source"])


@router.get("/logs/{source}")
def get_log(source: str, lines: int = 300) -> dict:
    path = _discover_logs().get(source)
    if path is None:
        raise HTTPException(status_code=404, detail=f"Unknown log source: {source!r}. GET /dev/logs lists what exists.")
    if not path.exists():
        return {"source": source, "path": str(path), "lines": [], "note": "log file does not exist yet"}
    content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return {"source": source, "path": str(path), "lines": content[-lines:]}


@router.get("/status")
def status(db: Session = Depends(get_db)) -> dict:
    """One-shot snapshot for a dashboard tile: DB shape and size, non-secret
    config, log inventory, process uptime. Nothing here that isn't already
    reachable through /dev/tables, /dev/logs and the .env.example -- this just
    collects it into one call."""
    inspector = inspect(db.get_bind())
    table_names = inspector.get_table_names()
    total_rows = 0
    for name in table_names:
        total_rows += db.execute(text(f'SELECT COUNT(*) FROM "{name}"')).scalar() or 0

    url = make_url(settings.database_url)
    db_file_size = None
    if url.get_backend_name() == "sqlite" and url.database:
        db_path = Path(url.database)
        if not db_path.is_absolute():
            db_path = BACKEND_DIR / db_path
        if db_path.exists():
            db_file_size = db_path.stat().st_size

    logs = list_logs()

    return {
        "uptime_seconds": time.time() - START_TIME,
        "db": {
            "dialect": url.get_backend_name(),
            "url": url.render_as_string(hide_password=True),
            "table_count": len(table_names),
            "total_rows": total_rows,
            "file_size_bytes": db_file_size,
        },
        "config": {
            "auth_mode": settings.auth_mode,
            "judgment_mode": settings.judgment_mode,
            "judgment_backend": settings.judgment_backend,
            "redis_backend": settings.redis_backend,
            "storage_backend": settings.storage_backend,
            "notification_channel": settings.notification_channel,
            "otp_delivery": settings.otp_delivery,
            "monthly_budget_usd": settings.monthly_budget_usd,
        },
        "logs": {
            "count": len(logs),
            "total_size_bytes": sum(entry["size_bytes"] for entry in logs),
        },
    }
