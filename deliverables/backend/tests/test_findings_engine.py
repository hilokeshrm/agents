"""
The findings engine against the real workbook (WBS 3.1, 4.1, 4.4, 4.5, 12.6).

The done-when for 4.5 is literal: all twelve documented findings (build spec,
section 03, F-01..F-12) reproduced from the real file by running one command.
The done-when for 4.1 is a passing and a failing fixture per rule, drawn from
the real file where it has one.
"""

from pathlib import Path

import pytest

from app.guards.report import SPEC_FINDINGS, render_text, workbook_report
from app.guards.rules import (
    ADVISORY,
    BLOCKING,
    RULES,
    RuleContext,
    run_rules,
)
from app.intake.xlsx_reader import RawRow, read_workbook

WORKBOOK = Path(__file__).resolve().parents[3] / "data" / "TrackF (1).xlsx"
needs_workbook = pytest.mark.skipif(not WORKBOOK.exists(), reason="TrackF (1).xlsx not present in this checkout")


@pytest.fixture(scope="module")
def report():
    return workbook_report(WORKBOOK)


@pytest.fixture(scope="module")
def wb():
    return read_workbook(WORKBOOK)


# --------------------------------------------------------------------------- #
# 3.1 -- the reader
# --------------------------------------------------------------------------- #

@needs_workbook
def test_reader_handles_the_two_row_header_and_the_shifted_terminal_tabs(wb):
    pt = wb.tabs["ProjectTrack"]
    assert pt.headers["Q"] == "confidence"            # "Confidence" + "Level" across rows 3 and 4
    assert pt.headers["R"] == "adjusted_revenue_k"
    mp = wb.tabs["Mass Production"]
    assert mp.headers["P"] == "confidence"            # one letter left: no Stage column
    assert mp.headers["Q"] == "adjusted_revenue_k"
    fcst = wb.tabs["FCST_Revenue"]
    assert fcst.headers["O"] == "cy25_units_q2"       # group on row 3, quarter on row 4
    assert fcst.headers["AG"] == "cy26_revenue_k_ttl"
    assert str(fcst.as_of).startswith("2025-03-10")


@needs_workbook
def test_reader_separates_data_rows_skeletons_and_footers(wb):
    assert len(wb.tabs["Funnel"].rows) == 8
    assert len(wb.tabs["FCST_Revenue"].rows) == 10
    assert [f.fields["region"] for f in wb.tabs["FCST_Revenue"].footers] == [
        "Korea Region", "Europe Region", "Taiwan Region", "Japan Region", "Elevation Micro Total",
    ]
    # ProjectTrack: nine complete rows plus five skeletons -- data, not footers.
    pt = wb.tabs["ProjectTrack"]
    assert len(pt.rows) == 14 and pt.footers == []
    assert [r.row_number for r in pt.rows if not r.fields.get("customer")] == [14, 15, 16, 17, 18]


@needs_workbook
def test_reader_keeps_formulas_and_coordinates(wb):
    europe = wb.tabs["FCST_Revenue"].footers[1]
    cell = europe.cell("cy25_units_ttl")
    assert cell.coordinate == "FCST_Revenue!R21"
    assert cell.formula == "=SUM(#REF!)" and cell.is_error
    derived = wb.tabs["Funnel"].rows[4].cell("disty_asp")   # row 9, ID501
    assert derived.formula == "=M9*0.975" and derived.value == pytest.approx(0.8775)
    entered = wb.tabs["Funnel"].rows[0].cell("disty_asp")
    assert entered.formula is None


# --------------------------------------------------------------------------- #
# 4.5 -- all twelve, one command
# --------------------------------------------------------------------------- #

@needs_workbook
def test_all_twelve_documented_findings_are_reproduced(report):
    assert report.spec_missing == [], f"missing {report.spec_missing}"
    assert report.spec_refs == set(SPEC_FINDINGS)


@needs_workbook
def test_each_documented_finding_lands_where_the_specification_says(report):
    where = {}
    for f in report.findings:
        if f.spec_ref:
            where.setdefault(f.spec_ref, []).append(f)
    assert {f.cell for f in where["F-01"]} >= {"R21, S21, T21...", "R22, S22, T22..."}
    assert {f.cell for f in where["F-02"]} == {"AB21", "AB22"}
    assert {f.cell for f in where["F-03"]} == {"AB23", "AG23"}
    assert where["F-04"][0].cell == "R24, W24, AG24"
    assert any("IP901" in f.message and "32.7M" in f.message for f in where["F-05"])
    assert any("ID801" in f.message and "57,175" in f.message and "1,343" in f.message for f in where["F-06"])
    assert {f.cell for f in where["F-07"]} >= {"Funnel!J11", "Funnel!K11", "Funnel!L11", "Funnel!M11"}
    assert sorted(f.row_number for f in where["F-08"]) == [14, 15, 16, 17, 18]
    assert "0.30, 0.50" in where["F-09"][0].message and "Q9" in where["F-09"][0].cell
    assert where["F-10"][0].cell == "Funnel!N5:N12"
    assert where["F-11"][0].tab == "Sheet1"
    assert any("AX01 appears on 6 of 9" in f.message for f in where["F-12"])


