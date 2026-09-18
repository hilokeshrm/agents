"""
The populated parameter registry (WBS 2.1). Sourced directly from
docs/03-reference/Opportunity_Tracking_Agent_Tab_and_Field_Map.docx -- the tab-by-
tab column dictionary for TrackF (1).xlsx -- not invented to hit a round count.

Entries: the 19 lettered ProjectTrack columns (A-S, the primary tab -- "the
only one carrying both Stage and Confidence"), the fields unique to Funnel,
FCST_Revenue and Mass Production/Design Lost, plus three proposed parameters the
platform needs that no tab carries today (V25-V27).

The sixteen FCST_Revenue quarterly columns are registered individually (V30-V45)
as the WBS counted them, alongside the collapsed V23 that older code cites.
Proposed platform parameters (targets G1/G2, actuals A1-A3, parsed milestones
M1-M3, state history H1-H3, competitor and programme data R1/P1/P2, cost C1,
owner bias O1) are registered absent, which is what lets an analysis or rubric
rule say exactly which input it is waiting on.

id convention: V-prefixed, in tab reading order. Never cite a column letter or a
tab name outside this file; downstream code cites the id.
"""

from datetime import date

from app.registry.param_spec import ParamRegistry, ParamSpec

PARAMS = ParamRegistry()

_ALL_TABS = ("ProjectTrack", "Funnel", "FCST_Revenue", "MassProduction", "DesignLost")

