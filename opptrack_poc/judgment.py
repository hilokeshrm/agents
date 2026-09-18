"""
Judgment layer: calibrates the human-entered Confidence Level against
project context, the same design pattern used in the ROI Agent's judgment
layer (judgment.py there).

The LLM never touches Sales Revenue or Adjusted Revenue math. It only ever
returns a structured, cited confidence adjustment, which calc_engine.py's
Adjusted Revenue formula then applies. Two modes: LIVE (calls Claude via the
anthropic package if ANTHROPIC_API_KEY is set) and MOCK (a rule-based
stand-in so this POC runs end to end with zero setup).

To go live: pip install anthropic, set ANTHROPIC_API_KEY, and re-run.
"""

import json
import os

RUBRIC = [
    {
        "key": "stage_status_mismatch",
        "label": "Design status / stage mismatch",
        "guidance": "Design Status (e.g. Design Win, Sample, Evaluation, Promotion) should be consistent with "
                    "the hardware validation Stage (Concept, EVT, DVT, PVT). A 'Design Win' still sitting at "
                    "Concept stage, or a 'Promotion' entry claiming PVT, is an internal inconsistency worth a "
                    "confidence haircut until reconciled.",
    },
    {
        "key": "named_competitor_threat",
        "label": "Named competitor part",
        "guidance": "A populated Competitor Part# means a rival is actively being evaluated for the same socket. "
                    "This should reduce confidence versus an otherwise identical opportunity with no named competitor.",
    },
    {
        "key": "design_win_lock_in",
        "label": "Design win lock-in",
        "guidance": "Design Status = Design Win at DVT or PVT stage represents a genuinely locked-in outcome and "
                    "should generally support, not reduce, the reported confidence.",
    },
    {
        "key": "early_stage_optimism",
        "label": "Early-stage optimism",
        "guidance": "Concept or early Evaluation stage opportunities are inherently uncertain (design wins are not "
                    "guaranteed, EAU is a forecast, and the customer may not proceed at all). A high confidence "
                    "figure this early in the funnel deserves scrutiny.",
    },
    {
        "key": "customer_concentration",
        "label": "Customer / region concentration",
        "guidance": "A pipeline heavily concentrated in one customer or region is riskier than the same total "
                    "adjusted revenue spread across several, even if each individual project's confidence looks fine.",
    },
    {
        "key": "submitter_calibration",
        "label": "Submitter calibration",
        "guidance": "Whether the salesperson or region owner who entered this confidence number has a history of "
                    "being optimistic or conservative versus how the opportunity actually resolved (won, lost, or "
                    "converted to Mass Production).",
    },
]

SYSTEM_PROMPT = """You are the judgment layer of a semiconductor company's Opportunity Tracking agent. \
You are given a pipeline opportunity's context (not the Sales Revenue or Adjusted Revenue math itself, which is \
computed separately in code) and a rubric of confidence-calibration factors. For each factor that plausibly \
applies, decide:
- whether it applies (true/false)
- a confidence_adjustment_pct: a percentage-point adjustment to apply to the human-entered Confidence Level \
  (negative = haircut, positive = support), typically in the range -50 to +20
- a one-sentence rationale citing what in the context supports this
- a confidence (0-1) in your own assessment

Only mark a factor as applying if the context actually supports it, do not invent risk. \
Return ONLY valid JSON: a list of objects with keys: key, applies, confidence_adjustment_pct, rationale, confidence."""


def _build_user_prompt(project_context: dict) -> str:
    return json.dumps({"rubric": RUBRIC, "opportunity": project_context}, indent=2)


def _mock_score(project_context: dict) -> list:
    """Deterministic, rule-based stand-in for an LLM call. Only used when no
    API key is configured. Clearly labeled MOCK; not a substitute for the
    real judgment layer."""
    design_status = (project_context.get("design_status") or "").lower()
    stage = (project_context.get("stage") or "").lower()
    has_competitor = bool(project_context.get("competitor_part"))
    results = []

    for factor in RUBRIC:
        applies, adj, rationale, conf = False, 0.0, "No supporting evidence found in context (MOCK scorer).", 0.3

        if factor["key"] == "stage_status_mismatch":
            mismatch = ("win" in design_status and stage in ("concept", "evt")) or \
                       ("promotion" in design_status and stage in ("pvt", "dvt"))
            if mismatch:
                applies, adj, conf = True, -20.0, 0.5
                rationale = f"Design status '{project_context.get('design_status')}' looks inconsistent with stage '{project_context.get('stage')}' (MOCK scorer)."
        elif factor["key"] == "named_competitor_threat" and has_competitor:
            applies, adj, conf = True, -10.0, 0.5
            rationale = f"Competitor part {project_context.get('competitor_part')} is named against this socket (MOCK scorer)."
        elif factor["key"] == "design_win_lock_in" and "win" in design_status and stage in ("dvt", "pvt"):
            applies, adj, conf = True, 8.0, 0.5
            rationale = "Design Win at DVT/PVT stage supports the reported confidence (MOCK scorer)."
        elif factor["key"] == "early_stage_optimism" and stage in ("concept", "evt") and float(project_context.get("confidence", 0)) >= 0.5:
            applies, adj, conf = True, -15.0, 0.45
            rationale = f"Confidence of {project_context.get('confidence')} looks high for a {project_context.get('stage')}-stage opportunity (MOCK scorer)."

        results.append({"key": factor["key"], "applies": applies, "confidence_adjustment_pct": adj, "rationale": rationale, "confidence": conf})

    return results


def _live_score(project_context: dict) -> list:
    import anthropic  # imported lazily so the module loads fine without it installed

    client = anthropic.Anthropic()
    message = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": _build_user_prompt(project_context)}],
    )
    return json.loads(message.content[0].text)


def score_confidence_factors(project_context: dict) -> dict:
    """Returns {"mode": "live"|"mock", "factors": [...]}"""
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            return {"mode": "live", "factors": _live_score(project_context)}
        except Exception as e:
            print(f"[judgment.py] Live LLM call failed ({e}); falling back to MOCK scorer.")
    return {"mode": "mock", "factors": _mock_score(project_context)}


def apply_confidence_adjustment(base_confidence: float, factors: list) -> float:
    """Collapse applicable factors into a single adjusted confidence, clamped to [0, 1]."""
    total_pct = sum(f["confidence_adjustment_pct"] for f in factors if f.get("applies"))
    adjusted = base_confidence + total_pct / 100.0
    return max(0.0, min(1.0, adjusted))


if __name__ == "__main__":
    import json as _json

    with open("data/sample_pipeline.json") as f:
        data = _json.load(f)

    # Demonstrate on one representative row: an early-stage opportunity with a named competitor.
    row = data["project_track"][2]  # Hermes: Sample/EVT, confidence 0.3, large volume
    result = score_confidence_factors(row)
    print(f"--- Judgment layer output for '{row['project']}' (mode={result['mode']}) ---")
    for f in result["factors"]:
        flag = "APPLIES" if f["applies"] else "n/a"
        print(f"  [{flag:7}] {f['key']:24} adj={f['confidence_adjustment_pct']:+.1f}pp  conf={f['confidence']:.2f}  -- {f['rationale']}")

    adjusted = apply_confidence_adjustment(row["confidence"], result["factors"])
    print(f"\nBase confidence: {row['confidence']:.2f}  ->  Adjusted confidence: {adjusted:.2f}")
