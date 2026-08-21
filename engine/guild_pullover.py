"""Deterministic Guild RPG cast pullover extractor.

Parses the canonical Aelthar Keldor character markdowns
(``guild-rpg-digital-dm/Characters/``) into roster-ready payloads for
``upsert_character()`` WITHOUT an LLM. The markdowns carry the Active
Narrative Syntax (Structural Fault / Sixth Guard / Levers) as prose + a YAML
sentence block, but no numeric Tri-Stat stats — so the BESM numbers are derived
deterministically from the character's rank bracket, mirroring the conversion
precedent in ``card_to_besm.py``.

Supports the two markdown layouts used by the cast:

- **Single-character files** — a ``### Basic`` / ``### Description`` metadata
  block carrying ``- Name:`` / ``- Basic:`` / ``- Rank:`` lines.
- **Tagged multi-character files** (pairs + trio) — ``<Name>`` blocks each
  carrying their own metadata (e.g. Soren & Urkakh, the C-Rank Trio's Lina /
  Miri / Seris).

Output is a list of dicts shaped exactly for ``upsert_character``: name,
rank_label, race, points_budget, stat_body/mind/soul, acv, dcv, max_hp, max_ep,
plus the three narrative-syntax fields.
"""

import re

from .card_to_besm import ARCHETYPE_KEYWORDS, ARCHETYPE_ORDER, ARCHETYPES

# Guild rank -> (CP bracket midpoint, stat pool). Midpoint is used as the
# deterministic points_budget; the pool feeds allocate_stats the way card_to_besm
# feeds its Tier ladder. Brackets follow the canonical Aelthar sheet:
# D 0-49 / C 50-74 / B 75-99 / A 100-149 / S 150-250+.
RANK_BRACKETS = {
    "S": (200, 30, 12),
    "A": (120, 23, 12),
    "B": (82, 17, 12),
    "C": (57, 12, 9),
    "D": (35, 10, 7),
}

# Succinct rank labels that match the existing roster's house style
# (e.g. "A-Rank (Elite)"). Fall back to the plain bracket when unknown.
RANK_LABELS = {
    "S": "S-Rank (Sovereign Tier)",
    "A": "A-Rank (Elite)",
    "B": "B-Rank (Professional)",
    "C": "C-Rank (Standard)",
    "D": "D-Rank (Novice)",
}

# Canonical roster names. The markdowns sometimes carry a full name ("Sylvara
# Duskveil", "Tomoe Shirakane") but the roster keys on the short form — and a
# mismatched name would UPSERT a duplicate row instead of updating the existing
# wired character. Map any source variant to the roster's canonical key.
CANONICAL_NAMES = {
    "Sylvara Duskveil": "Sylvara",
    "Tomoe Shirakane": "Tomoe",
}


def _rank_letter(rank_text: str) -> str:
    """Map a markdown rank string ('D-Rank', 'C-Rank', 'S/SS-Rank') to S/A/B/C/D."""
    m = re.search(r"\b([SABCD])\s*/?\s*[SABCD]?\s*-?\s*Rank", rank_text, re.I)
    return m.group(1).upper() if m else ""


def split_character_blocks(md_text: str) -> list[str]:
    """Split a markdown into per-character metadata blocks.

    Returns the ``<Name>`` tagged blocks when present (pairs/trio), else the
    whole file as a single block (single-character files).
    """
    tagged = re.findall(r"<([A-Za-z]+)>\n(.*?)\n</\1>", md_text, re.S)
    if tagged:
        return [block for _, block in tagged]
    return [md_text]


