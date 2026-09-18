"""
The eight guards on the model's reply (app/judgment/reply_guards.py, step 6 of
the ten-step run).

Each guard gets a case built the way the real reply arrives -- a list of dicts
from the scorer -- because the guard's whole job is to distrust that list.
"""

from app.judgment.reply_guards import GUARD_IDS, check_factors

ALLOWED = {
    "stage_status_mismatch", "named_competitor_threat", "design_win_lock_in",
    "early_stage_optimism", "customer_concentration", "submitter_calibration",
}

ROW = {
    "design_status": "Design Win", "stage": "PVT", "competitor_part": "RIVAL-1",
    "confidence": 0.9, "customer": "Mobis", "region": "Korea", "owner": "jdoe",
    "matrix_a_forbidden": False, "matrix_a_baseline": 0.90,
    "_calibration": None,  # no calibration record exists for anyone yet
}


def factor(key, applies=True, adj=-10.0, rationale="A named competitor is on this socket already.", conf=0.6,
           quote="competitor_part: RIVAL-1"):
    return {"key": key, "applies": applies, "confidence_adjustment_pct": adj,
            "quote": quote, "rationale": rationale, "confidence": conf}


def test_a_clean_factor_is_accepted_and_counted():
    check = check_factors([factor("named_competitor_threat")], ROW, allowed_keys=ALLOWED, factor_cap_pp=None)
    assert check.fired and check.fired[0].key == "named_competitor_threat"
    assert check.total_adjustment_pp == -10.0


def test_unknown_rule_is_rejected():
    check = check_factors([factor("vibes")], ROW, allowed_keys=ALLOWED, factor_cap_pp=None)
    assert check.rejected[0].guard == "unknown_rule"
    assert check.total_adjustment_pp == 0.0


def test_a_factor_whose_input_is_absent_is_not_assessable():
    row = {**ROW, "competitor_part": None}
    check = check_factors([factor("named_competitor_threat")], row, allowed_keys=ALLOWED, factor_cap_pp=None)
    assert check.not_assessable[0].guard == "not_assessable"
    assert "competitor_part" in check.not_assessable[0].detail
    assert check.total_adjustment_pp == 0.0


def test_submitter_calibration_is_dark_because_no_calibration_exists():
    check = check_factors([factor("submitter_calibration", adj=-5.0)], ROW,
                          allowed_keys=ALLOWED, factor_cap_pp=None)
    assert check.not_assessable[0].key == "submitter_calibration"


def test_firing_without_a_citation_is_rejected():
    check = check_factors([factor("named_competitor_threat", rationale="risky")], ROW,
                          allowed_keys=ALLOWED, factor_cap_pp=None)
    assert check.rejected[0].guard == "missing_citation"


def test_a_haircut_rule_that_supports_is_rejected():
    check = check_factors(
        [factor("named_competitor_threat", adj=+8.0, rationale="A competitor makes this stronger somehow.")],
        ROW, allowed_keys=ALLOWED, factor_cap_pp=None,
    )
    assert check.rejected[0].guard == "wrong_direction"


def test_a_support_rule_that_cuts_is_rejected():
    check = check_factors(
        [factor("design_win_lock_in", adj=-8.0, rationale="Locked in at PVT, so I am cutting it anyway.")],
        ROW, allowed_keys=ALLOWED, factor_cap_pp=None,
    )
    assert check.rejected[0].guard == "wrong_direction"


def test_out_of_contract_range_is_rejected():
    check = check_factors([factor("named_competitor_threat", adj=-90.0)], ROW,
                          allowed_keys=ALLOWED, factor_cap_pp=None)
    assert check.rejected[0].guard == "out_of_range"


def test_firing_with_a_zero_adjustment_is_rejected():
    check = check_factors([factor("named_competitor_threat", adj=0.0)], ROW,
                          allowed_keys=ALLOWED, factor_cap_pp=None)
    assert check.rejected[0].guard == "no_op_adjustment"


def test_a_malformed_reply_item_is_a_schema_rejection():
    check = check_factors(["not a factor"], ROW, allowed_keys=ALLOWED, factor_cap_pp=None)
    assert check.rejected[0].guard == "schema"


