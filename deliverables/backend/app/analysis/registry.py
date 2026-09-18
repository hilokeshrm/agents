"""
Analysis registry (WBS 6.1, Layer 4).

Analyses are deterministic reports over figures the calc engine already
computed. They are separated from the judgment layer deliberately: an analysis
states a fact about the portfolio, a rubric factor argues about a confidence
level, and conflating the two is how a report becomes an opinion.

Adding an analysis needs no registration code: any module in this package that
exports `ANALYSIS = Analysis(...)` is discovered. Each declares `requires` as
ParamSpec ids. Two things decide whether it may run:

- the static registry (app/registry/parameters.py): a proposed parameter that
  no source carries yet leaves the analysis dark, with the id named;
- the run context's `available` set: parameters that exist in principle but
  depend on data being present -- targets (G1), actuals (A1), state history
  (H1) -- are declared available by the context only when the table has rows.

So the run output lists what ran, what was dark, and which parameter was
missing, and a blocked analysis lights up on its own the day its input lands.
"""

import importlib
import pkgutil
from dataclasses import dataclass, field
from datetime import date
from typing import Callable

from app.calc.engine import ProjectFinancials
from app.registry.param_spec import ParamRegistry
from app.registry.parameters import PARAMS


@dataclass
class AnalysisContext:
    financials: list[ProjectFinancials]          # scorable rows only (blocking rows excluded)
    opportunities: list                          # the ORM rows behind them, same order
    as_of: date
    db: object = None                            # a Session when history-backed inputs are wanted
    available: set[str] = field(default_factory=set)   # dynamic parameter ids present for this run
    excluded_count: int = 0
    targets: list = field(default_factory=list)
    actuals: list = field(default_factory=list)


@dataclass
class AnalysisResult:
    key: str
    label: str
    status: str                                  # live | partial | dark
    headline: str                                # the one figure a reviewer can act on
    figures: dict = field(default_factory=dict)
    rows: list[dict] = field(default_factory=list)   # the rows the analysis is talking about
    missing: list[str] = field(default_factory=list)
    note: str = ""


@dataclass(frozen=True)
class Analysis:
    key: str
    label: str
    requires: frozenset                          # ParamSpec ids
    run: Callable[[AnalysisContext], AnalysisResult]
    description: str = ""


_REGISTRY: dict[str, Analysis] = {}


def register(analysis: Analysis) -> None:
    _REGISTRY[analysis.key] = analysis


def discover() -> dict[str, Analysis]:
    """Imports every module in app.analysis that exports ANALYSIS. Idempotent."""
    import app.analysis as pkg

    for info in pkgutil.iter_modules(pkg.__path__):
        if info.name.startswith("_") or info.name == "registry":
            continue
        module = importlib.import_module(f"app.analysis.{info.name}")
        analysis = getattr(module, "ANALYSIS", None)
        if isinstance(analysis, Analysis):
            register(analysis)
    return dict(_REGISTRY)


def missing_for(analysis: Analysis, registry: ParamRegistry, available: set[str]) -> list[str]:
    missing = []
    for param_id in sorted(analysis.requires):
        spec = registry.get(param_id)  # KeyError for an unregistered id: a bug, not a dark input
        if spec.present_in_current_file or param_id in available:
            continue
        missing.append(param_id)
    return missing


def available_for(registry: ParamRegistry = PARAMS, available: set[str] | None = None) -> list[Analysis]:
    discover()
    return [a for a in _REGISTRY.values() if not missing_for(a, registry, available or set())]


def run_all(ctx: AnalysisContext, registry: ParamRegistry = PARAMS) -> dict:
    """Runs every eligible analysis; reports what ran and what was dark and why.
    A dark analysis still returns a result object so the screen can show the
    parameter it is waiting on rather than an empty slot."""
    discover()
    ran: dict[str, AnalysisResult] = {}
    dark: dict[str, AnalysisResult] = {}
    for key, analysis in sorted(_REGISTRY.items()):
        missing = missing_for(analysis, registry, ctx.available)
        if missing:
            dark[key] = AnalysisResult(
                key=key, label=analysis.label, status="dark", headline="not runnable",
                missing=missing,
                note=f"waiting on {', '.join(f'{m} ({registry.get(m).name})' for m in missing)}",
            )
            continue
        ran[key] = analysis.run(ctx)
    return {"ran": ran, "dark": dark}


def build_context(db, *, as_of: date | None = None, actor=None) -> AnalysisContext:
    """The context a run over the live rows gets: scorable financials, the
    rows behind them, and the dynamic availability set read from the tables."""
    from sqlalchemy import select

    from app.calc.engine import compute_project_financials
    from app.calc.severity import BLOCKING, classify_severity
    from app.db.models.actual import Actual
    from app.db.models.opportunity import Opportunity
    from app.db.models.state_history import StateHistory
    from app.db.models.target import Target
    from app.security.roles import scope_opportunities
    from app.services.financials import engine_row
    from app.services.rubric_versions import effective_version, is_forbidden

    stmt = select(Opportunity).order_by(Opportunity.created_at)
    if actor is not None:
        stmt = scope_opportunities(stmt, Opportunity, actor)
    rows = list(db.scalars(stmt).all())
    version = effective_version(db)
    scorable, excluded = [], 0
    for o in rows:
        row = engine_row(o)
        if classify_severity(row) == BLOCKING or is_forbidden(version, o.design_status, o.stage):
            excluded += 1
            continue
        scorable.append(o)
    financials = [compute_project_financials(engine_row(o)) for o in scorable]

    available: set[str] = set()
    if rows:
        # Direct-entry fields the workbook never carried but every platform
        # row does (NOT NULL): owner, rationale, the minted id, NRE charge.
        available.update({"V26", "V27", "V28", "V29"})
    if db.scalar(select(StateHistory.id).where(StateHistory.reason_code.is_not(None)).limit(1)) is not None:
        available.add("V25")
    targets = list(db.scalars(select(Target)).all())
    actuals = list(db.scalars(select(Actual)).all())
    if targets:
        available.update({"G1", "G2"})
    if actuals:
        available.update({"A1", "A2", "A3"})
    if db.scalar(select(StateHistory.id).limit(1)) is not None:
        available.update({"H1", "H2"})
    from app.db.models.calibration import Calibration
    if db.scalar(select(Calibration.id).limit(1)) is not None:
        available.update({"H3", "O1"})
    from app.db.models.market_programme import MarketProgramme
    if db.scalar(select(MarketProgramme.id).limit(1)) is not None:
        available.update({"P1", "P2"})
    return AnalysisContext(
        financials=financials, opportunities=scorable, as_of=as_of or date.today(), db=db,
        available=available, excluded_count=excluded, targets=targets, actuals=actuals,
    )
