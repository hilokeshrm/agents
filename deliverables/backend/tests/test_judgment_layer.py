"""
The judgment layer against Matrix A and Matrix B (WBS 7.1-7.4, 12.2, 12.3).

Three things this file proves that the first live run did not have:

- The two misfires cannot recur. Aphrodite (Design In at DVT) and Montana
  (Design In at DVT) are explicit must-not-fire fixtures for J-01 and J-04,
  checked at the mock scorer, at the guards, and end to end through a run.
- Concentration fires on the Korea case. Hermes is 47.7% of Korea's weighted
  pipeline; under the one-row signature nothing could see that.
- A proposal outside the bounds cannot exist as an object, and every failure
  of the live path raises rather than returning fabricated numbers.

Fixtures are the nine live ProjectTrack rows in tests/fixtures/sample_pipeline.json
-- the same rows test_calc_engine.py proves the arithmetic on.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.calc.engine import compute_project_financials
from app.judgment import rubric as rubric_module
from app.judgment.contract import ConfidenceProposal, ContractViolation, Factor
from app.judgment.matrix_b import BY_ID, BY_KEY, RULES, STAGE_ORDER, is_early
from app.judgment.rubric import (
    JudgmentReplyError,
    REPLY_SCHEMA,
    _live_score,
    _mock_score,
    citable_text,
    score_confidence_factors,
)
from app.judgment.reply_guards import check_factors
from app.services.portfolio import concentration, portfolio_context
from tests.test_roles_and_scope import headers

FIXTURE = Path(__file__).parent / "fixtures" / "sample_pipeline.json"
ROWS = json.loads(FIXTURE.read_text())["project_track"]
BY_PROJECT = {r["project"]: r for r in ROWS}

# Matrix A v1 (decision register, section 2), as the bundle carries it.
BASELINE = {
    ("Promotion", "Concept"): 0.10, ("Promotion", "EVT"): 0.15,
    ("Sample", "Concept"): 0.20, ("Sample", "EVT"): 0.30,
    ("Evaluation", "Concept"): 0.20, ("Evaluation", "EVT"): 0.35,
    ("Design In", "DVT"): 0.65, ("Design In", "PVT"): 0.80,
    ("Design Win", "PVT"): 0.90, ("Mass Production", "PVT"): 0.95,
}


def bundle_for(project: str, **overrides) -> dict:
    """A bundle shaped like app/services/proposals.evidence_bundle, built from
    the fixture row without a database."""
    row = BY_PROJECT[project]
    cell = (row["design_status"], row["stage"])
    fin = compute_project_financials({**row, "unit_set": None})
    b = {
        "project": row["project"], "region": row["region"], "customer": row["customer"],
        "end_customer": row["end_customer"], "product_line": None, "part_number": row["part_number"],
        "design_status": row["design_status"], "stage": row["stage"], "mp_date": None,
        "competitor_part": row["competitor_part"], "owner": "jdoe", "confidence": row["confidence"],
        "confidence_rationale": row["comments"], "evidence": row["comments"],
        "matrix_a_baseline": BASELINE.get(cell), "matrix_a_forbidden": cell not in BASELINE,
        "_portfolio": None, "_missing_required": [], "_set_volume_ksets": None,
        "_channel_margin_pct": fin.channel_margin_pct, "_overdue_milestones": None,
        "_days_in_stage": None, "_stage_median_days": None, "_sop_slip_months": None,
        "_calibration": None,
    }
    b.update(overrides)
    return b


def fired(factors: list) -> dict[str, float]:
    return {f["key"]: f["confidence_adjustment_pct"] for f in factors if f["applies"]}


# --------------------------------------------------------------------------- #
# Matrix B as a table
# --------------------------------------------------------------------------- #

def test_matrix_b_has_thirteen_rules_with_unique_ids_and_caps():
    assert len(RULES) == 13
    assert [r.id for r in RULES] == [f"J-{n:02d}" for n in range(1, 14)]
    assert len(BY_KEY) == 13
    assert all(r.cap_pp > 0 for r in RULES)
    assert all(r.requires for r in RULES), "every rule declares what it needs"


def test_stage_order_is_explicit_and_dvt_is_not_early():
    assert STAGE_ORDER == ("Concept", "EVT", "DVT", "PVT")
    assert is_early("Concept") and is_early("EVT")
    assert not is_early("DVT") and not is_early("PVT") and not is_early(None)


def test_every_rule_reports_not_assessable_when_its_input_is_absent():
    """WBS 7.2 done-when: no factor produces an adjustment from a null field."""
    blank = {k: None for r in RULES for k in r.requires}
    blank.update({"design_status": None, "stage": None, "confidence": None})
    results = _mock_score(blank)
    assert len(results) == 13
    assert all(not f["applies"] and f["confidence_adjustment_pct"] == 0.0 for f in results)
    assert all("absent" in f["rationale"] for f in results)


# --------------------------------------------------------------------------- #
# The two misfires (WBS 7.3, 12.2)
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("project", ["Aphrodite", "Montana"])
def test_design_in_at_dvt_does_not_misfire_j01_or_j04(project):
    """Both are Design In at DVT, entered at 0.80 against a 0.65 baseline. The
    first live run docked Aphrodite 12pp for a 'mismatch' and Montana 15pp for
    'early-stage optimism'. Neither rule may fire: the cell is allowed, and DVT
    is not early."""
    b = bundle_for(project)
    assert b["matrix_a_forbidden"] is False
    result = fired(_mock_score(b))
    assert "stage_status_mismatch" not in result
    assert "early_stage_optimism" not in result
    assert result == {}, f"nothing should fire on {project}: {result}"


def test_the_guards_refuse_the_misfires_even_if_the_scorer_makes_them():
    """Belt and braces: a reply that fires J-01 on Aphrodite or J-04 on Montana
    is rejected by a guard that reads the bundle, not the model's opinion."""
    for project in ("Aphrodite", "Montana"):
        b = bundle_for(project)
        reply = [
            {"rule_id": "J-01", "key": "stage_status_mismatch", "applies": True,
             "confidence_adjustment_pct": -12.0, "quote": "design_status: Design In",
             "rationale": "Design In at DVT is inconsistent in my reading of the funnel.", "confidence": 0.6},
            {"rule_id": "J-04", "key": "early_stage_optimism", "applies": True,
             "confidence_adjustment_pct": -15.0, "quote": "confidence: 0.8",
             "rationale": "0.80 looks high for such an early stage of validation.", "confidence": 0.6},
        ]
        check = check_factors(reply, b, allowed_keys=set(BY_KEY), factor_cap_pp=None, citable=citable_text(b))
        assert check.fired == []
        assert {f.guard for f in check.rejected} == {"matrix_a_contradiction", "not_early"}


