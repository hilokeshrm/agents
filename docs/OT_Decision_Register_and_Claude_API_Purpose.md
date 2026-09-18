# Opportunity Tracking Agent Decision Register

**Version:** 1.0
**Date:** 2026-09-09
**Status:** Recommended defaults pending business and security sign-off

This document consolidates the open-question answers for the Opportunity Tracking Agent. The decisions are intended to be implementation defaults. They should be formally approved by the business owner, Finance, Security, and the ROI Agent owner before production release.

## 1. Executive Decisions

1. Matrix A is the source of truth for valid status/stage combinations and baseline confidence.
2. Confidence is bounded from 0.05 to 0.95. The agent proposes changes; it never applies them directly.
3. Invalid status/stage combinations are blocking findings and are excluded from forecast totals.
4. Every opportunity has an immutable UUID, a human-readable external ID, and one accountable owner.
5. Mass Production and Design Lost require human approval before changing lifecycle status.
6. The latest business-approved workbook is canonical and is stored as an immutable, hashed snapshot.
7. Quarterly phasing uses programme profiles first, M/P-date ramp second, and reports unphased values when neither exists.
8. Sensitive NDA and customer-pricing data uses local vLLM by default. Hosted Claude requires Security approval.
9. Direct entry, workbook import, CRM sync, and API writes share one canonical intake schema.
10. ROI receives a versioned, snapshot-linked feed but keeps an independent forecast for cross-checking.

## 2. Matrix A

`Mass Production` is a Design Status, not a hardware Stage. Hardware stages remain Concept, EVT, DVT, and PVT. When a record enters Mass Production, its last hardware stage is retained.

| Design Status | Concept | EVT | DVT | PVT |
|---|---:|---:|---:|---:|
| Promotion | 0.10 | 0.15 | Invalid | Invalid |
| Sample | 0.20 | 0.30 | Invalid | Invalid |
| Evaluation | 0.20 | 0.35 | Invalid | Invalid |
| Design In | Invalid | Invalid | 0.65 | 0.80 |
| Design Win | Invalid | Invalid | Invalid | 0.90 |
| Mass Production | Invalid | Invalid | Invalid | 0.95 |
| Lost | 0.00 | 0.00 | 0.00 | 0.00 |

`Lost` is terminal, may be reached from any stage, and requires a loss reason. Unknown combinations are not automatically accepted.

## 3. Confidence Policy

- Minimum confidence: `0.05`.
- Maximum confidence: `0.95`.
- Maximum single-factor adjustment: `15 percentage points`.
- Maximum total movement in one run: `20 percentage points`.
- Positive and negative adjustments are allowed within the caps.
- A Matrix A band crossing always creates a human-review proposal.
- A value already at `0.95` cannot increase.
- Every factor must include a rule ID, rationale, and evidence quote.
- Missing or contradictory evidence produces `not_assessable`, not an invented adjustment.

## 4. Answers to the Questionnaire

### A. Scope and Ownership

**1.** Keep one agent covering funnel, pipeline, design wins, mass production, and losses.

**2.** Finance owns the official quarterly forecast. OT supplies the auditable pipeline feed.

**3.** ROI keeps an independent forecast and cross-checks OT adjusted revenue.

**4.** Finance owns the final forecast. Differences become review findings.

**5.** Every opportunity must have one accountable owner.

**6.** Ownership may change. Every change is recorded in append-only history.

**7.** Owner performance may become a calibration prior after sufficient historical outcomes exist. It must never directly overwrite current confidence.

### B. Matrix A and Confidence

**8.** Use the Matrix A table in Section 2 as the baseline source of truth.

**9.** Valid pairings are exactly the non-Invalid cells in Matrix A.

**10.** Invalid pairings block forecast inclusion and create a blocking finding.

**11.** Baselines are defined in Matrix A. The values are provisional until signed off.

**12.** Mass Production is a Design Status, not a Stage.

**13.** The maximum confidence is `0.95`, including Design Win.

