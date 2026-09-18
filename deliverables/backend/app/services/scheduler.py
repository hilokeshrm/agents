"""
The jobs and their cadence (WBS 13.2; platform architecture section 08).

Job                 Trigger                 Does
monthly_run         cron, start of month    Full judgment pass over every scorable row
event_runs          stage/status change     Re-scores the changed rows only (queued by record_transition)
stall_sweep         nightly                 Stalls and overdue milestones -> findings + notifications
embedding_refresh   after each ingest       Chunks new notes into L3 memory, expires anything past 8 quarters
calibration_rebuild quarterly               Owner and region bias from resolved outcomes
connector_sync      per connector           Pulls whatever landed in the drop folder
retention           nightly                 Expires semantic memory, reports the episodic tables
dispatch            every few minutes       Sends pending notifications, retries failed webhooks

Two ways to run them. `python -m scripts.run_job <name>` runs one job once
with its own session -- that is what a cron line or a Kubernetes CronJob
calls. `python -m scripts.scheduler` runs the in-process loop for a single
box (no APScheduler dependency: a timer per job). Both call the same
functions, so the behaviour cannot differ between the two.
"""

import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.redis_client import get_redis_client

EVENT_QUEUE = "opptrack:event_runs"


@dataclass(frozen=True)
class Job:
    name: str
    cadence: str            # human description
    interval_seconds: int   # the in-process loop's period
    cron: str               # the equivalent crontab entry
    run: Callable[[Session], dict]


def _version(db: Session):
    from app.services.rubric_versions import current_version, publish_v1

    return current_version(db) or publish_v1(db, published_by="scheduler")


def monthly_run(db: Session) -> dict:
    from app.services.judgment_runs import execute_run

    run = execute_run(db, version=_version(db), actor="scheduler:monthly")
    return {"run_id": run.id, "status": run.status, "mode": run.mode, **run.counts}


def enqueue_event_run(opportunity_id: str) -> None:
    """Called by record_transition: a stage or status change re-scores that row."""
    try:
        get_redis_client().rpush(EVENT_QUEUE, opportunity_id)
    except Exception as exc:  # noqa: BLE001 -- a queue outage never blocks a transition
        print(f"[scheduler] could not enqueue event run: {exc}")


def event_runs(db: Session) -> dict:
    from app.services.judgment_runs import execute_run

    r = get_redis_client()
    ids: list[str] = []
    while True:
        item = r.lpop(EVENT_QUEUE)
        if item is None:
            break
        ids.append(item.decode() if isinstance(item, bytes) else item)
    ids = list(dict.fromkeys(ids))
    if not ids:
        return {"rows": 0}
    run = execute_run(db, version=_version(db), actor="scheduler:event", opportunity_ids=ids)
    return {"rows": len(ids), "run_id": run.id, "status": run.status, **run.counts}


def stall_sweep(db: Session) -> dict:
    from app.services.notifications import notify_review_pending, sweep

    result = sweep(db, as_of=date.today())
    pending = notify_review_pending(db, as_of=date.today())
    return {**vars(result), "review_pending_notices": pending}


def embedding_refresh(db: Session) -> dict:
    from sqlalchemy import select

    from app.db.models.opportunity import Opportunity
    from app.memory import expire, refresh_from_rows

    rows = db.scalars(select(Opportunity)).all()
    written = refresh_from_rows(db, rows, vintage=f"refresh:{date.today().isoformat()}")
    return {"chunks_written": written, "expired": expire(db)}


def calibration_rebuild(db: Session) -> dict:
    from app.services.calibration import rebuild_calibration

    rows = rebuild_calibration(db, as_of=date.today())
    return {"calibration_rows": len(rows), "owners": sorted({r.owner for r in rows if r.owner})}