def test_j01_fires_only_on_a_forbidden_cell():
    forbidden = bundle_for("Hercules", stage="Concept", matrix_a_forbidden=True, matrix_a_baseline=None)
    assert fired(_mock_score(forbidden))["stage_status_mismatch"] == -20.0
    allowed = bundle_for("Hercules")
    assert "stage_status_mismatch" not in fired(_mock_score(allowed))


def test_j04_fires_on_an_early_row_above_tolerance_and_not_at_baseline():
    # Apollo: Evaluation at EVT, entered 0.50 against a 0.35 baseline -> +0.15,
    # which is not *more than* the tolerance, so it stays quiet.
    assert "early_stage_optimism" not in fired(_mock_score(bundle_for("Apollo")))
    # Push it to 0.55 and it fires.
    assert fired(_mock_score(bundle_for("Apollo", confidence=0.55)))["early_stage_optimism"] == -15.0
    # Hermes sits exactly on its baseline (0.30 Sample at EVT): no deviation.
    assert "early_stage_optimism" not in fired(_mock_score(bundle_for("Hermes")))


# --------------------------------------------------------------------------- #
# Concentration needs portfolio context (WBS 7.1)
# --------------------------------------------------------------------------- #

def test_portfolio_shares_reproduce_the_specification_c12_table():
    fins = [compute_project_financials({**r, "unit_set": None}) for r in ROWS]
    conc = concentration(fins)
    assert conc["total_adjusted_revenue_k"] == pytest.approx(30915.0)
    assert conc["cuts"]["region"]["largest"] == "Korea"
    assert conc["cuts"]["region"]["share"] == pytest.approx(0.813, abs=0.001)
    assert conc["cuts"]["end_customer"]["largest"] == "Ford"
    assert conc["cuts"]["end_customer"]["share"] == pytest.approx(0.602, abs=0.001)
    assert conc["cuts"]["row"]["largest"] == "Hermes"
    assert conc["cuts"]["row"]["share"] == pytest.approx(0.388, abs=0.001)
    assert conc["cuts"]["part_number"]["largest"] == "AX01"
    assert conc["cuts"]["part_number"]["share"] == pytest.approx(0.398, abs=0.001)

    shares = portfolio_context(fins)
    assert shares["Hermes"].row_share_of_region == pytest.approx(12000 / 25140)
    assert shares["Hermes"].region_row_count == 5


