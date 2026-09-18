# Rubric -- Matrix A and Matrix B

Generated from `app/judgment/matrix_b.py` and `app/services/rubric_versions.py`. The published rubric version in the database is the one in force; this page is the code's v1.

## Matrix A -- valid pairings and baseline confidence (provisional, decision register section 2)

| Design Status | Concept | EVT | DVT | PVT |
|---|---|---|---|---|
| Promotion | 0.10 | 0.15 | forbidden | forbidden |
| Sample | 0.20 | 0.30 | forbidden | forbidden |
| Evaluation | 0.20 | 0.35 | forbidden | forbidden |
| Design In | forbidden | forbidden | 0.65 | 0.80 |
| Design Win | forbidden | forbidden | forbidden | 0.90 |
| Mass Production | forbidden | forbidden | forbidden | 0.95 |
| Lost | 0.00 (terminal, reachable from any stage; needs a loss reason) | | | |

Bounds: floor 0.05, ceiling 0.95, per-factor cap 15.0pp, per-run cap 20.0pp. Review policy: `gate_all`.

Lifecycle bands (a proposal crossing one always reaches a person): early [0, 0.65), design_in [0.65, 0.9), design_win [0.9, 0.95), mass_production [0.95, 1)

Stage order: Concept < EVT < DVT < PVT. Early = Concept or EVT. J-04 tolerance: 0.15.

## Matrix B -- the thirteen factors

| Rule | Key | Direction | Cap (pp) | Requires | Availability | Condition |
|---|---|---|---|---|---|---|
| J-01 | `stage_status_mismatch` | haircut | 25 | design_status, stage, matrix_a_forbidden | live | Fires ONLY when matrix_a_forbidden is true -- the (Design Status, Stage) cell is marked forbidden in the published Matrix A. Read the flag; never infer a contradiction from the words. Design In at DVT is a valid pairing. |
| J-02 | `named_competitor_threat` | haircut | 12 | competitor_part | live | A populated Competitor Part# (not 'TBD') means a rival is actively being evaluated for the same socket. Cite the part number. |
| J-03 | `design_win_lock_in` | support | 8 | design_status, stage | live | Design Win at PVT with no open risk factor on the row deserves support, not a haircut. Support is only meaningful below the confidence ceiling. |
| J-04 | `early_stage_optimism` | haircut | 15 | stage, confidence, matrix_a_baseline | live | Stage order is Concept < EVT < DVT < PVT. 'Early' means Concept or EVT and nothing else -- DVT is not early. Fires when stage is early AND the entered confidence exceeds matrix_a_baseline by more than 0.15. Cite both numbers. |
| J-05 | `customer_concentration` | haircut | 10 | _portfolio | live | Read _portfolio: fires when this row is more than 25% of its region's weighted pipeline, or its end customer is more than 40% of the whole portfolio's. Cite the share. This needs portfolio context; a single row cannot show it. |
| J-06 | `submitter_calibration` | either | 10 | owner, _calibration | phase4 | The owner's historic forecast bias, from resolved outcomes. Fires only when _calibration is present and its bias exceeds one standard deviation. |
| J-07 | `dual_sourcing` | haircut | 10 | competitor_part, evidence | live | A second source is named, or the evidence text says the customer requires one. Quote the evidence. |
| J-08 | `cancellation_risk` | haircut | 15 | evidence, _sop_slip_months | phase2 | A programme cancellation signal in the evidence, or an SoP date that slipped across runs (_sop_slip_months > 0). Slip detection needs two snapshots. |
| J-09 | `stage_stall` | haircut | 10 | _days_in_stage, _stage_median_days | phase2 | Fires when _days_in_stage exceeds 1.5 x _stage_median_days. Needs a population to compute a median from; stays quiet until state history exists. |
| J-10 | `milestone_slip` | haircut | 12 | _overdue_milestones | live | A parsed ES, PPAP, Design Review or SoP date is past due. Cite the source substring the date was parsed from, not the parse. |
| J-11 | `eau_plausibility` | haircut | 20 | _set_volume_ksets | live | EAU / Unit-per-set gives vehicle sets per year. Above 10,000 Ksets (ten million vehicles a year for one programme) is implausible. Cite the figure. |
| J-12 | `data_completeness` | haircut | 15 | _missing_required | live | A required field is null or 'TBD' on the row. _missing_required lists them; fires only when the list is non-empty, and the citation names the fields. |
| J-13 | `price_anomaly` | haircut | 8 | _channel_margin_pct | live | _channel_margin_pct is a fraction (0.0698 = 6.98%). Fires when it is negative (Resale below Distributor ASP) or above 0.15. Exactly 0.025 is a formula (Disty = Resale x 0.975), not an anomaly. |

## Guards on the reply

Every factor the model returns passes ten guards before it counts (`app/judgment/reply_guards.py`): schema, unknown rule, not assessable, missing citation (a verbatim quote from the bundle), Matrix A contradiction (J-01 on an allowed cell), not early (J-04 off Concept/EVT), wrong direction, out of range, no-op adjustment, over the factor cap (clipped and flagged). Then the `ConfidenceProposal` contract refuses to construct anything outside the bounds.
