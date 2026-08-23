"""Safe-ingest dry run for Guild RPG organization sheets.

Previews what ``engine/guild_org_ingest.py`` would write without mutating the
live roster DB. Mirrors the region dry-run review flow.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from engine.guild_org_ingest import ingest, DEFAULT_BASE


def main() -> int:
    base = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_BASE
    summary = ingest(base=base, dry_run=True)
    print(f"[DRY RUN] Guild RPG organizations -> preview from '{base}'")
    print(f"  would insert : {summary['inserted']}")
    print(f"  would update : {summary['updated']}")
    print(f"  existing     : {summary['existing']} (untouched, add-only)")
    print(f"  skipped      : {summary['skipped']} (unresolved / dup)")
    print(f"  errors       : {summary['errors']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