**14.** Dual sourcing normally reduces confidence by 5-10 points, based on evidence.

**15.** Cancellation risk reduces confidence by 5-15 points, based on evidence severity.

**16.** The minimum confidence floor is `0.05`.

**17.** The agent may propose increases and decreases, but never directly apply them.

**18.** A single factor may move confidence by at most 15 points.

**19.** A complete run may move confidence by at most 20 points.

**20.** Yes. Matrix A band crossings require human approval.

**21.** Confidence is proposed by the agent and resolved by a human reviewer.

**22.** Positive adjustments are allowed at values below 0.95. Values at 0.95 remain capped.

### C. Judgment Service

**23.** `score_confidence` receives the opportunity, portfolio context, rubric version, and evidence bundle.

**24.** The active rubric version is an explicit input and is stored on every proposal and event.

**25.** The service returns a proposal and never mutates the opportunity.

**26.** Initial factors are status/stage consistency, competitor threat, data completeness, design-win support, early-stage optimism, and concentration.

**27.** A factor fires only when its required fields and supporting evidence exist.

**28.** Yes. Every factor requires a rule ID, rationale, and verbatim evidence quote.

**29.** Missing, contradictory, or stale evidence is reported as not assessable or a finding.

**30.** Competitor part is stored on the confidence-bearing opportunity record.

**31.** Stage order is Concept < EVT < DVT < PVT. Mass Production is a terminal status.

**32.** Concentration is calculated for the full portfolio, by region, and by product line where data exists.

**33.** The immutable owner identity is the submitter identity. Corrections also record `submitted_by`.

**34.** Identical snapshot, rubric, prompt, and model version should produce reproducible results. Use deterministic model settings where available.

**35.** Invalid JSON, refusal, timeout, or truncation fails loudly, records a failed run, and creates no proposal.

### D. Lifecycle and Review

**36.** The agent does not directly move records to Mass Production or Design Lost. It creates a transition proposal.

**37.** A human approves Mass Production, Design Lost, and any forecast-impacting transition.

**38.** Owners may request reviews.

**39.** Owners may not approve or override their own proposals.

**40.** Managers approve within region. Directors approve across regions. Owners provide evidence and request review. Admins publish configuration but do not approve proposals.

**41.** Override reasons are `rubric_missed_context`, `stale_precedent`, `submitter_correction`, `new_evidence_since_proposal`, and `other`.

**42.** Every Design Lost transition requires a loss reason.

**43.** Loss reasons are price, technical fit, competitor, relationship, timing, cancellation, and other.

**44.** The audit event is written transactionally before the successful response returns.

**45.** Approved confidence immediately triggers deterministic adjusted-revenue recalculation.

**46.** Stage/status changes trigger targeted re-scoring. Portfolio-wide re-scoring runs monthly.

### E. Data and Workbook

**47.** The latest business-approved TrackF workbook is canonical.

**48.** Yes. Store filename, version, source date, SHA-256 hash, and immutable snapshot ID.

**49.** Stretch means unweighted sales revenue. Projection means confidence-weighted revenue.

**50.** Existing #REF! forecast rows are treated as obsolete Finance-owned artifacts unless Finance supplies a corrected version.

**51.** Obtain and freeze a corrected workbook before final validation rules are approved.

**52.** EAU is annual chip usage. Unit/Set is used for set volume and attach rate, not as a revenue multiplier.

**53.** Preserve conflicting EAU values, create a finding, and apply documented source precedence rather than silently choosing one.

**54.** NRE and license revenue use separate record types from silicon-volume opportunities.

**55.** Every source row maps to one immutable Opportunity ID.

**56.** Use an internal UUID plus a human-readable ID such as `OPP-000001`. Preserve CRM/workbook IDs separately.

**57.** Backfill IDs using a reviewed crosswalk based on customer, project, part, region, and source row. Do not merge uncertain duplicates automatically.

**58.** Required intake fields are Opportunity ID or source ID, region, customer, end customer, project, application, product line, part number, design status, stage, EAU, distributor ASP, confidence, owner, and confidence rationale.

