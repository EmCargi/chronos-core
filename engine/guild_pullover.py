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

# Editorial provenance markers ("[cite: 386, 394]") are noise in roster fields
# that get injected into LLM prompts. Strip them before any parsing so the
# extractor is tolerant of the human-authored vault annotations.
_CITE_RE = re.compile(r"\[cite:[^\]]*\]", re.I)


def _strip_cites(text: str) -> str:
    return _CITE_RE.sub("", text)

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
    "Nieven Vara": "Nieven",
    "Sylvanus Vara": "Sylvanus",
}


def _rank_letter(rank_text: str) -> str:
    """Map a markdown rank string to S/A/B/C/D.

    Uses the LAST rank token in the line so compound descriptions like
    'Low C-Rank equivalent | S-Rank Administrative Gatekeeper' resolve to the
    character's actual tier (S), not the flavor comparison (C).
    """
    matches = re.findall(r"\b([SABCD])\s*/?\s*[SABCD]?\s*-?\s*Rank", rank_text, re.I)
    return matches[-1].upper() if matches else ""


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

    name = grab("Name") or grab("Character Name")
    if name:
        # Drop editorial citations, trailing epithet/note parentheticals, and
        # honorific prefixes so the key matches the roster's canonical row.
        name = _CITE_RE.sub("", name)
        name = re.sub(r"\s*\([^)]*\)\s*$", "", name)
        # Boss epithets ("Zarkoth, The Soul-Eater") — keep the base name only.
        name = re.sub(r",.*$", "", name).strip()
        name = re.sub(r"^(Archdruid|Professor)\s+", "", name, flags=re.I)
        name = name.strip()
    if not name:
        # Fall back to the Narrative-Sentence heading title.
        heading = re.search(
            r"#+\s*📐\s*([A-Za-z' ]+)['’]?\s*Individual Narrative Sentence",
            block, re.I,
        )
        if heading:
            name = re.sub(r"['’]s\b", "", heading.group(1).strip()).strip()
    if not name:
        # Boss sheets that omit "Character Name:" carry the name in the H-level
        # title ("##### 👾 A-RANK SYSTEMIC CALAMITY: ZARKOTH (THE SOUL-EATER)").
        heading = re.search(
            r"^#+\s*👾?\s*[A-Z]-Rank\s+SYSTEMIC\s+\w+:\s*([A-Za-z'’ ]+?)\s*\([^)]*\).*$",
            block, re.M | re.I,
        )
        if heading:
            name = heading.group(1).strip().title()
    data["name"] = name

    basic = grab("Basic")
    race = ""
    basic_race = re.search(r"^(?:Female|Male)[,;]\s*([A-Za-z]+(?:[ -][A-Za-z]+)*)", basic)
    if basic_race:
        race = basic_race.group(1).strip()
    race = race or grab("Race") or grab("Race / Species") or grab("Species")
    if race:
        race = re.sub(r"\s*\([^)]*\)\s*$", "", race).strip()
        race = _CITE_RE.sub("", race).strip()
    data["race"] = race

    rank = grab("Rank") or grab("Adventurer Rank") or grab("Power Bracket") or grab("Threat Bracket")
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
    reg = parse_registry_narrative_syntax(_strip_cites(md_text))
    if reg.get("structural_fault") or reg.get("sixth_guard"):
        return {k: _CITE_RE.sub("", v) for k, v in reg.items()}

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

    # Sixth Guard: boss inline bullet ("*   **The Sixth Guard Anchor (...):** <text>")
    # takes priority; otherwise the prose anchor paragraph under the 🛑 heading.
    anchor_m = re.search(
        r"The Sixth Guard Anchor[^\n:]*:\s*\**\s*(.+)", md_text, re.I
    )
    if anchor_m:
        sixth_guard = re.sub(r"\s+", " ", anchor_m.group(1)).strip().lstrip("* ")
    if not sixth_guard:
        anchor_m = re.search(
            r"Sixth Guard.*?\n\n(.+?)(?=\n\n|##\s|###\s|####\s|$)",
            md_text, re.S | re.I,
        )
        if anchor_m:
            sixth_guard = re.sub(r"\s+", " ", anchor_m.group(1)).strip().lstrip("* ")

    # Levers: three sections (Containment / Velocity / Defection). Two layouts:
    #  - registry "Individual Action Syntax Card": "Lever N: The <Name> Vector"
    #    with "**The Strategy:**" / "**The Action:**" bold bullets;
    #  - boss "PREDICATE" block: "Lever N: <Name> (...):" with indented
    #    "- Strategy:" / "- Action:" bullets.
    # Reduce each to "Name: <strategy sentence> <action sentence>".
    lever_names = ["Containment", "Velocity", "Defection"]
    lever_parts = []
    for name in lever_names:
        sec = None
        strat_re = r"\*\*The Strategy:?\*\*\s*(.+)"
        act_re = r"\*\*The Action:?\*\*\s*(.+)"
        pat1 = re.compile(
            rf"Lever\s*\d+\s*:\s*The\s+{name}\s+Vector.*?(?=\n####|\n###|\n##|\Z)",
            re.S | re.I,
        )
        pat2 = re.compile(
            rf"Lever\s*\d+\s*:\s*{name}\s*\([^)]*\)[^:]*:\s*\n((?:\s+-.*\n?)*)",
            re.S | re.I,
        )
        if pat1.search(md_text):
            sec = pat1.search(md_text).group(0)
        elif pat2.search(md_text):
            sec = pat2.search(md_text).group(1)
            strat_re = r"Strategy:\s*(.+)"
            act_re = r"Action:\s*(.+)"
        else:
            continue
        strategy = re.search(strat_re, sec, re.I)
        action = re.search(act_re, sec, re.I)
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
        "structural_fault": _CITE_RE.sub("", structural_fault),
        "sixth_guard": _CITE_RE.sub("", sixth_guard),
        "levers": _CITE_RE.sub("", levers),
    }