@needs_workbook
def test_the_report_finds_what_the_specification_missed(report):
    """ID802 and ID803 carry the same defect as IP901 -- the rule is a division,
    so it does not stop at the one row a person happened to notice."""
    f05 = [f for f in report.findings if f.spec_ref == "F-05"]
    assert {f.message.split(":")[0] for f in f05} == {"IP901", "ID802", "ID803"}


@needs_workbook
def test_funnel_row_11_carries_seven_placeholders(report):
    row11 = [f for f in report.findings if f.tab == "Funnel" and f.row_number == 11]
    assert len(row11) == 7
    assert {f.rule_id for f in row11} == {"V-a", "V-g"}


@needs_workbook
def test_nre_lines_are_not_flagged_for_having_no_mp_date(report):
    assert not any(f.tab == "FCST_Revenue" and f.field == "mp_date" for f in report.findings)


@needs_workbook
def test_the_nine_complete_rows_carry_no_blocking_finding(report):
    """The pipeline the calc engine is proven on is clean at row level: every
    blocking finding is a skeleton, a Funnel volume, a cross-tab gap or a
    roll-up formula -- none of the nine live ProjectTrack rows."""
    live_rows = set(range(5, 14))
    blocking_pt = [f for f in report.findings if f.severity == BLOCKING and f.tab == "ProjectTrack" and f.row_number in live_rows]
    assert blocking_pt == []


@needs_workbook
def test_render_text_is_the_phase_0_page(report):
    text = render_text(report)
    assert "Documented findings reproduced: 12 of 12" in text
    assert "[F-01]" in text and "[F-12]" in text
    assert "V-a Required field missing or TBD" in text


@needs_workbook
def test_the_script_runs_end_to_end(capsys):
    from scripts.findings_report import main

    assert main([str(WORKBOOK)]) == 0
    assert "12 of 12" in capsys.readouterr().out
    assert main([str(WORKBOOK), "--json"]) == 0
    assert '"spec_findings_missing": []' in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# 4.1 -- a passing and a failing fixture per rule
# --------------------------------------------------------------------------- #

def row(tab, n, **fields) -> RawRow:
    from app.intake.xlsx_reader import Cell

    cells = {k: Cell(coordinate=f"{tab}!{chr(65 + i)}{n}", value=v, formula=None) for i, (k, v) in enumerate(fields.items())}
    return RawRow(tab=tab, row_number=n, fields=dict(fields), cells=cells)


def clean_row(tab="ProjectTrack", n=5, **over) -> RawRow:
    base = dict(region="Korea", customer="SLM", end_customer="GM", project="Hercules", part_number="AX01",
                design_status="Design Win", stage="PVT", eau_kpcs=1100, unit_set=5, disty_asp=3,
                resale_asp=3.2, confidence=1.0)
    base.update(over)
    return row(tab, n, **base)


MATRIX = {("Design Win", "PVT"): True, ("Design Win", "Concept"): False, ("Evaluation", "EVT"): True,
          ("Design In", "DVT"): True}
BASE = {("Design Win", "PVT"): 0.90, ("Evaluation", "EVT"): 0.35, ("Design In", "DVT"): 0.65}


def only(rule_id, ctx):
    findings, _ = run_rules(ctx, rule_ids=(rule_id,))
    return findings


