"""
Judgment bench — the rewrite of judgment.py, with the guards from section 06
of the Opportunity Tracking build specification actually implemented.

What is different from judgment.py:

  1. MATRIX A IS CONFIG, NOT PROSE. Baseline confidence per (Design Status,
     Stage) cell is a table the model reads, not something it infers. This is
     what stops J-01 docking Aphrodite for a pairing David's rules allow, and
     J-04 reading DVT as "early". Those two misfires were 44% of the whole
     calibration effect on the first live run.
  2. A 0.95 CEILING. apply_confidence_adjustment clamps to [0,1] and both
     design wins sit at 1.00, so any positive support was discarded and the
     layer could only ever move the total down. The band is [0.05, 0.95] here,
     which gives J-03 somewhere to put its points.
  3. PORTFOLIO CONTEXT. score() takes the whole pipeline, so J-05 concentration
     can actually be computed. Under the old one-row signature it could never
     fire at all.
  4. SCHEMA ON THE REQUEST. A markdown fence took out all nine projects on the
     first live run and fell back to MOCK silently. The reply shape is now
     constrained server-side.
  5. NO SILENT MOCK. A failed call raises. It never substitutes hard-coded
     numbers behind a successful-looking run.
  6. CAPS AND BAND CHECKS IN CODE. Per-factor caps, a 20pp per-run cap, the
     hard clamp, and a band-crossing check that routes to review rather than
     auto-applying.

Usage:
    python judgment_bench.py               # score the sample pipeline, print the effect
    python judgment_bench.py --diagnose    # probe the API feature by feature
    python judgment_bench.py --serve       # browser UI on http://localhost:8775
"""

import argparse
import json
import os
import sys

from calc_engine import compute_project_financials, portfolio_rollup

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

_DIR = os.path.dirname(os.path.abspath(__file__))
KEYFILE = os.path.join(_DIR, ".anthropic_key")
ENVFILE = os.path.join(_DIR, ".env")

RUBRIC_VERSION = "opptrack-matrix/2026-08-19"
PROMPT_VERSION = "opptrack-judgment/2026-08-19"
DEFAULT_MODEL = "claude-opus-5"
PER_RUN_CAP_PP = 20.0            # spec 06: total movement per row, per run
CONF_FLOOR, CONF_CEIL = 0.05, 0.95


def load_dotenv(path=ENVFILE):
    """Python does not read .env by itself. A key sitting in one next to the
    script does nothing until something loads it. Existing env vars win."""
    setnames = []
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                if line.lower().startswith("export "):
                    line = line[7:]
                name, _, val = line.partition("=")
                name, val = name.strip(), val.strip()
                if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
                    val = val[1:-1]
                if name and name not in os.environ:
                    os.environ[name] = val
                    setnames.append(name)
    except OSError:
        pass
    return setnames


DOTENV_LOADED = load_dotenv()


