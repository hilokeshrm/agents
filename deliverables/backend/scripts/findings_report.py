"""
Phase 0 in one command (WBS 4.5): read the real workbook, run rules V-a..V-i,
print the findings. No database, no auth, no model.

    python -m scripts.findings_report                 # data/TrackF (1).xlsx
    python -m scripts.findings_report path/to.xlsx    # any TrackF-shaped file
    python -m scripts.findings_report --json          # machine-readable
"""

import json
import sys
from pathlib import Path

from app.guards.report import render_text, workbook_report

DEFAULT = Path(__file__).resolve().parents[3] / "data" / "TrackF (1).xlsx"


def main(argv: list[str]) -> int:
    as_json = "--json" in argv
    paths = [a for a in argv if not a.startswith("--")]
    path = Path(paths[0]) if paths else DEFAULT
    if not path.exists():
        print(f"workbook not found: {path}", file=sys.stderr)
        return 1
    report = workbook_report(path)
    print(json.dumps(report.as_dict(), indent=2, default=str) if as_json else render_text(report))
    return 0 if not report.spec_missing else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
