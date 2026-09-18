# Parameter registry

Generated from `app/registry/parameters.py`. Every rule, analysis and rubric factor cites a parameter by id, never a spreadsheet column name.

| Id | Name | Type | Unit | Required | Tabs | Present | Note |
|---|---|---|---|---|---|---|---|
| V1 | Region | str |  | yes | ProjectTrack, Funnel, FCST_Revenue, MassProduction, DesignLost | yes | Raw values collide across tabs (KR vs Korea); canonicalize via app/registry/enums.py. |
| V2 | Customer | str |  | yes | ProjectTrack, Funnel, FCST_Revenue, MassProduction, DesignLost | yes | Open set, case-insensitive match (MOBIS vs Mobis), not a closed enum. |
| V3 | End Customer | str |  | yes | ProjectTrack, Funnel, FCST_Revenue, MassProduction, DesignLost | yes | OEM dimension; several direct customers can sit behind one OEM. |
| V4 | Project Name | str |  | yes | ProjectTrack, Funnel, FCST_Revenue, MassProduction, DesignLost | yes | The de facto identity today; unreliable to join on until V26-style IDs land (WBS 2.4). |
| V5 | Application | str |  |  | ProjectTrack, Funnel, FCST_Revenue, MassProduction, DesignLost | yes | Open set; only the values seen in the current file are pre-registered. |
| V6 | Product Line | str |  |  | ProjectTrack, Funnel, FCST_Revenue, MassProduction, DesignLost | yes | Open set; only the values seen in the current file are pre-registered. |
| V7 | Part Number | str |  | yes | ProjectTrack, Funnel, FCST_Revenue, MassProduction, DesignLost | yes | Supply key; aggregates unit demand across every socket using the same part. |
| V8 | Design Status | str |  | yes | ProjectTrack, Funnel, FCST_Revenue, MassProduction, DesignLost | yes | NRE and TBD are excluded on purpose -- they are not statuses (see V24, WBS 3.3/3.5). |
| V9 | Stage | str |  | yes | ProjectTrack | yes | Only ProjectTrack has this column -- Funnel, Mass Production and Design Lost do not. |
| V10 | M/P Date | date |  |  | ProjectTrack, Funnel, FCST_Revenue, MassProduction, DesignLost | yes | Coerced from strings like "Dec'24"; WBS 3.3 handles the coercion, not this registry. |
| V11 | EAU | float | Kpcs | yes | ProjectTrack, Funnel, FCST_Revenue, MassProduction, DesignLost | yes | Volume input to Sales Revenue (calc_engine.py). Cross-tab values for the same part disagree. |
| V12 | Unit/Set | float |  |  | ProjectTrack, Funnel, FCST_Revenue, MassProduction, DesignLost | yes | Attach rate; Set volume = EAU / Unit-Set. Dropped from the POC's sample data, needs restoring. |
| V13 | Disty ASP | float | USD | yes | ProjectTrack, Funnel, FCST_Revenue, MassProduction, DesignLost | yes | Price input to Sales Revenue; the authoritative price for all revenue figures. |
| V14 | Resale ASP | float | USD |  | ProjectTrack, Funnel, FCST_Revenue, MassProduction | yes | Reaches no formula today; Resale minus Disty is unbuilt channel-margin analysis (WBS 5.2, C3-C7). |
| V15 | Sales Revenue | float | USD thousands |  | ProjectTrack, MassProduction, DesignLost | yes | Computed: EAU * Disty ASP. Not on Funnel (no revenue formula there). |
| V16 | Competitor Part# | list |  |  | ProjectTrack, Funnel | yes | A list, not a string -- one cell holds two parts separated by a line break. |
| V17 | Confidence Level | float |  | yes | ProjectTrack, MassProduction, DesignLost | yes | The only field the agent may write. Fixed by state on the terminal tabs (1.0 or 0.0). |
| V18 | Adjusted Revenue | float | USD thousands |  | ProjectTrack, MassProduction, DesignLost | yes | Computed: Sales Revenue * Confidence Level. |
| V19 | Comments | str |  |  | ProjectTrack, MassProduction, DesignLost | yes | Free text; evidence for the judgment layer, quoted in a rationale, never parsed as a field. |
| V20 | FCST (Funnel) | str |  |  | Funnel | yes | Undocumented. Appears nowhere else and is referenced by no formula -- an open question, not a bug. |
| V21 | Pjt. Status/Note | str |  |  | Funnel | yes | Evidence text; can describe two different states for two different vehicle programmes in one cell. |
| V22 | Next Action To Do | str |  |  | Funnel | yes | The milestone source: PPAP, ES, SoP and design-review dates are extracted from here (WBS 6.3). |
| V23 | Quarterly Unit Forecast | list | Kpcs |  | FCST_Revenue | yes | The only phasing information in the file. Collapses 8 quarterly columns (CY25-26) into one field pending WBS 5.5 (the phasing rule) and 3.5 (splitting NRE rows out of it first). |
| V24 | FCST Remarks | str |  |  | FCST_Revenue | yes | Free text context. |
| V25 | Loss Reason Code | str |  | yes |  | proposed | Confirmed required by David; the vocabulary itself is WBS 2.6's job, not decided here. |
| V26 | Owner | str |  | yes |  | proposed | One of the five fields WBS 1.5 names as blocking a rubric factor or a join by its absence. Captured today via direct entry (app/schemas/opportunity.py), not via any workbook tab. |
| V27 | Confidence Rationale | str |  | yes |  | proposed | Structured rationale distinct from free-text Comments (V19); direct-entry-only (WBS 3.7). |
| V29 | NRE Charge | float | USD K |  |  | proposed | One-off engineering charge on an opportunity. The workbook carries NRE only as whole FCST_Revenue rows with Design Status NRE (see app/calc/nre.py), never as a per-row field, so this is proposed rather than present. |
| V28 | Opportunity ID | str |  |  |  | proposed | Stable human-facing identifier used for workbook and CRM crosswalks. |
| V30 | CY25 FCST Q1 | float | Kpcs |  | FCST_Revenue | yes | FCST_Revenue column N: CY25 Q1 units. |
| V31 | CY25 FCST Q2 | float | Kpcs |  | FCST_Revenue | yes | FCST_Revenue column O: CY25 Q2 units. |
| V32 | CY25 FCST Q3 | float | Kpcs |  | FCST_Revenue | yes | FCST_Revenue column P: CY25 Q3 units. |
| V33 | CY25 FCST Q4 | float | Kpcs |  | FCST_Revenue | yes | FCST_Revenue column Q: CY25 Q4 units. |
| V34 | CY25 Revenue Q1 | float | USD thousands |  | FCST_Revenue | yes | FCST_Revenue column S: CY25 Q1 revenue. |
| V35 | CY25 Revenue Q2 | float | USD thousands |  | FCST_Revenue | yes | FCST_Revenue column T: CY25 Q2 revenue. |
| V36 | CY25 Revenue Q3 | float | USD thousands |  | FCST_Revenue | yes | FCST_Revenue column U: CY25 Q3 revenue. |
| V37 | CY25 Revenue Q4 | float | USD thousands |  | FCST_Revenue | yes | FCST_Revenue column V: CY25 Q4 revenue. |
| V38 | CY26 FCST Q1 | float | Kpcs |  | FCST_Revenue | yes | FCST_Revenue column X: CY26 Q1 units. |
| V39 | CY26 FCST Q2 | float | Kpcs |  | FCST_Revenue | yes | FCST_Revenue column Y: CY26 Q2 units. |
| V40 | CY26 FCST Q3 | float | Kpcs |  | FCST_Revenue | yes | FCST_Revenue column Z: CY26 Q3 units. |
| V41 | CY26 FCST Q4 | float | Kpcs |  | FCST_Revenue | yes | FCST_Revenue column AA: CY26 Q4 units. |
| V42 | CY26 Revenue Q1 | float | USD thousands |  | FCST_Revenue | yes | FCST_Revenue column AC: CY26 Q1 revenue. |
| V43 | CY26 Revenue Q2 | float | USD thousands |  | FCST_Revenue | yes | FCST_Revenue column AD: CY26 Q2 revenue. |
| V44 | CY26 Revenue Q3 | float | USD thousands |  | FCST_Revenue | yes | FCST_Revenue column AE: CY26 Q3 revenue. |
| V45 | CY26 Revenue Q4 | float | USD thousands |  | FCST_Revenue | yes | FCST_Revenue column AF: CY26 Q4 revenue. |
| G1 | Regional Target | float | USD thousands |  |  | proposed | Finance's top-down commitment by region and quarter (decision #67). Sheet1's Projection/Stretch was a template leftover, not a target. C13 coverage is dark until Finance enters these. |
| G2 | Target Period | str |  |  |  | proposed | The quarter or year a G1 target applies to. |
| A1 | Shipped Revenue | float | USD thousands |  |  | proposed | Actuals from the ERP extract (primary, decision #69) -- what was invoiced. |
| A2 | POS Units | float | Kpcs |  |  | proposed | Distributor point-of-sale units (cross-check, decision #69). |
| A3 | Forecast Vintage | str |  |  |  | proposed | The snapshot a forecast figure came from; C15 forecast error compares vintages against actuals. |
| M1 | ES Date | date |  |  | Funnel | yes | Engineering sample date parsed from Next Action To Do (WBS 6.3); the source substring is kept. |
| M2 | PPAP Date | date |  |  | Funnel | yes | Parsed from Next Action To Do; overdue PPAP is a milestone finding (J-10). |
| M3 | SoP Date | date |  |  | Funnel, FCST_Revenue | yes | Start of production; disagreements between tabs are a V-e finding. |
| H1 | State History | list |  |  |  | proposed | Append-only design status and stage events (WBS 9.2). Present from Phase 2; drives C14, J-09. |
| H2 | Days In Stage | float | days |  |  | proposed | Computed from H1; compared against the stage median for stall detection. |
| H3 | Resolved Outcome | str |  |  |  | proposed | won / lost label from the latest terminal state, the calibration table's training signal. |
| R1 | Competitor Detail | str |  |  |  | proposed | Competitor part attributes from vendor catalogues (connector 11.6-class); enriches J-02. |
| P1 | Programme Build Volume | float | Ksets |  |  | proposed | Licensed vehicle-programme build forecast; the real check behind J-11 (licence required). |
| P2 | Programme SoP | date |  |  |  | proposed | Licensed programme start of production; feeds white-space detection. |
| C1 | Standard Cost | float | USD |  |  | proposed | Per-unit cost; turns channel margin into gross margin for the margin analysis. |
| O1 | Owner Bias | float | pp |  |  | proposed | L5 calibration: the owner's historic forecast bias, rebuilt quarterly (J-06). |