def test_every_rule_has_a_passing_and_a_failing_fixture():
    cases = {
        "V-a": (clean_row(), clean_row(customer=None, project=None, disty_asp=None)),
        "V-b": (clean_row(), clean_row(stage="Concept")),
        "V-c": (clean_row(), None),  # failing case needs two rows, below
        "V-d": (clean_row(), clean_row(eau_kpcs=130790, unit_set=4)),
        "V-e": (clean_row(), None),  # failing case needs two tabs, below
        "V-f": (None, None),         # footers only, below
        "V-g": (clean_row(), clean_row(region="LATAM")),
        "V-h": (clean_row(), row("Funnel", 5, region="KR", customer="MOBIS", project="Tail Lamp", fcst_flag=1)),
        "V-i": (clean_row(), None),  # failing case needs two rows, below
    }
    for rule in RULES:
        passing, failing = cases[rule.id]
        if passing is not None:
            assert only(rule.id, RuleContext(rows=[passing], matrix_a=MATRIX, baselines=BASE)) == [], rule.id
        if failing is not None:
            assert only(rule.id, RuleContext(rows=[failing], matrix_a=MATRIX, baselines=BASE)), rule.id

    # V-c: same cell, different confidence -> one tab-level advisory.
    a = clean_row(n=9, project="Apollo", design_status="Evaluation", stage="EVT", confidence=0.5)
    b = clean_row(n=10, project="Hugo", design_status="Evaluation", stage="EVT", confidence=0.3)
    vc = only("V-c", RuleContext(rows=[a, b], matrix_a=MATRIX, baselines=BASE))
    assert len(vc) == 1 and vc[0].severity == ADVISORY and "0.30, 0.50" in vc[0].message

    # V-e: same part and account on two tabs, 40x apart -> blocking; different account -> nothing.
    funnel = row("Funnel", 5, region="KR", customer="MOBIS", end_customer="Hyundai/Kia", part_number="ID801", design_status="M/P", eau_kpcs=57175)
    fcst = row("FCST_Revenue", 5, region="KR", customer="Mobis", end_customer="Hyundai/Kia", part_number="ID801", design_status="M/P", eau_kpcs=1343)
    other = row("FCST_Revenue", 6, region="KR", customer="Foxc", end_customer="Forde", part_number="ID801", design_status="M/P", eau_kpcs=1343)
    assert only("V-e", RuleContext(rows=[funnel, fcst]))[0].severity == BLOCKING
    assert only("V-e", RuleContext(rows=[funnel, other])) == []

    # V-i: the same part twice on one tab -> advisory; once -> nothing.
    assert only("V-i", RuleContext(rows=[clean_row(n=5), clean_row(n=6, project="Aphrodite")]))
    assert only("V-i", RuleContext(rows=[clean_row(n=5)])) == []


def test_v_f_reads_footer_formulas_and_is_dark_without_them():
    from app.intake.xlsx_reader import Cell

    def footer(n, label, **cells):
        return RawRow(tab="FCST_Revenue", row_number=n, fields={"region": label, **{k: v[0] for k, v in cells.items()}},
                      cells={"region": Cell(f"FCST_Revenue!A{n}", label, None),
                             **{k: Cell(f"FCST_Revenue!X{n}", v[0], v[1]) for k, v in cells.items()}})

    korea = footer(20, "Korea Region", cy26_units_ttl=(5698, "=SUM(AB5:AB15)"))
    europe = footer(21, "Europe Region", cy25_units_ttl=("#REF!", "=SUM(#REF!)"), cy26_units_ttl=(11396, "=SUM(AB5:AB20)"))
    total = footer(24, "Elevation Micro Total", cy25_units_ttl=("#REF!", "=SUM(R20:R23)"))
    findings = only("V-f", RuleContext(rows=[], footers=[korea, europe, total]))
    assert {f.spec_ref for f in findings} == {"F-01", "F-02", "F-04"}
    assert all(f.severity == BLOCKING for f in findings)
    # Korea's own range is clean, so nothing is reported against it.
    assert not any(f.row_number == 20 for f in findings)

    _, dark = run_rules(RuleContext(rows=[clean_row()], footers=[]), rule_ids=("V-f",))
    assert "V-f" in dark


def test_v_b_is_dark_without_a_matrix_and_never_guesses():
    findings, dark = run_rules(RuleContext(rows=[clean_row(stage="Concept")], matrix_a=None), rule_ids=("V-b",))
    assert findings == [] and dark["V-b"] == "no Matrix A available"


@needs_workbook
def test_the_walkthrough_reproduces_the_specification_worked_example(tmp_path, monkeypatch):
    """One command, a fresh database: the findings, the nine rows, rubric v1, a
    run, and Hermes 0.30 -> 0.20 ($12,000K -> $8,000K) approved and audited --
    the build specification's own worked example (section 06)."""
    from scripts import walkthrough

    monkeypatch.setattr(walkthrough, "OUT", tmp_path / "walkthrough.md")
    assert walkthrough.main(["--keep-db", str(tmp_path / "w.sqlite")]) == 0
    text = (tmp_path / "walkthrough.md").read_text(encoding="utf-8")
    assert "| Hermes | 0.30 | 0.20 | J-05 -10pp |" in text
    assert "| Aphrodite | 0.80 | 0.80 | none |" in text and "| Montana | 0.80 | 0.80 | none |" in text
    assert "$8,000K, from $12,000K" in text
    assert "| approval | 0.30 | 0.20 | walkthrough-director (director) |" in text
    assert (tmp_path / "w.sqlite").exists()