def test_concentration_fires_on_the_korea_case_and_is_dark_without_context():
    fins = [compute_project_financials({**r, "unit_set": None}) for r in ROWS]
    shares = portfolio_context(fins)
    with_context = bundle_for("Hermes", _portfolio=shares["Hermes"].as_bundle())
    result = _mock_score(with_context)
    assert fired(result)["customer_concentration"] == -10.0
    j05 = next(f for f in result if f["key"] == "customer_concentration")
    assert "47.7%" in j05["rationale"]
    # And the quote is verbatim from the bundle text the model was shown.
    assert j05["quote"].lower() in citable_text(with_context).lower()

    without = _mock_score(bundle_for("Hermes"))
    j05 = next(f for f in without if f["key"] == "customer_concentration")
    assert not j05["applies"] and "_portfolio is absent" in j05["rationale"]


# --------------------------------------------------------------------------- #
# Positive and negative fixture per remaining rule (WBS 12.2)
# --------------------------------------------------------------------------- #

def test_j02_named_competitor():
    assert fired(_mock_score(bundle_for("Hugo", competitor_part="RIVAL-9")))["named_competitor_threat"] == -10.0
    assert "named_competitor_threat" not in fired(_mock_score(bundle_for("Hugo", competitor_part="TBD")))


def test_j03_design_win_lock_in_supports_only_a_pvt_design_win():
    assert fired(_mock_score(bundle_for("Hercules")))["design_win_lock_in"] == 5.0
    assert "design_win_lock_in" not in fired(_mock_score(bundle_for("Aphrodite")))


def test_j06_submitter_calibration_needs_a_bias_beyond_one_sd():
    cal = {"bias_pp": 12.0, "sd_pp": 5.0, "sample_size": 8}
    assert fired(_mock_score(bundle_for("Apollo", _calibration=cal)))["submitter_calibration"] == -10.0
    quiet = {"bias_pp": 2.0, "sd_pp": 5.0, "sample_size": 8}
    assert "submitter_calibration" not in fired(_mock_score(bundle_for("Apollo", _calibration=quiet)))


def test_j07_dual_sourcing_reads_the_evidence():
    b = bundle_for("Hugo", competitor_part="RIVAL-9", evidence="Customer requires dual sourcing on this socket.")
    assert fired(_mock_score(b))["dual_sourcing"] == -7.0
    assert "dual_sourcing" not in fired(_mock_score(bundle_for("Hugo", competitor_part="RIVAL-9")))


def test_j08_cancellation_risk_from_evidence_or_sop_slip():
    assert fired(_mock_score(bundle_for("Poseidon", _sop_slip_months=0, evidence="Programme on hold pending budget.")))["cancellation_risk"] == -12.0
    assert fired(_mock_score(bundle_for("Poseidon", _sop_slip_months=3)))["cancellation_risk"] == -6.0
    assert "cancellation_risk" not in fired(_mock_score(bundle_for("Poseidon", _sop_slip_months=0)))


def test_j09_stage_stall_at_one_and_a_half_times_the_median():
    assert fired(_mock_score(bundle_for("Aphrodite", _days_in_stage=197, _stage_median_days=120)))["stage_stall"] == -8.0
    assert "stage_stall" not in fired(_mock_score(bundle_for("Aphrodite", _days_in_stage=100, _stage_median_days=120)))


