"""Dry-run the Guild RPG region sheet pullover (no DB writes).

Scans the regions/ folder, parses every canonical region sheet, and prints a
compact preview plus an NS-completeness check so gaps can be fixed before the
real ingest. Honors SKIP_FILES (Guild / World lore / methods doc).
"""

import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT))                              # chronos-core/
sys.path.insert(0, str(PROJECT.parent.parent))  # dev/ for core

from engine.guild_region_pullover import (
    REGION_FILES, SKIP_FILES, extract_file, extract_region, extract_narrative_syntax,
)

REGIONS_DIR = (
    PROJECT
    / ".."
    / "guild-rpg-digital-dm"
    / "Characters"
    / "Official AK Characters"
    / "BESM Sheets"
    / "regions"
)


def main() -> int:
    if not REGIONS_DIR.exists():
        print(f"regions dir not found: {REGIONS_DIR}")
        return 2
    files = sorted(p.name for p in REGIONS_DIR.iterdir() if p.suffix == ".md")
    print(f"== Region folder: {REGIONS_DIR} ==\n")
    total = 0
    missing_ns = 0
    skip = 0
    for fn in files:
        if fn in SKIP_FILES:
            print(f"[SKIP] {fn} (non-region sheet)")
            skip += 1
            continue
        if fn not in REGION_FILES:
            print(f"[??]   {fn} (not in REGION_FILES — review)")
            continue
        results = extract_file(str(REGIONS_DIR / fn))
        for r in results:
            if "error" in r:
                print(f"[ERR]  {fn}: {r['error']}")
                missing_ns += 1
                continue
            total += 1
            sf = r.get("structural_fault", "")
            sg = r.get("sixth_guard", "")
            lv = r.get("levers", "")
            gaps = [g for g, v in (("structural_fault", sf), ("sixth_guard", sg)) if not v]
            if gaps:
                missing_ns += 1
            print(f"[OK]   {fn}")
            print(f"        name : {r['name']}")
            print(f"        type : {r['location_type']}")
            print(f"        geo  : {r.get('description','')[:70]}")
            print(f"        SF   : {sf[:60]}")
            print(f"        SG   : {sg[:60]}")
            print(f"        LV   : {'present' if lv else 'MISSING'} ({len(lv)} chars)")
            if gaps:
                print(f"        !! missing: {', '.join(gaps)}")
            print()
    print(f"== {total} region(s) parsed, {missing_ns} with missing NS, {skip} skipped ==")
    return 0


if __name__ == "__main__":
    sys.exit(main())
