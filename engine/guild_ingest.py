"""Guild RPG cast live ingest — wires the registry sheets into the roster.

Mirrors ``engine/disc_ingest.py`` in shape: it connects the deterministic,
LLM-free registry-sheet parser (``engine/guild_pullover.py``) to the live roster
DB via ``guild_roster.upsert_character``, behind a SAFE-INGEST guard:

- **Default (Option B — Safe Add-Only):** only sheets whose normalized name is
  ABSENT from the ``guild_rpg`` setting are inserted. The existing hand-tuned
  rows (Eira, Rosivelle, Sylvara, Aglae, Tomoe, Nieven, Zarlen, Liora) are left
  strictly untouched — the registry sheets become the source of truth for *new*
  adventurers without clobbering prior tuning.
- **--update-existing (Option A — Canon Upsert):** overlapping entries are also
  upserted, upgrading them with the registry-sheet stats + narrative syntax so
  the sheets are fully authoritative.
- The live DB is checkpointed to ``data/checkpoints/`` before any write, so a run
  is always reversible.
- Normalized name check (strip non-alphanumerics) prevents duplicate insertion
  across punctuation/hyphen/apostrophe variants.

No engine math is touched; this is pure disc-content wiring. The live DB is only
written when ``--dry-run`` is NOT passed.
"""

import argparse
import json
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))               # chronos-core/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))  # dev/

from engine import guild_roster
from engine.guild_pullover import extract_file

SETTING_ID = "guild_rpg"
DEFAULT_BASE = "../guild-rpg-digital-dm/Characters/Official AK Characters/BESM Sheets/adventurers"

# Sub-sheets that are not standalone roster characters.
SKIP_FILES = {
    "sefnes-arcane-golem-sub-sheet.md",
    # Superseded by the v2 Abyssal Behemoth sheet (which adds the Sixth Guard Anchor).
    "abyssal-behemoth-boss-sheet.md",
}


def normalize_name(name: str) -> str:
    """Slug-normalize for collision detection (strips punctuation/hyphens/case)."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def discover_markdowns(base: str) -> list[str]:
    files = []
    for root, _, names in os.walk(base):
        for f in sorted(names):
            if f.endswith(".md") and f not in SKIP_FILES and os.path.getsize(os.path.join(root, f)) > 0:
                files.append(os.path.join(root, f))
    return sorted(files)


def _build_character(payload: dict) -> dict:
    """Shape an extractor payload into upsert_character's `character` dict."""
    char = {
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
    }
    # Loadout fields (from extract_loadout) ride through so the cast's BESM
    # builds reach the roster columns — they were dropped in the original shape.
    for key in ("combat_techniques", "skills", "defects"):
        if payload.get(key):
            char[key] = payload[key]
    if payload.get("shock_value") is not None:
        char["shock_value"] = payload["shock_value"]
    return char


def _checkpoint_db() -> str | None:
    """Snapshot the live roster DB before mutating it. Returns the backup path."""
    src = guild_roster.ROSTER_PATH
    if not os.path.exists(src):
        return None
    checkpoint_dir = os.path.join(guild_roster.DATA_DIR, "checkpoints")
    os.makedirs(checkpoint_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    dst = os.path.join(checkpoint_dir, f"guild_rpg_roster_guild_ingest_{stamp}.db")
    shutil.copy2(src, dst)
    return dst


def ingest(base: str = DEFAULT_BASE, update_existing: bool = False,
           dry_run: bool = False) -> dict:
    """Run the Guild RPG cast ingest against the live roster DB.

    Returns a summary dict: inserted / updated / skipped / existing / errors.
    Skipped (unresolved) and existing-but-untouched rows never call
    upsert_character, so the live DB is only mutated for genuinely new or
    explicitly-upgraded entries.
    """
    if not dry_run:
        guild_roster.init_roster_db()
        _checkpoint_db()

    with guild_roster.get_roster_connection() as conn:
        existing = {
            normalize_name(r[0])
            for r in conn.execute(
                "SELECT name FROM characters WHERE setting_id = ?", (SETTING_ID,)
            ).fetchall()
        }

    summary = {"inserted": 0, "updated": 0, "skipped": 0, "existing": 0, "errors": 0}
    seen_norms: set[str] = set()

    for path in discover_markdowns(base):
        for payload in extract_file(path):
            if "error" in payload:
                summary["errors"] += 1
                continue
            norm = normalize_name(payload["name"])
            if norm in seen_norms:
                # Already handled within this run.
                summary["skipped"] += 1
                continue
            if norm in existing and not update_existing:
                summary["existing"] += 1
                continue
            if not dry_run:
                guild_roster.upsert_character(
                    SETTING_ID,
                    _build_character(payload),
                    "{}",
                    path,
                )
            if norm in existing:
                summary["updated"] += 1
            else:
                summary["inserted"] += 1
            seen_norms.add(norm)

    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default=DEFAULT_BASE, help="Registry sheets markdown root.")
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
        print(f"[{verb}] Guild RPG cast -> setting '{SETTING_ID}'")
        print(f"  inserted : {summary['inserted']}")
        print(f"  updated  : {summary['updated']}")
        print(f"  existing : {summary['existing']} (untouched, add-only)")
        print(f"  skipped  : {summary['skipped']} (unresolved / dup)")
        print(f"  errors   : {summary['errors']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
