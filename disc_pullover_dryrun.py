#!/usr/bin/env python3
"""Dry-run sweep for the BESM Disc Bestiary pullover.

Scans the canonical BESM Disc stat-block pages, runs each through the deterministic
extractor (engine/disc_pullover.py), and prints every resulting
upsert_character() payload for review WITHOUT touching the roster DB.

Use this to sanity-check the full bestiary before the real ingest: confirm
names, tier labels, parsed stats, and memo coverage. Pages that are skipped
(data-sparse BESM Disc-only bosses, missing stat blocks, duplicates) are listed with
their exact reason so the gap surfaces before anything is written.
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # dev/
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))         # chronos-core/

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from engine.disc_pullover import extract_file

# The Bestiary is one monster per file; no skip-list needed (the extractor flags
# data-sparse pages itself). Kept for parity with the Guild dry-run structure.
SKIP_FILES: set[str] = set()


def discover_markdowns(base: str) -> list[str]:
    files = []
    for root, _, names in os.walk(base):
        for f in sorted(names):
            if f.endswith(".md") and f not in SKIP_FILES:
                full = os.path.join(root, f)
                if os.path.getsize(full) == 0:
                    continue
                files.append(full)
    return sorted(files)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base",
        default="../besm-disc-digital-dm/sxm1-besm-folder/Bestiary",
        help="Root dir holding the BESM Disc Bestiary markdown pages.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the payloads as JSON (for machine review) instead of a table.",
    )
    args = parser.parse_args()

    console = Console()
    base = os.path.abspath(args.base)
    if not os.path.isdir(base):
        console.print(f"[bold red]Base dir not found:[/bold red] {base}")
        return 1

    files = discover_markdowns(base)
    payloads, skipped = [], []
    seen: set[str] = set()
    for path in files:
        for payload in extract_file(path, seen=seen):
            if "skip" in payload:
                skipped.append(payload)
            else:
                payloads.append(payload)

    if args.json:
        import json
        console.print_json(json.dumps(
            {"payloads": payloads, "skipped": skipped}, ensure_ascii=False))
        return 0

    table = Table(title=f"BESM Disc Bestiary Pullover — Dry Run ({len(payloads)} resolved)")
    table.add_column("Name", style="bold cyan")
    table.add_column("Tier")
    table.add_column("CP")
    table.add_column("B/M/S")
    table.add_column("ACV/DCV")
    table.add_column("HP/EP")
    table.add_column("Memo", justify="center")

    for p in sorted(payloads, key=lambda x: x["name"]):
        memo_ok = bool(p.get("monster_memo"))
        memo_tag = "[green]✓[/green]" if memo_ok else "[bold yellow]⚠[/bold yellow]"
        stats = f"{p['stat_body']}/{p['stat_mind']}/{p['stat_soul']}"
        table.add_row(
            p["name"],
            p["rank_label"],
            str(p["points_budget"]),
            stats,
            f"{p['acv']}/{p['dcv']}",
            f"{p['max_hp']}/{p['max_ep']}",
            memo_tag,
        )
    console.print(table)

    if skipped:
        lines = [f"[bold yellow]{s['name']}[/bold yellow]: {s['skip']}" for s in skipped]
        console.print(Panel(
            "\n".join(lines),
            title=f"[bold yellow]⚠ Skipped ({len(skipped)})[/bold yellow]",
            border_style="yellow",
        ))

    missing_memo = [p["name"] for p in payloads if not p.get("monster_memo")]
    if missing_memo:
        console.print(
            f"\n[bold yellow]Missing Tamer's Memo (⚠):[/bold yellow] {', '.join(missing_memo)}")

    console.print(
        f"\n[bold green]Dry run complete.[/bold green] {len(payloads)} resolved, "
        f"{len(skipped)} skipped, {len(missing_memo)} missing memo. No DB writes performed."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