def test_j10_milestone_slip_cites_the_source_substring():
    overdue = [{"label": "PPAP", "source_substring": "PPAP: Oct'25", "due": "2025-10-01"}]
    result = _mock_score(bundle_for("Dresden", _overdue_milestones=overdue))
    assert fired(result)["milestone_slip"] == -8.0
    assert next(f for f in result if f["key"] == "milestone_slip")["quote"] == "PPAP: Oct'25"
    assert "milestone_slip" not in fired(_mock_score(bundle_for("Dresden", _overdue_milestones=[])))


def test_j11_eau_plausibility_catches_ip901_and_passes_hermes():
    # Funnel IP901: 130,790 Kpcs / 4 per set = 32,697 Ksets -- a third of world production.
    assert fired(_mock_score(bundle_for("Hermes", _set_volume_ksets=32697.5)))["eau_plausibility"] == -20.0
    # Hermes: 10,000 / 15 = 666.7 Ksets, plausible for a Ford powertrain programme.
    assert "eau_plausibility" not in fired(_mock_score(bundle_for("Hermes", _set_volume_ksets=666.7)))


def test_j12_data_completeness_names_the_missing_fields():
    result = _mock_score(bundle_for("Yellowstone", _missing_required=["disty_asp", "owner"]))
    assert fired(result)["data_completeness"] == -10.0
    assert "disty_asp, owner" in next(f for f in result if f["key"] == "data_completeness")["rationale"]
    assert "data_completeness" not in fired(_mock_score(bundle_for("Yellowstone")))


def test_j13_price_anomaly_but_not_the_formula():
    assert fired(_mock_score(bundle_for("Hugo", _channel_margin_pct=-0.03)))["price_anomaly"] == -5.0
    assert fired(_mock_score(bundle_for("Hugo", _channel_margin_pct=0.22)))["price_anomaly"] == -5.0
    assert "price_anomaly" not in fired(_mock_score(bundle_for("Hugo", _channel_margin_pct=0.025)))
    assert "price_anomaly" not in fired(_mock_score(bundle_for("Hugo")))  # 6.25% on the fixture


# --------------------------------------------------------------------------- #
# The contract (WBS 7.4)
# --------------------------------------------------------------------------- #

def ok_factor(**kw) -> Factor:
    base = dict(rule_id="J-02", key="named_competitor_threat", delta_pp=-10.0,
                quote="competitor_part: RIVAL-1", rationale="A named rival is on the socket.")
    base.update(kw)
    return Factor(**base)


def test_a_valid_proposal_constructs():
    p = ConfidenceProposal("opp", prior=0.30, proposed=0.20, factors=(ok_factor(),), rubric_version="2026.1")
    assert p.movement_pp == pytest.approx(-10.0)
    assert p.fired_rule_ids == ("J-02",)


@pytest.mark.parametrize("kwargs,message", [
    (dict(proposed=0.96, factors=(ok_factor(delta_pp=-1.0),)), "outside"),
    (dict(proposed=0.04, prior=0.10, factors=(ok_factor(delta_pp=-6.0),)), "outside"),
    (dict(prior=0.80, proposed=0.55, factors=(ok_factor(delta_pp=-12.0), ok_factor(rule_id="J-04", key="early_stage_optimism", delta_pp=-13.0))), "per-run cap"),
    (dict(prior=0.30, proposed=0.25, factors=()), "at least one factor"),
    (dict(factors=(ok_factor(quote="   "),)), "evidence quote"),
    (dict(factors=(ok_factor(delta_pp=+5.0),)), "haircut rule"),
    (dict(factors=(ok_factor(rule_id="J-03", key="design_win_lock_in", delta_pp=-5.0),)), "support rule"),
    (dict(factors=(ok_factor(delta_pp=-13.0),)), "cap of 12"),
    (dict(factors=(ok_factor(rule_id="J-99"),)), "Matrix B rule id"),
    (dict(factors=(ok_factor(), ok_factor())), "cited twice"),
    (dict(factors=(ok_factor(delta_pp=0.0),)), "zero adjustment"),
])
def test_an_out_of_bounds_proposal_cannot_be_constructed(kwargs, message):
    base = dict(opportunity_id="opp", prior=0.30, proposed=0.20, factors=(ok_factor(),), rubric_version="2026.1")
    base.update(kwargs)
    with pytest.raises(ContractViolation, match=message):
        ConfidenceProposal(**base)


