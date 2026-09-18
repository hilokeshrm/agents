"""
Ask OppTrack -- the assistant (WBS 10.x, the product document's chat panel).

The panel is a reader of the system, not a second path into it. Every tool below
is read-only, and there is deliberately no set_confidence tool, no transition
tool and no create tool: the assistant answers from the same tables the dashboard
renders and quotes the same audit events a reviewer would open. A question that
would require a write is answered with what the person can do instead.

Two modes, the same split app/judgment/rubric.py already uses:

- LIVE: a tool-use loop against Claude. The model never computes a figure -- it
  calls get_rollup / compute_scenario, and those call app/calc/engine.py, so an
  answer in chat and an answer in a board pack come from one function.
- READER (the default): a deterministic reader that recognises a fixed set of
  questions and answers them from the same tools. It says what it matched and
  what it cannot answer. It is not a language model pretending to be small; it
  is a lookup that refuses to guess, which is the honest behaviour when no key
  is configured.

Region scope applies in both modes: the tools take the caller's Actor and run
every query through app/security/roles.py, so the assistant cannot read a row
its caller could not open.
"""

import json
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.calc.engine import portfolio_rollup
from app.services.financials import financials_for
from app.core.config import settings
from app.db.models.confidence_event import ConfidenceEvent
from app.db.models.finding import Finding
from app.db.models.opportunity import Opportunity
from app.db.models.proposal import Proposal
from app.db.models.rubric_version import RubricVersion
from app.security.roles import Actor, scope_opportunities
from app.services.state_transitions import win_rate

SYSTEM_PROMPT = """You are the read-only assistant inside OppTrack, a semiconductor \
design-win pipeline platform. You answer questions about the pipeline by calling the \
supplied tools, which read the same database the rest of the product renders.

Hard rules:
- Never compute a currency figure yourself. Call get_rollup, get_pipeline or \
compute_scenario and quote what they return. Those go through the deterministic calc \
engine; arithmetic you do in your head does not, and the two must not disagree.
- You cannot write. There is no tool to set a confidence, approve a proposal, move a \
stage or create a row. If the person asks for one, say plainly that it is a reviewer \
action you have no tool for, and tell them where in the product to do it.
- Cite what produced a figure: the tool you called, and for a proposal the factors and \
rubric version stored on it. Quote stored rationales verbatim rather than re-deriving them.
- When a tool returns nothing, say so. Do not fill the gap with an estimate.
- Every figure you state must be one a tool returned, and you name the tool next to it, \
e.g. "$30,915K weighted (get_rollup)". A figure with no tool behind it is not allowed."""


@dataclass
class ToolCall:
    name: str
    input: dict
    summary: str
    output: object = None   # retained so grounding can trace every figure to a tool result


@dataclass
class Answer:
    mode: str  # live | reader | refused
    answer: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    model_id: str | None = None
    note: str | None = None
    intent: str = "answer"
    grounded: bool | None = None
    untraceable: list[str] = field(default_factory=list)
    citations: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# The read-only tool surface
# --------------------------------------------------------------------------- #

