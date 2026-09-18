"""
OppTrack bench — calc and judgment in one pipeline, with every step showing its working.

   1  intake            deterministic   the pipeline rows, and who owns each field
   2  validate          deterministic   gates, including the Matrix A pairing check
   3  compute base      deterministic   C1/C2 per row and the roll-ups, from calc_engine.py
   4  precedent         judgment        not built yet (Phase 2, pgvector)
   5  score factors     judgment        the one live model call, whole pipeline at once
   6  check the reply   deterministic   caps, citations, per-run cap, clamp, band crossing
   7  recompute         deterministic   the SAME arithmetic on approved confidence
   8  lifecycle moves   deterministic   not run — Phase 2, needs state history
   9  human decision    human           a person clears the review queue
  10  log               deterministic   the audit record

Steps 1-3 and 6-7 come from calc_engine.py, the module test_calc_engine.py asserts
against TrackF_1.xlsx. Step 5 is the only step that touches a model, and what it
returns is percentage points and quotes — never a revenue figure.

Usage:
    python opptrack_bench.py            # serve on http://localhost:8776
    python opptrack_bench.py --port N
"""

import argparse
import json
import os
import sys

from calc_engine import compute_project_financials, portfolio_rollup
from judgment_bench import (
    local_key, DOTENV_LOADED,
    RUBRIC, RUBRIC_VERSION, PROMPT_VERSION, DEFAULT_MODEL, PER_RUN_CAP_PP,
    MATRIX_A, STAGES, EARLY_STAGES, CONF_FLOOR, CONF_CEIL,
    PROPOSAL_SCHEMA, JudgmentError,
    baseline_for, band_of, score, apply_all, portfolio_context,
)

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
STATUSES = list(MATRIX_A.keys())


def money(v, d=1):
    if v is None:
        return "n/a"
    return ("−$" if v < 0 else "$") + "{:,.{p}f}K".format(abs(v), p=d)


def num(v, d=1):
    return ("−" if v < 0 else "") + "{:,.{p}f}".format(abs(v), p=d)


def step(n, name, lane, status, headline, rows=None, note=None, extra=None):
    return {"n": n, "name": name, "lane": lane, "status": status,
            "headline": headline, "rows": rows or [], "note": note, "extra": extra or {}}


# --------------------------------------------------------------------- steps

def s1_intake(rows):
    out = [[r["project"], r["region"], r.get("end_customer", "—"),
            "%s @ %s" % (r["design_status"], r["stage"]),
            "%s Kpcs" % num(r["eau_kpcs"], 0), "$%.2f" % r["disty_asp"], "%.2f" % r["confidence"]]
           for r in rows]
    return step(1, "Intake", "det", "done", "%d opportunities" % len(rows), out,
                "V1 EAU and V3 Distributor ASP come from the sales owner; J1 Confidence is the one "
                "hand-entered number that multiplies every revenue figure in the file. That is why "
                "it is the only field the agent is allowed to propose a change to.")


def s2_validate(rows):
    checks = []
    forbidden = [r["project"] for r in rows if baseline_for(r["design_status"], r["stage"]) is None]
    checks.append(["Every (Design Status, Stage) pairing exists in Matrix A", not forbidden,
                   ", ".join(forbidden) if forbidden else "all %d rows valid" % len(rows)])
    badconf = [r["project"] for r in rows if not (0.0 <= r["confidence"] <= 1.0)]
    checks.append(["Confidence in [0, 1]", not badconf, ", ".join(badconf) if badconf else "clean"])
    noeau = [r["project"] for r in rows if not r.get("eau_kpcs")]
    checks.append(["EAU present and non-zero", not noeau, ", ".join(noeau) if noeau else "clean"])
    noasp = [r["project"] for r in rows if not r.get("disty_asp")]
    checks.append(["Distributor ASP present", not noasp, ", ".join(noasp) if noasp else "clean"])
    inverted = [r["project"] for r in rows
                if r.get("resale_asp") and r["resale_asp"] < r.get("disty_asp", 0)]
    checks.append(["Resale ASP at or above Distributor ASP", not inverted,
                   ", ".join(inverted) if inverted else "clean"])
    ceil = [r["project"] for r in rows if r["confidence"] >= 1.0]
    checks.append(["No row pinned at the 1.00 ceiling", not ceil,
                   (", ".join(ceil) + " — positive support would be discarded") if ceil else "clean"])

    failed = [c[0] for c in checks if not c[1]]
    out = [[c[0], "PASS" if c[1] else "FAIL", c[2]] for c in checks]
    return step(2, "Validate", "det", "done" if not failed else "gate",
                "%d of %d gates pass" % (len(checks) - len(failed), len(checks)), out,
                "Gates cap a run; they do not haircut it. The Matrix A check runs here, before the "
                "model sees anything — a forbidden pairing is a data problem to reconcile, not a "
                "confidence problem to discount.")