def parse_explicit_stats(md_text: str) -> dict:
    """Pull explicit numeric BESM stats from the registry-sheet stats table.

    The design-pass sheets carry a ``| **Body (B) Stat** | **4** |`` table (rows
    may be collapsed onto one physical line with ``||`` joins). Returns a dict
    with stat_body/mind/soul, acv, dcv, max_hp, max_ep, shock_value when the
    table is present and complete enough, else {}.
    """
    def _num_after(label_re: str) -> int | None:
        # Accepts both the registry-table form ("**Label** ... | **N**") and the
        # boss derived-metrics bullet form ("**Label:** **N**", colon inside the
        # bold), plus the optional " Stat" suffix on Body/Mind/Soul cells.
        for pat in (
            r"\*\*" + label_re + r":?\*\*[^|\n]*\|\s*\**(\d+)",
            r"\*\*" + label_re + r":?\*\*\s*\**(\d+)",
        ):
            m = re.search(pat, md_text)
            if m:
                try:
                    return int(m.group(1))
                except ValueError:
                    return None
        return None

    stats = {}
    body = _num_after(r"Body \(B\)(?: Stat)?")
    mind = _num_after(r"Mind \(M\)(?: Stat)?")
    soul = _num_after(r"Soul \(S\)(?: Stat)?")
    if body and mind and soul:
        stats.update(stat_body=body, stat_mind=mind, stat_soul=soul)
        # Prefer explicit derived values when present, else recompute from stats.
        acv = _num_after(r"Attack Combat Value \(ACV\)")
        dcv = _num_after(r"Defence Combat Value \(DCV\)")
        hp = _num_after(r"Health Points \(HP\)")
        ep = _num_after(r"Energy Points \(EP[^)]*\)")
        stats["acv"] = acv or (body + mind + soul) // 3
        stats["dcv"] = dcv or max(1, (body + mind + soul) // 3 - 2)
        stats["max_hp"] = hp or (body + soul) * 5
        stats["max_ep"] = ep or (mind + soul) * 5
        # Budget from the rank line's CP figure when present, else the boss
        # "Power Bracket: ... (250 CP Budget)" form, else ladder default.
        # Anchored to the rank line so attribute "(4 CP)" bundles don't get
        # mistaken for the character budget.
        budget = None
        rank_line = re.search(r"(?:Adventurer\s+)?Rank[^\n]*\([^\n]*\d+\s*CP", md_text, re.I)
        if rank_line:
            budget_m = re.search(r"\([^\n]*?(\d+)\s*CP", rank_line.group(0), re.I)
            budget = int(budget_m.group(1)) if budget_m else None
        if budget is None:
            rank_line = re.search(r"(?:Adventurer\s+)?Rank[^\n]*?(\d+)\s*CP", md_text, re.I)
            budget = int(rank_line.group(1)) if rank_line else None
        if budget is None:
            budget_m = re.search(r"(\d+)\s*CP\s*Budget", md_text, re.I)
            budget = int(budget_m.group(1)) if budget_m else None
        if budget is not None:
            stats["points_budget"] = budget
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
        _strip_cites(md_text), re.S | re.I,
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
            rf"Lever \d+:\s*{name}\s*\([^)]*\)[^:]*:\s*\n((?:\s+-.*\n?)*)",
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

    loadout = extract_loadout(md_text)

    payload = {
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
        "combat_techniques": loadout["combat_techniques"],
        "skills": loadout["skills"],
        "defects": loadout["defects"],
        "loadout_flags": loadout["flags"],
    }
    # Explicit shock only when the sheet declares one — omitting the key lets
    # upsert_character fall back to its computed default (None would store NULL).
    if loadout["shock_value"] is not None:
        payload["shock_value"] = loadout["shock_value"]
    return payload


def extract_file(path: str) -> list[dict]:
    """Parse a markdown file into one-or-more upsert payloads (handles pairs/trio)."""
    md_text = open(path, encoding="utf-8", errors="ignore").read()
    # Some vault sheets serialize newlines as literal "\n" escape sequences
    # (collapsing the whole sheet onto one physical line). Normalize so the
    # newline-delimited block / lever-bullet parsers behave.
    md_text = md_text.replace("\\n", "\n")
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


# ── loadout extraction (Combat Techniques / Skills / Defects / Shock) ────────
# The registry sheets author full, CP-priced BESM builds that the classic
# extractor dropped. These parsers lift them into the roster's loadout columns
# deterministically (no LLM). Two section vocabularies are supported:
# adventurer ("Combat Skills & Underbelly Payloads" / "Purchased Attributes") and
# boss ("ALIGNMENT & … ATTRIBUTE BUILD" / "SYSTEMIC FRICTION (DEFECTS)"). See
# changelog/proposals/2026-09-09-chronos-core-guild-loadout-pullover.md.

# CP-2: pure stat-budget modifiers already encoded in the sheets' explicit HP/EP.
PASSIVE_STAT_EXCLUSIONS = ["tough", "energised"]

# CP-3: Skill Groups don't name their governing stat on the sheet. Deterministic
# keyword map grounded in BESM Extras' "Relevant Stat" (official text, pp.22-29);
# anything unmatched falls back to Mind and is flagged in the dry run.
#   Medical p26 "Mind (sometimes Body)" · Military Sciences p27 "Mind"
#   Survival p29 "Mind (sometimes Body)" · Street Sense p29 "Mind or Soul"
#   Social Sciences p29 "Mind" · Domestic Arts p24 "Mind or Soul"
#   Artisan p22 "Average of Body and Soul" (single-stat pick: Soul)
#   Adventuring = Adventure Skills category (mixed; physical default: Body)
SKILL_STAT_MAP = {
    "adventuring": "stat_body",
    "medical": "stat_mind",
    "military": "stat_mind",
    "survival": "stat_mind",
    "street": "stat_mind",
    "social": "stat_mind",
    "domestic": "stat_soul",
    "artisan": "stat_soul",
    "sacred": "stat_soul",
    "pleading": "stat_soul",
    "academic": "stat_mind",
    "scientific": "stat_mind",
    "business": "stat_mind",
    "athletic": "stat_body",
    "combat": "stat_body",
    "craft": "stat_mind",
    "technical": "stat_mind",
}
DEFAULT_SKILL_STAT = "stat_mind"


def _skill_stat(group: str) -> tuple[str, bool]:
    """Resolve a skill-group label to a stat via the source-grounded map.

    Composite labels ("Social/Sacred", "Street/Survival") match on any
    component. Returns (stat, used_default) — Mind-defaults are flagged for the
    dry-run review so genuinely novel groups stay visible.
    """
    parts = [p.strip().lower() for p in re.split(r"[/+,&]", group) if p.strip()]
    for part in parts:
        if part in SKILL_STAT_MAP:
            return SKILL_STAT_MAP[part], False
    return DEFAULT_SKILL_STAT, True

# Anchored to heading lines so prose false-positives ("123 CP with Defects",
# "Attribute Build" mid-sentence) never start a section mid-file.
_TECH_START = re.compile(
    r"^#{1,6}[^\n]*(?:Combat Skills|Underbelly|Payload|Attribute Build|Attribute)",
    re.M | re.I,
)
_ATTR_START = re.compile(
    r"^#{1,6}[^\n]*(?:Purchased Attribute|Investment)", re.M | re.I
)
_DEFECT_START = re.compile(
    r"^#{1,6}[^\n]*(?:Defects|Friction)", re.M | re.I
)
_SECTION_STOPS = [
    re.compile(r"Individual Action Syntax Card", re.I),
    re.compile(r"DM Cheat", re.I),
    re.compile(r"GM Tactical|TACTICAL MANUAL", re.I),
    re.compile(r"^#{1,2}\s", re.M),
]
_ENTRY_RE = re.compile(r"^\s*\*+\s*\*\*(.+?)\*\*\s*(?::\s*|\*\*\s*)?(.*)$")
_SKILL_GROUP_RE = re.compile(r"Skill Group\s*\(([^)]*)\)", re.I)


def _section_text(md_text: str, start_re, extra_stops: list = None) -> str:
    """Slice the first section matching start_re, up to the EARLIEST next stop."""
    start = re.search(start_re, md_text)
    if not start:
        return ""
    s = start.end()
    best = None
    for stop in _SECTION_STOPS + (extra_stops or []):
        m = re.search(stop, md_text[s:])
        if m and (best is None or m.start() < best.start()):
            best = m
    if best:
        return md_text[s:s + best.start()]
    return md_text[s:]


def _loadout_entries(section: str) -> list[tuple[str, str]]:
    """Yield (bold_label, rest) for each bold-led bullet in a section.

    Continuation lines (indented sub-bullets, italic payload math) fold into the
    current entry's rest so the effect prose carries the full mechanical picture.
    """
    entries = []
    current = None
    for ln in section.splitlines():
        m = _ENTRY_RE.match(ln)
        if m:
            if current:
                entries.append(current)
            current = [m.group(1).strip(), m.group(2).strip()]
        elif current and (ln.startswith((" ", "\t", "*", "-"))):
            current[1] += " " + re.sub(r"^\s*\*+\s*", "", ln).strip()
    if current:
        entries.append(current)
    return entries


def _entry_level(bold: str, rest: str) -> tuple[int, str]:
    """Pull the numeric level from a bold label (Level/Rank N), defaulting to 1."""
    m = re.search(r"\b(?:Level|Rank)\s*(\d+)", bold)
    if m:
        return int(m.group(1)), re.sub(r"\s*(?:Level|Rank)\s*\d+\s*", " ", bold).strip(" :").strip()
    return 1, bold.strip(" :")


def _clean_prose(text: str) -> str:
    """Whitespace-collapse and strip cost/cite markers from effect/trigger prose."""
    text = re.sub(r"\[Cost:\s*[^\]]*\]", "", text)
    text = re.sub(r"\[Gain:\s*[^\]]*\]", "", text)
    text = re.sub(r"\(Returns\s*[^)]*\)", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = text.strip("-").strip("—").strip("-").strip()
    return re.sub(r"\s+\.\s*$", "", text).strip()


def extract_loadout(md_text: str) -> dict:
    """Deterministic loadout parse of a registry sheet.

    Returns the roster's four loadout fields plus a review ``flags`` list:
    combat_techniques, skills, defects, shock_value (explicit-over-derived), flags.
    Best-effort per section — a missing section yields empty fields + a flag,
    never a crash.
    """
    md_text = _strip_cites(md_text)
    flags = []
    techniques, skills, defects = [], [], []

    tech_section = _section_text(md_text, _TECH_START, [_ATTR_START, _DEFECT_START])
    attr_section = _section_text(md_text, _ATTR_START, [_DEFECT_START])
    for section in (tech_section, attr_section):
        for bold, rest in _loadout_entries(section):
            if _SKILL_GROUP_RE.search(bold):
                m = _SKILL_GROUP_RE.search(bold)
                group = m.group(1).strip()
                level, _ = _entry_level(bold, rest)
                stat, used_default = _skill_stat(group)
                if used_default:
                    flags.append(f"skill-default-stat:{group}")
                skills.append({
                    "name": f"Skill Group ({group})",
                    "rank": level,
                    "stat": stat,
                    "specialisation": _clean_prose(rest),
                })
                continue
            level, name = _entry_level(bold, rest)
            if name.lower() in PASSIVE_STAT_EXCLUSIONS:
                flags.append(f"excluded-passive:{name}")
                continue
            if name.lower() == "skill group":
                continue
            techniques.append({
                "name": re.sub(r"^Attribute:\s*", "", name).strip(" :"),
                "level": level,
                "effect": _clean_prose(rest),
            })

    defect_section = _section_text(md_text, _DEFECT_START)
    for bold, rest in _loadout_entries(defect_section):
        name = re.sub(r"^Attribute:\s*", "", bold)
        rank = 1
        m = re.search(r"\bRank\s*(\d+)", name)
        if m:
            rank = int(m.group(1))
            name = re.sub(r"\s*Rank\s*\d+\s*", " ", name).strip()
        cp = 0
        m2 = re.search(r"\[Gain:\s*-?\s*(\d+)\s*CP\]", rest) or re.search(
            r"\(Returns\s*\+\s*(\d+)\s*CP\)", rest
        )
        if m2:
            cp = int(m2.group(1))
        defects.append({
            "name": name.strip(" :"),
            "rank": rank,
            "cp": cp,
            "trigger": _clean_prose(rest),
        })

    # Explicit Shock Value from the stats table (explicit-over-derived).
    shock = None
    shock_m = re.search(
        r"\*\*Shock Value:?\*\*[^|\n]*\|\s*\**\s*(\d+)", md_text, re.I
    ) or re.search(r"\*\*Shock Value:?\*\*\s*\**\s*(\d+)", md_text, re.I)
    if shock_m:
        shock = int(shock_m.group(1))

    return {
        "combat_techniques": techniques,
        "skills": skills,
        "defects": defects,
        "shock_value": shock,
        "flags": flags,
    }
