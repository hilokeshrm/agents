"""
Outbound notifications (WBS 11.7) and the nightly sweeps that raise them
(WBS 8.5): stalls, overdue milestones, proposals waiting for a reviewer,
lifecycle moves proposed.

A notification is a row first and a message second. The sweeps write rows
with a dedupe key (one stall notice per row per day, not one per run), and
`dispatch_pending` delivers them through the configured channel:

- log      print to the process log (the default; nothing external is provisioned)
- smtp     plain SMTP via settings (host, port, sender)
- webhook  POST to every subscription for the notification kind (WBS 10.13)

Delivery state lives on the row, so a failed send is a visible `failed`, not
a lost message, and a re-dispatch retries only those.
"""

import json
from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models.finding import Finding
from app.db.models.notification import Notification
from app.db.models.opportunity import Opportunity
from app.db.models.proposal import Proposal


def _recipients_for(opp: Opportunity) -> list[str]:
    """The owner, and the managers of the row's region (a role address the
    dispatcher resolves against app_user once provisioning exists)."""
    out = []
    if opp.owner and opp.owner.strip().lower() not in ("", "unassigned"):
        out.append(opp.owner)
    out.append(f"role:manager:{opp.region}")
    return out


def notify(db: Session, *, kind: str, recipients: list[str], subject: str, body: str,
           payload: dict | None = None, dedupe_key: str | None = None) -> list[Notification]:
    written = []
    for recipient in recipients:
        key = f"{dedupe_key}:{recipient}" if dedupe_key else None
        if key and db.scalar(select(Notification.id).where(Notification.dedupe_key == key).limit(1)):
            continue
        n = Notification(kind=kind, recipient=recipient, subject=subject, body=body,
                         payload=payload or {}, dedupe_key=key)
        db.add(n)
        written.append(n)
    db.flush()
    return written


@dataclass
class SweepResult:
    stalls: int
    overdue_milestones: int
    notifications: int
    findings: int


def sweep(db: Session, *, as_of: date | None = None) -> SweepResult:
    """The nightly stall and milestone sweep (WBS 8.5). Runs the milestone/stall
    analysis over the live rows, writes an advisory finding per new stall or
    overdue milestone (one per row per day) and a notification to the owner
    and the region's managers, with the rationale attached."""
    from app.analysis.registry import build_context
    from app.analysis.milestones_and_stalls import run as run_ms

    as_of = as_of or date.today()
    ctx = build_context(db, as_of=as_of)
    result = run_ms(ctx)
    stalls = overdue = findings = notes = 0
    for row in result.rows:
        opp = db.get(Opportunity, row["opportunity_id"])
        if opp is None:
            continue
        if row["kind"] == "stall":
            stalls += 1
            message = (f"{opp.project} has sat in {row['stage']} for {row['days_in_stage']:.0f} days against a "
                       f"median of {row['stage_median_days']:.0f} ({row['multiple']}x; threshold {row['threshold_multiple']}x)")
            key = f"stall:{opp.id}:{as_of.isoformat()}"
            if not db.scalar(select(Finding.id).where(Finding.opportunity_id == opp.id, Finding.rule_id == "STALL",
                                                       Finding.message == message).limit(1)):
                db.add(Finding(opportunity_id=opp.id, snapshot_id=None, rule_id="STALL", severity="advisory", message=message))
                findings += 1
            notes += len(notify(db, kind="stall", recipients=_recipients_for(opp),
                                subject=f"Stalled: {opp.project} in {row['stage']}", body=message,
                                payload={"opportunity_id": opp.id, **{k: v for k, v in row.items() if k != "kind"}},
                                dedupe_key=key))
        elif row["kind"] == "milestone" and row["overdue"]:
            for m in row["milestones"]:
                if not m["overdue"]:
                    continue
                overdue += 1
                message = f"{opp.project}: {m['milestone']} is past due -- \"{m['source_substring']}\" (due {m['date']})"
                if not db.scalar(select(Finding.id).where(Finding.opportunity_id == opp.id, Finding.rule_id == "MILESTONE",
                                                           Finding.message == message).limit(1)):
                    db.add(Finding(opportunity_id=opp.id, snapshot_id=None, rule_id="MILESTONE", severity="advisory", message=message))
                    findings += 1
                notes += len(notify(db, kind="milestone", recipients=_recipients_for(opp),
                                    subject=f"Overdue {m['milestone']}: {opp.project}", body=message,
                                    payload={"opportunity_id": opp.id, **m},
                                    dedupe_key=f"milestone:{opp.id}:{m['milestone']}:{as_of.isoformat()}"))
    db.flush()
    return SweepResult(stalls=stalls, overdue_milestones=overdue, notifications=notes, findings=findings)


