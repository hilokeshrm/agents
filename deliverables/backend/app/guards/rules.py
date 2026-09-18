"""
Validation rules V-a .. V-i (WBS 4.1, 4.3, 4.4) -- the data-quality checks that
turn section 03 of the build specification from a written list into generated
output.

Each rule declares the fields it requires and goes dark rather than throwing
when one is absent. Rules are checks, not judgment: they answer whether the
file is internally consistent, and every one is explainable to a sales owner
in a sentence (the `plain` text below is that sentence).

The nine rules cover the twelve documented findings F-01..F-12:

  V-a  Required field missing or TBD in a numeric field    F-07, F-08
  V-b  Forbidden (Design Status, Stage) pairing            -- (Matrix A, decision #10)
  V-c  Confidence is not a function of stage               F-09
  V-d  EAU implausible against Unit/Set                    F-05
  V-e  Same part, different EAU across tabs                F-06
  V-f  Roll-up does not compute                            F-01, F-02, F-03, F-04
  V-g  Value on no canonical list                          -- (region, status)
  V-h  Column or value that reaches no formula             F-10, F-11
  V-i  Part number reused across rows                      F-12

Severity: BLOCKING excludes a row from totals (row scope) or says a total
cannot be trusted (tab or workbook scope); ADVISORY annotates and lets the
row through; COSMETIC is worth fixing and changes nothing. F-09 is advisory
here rather than the specification's blocking: with Matrix A published, the
per-row deviation is J-04's job in the judgment layer, and the file-level
inconsistency is a fact to report, not a reason to drop three rows from the
pipeline.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable

from app.intake.coerce import coerce_numeric
from app.intake.xlsx_reader import RawRow, Workbook
from app.judgment.matrix_b import EARLY_OPTIMISM_TOLERANCE
from app.registry.enums import (
    NOT_A_DESIGN_STATUS,
    canonicalize_design_status,
    canonicalize_region,
    canonicalize_stage,
)

BLOCKING, ADVISORY, COSMETIC = "blocking", "advisory", "cosmetic"
ROW, TAB, WORKBOOK = "row", "tab", "workbook"

TBD_STRINGS = frozenset({"tbd", "n/a", "na", "?"})
NUMERIC_FIELDS = ("eau_kpcs", "unit_set", "disty_asp", "resale_asp", "confidence")
# Typed non-numeric fields where "TBD" is also an absence, not a value.
TYPED_TEXT_FIELDS = ("mp_date", "competitor_part")
# Fields a row needs before C1 can be computed at all (app/calc/severity.py).
REQUIRED_FOR_REVENUE = ("customer", "project", "disty_asp")
# Ten million vehicle sets a year for one programme is a third of world
# light-vehicle production (build spec, F-05).
IMPLAUSIBLE_KSETS = 10_000.0
# Same part, EAU differing by more than this factor between tabs (F-06 is 40x).
EAU_DISAGREEMENT_FACTOR = 5.0


@dataclass(frozen=True)
class Finding:
    rule_id: str
    severity: str
    scope: str
    message: str
    tab: str | None = None
    row_number: int | None = None
    cell: str | None = None
    field: str | None = None
    raw_value: str | None = None
    spec_ref: str | None = None   # F-01..F-12 when the finding is a documented one

    @property
    def where(self) -> str:
        return self.cell or (f"{self.tab}!row {self.row_number}" if self.tab and self.row_number else self.tab or "workbook")


@dataclass(frozen=True)
class Rule:
    id: str
    label: str
    plain: str                      # the one-sentence explanation for a sales owner
    severity: str
    scope: str
    requires: tuple[str, ...]       # row fields, or "@footers" / "@matrix_a" for non-row inputs
    run: Callable[["RuleContext"], list[Finding]]


@dataclass
class RuleContext:
    rows: list[RawRow]
    footers: list[RawRow] = field(default_factory=list)
    # (design_status, stage) -> allowed. None means no Matrix A is available,
    # which leaves V-b dark rather than guessing what is forbidden.
    matrix_a: dict[tuple[str, str], bool] | None = None
    # (design_status, stage) -> baseline confidence, for V-c's comparison.
    baselines: dict[tuple[str, str], float] | None = None


def _is_tbd(value: object) -> bool:
    return isinstance(value, str) and value.strip().lower() in TBD_STRINGS


def _num(value: object) -> float | None:
    if value is None or _is_tbd(value):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return coerce_numeric(str(value)).value


def _has(row: RawRow, name: str) -> bool:
    return row.fields.get(name) is not None


def _dark(rule_requires: tuple[str, ...], row: RawRow) -> bool:
    return any(not _has(row, r) for r in rule_requires if not r.startswith("@"))


# --------------------------------------------------------------------------- #
# V-a  required field missing / TBD in a numeric field
# --------------------------------------------------------------------------- #

def _v_a(ctx: RuleContext) -> list[Finding]:
    out: list[Finding] = []
    for row in ctx.rows:
        is_nre = str(row.fields.get("design_status") or "").strip().lower() == "nre"
        # An NRE line has no mass-production date by nature; "N/A" there is
        # correct, not a placeholder.
        typed = NUMERIC_FIELDS + (("competitor_part",) if is_nre else TYPED_TEXT_FIELDS)
        tbd_fields = [f for f in typed if _is_tbd(row.fields.get(f))]
        for f in tbd_fields:
            kind = "a numeric field" if f in NUMERIC_FIELDS else ("a date field" if f == "mp_date" else "a typed field")
            out.append(Finding(
                rule_id="V-a", severity=ADVISORY, scope=ROW, tab=row.tab, row_number=row.row_number,
                cell=row.coordinate(f), field=f, raw_value=str(row.fields.get(f)),
                message=f"{f} holds the text {row.fields.get(f)!r} in {kind}; coerced to null, never to zero",
                spec_ref="F-07",
            ))
        if row.tab in ("ProjectTrack", "Mass Production", "Design Lost", "Funnel"):
            missing = [f for f in REQUIRED_FOR_REVENUE if row.fields.get(f) is None or _is_tbd(row.fields.get(f))]
            if missing and not (tbd_fields and set(missing) <= set(tbd_fields)):
                out.append(Finding(
                    rule_id="V-a", severity=BLOCKING, scope=ROW, tab=row.tab, row_number=row.row_number,
                    field=missing[0], raw_value=None,
                    message=f"row carries {row.fields.get('design_status')!r} with region "
                            f"{row.fields.get('region')!r} and EAU {row.fields.get('eau_kpcs')!r} but no "
                            f"{', '.join(missing)} -- Sales Revenue computes to zero, so it is excluded and counted",
                    spec_ref="F-08" if row.tab == "ProjectTrack" else None,
                ))
    return out


# --------------------------------------------------------------------------- #
# V-b  forbidden pairing (Matrix A)
# --------------------------------------------------------------------------- #

def _v_b(ctx: RuleContext) -> list[Finding]:
    if ctx.matrix_a is None:
        return []
    out: list[Finding] = []
    for row in ctx.rows:
        status = canonicalize_design_status(str(row.fields.get("design_status") or ""))
        stage = canonicalize_stage(str(row.fields.get("stage") or "")) if _has(row, "stage") else None
        if status is None or stage is None:
            continue
        if ctx.matrix_a.get((status, stage)) is False:
            out.append(Finding(
                rule_id="V-b", severity=BLOCKING, scope=ROW, tab=row.tab, row_number=row.row_number,
                cell=row.coordinate("stage"), field="stage", raw_value=f"{status} / {stage}",
                message=f"{status} at {stage} is a forbidden pairing in Matrix A; the row is excluded until corrected",
            ))
    return out


# --------------------------------------------------------------------------- #
# V-c  confidence is not a function of stage
# --------------------------------------------------------------------------- #

def _v_c(ctx: RuleContext) -> list[Finding]:
    by_cell: dict[tuple[str, str], list[tuple[RawRow, float]]] = defaultdict(list)
    for row in ctx.rows:
        if not (_has(row, "design_status") and _has(row, "stage") and _has(row, "confidence")):
            continue
        status = canonicalize_design_status(str(row.fields["design_status"]))
        stage = canonicalize_stage(str(row.fields["stage"]))
        conf = _num(row.fields["confidence"])
        if status and stage and conf is not None:
            by_cell[(status, stage)].append((row, conf))
    out: list[Finding] = []
    for (status, stage), entries in by_cell.items():
        values = sorted({c for _, c in entries})
        if len(values) > 1:
            cells = ", ".join(r.coordinate("confidence") or f"row {r.row_number}" for r, _ in entries)
            baseline = (ctx.baselines or {}).get((status, stage))
            out.append(Finding(
                rule_id="V-c", severity=ADVISORY, scope=TAB, tab=entries[0][0].tab,
                cell=cells, field="confidence",
                raw_value=", ".join(f"{v:.2f}" for v in values),
                message=f"{len(entries)} rows are {status} at {stage} and carry confidence "
                        f"{', '.join(f'{v:.2f}' for v in values)} -- confidence is not a function of stage"
                        + (f"; Matrix A baseline for the cell is {baseline:.2f}" if baseline is not None else ""),
                spec_ref="F-09",
            ))
        elif ctx.baselines:
            baseline = ctx.baselines.get((status, stage))
            for row, conf in entries:
                if baseline is not None and abs(conf - baseline) > EARLY_OPTIMISM_TOLERANCE:
                    out.append(Finding(
                        rule_id="V-c", severity=ADVISORY, scope=ROW, tab=row.tab, row_number=row.row_number,
                        cell=row.coordinate("confidence"), field="confidence", raw_value=f"{conf:.2f}",
                        message=f"{status} at {stage} entered at {conf:.2f} against a Matrix A baseline of "
                                f"{baseline:.2f}; the judgment layer will be asked to justify the deviation",
                    ))
    return out


# --------------------------------------------------------------------------- #
# V-d  EAU plausibility
# --------------------------------------------------------------------------- #

def _v_d(ctx: RuleContext) -> list[Finding]:
    out: list[Finding] = []
    for row in ctx.rows:
        eau, per_set = _num(row.fields.get("eau_kpcs")), _num(row.fields.get("unit_set"))
        if eau is None or per_set is None or per_set <= 0:
            continue
        ksets = eau / per_set
        if ksets > IMPLAUSIBLE_KSETS:
            out.append(Finding(
                rule_id="V-d", severity=BLOCKING, scope=ROW, tab=row.tab, row_number=row.row_number,
                cell=f"{row.coordinate('eau_kpcs')}, {row.coordinate('unit_set')}", field="eau_kpcs",
                raw_value=f"{eau:,.0f} Kpcs / {per_set:g} per set",
                message=f"{row.fields.get('part_number')}: {eau:,.0f} Kpcs at {per_set:g} units per set implies "
                        f"{ksets/1000:,.1f}M vehicle sets a year -- either the EAU or the Unit/Set value is wrong",
                spec_ref="F-05",
            ))
    return out


# --------------------------------------------------------------------------- #
# V-e  same part, different EAU across tabs
# --------------------------------------------------------------------------- #

def _v_e(ctx: RuleContext) -> list[Finding]:
    """Same part, same account, different tabs. The account is part of the key:
    Zeus and Montana share AX01 but not a programme, and comparing them would
    be a part-reuse observation (V-i), not a contradiction."""
    by_part: dict[tuple[str, str], list[tuple[RawRow, float]]] = defaultdict(list)
    for row in ctx.rows:
        part = row.fields.get("part_number")
        status = str(row.fields.get("design_status") or "").strip().lower()
        eau = _num(row.fields.get("eau_kpcs"))
        if not part or _is_tbd(part) or eau is None or status in NOT_A_DESIGN_STATUS:
            continue
        account = str(row.fields.get("end_customer") or row.fields.get("customer") or "").strip().lower()
        by_part[(str(part).strip(), account)].append((row, eau))
    out: list[Finding] = []
    out.extend(_v_e_dates(ctx))
    for (part, _account), entries in by_part.items():
        tabs = {r.tab for r, _ in entries}
        if len(tabs) < 2:
            continue
        lo = min(entries, key=lambda e: e[1])
        hi = max(entries, key=lambda e: e[1])
        if lo[1] > 0 and hi[1] / lo[1] > EAU_DISAGREEMENT_FACTOR:
            out.append(Finding(
                rule_id="V-e", severity=BLOCKING, scope=WORKBOOK, tab=None,
                cell=f"{hi[0].coordinate('eau_kpcs')} vs {lo[0].coordinate('eau_kpcs')}", field="eau_kpcs",
                raw_value=f"{hi[1]:,.0f} vs {lo[1]:,.0f}",
                message=f"{part} reads {hi[1]:,.0f} Kpcs on {hi[0].tab} and {lo[1]:,.0f} Kpcs on {lo[0].tab} "
                        f"-- a {hi[1]/lo[1]:,.0f}x gap that only makes sense if one is programme-lifetime "
                        f"and the other annual; both are kept and neither is chosen",
                spec_ref="F-06",
            ))
    return out


def _v_e_dates(ctx: RuleContext) -> list[Finding]:
    """The same part and account carrying different M/P (SoP) dates on two
    tabs -- the "SoP dates that disagree across sheets" half of WBS 4.4. Dates
    are compared at month precision after coercion; an unparseable date is a
    V-a matter, not a disagreement."""
    from app.intake.coerce import coerce_date

    by_key: dict[tuple[str, str], list[tuple[RawRow, object]]] = defaultdict(list)
    for row in ctx.rows:
        # Funnel names the module and FCST_Revenue the vehicle programme for
        # the same part; those are the two tabs whose dates should agree.
        # ProjectTrack rows sharing a part are different sockets (V-i).
        if row.tab not in ("Funnel", "FCST_Revenue"):
            continue
        part = row.fields.get("part_number")
        status = str(row.fields.get("design_status") or "").strip().lower()
        raw = row.fields.get("mp_date")
        if not part or _is_tbd(part) or raw is None or _is_tbd(raw) or status in NOT_A_DESIGN_STATUS:
            continue
        parsed = raw if hasattr(raw, "year") else coerce_date(str(raw)).value
        if parsed is None:
            continue
        account = str(row.fields.get("end_customer") or row.fields.get("customer") or "").strip().lower()
        by_key[(str(part).strip(), account)].append((row, parsed))
    out: list[Finding] = []
    for (part, _account), entries in by_key.items():
        if len({r.tab for r, _ in entries}) < 2:
            continue
        months = {(d.year, d.month) for _, d in entries}
        if len(months) > 1:
            listed = "; ".join(f"{r.tab} {r.fields.get('project')}: {d.strftime('%b %Y')}" for r, d in entries)
            out.append(Finding(
                rule_id="V-e", severity=ADVISORY, scope=WORKBOOK, tab=None,
                cell=", ".join(r.coordinate("mp_date").split("!")[1] if r.coordinate("mp_date") else "" for r, _ in entries),
                field="mp_date", raw_value=listed,
                message=f"{part}: M/P date disagrees across tabs ({listed}); the earliest programme start is "
                        f"not necessarily the socket's -- both are kept and the row is flagged",
            ))
    return out


# --------------------------------------------------------------------------- #
# V-f  roll-up does not compute
# --------------------------------------------------------------------------- #

def _range_rows(formula: str) -> tuple[int, int] | None:
    """Rows spanned by a =SUM(X5:X20) formula, or None."""
    import re

    m = re.search(r"SUM\(\$?([A-Z]+)\$?(\d+):\$?([A-Z]+)\$?(\d+)\)", formula, re.I)
    if not m:
        return None
    return int(m.group(2)), int(m.group(4))


def _v_f(ctx: RuleContext) -> list[Finding]:
    out: list[Finding] = []
    footers = ctx.footers
    if not footers:
        return out
    footer_rows = {f.row_number for f in footers}
    total_row = next((f for f in footers if "total" in str(f.fields.get("region", "")).lower()), None)
    regional = [f for f in footers if f is not total_row]

    for f in regional:
        label = str(f.fields.get("region"))
        ref_cells = [c for c in f.cells.values() if c.is_formula and "#REF!" in c.formula]
        if ref_cells:
            out.append(Finding(
                rule_id="V-f", severity=BLOCKING, scope=TAB, tab=f.tab, row_number=f.row_number,
                cell=", ".join(c.coordinate.split("!")[1] for c in ref_cells[:3]) + ("..." if len(ref_cells) > 3 else ""),
                field="roll-up", raw_value="#REF!",
                message=f"{label} roll-up: {len(ref_cells)} cells are =SUM(#REF!) -- the references are gone",
                spec_ref="F-01",
            ))
        for name, c in f.cells.items():
            if not c.is_formula or "#REF!" in c.formula:
                continue
            span = _range_rows(c.formula)
            if span is None:
                continue
            lo, hi = span
            swallowed = sorted(r for r in footer_rows if lo <= r <= hi and r != f.row_number)
            if swallowed:
                names = ", ".join(str(next(x for x in footers if x.row_number == r).fields.get("region")) for r in swallowed)
                # A range that runs from the first data row and swallows exactly
                # one subtotal double-counts it (F-02); one that starts inside the
                # data and swallows several is a shifted range (F-03).
                spec = "F-02" if lo <= 5 and len(swallowed) == 1 else "F-03"
                out.append(Finding(
                    rule_id="V-f", severity=BLOCKING, scope=TAB, tab=f.tab, row_number=f.row_number,
                    cell=c.coordinate.split("!")[1], field=name, raw_value=c.formula,
                    message=f"{label} {name} is {c.formula}: the range includes the {names} roll-up row(s), "
                            f"so it double-counts "
                            + ("Korea" if spec == "F-02" else "other regions' subtotals"),
                    spec_ref=spec,
                ))
    if total_row is not None:
        bad = [c for c in total_row.cells.values() if c.is_formula and c.is_error]
        if bad:
            out.append(Finding(
                rule_id="V-f", severity=BLOCKING, scope=WORKBOOK, tab=total_row.tab, row_number=total_row.row_number,
                cell=", ".join(c.coordinate.split("!")[1] for c in bad), field="roll-up", raw_value="#REF!",
                message=f"{total_row.fields.get('region')} inherits every error above, so the headline "
                        f"number does not compute ({len(bad)} of its cells are #REF!)",
                spec_ref="F-04",
            ))
    return out


# --------------------------------------------------------------------------- #
# V-g  value on no canonical list
# --------------------------------------------------------------------------- #

def _v_g(ctx: RuleContext) -> list[Finding]:
    out: list[Finding] = []
    for row in ctx.rows:
        region = row.fields.get("region")
        if region is not None and canonicalize_region(str(region)) is None:
            out.append(Finding(
                rule_id="V-g", severity=BLOCKING, scope=ROW, tab=row.tab, row_number=row.row_number,
                cell=row.coordinate("region"), field="region", raw_value=str(region),
                message=f"region {region!r} is on nobody's list (Europe, Taiwan, Japan, Korea, India, US, Other); "
                        f"not invented as a new region",
            ))
        status = row.fields.get("design_status")
        if status is not None and canonicalize_design_status(str(status)) is None:
            key = str(status).strip().lower()
            if key == "nre":
                continue  # a line-item type, split out by app/calc/nre.py, not a status finding
            out.append(Finding(
                rule_id="V-g", severity=ADVISORY, scope=ROW, tab=row.tab, row_number=row.row_number,
                cell=row.coordinate("design_status"), field="design_status", raw_value=str(status),
                message=f"design status {status!r} is not a status; the row has no lifecycle position",
            ))
    return out


# --------------------------------------------------------------------------- #
# V-h  column or value that reaches no formula
# --------------------------------------------------------------------------- #

def _v_h(ctx: RuleContext) -> list[Finding]:
    out: list[Finding] = []
    funnel = [r for r in ctx.rows if r.tab == "Funnel" and _has(r, "fcst_flag")]
    if funnel:
        values = sorted({str(r.fields["fcst_flag"]) for r in funnel})
        out.append(Finding(
            rule_id="V-h", severity=ADVISORY, scope=TAB, tab="Funnel",
            cell=f"{funnel[0].coordinate('fcst_flag')}:{funnel[-1].coordinate('fcst_flag').split('!')[1]}",
            field="fcst_flag", raw_value=", ".join(values),
            message=f"Funnel column headed FCST holds {', '.join(values)} on {len(funnel)} rows; it reaches no "
                    f"formula and is defined nowhere",
            spec_ref="F-10",
        ))
    return out


# --------------------------------------------------------------------------- #
# V-i  part number reuse
# --------------------------------------------------------------------------- #

def _v_i(ctx: RuleContext) -> list[Finding]:
    out: list[Finding] = []
    by_tab_part: dict[tuple[str, str], list[RawRow]] = defaultdict(list)
    for row in ctx.rows:
        part = row.fields.get("part_number")
        status = str(row.fields.get("design_status") or "").strip().lower()
        if part and not _is_tbd(part) and status not in NOT_A_DESIGN_STATUS:
            by_tab_part[(row.tab, str(part).strip())].append(row)
    for (tab, part), rows in by_tab_part.items():
        if len(rows) > 1:
            total = len([r for r in ctx.rows if r.tab == tab and r.fields.get("part_number")])
            out.append(Finding(
                rule_id="V-i", severity=ADVISORY, scope=TAB, tab=tab, field="part_number", raw_value=part,
                cell=", ".join(r.coordinate("part_number").split("!")[1] for r in rows),
                message=f"{part} appears on {len(rows)} of {total} {tab} rows ({', '.join(str(r.fields.get('project')) for r in rows)}); "
                        f"deliberate or not, it changes how silicon demand aggregates for capacity planning",
                spec_ref="F-12",
            ))
    return out


RULES: tuple[Rule, ...] = (
    Rule("V-a", "Required field missing or TBD",
         "A number field holds text, or a row is missing something revenue cannot be computed without.",
         BLOCKING, ROW, ("design_status",), _v_a),
    Rule("V-b", "Forbidden status/stage pairing",
         "The Design Status and Stage on this row cannot go together under the agreed table.",
         BLOCKING, ROW, ("design_status", "stage", "@matrix_a"), _v_b),
    Rule("V-c", "Confidence is not a function of stage",
         "Rows at the same status and stage carry different confidence numbers, or sit off the agreed baseline.",
         ADVISORY, TAB, ("design_status", "stage", "confidence"), _v_c),
    Rule("V-d", "EAU implausible against Unit/Set",
         "Dividing the annual volume by units per vehicle gives more vehicles than a programme can build.",
         BLOCKING, ROW, ("eau_kpcs", "unit_set"), _v_d),
    Rule("V-e", "Same part, different EAU across tabs",
         "The same part number carries very different volumes on two tabs; one is probably lifetime, one annual.",
         BLOCKING, WORKBOOK, ("part_number", "eau_kpcs"), _v_e),
    Rule("V-f", "Roll-up does not compute",
         "A regional or company total is broken: a reference is gone or a range sums the wrong rows.",
         BLOCKING, TAB, ("@footers",), _v_f),
    Rule("V-g", "Value on no canonical list",
         "A region or status is spelled in a way that matches nothing on the agreed list.",
         BLOCKING, ROW, ("region",), _v_g),
    Rule("V-h", "Column reaches no formula",
         "A column is filled in on every row and used by nothing.",
         ADVISORY, TAB, ("fcst_flag",), _v_h),
    Rule("V-i", "Part number reused",
         "One part number appears on several rows of the same tab.",
         ADVISORY, TAB, ("part_number",), _v_i),
)

BY_ID: dict[str, Rule] = {r.id: r for r in RULES}


def run_rules(ctx: RuleContext, rule_ids: tuple[str, ...] | None = None) -> tuple[list[Finding], dict[str, str]]:
    """Runs every rule (or the named ones). Returns the findings and a
    dark-report: rule id -> why it did not run, for rules whose non-row input
    (Matrix A, footers) is absent. Row-level requires are checked per row
    inside each rule, so a rule with some assessable rows still runs."""
    findings: list[Finding] = []
    dark: dict[str, str] = {}
    for rule in RULES:
        if rule_ids and rule.id not in rule_ids:
            continue
        if "@matrix_a" in rule.requires and ctx.matrix_a is None:
            dark[rule.id] = "no Matrix A available"
            continue
        if "@footers" in rule.requires and not ctx.footers:
            dark[rule.id] = "no roll-up rows on this input"
            continue
        findings.extend(rule.run(ctx))
    return findings, dark


def context_from_workbook(wb: Workbook, *, matrix_a=None, baselines=None) -> RuleContext:
    rows = wb.rows()
    footers = [f for t in wb.tabs.values() for f in t.footers]
    return RuleContext(rows=rows, footers=footers, matrix_a=matrix_a, baselines=baselines)
