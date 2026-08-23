"""Ingest Guild RPG organization sheets into the roster ``organizations`` table.

Mirrors ``engine/guild_region_ingest.py`` but targets org sheets via
``guild_org_pullover``. Orgs whose names already exist as seeded rows (none yet
by default) are enriched in place only under ``--update-existing`` (Canon
Upsert). ``--dry-run`` previews. The live DB is checkpointed before any write.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))               # chronos-core/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))  # dev/

from engine import guild_roster
from engine.guild_ingest import (
    SETTING_ID, normalize_name, discover_markdowns, _checkpoint_db,
)
from engine.guild_org_pullover import ORG_FILES, SKIP_FILES, extract_file

DEFAULT_BASE = "../guild-rpg-digital-dm/Characters/Official AK Characters/BESM Sheets/organizations"


def ingest(base: str = DEFAULT_BASE, update_existing: bool = False,
           dry_run: bool = False) -> dict:
    """Run the Guild RPG org ingest against the live roster DB.

    Returns a summary dict: inserted / updated / skipped / existing / errors.
    """
    # Ensure the table exists even on a dry run (regions pre-existed, orgs may not).
    guild_roster.init_organizations_table()
    if not dry_run:
        guild_roster.init_roster_db()
        _checkpoint_db()

    with guild_roster.get_roster_connection() as conn:
        existing = {
            normalize_name(r[0])
            for r in conn.execute(
                "SELECT name FROM organizations WHERE setting_id = ?", (SETTING_ID,)
            ).fetchall()
        }

    summary = {"inserted": 0, "updated": 0, "skipped": 0, "existing": 0, "errors": 0}
    seen_norms: set[str] = set()

    for path in discover_markdowns(base):
        fn = Path(path).name
        if fn in SKIP_FILES or fn not in ORG_FILES:
            continue
        for payload in extract_file(str(path)):
            if "error" in payload:
                summary["errors"] += 1
                continue
            norm = normalize_name(payload["name"])
            if norm in seen_norms:
                summary["skipped"] += 1
                continue
            if norm in existing and not update_existing:
                summary["existing"] += 1
                continue
            if not dry_run:
                guild_roster.upsert_organization(SETTING_ID, payload, "{}", str(path))
            if norm in existing:
                summary["updated"] += 1
            else:
                summary["inserted"] += 1
            seen_norms.add(norm)

    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default=DEFAULT_BASE, help="Org sheets markdown root.")
    parser.add_argument(
        "--update-existing", action="store_true",
        help="Option A: also upsert entries that already exist (Canon Upsert).")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview without writing to the roster DB.")
    parser.add_argument("--json", action="store_true", help="Emit JSON summary.")
    args = parser.parse_args()

    summary = ingest(
        base=args.base, update_existing=args.update_existing, dry_run=args.dry_run)

    if args.json:
        import json as _json
        print(_json.dumps({"dry_run": args.dry_run, **summary}, indent=2))
    else:
        verb = "DRY RUN (no writes)" if args.dry_run else "INGEST"
        print(f"[{verb}] Guild RPG organizations -> setting '{SETTING_ID}'")
        print(f"  inserted : {summary['inserted']}")
        print(f"  updated  : {summary['updated']}")
        print(f"  existing : {summary['existing']} (untouched, add-only)")
        print(f"  skipped  : {summary['skipped']} (unresolved / dup)")
        print(f"  errors   : {summary['errors']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