def connector_sync(db: Session) -> dict:
    """Pulls every file in the connector drop folder (one sub-folder per
    connector) and moves it to `done/` or `failed/`."""
    from app.connectors import CONNECTORS
    from app.connectors._framework import apply_observations

    root = Path(settings.connector_drop_dir)
    summary: dict = {}
    for name, connector in CONNECTORS.items():
        folder = root / name
        if not folder.exists():
            continue
        for path in sorted(p for p in folder.iterdir() if p.is_file()):
            content = path.read_bytes()
            ref = f"{name}:{path.name}"
            try:
                loaded = 0
                if name in ("erp", "disty_pos"):
                    loaded = connector.load_actuals(db, content, ref=ref)
                elif name == "market_data":
                    loaded = connector.load(db, content, ref=ref)
                observations = connector.observations(db, content, ref=ref) if name == "erp" else connector.pull(content, ref=ref)
                result = apply_observations(db, connector.spec, observations, actor=f"scheduler:{name}", ref=ref)
                (folder / "done").mkdir(exist_ok=True)
                path.replace(folder / "done" / path.name)
                summary[ref] = {"loaded": loaded, "applied": result.applied, "reconciliation": result.reconciliation_items}
            except Exception as exc:  # noqa: BLE001 -- one bad file never stops the others
                (folder / "failed").mkdir(exist_ok=True)
                path.replace(folder / "failed" / path.name)
                summary[ref] = {"error": f"{type(exc).__name__}: {exc}"}
    return summary


def retention(db: Session) -> dict:
    from app.services.retention import enforce_retention

    return vars(enforce_retention(db))


def dispatch(db: Session) -> dict:
    from app.services.notifications import dispatch_pending
    from app.services.webhooks import retry_failed

    return {"notifications": dispatch_pending(db), "webhooks_retried": retry_failed(db)}


JOBS: dict[str, Job] = {j.name: j for j in (
    Job("monthly_run", "start of month", 30 * 24 * 3600, "0 2 1 * *", monthly_run),
    Job("event_runs", "every 5 minutes (queue drained)", 300, "*/5 * * * *", event_runs),
    Job("stall_sweep", "nightly", 24 * 3600, "0 3 * * *", stall_sweep),
    Job("embedding_refresh", "after each ingest / nightly", 24 * 3600, "30 3 * * *", embedding_refresh),
    Job("calibration_rebuild", "quarterly", 91 * 24 * 3600, "0 4 1 1,4,7,10 *", calibration_rebuild),
    Job("connector_sync", "hourly (drop folder)", 3600, "15 * * * *", connector_sync),
    Job("retention", "nightly", 24 * 3600, "45 3 * * *", retention),
    Job("dispatch", "every 5 minutes", 300, "*/5 * * * *", dispatch),
)}


def run_job(name: str, *, session_factory=None) -> dict:
    """One job, one session, committed on success and rolled back on failure.
    Records the outcome in the metrics hash so `/metrics` shows the last
    result per job."""
    from app.db.session import SessionLocal
    from app.services.metrics import incr

    job = JOBS[name]
    db = (session_factory or SessionLocal)()
    started = datetime.now(timezone.utc)
    try:
        result = job.run(db)
        db.commit()
        incr(f"job:{name}:ok", 1)
        return {"job": name, "started_at": started.isoformat(), "ok": True, "result": result}
    except Exception as exc:  # noqa: BLE001 -- recorded, then re-raised
        db.rollback()
        incr(f"job:{name}:failed", 1)
        raise
    finally:
        db.close()


def crontab() -> str:
    """The crontab that runs the same jobs from outside the process."""
    return "\n".join(f"{j.cron}  cd /app && python -m scripts.run_job {j.name}" for j in JOBS.values()) + "\n"


def loop(stop: threading.Event | None = None) -> None:  # pragma: no cover -- the long-running process
    stop = stop or threading.Event()
    last: dict[str, float] = {}
    while not stop.is_set():
        now = time.time()
        for job in JOBS.values():
            if now - last.get(job.name, 0) >= job.interval_seconds:
                try:
                    print(f"[scheduler] {job.name}: {run_job(job.name)}")
                except Exception as exc:  # noqa: BLE001
                    print(f"[scheduler] {job.name} failed: {type(exc).__name__}: {exc}")
                last[job.name] = now
        stop.wait(30)
