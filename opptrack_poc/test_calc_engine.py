"""
Regression test: the deterministic calc engine must reproduce the exact
numbers already in TrackF_1.xlsx's ProjectTrack tab. If this test fails,
the financial math itself has changed, which should never happen silently.

Run: python3 test_calc_engine.py
"""

import json
from calc_engine import compute_project_financials

# (project name, expected Sales Revenue $K, expected Adjusted Revenue $K), lifted directly
# from ProjectTrack columns O and R in TrackF_1.xlsx.
EXPECTED = {
    "Hercules": (3300.0, 3300.0),
    "Aphrodite": (4050.0, 3240.0),
    "Hermes": (40000.0, 12000.0),
    "Poseidon": (16000.0, 1600.0),
    "Apollo": (10000.0, 5000.0),
    "Hugo": (2250.0, 675.0),
    "Dresden": (3000.0, 1500.0),
    "Yellowstone": (3000.0, 3000.0),
    "Montana": (750.0, 600.0),
}


def approx(a, b, tol=0.01):
    return abs(a - b) <= tol


def test_matches_spreadsheet():
    with open("data/sample_pipeline.json") as f:
        data = json.load(f)

    for row in data["project_track"]:
        f = compute_project_financials(row)
        want_sales, want_adjusted = EXPECTED[f.project]
        assert approx(f.sales_revenue_k, want_sales), f"{f.project} sales revenue: got {f.sales_revenue_k}, want {want_sales}"
        assert approx(f.adjusted_revenue_k, want_adjusted), f"{f.project} adjusted revenue: got {f.adjusted_revenue_k}, want {want_adjusted}"

    print(f"PASS -- calc_engine.py reproduces TrackF_1.xlsx exactly for all {len(EXPECTED)} sample projects.")


if __name__ == "__main__":
    test_matches_spreadsheet()
