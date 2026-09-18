# Walkthrough -- the Opportunity Tracking Agent on TrackF (1).xlsx

Generated 2026-09-17 by `python -m scripts.walkthrough` from the real workbook into a fresh database. Three things, in the order the specification asked for them: what the file gets wrong, what the pipeline is before and after the agent's proposals, and the audit trail behind one changed number.

## 1. What the file gets wrong

Rules V-a..V-i over the six tabs: **17 blocking, 17 advisory, 1 cosmetic**. All 12 of the specification's twelve documented findings are reproduced from the file; two the specification missed are found (ID802 and ID803 imply 36.8M and 35.0M vehicle sets a year, the same defect as IP901).

```

BLOCKING  V-a  ProjectTrack!row 14                                  row carries 'Evaluation' with region 'North America' and EAU 100 but no customer, project, disty_asp -- Sales Revenue computes to zero, so it is excluded and counted [F-08]
BLOCKING  V-a  ProjectTrack!row 15                                  row carries 'Evaluation' with region 'North America' and EAU 100 but no customer, project, disty_asp -- Sales Revenue computes to zero, so it is excluded and counted [F-08]
BLOCKING  V-a  ProjectTrack!row 16                                  row carries 'Design Win' with region 'Japan' and EAU 1000 but no customer, project, disty_asp -- Sales Revenue computes to zero, so it is excluded and counted [F-08]
BLOCKING  V-a  ProjectTrack!row 17                                  row carries 'Design Win' with region 'Japan' and EAU 500 but no customer, project, disty_asp -- Sales Revenue computes to zero, so it is excluded and counted [F-08]
BLOCKING  V-a  ProjectTrack!row 18                                  row carries 'Promotion' with region 'Japan' and EAU 500 but no customer, project, disty_asp -- Sales Revenue computes to zero, so it is excluded and counted [F-08]
BLOCKING  V-d  Funnel!J6, Funnel!K6                                 IP901: 130,790 Kpcs at 4 units per set implies 32.7M vehicle sets a year -- either the EAU or the Unit/Set value is wrong [F-05]
BLOCKING  V-d  Funnel!J7, Funnel!K7                                 ID802: 294,009 Kpcs at 8 units per set implies 36.8M vehicle sets a year -- either the EAU or the Unit/Set value is wrong [F-05]
BLOCKING  V-d  Funnel!J8, Funnel!K8                                 ID803: 70,000 Kpcs at 2 units per set implies 35.0M vehicle sets a year -- either the EAU or the Unit/Set value is wrong [F-05]
BLOCKING  V-e  Funnel!J5 vs FCST_Revenue!J5                         ID801 reads 57,175 Kpcs on Funnel and 1,343 Kpcs on FCST_Revenue -- a 43x gap that only makes sense if one is programme-lifetime and the other annual; both are kept and neither is chosen [F-06]
BLOCKING  V-e  Funnel!J6 vs FCST_Revenue!J7                         IP901 reads 130,790 Kpcs on Funnel and 1,464 Kpcs on FCST_Revenue -- a 89x gap that only makes sense if one is programme-lifetime and the other annual; both are kept and neither is chosen [F-06]
BLOCKING  V-f  R21, S21, T21...                                     Europe Region roll-up: 10 cells are =SUM(#REF!) -- the references are gone [F-01]
BLOCKING  V-f  AB21                                                 Europe Region cy26_units_ttl is =SUM(AB5:AB20): the range includes the Korea Region roll-up row(s), so it double-counts Korea [F-02]
BLOCKING  V-f  R22, S22, T22...                                     Taiwan Region roll-up: 10 cells are =SUM(#REF!) -- the references are gone [F-01]
BLOCKING  V-f  AB22                                                 Taiwan Region cy26_units_ttl is =SUM(AB5:AB20): the range includes the Korea Region roll-up row(s), so it double-counts Korea [F-02]
BLOCKING  V-f  AB23                                                 Japan Region cy26_units_ttl is =SUM(AB6:AB21): the range includes the Korea Region, Europe Region roll-up row(s), so it double-counts other regions' subtotals [F-03]
BLOCKING  V-f  AG23                                                 Japan Region cy26_revenue_k_ttl is =SUM(AG6:AG21): the range includes the Korea Region, Europe Region roll-up row(s), so it double-counts other regions' subtotals [F-03]
BLOCKING  V-f  R24, W24, AG24                                       Elevation Micro Total inherits every error above, so the headline number does not compute (3 of its cells are #REF!) [F-04]
ADVISORY  V-a  Funnel!O10                                           competitor_part holds the text 'TBD' in a typed field; coerced to null, never to zero [F-07]
ADVISORY  V-a  Funnel!J11                                           eau_kpcs holds the text 'TBD' in a numeric field; coerced to null, never to zero [F-07]
  ...
```