class Tools:
    def __init__(self, db: Session, actor: Actor) -> None:
        self.db = db
        self.actor = actor
        self.calls: list[ToolCall] = []
        # Every public tool keeps its output on the call record, in both modes,
        # so grounding can trace a quoted figure to the tool that returned it.
        for name in [t["name"] for t in TOOL_SCHEMAS]:
            method = getattr(self, name)

            def wrapped(*args, _m=method, _n=name, **kwargs):
                out = _m(*args, **kwargs)
                if self.calls and self.calls[-1].name == _n and self.calls[-1].output is None:
                    self.calls[-1].output = out
                return out

            setattr(self, name, wrapped)

    # -- helpers ----------------------------------------------------------- #

    def _rows(self, region: str | None = None, design_status: str | None = None) -> list[Opportunity]:
        stmt = scope_opportunities(select(Opportunity), Opportunity, self.actor)
        if region:
            stmt = stmt.where(Opportunity.region == region)
        if design_status:
            stmt = stmt.where(Opportunity.design_status == design_status)
        return list(self.db.scalars(stmt).all())

    @staticmethod
    def _financials(opp: Opportunity, confidence: float | None = None):
        return financials_for(opp, confidence)

    def _record(self, name: str, tool_input: dict, summary: str, output: object = None) -> None:
        self.calls.append(ToolCall(name=name, input=tool_input, summary=summary, output=output))

    # -- tools -------------------------------------------------------------- #

    def get_rollup(self, by: str = "region", region: str | None = None) -> dict:
        rows = self._rows(region=region)
        financials = [self._financials(o) for o in rows]
        rollup = portfolio_rollup(financials)

        if by == "customer":
            grouped: dict[str, dict] = {}
            for f in financials:
                entry = grouped.setdefault(f.customer, {"adjusted_revenue_k": 0.0, "count": 0})
                entry["adjusted_revenue_k"] += f.adjusted_revenue_k
                entry["count"] += 1
            result = {"by": "customer", "groups": grouped}
        elif by == "part":
            grouped = {}
            for f in financials:
                entry = grouped.setdefault(f.part_number, {"adjusted_revenue_k": 0.0, "eau_kpcs": 0.0})
                entry["adjusted_revenue_k"] += f.adjusted_revenue_k
                entry["eau_kpcs"] += f.eau_kpcs
            result = {"by": "part", "groups": grouped}
        elif by == "stage":
            result = {"by": "stage", "groups": rollup["by_stage"]}
        else:
            result = {"by": "region", "groups": rollup["by_region"]}

        result.update({
            "total_adjusted_revenue_k": rollup["total_adjusted_revenue_k"],
            "total_sales_revenue_k": rollup["total_sales_revenue_k"],
            "opportunity_count": len(rows),
            "engine": "app/calc/engine.py",
        })
        self._record("get_rollup", {"by": by, "region": region},
                     f"{len(rows)} rows, ${rollup['total_adjusted_revenue_k']:,.0f}K weighted")
        return result

    def get_pipeline(self, region: str | None = None, design_status: str | None = None) -> dict:
        rows = self._rows(region, design_status)
        out = []
        for opp in rows:
            f = self._financials(opp)
            out.append({
                "opportunity_id": opp.id, "project": opp.project, "customer": opp.customer,
                "region": opp.region, "design_status": opp.design_status, "stage": opp.stage,
                "part_number": opp.part_number, "owner": opp.owner, "confidence": opp.confidence,
                "mp_date": opp.mp_date.isoformat() if opp.mp_date else None,
                "sales_revenue_k": f.sales_revenue_k, "adjusted_revenue_k": f.adjusted_revenue_k,
                "confidence_rationale": opp.confidence_rationale, "evidence": opp.evidence,
                "competitor_part": opp.competitor_part,
            })
        self._record("get_pipeline", {"region": region, "design_status": design_status}, f"{len(out)} rows")
        return {"rows": out, "count": len(out)}

    def get_opportunity(self, query: str) -> dict:
        rows = self._rows()
        match = next((o for o in rows if o.id == query), None) or next(
            (o for o in rows if o.project.lower() == query.strip().lower()), None
        ) or next((o for o in rows if query.strip().lower() in o.project.lower()), None)
        if match is None:
            self._record("get_opportunity", {"query": query}, "no match in scope")
            return {"found": False, "query": query}

        f = self._financials(match)
        proposals = self.db.scalars(
            select(Proposal).where(Proposal.opportunity_id == match.id).order_by(Proposal.created_at.desc())
        ).all()
        self._record("get_opportunity", {"query": query}, f"{match.project}")
        return {
            "found": True, "opportunity_id": match.id, "project": match.project,
            "customer": match.customer, "end_customer": match.end_customer, "region": match.region,
            "owner": match.owner, "design_status": match.design_status, "stage": match.stage,
            "part_number": match.part_number, "confidence": match.confidence,
            "confidence_rationale": match.confidence_rationale, "evidence": match.evidence,
            "competitor_part": match.competitor_part,
            "mp_date": match.mp_date.isoformat() if match.mp_date else None,
            "eau_kpcs": match.eau_kpcs, "disty_asp": match.disty_asp,
            "sales_revenue_k": f.sales_revenue_k, "adjusted_revenue_k": f.adjusted_revenue_k,
            "open_proposal_id": next((p.id for p in proposals if p.status == "pending"), None),
            "proposal_count": len(proposals),
        }

    def get_proposal(self, proposal_id: str | None = None, opportunity_id: str | None = None) -> dict:
        stmt = select(Proposal)
        if proposal_id:
            stmt = stmt.where(Proposal.id == proposal_id)
        elif opportunity_id:
            stmt = stmt.where(Proposal.opportunity_id == opportunity_id)
        else:
            return {"found": False, "error": "needs a proposal_id or an opportunity_id"}

        proposal = self.db.scalars(stmt.order_by(Proposal.created_at.desc())).first()
        if proposal is None:
            self._record("get_proposal", {"proposal_id": proposal_id, "opportunity_id": opportunity_id}, "no match")
            return {"found": False}

        opp = self.db.get(Opportunity, proposal.opportunity_id)
        if opp is None or not self.actor.in_scope(opp.region):
            return {"found": False}

        version = self.db.get(RubricVersion, proposal.rubric_version_id)
        self._record("get_proposal", {"proposal_id": proposal.id}, f"{opp.project}, {proposal.status}")
        return {
            "found": True, "proposal_id": proposal.id, "project": opp.project,
            "status": proposal.status, "base_confidence": proposal.base_confidence,
            "proposed_confidence": proposal.proposed_confidence,
            "band_crossing": proposal.band_crossing,
            "rubric_version": version.label if version else None,
            "factors": proposal.factors,
            "base_adjusted_revenue_k": self._financials(opp, proposal.base_confidence).adjusted_revenue_k,
            "proposed_adjusted_revenue_k": self._financials(opp, proposal.proposed_confidence).adjusted_revenue_k,
        }

    def get_audit_events(self, opportunity_id: str | None = None, limit: int = 20) -> dict:
        visible = {o.id: o.project for o in self._rows()}
        stmt = select(ConfidenceEvent).order_by(ConfidenceEvent.occurred_at.desc()).limit(limit)
        if opportunity_id:
            stmt = stmt.where(ConfidenceEvent.opportunity_id == opportunity_id)
        events = [
            {
                "at": e.occurred_at.isoformat(), "type": e.event_type,
                "project": visible.get(e.opportunity_id), "actor": e.actor, "role": e.actor_role,
                "from": e.base_confidence, "to": e.resulting_confidence,
                "reason_code": e.reason_code, "note": e.note, "model_id": e.model_id,
            }
            for e in self.db.scalars(stmt).all() if e.opportunity_id in visible
        ]
        self._record("get_audit_events", {"opportunity_id": opportunity_id, "limit": limit},
                     f"{len(events)} events")
        return {"events": events, "count": len(events)}

    def compute_scenario(self, overrides: list | None = None, include_pending_proposals: bool = False) -> dict:
        rows = self._rows()
        by_id = {o.id: o for o in rows}
        scenario: dict[str, float] = {}

        if include_pending_proposals:
            for proposal in self.db.scalars(select(Proposal).where(Proposal.status == "pending")).all():
                if proposal.opportunity_id in by_id:
                    scenario[proposal.opportunity_id] = proposal.proposed_confidence
        for override in overrides or []:
            key = override.get("opportunity_id")
            if key in by_id:
                scenario[key] = float(override["confidence"])
            else:
                match = next((o for o in rows if o.project.lower() == str(key).lower()), None)
                if match:
                    scenario[match.id] = float(override["confidence"])

        base = sum(self._financials(o).adjusted_revenue_k for o in rows)
        after = sum(
            self._financials(o, scenario.get(o.id)).adjusted_revenue_k for o in rows
        )
        changed = [
            {
                "project": by_id[oid].project, "region": by_id[oid].region,
                "from": by_id[oid].confidence, "to": value,
                "delta_k": self._financials(by_id[oid], value).adjusted_revenue_k
                           - self._financials(by_id[oid]).adjusted_revenue_k,
            }
            for oid, value in scenario.items()
        ]
        self._record("compute_scenario",
                     {"overrides": overrides, "include_pending_proposals": include_pending_proposals},
                     f"${base:,.0f}K -> ${after:,.0f}K")
        return {
            "base_weighted_k": base, "scenario_weighted_k": after, "delta_k": after - base,
            "changed": changed, "persisted": False, "engine": "app/calc/engine.py",
        }

    def list_findings(self, severity: str | None = None, limit: int = 50) -> dict:
        stmt = select(Finding).order_by(Finding.occurred_at.desc()).limit(limit)
        if severity:
            stmt = stmt.where(Finding.severity == severity)
        findings = [
            {"rule_id": f.rule_id, "severity": f.severity, "message": f.message,
             "at": f.occurred_at.isoformat()}
            for f in self.db.scalars(stmt).all()
        ]
        self._record("list_findings", {"severity": severity}, f"{len(findings)} findings")
        return {"findings": findings, "count": len(findings)}

    def get_win_rate(self) -> dict:
        region = self.actor.regions[0] if len(self.actor.regions) == 1 else None
        rate = win_rate(self.db, region=region)
        self._record("get_win_rate", {"region": region},
                     f"{rate.won}/{rate.resolved} resolved")
        return {
            "won": rate.won, "lost": rate.lost, "resolved": rate.resolved, "rate": rate.rate,
            "source": "state_history event stream, not an estimate",
        }

    def get_review_queue(self) -> dict:
        rows = {o.id: o for o in self._rows()}
        proposals = [
            p for p in self.db.scalars(select(Proposal).where(Proposal.status == "pending")).all()
            if p.opportunity_id in rows
        ]
        self._record("get_review_queue", {}, f"{len(proposals)} pending")
        return {
            "count": len(proposals),
            "proposals": [
                {
                    "proposal_id": p.id, "project": rows[p.opportunity_id].project,
                    "region": rows[p.opportunity_id].region,
                    "from": p.base_confidence, "to": p.proposed_confidence,
                    "band_crossing": p.band_crossing,
                }
                for p in proposals
            ],
        }


