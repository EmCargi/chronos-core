"""Deterministic Guild RPG region/macro-location pullover extractor.

Parses the ``BESM Sheets/regions/`` "Macro-Character" sheets into
``upsert_location()`` payloads WITHOUT an LLM. Region sheets are a distinct
layout from the adventurer/boss sheets:

- Metadata lives in a "Geopolitical Profile" block (``**Name:**``,
  ``**Scale & Tier:**`` / ``**Geopolitical Scale:**`` / ``**Classification:**``).
- The Active Narrative Syntax sits in a fenced ``yaml`` ``SUBJECT`` block
  (``Structural Fault:`` / ``(The_)?Grand_Guard:`` bullets) and prose lever
  sections. Capital uses the registry-card lever style (``**The Strategy:**``
  bullets); the other regions use the boss "PREDICATE" style
  (``- Strategy:`` / ``- Action:`` indented bullets, sometimes with a
  ``[cite: N]`` inside the lever header itself).
- Some vault sheets serialize newlines as literal ``\\n`` escapes; normalize.

Regions whose names already exist as seeded atlas rows (The Capital City,
Inewell, Srurpolis) are upgraded in place by the ingest's canon-upsert mode.
"""

import re

from .guild_pullover import _CITE_RE, _strip_cites

# Canonical region filenames to ingest; the rest of the regions/ folder holds
# the Guild, the World lore, and a methods doc that are not locations.
REGION_FILES = {
    "capital-region-sheet.md",
    "inewell-region-sheet.md",
    "srurpolis-region-sheet.md",
    "vardun-wood-region-sheet.md",
}

# Sub-sheets that are NOT standalone locations.
SKIP_FILES = {
    "aelthar-keldor-guild-sheet.md",   # the Guild macro-character
    "guild-rpg-world-lore.md",          # the World macro-character
    "methods-of-play.md",               # design doc, not an entity
}


def _grab(md_text: str, label: str) -> str:
    """Tolerant label grab: '### Name: X' / '- Name: X' / '*  **Name:** X'."""
    m = re.search(
        rf"^#*\s*-?\s*\*+\s*\*?\*?\s*{label}\s*:\s*(.+)$", md_text, re.M
    ) or re.search(
        rf"^#*\s*-?\s*{label}\s*:\s*(.+)$", md_text, re.M
    )
    if not m:
        return ""
    return re.sub(r"^\s*\*+\s*", "", m.group(1)).strip()


def _location_type(scale_text: str) -> str:
    """Derive a roster location_type from the Scale / Tier / Classification line."""
    s = (scale_text or "").lower()
    if "metropolis" in s or "capital" in s:
        return "capital"
    if "city-state" in s or "citadel" in s or "city" in s:
        return "city"
    if "kingdom" in s:
        return "kingdom"
    if "region" in s or "wood" in s or "wastes" in s:
        return "region"
    return "settlement"


def extract_metadata(md_text: str) -> dict:
    name = _grab(md_text, "Name")
    if name:
        name = _CITE_RE.sub("", name)
        name = re.sub(r"\s*\([^)]*\)\s*$", "", name).strip()
    scale = (
        _grab(md_text, "Scale & Tier")
        or _grab(md_text, "Geopolitical Scale")
        or _grab(md_text, "Classification")
    )
    # The Rank Bracket line (e.g. "SS-Rank Sovereign City-State") carries the
    # city/region signal that the Geopolitical Scale line sometimes omits.
    rank_bracket = _grab(md_text, "Rank Bracket")
    # A short human label for the type column.
    ltype = _location_type(f"{scale} {rank_bracket}")
    # Geometry / subject description from the YAML SUBJECT block.
    geom = ""
    geom_m = re.search(
        r"(?:Regional_Geometry|Arena Geometry)\s*:\s*[\"']?(.*?)[\"']?\s*(?:\n|$)",
        md_text, re.I,
    )
    if geom_m:
        geom = geom_m.group(1).strip().strip('"').strip()
    return {
        "name": name,
        "location_type": ltype,
        "scale_text": _CITE_RE.sub("", scale).strip(),
        "description": _CITE_RE.sub("", geom).strip(),
    }