def notify_review_pending(db: Session, *, as_of: date | None = None) -> int:
    """One digest per region manager for proposals waiting on a person."""
    as_of = as_of or date.today()
    pending = db.execute(
        select(Proposal, Opportunity).join(Opportunity, Proposal.opportunity_id == Opportunity.id)
        .where(Proposal.status == "pending")
    ).all()
    by_region: dict[str, list] = {}
    for p, o in pending:
        by_region.setdefault(o.region, []).append((p, o))
    written = 0
    for region, items in by_region.items():
        lines = [f"- {o.project}: " + (f"{p.transition['from_value']} -> {p.transition['to_value']}" if p.kind == "transition"
                                       else f"{p.base_confidence:.2f} -> {p.proposed_confidence:.2f}") for p, o in items]
        written += len(notify(
            db, kind="review_pending", recipients=[f"role:manager:{region}"],
            subject=f"{len(items)} proposal(s) awaiting review in {region}", body="\n".join(lines),
            payload={"region": region, "proposal_ids": [p.id for p, _ in items]},
            dedupe_key=f"review_pending:{region}:{as_of.isoformat()}",
        ))
    return written


# --------------------------------------------------------------------------- #
# Delivery
# --------------------------------------------------------------------------- #

def _send_log(n: Notification) -> None:
    print(f"[notify:{n.kind}] to={n.recipient} subject={n.subject!r}")


def _send_smtp(n: Notification) -> None:
    import smtplib
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["From"] = settings.smtp_sender
    msg["To"] = n.recipient if "@" in n.recipient else settings.smtp_sender
    msg["Subject"] = f"[OppTrack] {n.subject}"
    msg.set_content(n.body + "\n\n" + json.dumps(n.payload, indent=2, default=str))
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
        if settings.smtp_starttls:
            smtp.starttls()
        if settings.smtp_username:
            smtp.login(settings.smtp_username, settings.smtp_password or "")
        smtp.send_message(msg)


def _send_webhook(db: Session, n: Notification) -> None:
    from app.services.webhooks import deliver_event

    deliver_event(db, event=f"notification.{n.kind}", payload={
        "recipient": n.recipient, "subject": n.subject, "body": n.body, **n.payload,
    })


def dispatch_pending(db: Session, *, channel: str | None = None, limit: int = 500) -> dict:
    channel = channel or settings.notification_channel
    pending = db.scalars(select(Notification).where(Notification.status.in_(("pending", "failed"))).limit(limit)).all()
    sent = failed = 0
    for n in pending:
        try:
            if channel == "smtp":
                _send_smtp(n)
            elif channel == "webhook":
                _send_webhook(db, n)
            else:
                _send_log(n)
            n.status, n.channel, n.error, n.sent_at = "sent", channel, None, datetime.now(timezone.utc)
            sent += 1
        except Exception as exc:  # noqa: BLE001 -- recorded on the row
            n.status, n.channel, n.error = "failed", channel, f"{type(exc).__name__}: {exc}"
            failed += 1
    db.flush()
    return {"channel": channel, "sent": sent, "failed": failed}