_ENTRIES = [
    # -- ProjectTrack A-S: the primary tab, the only one with both Stage and Confidence.
    ParamSpec("V1", "Region", str, None, ("Korea", "Europe", "Taiwan", "Japan", "India", "US", "Other"),
              True, _ALL_TABS, True,
              "Raw values collide across tabs (KR vs Korea); canonicalize via app/registry/enums.py."),
    ParamSpec("V2", "Customer", str, None, None, True, _ALL_TABS, True,
              "Open set, case-insensitive match (MOBIS vs Mobis), not a closed enum."),
    ParamSpec("V3", "End Customer", str, None, None, True, _ALL_TABS, True,
              "OEM dimension; several direct customers can sit behind one OEM."),
    ParamSpec("V4", "Project Name", str, None, None, True, _ALL_TABS, True,
              "The de facto identity today; unreliable to join on until V26-style IDs land (WBS 2.4)."),
    ParamSpec("V5", "Application", str, None, ("ADAS", "Powertrain", "Lamp"), False, _ALL_TABS, True,
              "Open set; only the values seen in the current file are pre-registered."),
    ParamSpec("V6", "Product Line", str, None, ("SerDes", "IGD", "LED Lighting"), False, _ALL_TABS, True,
              "Open set; only the values seen in the current file are pre-registered."),
    ParamSpec("V7", "Part Number", str, None, None, True, _ALL_TABS, True,
              "Supply key; aggregates unit demand across every socket using the same part."),
    ParamSpec("V8", "Design Status", str, None,
              ("Design Win", "Design In", "Sample", "Promotion", "Evaluation", "Lost", "Mass Production"),
              True, _ALL_TABS, True,
              "NRE and TBD are excluded on purpose -- they are not statuses (see V24, WBS 3.3/3.5)."),
    ParamSpec("V9", "Stage", str, None, ("Concept", "EVT", "DVT", "PVT"), True, ("ProjectTrack",), True,
              "Only ProjectTrack has this column -- Funnel, Mass Production and Design Lost do not."),
    ParamSpec("V10", "M/P Date", date, None, None, False, _ALL_TABS, True,
              "Coerced from strings like \"Dec'24\"; WBS 3.3 handles the coercion, not this registry."),
    ParamSpec("V11", "EAU", float, "Kpcs", None, True, _ALL_TABS, True,
              "Volume input to Sales Revenue (calc_engine.py). Cross-tab values for the same part disagree."),
    ParamSpec("V12", "Unit/Set", float, None, None, False, _ALL_TABS, True,
              "Attach rate; Set volume = EAU / Unit-Set. Dropped from the POC's sample data, needs restoring."),
    ParamSpec("V13", "Disty ASP", float, "USD", None, True, _ALL_TABS, True,
              "Price input to Sales Revenue; the authoritative price for all revenue figures."),
    ParamSpec("V14", "Resale ASP", float, "USD", None, False, ("ProjectTrack", "Funnel", "FCST_Revenue", "MassProduction"), True,
              "Reaches no formula today; Resale minus Disty is unbuilt channel-margin analysis (WBS 5.2, C3-C7)."),
    ParamSpec("V15", "Sales Revenue", float, "USD thousands", None, False,
              ("ProjectTrack", "MassProduction", "DesignLost"), True,
              "Computed: EAU * Disty ASP. Not on Funnel (no revenue formula there)."),
    ParamSpec("V16", "Competitor Part#", list, None, None, False, ("ProjectTrack", "Funnel"), True,
              "A list, not a string -- one cell holds two parts separated by a line break."),
    ParamSpec("V17", "Confidence Level", float, None, None, True,
              ("ProjectTrack", "MassProduction", "DesignLost"), True,
              "The only field the agent may write. Fixed by state on the terminal tabs (1.0 or 0.0)."),
    ParamSpec("V18", "Adjusted Revenue", float, "USD thousands", None, False,
              ("ProjectTrack", "MassProduction", "DesignLost"), True,
              "Computed: Sales Revenue * Confidence Level."),
    ParamSpec("V19", "Comments", str, None, None, False, ("ProjectTrack", "MassProduction", "DesignLost"), True,
              "Free text; evidence for the judgment layer, quoted in a rationale, never parsed as a field."),

    # -- Fields unique to Funnel (no Stage, no Confidence, no revenue formula there).
    ParamSpec("V20", "FCST (Funnel)", str, None, None, False, ("Funnel",), True,
              "Undocumented. Appears nowhere else and is referenced by no formula -- an open question, not a bug."),
    ParamSpec("V21", "Pjt. Status/Note", str, None, None, False, ("Funnel",), True,
              "Evidence text; can describe two different states for two different vehicle programmes in one cell."),
    ParamSpec("V22", "Next Action To Do", str, None, None, False, ("Funnel",), True,
              "The milestone source: PPAP, ES, SoP and design-review dates are extracted from here (WBS 6.3)."),

    # -- Fields unique to FCST_Revenue (out of scope as an input; matters for phasing shape only).
    ParamSpec("V23", "Quarterly Unit Forecast", list, "Kpcs", None, False, ("FCST_Revenue",), True,
              "The only phasing information in the file. Collapses 8 quarterly columns (CY25-26) into one field "
              "pending WBS 5.5 (the phasing rule) and 3.5 (splitting NRE rows out of it first)."),
    ParamSpec("V24", "FCST Remarks", str, None, None, False, ("FCST_Revenue",), True, "Free text context."),

    # -- Proposed: needed by the platform, not carried by any tab today (registered absent, not missing).
    ParamSpec("V25", "Loss Reason Code", str, None, None, True, (), False,
              "Confirmed required by David; the vocabulary itself is WBS 2.6's job, not decided here."),
    ParamSpec("V26", "Owner", str, None, None, True, (), False,
              "One of the five fields WBS 1.5 names as blocking a rubric factor or a join by its absence. "
              "Captured today via direct entry (app/schemas/opportunity.py), not via any workbook tab."),
    ParamSpec("V27", "Confidence Rationale", str, None, None, True, (), False,
              "Structured rationale distinct from free-text Comments (V19); direct-entry-only (WBS 3.7)."),
    ParamSpec("V29", "NRE Charge", float, "USD K", None, False, (), False,
              "One-off engineering charge on an opportunity. The workbook carries NRE only as whole "
              "FCST_Revenue rows with Design Status NRE (see app/calc/nre.py), never as a per-row "
              "field, so this is proposed rather than present."),
    ParamSpec("V28", "Opportunity ID", str, None, None, False, (), False,
              "Stable human-facing identifier used for workbook and CRM crosswalks."),

    # -- FCST_Revenue quarterly columns, one ParamSpec each (the finer grain the
    #    WBS counted). Present in the file; consumed by T2 and C10.
    *[
        ParamSpec(f"V{30 + i}", f"{cy} {kind} {q}", float, unit, None, False, ("FCST_Revenue",), True,
                  f"FCST_Revenue column {col}: {cy} {q} {'units' if kind == 'FCST' else 'revenue'}.")
        for i, (cy, kind, q, unit, col) in enumerate([
            ("CY25", "FCST", "Q1", "Kpcs", "N"), ("CY25", "FCST", "Q2", "Kpcs", "O"),
            ("CY25", "FCST", "Q3", "Kpcs", "P"), ("CY25", "FCST", "Q4", "Kpcs", "Q"),
            ("CY25", "Revenue", "Q1", "USD thousands", "S"), ("CY25", "Revenue", "Q2", "USD thousands", "T"),
            ("CY25", "Revenue", "Q3", "USD thousands", "U"), ("CY25", "Revenue", "Q4", "USD thousands", "V"),
            ("CY26", "FCST", "Q1", "Kpcs", "X"), ("CY26", "FCST", "Q2", "Kpcs", "Y"),
            ("CY26", "FCST", "Q3", "Kpcs", "Z"), ("CY26", "FCST", "Q4", "Kpcs", "AA"),
            ("CY26", "Revenue", "Q1", "USD thousands", "AC"), ("CY26", "Revenue", "Q2", "USD thousands", "AD"),
            ("CY26", "Revenue", "Q3", "USD thousands", "AE"), ("CY26", "Revenue", "Q4", "USD thousands", "AF"),
        ])
    ],

    # -- Proposed platform parameters (registered absent so runnable() can name
    #    what is missing rather than a module raising on a null).
    ParamSpec("G1", "Regional Target", float, "USD thousands", None, False, (), False,
              "Finance's top-down commitment by region and quarter (decision #67). Sheet1's Projection/Stretch "
              "was a template leftover, not a target. C13 coverage is dark until Finance enters these."),
    ParamSpec("G2", "Target Period", str, None, None, False, (), False,
              "The quarter or year a G1 target applies to."),
    ParamSpec("A1", "Shipped Revenue", float, "USD thousands", None, False, (), False,
              "Actuals from the ERP extract (primary, decision #69) -- what was invoiced."),
    ParamSpec("A2", "POS Units", float, "Kpcs", None, False, (), False,
              "Distributor point-of-sale units (cross-check, decision #69)."),
    ParamSpec("A3", "Forecast Vintage", str, None, None, False, (), False,
              "The snapshot a forecast figure came from; C15 forecast error compares vintages against actuals."),
    ParamSpec("M1", "ES Date", date, None, None, False, ("Funnel",), True,
              "Engineering sample date parsed from Next Action To Do (WBS 6.3); the source substring is kept."),
    ParamSpec("M2", "PPAP Date", date, None, None, False, ("Funnel",), True,
              "Parsed from Next Action To Do; overdue PPAP is a milestone finding (J-10)."),
    ParamSpec("M3", "SoP Date", date, None, None, False, ("Funnel", "FCST_Revenue"), True,
              "Start of production; disagreements between tabs are a V-e finding."),
    ParamSpec("H1", "State History", list, None, None, False, (), False,
              "Append-only design status and stage events (WBS 9.2). Present from Phase 2; drives C14, J-09."),
    ParamSpec("H2", "Days In Stage", float, "days", None, False, (), False,
              "Computed from H1; compared against the stage median for stall detection."),
    ParamSpec("H3", "Resolved Outcome", str, None, ("won", "lost"), False, (), False,
              "won / lost label from the latest terminal state, the calibration table's training signal."),
    ParamSpec("R1", "Competitor Detail", str, None, None, False, (), False,
              "Competitor part attributes from vendor catalogues (connector 11.6-class); enriches J-02."),
    ParamSpec("P1", "Programme Build Volume", float, "Ksets", None, False, (), False,
              "Licensed vehicle-programme build forecast; the real check behind J-11 (licence required)."),
    ParamSpec("P2", "Programme SoP", date, None, None, False, (), False,
              "Licensed programme start of production; feeds white-space detection."),
    ParamSpec("C1", "Standard Cost", float, "USD", None, False, (), False,
              "Per-unit cost; turns channel margin into gross margin for the margin analysis."),
    ParamSpec("O1", "Owner Bias", float, "pp", None, False, (), False,
              "L5 calibration: the owner's historic forecast bias, rebuilt quarterly (J-06)."),
]

for _entry in _ENTRIES:
    PARAMS.register(_entry)
