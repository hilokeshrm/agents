"""
Import wizard and findings view (WBS 10.11, over 3.1/3.2/4.5/4.6).

Two calls, in this order and only this order: a dry run that seals the file into
a snapshot and reports what would fail, then a commit that re-reads those exact
bytes from object storage and creates only the rows that passed. The commit
takes a snapshot id, not a second upload -- so what gets written is what a person
approved, not a file that may have changed between the two clicks.
"""

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.calc.severity import BLOCKING
from app.db.models.finding import Finding
from app.db.models.opportunity import Opportunity
from app.db.models.snapshot import Snapshot
from app.db.session import get_db
from app.security.roles import Actor, require
from app.services.imports import commit_rows, parse_bytes, persist_findings, validate_rows
from app.services.snapshots import create_snapshot, read_snapshot_content
from app.services.rubric_versions import effective_version

router = APIRouter(prefix="/imports", tags=["imports"])

MAX_PREVIEW_ROWS = 500


class FindingRead(BaseModel):
    rule_id: str
    severity: str
    field: str | None
    raw_value: str | None
    message: str


class PreviewRowRead(BaseModel):
    index: int
    values: dict
    findings: list[FindingRead]
    blocking: bool


class DryRunRead(BaseModel):
    snapshot_id: str
    sha256: str
    filename: str
    headers: list[str]
    mapping: dict[str, str]
    unmapped_headers: list[str]
    row_count: int
    would_create: int
    would_block: int
    advisory_count: int
    findings_stored: int
    rows: list[PreviewRowRead]


class CommitRead(BaseModel):
    snapshot_id: str
    created: int
    blocked: int
    opportunity_ids: list[str]


def _preview_read(rows) -> list[PreviewRowRead]:
    return [
        PreviewRowRead(
            index=r.index,
            values={k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in r.values.items()},
            findings=[FindingRead(**vars(f)) for f in r.findings],
            blocking=r.blocking,
        )
        for r in rows[:MAX_PREVIEW_ROWS]
    ]


@router.post("/dry-run", response_model=DryRunRead)
async def dry_run(
    file: UploadFile = File(...),
    mapping_json: str | None = Form(default=None),
    db: Session = Depends(get_db),
    actor: Actor = Depends(require("create_edit_opportunity")),
) -> DryRunRead:
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="empty file")

    try:
        parsed = parse_bytes(content, file.filename or "upload.csv")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    mapping = parsed.mapping
    if mapping_json:
        import json

        override = json.loads(mapping_json)
        unknown = [h for h in override if h not in parsed.headers]
        if unknown:
            raise HTTPException(status_code=400, detail=f"mapping names headers not in the file: {unknown}")
        mapping = override

    if not mapping:
        raise HTTPException(
            status_code=400,
            detail="no column in this file maps to an intake field -- map them by hand before the dry run",
        )

    existing = list(db.scalars(select(Opportunity)).all())
    preview = validate_rows(parsed, mapping, effective_version(db), existing)
    snapshot = create_snapshot(
        db, content, file.filename or "upload.csv",
        row_counts={"rows": len(parsed.rows), "sheet": file.filename or "upload.csv"},
    )
    stored = persist_findings(db, snapshot.id, preview)
    db.commit()

    return DryRunRead(
        snapshot_id=snapshot.id, sha256=snapshot.sha256, filename=file.filename or "upload.csv",
        headers=parsed.headers, mapping=mapping, unmapped_headers=parsed.unmapped_headers,
        row_count=len(preview),
        would_create=sum(1 for r in preview if not r.blocking),
        would_block=sum(1 for r in preview if r.blocking),
        advisory_count=sum(1 for r in preview for f in r.findings if f.severity != BLOCKING),
        findings_stored=stored,
        rows=_preview_read(preview),
    )


