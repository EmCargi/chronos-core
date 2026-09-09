#!/usr/bin/env python3
"""Dry-run sweep for the Guild RPG cast pullover.

Scans the canonical registry sheets (the roster's source of truth), runs each
through the deterministic extractor (engine/guild_pullover.py), and prints every
resulting upsert_character() payload for review WITHOUT touching the roster DB.

Use this to sanity-check the full cast before the real ingest: confirm names,
rank labels, derived stats, and narrative-syntax coverage. A character missing
its structural_fault / sixth_guard / levers shows a warning so the design-pass
gap surfaces before anything is written.
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

from engine.guild_pullover import extract_file

# Pair/trio + superseded + duplicate source files are skipped here. The design
# pass authored individual registry sheets (beril-c-rank.md, miri-c-rank.md,
# soren-d-rank.md, urkakh-b-rank.md, vandil-b-rank.md) for the pair/trio
# characters, so their legacy counterparts no longer feed the ingest.
SKIP_FILES = {
    # Legacy pair/trio files (replaced by registry sheets).
    "Beril and Vandil B Rank.md",
    "Urkakh and Soren B-Rank.md",
    "Soren and Urkakh B-Rank.md",
    "C-Rank Trio.md",
    "Nei and Tai D Rank.md",
    # Legacy single file superseded by the soren-d-rank.md registry sheet.
    "Soren D-Rank.md",
    # Duplicate of "Sera C Rank.md".
    "Sera C-Rank.md",
    # Sefne's arcane-golem sub-sheet — not a standalone roster character.
    "sefnes-arcane-golem-sub-sheet.md",
    # Superseded by the v2 Abyssal Behemoth sheet (which adds the Sixth Guard Anchor).
    "abyssal-behemoth-boss-sheet.md",
}


def discover_markdowns(base: str) -> list[str]:
    files = []
    for root, _, names in os.walk(base):
        for f in sorted(names):
            if f.endswith(".md") and f not in SKIP_FILES:
                full = os.path.join(root, f)
                # Skip empty placeholder files (e.g. the leftover Miri C-Rank.md).
                if os.path.getsize(full) == 0:
                    continue
                files.append(full)
    return sorted(files)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base",
        default="../guild-rpg-digital-dm/Characters/Official AK Characters/BESM Sheets/adventurers",
        help="Root dir holding the registry sheets (the roster's source of truth).",
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
    payloads, errors = [], []
    for path in files:
        for payload in extract_file(path):
            if "error" in payload:
                errors.append(payload)
            else:
                payloads.append(payload)

    # Sort by rank then name for a readable sweep.
    rank_order = {"S": 0, "A": 1, "B": 2, "C": 3, "D": 4, "FAN": 5}
    payloads.sort(key=lambda p: (rank_order.get(p["rank_label"][0], 9), p["name"]))

    if args.json:
        import json
        console.print_json(json.dumps({"payloads": payloads, "errors": errors}))
        return 0

    table = Table(title=f"Guild RPG Cast Pullover — Dry Run ({len(payloads)} characters)")
    table.add_column("Name", style="bold cyan")
    table.add_column("Rank")
    table.add_column("Race")
    table.add_column("CP")
    table.add_column("B/M/S")
    table.add_column("ACV/DCV")
    table.add_column("HP/EP")
    table.add_column("NS", justify="center")
    table.add_column("Tech", justify="center")
    table.add_column("Sk", justify="center")
    table.add_column("Def", justify="center")
    table.add_column("SV")

    for p in payloads:
        # Levers are an adventurer-only construct; bosses carry the Structural
        # Fault + Sixth Guard core but no three-vector Lever block.
        ns_ok = all(p.get(k) for k in ("structural_fault", "sixth_guard"))
        ns_tag = "[green]✓[/green]" if ns_ok else "[bold yellow]⚠[/bold yellow]"
        stats = f"{p['stat_body']}/{p['stat_mind']}/{p['stat_soul']}"
        tech = len(p.get("combat_techniques", []))
        sk = len(p.get("skills", []))
        df = len(p.get("defects", []))
        loadout_tag = f"[green]{tech}[/green]" if tech else "[bold yellow]0[/bold yellow]"
        sv = p.get("shock_value") or "auto"
        table.add_row(
            p["name"],
            p["rank_label"],
            p["race"],
            str(p["points_budget"]),
            stats,
            f"{p['acv']}/{p['dcv']}",
            f"{p['max_hp']}/{p['max_ep']}",
            ns_tag,
            loadout_tag,
            str(sk),
            str(df),
            str(sv),
        )

    console.print(table)

    if errors:
        console.print(Panel(
            "\n".join(f"[bold red]{e['file']}[/bold red]: {e['error']}" for e in errors),
            title="[bold red]⚠ Unresolved files[/bold red]",
            border_style="red",
        ))

    missing_ns = [p["name"] for p in payloads if not all(p.get(k) for k in ("structural_fault", "sixth_guard"))]
    if missing_ns:
        console.print(f"\n[bold yellow]Missing narrative syntax (⚠):[/bold yellow] {', '.join(missing_ns)}")

    no_loadout = [p["name"] for p in payloads if not p.get("combat_techniques") and not p.get("skills") and not p.get("defects")]
    if no_loadout:
        console.print(f"\n[bold yellow]No loadout sections found (0/0/0):[/bold yellow] {', '.join(no_loadout)}")

    flags = [f"{p['name']}: {', '.join(p.get('loadout_flags', []))}" for p in payloads if p.get("loadout_flags")]
    if flags:
        console.print(Panel(
            "\n".join(f"[bold yellow]{f}[/bold yellow]" for f in flags),
            title="[bold yellow]Loadout review flags[/bold yellow]",
            border_style="yellow",
        ))

    console.print(
        f"\n[bold green]Dry run complete.[/bold green] {len(payloads)} payloads ready, "
        f"{len(errors)} unresolved, {len(missing_ns)} missing NS, "
        f"{len(no_loadout)} with no loadout. No DB writes performed."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
