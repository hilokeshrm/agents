"""
Matrix B -- the factor rubric as a rule table (WBS 7.2), and the stage order
stated explicitly (WBS 7.3).

Thirteen rules from section 06 of the build specification
(docs/Opportunity_Tracking_Agent_Build_Specification.html). Each declares:

- `id`         the rule ID a factor must cite (J-01 .. J-13);
- `key`        the stable key used in replies, proposals and the published
               rubric version (the six that already existed keep their names,
               so stored proposals stay readable);
- `direction`  which way the rule may push -- a haircut rule returning +pp is
               rejected by the wrong_direction guard, because a rubric that can
               argue both ways for the same condition is not a rubric;
- `cap_pp`     the most it may move confidence, from the specification's Cap
               column. A published rubric version may lower a cap; it may not
               raise one above this table without editing the table, because the
               table is the citation;
- `requires`   evidence-bundle fields that must be non-null before the rule can
               be assessed at all. A rule whose input is absent reports
               NOT ASSESSABLE rather than guessing (same discipline as
               app/registry/runnable.py). The underscore-prefixed names are
               derived context the bundle carries alongside the row -- portfolio
               shares, the Matrix A cell, the milestone parse -- never a revenue
               figure.

The two rewrites the first live run demanded (build spec, section 06, "The two
misfires, priced"):

- J-01 reads Matrix A. It fires only when the (Design Status, Stage) cell is
  marked forbidden in the published version. It never infers what a
  contradiction is -- that inference is what docked Aphrodite 12 points for a
  Design In at DVT, which the rules allow.
- J-04 uses STAGE_ORDER. "Early" means Concept or EVT, by position in the order,
  not by the model's reading of the word. That reading is what docked Montana 15
  points at DVT.

Both are also enforced by a deterministic guard in app/judgment/reply_guards.py,
so a prompt edit cannot bring either misfire back.
"""

from dataclasses import dataclass

# Hardware validation stages, in order. Mass Production is a Design Status, not
# a stage (decision register, section 2): a record entering MP keeps its last
# hardware stage.
STAGE_ORDER: tuple[str, ...] = ("Concept", "EVT", "DVT", "PVT")
EARLY_STAGES: frozenset[str] = frozenset(STAGE_ORDER[:2])

# J-04 fires when the entered confidence exceeds the Matrix A baseline for the
# cell by more than this (build spec, Matrix B: "J1 exceeds its Matrix A
# baseline by > 0.15").
EARLY_OPTIMISM_TOLERANCE = 0.15

# J-05 thresholds (build spec, C12: "Trigger at 25 / 40%").
ROW_SHARE_OF_REGION_TRIGGER = 0.25
OEM_SHARE_OF_PORTFOLIO_TRIGGER = 0.40

# J-09: a stage is stalled at this multiple of the historic median (build spec,
# C14 worked example: "1.5x stall threshold").
STALL_MULTIPLE = 1.5

HAIRCUT, SUPPORT, EITHER = "haircut", "support", "either"


@dataclass(frozen=True)
class Rule:
    id: str
    key: str
    label: str
    direction: str
    cap_pp: float
    requires: tuple[str, ...]
    guidance: str
    # Informational: which phase's data the rule needs. "live" rules can fire
    # on today's rows; the rest report not assessable until their input exists.
    availability: str = "live"