@router.post("/{snapshot_id}/commit", response_model=CommitRead)
def commit(
    snapshot_id: str,
    mapping_json: str | None = Form(default=None),
    db: Session = Depends(get_db),
    actor: Actor = Depends(require("create_edit_opportunity")),
) -> CommitRead:
    snapshot = db.get(Snapshot, snapshot_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Snapshot not found")

    try:
        # Round-trips through object storage and re-checks the sha256 -- the
        # commit validates the same bytes the dry run did, not a re-upload.
        content = read_snapshot_content(db, snapshot_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    filename = snapshot.source_uri.rsplit("/", 1)[-1]
    parsed = parse_bytes(content, filename)
    mapping = parsed.mapping
    if mapping_json:
        import json

        mapping = json.loads(mapping_json)

    existing = list(db.scalars(select(Opportunity)).all())
    preview = validate_rows(parsed, mapping, effective_version(db), existing)
    created = commit_rows(db, preview, actor=actor.user_id, snapshot_id=snapshot_id)
    db.commit()

    return CommitRead(
        snapshot_id=snapshot_id,
        created=len(created),
        blocked=sum(1 for r in preview if r.blocking),
        opportunity_ids=[o.id for o in created],
    )


class SnapshotRead(BaseModel):
    id: str
    sha256: str
    source_uri: str
    row_counts: dict
    captured_at: str
    sealed_at: str | None
    finding_count: int
    blocking_count: int


@router.get("", response_model=list[SnapshotRead])
def list_snapshots(db: Session = Depends(get_db)) -> list[SnapshotRead]:
    findings: dict[str, list[Finding]] = {}
    for finding in db.scalars(select(Finding)).all():
        findings.setdefault(finding.snapshot_id, []).append(finding)

    out = []
    for snapshot in db.scalars(select(Snapshot).order_by(Snapshot.captured_at.desc())).all():
        rows = findings.get(snapshot.id, [])
        out.append(SnapshotRead(
            id=snapshot.id, sha256=snapshot.sha256, source_uri=snapshot.source_uri,
            row_counts=snapshot.row_counts, captured_at=snapshot.captured_at.isoformat(),
            sealed_at=snapshot.sealed_at.isoformat() if snapshot.sealed_at else None,
            finding_count=len(rows),
            blocking_count=sum(1 for f in rows if f.severity == BLOCKING),
        ))
    return out


@router.get("/{snapshot_id}/findings", response_model=list[FindingRead])
def snapshot_findings(snapshot_id: str, db: Session = Depends(get_db)) -> list[FindingRead]:
    rows = db.scalars(
        select(Finding).where(Finding.snapshot_id == snapshot_id).order_by(Finding.occurred_at)
    ).all()
    if not rows and db.get(Snapshot, snapshot_id) is None:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    return [
        FindingRead(rule_id=f.rule_id, severity=f.severity, field=None, raw_value=None, message=f.message)
        for f in rows
    ]

@router.get("/workbook-report")
def workbook_report_endpoint(actor: Actor = Depends(require("create_edit_opportunity"))) -> dict:
    """WBS 4.5 / 10.11: the Phase 0 findings report over the canonical
    workbook (settings.workbook_path), the same thing
    `python -m scripts.findings_report` prints, as JSON for the Findings view."""
    from pathlib import Path

    from app.core.config import settings
    from app.guards.report import workbook_report

    path = Path(settings.workbook_path)
    if not path.is_absolute():
        path = (Path(__file__).resolve().parents[3] / settings.workbook_path).resolve()
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"workbook not found at {path}")
    # Reading the workbook twice (values and formulas) takes a second or two;
    # the report only changes when the file does, so it is cached by mtime.
    key = (str(path), path.stat().st_mtime_ns)
    if _REPORT_CACHE.get("key") != key:
        _REPORT_CACHE["key"], _REPORT_CACHE["report"] = key, workbook_report(path).as_dict()
    return _REPORT_CACHE["report"]


_REPORT_CACHE: dict = {}