## 2. The pipeline, before

9 complete rows loaded through the intake service (the five skeleton rows are findings, not rows). Rubric **2026.1** published: Matrix A per the decision register, thirteen Matrix B rules, 0.05-0.95, a 20pp run cap, gate_all. One liberty: the workbook has no owner column, and without an owner J-12 (data completeness) haircuts every row by 10pp -- correct, and it drowns everything else -- so each row is given a nominal owner per region here. That is the case for the owner field.

| Project | Region | Status / stage | EAU Kpcs | ASP | Sales revenue | Confidence | Adjusted |
|---|---|---|---:|---:|---:|---:|---:|
| Hermes | Korea | Sample / EVT | 10,000 | $4.00 | $40,000K | 0.30 | $12,000K |
| Apollo | Korea | Evaluation / EVT | 5,000 | $2.00 | $10,000K | 0.50 | $5,000K |
| Hercules | Korea | Design Win / PVT | 1,100 | $3.00 | $3,300K | 1.00 | $3,300K |
| Aphrodite | Korea | Design In / DVT | 1,350 | $3.00 | $4,050K | 0.80 | $3,240K |
| Yellowstone | Taiwan | Design Win / PVT | 1,000 | $3.00 | $3,000K | 1.00 | $3,000K |
| Poseidon | Korea | Promotion / Concept | 8,000 | $2.00 | $16,000K | 0.10 | $1,600K |
| Dresden | Europe | Evaluation / EVT | 1,000 | $3.00 | $3,000K | 0.50 | $1,500K |
| Hugo | Europe | Evaluation / EVT | 750 | $3.00 | $2,250K | 0.30 | $675K |
| Montana | Taiwan | Design In / DVT | 250 | $3.00 | $750K | 0.80 | $600K |
| **Total** | | | | | **$82,350K** | | **$30,915K** |

## 3. One run, ten steps