def local_key():
    if os.environ.get("ANTHROPIC_API_KEY"):
        return os.environ["ANTHROPIC_API_KEY"]
    try:
        with open(KEYFILE, "r", encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    return line
    except OSError:
        pass
    return None


# --------------------------------------------------------------- Matrix A
# Baseline confidence per (Design Status, Stage). None = a pairing David's
# rules forbid. Our proposal, and the thing that needs ratifying.
STAGES = ["Concept", "EVT", "DVT", "PVT", "MP"]
EARLY_STAGES = {"Concept", "EVT"}
MATRIX_A = {
    "Promotion":       {"Concept": 0.10, "EVT": 0.15, "DVT": None, "PVT": None, "MP": None},
    "Sample":          {"Concept": 0.20, "EVT": 0.30, "DVT": None, "PVT": None, "MP": None},
    "Evaluation":      {"Concept": 0.20, "EVT": 0.35, "DVT": None, "PVT": None, "MP": None},
    "Design In":       {"Concept": None, "EVT": None, "DVT": 0.65, "PVT": 0.80, "MP": None},
    "Design Win":      {"Concept": None, "EVT": None, "DVT": None, "PVT": 0.90, "MP": 0.95},
    "Mass Production": {"Concept": None, "EVT": None, "DVT": None, "PVT": None, "MP": 0.95},
    "Lost":            {s: 0.00 for s in STAGES},
}
BANDS = [(0.00, 0.05, "terminal"), (0.05, 0.45, "early"),
         (0.45, 0.85, "designing"), (0.85, 1.00, "locked")]


def baseline_for(design_status, stage):
    return (MATRIX_A.get(design_status) or {}).get(stage)


def band_of(conf):
    for lo, hi, name in BANDS:
        if lo <= conf < hi:
            return name
    return "locked"


# --------------------------------------------------------------- Matrix B
RUBRIC = [
    {"id": "J-01", "label": "Status / stage mismatch", "dir": "-", "cap": 25,
     "fires_when": "the (Design Status, Stage) cell is forbidden in Matrix A",
     "guidance": "READ THE MATRIX, never infer. Design In at DVT is VALID — the old rubric "
                 "docked Aphrodite 12 points for exactly that pairing."},
    {"id": "J-02", "label": "Named competitor", "dir": "-", "cap": 12,
     "fires_when": "competitor_part is populated and is not 'TBD'",
     "guidance": "Blank on every ProjectTrack row today. If you have no competitor field, "
                 "this is not assessable — say so rather than inferring rivalry from prose."},
    {"id": "J-03", "label": "Design win lock-in", "dir": "+", "cap": 8,
     "fires_when": "Design Win at PVT or MP with no open risk factor",
     "guidance": "The only routinely-positive factor. It exists so the layer is two-directional "
                 "instead of a one-way haircut."},
    {"id": "J-04", "label": "Early-stage optimism", "dir": "-", "cap": 15,
     "fires_when": "stage is Concept or EVT AND confidence exceeds its Matrix A baseline by > 0.15",
     "guidance": "The stage order is Concept, EVT, DVT, PVT, MP. DVT and PVT are NOT early — the "
                 "old rubric read DVT as early and docked Montana 15 points."},
    {"id": "J-05", "label": "Customer concentration", "dir": "-", "cap": 10,
     "fires_when": "this row is over 25% of its region's adjusted revenue, or one end customer "
                   "is over 40% of the portfolio's adjusted revenue",
     "guidance": "Compute it from the portfolio figures you are given. Cite the percentage."},
    {"id": "J-06", "label": "Submitter calibration", "dir": "+/-", "cap": 10,
     "fires_when": "the owner's historic bias exceeds one standard deviation",
     "guidance": "No owner field exists anywhere in the workbook and no outcomes have resolved. "
                 "Not assessable — do not guess."},
    {"id": "J-07", "label": "Dual sourcing", "dir": "-", "cap": 10,
     "fires_when": "a second source is named, or customer policy requires one",
     "guidance": "Requested by David. Needs the competitor column and the note field."},
    {"id": "J-08", "label": "Cancellation risk", "dir": "-", "cap": 15,
     "fires_when": "a programme cancellation signal, or an SoP date slipping across runs",
     "guidance": "Slip detection needs two snapshots. With one, say not assessable."},
    {"id": "J-09", "label": "Stage stall", "dir": "-", "cap": 10,
     "fires_when": "days in stage exceed 1.5x the median for that stage",
     "guidance": "Needs state history, which does not exist yet."},
    {"id": "J-10", "label": "Milestone slip", "dir": "-", "cap": 12,
     "fires_when": "a parsed ES, PPAP, Design Review or SoP date is past due",
     "guidance": "Cite the source string, never your parse of it."},
    {"id": "J-11", "label": "EAU plausibility", "dir": "-", "cap": 20,
     "fires_when": "EAU divided by units-per-set is implausible against programme build volume",
     "guidance": "Needs unit_per_set. Without it this is not assessable on a ProjectTrack row."},
    {"id": "J-12", "label": "Data completeness", "dir": "-", "cap": 15,
     "fires_when": "a required field is null or 'TBD' on the row",
     "guidance": "List the missing fields in the citation."},
    {"id": "J-13", "label": "Price anomaly", "dir": "-", "cap": 8,
     "fires_when": "resale ASP below distributor ASP, or channel margin outside the observed band",
     "guidance": "Some rows derive Disty as Resale x 0.975. Do not flag a formula as an anomaly."},
]
CAPS = {f["id"]: f["cap"] for f in RUBRIC}
POSITIVE_OK = {"J-03", "J-06"}


SYSTEM_PROMPT = """You are the judgment layer of a semiconductor company's Opportunity Tracking agent.

You are given a design-win pipeline and a rubric. You are NOT given, and must never produce, a \
revenue figure — Sales Revenue and Adjusted Revenue are computed separately in code from whatever \
you return. You may move exactly one thing: a proposed adjustment to each row's Confidence Level.

Matrix A gives the baseline confidence for each (Design Status, Stage) pairing. A cell marked null \
is a pairing the company's rules forbid. READ THIS TABLE. Do not infer from the words whether a \
pairing is contradictory — Design In at DVT is a normal, valid pairing, and Design Win only occurs \
at PVT or MP.

The stage order is: Concept, EVT, DVT, PVT, MP. Concept and EVT are the early stages. DVT and PVT \
are not early.

For each project, for each rubric factor, decide:
  - applies: whether the row's own data supports it. Do not invent risk.
  - adjustment_pp: signed percentage POINTS to add to the confidence level (so -10 moves 0.60 to \
0.50). Stay within the factor's cap; caps are enforced in code and exceeding one is clipped and flagged.
  - evidence: a VERBATIM quote from the row or the portfolio figures you were given. Not a \
paraphrase. If you cannot quote something, the factor does not apply.
  - rationale: one sentence explaining the size, not just the direction.
  - confidence: 0 to 1 in your own assessment.
  - valid: false when the factor cannot be assessed because the input it needs does not exist on \
this row. Prefer valid: false over a guess. Several factors in this rubric are expected to be \
not-assessable on this data; that is the correct answer for them, not a failure.

Only J-03 and J-06 may return a positive adjustment. Every other factor is a reduction or nothing."""


PROPOSAL_SCHEMA = {
    "type": "object",
    "properties": {
        "projects": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "project": {"type": "string"},
                    "factors": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "rule_id":       {"type": "string", "enum": [f["id"] for f in RUBRIC]},
                                "applies":       {"type": "boolean"},
                                "adjustment_pp": {"type": "number"},
                                "evidence":      {"type": "string"},
                                "rationale":     {"type": "string"},
                                "confidence":    {"type": "number"},
                                "valid":         {"type": "boolean"},
                            },
                            "required": ["rule_id", "applies", "adjustment_pp", "evidence",
                                         "rationale", "confidence", "valid"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["project", "factors"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["projects"],
    "additionalProperties": False,
}


class JudgmentError(RuntimeError):
    """Raised instead of quietly falling back to made-up numbers."""


# --------------------------------------------------------------- context

def portfolio_context(rows):
    """The computed figures the model may see. Deliberately NOT a total the
    reviewer will read — the per-row percentages J-05 needs, and nothing else."""
    fins = [compute_project_financials(r) for r in rows]
    roll = portfolio_rollup(fins)
    total_adj = roll["total_adjusted_revenue_k"] or 1.0
    by_end = {}
    for r, f in zip(rows, fins):
        by_end[r.get("end_customer", "?")] = by_end.get(r.get("end_customer", "?"), 0.0) + f.adjusted_revenue_k
    out = []
    for r, f in zip(rows, fins):
        reg = roll["by_region"][f.region]["adjusted_revenue_k"] or 1.0
        out.append({
            "project": r["project"],
            "region": r["region"],
            "share_of_region_adjusted_pct": round(f.adjusted_revenue_k / reg * 100, 1),
            "share_of_portfolio_adjusted_pct": round(f.adjusted_revenue_k / total_adj * 100, 1),
            "end_customer_share_of_portfolio_pct":
                round(by_end.get(r.get("end_customer", "?"), 0.0) / total_adj * 100, 1),
        })
    return out


def rows_for_model(rows):
    """Strip the money. The model sees the qualitative record and the shares."""
    keep = ("project", "region", "customer", "end_customer", "part_number",
            "design_status", "stage", "confidence", "competitor_part", "comments",
            "eau_kpcs", "disty_asp", "resale_asp")
    return [{k: r.get(k) for k in keep if k in r} for r in rows]


def build_user_prompt(rows):
    return json.dumps({
        "rubric": RUBRIC,
        "matrix_a_baseline_confidence": MATRIX_A,
        "stage_order": STAGES,
        "early_stages": sorted(EARLY_STAGES),
        "pipeline": rows_for_model(rows),
        "portfolio_figures": portfolio_context(rows),
        "rubric_version": RUBRIC_VERSION,
    }, indent=2)


# --------------------------------------------------------------- the call

def score(rows, api_key=None, model=DEFAULT_MODEL, use_fallbacks=True):
    try:
        import anthropic
    except ImportError:
        raise JudgmentError("The anthropic package is not installed. pip install anthropic")

    k = api_key or local_key()
    client = anthropic.Anthropic(api_key=k) if k else anthropic.Anthropic()
    base = dict(model=model, max_tokens=32000, system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": build_user_prompt(rows)}])
    fmt = {"format": {"type": "json_schema", "schema": PROPOSAL_SCHEMA}}

    # Streaming, not create(): 9 projects x 13 factors is a large structured
    # reply, and the SDK refuses a non-streaming request whose max_tokens could
    # outrun the HTTP timeout. get_final_message() gives back the same object.
    def stream_beta():
        with client.beta.messages.stream(
                betas=["server-side-fallback-2026-07-01"], fallbacks="default",
                thinking={"type": "adaptive"}, output_config=fmt, **base) as s:
            return s.get_final_message()

    def stream_plain(**extra):
        with client.messages.stream(**dict(base, **extra)) as s:
            return s.get_final_message()

    rungs = []
    if use_fallbacks:
        rungs.append(("schema + thinking + fallbacks", stream_beta))
    rungs += [
        ("schema + thinking", lambda: stream_plain(thinking={"type": "adaptive"}, output_config=fmt)),
        ("schema only", lambda: stream_plain(output_config=fmt)),
        ("plain", lambda: stream_plain()),
    ]

    msg, rung_used, attempts = None, None, []
    for label, fn in rungs:
        try:
            msg = fn()
            rung_used = label
            break
        except Exception as e:
            attempts.append("%s -> %s%s: %s" % (
                label, type(e).__name__,
                " %s" % getattr(e, "status_code", "") if getattr(e, "status_code", None) else "",
                str(e)[:220]))
            if type(e).__name__ in ("AuthenticationError", "PermissionDeniedError",
                                    "APIConnectionError", "NotFoundError"):
                break
            if isinstance(e, TypeError) and "authentication" in str(e).lower():
                raise JudgmentError(
                    "No credentials. The SDK found no API key, auth token or ant profile.\n"
                    "  Set ANTHROPIC_API_KEY, put one in .env, or run `ant auth login`.")
    if msg is None:
        raise JudgmentError("Every request shape failed.\n  " + "\n  ".join(attempts))
    if rung_used != rungs[0][0]:
        print("[judgment_bench] fell back to '%s'. Earlier attempts:\n  %s"
              % (rung_used, "\n  ".join(attempts)), file=sys.stderr)

    if msg.stop_reason == "refusal":
        raise JudgmentError("Model declined this request (stop_reason=refusal). Nothing scored.")
    if msg.stop_reason == "max_tokens":
        raise JudgmentError("Reply hit max_tokens and is truncated. Nothing scored.")

    text = next((b.text for b in msg.content if getattr(b, "type", None) == "text"), None)
    if text is None:
        raise JudgmentError("No text block in the reply; blocks were: %s"
                            % [getattr(b, "type", "?") for b in msg.content])

    salvaged = False
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        t = text.strip()
        if t.startswith("```"):
            t = t.split("```")[1] if "```" in t[3:] else t[3:]
            if t.lstrip().lower().startswith("json"):
                t = t.lstrip()[4:]
        a, b = t.find("{"), t.rfind("}")
        if a < 0 or b <= a:
            raise JudgmentError("Reply was not JSON and could not be salvaged:\n%s" % text[:300])
        payload = json.loads(t[a:b + 1])
        salvaged = True

    return {
        "projects": payload.get("projects", []),
        "provenance": {
            "model": msg.model, "request_shape": rung_used,
            "schema_enforced": "schema" in rung_used, "json_salvaged": salvaged,
            "rubric_version": RUBRIC_VERSION, "prompt_version": PROMPT_VERSION,
            "stop_reason": msg.stop_reason,
            "input_tokens": msg.usage.input_tokens, "output_tokens": msg.usage.output_tokens,
        },
    }


# --------------------------------------------------------------- guards

def validate_row(row, factors):
    """Caps, citations, direction, per-run cap, clamp, band crossing."""
    accepted, violations = [], []
    for f in factors:
        rid = f.get("rule_id")
        if rid not in CAPS:
            violations.append({"rule_id": rid, "kind": "unknown_rule",
                               "detail": "not in %s" % RUBRIC_VERSION})
            continue
        if not f.get("valid", True):
            violations.append({"rule_id": rid, "kind": "not_assessable",
                               "detail": (f.get("rationale") or "model marked it invalid")[:180]})
            continue
        if not f.get("applies"):
            continue
        adj = float(f.get("adjustment_pp") or 0.0)
        ev = (f.get("evidence") or "").strip()
        if not ev:
            violations.append({"rule_id": rid, "kind": "no_citation",
                               "detail": "a factor with no evidence invalidates the proposal"})
            continue
        if rid not in POSITIVE_OK and adj > 0:
            violations.append({"rule_id": rid, "kind": "wrong_direction",
                               "detail": "only J-03 and J-06 may be positive; got %+.1f" % adj})
            continue
        if abs(adj) > CAPS[rid]:
            violations.append({"rule_id": rid, "kind": "over_factor_cap",
                               "detail": "%+.1f clipped to cap %d" % (adj, CAPS[rid])})
            adj = CAPS[rid] if adj > 0 else -CAPS[rid]
        g = dict(f); g["adjustment_pp"] = adj
        accepted.append(g)

    total = sum(f["adjustment_pp"] for f in accepted)
    if abs(total) > PER_RUN_CAP_PP:
        scale = PER_RUN_CAP_PP / abs(total)
        violations.append({"rule_id": "—", "kind": "over_run_cap",
                           "detail": "total %+.1fpp scaled to the %.0fpp per-run cap"
                                     % (total, PER_RUN_CAP_PP)})
        for f in accepted:
            f["adjustment_pp"] *= scale
        total = sum(f["adjustment_pp"] for f in accepted)

    entered = float(row["confidence"])
    proposed = entered + total / 100.0
    clamped = max(CONF_FLOOR, min(CONF_CEIL, proposed))
    if abs(clamped - proposed) > 1e-9:
        violations.append({"rule_id": "—", "kind": "clamped",
                           "detail": "%.2f clamped into [%.2f, %.2f]" % (proposed, CONF_FLOOR, CONF_CEIL)})

    crossed = band_of(entered) != band_of(clamped)
    if crossed:
        violations.append({"rule_id": "—", "kind": "band_crossing",
                           "detail": "%s -> %s: needs human approval, not auto-apply"
                                     % (band_of(entered), band_of(clamped))})

    return {"accepted": accepted, "violations": violations, "total_pp": total,
            "entered": entered, "proposed": clamped, "band_crossing": crossed,
            "baseline": baseline_for(row.get("design_status"), row.get("stage")),
            "valid_pairing": baseline_for(row.get("design_status"), row.get("stage")) is not None}


def apply_all(rows, scored):
    """Match the model's per-project blocks back to rows and run every guard."""
    by_name = {p.get("project"): p.get("factors", []) for p in scored}
    out = []
    for r in rows:
        res = validate_row(r, by_name.get(r["project"], []))
        res["row"] = r
        out.append(res)
    return out


# --------------------------------------------------------------- CLI

def money(v):
    return ("−$" if v < 0 else "$") + "{:,.1f}K".format(abs(v))


def run_cli(args):
    with open(os.path.join(_DIR, "data", "sample_pipeline.json")) as f:
        rows = json.load(f)["project_track"]

    base = [compute_project_financials(r) for r in rows]
    broll = portfolio_rollup(base)

    print("=" * 92)
    print("OPPORTUNITY TRACKING — JUDGMENT BENCH")
    print("=" * 92)
    print("\n[1] BASE CASE, computed before any model call")
    print("    Sales ${:,.1f}K   Adjusted ${:,.1f}K   effective confidence {:.3f}".format(
        broll["total_sales_revenue_k"], broll["total_adjusted_revenue_k"],
        broll["total_adjusted_revenue_k"] / broll["total_sales_revenue_k"]))

    print("\n[2] MATRIX A CHECK, before the model sees anything")
    for r in rows:
        b = baseline_for(r["design_status"], r["stage"])
        mark = "valid  " if b is not None else "FORBIDDEN"
        print("    {:12} {:14} @ {:8} {}  baseline {}  entered {:.2f}".format(
            r["project"], r["design_status"], r["stage"], mark,
            "  n/a" if b is None else "%.2f" % b, r["confidence"]))

    print("\n[3] LIVE JUDGMENT CALL  (model=%s, rubric=%s)" % (args.model, RUBRIC_VERSION))
    try:
        res = score(rows, model=args.model, use_fallbacks=not args.no_fallbacks)
    except JudgmentError as e:
        print("\n    REFUSED TO GUESS: %s" % e)
        print("    No calibrated total produced. That is the intended behaviour.")
        return 1
    print("    provenance: %s" % json.dumps(res["provenance"]))

    results = apply_all(rows, res["projects"])

    print("\n[4] PER ROW")
    for R in results:
        r = R["row"]
        flag = " BAND-CROSS" if R["band_crossing"] else ""
        print("\n  {:12} {:14} @ {:8}  {:.2f} -> {:.2f}  ({:+.1f}pp){}".format(
            r["project"], r["design_status"], r["stage"],
            R["entered"], R["proposed"], R["total_pp"], flag))
        for f in R["accepted"]:
            print("      {} {:+6.1f}pp  \"{}\"".format(
                f["rule_id"], f["adjustment_pp"], (f.get("evidence") or "")[:70]))
        for v in R["violations"]:
            if v["kind"] != "not_assessable":
                print("      GUARD {:<16} {} {}".format(v["kind"], v["rule_id"], v["detail"][:70]))
        na = [v["rule_id"] for v in R["violations"] if v["kind"] == "not_assessable"]
        if na:
            print("      not assessable: %s" % ", ".join(na))

    print("\n[5] EFFECT ON THE WEIGHTED PIPELINE")
    cal_rows = []
    for R in results:
        c = dict(R["row"]); c["confidence"] = R["proposed"]; cal_rows.append(c)
    cfin = [compute_project_financials(r) for r in cal_rows]
    croll = portfolio_rollup(cfin)
    d = croll["total_adjusted_revenue_k"] - broll["total_adjusted_revenue_k"]
    print("    Adjusted revenue {}  ->  {}   ({}{:.1f}%)".format(
        money(broll["total_adjusted_revenue_k"]), money(croll["total_adjusted_revenue_k"]),
        "+" if d >= 0 else "", d / broll["total_adjusted_revenue_k"] * 100))
    print("    Sales revenue unchanged at {} — the model never touches it.".format(
        money(broll["total_sales_revenue_k"])))
    queued = [R["row"]["project"] for R in results if R["band_crossing"]]
    if queued:
        print("    Queued for human approval (band crossing): %s" % ", ".join(queued))
    return 0


def diagnose(model, key=None):
    print("=" * 74)
    print("OPPORTUNITY TRACKING — JUDGMENT BENCH DIAGNOSTICS")
    print("=" * 74)
    try:
        import anthropic
        print("  anthropic SDK      %s" % anthropic.__version__)
    except ImportError:
        print("  anthropic SDK      NOT INSTALLED  ->  pip install anthropic")
        return 1
    print("  python             %s" % sys.version.split()[0])
    if DOTENV_LOADED:
        print("  .env               loaded, set %s" % ", ".join(DOTENV_LOADED))
    elif os.path.exists(ENVFILE):
        print("  .env               present but set nothing")

    k = key or local_key()
    if not k:
        print("  credentials        NONE FOUND")
        print("\n  Pick one:")
        print("    echo ANTHROPIC_API_KEY=sk-ant-... > %s" % ENVFILE)
        print("    ant auth login")
        return 1
    print("  credentials        %d chars, ends …%s" % (len(k), k[-6:]))
    print("  model              %s" % model)

    client = anthropic.Anthropic(api_key=k)
    req = dict(model=model, max_tokens=1024,
               messages=[{"role": "user", "content": "Reply with the single word: ok"}])
    fmt = {"format": {"type": "json_schema", "schema": {
        "type": "object", "properties": {"answer": {"type": "string"}},
        "required": ["answer"], "additionalProperties": False}}}
    probes = [
        ("plain call", lambda: client.messages.create(**req)),
        ("thinking adaptive", lambda: client.messages.create(thinking={"type": "adaptive"}, **req)),
        ("structured output", lambda: client.messages.create(output_config=fmt, **req)),
        ("structured + thinking", lambda: client.messages.create(
            thinking={"type": "adaptive"}, output_config=fmt, **req)),
        ("server-side fallbacks", lambda: client.beta.messages.create(
            betas=["server-side-fallback-2026-07-01"], fallbacks="default", **req)),
    ]
    print("\n  %-24s %s" % ("FEATURE", "RESULT"))
    print("  " + "-" * 70)
    ok_any = False
    for label, fn in probes:
        try:
            m = fn()
            ok_any = True
            print("  %-24s OK   (%s, %d out tokens)" % (label, m.stop_reason, m.usage.output_tokens))
        except Exception as e:
            print("  %-24s FAIL %s %s" % (label, type(e).__name__, getattr(e, "status_code", "")))
            print("  %-24s      %s" % ("", str(e)[:200]))
    print()
    print("  Ready." if ok_any else "  Nothing worked — key, network or model name.")
    return 0 if ok_any else 1


def main():
    p = argparse.ArgumentParser(description="Judgment bench for the Opportunity Tracking agent")
    p.add_argument("--diagnose", action="store_true")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--no-fallbacks", action="store_true")
    args = p.parse_args()
    if args.diagnose:
        return diagnose(args.model)
    return run_cli(args)


if __name__ == "__main__":
    sys.exit(main())