def s3_base(rows, focus):
    fins = [compute_project_financials(r) for r in rows]
    roll = portfolio_rollup(fins)
    tS, tA = roll["total_sales_revenue_k"], roll["total_adjusted_revenue_k"]

    per = []
    for r, f in zip(rows, fins):
        b = baseline_for(r["design_status"], r["stage"])
        per.append([r["project"], r["region"], "%s @ %s" % (r["design_status"], r["stage"]),
                    num(r["eau_kpcs"], 0), "$%.2f" % r["disty_asp"], money(f.sales_revenue_k),
                    "%.2f" % f.confidence, money(f.adjusted_revenue_k),
                    "forbidden" if b is None else "%.2f" % b])

    i = max(0, min(focus, len(rows) - 1))
    r, f = rows[i], fins[i]
    b = baseline_for(r["design_status"], r["stage"])
    reg = roll["by_region"][r["region"]]["adjusted_revenue_k"] or 1.0
    work = [
        ["C1", "Sales revenue", "V1 × V3",
         "%s Kpcs × $%.2f" % (num(r["eau_kpcs"], 0), r["disty_asp"]), money(f.sales_revenue_k)],
        ["C2", "Adjusted revenue", "C1 × J1",
         "%s × %.2f" % (money(f.sales_revenue_k), f.confidence), money(f.adjusted_revenue_k)],
        ["C5", "Channel margin", "V4 − V3",
         "$%.2f − $%.2f" % (r.get("resale_asp", 0), r["disty_asp"]),
         "$%.2f / unit" % (r.get("resale_asp", 0) - r["disty_asp"])],
        ["C12", "Share of %s's weighted pipeline" % r["region"], "row C2 ÷ Σ C2 for the region",
         "%s ÷ %s" % (money(f.adjusted_revenue_k), money(reg)),
         "%.1f%%" % (f.adjusted_revenue_k / reg * 100)],
        ["C12b", "Share of the whole weighted pipeline", "row C2 ÷ Σ C2",
         "%s ÷ %s" % (money(f.adjusted_revenue_k), money(tA)),
         "%.1f%%" % (f.adjusted_revenue_k / tA * 100) if tA else "n/a"],
        ["A", "Matrix A baseline", "%s @ %s" % (r["design_status"], r["stage"]),
         "pairing the rules forbid" if b is None else "table lookup",
         "forbidden" if b is None else "%.2f" % b],
        ["Δ", "Entered vs baseline", "J1 − baseline",
         "no baseline" if b is None else "%.2f − %.2f" % (r["confidence"], b),
         "n/a" if b is None else "%+.2f" % (r["confidence"] - b)],
    ]

    st = step(3, "Compute the base case", "det", "done",
              "%s sales · %s weighted · effective confidence %.3f"
              % (money(tS), money(tA), tA / tS if tS else 0), per,
              "These numbers exist before any model call and are never replaced. Step 7 re-runs this "
              "exact function on approved confidence, which is what makes the two comparable.")
    st["extra"] = {
        "work": work, "focus": i,
        "projects": [r["project"] for r in rows],
        "total_sales": tS, "total_adjusted": tA,
        "effective_confidence": tA / tS if tS else 0,
        "by_region": roll["by_region"], "by_stage": roll["by_stage"],
    }
    return st


def s4_precedent():
    return step(4, "Retrieve precedent", "judge", "skipped", "not built — Phase 2",
                [["pgvector over resolved opportunities", "NOT RUN",
                  "needs won/lost outcomes to retrieve from"],
                 ["Submitter reliability profiles", "NOT RUN",
                  "no owner field exists anywhere in the workbook"]],
                "Two of the thirteen factors depend on history that does not exist yet. They will "
                "correctly return not-assessable below rather than guessing.")


def s5_score(rows, key, model, no_fallbacks):
    sent = {"pipeline_rows": len(rows), "portfolio_figures": portfolio_context(rows),
            "matrix_a": "sent as config", "rubric_version": RUBRIC_VERSION}
    try:
        res = score(rows, api_key=key, model=model, use_fallbacks=not no_fallbacks)
    except JudgmentError as e:
        full = str(e)
        st = step(5, "Score the factors", "judge", "failed", full.split("\n")[0][:110], [],
                  "A failed judgement call must never look like a successful run. No calibrated "
                  "total is produced, and nothing is substituted.")
        st["extra"] = {"sent": sent, "error": full}
        return st, None

    out = []
    for p in res["projects"]:
        for f in p.get("factors", []):
            state = "applies" if f.get("applies") else ("not assessable" if not f.get("valid", True) else "n/a")
            out.append([p.get("project"), f.get("rule_id"), state,
                        "%+.1fpp" % (f.get("adjustment_pp") or 0),
                        f.get("evidence") or "", f.get("rationale") or "",
                        "%.2f" % (f.get("confidence") or 0)])
    applied = sum(1 for r0 in out if r0[2] == "applies")
    st = step(5, "Score the factors", "judge", "done",
              "%d factor verdicts across %d projects, %d apply" % (len(out), len(res["projects"]), applied),
              out,
              "One call for the whole pipeline, not one per row — which is what lets J-05 "
              "concentration compute at all. Under the old one-row signature it could never fire.")
    st["extra"] = {"sent": sent, "provenance": res["provenance"],
                   "schema_keys": list(PROPOSAL_SCHEMA["properties"]["projects"]["items"]
                                       ["properties"]["factors"]["items"]["properties"])}
    return st, res


def s6_check(rows, res):
    results = apply_all(rows, res["projects"])
    out, kinds = [], 0
    for R in results:
        p = R["row"]["project"]
        for f in R["accepted"]:
            out.append([p, f["rule_id"], "PASS", "%+.1fpp within cap, evidence present"
                        % f["adjustment_pp"]])
        for v in R["violations"]:
            if v["kind"] == "not_assessable":
                continue
            kinds += 1
            out.append([p, v["rule_id"], v["kind"].replace("_", " ").upper(), v["detail"][:150]])
    st = step(6, "Check the reply", "det", "done" if not kinds else "gate",
              "%d guard%s fired" % (kinds, "" if kinds == 1 else "s"), out,
              "Nothing the model returned reaches step 7 without passing a check written in Python. "
              "A band crossing does not block the run — it routes that row to a person instead of "
              "auto-applying.")
    st["extra"] = {"results": [{"project": R["row"]["project"], "entered": R["entered"],
                                "proposed": R["proposed"], "total_pp": R["total_pp"],
                                "band_crossing": R["band_crossing"]} for R in results]}
    return st, results


