"""BESM Disc Bestiary live ingest — Phase 2 of the true-disc roadmap.

Wires the deterministic dry-run parser (engine/disc_pullover.py) into the live
roster DB via guild_roster.upsert_character, behind a SAFE-INGEST guard:

- **Default (Option B — Safe Add-Only):** only Bestiary entries whose normalized
  name is ABSENT from the setting are inserted. The 76-77 existing card-derived
  rows are left strictly untouched (net +8 rows: 97 -> 105).
- **--update-existing (Option A — Canon Upsert):** overlapping entries are also
  upserted, upgrading them with the curated Bestiary stats + verbatim memos.
- Skipped pages (data-sparse BESM Disc-only, missing stat block, duplicate name) never
  touch the DB.
- Normalized name check (strip non-alphanumerics) prevents duplicate insertion
  across punctuation/hyphen/apostrophe variants (e.g. Jack-O'Lantern).

No engine code is touched; this is pure disc-content wiring. The live DB is only
written when --dry-run is NOT passed.
"""

import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))            # chronos-core/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))  # dev/

from engine import guild_roster
from engine.disc_pullover import SETTING_ID, extract_file

DEFAULT_BASE = "../besm-disc-digital-dm/sxm1-besm-folder/Bestiary"


def normalize_name(name: str) -> str:
    """Slug-normalize for collision detection (strips punctuation/hyphens/case)."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def discover_markdowns(base: str) -> list[str]:
    files = []
    for root, _, names in os.walk(base):
        for f in sorted(names):
            if f.endswith(".md") and os.path.getsize(os.path.join(root, f)) > 0:
                files.append(os.path.join(root, f))
    return sorted(files)


def _build_character(payload: dict) -> dict:
    """Shape an extractor payload into upsert_character's `character` dict."""
    return {
        "name": payload["name"],
        "rank_label": payload["rank_label"],
        "race": payload["race"],
        "points_budget": payload["points_budget"],
        "stat_body": payload["stat_body"],
        "stat_mind": payload["stat_mind"],
        "stat_soul": payload["stat_soul"],
        "acv": payload["acv"],
        "dcv": payload["dcv"],
        "max_hp": payload["max_hp"],
        "max_ep": payload["max_ep"],
        "sixth_guard": payload["sixth_guard"],
        "structural_fault": payload["structural_fault"],
        "levers": payload["levers"],
        "combat_techniques": payload["combat_techniques"],
        "skills": payload["skills"],
        "defects": payload["defects"],
    }


def ingest(base: str = DEFAULT_BASE, update_existing: bool = False,
           dry_run: bool = False, setting_id: str = SETTING_ID) -> dict:
    """Run the BESM Disc Bestiary ingest against the live roster DB.

    Returns a summary dict: inserted / updated / skipped / existing / errors.
    Skipped (data-sparse etc.) and existing-but-untouched rows never call
    upsert_character, so the live DB is only mutated for genuinely new or
    explicitly-upgraded entries.
    """
    if not dry_run:
        guild_roster.init_roster_db()

    with guild_roster.get_roster_connection() as conn:
        # norm -> canonical DB name, so a case/spelling variant in the Bestiary
        # upgrades the existing row in place rather than inserting a duplicate.
        existing_map = {
            normalize_name(r[0]): r[0]
            for r in conn.execute(
                "SELECT name FROM characters WHERE setting_id = ?", (setting_id,)
            ).fetchall()
        }

    summary = {"inserted": 0, "updated": 0, "skipped": 0, "existing": 0, "errors": 0}
    seen_norms: set[str] = set()

    for path in discover_markdowns(base):
        for payload in extract_file(path, seen=seen_norms):
            if "skip" in payload:
                summary["skipped"] += 1
                continue
            norm = normalize_name(payload["name"])
            if norm in seen_norms:
                # Already handled within this run.
                summary["skipped"] += 1
                continue
            if norm in existing_map and not update_existing:
                summary["existing"] += 1
                continue
            # On a normalized collision, fold the curated data into the canonical
            # (existing) row name — never insert a variant duplicate.
            if norm in existing_map:
                payload = {**payload, "name": existing_map[norm]}
            if not dry_run:
                guild_roster.upsert_character(
                    setting_id,
                    _build_character(payload),
                    payload["card_json"],
                    path,
                )
            if norm in existing_map:
                summary["updated"] += 1
            else:
                summary["inserted"] += 1
            seen_norms.add(norm)

    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default=DEFAULT_BASE, help="Bestiary markdown root.")
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
        import json
        print(json.dumps({"dry_run": args.dry_run, **summary}, indent=2))
    else:
        verb = "DRY RUN (no writes)" if args.dry_run else "INGEST"
        print(f"[{verb}] BESM Disc Bestiary -> setting '{SETTING_ID}'")
        print(f"  inserted : {summary['inserted']}")
        print(f"  updated  : {summary['updated']}")
        print(f"  existing : {summary['existing']} (untouched, add-only)")
        print(f"  skipped  : {summary['skipped']} (data-sparse / dup / missing)")
        print(f"  errors   : {summary['errors']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