# --------------------------------------------------------------------------- #
# The model path (WBS 7.6, 12.3)
# --------------------------------------------------------------------------- #

def _fake_client(monkeypatch, *, stop_reason="end_turn", blocks=None):
    class Messages:
        def __init__(self):
            self.kwargs = None

        def create(self, **kwargs):
            self.kwargs = kwargs
            return SimpleNamespace(stop_reason=stop_reason, content=blocks or [])

    messages = Messages()
    fake_anthropic = SimpleNamespace(Anthropic=lambda **_: SimpleNamespace(messages=messages))
    monkeypatch.setitem(__import__("sys").modules, "anthropic", fake_anthropic)
    return messages


def text_block(text: str):
    return SimpleNamespace(type="text", text=text)


def test_live_request_fixes_the_reply_shape_with_a_schema(monkeypatch):
    good = json.dumps({"factors": [{"rule_id": "J-02", "key": "named_competitor_threat", "applies": False,
                                    "confidence_adjustment_pct": 0.0, "quote": "", "rationale": "", "confidence": 0.3}]})
    messages = _fake_client(monkeypatch, blocks=[SimpleNamespace(type="thinking", thinking=""), text_block(good)])
    factors = _live_score(bundle_for("Hugo"))
    assert factors[0]["key"] == "named_competitor_threat"
    assert messages.kwargs["output_config"]["format"]["schema"] is REPLY_SCHEMA
    assert "Concept < EVT < DVT < PVT" in messages.kwargs["system"]
    assert messages.kwargs["max_tokens"] >= 8000


@pytest.mark.parametrize("stop_reason,blocks,message", [
    ("max_tokens", [text_block('{"factors": [')], "truncated"),
    ("refusal", [], "refused"),
    ("end_turn", [SimpleNamespace(type="thinking", thinking="")], "no text block"),
    ("end_turn", [text_block("```json\n{\"factors\": []}\n```")], "not JSON"),
    ("end_turn", [text_block('{"answer": 42}')], "no 'factors' list"),
])
def test_every_live_failure_raises_loudly(monkeypatch, stop_reason, blocks, message):
    _fake_client(monkeypatch, stop_reason=stop_reason, blocks=blocks)
    with pytest.raises(JudgmentReplyError, match=message):
        _live_score(bundle_for("Hugo"))


def test_a_live_failure_is_recorded_when_it_falls_back_and_raises_when_it_may_not(monkeypatch):
    _fake_client(monkeypatch, stop_reason="max_tokens", blocks=[])
    monkeypatch.setattr(rubric_module.settings, "judgment_mode", "live")
    monkeypatch.setattr(rubric_module.settings, "anthropic_api_key", "sk-test")

    monkeypatch.setattr(rubric_module.settings, "judgment_fallback_to_mock", True)
    result = score_confidence_factors(bundle_for("Hugo"))
    assert result["mode"] == "mock"
    assert "truncated" in result["fallback_error"]

    monkeypatch.setattr(rubric_module.settings, "judgment_fallback_to_mock", False)
    with pytest.raises(JudgmentReplyError):
        score_confidence_factors(bundle_for("Hugo"))


# --------------------------------------------------------------------------- #
# End to end over the nine rows (WBS 7.1 done-when)
# --------------------------------------------------------------------------- #

def load_nine(client):
    ids = {}
    for row in ROWS:
        payload = {k: v for k, v in row.items() if k != "comments"}
        payload.update({"owner": "jdoe", "confidence_rationale": row["comments"], "evidence": row["comments"],
                        "application": "Lighting", "product_line": "Driver"})
        resp = client.post("/api/v1/opportunities", json=payload, headers=headers("director"))
        assert resp.status_code == 201, resp.text
        ids[row["project"]] = resp.json()["id"]
    return ids