def s7_recompute(rows, results):
    base = [compute_project_financials(r) for r in rows]
    broll = portfolio_rollup(base)
    cal = []
    for R in results:
        c = dict(R["row"]); c["confidence"] = R["proposed"]; cal.append(c)
    cfin = [compute_project_financials(r) for r in cal]
    croll = portfolio_rollup(cfin)

    out = []
    for R, bf, cf in zip(results, base, cfin):
        d = cf.adjusted_revenue_k - bf.adjusted_revenue_k
        out.append([R["row"]["project"], "%.2f" % R["entered"], "%.2f" % R["proposed"],
                    "%+.1fpp" % R["total_pp"], money(bf.adjusted_revenue_k),
                    money(cf.adjusted_revenue_k), money(d),
                    "review" if R["band_crossing"] else "auto"])
    tb, tc = broll["total_adjusted_revenue_k"], croll["total_adjusted_revenue_k"]
    st = step(7, "Recompute", "det", "done", "%s → %s" % (money(tb), money(tc)), out,
              "Same function as step 3, same untouched formulas — only the confidence differs. "
              "Sales revenue is identical because the model has no way to reach it.")
    st["extra"] = {"base_adjusted": tb, "cal_adjusted": tc,
                   "base_sales": broll["total_sales_revenue_k"],
                   "base_eff": tb / broll["total_sales_revenue_k"] if broll["total_sales_revenue_k"] else 0,
                   "cal_eff": tc / croll["total_sales_revenue_k"] if croll["total_sales_revenue_k"] else 0,
                   "queued": [R["row"]["project"] for R in results if R["band_crossing"]]}
    return st


def s8_lifecycle():
    return step(8, "Lifecycle moves", "det", "skipped", "not run — Phase 2",
                [["Promote to Mass Production", "NOT RUN", "needs state history and a human gate"],
                 ["Move to Design Lost", "NOT RUN", "requires a reason code on the way out"],
                 ["C14 time in stage", "NOT RUN", "no state_history table yet"]],
                "David's own answer was that a person should confirm before an opportunity is marked "
                "Design Lost or promoted to Mass Production. Until that gate exists, this agent "
                "proposes confidence and nothing else.")


def s9_human(results, decisions):
    queued = [R["row"]["project"] for R in results if R["band_crossing"]] if results else []
    rows = [[p, decisions.get(p, "—"), "band crossing — needs approval before it applies"] for p in queued]
    done = all(decisions.get(p) for p in queued) if queued else True
    return step(9, "Human decision", "human", "done" if done else "waiting",
                ("review queue clear" if not queued else
                 "%d of %d cleared" % (sum(1 for p in queued if decisions.get(p)), len(queued))),
                rows,
                "Only rows that cross a lifecycle band need a person. Everything else applies "
                "automatically, which is the difference between a review queue and a rubber stamp.")


def s10_log(rows, prov, results, decisions):
    rec = {
        "pipeline_rows": len(rows),
        "rubric_version": RUBRIC_VERSION,
        "prompt_version": PROMPT_VERSION,
        "model": (prov or {}).get("model"),
        "stop_reason": (prov or {}).get("stop_reason"),
        "tokens": {"in": (prov or {}).get("input_tokens"), "out": (prov or {}).get("output_tokens")},
        "rows_moved": sum(1 for R in (results or []) if abs(R["total_pp"]) > 1e-9),
        "rows_queued": [R["row"]["project"] for R in (results or []) if R["band_crossing"]],
        "decisions": decisions or {},
    }
    return step(10, "Log", "det", "done", "audit record assembled",
                [[k, json.dumps(v) if not isinstance(v, str) else v] for k, v in rec.items()],
                "Written on every proposal and every override, from day one — because the output "
                "moves a number a board pack is built on, and because this log is the only thing "
                "that will ever let anyone check whether the agent's past calibrations were right.")


# --------------------------------------------------------------------- run

def run_pipeline(body):
    rows = body["rows"]
    focus = int(body.get("focus", 2))
    decisions = body.get("decisions") or {}
    trace = [s1_intake(rows)]
    v = s2_validate(rows)
    trace.append(v)
    trace.append(s3_base(rows, focus))
    trace.append(s4_precedent())

    if not body.get("judge"):
        trace.append(step(5, "Score the factors", "judge", "skipped",
                          "not requested — calculation only", [],
                          "Press “Run the judgement call” to include a live model call."))
        trace.append(step(6, "Check the reply", "det", "skipped", "nothing to check", []))
        trace.append(step(7, "Recompute", "det", "skipped",
                          "no adjustment, so the weighted total is the base case", []))
        trace.append(s8_lifecycle())
        trace.append(s9_human(None, decisions))
        trace.append(s10_log(rows, None, None, decisions))
        return {"ok": True, "trace": trace, "judged": False}

    s5, res = s5_score(rows, (body.get("key") or "").strip() or None,
                       body.get("model") or DEFAULT_MODEL, body.get("no_fallbacks"))
    trace.append(s5)
    if res is None:
        trace.append(step(6, "Check the reply", "det", "skipped", "no reply to check", []))
        trace.append(step(7, "Recompute", "det", "skipped",
                          "no adjustment — the base case stands alone", []))
        trace.append(s8_lifecycle())
        trace.append(s9_human(None, decisions))
        trace.append(s10_log(rows, None, None, decisions))
        return {"ok": True, "trace": trace, "judged": False}

    s6, results = s6_check(rows, res)
    trace.append(s6)
    trace.append(s7_recompute(rows, results))
    trace.append(s8_lifecycle())
    trace.append(s9_human(results, decisions))
    trace.append(s10_log(rows, s5["extra"].get("provenance"), results, decisions))
    return {"ok": True, "trace": trace, "judged": True}