TOOL_SCHEMAS = [
    {
        "name": "get_rollup",
        "description": "Weighted and unweighted pipeline revenue grouped by region, stage, customer "
                       "or part, computed by the deterministic calc engine. Use this for any total.",
        "input_schema": {
            "type": "object",
            "properties": {
                "by": {"type": "string", "enum": ["region", "stage", "customer", "part"]},
                "region": {"type": "string", "description": "optional filter to one region"},
            },
        },
    },
    {
        "name": "get_pipeline",
        "description": "The opportunity rows themselves with their computed revenue, confidence, "
                       "owner, rationale and evidence. Use when the answer needs specific rows.",
        "input_schema": {
            "type": "object",
            "properties": {
                "region": {"type": "string"},
                "design_status": {"type": "string"},
            },
        },
    },
    {
        "name": "get_opportunity",
        "description": "One opportunity by id or project name, with its computed figures and whether "
                       "it has an open proposal.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
    {
        "name": "get_proposal",
        "description": "A confidence proposal with its stored factors, each factor's rationale, and "
                       "which guard rejected or clipped it. Quote these verbatim; do not re-derive them.",
        "input_schema": {
            "type": "object",
            "properties": {
                "proposal_id": {"type": "string"},
                "opportunity_id": {"type": "string"},
            },
        },
    },
    {
        "name": "get_audit_events",
        "description": "The append-only confidence_event stream: proposals, approvals, overrides and "
                       "rejections, with actor, role and reason code.",
        "input_schema": {
            "type": "object",
            "properties": {
                "opportunity_id": {"type": "string"},
                "limit": {"type": "integer"},
            },
        },
    },
    {
        "name": "compute_scenario",
        "description": "Recompute weighted pipeline under hypothetical confidences. Nothing is "
                       "written. Set include_pending_proposals to answer 'what if I approve the queue'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "overrides": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "opportunity_id": {"type": "string", "description": "id or project name"},
                            "confidence": {"type": "number"},
                        },
                        "required": ["opportunity_id", "confidence"],
                    },
                },
                "include_pending_proposals": {"type": "boolean"},
            },
        },
    },
    {
        "name": "list_findings",
        "description": "Validation findings recorded against imported snapshots.",
        "input_schema": {
            "type": "object",
            "properties": {
                "severity": {"type": "string", "enum": ["blocking", "advisory"]},
                "limit": {"type": "integer"},
            },
        },
    },
    {
        "name": "get_win_rate",
        "description": "Win rate computed from the state_history event stream.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_review_queue",
        "description": "Proposals currently waiting for a reviewer, in the caller's region scope.",
        "input_schema": {"type": "object", "properties": {}},
    },
]


