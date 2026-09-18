"""
Backup and restore drill (WBS 13.5).

    python -m scripts.backup                       # backup to settings.backup_dir
    python -m scripts.backup verify <dir>
    python -m scripts.backup restore <dir>         # refuses a backup whose hashes do not match
"""

import json
import sys

from app.core.config import settings
from app.services.backup import backup, restore, verify


def main(argv: list[str]) -> int:
    if not argv:
        print(json.dumps(backup(settings.backup_dir), indent=2))
        return 0
    if argv[0] == "verify":
        result = verify(argv[1])
        print(json.dumps(result, indent=2))
        return 0 if result["ok"] else 1
    if argv[0] == "restore":
        print(json.dumps(restore(argv[1]), indent=2))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
