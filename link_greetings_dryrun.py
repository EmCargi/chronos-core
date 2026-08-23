"""Link guild_rpg roster characters to their Character Markdown source of truth.

Greetings are parsed from each character's canonical markdown (see
engine.guild_roster.get_character_greetings). Most roster rows were never
linked via `md_source_path`, so /greetings only worked for the 8 rows that had
a path set. This linker resolves every roster character to its vault markdown
by parsing the file's `Name:` field (robust against filename typos like
Faela vs Feala) and sets md_source_path idempotently.

Run with no args for a dry-run report; pass --apply to write.
"""
import argparse
import os
import re
import sys

sys.path.insert(0, "/home/megane/dev")
sys.path.insert(0, "/home/megane/dev/digital-dm-project/chronos-core")

from engine import guild_roster as gr

VAULT_BASE = "/home/megane/dev/digital-dm-project/guild-rpg-digital-dm/Characters/Official AK Characters/Character Markdowns"
SETTING_ID = "guild_rpg"


def normalize(name: str) -> str:
    n = name.lower()
    n = re.sub(r"[^a-z0-9]+", "", n)
    return n


RANK_TOKENS = re.compile(r"\b(a|b|c|d|s)[-\s]?rank\b|\brank\b", re.IGNORECASE)
MULTI_INDICATORS = re.compile(r"\band\b|&|\+|trio|party|,", re.IGNORECASE)


def parse_names(md_text: str) -> list:
    """Extract canonical character names from a markdown's Basic block(s)."""
    names = []
    # Match "- Name: X" or "Name: X" across the doc
    for m in re.finditer(r"name\s*:\s*([^\n\-]+)", md_text, re.IGNORECASE):
        cand = m.group(1).strip().strip("*").strip()
        # Drop rank annotations that sometimes trail the name
        cand = re.sub(r"\s*[\(\[].*?[\)\]]\s*$", "", cand)
        if cand and len(cand) <= 40:
            names.append(cand)
    # De-dup preserving order
    seen = set()
    out = []
    for n in names:
        if n.lower() not in seen:
            seen.add(n.lower())
            out.append(n)
    return out


def stem_tokens(basename: str):
    """Normalized filename-stem tokens (rank words stripped)."""
    stem = basename[:-3] if basename.endswith(".md") else basename
    stem = RANK_TOKENS.sub(" ", stem)
    return normalize(stem)


def gather_files():
    results = []
    for root, _dirs, files in os.walk(VAULT_BASE):
        for fn in files:
            if fn.endswith(".md"):
                path = os.path.join(root, fn)
                with open(path, "r", encoding="utf-8") as f:
                    text = f.read()
                names = parse_names(text)
                results.append((path, names, text))
    return results


def build_name_map(files):
    """Map normalized character name -> list of (path, greeting_count).

    Indexes both the full name and its first token (handles 'Sylvara Duskveil'
    matching roster short-name 'Sylvara').
    """
    from engine.guild_roster import parse_greetings_from_markdown

    name_map = {}
    for path, names, text in files:
        gcount = len(parse_greetings_from_markdown(text))
        for nm in names:
            for key in (normalize(nm), normalize(nm.split()[0]) if nm.split() else ""):
                if not key:
                    continue
                name_map.setdefault(key, []).append((path, gcount))
    return name_map


def resolve_conflict(candidates):
    """Pick the best file when a name resolves to multiple.

    Precedence: solo file (no and/trio/party in stem) > more greetings >
    shorter stem. Prefers a character's own card over a shared multi-character
    card (e.g. Miri -> Miri C-Rank.md, not C-Rank Trio.md).
    """
    def is_multi(path):
        return bool(MULTI_INDICATORS.search(os.path.basename(path)))
    return sorted(
        candidates,
        key=lambda c: (is_multi(c[0]), -c[1], len(os.path.basename(c[0]))),
    )[0][0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="Write md_source_path to the roster DB")
    args = ap.parse_args()

    files = gather_files()
    name_map = build_name_map(files)
    # Pre-compute per-file normalized stem (rank-stripped) for fallback matching
    stem_index = {}  # normalized_stem -> path
    for path, _names, _text in files:
        s = stem_tokens(os.path.basename(path))
        if s:
            stem_index.setdefault(s, path)

    # Current roster state
    with gr.get_roster_connection() as conn:
        rows = conn.execute(
            "SELECT name, md_source_path FROM characters WHERE setting_id = ? ORDER BY name",
            (SETTING_ID,),
        ).fetchall()

    linked = 0
    already = 0
    skipped_no_file = []
    skipped_other_file = []  # has a path but it differs / missing
    for r in rows:
        name = r["name"]
        norm = normalize(name)
        chosen = None
        if norm in name_map:
            chosen = resolve_conflict(name_map[norm])
        else:
            # Filename-stem fallback for {{char}}-style cards with no Name: field
            # (Kaelis, Nico). Only exact stem match, to avoid grabbing pair/trio files.
            if norm in stem_index:
                chosen = stem_index[norm]
        if not chosen:
            skipped_no_file.append(name)
            continue
        existing = r["md_source_path"] or ""
        if existing == chosen:
            already += 1
            continue
        if existing and existing != chosen:
            skipped_other_file.append((name, existing, chosen))
            continue
        if args.apply:
            gr.set_character_md_path(SETTING_ID, name, chosen)
        linked += 1
        print(f"  {'WRITE' if args.apply else 'WOULD LINK'}  {name:20} -> {chosen}")

    print(f"\nSummary: {linked} to link, {already} already correct, "
          f"{len(skipped_other_file)} differs-from-existing, "
          f"{len(skipped_no_file)} no markdown found.")
    if skipped_other_file:
        print("\nExisting path differs (left untouched):")
        for name, old, new in skipped_other_file:
            print(f"  {name:20} existing={old}\n                 candidate={new}")
    if skipped_no_file:
        print("\nNo markdown source found (unlinked):")
        print("  " + ", ".join(skipped_no_file))


if __name__ == "__main__":
    main()