def _dispatch(tools: Tools, name: str, tool_input: dict):
    handler = getattr(tools, name, None)
    if handler is None:
        return {"error": f"unknown tool {name!r}"}
    output = handler(**tool_input)
    # Keep the output on the last recorded call so grounding can trace figures.
    if tools.calls and tools.calls[-1].name == name and tools.calls[-1].output is None:
        tools.calls[-1].output = output
    return output


# --------------------------------------------------------------------------- #
# Live mode: a tool-use loop
# --------------------------------------------------------------------------- #

MAX_TOOL_TURNS = 8


def _ask_live(question: str, tools: Tools) -> Answer:
    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    messages: list[dict] = [{"role": "user", "content": question}]

    for _ in range(MAX_TOOL_TURNS):
        response = client.messages.create(
            model=settings.judgment_model,
            max_tokens=16000,
            thinking={"type": "adaptive"},
            system=SYSTEM_PROMPT,
            tools=TOOL_SCHEMAS,
            messages=messages,
        )
        if response.stop_reason != "tool_use":
            text = "\n\n".join(b.text for b in response.content if b.type == "text")
            return Answer(mode="live", answer=text.strip(), tool_calls=tools.calls,
                          model_id=settings.judgment_model)

        messages.append({"role": "assistant", "content": response.content})
        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            output = _dispatch(tools, block.name, dict(block.input))
            results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps(output, default=str),
            })
        messages.append({"role": "user", "content": results})

    return Answer(
        mode="live", answer="I ran out of tool turns before finishing that answer. Ask something "
                            "narrower, or open the Runs & audit screen for the underlying events.",
        tool_calls=tools.calls, model_id=settings.judgment_model,
    )