def parse_metadata(block: str, full_text: str = "") -> dict:
    """Extract name, race, and rank from a character block's metadata lines.

    The cast files are not perfectly uniform, so this tolerates the variants in
    the wild: ``- Name:`` / ``- Basic:`` blocks, ``- Adventurer Rank:`` /
    ``- Rank:`` lines, an embedded ``Rank: C-Rank`` inside ``Basic``, and (for
    files with no ``- Name:`` at all) the Narrative-Sentence heading
    (``Kaelis's Individual Narrative Sentence``).
    """
    data: dict[str, str] = {}

    def grab(label: str):
        # Tolerates "### Name: X" / "- Name: X" / bare "Name: X" / "- Basic: X"
        # AND the registry sheets' "*  **Name:** X" / "*  **Adventurer Rank:** X".
        m = re.search(
            rf"^#*\s*-?\s*\*+\s*\*?\*?\s*{label}\s*:\s*(.+)$", block, re.M
        ) or re.search(
            rf"^#*\s*-?\s*{label}\s*:\s*(.+)$", block, re.M
        )
        if not m:
            return ""
        # Strip the closing bold "** " from "*  **Name:** Beril" → "Beril".
        return re.sub(r"^\s*\*+\s*", "", m.group(1)).strip()

    name = grab("Name")
    if not name:
        # Fall back to the Narrative-Sentence heading title.
        heading = re.search(
            r"#+\s*📐\s*([A-Za-z' ]+)['’]?\s*Individual Narrative Sentence",
            block, re.I,
        )
        if heading:
            name = re.sub(r"['’]s\b", "", heading.group(1).strip()).strip()
    data["name"] = name

    basic = grab("Basic")
    race = ""
    basic_race = re.search(r"^(?:Female|Male)[,;]\s*([A-Za-z]+(?:[ -][A-Za-z]+)*)", basic)
    if basic_race:
        race = basic_race.group(1).strip()
    race = race or grab("Race")
    data["race"] = race

    rank = grab("Rank") or grab("Adventurer Rank")
    if not rank:
        rank_m = re.search(r"Rank\s*:\s*([SABCD][^\n]*-?\s*Rank)", basic, re.I)
        rank = rank_m.group(1).strip() if rank_m else ""
    if not rank:
        rank_m = re.search(r"\b([SABCD][^\n,]{0,20}Rank)\b", basic, re.I)
        rank = rank_m.group(1).strip() if rank_m else ""
    if not rank:
        # Rank Bracket: line in the DM cheat sheet (e.g. "B-Rank (Heroic | 75-99 CP)")
        bracket = re.search(r"Rank Bracket[^\n]*?\b([SABCD])-?Rank", full_text or block, re.I)
        if bracket:
            rank = bracket.group(1) + "-Rank"
    data["rank"] = rank

    return data


def _rank_from_path(path: str) -> str:
    """Fall back to the rank encoded in the file path/filename (e.g. D-Rank/…)."""
    m = re.search(r"\b([SABCD])-?Rank\b", path, re.I)
    return m.group(1) + "-Rank" if m else ""