RULES: tuple[Rule, ...] = (
    Rule(
        id="J-01", key="stage_status_mismatch", label="Status / stage mismatch",
        direction=HAIRCUT, cap_pp=25.0,
        requires=("design_status", "stage", "matrix_a_forbidden"),
        guidance="Fires ONLY when matrix_a_forbidden is true -- the (Design Status, Stage) cell is "
                 "marked forbidden in the published Matrix A. Read the flag; never infer a "
                 "contradiction from the words. Design In at DVT is a valid pairing.",
    ),
    Rule(
        id="J-02", key="named_competitor_threat", label="Named competitor",
        direction=HAIRCUT, cap_pp=12.0,
        requires=("competitor_part",),
        guidance="A populated Competitor Part# (not 'TBD') means a rival is actively being evaluated "
                 "for the same socket. Cite the part number.",
    ),
    Rule(
        id="J-03", key="design_win_lock_in", label="Design win lock-in",
        direction=SUPPORT, cap_pp=8.0,
        requires=("design_status", "stage"),
        guidance="Design Win at PVT with no open risk factor on the row deserves support, not a "
                 "haircut. Support is only meaningful below the confidence ceiling.",
    ),
    Rule(
        id="J-04", key="early_stage_optimism", label="Early-stage optimism",
        direction=HAIRCUT, cap_pp=15.0,
        requires=("stage", "confidence", "matrix_a_baseline"),
        guidance="Stage order is Concept < EVT < DVT < PVT. 'Early' means Concept or EVT and nothing "
                 "else -- DVT is not early. Fires when stage is early AND the entered confidence "
                 "exceeds matrix_a_baseline by more than 0.15. Cite both numbers.",
    ),
    Rule(
        id="J-05", key="customer_concentration", label="Customer / region concentration",
        direction=HAIRCUT, cap_pp=10.0,
        requires=("_portfolio",),
        guidance="Read _portfolio: fires when this row is more than 25% of its region's weighted "
                 "pipeline, or its end customer is more than 40% of the whole portfolio's. Cite the "
                 "share. This needs portfolio context; a single row cannot show it.",
    ),
    Rule(
        id="J-06", key="submitter_calibration", label="Submitter calibration",
        direction=EITHER, cap_pp=10.0,
        requires=("owner", "_calibration"),
        guidance="The owner's historic forecast bias, from resolved outcomes. Fires only when "
                 "_calibration is present and its bias exceeds one standard deviation.",
        availability="phase4",
    ),
    Rule(
        id="J-07", key="dual_sourcing", label="Dual sourcing",
        direction=HAIRCUT, cap_pp=10.0,
        requires=("competitor_part", "evidence"),
        guidance="A second source is named, or the evidence text says the customer requires one. "
                 "Quote the evidence.",
    ),
    Rule(
        id="J-08", key="cancellation_risk", label="Cancellation risk",
        direction=HAIRCUT, cap_pp=15.0,
        requires=("evidence", "_sop_slip_months"),
        guidance="A programme cancellation signal in the evidence, or an SoP date that slipped "
                 "across runs (_sop_slip_months > 0). Slip detection needs two snapshots.",
        availability="phase2",
    ),
    Rule(
        id="J-09", key="stage_stall", label="Stage stall",
        direction=HAIRCUT, cap_pp=10.0,
        requires=("_days_in_stage", "_stage_median_days"),
        guidance="Fires when _days_in_stage exceeds 1.5 x _stage_median_days. Needs a population "
                 "to compute a median from; stays quiet until state history exists.",
        availability="phase2",
    ),
    Rule(
        id="J-10", key="milestone_slip", label="Milestone slip",
        direction=HAIRCUT, cap_pp=12.0,
        requires=("_overdue_milestones",),
        guidance="A parsed ES, PPAP, Design Review or SoP date is past due. Cite the source "
                 "substring the date was parsed from, not the parse.",
    ),
    Rule(
        id="J-11", key="eau_plausibility", label="EAU plausibility",
        direction=HAIRCUT, cap_pp=20.0,
        requires=("_set_volume_ksets",),
        guidance="EAU / Unit-per-set gives vehicle sets per year. Above 10,000 Ksets (ten million "
                 "vehicles a year for one programme) is implausible. Cite the figure.",
    ),
    Rule(
        id="J-12", key="data_completeness", label="Data completeness",
        direction=HAIRCUT, cap_pp=15.0,
        requires=("_missing_required",),
        guidance="A required field is null or 'TBD' on the row. _missing_required lists them; fires "
                 "only when the list is non-empty, and the citation names the fields.",
    ),
    Rule(
        id="J-13", key="price_anomaly", label="Price anomaly",
        direction=HAIRCUT, cap_pp=8.0,
        requires=("_channel_margin_pct",),
        guidance="_channel_margin_pct is a fraction (0.0698 = 6.98%). Fires when it is negative (Resale "
                 "below Distributor ASP) or above 0.15. Exactly 0.025 is a formula (Disty = Resale x "
                 "0.975), not an anomaly.",
    ),
)

BY_KEY: dict[str, Rule] = {r.key: r for r in RULES}
BY_ID: dict[str, Rule] = {r.id: r for r in RULES}

# A rule whose cap the published version leaves unset still has this table's
# cap. Only a lower published cap wins.
def effective_cap_pp(rule: Rule, published_cap_pp: float | None) -> float:
    if published_cap_pp is None:
        return rule.cap_pp
    return min(rule.cap_pp, float(published_cap_pp))


def is_early(stage: str | None) -> bool:
    return stage in EARLY_STAGES


def stage_index(stage: str | None) -> int | None:
    try:
        return STAGE_ORDER.index(stage)  # type: ignore[arg-type]
    except ValueError:
        return None