# --------------------------------------------------------------------------- #
# Reader mode: deterministic, and explicit about what it cannot do
# --------------------------------------------------------------------------- #

CAPABILITIES = [
    "the weighted pipeline, by region, stage, customer or part",
    "concentration -- which row carries what share of a region",
    "what the review queue would do to the weighted total if it were all approved",
    "why a proposal says what it says, factor by factor, including the rejected ones",
    "win rate, computed from the state_history stream",
    "an opportunity's own figures, rationale and evidence",
]

_WRITE_WORDS = ("set ", "change ", "approve", "reject", "override", "move ", "update ", "delete", "create ")


def _fmt_k(value: float) -> str:
    return f"${value:,.0f}K"


def _ask_reader(question: str, tools: Tools) -> Answer:
    q = question.lower().strip()

    if any(word in q for word in _WRITE_WORDS) and "if" not in q and "what if" not in q:
        return Answer(
            mode="reader",
            answer="I can't write anything -- there is no tool here that sets a confidence, resolves "
                   "a proposal or moves a stage; those are reviewer actions on the Review queue and "
                   "the opportunity page. I can tell you what the change would do to the numbers "
                   "first: ask me to compute it.",
            tool_calls=tools.calls,
        )

    if "queue" in q or ("approve" in q and "if" in q):
        scenario = tools.compute_scenario(include_pending_proposals=True)
        queue = tools.get_review_queue()
        if queue["count"] == 0:
            return Answer(mode="reader", answer="The review queue is empty in your region scope, so "
                                                "approving it would change nothing.", tool_calls=tools.calls)
        lines = [
            f"Approving all {queue['count']} pending proposals moves the weighted pipeline from "
            f"{_fmt_k(scenario['base_weighted_k'])} to {_fmt_k(scenario['scenario_weighted_k'])}, "
            f"a {_fmt_k(scenario['delta_k'])} change.",
            "",
            "Row by row:",
        ]
        for row in sorted(scenario["changed"], key=lambda r: abs(r["delta_k"]), reverse=True):
            lines.append(f"  {row['project']} ({row['region']}): {row['from']:.2f} -> {row['to']:.2f}, "
                         f"{_fmt_k(row['delta_k'])}")
        lines.append("")
        lines.append("Computed by re-running the calc engine over the proposed values -- the same "
                     "function behind the dashboard figure. Nothing was written.")
        return Answer(mode="reader", answer="\n".join(lines), tool_calls=tools.calls)

    if "concentration" in q or "concentrated" in q or "share" in q:
        pipeline = tools.get_pipeline()
        if not pipeline["rows"]:
            return Answer(mode="reader", answer="No opportunities in your region scope.", tool_calls=tools.calls)
        by_region: dict[str, float] = {}
        for row in pipeline["rows"]:
            by_region[row["region"]] = by_region.get(row["region"], 0.0) + row["adjusted_revenue_k"]
        lines = ["Largest single row as a share of its region's weighted pipeline:"]
        for region, total in sorted(by_region.items(), key=lambda kv: -kv[1]):
            rows = [r for r in pipeline["rows"] if r["region"] == region]
            top = max(rows, key=lambda r: r["adjusted_revenue_k"])
            share = (top["adjusted_revenue_k"] / total * 100) if total else 0.0
            lines.append(f"  {region}: {top['project']} is {_fmt_k(top['adjusted_revenue_k'])} of "
                         f"{_fmt_k(total)}, {share:.1f}% across {len(rows)} rows")
        lines.append("")
        lines.append("Figures from the calc engine. The concentration threshold that would make one of "
                     "these a finding is not ratified yet (WBS 1.1), so this is the measurement, not a verdict.")
        return Answer(mode="reader", answer="\n".join(lines), tool_calls=tools.calls)

    if "win rate" in q or "win-rate" in q:
        rate = tools.get_win_rate()
        if rate["resolved"] == 0:
            return Answer(mode="reader",
                          answer="Nothing has resolved to a win or a loss yet, so there is no win rate to "
                                 "report -- not a rate of zero, an absence of resolved outcomes.",
                          tool_calls=tools.calls)
        return Answer(mode="reader",
                      answer=f"{rate['won']} won, {rate['lost']} lost, {rate['resolved']} resolved -- "
                             f"{rate['rate'] * 100:.0f}%. Computed from the state_history event stream, "
                             f"not estimated.",
                      tool_calls=tools.calls)

    if "why" in q or "proposal" in q or "factor" in q:
        target = _guess_project(q, tools)
        if target:
            proposal = tools.get_proposal(opportunity_id=target["opportunity_id"])
            if proposal.get("found"):
                return Answer(mode="reader", answer=_explain_proposal(proposal), tool_calls=tools.calls)
            return Answer(mode="reader",
                          answer=f"{target['project']} has no proposal on it. Its entered confidence is "
                                 f"{target['confidence']:.2f}, rationale: "
                                 f"“{target['confidence_rationale']}”. Request a review on the "
                                 f"opportunity page to have the rubric score it.",
                          tool_calls=tools.calls)

    if "pipeline" in q or "weighted" in q or "total" in q or "revenue" in q or "forecast" in q:
        by = "region"
        for candidate in ("stage", "customer", "part"):
            if candidate in q:
                by = candidate
        rollup = tools.get_rollup(by=by)
        lines = [f"Weighted pipeline: {_fmt_k(rollup['total_adjusted_revenue_k'])} across "
                 f"{rollup['opportunity_count']} opportunities "
                 f"({_fmt_k(rollup['total_sales_revenue_k'])} unweighted).", "", f"By {by}:"]
        for name, group in sorted(
            rollup["groups"].items(),
            key=lambda kv: -(kv[1].get("adjusted_revenue_k", 0.0) if isinstance(kv[1], dict) else 0.0),
        ):
            amount = group.get("adjusted_revenue_k", 0.0) if isinstance(group, dict) else 0.0
            lines.append(f"  {name}: {_fmt_k(amount)}")
        lines.append("")
        lines.append("From app/calc/engine.py, the same function the dashboard calls.")
        return Answer(mode="reader", answer="\n".join(lines), tool_calls=tools.calls)

    target = _guess_project(q, tools)
    if target:
        return Answer(
            mode="reader",
            answer=f"{target['project']} -- {target['customer']} / {target['end_customer']}, "
                   f"{target['region']}, {target['design_status']} at {target['stage']}, part "
                   f"{target['part_number']}, owner {target['owner']}.\n"
                   f"Confidence {target['confidence']:.2f}: “{target['confidence_rationale']}”\n"
                   f"Sales revenue {_fmt_k(target['sales_revenue_k'])}, weighted "
                   f"{_fmt_k(target['adjusted_revenue_k'])}."
                   + (f"\nOpen proposal: {target['open_proposal_id']}" if target["open_proposal_id"] else ""),
            tool_calls=tools.calls,
        )

    return Answer(
        mode="reader",
        answer="No model key is configured, so I am running as a deterministic reader and I did not "
               "recognise that question. What I can answer from the live tables:\n"
               + "\n".join(f"  - {c}" for c in CAPABILITIES)
               + "\n\nSet ANTHROPIC_API_KEY and JUDGMENT_MODE=live for open-ended questions.",
        tool_calls=tools.calls,
    )