def extract_narrative_syntax(md_text: str) -> dict:
    """Pull Structural Fault / Sixth Guard / Levers out of the markdown prose.

    Prefers the structured YAML sentence block for the fault, then the prose
    Sixth Guard anchor + three Lever sections. Returns the three roster fields.
    """
    # Prefer the registry-sheet "Individual Action Syntax Card" YAML format.
    reg = parse_registry_narrative_syntax(md_text)
    if reg.get("structural_fault") or reg.get("sixth_guard"):
        return reg

    structural_fault = ""
    sixth_guard = ""
    levers = ""

    yaml_m = re.search(
        r"```\s*\n?\s*The_Subject:\s*\n(.*?)```", md_text, re.S | re.I
    )
    if yaml_m:
        yaml_block = yaml_m.group(1)
        fault_m = re.search(r'Structural_Fault:\s*"?(.*?)"?\s*$', yaml_block, re.M | re.I)
        if fault_m:
            structural_fault = fault_m.group(1).strip().rstrip('"').lstrip("* ")

    if not structural_fault:
        fault_m = re.search(
            r"The Structural Fault[^\n:]*:\s*(.+)", md_text, re.I
        )
        if fault_m:
            structural_fault = fault_m.group(1).strip().lstrip("* ").strip()

    # Sixth Guard: the prose anchor paragraph under the 🛑 heading.
    anchor_m = re.search(
        r"Sixth Guard.*?\n\n(.+?)(?=\n\n|##\s|###\s|####\s|$)",
        md_text, re.S | re.I,
    )
    if anchor_m:
        sixth_guard = re.sub(r"\s+", " ", anchor_m.group(1)).strip()

    # Levers: three sections, each "Lever N: The X Vector" carrying
    # "- **The Strategy:** ..." and "- **The Action:** ..." bullets. Reduce to
    # "Name: <strategy sentence> <action sentence>" — the engine-native shape
    # the roster's existing levers use, minus the markdown scaffolding.
    lever_names = ["Containment", "Velocity", "Defection"]
    lever_parts = []
    for name in lever_names:
        pat = re.compile(
            rf"Lever\s*\d+\s*:\s*The\s+{name}\s+Vector.*?(?=\n####|\n###|\n##|\Z)",
            re.S | re.I,
        )
        sec = pat.search(md_text)
        if not sec:
            continue
        section = sec.group(0)
        strategy = re.search(r"\*\*The Strategy:?\*\*\s*(.+)", section, re.I)
        action = re.search(r"\*\*The Action:?\*\*\s*(.+)", section, re.I)
        bits = []
        if strategy:
            bits.append(re.sub(r"\s+", " ", strategy.group(1)).strip())
        if action:
            bits.append(re.sub(r"\s+", " ", action.group(1)).strip())
        if bits:
            lever_parts.append(f"{name}: {' '.join(bits)}")
    if lever_parts:
        levers = " ".join(lever_parts)

    return {
        "structural_fault": structural_fault,
        "sixth_guard": sixth_guard,
        "levers": levers,
    }