def extract_narrative_syntax(md_text: str) -> dict:
    """Pull structural_fault / sixth_guard / levers from a region sheet."""
    text = _strip_cites(md_text)

    # --- Structural Fault: YAML bullet/key, else prose heading. ---
    sf = ""
    sf_m = re.search(
        r"Structural[\s_]*Fault\s*:\s*[\"']?(.*?)[\"']?\s*(?:\n|$)", text, re.I
    )
    if not sf_m:
        sf_m = re.search(r"The Structural Fault[^\n:]*:\s*(.+)", text, re.I)
    if sf_m:
        sf = sf_m.group(1).replace('"', '').strip()

    # --- Sixth Guard / Grand Guard anchor. ---
    # Capital style: inline "The Anchor: The Grand Guard (LABEL)". Non-capital
    # style: a "THE ANCHOR (The Grand Guard):" block of bullets (Sovereign
    # Anchor / Failure Trigger / Systemic Collapse / Primary Defense).
    sg = ""
    anchor_block = re.search(
        r"THE ANCHOR[^\n:]*:\s*\n(.*?)(?=\n#{2,4}\s|\n######|\Z)", text, re.I | re.S
    )
    if anchor_block:
        block = anchor_block.group(1)
        parts = []
        for key in ("Sovereign Anchor", "Failure Trigger", "Systemic Collapse",
                    "Primary Defense"):
            km = re.search(rf"-\s*{key}\s*:\s*(.+)", block, re.I)
            if km:
                parts.append(f"{key}: {km.group(1).strip()}")
        if parts:
            sg = " ".join(parts)
    if not sg:
        anchor_label = re.search(r"The Anchor[^\n:]*:\s*(.+)", text, re.I)
        if anchor_label:
            sg = re.sub(r"\s+", " ", anchor_label.group(1)).strip().lstrip("* ")
    if not sg:
        # Fallback: the short YAML guard phrase.
        g = re.search(
            r"(?:The_)?(?:Grand_Guard|Sixth_Guard)\s*:\s*[\"']?(.*?)[\"']?\s*(?:\n|$)",
            text, re.I,
        )
        if g:
            sg = g.group(1).replace('"', '').strip()

    # --- Levers: Containment / Velocity / Defection. ---
    lever_parts = []
    for name in ("Containment", "Velocity", "Defection"):
        sec = None
        strat_re = r"\*\*The Strategy:?\*\*\s*(.+)"
        act_re = r"\*\*The Action:?\*\*\s*(.+)"
        # Format 1 (Capital): "Lever N: The <Name> Vector" + **The Strategy:**.
        p1 = re.compile(
            rf"Lever\s*\d+\s*:\s*The\s+{name}\s+Vector.*?(?=\n####|\n###|\n##|\Z)",
            re.S | re.I,
        )
        # Format 2 (others): "Lever N: <Name> (...):" + "- Strategy:" bullets.
        # The optional "(...)" may carry a "[cite: N]" before the trailing colon,
        # so consume the rest of the header line before capturing the block.
        p2 = re.compile(
            rf"Lever\s*\d+\s*:\s*{name}\s*(?:\([^)]*\))?.*?\n(.*?)(?=\n#{2,4}\s|\nLever\s*\d+|\Z)",
            re.S | re.I,
        )
        if p1.search(text):
            sec = p1.search(text).group(0)
        elif p2.search(text):
            sec = p2.search(text).group(1)
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
    levers = " ".join(lever_parts)

    return {
        "structural_fault": _CITE_RE.sub("", sf),
        "sixth_guard": _CITE_RE.sub("", sg),
        "levers": _CITE_RE.sub("", levers),
    }


def extract_region(md_text: str, source_path: str = "") -> dict:
    """Compile a region markdown into an upsert_location() payload."""
    md_text = md_text.replace("\\n", "\n")
    meta = extract_metadata(md_text)
    if not meta["name"]:
        raise ValueError("could not resolve region name")
    ns = extract_narrative_syntax(md_text)
    return {
        "name": meta["name"],
        "location_type": meta["location_type"],
        "region": "",
        "description": meta["description"],
        "travel_from_capital": "",
        "notes": meta["scale_text"],
        "structural_fault": ns["structural_fault"],
        "sixth_guard": ns["sixth_guard"],
        "levers": ns["levers"],
    }


def extract_file(path: str) -> list[dict]:
    md_text = open(path, encoding="utf-8", errors="ignore").read()
    try:
        return [extract_region(md_text, source_path=path)]
    except ValueError as e:
        return [{"error": str(e), "file": path}]