def _guess_project(question: str, tools: Tools) -> dict | None:
    for row in tools.get_pipeline()["rows"]:
        if row["project"].lower() in question:
            return tools.get_opportunity(row["project"])
    return None


def _explain_proposal(proposal: dict) -> str:
    fired = [f for f in proposal["factors"] if f.get("accepted") and f.get("applies")]
    dark = [f for f in proposal["factors"] if f.get("guard") == "not_assessable"]
    rejected = [f for f in proposal["factors"] if not f.get("accepted") and f.get("guard") != "not_assessable"]

    lines = [
        f"{proposal['project']}: {proposal['base_confidence']:.2f} -> "
        f"{proposal['proposed_confidence']:.2f} (rubric version {proposal['rubric_version']}, "
        f"status {proposal['status']}).",
        f"Weighted revenue {_fmt_k(proposal['base_adjusted_revenue_k'])} -> "
        f"{_fmt_k(proposal['proposed_adjusted_revenue_k'])}.",
        "",
    ]
    if fired:
        lines.append("Factors that fired:")
        for f in fired:
            clipped = (f" (model asked for {f['clipped_from']:+.1f}pp; clipped to the published cap)"
                       if f.get("clipped_from") is not None else "")
            lines.append(f"  {f['key']} {f['confidence_adjustment_pct']:+.1f}pp{clipped}: {f['rationale']}")
    else:
        lines.append("No factor fired.")
    if dark:
        lines.append("")
        lines.append("Not assessable on this row:")
        for f in dark:
            lines.append(f"  {f['key']}: {f['detail']}")
    if rejected:
        lines.append("")
        lines.append("Rejected by a guard:")
        for f in rejected:
            lines.append(f"  {f['key']} ({f['guard']}): {f['detail']}")
    lines.append("")
    lines.append("Quoted from the stored proposal, not re-derived.")
    return "\n".join(lines)