def parse_explicit_stats(md_text: str) -> dict:
    """Pull explicit numeric BESM stats from the registry-sheet stats table.

    The design-pass sheets carry a ``| **Body (B) Stat** | **4** |`` table (rows
    may be collapsed onto one physical line with ``||`` joins). Returns a dict
    with stat_body/mind/soul, acv, dcv, max_hp, max_ep, shock_value when the
    table is present and complete enough, else {}.
    """
    def cell_value(pattern: str) -> int | None:
        m = re.search(pattern, md_text)
        if not m:
            return None
        val = m.group(1).strip().rstrip("*").strip()
        try:
            return int(val)
        except ValueError:
            return None

    stats = {}
    body = cell_value(r"\*\*Body \(B\) Stat\*\*[^|]*\|\s*\*?\*?(\d+)")
    mind = cell_value(r"\*\*Mind \(M\) Stat\*\*[^|]*\|\s*\*?\*?(\d+)")
    soul = cell_value(r"\*\*Soul \(S\) Stat\*\*[^|]*\|\s*\*?\*?(\d+)")
    if body and mind and soul:
        stats.update(stat_body=body, stat_mind=mind, stat_soul=soul)
        # Prefer explicit derived values when present, else recompute from stats.
        acv = cell_value(r"\*\*Attack Combat Value \(ACV\)\*\*[^|]*\|\s*\*?\*?(\d+)")
        dcv = cell_value(r"\*\*Defence Combat Value \(DCV\)\*\*[^|]*\|\s*\*?\*?(\d+)")
        hp = cell_value(r"\*\*Health Points \(HP\)\*\*[^|]*\|\s*\*?\*?(\d+)")
        ep = cell_value(r"\*\*Energy Points \(EP\)\*\*[^|]*\|\s*\*?\*?(\d+)")
        stats["acv"] = acv or (body + mind + soul) // 3
        stats["dcv"] = dcv or max(1, (body + mind + soul) // 3 - 2)
        stats["max_hp"] = hp or (body + soul) * 5
        stats["max_ep"] = ep or (mind + soul) * 5
        # Budget from the Adventurer Rank line's CP bracket when present, else
        # ladder default. Anchored to the rank line so attribute "(4 CP)" bundles
        # don't get mistaken for the character budget.
        rank_line = re.search(r"(?:Adventurer\s+)?Rank[^\n]*\([^\n]*\d+\s*CP", md_text, re.I)
        if rank_line:
            budget_m = re.search(r"\([^\n]*?(\d+)\s*CP", rank_line.group(0), re.I)
            if budget_m:
                stats["points_budget"] = int(budget_m.group(1))
    return stats


def parse_registry_narrative_syntax(md_text: str) -> dict:
    """Parse the registry sheets' ``Individual Action Syntax Card`` YAML block.

    The design-pass format nests the fault and levers differently from the
    legacy prose: ``Structural Fault:`` under SUBJECT, ``THE ANCHOR`` →
    Failure Trigger + Systemic Collapse (the Sixth Guard), and ``PREDICATE`` →
    three ``Lever N: <Channel>`` entries with nested Strategy/Action.
    """
    # The card's YAML may be fenced (```yaml ... ```) or bare (some copies omit
    # the fence) — accept both so a missing code block never drops the syntax.
    yaml_m = re.search(
        r"Individual Action Syntax Card[^\n]*\n(?:(?:```yaml)\n)?(.*?)(?:\n```)?(?=\n###|\n##\n|\n## |\Z)",
        md_text, re.S | re.I,
    )
    if not yaml_m:
        return {}
    block = yaml_m.group(1).rstrip()

    fault = ""
    fault_m = re.search(r"Structural Fault:\s*[\"']?(.*?)[\"']?\s*(?:\n|$)", block, re.I)
    if fault_m:
        fault = fault_m.group(1).strip().rstrip('"').strip()
        # The source writes `"Fault" — prose`; drop the paired quotes around the
        # em-dash so the field reads as engine-native prose.
        fault = re.sub(r'^"', "", fault)
        fault = re.sub(r'"\s*—', " —", fault)
        fault = fault.lstrip()

    # Sixth Guard = failure trigger + systemic collapse, joined.
    trigger = re.search(r"Failure Trigger:\s*[\"']?(.*?)[\"']?\s*(?:\n|$)", block, re.I)
    collapse = re.search(r"Systemic Collapse:\s*(.+?)(?=\n\s*\n|PREDICATE|\Z)", block, re.S | re.I)
    guard = ""
    if trigger:
        t = trigger.group(1).strip().rstrip('"').strip()
        t = re.sub(r'^"', "", t)
        t = re.sub(r'"\s*—', " —", t)
        t = t.lstrip()
        guard = "Failure Trigger: " + t
    if collapse:
        guard += " Systemic Collapse: " + re.sub(r"\s+", " ", collapse.group(1)).strip()
    guard = guard.strip()

    # Three levers with nested Strategy / Action bullets.
    lever_parts = []
    for name in ["Containment", "Velocity", "Defection"]:
        pat = re.compile(
            rf"Lever \d+:\s*{name}\s*\([^)]*\):\s*\n((?:\s+-.*\n?)*)",
            re.I,
        )
        m = pat.search(block)
        if not m:
            continue
        chunk = m.group(1)
        strat = re.search(r"Strategy:\s*(.+)", chunk, re.I)
        action = re.search(r"Action:\s*(.+)", chunk, re.I)
        bits = []
        if strat:
            bits.append(re.sub(r"\s+", " ", strat.group(1)).strip())
        if action:
            bits.append(re.sub(r"\s+", " ", action.group(1)).strip())
        if bits:
            lever_parts.append(f"{name}: {' '.join(bits)}")
    levers = " ".join(lever_parts)

    return {
        "structural_fault": fault,
        "sixth_guard": guard,
        "levers": levers,
    }


def classify_archetype(text: str) -> str:
    """Keyword-score full block text (not a Combat Role line) against the 5
    systemic templates. Highest hit wins; ties break in ARCHETYPE_ORDER."""
    lower = text.lower()
    scores = {
        name: sum(1 for kw in kws if kw in lower)
        for name, kws in ARCHETYPE_KEYWORDS.items()
    }
    best = max(scores, key=lambda n: (scores[n], -ARCHETYPE_ORDER.index(n)))
    return best if scores[best] > 0 else "Balanced"


def derive_stats(rank_letter: str, description: str) -> dict:
    """Derive numeric BESM stats from the rank bracket + archetype allocation."""
    budget, pool, cap = RANK_BRACKETS.get(rank_letter, RANK_BRACKETS["D"])
    archetype = classify_archetype(description)
    weights = ARCHETYPES.get(archetype, ARCHETYPES["Balanced"])
    stats = {"Body": 1, "Mind": 1, "Soul": 1}
    remaining = max(0, pool - 3)
    order = sorted(weights, key=lambda s: -weights[s])
    while remaining > 0:
        moved = False
        for stat in order:
            if remaining <= 0:
                break
            if stats[stat] < cap:
                stats[stat] += 1
                remaining -= 1
                moved = True
        if not moved:
            break
    body, mind, soul = stats["Body"], stats["Mind"], stats["Soul"]
    acv = (body + mind + soul) // 3
    return {
        "points_budget": budget,
        "stat_body": body,
        "stat_mind": mind,
        "stat_soul": soul,
        "acv": acv,
        "dcv": max(1, acv - 2),
        "max_hp": (body + soul) * 5,
        "max_ep": (mind + soul) * 5,
        "archetype": archetype,
    }


def extract_character(md_text: str, source_path: str = "") -> dict:
    """Compile a single character markdown into an upsert_character payload.

    Raises ValueError when the name or rank can't be resolved (so the caller
    can flag files that need manual attention rather than silently skip).
    """
    meta = parse_metadata(md_text, full_text=md_text)
    if not meta["rank"] and source_path:
        meta["rank"] = _rank_from_path(source_path)
    if not meta["name"]:
        raise ValueError("could not resolve character name")
    if not meta["rank"]:
        raise ValueError(f"could not resolve rank for {meta['name']}")

    letter = _rank_letter(meta["rank"])
    if not letter:
        raise ValueError(f"unrecognized rank '{meta['rank']}' for {meta['name']}")

    ns = extract_narrative_syntax(md_text)

    explicit = parse_explicit_stats(md_text)
    if explicit:
        explicit.setdefault("points_budget", RANK_BRACKETS[letter][0])
        stats = {**explicit, "archetype": classify_archetype(md_text)}
    else:
        stats = derive_stats(letter, md_text)

    return {
        "name": CANONICAL_NAMES.get(meta["name"], meta["name"]),
        "rank_label": RANK_LABELS[letter],
        "race": meta["race"] or "Unknown",
        "points_budget": stats["points_budget"],
        "stat_body": stats["stat_body"],
        "stat_mind": stats["stat_mind"],
        "stat_soul": stats["stat_soul"],
        "acv": stats["acv"],
        "dcv": stats["dcv"],
        "max_hp": stats["max_hp"],
        "max_ep": stats["max_ep"],
        "structural_fault": ns["structural_fault"],
        "sixth_guard": ns["sixth_guard"],
        "levers": ns["levers"],
        "archetype": stats["archetype"],
    }


def extract_file(path: str) -> list[dict]:
    """Parse a markdown file into one-or-more upsert payloads (handles pairs/trio)."""
    md_text = open(path, encoding="utf-8", errors="ignore").read()
    payloads = []
    for block in split_character_blocks(md_text):
        try:
            payload = extract_character(block, source_path=path)
            # Tagged files (pairs/trio) carry the NS at the file level, not
            # inside each <Name> block — backfill it from the full text when the
            # block-level parse came up empty.
            if not payload["structural_fault"] or not payload["sixth_guard"]:
                file_ns = extract_narrative_syntax(md_text)
                payload["structural_fault"] = payload["structural_fault"] or file_ns["structural_fault"]
                payload["sixth_guard"] = payload["sixth_guard"] or file_ns["sixth_guard"]
                payload["levers"] = payload["levers"] or file_ns["levers"]
            payloads.append(payload)
        except ValueError as e:
            payloads.append({"error": str(e), "file": path})
    return payloads