# --------------------------------------------------------------------- server

def serve(args):
    import http.server, socketserver

    with open(os.path.join(HERE, "data", "sample_pipeline.json")) as f:
        SEED = json.load(f)["project_track"]

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="application/json"):
            b = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype + "; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            if self.path.startswith("/api/seed"):
                self._send(200, json.dumps({
                    "rows": SEED, "rubric": RUBRIC, "rubric_version": RUBRIC_VERSION,
                    "matrix_a": MATRIX_A, "stages": STAGES, "statuses": STATUSES,
                    "early_stages": sorted(EARLY_STAGES),
                    "per_run_cap": PER_RUN_CAP_PP, "clamp": [CONF_FLOOR, CONF_CEIL],
                    "env_key": bool(local_key()), "default_model": DEFAULT_MODEL,
                }))
                return
            self._send(200, PAGE, "text/html")

        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            try:
                body = json.loads(self.rfile.read(n) or "{}")
            except json.JSONDecodeError:
                self._send(400, json.dumps({"ok": False, "error": "bad JSON"}))
                return
            body["no_fallbacks"] = args.no_fallbacks
            try:
                self._send(200, json.dumps(run_pipeline(body)))
            except Exception as e:
                self._send(200, json.dumps({"ok": False, "error": "%s: %s" % (type(e).__name__, e)}))

    # Threaded: a judgement call over nine rows takes minutes, and on a single
    # threaded server that blocks the page itself. allow_reuse_address stays OFF
    # on Windows, where SO_REUSEADDR would let duplicate servers bind the same
    # port and answer requests at random.
    class Server(socketserver.ThreadingTCPServer):
        daemon_threads = True
        allow_reuse_address = (os.name != "nt")

    srv, port = None, args.port
    for _ in range(12):
        try:
            srv = Server(("127.0.0.1", port), H)
            break
        except OSError as e:
            print("  port %d is busy (%s), trying %d" % (port, e.__class__.__name__, port + 1))
            port += 1
    if srv is None:
        print("Could not bind any port between %d and %d." % (args.port, port))
        return 1

    url = "http://localhost:%d/" % port
    print("")
    print("  OppTrack bench is running.")
    print("  ---------------------------------------------")
    print("  OPEN THIS:   %s" % url)
    print("  serving from: %s" % HERE)
    print("  .env:         %s" % (", ".join(DOTENV_LOADED) if DOTENV_LOADED else "nothing loaded"))
    print("  API key:      %s" % ("found" if local_key() else "not set — paste one into the page"))
    print("  ---------------------------------------------")
    print("  A judgement call scores 9 rows x 13 factors and takes a few minutes.")
    print("  Ctrl-C to stop.")
    print("")
    if not args.no_open:
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:
            pass
    with srv:
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped.")
    return 0