Mode **mock** (the rule-based scorer over the same Matrix A; the live model waits on the security sign-off). 9 rows scored, 9 proposals, 9 queued for a person, 0 applied without one, 1 lifecycle move(s) proposed.

 1. **Intake** (ran) -- 9 opportunity rows read from the database. No workbook snapshot: this run scores live rows, so there is no sealed source to hash (WBS 3.2 covers the import path).
 2. **Validate** (ran) -- 0 rows blocking (excluded from every total, WBS 4.2; a forbidden Matrix A pairing is blocking per decision #10), 0 advisory findings.
 3. **Compute** (ran) -- C1/C2 over 9 rows: $30,915.0K adjusted revenue, app/calc/engine.py, no model involvement.
 4. **Precedent** (ran) -- L3 memory (app/memory): filtered by region, product line and recency before ranking; 8 of 9 rows have comparable precedent, top-6 within a token budget. Numbers and pricing are scrubbed at write time. Calibration priors: 0 owners.
 5. **Score** (ran) -- one call per row, 9 rows, mock scorer. The bundle carries the row, its Matrix A cell, its portfolio shares and derived ratios -- no C1, no C2 -- and the reply is percentage points, quotes and rationales, never a figure.
 6. **Check** (ran) -- 8 factors fired, 54 not assessable, 0 rejected by a guard, 0 clipped to a cap. Ten guards, app/judgment/reply_guards.py, then the ConfidenceProposal contract -- rejected factors are kept on the proposal, not dropped.
 7. **Recompute** (ran) -- the same function as step 3, called again with the proposed confidences: $24,475.0K, a -6,440.0K change. That the two figures come from one function is what makes the delta mean anything.
 8. **Lifecycle** (ran) -- 0 of 9 confidence proposals cross a band in rubric version 2026.1; 2 carry a bounds flag. 1 lifecycle transition(s) proposed for a person with the close grant -- the agent moves nothing itself (decision #36): Hercules -> Mass Production (Design Win at PVT with M/P date 2026-09-01 on or before 2026-09-17).
 9. **Approve** (ran) -- review policy gate_all: 9 proposals queued for review, 0 applied without a person.
10. **Log** (ran) -- 9 confidence_event rows written, each stamping rubric version 2026.1 and the scorer mode. Append-only: nothing in this codebase updates or deletes one.

## 4. The pipeline, after -- if every proposal were approved

| Project | Entered | Proposed | Rules fired | Flags | Adjusted before | Adjusted after |
|---|---:|---:|---|---|---:|---:|
| Hermes | 0.30 | 0.20 | J-05 -10pp |  | $12,000K | $8,000K |
| Apollo | 0.50 | 0.42 | J-05 -8pp |  | $5,000K | $4,200K |
| Hercules | 1.00 | 0.95 | J-03 +5pp | clamped_from | $3,300K | $3,135K |
| Aphrodite | 0.80 | 0.80 | none |  | $3,240K | $3,240K |
| Yellowstone | 1.00 | 0.95 | J-03 +5pp, J-05 -10pp |  | $3,000K | $2,850K |
| Poseidon | 0.10 | 0.05 | J-05 -8pp | clamped_from | $1,600K | $800K |
| Dresden | 0.50 | 0.40 | J-05 -10pp |  | $1,500K | $1,200K |
| Hugo | 0.30 | 0.20 | J-05 -10pp |  | $675K | $450K |
| Montana | 0.80 | 0.80 | none |  | $600K | $600K |
| **Total** | | | | | **$30,915K** | **$24,475K** (-6,440K) |

Aphrodite and Montana -- both Design In at DVT, the two rows the first live run docked for a mismatch and for being 'early' -- are untouched: J-01 reads Matrix A as a flag and J-04 reads the stage order as a constant, and two guards refuse either firing regardless of what a model says.

## 5. The audit trail behind one changed number: Hermes

Hermes is the largest row ($40,000K sales revenue) and one of the least certain (Sample at EVT, entered at 0.30). The agent proposed **0.20**.

- **J-01 stage_status_mismatch** -- did not apply. matrix_a_forbidden is false; the pairing is allowed (MOCK scorer).
- **J-02 named_competitor_threat** -- not assessable. competitor_part is absent on this row (MOCK scorer).
- **J-03 design_win_lock_in** -- did not apply. not a Design Win at PVT (MOCK scorer).
- **J-04 early_stage_optimism** -- did not apply. confidence is within tolerance of the Matrix A baseline (MOCK scorer).
- **J-05 customer_concentration** -- fired, -10pp; quote: `row_share_of_region": 0.4773`. This row is 47.7% of Korea's weighted pipeline, over the 25% single-row trigger (MOCK scorer).
- **J-06 submitter_calibration** -- not assessable. _calibration is absent on this row (MOCK scorer).
- **J-07 dual_sourcing** -- not assessable. competitor_part is absent on this row (MOCK scorer).
- **J-08 cancellation_risk** -- not assessable. evidence is absent on this row (MOCK scorer).
- **J-09 stage_stall** -- not assessable. _days_in_stage is absent on this row (MOCK scorer).
- **J-10 milestone_slip** -- not assessable. _overdue_milestones is absent on this row (MOCK scorer).
- **J-11 eau_plausibility** -- did not apply. set volume is plausible (MOCK scorer).
- **J-12 data_completeness** -- did not apply. every required field is present (MOCK scorer).
- **J-13 price_anomaly** -- did not apply. channel margin is inside the observed band (MOCK scorer).

A director approves it. The row's confidence is now 0.20; Adjusted Revenue is recomputed by the calc engine from that number -- $8,000K, from $12,000K -- and the portfolio moves by exactly that row's delta.

The append-only stream for the row:

| When | Event | From | To | Actor | Version stamps |
|---|---|---:|---:|---|---|
| 2026-09-17 17:24:34 | proposal | 0.30 | 0.20 | agent (service) | 2026.09-matrixB;rubric:2026.1; model none |
| 2026-09-17 17:24:34 | approval | 0.30 | 0.20 | walkthrough-director (director) | —; model none |

Nothing in the codebase updates or deletes one of these rows; the ORM refuses to, for every role.

## 6. What the analyses say about this portfolio

- **Margin and price** (partial): $5,390K channel margin across 9 priced rows; 0 outside the 0-15% band
- **Competitive exposure** (partial): no row names a competitor part
- **Concentration risk** (live): Korea is 79% of the weighted pipeline (region)
- **Contradiction and data quality** (live): 9 of 9 scorable rows carry no finding; 0 excluded as blocking
- **Milestone and stall detection** (partial): 0 overdue milestone(s), 0 stalled row(s)
- **Stage mix and pipeline health** (live): 62% of the weighted pipeline has not reached DVT -- top-heavy
- Coverage against target: dark -- waiting on G1 (Regional Target), G2 (Target Period)
- EAU cross-check and white space: dark -- waiting on P1 (Programme Build Volume), P2 (Programme SoP)
- Forecast accuracy: dark -- waiting on A1 (Shipped Revenue), A3 (Forecast Vintage)
- Owner calibration: dark -- waiting on H3 (Resolved Outcome), O1 (Owner Bias)

## 7. What is still an input, not work

- The security sign-off for sending pipeline data to a hosted model: until then `JUDGMENT_MODE=mock`.
- Finance's targets (coverage), ERP and distributor actuals plus two quarters (forecast accuracy, owner calibration), the vehicle-programme licence (EAU cross-check, white space). Each lights up on its own the day the input lands.
- David Nam's ratification of Matrix A, the 0.95 ceiling and the close policy. The provisional values are published as rubric version 2026.1; a ratified table is a new version, not a code change.