def test_over_cap_is_clipped_and_flagged_not_rejected():
    """The document's own example: -14.0pp against a cap of 10, clipped and
    flagged, with the model's original number kept for the reviewer to see."""
    check = check_factors([factor("named_competitor_threat", adj=-14.0)], ROW,
                          allowed_keys=ALLOWED, factor_cap_pp=10.0)
    clipped = check.clipped[0]
    assert clipped.accepted is True
    assert clipped.clipped_from == -14.0
    assert clipped.confidence_adjustment_pct == -10.0
    assert check.total_adjustment_pp == -10.0


def test_the_two_misfires_are_rejected_by_deterministic_guards():
    """Aphrodite and Montana, as guards rather than fixtures: J-01 on an
    allowed cell and J-04 on a non-early stage are refused no matter what the
    model said."""
    dvt_design_in = {**ROW, "design_status": "Design In", "stage": "DVT", "matrix_a_forbidden": False,
                     "matrix_a_baseline": 0.65, "confidence": 0.8}
    check = check_factors(
        [factor("stage_status_mismatch", adj=-12.0, rationale="Design In at DVT looks inconsistent to me."),
         factor("early_stage_optimism", adj=-15.0, rationale="0.80 is optimistic this early in the funnel.")],
        dvt_design_in, allowed_keys=ALLOWED, factor_cap_pp=None,
    )
    guards = {f.key: f.guard for f in check.factors}
    assert guards["stage_status_mismatch"] == "matrix_a_contradiction"
    assert guards["early_stage_optimism"] == "not_early"
    assert check.fired == []
    assert check.total_adjustment_pp == 0.0


def test_a_quote_must_be_verbatim_from_the_bundle():
    good = check_factors([factor("named_competitor_threat", quote="competitor_part: RIVAL-1")], ROW,
                         allowed_keys=ALLOWED, factor_cap_pp=None, citable="competitor_part: RIVAL-1\nstage: PVT")
    assert good.fired[0].key == "named_competitor_threat"
    bad = check_factors([factor("named_competitor_threat", quote="a rival part was mentioned")], ROW,
                        allowed_keys=ALLOWED, factor_cap_pp=None, citable="competitor_part: RIVAL-1\nstage: PVT")
    assert bad.rejected[0].guard == "missing_citation"


def test_matrix_b_cap_applies_even_with_no_published_cap():
    """Matrix B's own cap (J-02: 12pp) is the citation; a published version may
    lower it but its absence does not remove it."""
    check = check_factors([factor("named_competitor_threat", adj=-14.0)], ROW,
                          allowed_keys=ALLOWED, factor_cap_pp=None)
    assert check.clipped[0].clipped_from == -14.0
    assert check.total_adjustment_pp == -12.0
    lowered = check_factors([factor("named_competitor_threat", adj=-14.0)], ROW,
                            allowed_keys=ALLOWED, factor_cap_pp=None,
                            factor_caps={"named_competitor_threat": 5.0})
    assert lowered.total_adjustment_pp == -5.0


def test_a_factor_that_declined_to_fire_is_kept_in_the_trace():
    check = check_factors([factor("named_competitor_threat", applies=False, adj=0.0)], ROW,
                          allowed_keys=ALLOWED, factor_cap_pp=None)
    assert check.factors[0].accepted is True
    assert check.fired == []


def test_rejected_and_not_assessable_are_disjoint():
    """Reporting them as one number would tell a reviewer the model was wrong
    N times when it was actually silent N times."""
    row = {**ROW, "competitor_part": None}
    check = check_factors(
        [factor("named_competitor_threat"), factor("design_win_lock_in", adj=-5.0, rationale="A locked design win, cut anyway.")],
        row, allowed_keys=ALLOWED, factor_cap_pp=None,
    )
    assert [f.key for f in check.not_assessable] == ["named_competitor_threat"]
    assert [f.key for f in check.rejected] == ["design_win_lock_in"]
    assert not set(f.key for f in check.rejected) & set(f.key for f in check.not_assessable)


def test_every_named_guard_has_a_case_here():
    """If a guard is added, this test fails until it is covered."""
    covered = {
        "schema", "unknown_rule", "not_assessable", "missing_citation",
        "matrix_a_contradiction", "not_early",
        "wrong_direction", "out_of_range", "no_op_adjustment", "over_factor_cap",
    }
    assert set(GUARD_IDS) == covered
