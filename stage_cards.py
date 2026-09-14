"""Stage BESM Disc V2 cards for deterministic batch_ingest.

Copies statted character cards from persona-etl/output/ into chronos-core/
staging/raw/ with the canonical [SYSTEM DATA: BESM 4E MECHANICS] block
injected into the description, so batch_ingest METHOD 1 parses the compiled
stats instead of handing them to the LLM mapper.

Only cards that actually carry a Combat Profile HP value are staged — the
lore-only BESM Disc cards (no stats decoded yet) are reported and skipped rather
than fabricated into bogus Tier 1 rows.

Idempotent & atomic: never clobbers an already-staged card, writes via
tempfile + os.replace.
"""

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))  # dev/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))                     # chronos-core/

from engine.card_to_besm import build_system_data_block, extract_game_hp


DEFAULT_SOURCE = "/home/megane/dev/persona-etl/output"
DEFAULT_RAW = os.path.join(os.path.dirname(os.path.abspath(__file__)), "staging", "raw")

SYSTEM_HEADER = "[SYSTEM DATA: BESM 4E MECHANICS]"


def find_cards(source: str) -> list:
    """Return (name, card_path) pairs for every *_character_card.json in source."""
    cards = []
    for entry in sorted(Path(source).iterdir()):
        if not entry.is_dir():
            continue
        matches = sorted(entry.glob("*_character_card.json"))
        for card_path in matches:
            cards.append((card_path.stem.replace("_character_card", ""), card_path))
    return cards


def inject_system_data(description: str, system_block: str) -> str:
    """Append the SYSTEM DATA block to a card description (idempotent)."""
    if SYSTEM_HEADER in description:
        return description
    return description.rstrip() + "\n\n" + system_block


def atomic_write_json(path: Path, payload: dict) -> None:
    """UTF-8 atomic JSON writer (tempfile + os.replace)."""
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        os.unlink(tmp) if os.path.exists(tmp) else None
        raise


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", default=DEFAULT_SOURCE, help="persona-etl cards dir")
    ap.add_argument("--raw", default=DEFAULT_RAW, help="staging/raw target dir")
    ap.add_argument("--dry-run", action="store_true", help="compile + report only, write nothing")
    args = ap.parse_args()

    os.makedirs(args.raw, exist_ok=True)
    cards = find_cards(args.source)
    print(f"\U0001f6a6 Staging sweep: {len(cards)} cards found in {args.source}\n")

    staged, skipped_no_stats, skipped_exists, failed = [], [], [], []

    for name, card_path in cards:
        try:
            with open(card_path, "r", encoding="utf-8") as f:
                card = json.load(f)
            inner = card.get("data", card)
            desc = str(inner.get("description", ""))

            if extract_game_hp(desc) <= 0:
                skipped_no_stats.append(name)
                continue

            compiled = build_system_data_block(name, desc)
            new_desc = inject_system_data(desc, compiled["system_block"])
            if new_desc == desc:
                skipped_exists.append(name)
                continue

            target = Path(args.raw) / f"{name}_character_card.json"
            if target.exists() and not args.dry_run:
                skipped_exists.append(name)
                continue

            if args.dry_run:
                staged.append(name)
                continue

            inner["description"] = new_desc
            atomic_write_json(target, card)
            staged.append(name)
        except Exception as e:
            failed.append((name, str(e)))

    print(f"  \u2705 Staged: {len(staged)}")
    print(f"  \u23f8\ufe0f  Skipped (no stats / lore-only): {len(skipped_no_stats)}")
    print(f"  \u233f Already in raw (or no change): {len(skipped_exists)}")
    if failed:
        print(f"  \u274c Failed: {len(failed)}")
        for name, err in failed[:10]:
            print(f"      {name}: {err}")

    if args.dry_run:
        print(f"\nDry run — {len(staged)} cards would be staged.")
        print("  " + ", ".join(staged[:20]) + ("..." if len(staged) > 20 else ""))


if __name__ == "__main__":
    main()