**59.** Optional fields are M/P date, Unit/Set, resale ASP, competitor part, evidence, revenue type, and loss reason when the record is not Lost.

**60.** Region, status, stage, product line, application, and loss reason use versioned reference tables.

**61.** `TBD` becomes null plus a finding. It is never converted to zero.

**62.** Missing required calculation fields block the row. Missing optional fields create advisory findings.

**63.** Source precedence is human edit > ERP > CRM > distributor POS/POR > workbook import > inferred value. Lower-trust conflicts remain visible.

**64.** Retain forecast vintages and audit events for seven years.

### F. Forecast and Analysis

**65.** Use a programme-specific profile when available; otherwise ramp from the M/P date; otherwise report the value as unphased.

**66.** Yes. Add yearly volume profiles for automotive opportunities when the source data supports them.

**67.** Finance provides targets by region and quarter/year.

**68.** Coverage is weighted pipeline divided by the applicable target.

**69.** ERP shipped revenue is the primary actual. Distributor POS is a cross-check.

**70.** Require at least two quarters of history before owner calibration is considered reliable.

**71.** Obtain at least 12-24 months of monthly TrackF files.

**72.** Extract PPAP, ES, Design Review, and SOP dates from Funnel text while retaining the original source text.

**73.** Overdue milestones become findings, with severity based on lateness and whether an action exists.

**74.** Initial analyses are stage mix, concentration, data quality, milestone/stall detection, competitive exposure, and channel margin.

**75.** A stall is time in stage greater than the historical median plus an agreed tolerance. Start with two median stage durations until better history exists.

### G. Security and Platform

**76.** Do not send NDA or customer-pricing data to a hosted LLM without Security approval.

**77.** Use local vLLM for sensitive data. Hosted use is allowed only for approved or redacted data.

**78.** Reuse the shared RTX PRO 6000 Blackwell deployment if capacity isolation is verified.

**79.** Approved local model families are Llama, Mistral, Gemma, and Command R+. Do not use Qwen or DeepSeek for this workload.

**80.** Production requires OIDC/SSO, MFA through the identity provider, and no shared logins.

**81.** Keep the six roles: owner, manager, director, finance, admin, and service.

**82.** Region scope is enforced in SQL and API authorization, not only by hiding UI controls.

**83.** Retain audit events for seven years.

**84.** Semantic precedent expires after eight quarters unless explicitly preserved.

**85.** Account deletion anonymizes display identity but retains immutable decisions and financial history.

**86.** Numeric values, pricing, and customer-sensitive financial data are not embedded in vector search.

**87.** Prioritize CRM, ERP, distributor POS/POR, and then broader market feeds.

### H. Internal Engineering Decisions

**88.** Use these service contracts:

```text
compute_project_financials(opportunity, confidence) -> Financials
score_confidence(opportunity, portfolio_context, rubric_version, evidence_bundle) -> ConfidenceProposal
```

**89.** Reviewer-facing rubric text contains the condition, evidence, adjustment, guard, and rationale. No unexplained model prose.

**90.** Direct entry, workbook import, CRM sync, and API writes use one canonical Opportunity schema.

**91.** The ROI payload includes snapshot ID, Opportunity ID, external ID, region, customer, product line, part number, period, sales revenue, adjusted revenue, confidence, status, stage, source, calculation version, and rubric version.

**92.** Run portfolio scoring monthly. Trigger targeted rescoring when stage, status, owner, competitor, evidence, or material commercial inputs change.

## 5. Claude API Key Purpose

The Claude API key is only for live language-model operations. It is not needed for deterministic calculations or ordinary application operation.

### Uses

1. **Live confidence judgment**
   - Reads the approved opportunity context and evidence.
   - Evaluates rubric factors.
   - Returns a structured confidence proposal with rationales and evidence citations.

2. **Assistant responses**
   - Answers questions about pipeline, risks, proposals, scenarios, and audit history.
   - Uses backend read-only tools.
   - Must not directly change opportunity or confidence data.

