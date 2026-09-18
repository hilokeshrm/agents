"""
Run one scheduled job once (WBS 13.2): `python -m scripts.run_job stall_sweep`.
The crontab that calls these is printed by `python -m scripts.run_job --crontab`.
"""

import json
import sys

from app.services.scheduler import JOBS, crontab, run_job


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print("jobs: " + ", ".join(JOBS))
        return 0
    if argv[0] == "--crontab":
        print(crontab(), end="")
        return 0
    if argv[0] not in JOBS:
        print(f"unknown job {argv[0]!r}; jobs: {', '.join(JOBS)}", file=sys.stderr)
        return 2
    print(json.dumps(run_job(argv[0]), indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