PAGE = r"""<!doctype html><html><head><meta charset="utf-8">
<title>OppTrack Agent Bench</title>
<style>
:root{--paper:#F7F6F3;--surface:#fff;--surface-2:#F1EFEA;--ink:#1F1B18;--ink-2:#453E37;
--muted:#6E665D;--faint:#948B81;--rule:#DCD7CF;--rule-2:#C7C0B6;--accent:#BE5320;
--accent-bg:#F6E7DD;--judge:#16706A;--judge-bg:#DDEDEB;--broken:#A22C22;--broken-bg:#F6E2DF;
--ok:#4E6A2C;--ok-bg:#E6EDDB;--s1:#BE5320;--s2:#00897B;--grid:#E4E0D9;
--mono:ui-monospace,"Cascadia Mono",Consolas,"SF Mono",Menlo,monospace;
--sans:system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif;
--serif:"Palatino Linotype","Iowan Old Style",Palatino,Georgia,serif;
--shadow:0 1px 2px rgba(31,27,24,.05),0 8px 24px -16px rgba(31,27,24,.18)}
@media(prefers-color-scheme:dark){:root:not([data-theme=light]){--paper:#17140F;--surface:#1E1A15;
--surface-2:#251F19;--ink:#EDE8E0;--ink-2:#CDC5BA;--muted:#9C938A;--faint:#7A7268;--rule:#332C25;
--rule-2:#443B32;--accent:#E8844B;--accent-bg:#3A2317;--judge:#4CB8AC;--judge-bg:#133430;
--broken:#E58275;--broken-bg:#3B1E1A;--ok:#A2C46C;--ok-bg:#26301A;--s1:#D9743C;--s2:#2FA79A;
--grid:#2C251E;--shadow:0 1px 2px rgba(0,0,0,.4),0 8px 24px -16px rgba(0,0,0,.7)}}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font-family:var(--sans);font-size:15.5px;line-height:1.55}
.shell{max-width:1560px;margin:0 auto;padding:38px 18px 100px}
.shell>*{min-width:0}
.eyebrow{font-family:var(--mono);font-size:10.5px;letter-spacing:.19em;text-transform:uppercase;color:var(--accent);margin-bottom:14px}
h1{font-family:var(--mono);font-weight:700;font-size:clamp(25px,4vw,42px);line-height:1.04;letter-spacing:-.03em;margin:0 0 6px}
.sub{font-family:var(--mono);font-size:clamp(13px,1.7vw,17px);color:var(--accent);margin:0 0 16px}
.lede{font-family:var(--serif);font-size:17px;color:var(--ink-2);max-width:66ch;margin:0 0 26px}
.cols{display:grid;grid-template-columns:minmax(0,1fr);gap:30px}
@media(min-width:1180px){.cols{grid-template-columns:410px minmax(0,1fr);gap:36px;align-items:start}
.pane-in{position:sticky;top:16px;max-height:calc(100vh - 32px);overflow-y:auto;padding-right:4px}}
h2{font-family:var(--mono);font-weight:700;font-size:15px;margin:0 0 12px;padding-top:13px;border-top:2px solid var(--ink)}
h3{font-family:var(--mono);font-size:11px;letter-spacing:.11em;text-transform:uppercase;color:var(--muted);margin:20px 0 9px;font-weight:600}
.card{background:var(--surface);border:1px solid var(--rule);padding:15px 17px;box-shadow:var(--shadow)}
label{display:flex;flex-direction:column;gap:5px;font-family:var(--mono);font-size:10.5px;letter-spacing:.09em;text-transform:uppercase;color:var(--muted)}
input,select,textarea{font-family:var(--mono);font-size:12.5px;color:var(--ink);background:var(--surface);border:1px solid var(--rule-2);border-radius:2px;padding:5px 7px;width:100%;font-variant-numeric:tabular-nums}
input:focus,select:focus,button:focus-visible{outline:2px solid var(--accent);outline-offset:1px}
.tw{overflow-x:auto;border:1px solid var(--rule);background:var(--surface);box-shadow:var(--shadow)}
table{border-collapse:collapse;width:100%;font-size:12.5px}
thead th{background:var(--surface-2);font-family:var(--mono);font-size:9.5px;font-weight:600;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);text-align:left;padding:7px 8px;border-bottom:1px solid var(--rule-2);white-space:nowrap}
td,tbody th{padding:5px 8px;border-bottom:1px solid var(--rule);vertical-align:top;text-align:left;font-weight:400}
tbody th{font-family:var(--mono);font-size:11.5px;font-weight:600;white-space:nowrap}
tr:last-child td,tr:last-child th{border-bottom:0}
td.m{font-family:var(--mono);font-size:11.5px;white-space:nowrap}
td.n{font-family:var(--mono);font-variant-numeric:tabular-nums;text-align:right;white-space:nowrap}
td.res{font-family:var(--mono);font-weight:600;font-variant-numeric:tabular-nums;text-align:right;white-space:nowrap;color:var(--accent)}
.gridtbl td{padding:2px 3px}
.gridtbl input,.gridtbl select{border-color:transparent;background:transparent;padding:4px 5px}
.gridtbl input:hover,.gridtbl select:hover{border-color:var(--rule-2)}
.gridtbl input:focus,.gridtbl select:focus{border-color:var(--accent);background:var(--surface)}
.gridtbl input[type=number]{text-align:right;min-width:58px}
button.go{font-family:var(--mono);font-size:13px;font-weight:600;letter-spacing:.04em;padding:10px 18px;cursor:pointer;background:var(--accent);color:#fff;border:0;border-radius:2px}
button.alt{background:var(--surface);color:var(--ink);border:1px solid var(--rule-2)}
button.go[disabled]{opacity:.5;cursor:default}
.row{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-top:13px}
.chip{display:inline-block;font-family:var(--mono);font-size:9.5px;font-weight:600;letter-spacing:.09em;text-transform:uppercase;padding:2px 7px;border-radius:2px;border:1px solid transparent;white-space:nowrap}
.c-ok{background:var(--ok-bg);color:var(--ok);border-color:var(--ok)}
.c-no{background:var(--broken-bg);color:var(--broken);border-color:var(--broken)}
.c-mut{background:var(--surface-2);color:var(--muted);border-color:var(--rule-2)}
.c-j{background:var(--judge-bg);color:var(--judge);border-color:var(--judge)}
.c-a{background:var(--accent-bg);color:var(--accent);border-color:var(--accent)}
.stepc{border:1px solid var(--rule);background:var(--surface);box-shadow:var(--shadow);margin-bottom:12px}
.stephd{display:grid;grid-template-columns:38px 1fr auto;gap:12px;align-items:center;padding:11px 15px;cursor:pointer}
.stephd:hover{background:var(--surface-2)}
.stepn{font-family:var(--mono);font-size:17px;font-weight:700;color:var(--faint);font-variant-numeric:tabular-nums}
.stepnm{font-family:var(--mono);font-size:13.5px;font-weight:600;display:block}
.stephl{font-size:12.5px;color:var(--muted)}
.stepbd{padding:0 15px 15px;border-top:1px dashed var(--rule)}
.stepbd[hidden]{display:none}
.stepnote{font-size:13.5px;color:var(--ink-2);margin:11px 0 0;max-width:88ch}
.lane-det{border-left:3px solid var(--rule-2)}
.lane-judge{border-left:3px solid var(--judge)}
.lane-human{border-left:3px solid var(--accent)}
.quote{font-family:var(--serif);font-style:italic;color:var(--ink-2);border-left:2px solid var(--judge);padding-left:9px;margin:3px 0 0;font-size:12.5px}
.note{border-left:3px solid var(--accent);background:var(--surface);padding:12px 15px;margin:12px 0;font-size:14px}
.note.bad{border-left-color:var(--broken)}
.note.good{border-left-color:var(--ok)}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:1px;background:var(--rule);border:1px solid var(--rule);margin-bottom:11px}
.stats div{background:var(--surface);padding:12px 14px}
.stats dt{font-family:var(--mono);font-size:9.5px;letter-spacing:.13em;text-transform:uppercase;color:var(--faint);margin-bottom:4px}
.stats dd{margin:0;font-family:var(--mono);font-size:18px;font-weight:600;font-variant-numeric:tabular-nums}
.stats dd small{display:block;font-weight:400;font-size:11px;color:var(--muted);margin-top:2px}
pre{font-family:var(--mono);font-size:11.5px;background:var(--surface-2);border:1px solid var(--rule);padding:11px 13px;overflow-x:auto;margin:9px 0 0;max-height:240px}
.cap{font-family:var(--mono);font-size:11.5px;color:var(--muted);line-height:1.5;margin:8px 0 0}
.neg{color:var(--broken)}.pos{color:var(--ok)}
.legend{display:flex;flex-wrap:wrap;gap:6px 18px;font-family:var(--mono);font-size:10.5px;color:var(--muted);margin:0 0 10px}
.legend i{font-style:normal;display:inline-flex;align-items:center;gap:6px}
.sw{width:11px;height:11px;display:inline-block;border-radius:1px}
.spin{font-family:var(--mono);font-size:12px;color:var(--muted)}
</style></head><body><div class="shell">

<div class="eyebrow">AxcelAI · Agent OS · Opportunity Tracking Agent</div>
<h1>OppTrack Agent Bench</h1>
<p class="sub">the whole pipeline, one step at a time, showing its working</p>
<p class="lede">Ten layers. Seven are ordinary Python from <code>calc_engine.py</code>; one calls a
model; one waits for a person. The model may move exactly one number — Confidence Level — under a
cap, with a citation. Open any step to see what it did.</p>

<div class="cols">
<div class="pane-in">
  <h2>Pipeline</h2>
  <div class="tw"><table class="gridtbl"><thead><tr>
    <th>Project</th><th>Status</th><th>Stage</th><th>EAU</th><th>ASP</th><th>Conf</th><th>A</th>
  </tr></thead><tbody id="gbody"></tbody></table></div>
  <p class="cap">Editable. <b>A</b> is the Matrix A baseline for that pairing — red means a pairing
  the rules forbid, which is what J-01 fires on.</p>

  <h3>Model access</h3>
  <div class="card">
    <label style="margin-bottom:10px">Anthropic API key
      <input type="password" id="key" placeholder="sk-ant-… or leave blank" autocomplete="off"></label>
    <label>Model<select id="model">
      <option value="claude-opus-5">claude-opus-5</option>
      <option value="claude-sonnet-5">claude-sonnet-5</option>
      <option value="claude-haiku-4-5">claude-haiku-4-5</option>
    </select></label>
    <div id="keynote" class="cap" style="margin-top:9px"></div>
  </div>

  <div class="row">
    <button class="go alt" id="calc">Calculate only</button>
    <button class="go" id="judge">Run the judgement call</button>
  </div>
  <div class="row"><span class="spin" id="spin"></span></div>
  <p class="cap">A judgement call scores every row against all 13 factors in one request. Expect a
  few minutes.</p>
</div>

<div class="pane-out">
  <h2>Pipeline</h2>
  <div class="legend">
    <i><span class="sw" style="background:var(--rule-2)"></span>Deterministic</i>
    <i><span class="sw" style="background:var(--judge)"></span>Judgment — a model call</i>
    <i><span class="sw" style="background:var(--accent)"></span>Human</i>
  </div>
  <div id="pipe"><div class="note">Loading the sample pipeline and computing the base case…</div></div>
</div>
</div></div>

<script>
var $=function(i){return document.getElementById(i)},D=null,ROWS=null,FOCUS=2,LAST=null,DEC={};

fetch("/api/seed").then(function(r){return r.json()}).then(function(d){
  D=d; ROWS=JSON.parse(JSON.stringify(d.rows));
  $("model").value=d.default_model;
  $("keynote").innerHTML=d.env_key
    ?'<span class="chip c-ok">key found</span> leave the field blank to use it'
    :'<span class="chip c-mut">no key found</span> paste one above';
  grid(); run(false);
}).catch(function(e){
  $("pipe").innerHTML='<div class="note bad"><b>Could not load the sample pipeline.</b><br>'+e+
    '<br><br>Check the terminal running opptrack_bench.py for a traceback.</div>';
});

function baseline(r){var m=D.matrix_a[r.design_status];return m?m[r.stage]:undefined}
function grid(){
  $("gbody").innerHTML=ROWS.map(function(r,i){
    var b=baseline(r), ok=(b!==null&&b!==undefined);
    return "<tr><th>"+r.project+"</th>"+
      '<td><select data-i="'+i+'" data-k="design_status" aria-label="Design status">'+
        D.statuses.map(function(s){return '<option'+(s===r.design_status?" selected":"")+">"+s+"</option>"}).join("")+"</select></td>"+
      '<td><select data-i="'+i+'" data-k="stage" aria-label="Stage">'+
        D.stages.map(function(s){return '<option'+(s===r.stage?" selected":"")+">"+s+"</option>"}).join("")+"</select></td>"+
      '<td><input type="number" step="10" data-i="'+i+'" data-k="eau_kpcs" value="'+r.eau_kpcs+'" aria-label="EAU"></td>'+
      '<td><input type="number" step="0.01" data-i="'+i+'" data-k="disty_asp" value="'+r.disty_asp+'" aria-label="ASP"></td>'+
      '<td><input type="number" step="0.05" min="0" max="1" data-i="'+i+'" data-k="confidence" value="'+r.confidence+'" aria-label="Confidence"></td>'+
      '<td>'+(ok?'<span class="chip c-ok">'+b.toFixed(2)+"</span>":'<span class="chip c-no">✕</span>')+"</td></tr>";
  }).join("");
  $("gbody").querySelectorAll("input,select").forEach(function(el){
    el.addEventListener("input",function(){
      var i=+el.dataset.i,k=el.dataset.k;
      ROWS[i][k]=el.type==="number"?(parseFloat(el.value)||0):el.value;
      grid();
    });
  });
}

$("calc").addEventListener("click",function(){run(false)});
$("judge").addEventListener("click",function(){run(true)});

function run(judge){
  $("calc").disabled=$("judge").disabled=true;
  $("spin").textContent=judge?"calling the model — this takes a few minutes…":"computing…";
  fetch("/api/run",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({rows:ROWS,focus:FOCUS,judge:judge,decisions:DEC,
      key:$("key").value,model:$("model").value})})
  .then(function(r){return r.json()}).then(function(d){
    if(!d.ok){$("pipe").innerHTML='<div class="note bad"><b>Failed.</b> '+d.error+"</div>";return}
    LAST=d; draw(d);
  }).catch(function(e){$("pipe").innerHTML='<div class="note bad"><b>Request failed.</b> '+e+"</div>"})
  .then(function(){$("calc").disabled=$("judge").disabled=false;$("spin").textContent=""});
}

var money=function(v){return (v<0?"−$":"$")+Math.abs(v).toLocaleString("en-US",{minimumFractionDigits:1,maximumFractionDigits:1})+"K"};
var esc=function(s){return String(s==null?"":s).replace(/[&<>]/g,function(c){return{"&":"&amp;","<":"&lt;",">":"&gt;"}[c]})};
function chipFor(st){return {done:'<span class="chip c-ok">done</span>',gate:'<span class="chip c-no">gate fired</span>',
  failed:'<span class="chip c-no">stopped</span>',skipped:'<span class="chip c-mut">not run</span>',
  waiting:'<span class="chip c-a">waiting</span>'}[st]||""}

function draw(d){
  var h="";
  d.trace.forEach(function(s){
    var open=(s.n===3||s.n===5||s.n===6||s.n===7)&&s.status!=="skipped";
    h+='<div class="stepc lane-'+s.lane+'"><div class="stephd" data-n="'+s.n+'">'+
      '<div class="stepn">'+s.n+'</div><div><span class="stepnm">'+s.name+"</span>"+
      '<span class="stephl">'+esc(s.headline)+"</span></div><div>"+chipFor(s.status)+"</div></div>"+
      '<div class="stepbd" id="bd'+s.n+'"'+(open?"":" hidden")+">"+body(s)+
      (s.note?'<p class="stepnote">'+s.note+"</p>":"")+"</div></div>";
  });
  $("pipe").innerHTML=h;
  $("pipe").querySelectorAll(".stephd").forEach(function(el){
    el.addEventListener("click",function(){var b=$("bd"+el.dataset.n);b.hidden=!b.hidden})});
  $("pipe").querySelectorAll("[data-focus]").forEach(function(b){
    b.addEventListener("click",function(){FOCUS=+b.dataset.focus;run(LAST.judged)})});
  $("pipe").querySelectorAll("[data-approve]").forEach(function(b){
    b.addEventListener("click",function(){
      DEC[b.dataset.approve]=b.dataset.verdict;
      var s9=LAST.trace.filter(function(s){return s.n===9})[0];
      var s10=LAST.trace.filter(function(s){return s.n===10})[0];
      if(s9){s9.rows=s9.rows.map(function(r){return r[0]===b.dataset.approve?[r[0],b.dataset.verdict,r[2]]:r});
        var cleared=s9.rows.filter(function(r){return r[1]!=="—"}).length;
        s9.headline=cleared+" of "+s9.rows.length+" cleared";
        s9.status=cleared===s9.rows.length?"done":"waiting";}
      if(s10){s10.rows=s10.rows.map(function(r){return r[0]==="decisions"?[r[0],JSON.stringify(DEC)]:r})}
      draw(LAST);
    })});
}

function tbl(head,rows,cls){
  if(!rows.length)return"";
  return '<div class="tw" style="margin-top:11px"><table><thead><tr>'+
    head.map(function(x){return "<th>"+x+"</th>"}).join("")+"</tr></thead><tbody>"+
    rows.map(function(r){return "<tr>"+r.map(function(c,i){
      var k=(cls&&cls[i])||"";
      if(k==="chip"){var ok=/PASS|valid/i.test(c),no=/FAIL|REJECT|CLIP|CLAMP|OVER|WRONG|BAND|forbidden/i.test(c);
        return '<td><span class="chip '+(ok?"c-ok":no?"c-no":"c-mut")+'">'+esc(c)+"</span></td>"}
      return '<td class="'+k+'">'+esc(c)+"</td>";
    }).join("")+"</tr>"}).join("")+"</tbody></table></div>";
}

function body(s){
  if(s.n===1)return tbl(["Project","Region","End customer","Status @ Stage","EAU","ASP","Conf"],s.rows,["","m","m","m","n","n","n"]);
  if(s.n===2)return tbl(["Gate","","Detail"],s.rows,["","chip","m"]);
  if(s.n===3){
    var e=s.extra;
    var st='<dl class="stats"><div><dt>C1 · Sales</dt><dd>'+money(e.total_sales)+"<small>unweighted</small></dd></div>"+
      "<div><dt>C2 · Adjusted</dt><dd>"+money(e.total_adjusted)+"<small>confidence-weighted</small></dd></div>"+
      "<div><dt>Effective confidence</dt><dd>"+e.effective_confidence.toFixed(3)+"<small>falls out of the roll-up</small></dd></div></dl>";
    var pick='<div class="row" style="margin:0 0 4px">'+e.projects.map(function(p,i){
      return '<button class="go alt" style="padding:5px 10px;font-size:11.5px'+
        (i===e.focus?";background:var(--accent-bg);color:var(--accent);border-color:var(--accent)":"")+
        '" data-focus="'+i+'">'+esc(p)+"</button>"}).join("")+"</div>";
    return st+tbl(["Project","Region","Status @ Stage","EAU","ASP","C1 Sales","J1","C2 Adjusted","Matrix A"],
                  s.rows,["","m","m","n","n","n","n","res","chip"])+
      "<h3>One row, substituted</h3>"+pick+
      tbl(["ID","What","Formula","Substituted","Result"],e.work,["","","m","m","res"]);
  }
  if(s.n===4||s.n===8)return tbl(["Component","","Why not"],s.rows,["","chip","m"]);
  if(s.n===5){
    var out="";
    if(s.extra.sent)out+="<h3>What crossed the boundary</h3><pre>"+esc(JSON.stringify(s.extra.sent,null,2))+"</pre>"+
      '<p class="cap">Matrix A goes in as config, so the model reads the table rather than inferring a contradiction from the words. No revenue figure crosses in either direction.</p>';
    if(s.status==="failed")return out+'<div class="note bad" style="margin-top:11px"><b>Refused to guess.</b><br>'+
      esc(s.headline)+"</div><pre>"+esc(s.extra.error||"")+"</pre>";
    if(s.extra.schema_keys)out+='<p class="cap">Reply constrained server-side to: '+s.extra.schema_keys.join(", ")+"</p>";
    var applied=s.rows.filter(function(r){return r[2]==="applies"});
    var na=s.rows.filter(function(r){return r[2]==="not assessable"});
    out+="<h3>Factors that applied</h3>"+
      '<div class="tw" style="margin-top:11px"><table><thead><tr><th>Project</th><th>Rule</th><th>Adj</th><th>Conf</th><th>Evidence it cited, and why</th></tr></thead><tbody>'+
      applied.map(function(r){var a=parseFloat(r[3]);
        return "<tr><th>"+esc(r[0])+"</th><td>"+esc(r[1])+'</td><td class="n '+(a<0?"neg":a>0?"pos":"")+'">'+esc(r[3])+
          '</td><td class="n">'+esc(r[6])+"</td><td>"+(r[4]?'<div class="quote">“'+esc(r[4])+'”</div>':"")+
          '<div style="color:var(--muted);font-size:12px;margin-top:3px">'+esc(r[5])+"</div></td></tr>"}).join("")+
      "</tbody></table></div>";
    var byRule={};na.forEach(function(r){byRule[r[1]]=(byRule[r[1]]||0)+1});
    out+="<h3>Not assessable</h3><p class=\"cap\">"+Object.keys(byRule).sort().map(function(k){
      return k+" ("+byRule[k]+" rows)"}).join(" · ")+
      " — the input each needs does not exist on this data. Declining is the correct answer for them, not a failure.</p>";
    if(s.extra.provenance)out+="<h3>Provenance</h3><pre>"+esc(JSON.stringify(s.extra.provenance,null,2))+"</pre>";
    return out;
  }
  if(s.n===6)return tbl(["Project","Rule","Guard","What it did"],s.rows,["","","chip","m"]);
  if(s.n===7){
    if(!s.rows.length)return"";
    var e=s.extra;
    var st='<dl class="stats"><div><dt>Before</dt><dd>'+money(e.base_adjusted)+"<small>eff. conf "+e.base_eff.toFixed(3)+"</small></dd></div>"+
      "<div><dt>After</dt><dd>"+money(e.cal_adjusted)+"<small>eff. conf "+e.cal_eff.toFixed(3)+"</small></dd></div>"+
      "<div><dt>Movement</dt><dd>"+money(e.cal_adjusted-e.base_adjusted)+"<small>"+
      ((e.cal_adjusted-e.base_adjusted)/e.base_adjusted*100).toFixed(1)+"%</small></dd></div>"+
      "<div><dt>Sales revenue</dt><dd>"+money(e.base_sales)+"<small>unchanged — out of reach</small></dd></div></dl>";
    return st+tbl(["Project","Entered","Proposed","Movement","C2 before","C2 after","Δ","Applies"],
                  s.rows,["","n","n","n","n","res","n","chip"]);
  }
  if(s.n===9){
    if(!s.rows.length)return '<p class="cap" style="margin-top:11px">No row crossed a lifecycle band, so nothing needs a person before it applies.</p>';
    return '<div class="tw" style="margin-top:11px"><table><thead><tr><th>Project</th><th>Decision</th><th>Why it is queued</th><th></th></tr></thead><tbody>'+
      s.rows.map(function(r){
        return "<tr><th>"+esc(r[0])+'</th><td><span class="chip '+(r[1]==="—"?"c-a":"c-ok")+'">'+esc(r[1])+"</span></td>"+
          '<td class="m">'+esc(r[2])+'</td><td><button class="go alt" style="padding:4px 9px;font-size:11px" data-approve="'+
          esc(r[0])+'" data-verdict="Approved">Approve</button> <button class="go alt" style="padding:4px 9px;font-size:11px" data-approve="'+
          esc(r[0])+'" data-verdict="Rejected">Reject</button></td></tr>"}).join("")+"</tbody></table></div>";
  }
  if(s.n===10)return tbl(["Field","Value"],s.rows,["","m"]);
  return tbl(["","","",""],s.rows);
}
</script></body></html>
"""


def main():
    p = argparse.ArgumentParser(description="OppTrack bench — calc and judgment together")
    p.add_argument("--port", type=int, default=8776)
    p.add_argument("--no-fallbacks", action="store_true")
    p.add_argument("--no-open", action="store_true")
    args = p.parse_args()
    need = ["calc_engine.py", "judgment_bench.py", os.path.join("data", "sample_pipeline.json")]
    missing = [f for f in need if not os.path.exists(os.path.join(HERE, f))]
    if missing:
        print("Cannot start — missing from %s:" % HERE)
        for f in missing:
            print("   %s" % f)
        return 1
    return serve(args)


if __name__ == "__main__":
    sys.exit(main())