def test_a_run_over_the_nine_rows_with_rubric_v1(client):
    """publish_v1, then one run over the specification's nine rows.

    What the rubric says about this portfolio, row by row: it is concentrated
    -- Ford is 60% of the weighted pipeline, Korea 81%, Hermes 48% of Korea,
    Yellowstone 83% of Taiwan -- so J-05 fires on six rows. Aphrodite and
    Montana are untouched. Poseidon at 0.10 hits the 0.05 floor and is
    flagged; Hercules at 1.00 hits the 0.95 ceiling and is flagged. Every
    proposal queues under gate_all, and the recompute is the calc engine on
    the proposed confidences."""
    ids = load_nine(client)
    version = client.post("/api/v1/rubric/publish-v1", headers=headers("admin")).json()
    assert version["label"] == "2026.1"
    assert version["rubric_factors"]["review_policy"] == "gate_all"
    assert version["rubric_factors"]["caps"]["run_cap_pp"] == 20.0
    # Idempotent: a second publish-v1 returns the same version.
    assert client.post("/api/v1/rubric/publish-v1", headers=headers("admin")).json()["id"] == version["id"]

    run = client.post("/api/v1/runs", json={}, headers=headers("admin")).json()
    assert run["status"] == "completed"
    assert run["counts"]["base_adjusted_revenue_k"] == pytest.approx(30915.0)
    assert run["counts"]["queued"] == 9 and run["counts"]["auto_applied"] == 0
    assert next(s for s in run["steps"] if s["name"] == "Lifecycle")["status"] == "ran"

    proposals = {p["project"]: p for p in client.get("/api/v1/proposals", headers=headers("director")).json()}
    rules = {name: sorted(f["rule_id"] for f in p["factors"] if f["applies"]) for name, p in proposals.items()}
    proposed = {name: p["proposed_confidence"] for name, p in proposals.items()}

    assert rules["Aphrodite"] == [] and proposed["Aphrodite"] == pytest.approx(0.80)
    assert rules["Montana"] == [] and proposed["Montana"] == pytest.approx(0.80)
    assert rules["Hermes"] == ["J-05"] and proposed["Hermes"] == pytest.approx(0.20)
    assert rules["Hercules"] == ["J-03"] and proposed["Hercules"] == pytest.approx(0.95)
    assert proposals["Hercules"]["flags"]["clamped_from"] == pytest.approx(1.05)
    assert rules["Yellowstone"] == ["J-03", "J-05"] and proposed["Yellowstone"] == pytest.approx(0.95)
    assert proposals["Yellowstone"]["flags"] == {}
    assert rules["Poseidon"] == ["J-05"] and proposed["Poseidon"] == pytest.approx(0.05)
    assert proposals["Poseidon"]["flags"]["clamped_from"] == pytest.approx(0.02)
    assert rules["Apollo"] == ["J-05"] and proposed["Apollo"] == pytest.approx(0.42)
    assert rules["Hugo"] == ["J-05"] and proposed["Hugo"] == pytest.approx(0.20)
    assert rules["Dresden"] == ["J-05"] and proposed["Dresden"] == pytest.approx(0.40)
    assert all(p["band_crossing"] is not None for p in proposals.values())
    assert all(p["status"] == "pending" for p in proposals.values())

    # Every quote is verbatim: it appears in the bundle text the scorer saw.
    for p in proposals.values():
        for f in p["factors"]:
            if f["applies"]:
                assert f["quote"], f"{p['project']} {f['rule_id']} fired without a quote"

    # Recompute is the calc engine over the proposed confidences, row by row.
    expected_delta = (
        40000 * (0.20 - 0.30) + 16000 * (0.05 - 0.10) + 10000 * (0.42 - 0.50)
        + 2250 * (0.20 - 0.30) + 3000 * (0.40 - 0.50) + 3300 * (0.95 - 1.0) + 3000 * (0.95 - 1.0)
    )
    assert run["counts"]["delta_adjusted_revenue_k"] == pytest.approx(expected_delta)
    assert proposals["Hermes"]["opportunity_id"] == ids["Hermes"]