3. **Proof-of-concept live mode**
   - Replaces the rule-based mock judgment layer with real Claude reasoning.

### Does not use Claude

- Revenue calculations
- Confidence multiplication
- Roll-ups
- Intake validation
- Provenance
- Audit persistence
- Role enforcement
- Lifecycle writes
- Review approval
- Frontend rendering

### Runtime policy

The backend defaults to mock mode:

```env
JUDGMENT_MODE=mock
```

Live Claude mode requires backend-only configuration:

```env
JUDGMENT_MODE=live
ANTHROPIC_API_KEY=<stored outside source control>
```

The key must never be placed in frontend code, browser storage, or a public `.env` file.

### Security requirement

A real-looking Anthropic key was found in a POC environment file during repository review. It must be revoked and rotated immediately. The replacement must be stored in an untracked backend secret store or deployment secret manager.

## 6. Approval Checklist

Before production release, obtain written approval for:

- Matrix A values
- Confidence ceiling and caps
- Status/stage combinations
- Opportunity ID and owner rules
- Human lifecycle approval
- Canonical workbook and precedence
- Quarterly phasing
- Hosted/local model policy
- Intake schema
- ROI handoff contract
- Claude data-residency and security policy

## 7. Adoption (2026-09-15)

David Nam did not reply to the four questions sent 18 August (Matrix A baselines, the confidence ceiling, auto-move sign-off, the current workbook). On 2026-09-15 the answers above were adopted as the working policy for the build. Everything built against them is marked provisional in code and in `deliverables/WBS.md`, and is swappable by publishing a new rubric version — no code change is needed to change a baseline, a cap, a band or the review policy.

Four things the register did not cover, decided in the same pass:

**7.1 North America maps to US.** The file holds `North America` on ProjectTrack rows 14–15; David's region list has `US` and `Other`. Mapped to `US`: there are no Canadian or Mexican rows to argue otherwise, and `Other` would hide a real US opportunity under a catch-all. `app/registry/enums.py`.

**7.2 Review policy defaults to `gate_all`.** Decision #21 ("proposed by the agent and resolved by a human reviewer") and Plate 2's step 9 (auto-apply when no lifecycle band is crossed) do not say the same thing. The published rubric carries a `review_policy` setting: `gate_all` (v1 — every proposal reaches a person) or `gate_band_crossing` (step 9). A flagged proposal — run cap clipped, clamped to a bound, contract violation — always reaches a person under either policy.

**7.3 Lifecycle bands derived from Matrix A.** Half-open intervals on the baselines that separate one lifecycle position from the next: `early` below 0.65, `design_in` 0.65–0.90, `design_win` 0.90–0.95, `mass_production` from 0.95. A proposal that moves a row across one of those boundaries is a band crossing (#20). Apollo 0.50 → 0.66 crosses; Hermes 0.30 → 0.20 does not.

**7.4 Reason-code vocabularies.** Loss reasons per #43; override reasons per #41; a `rejection_reason` list added so a rejected proposal can say which rubric factor it disagrees with (`factor_misfired`, `evidence_stale`, `magnitude_too_large`, `magnitude_too_small`, `data_error_on_row`, `other`); the stage-exit list is ours. All enforced at the API, none ratified.

**7.5 Validation rules V-a to V-i.** The nine rules the architecture named but never listed: required field or TBD (V-a), forbidden pairing (V-b), confidence not a function of stage (V-c), EAU implausible against Unit/Set (V-d), same part with different EAU across tabs (V-e), roll-up does not compute (V-f), value on no canonical list (V-g), column reaching no formula (V-h), part number reused (V-i). Together they reproduce all twelve documented findings from `TrackF (1).xlsx` — `python -m scripts.findings_report` — and found two the specification missed (ID802 and ID803 imply 36.8M and 35.0M vehicle sets a year, the same defect as IP901).

What this does not settle: the security sign-off for sending pipeline data to a hosted model (#76). `JUDGMENT_MODE` stays `mock` until it exists.