def ask(db: Session, actor: Actor, question: str, *, request_id: str | None = None) -> Answer:
    """Classify, answer, ground, log (WBS 14.2, 14.4, 14.5)."""
    from app.services.assistant_guard import check_grounding, classify

    intent = classify(question)
    if intent.kind != "answer":
        answer = Answer(mode="refused", answer=intent.message or "", intent=intent.kind, grounded=True)
        _log(db, actor, question, answer, request_id)
        return answer

    tools = Tools(db, actor)
    if settings.judgment_mode == "live" and settings.anthropic_api_key:
        try:
            answer = _ask_live(question, tools)
        except Exception as exc:  # noqa: BLE001 -- reported, never silently downgraded
            answer = _ask_reader(question, tools)
            answer.note = (f"The live model call failed ({type(exc).__name__}: {exc}); this answer came "
                           f"from the deterministic reader instead.")
    else:
        answer = _ask_reader(question, tools)

    outputs = [c.output for c in answer.tool_calls if c.output is not None]
    grounding = check_grounding(answer.answer, outputs) if outputs or answer.mode == "live" else None
    if grounding is not None:
        answer.grounded = grounding.grounded
        answer.untraceable = grounding.untraceable
        if not grounding.grounded:
            answer.note = ((answer.note + " ") if answer.note else "") + (
                f"Ungrounded: {', '.join(grounding.untraceable)} could not be traced to a tool result -- "
                f"treat those figures as unverified and open the screen instead."
            )
    else:
        answer.grounded = True
    answer.citations = [f"{c.name}({json.dumps(c.input, default=str)})" for c in answer.tool_calls]
    _log(db, actor, question, answer, request_id)
    return answer


def _log(db: Session, actor: Actor, question: str, answer: Answer, request_id: str | None) -> None:
    from app.db.models.conversation import Conversation

    try:
        db.add(Conversation(
            actor=actor.user_id, actor_role=actor.role, request_id=request_id, question=question,
            answer=answer.answer, mode=answer.mode, intent=answer.intent,
            tool_calls=[{"name": c.name, "input": c.input, "summary": c.summary} for c in answer.tool_calls],
            grounded=answer.grounded, untraceable=answer.untraceable, model_id=answer.model_id,
        ))
        db.commit()
    except Exception as exc:  # noqa: BLE001 -- logging never breaks an answer
        db.rollback()
        print(f"[assistant] conversation log failed: {type(exc).__name__}: {exc}")
