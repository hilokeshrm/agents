"""
End-to-end POC: loads the sample pipeline (from TrackF_1.xlsx's ProjectTrack
tab), computes deterministic Sales Revenue and Adjusted Revenue per project,
runs the judgment layer to calibrate each project's confidence level, and
prints a before/after portfolio roll-up so you can see exactly how much the
judgment layer moved the weighted pipeline number, and why.

Run: python3 run_poc.py
"""

import json

from calc_engine import compute_project_financials, portfolio_rollup
from judgment import score_confidence_factors, apply_confidence_adjustment


def main():
    with open("data/sample_pipeline.json") as f:
        data = json.load(f)

    print("=" * 88)
    print("OPPORTUNITY TRACKING AGENT POC")
    print("=" * 88)

    rows = data["project_track"]

    print("\n[1] BASE CASE (confidence as submitted, no AI adjustment)")
    base_financials = [compute_project_financials(r) for r in rows]
    base_rollup = portfolio_rollup(base_financials)
    for f in base_financials:
        print(f"    {f.project:12} {f.region:8} {f.stage:8} sales=${f.sales_revenue_k:>9,.1f}K  "
              f"conf={f.confidence:.2f}  adjusted=${f.adjusted_revenue_k:>9,.1f}K")
    print(f"    TOTAL: sales=${base_rollup['total_sales_revenue_k']:,.1f}K   "
          f"adjusted (weighted)=${base_rollup['total_adjusted_revenue_k']:,.1f}K")

    print("\n[2] JUDGMENT LAYER (per-project confidence calibration)")
    mode_seen = None
    calibrated_rows = []
    for row in rows:
        result = score_confidence_factors(row)
        mode_seen = result["mode"]
        new_confidence = apply_confidence_adjustment(row["confidence"], result["factors"])
        applied = [f for f in result["factors"] if f["applies"]]
        if applied:
            reasons = "; ".join(f"{f['key']}({f['confidence_adjustment_pct']:+.0f}pp)" for f in applied)
            print(f"    {row['project']:12} confidence {row['confidence']:.2f} -> {new_confidence:.2f}   [{reasons}]")
        else:
            print(f"    {row['project']:12} confidence {row['confidence']:.2f} -> {new_confidence:.2f}   [no factors applied]")
        calibrated_row = dict(row)
        calibrated_row["confidence"] = new_confidence
        calibrated_rows.append(calibrated_row)

    print("\n[3] CALIBRATED PORTFOLIO ROLL-UP")
    calibrated_financials = [compute_project_financials(r) for r in calibrated_rows]
    calibrated_rollup = portfolio_rollup(calibrated_financials)
    print(f"    Before calibration: adjusted (weighted) pipeline = ${base_rollup['total_adjusted_revenue_k']:,.1f}K")
    print(f"    After calibration:  adjusted (weighted) pipeline = ${calibrated_rollup['total_adjusted_revenue_k']:,.1f}K")
    delta = calibrated_rollup['total_adjusted_revenue_k'] - base_rollup['total_adjusted_revenue_k']
    print(f"    Net change from judgment layer: {delta:+,.1f}K")

    print("\nNote: Sales Revenue and Adjusted Revenue math above is 100% deterministic")
    print("code (calc_engine.py), unit-tested against the original TrackF_1.xlsx.")
    print("Only the *confidence input* to that math was touched by the judgment layer.")
    if mode_seen == "mock":
        print("\n*** Judgment layer ran in MOCK mode (no ANTHROPIC_API_KEY set). ***")
        print("*** Install `anthropic` and set the key to see live LLM judgment. ***")


if __name__ == "__main__":
    main()
