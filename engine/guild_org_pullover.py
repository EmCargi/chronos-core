"""Deterministic Guild RPG organization (guild / faction) pullover extractor.

Parses the ``BESM Sheets/organizations/`` "Institutional Macro-Character" sheets
into ``upsert_organization()`` payloads WITHOUT an LLM. Organization sheets reuse
the exact Active Narrative Syntax layout of the region sheets (fenced YAML
``SUBJECT`` block + ``THE ANCHOR`` block + ``PREDICATE`` levers), so the NS
extraction is shared with ``engine.guild_region_pullover``.

Org-specific metadata (type / scale / leader / base) is read from the Basic block
and never collides with the NS fields.
"""

import re

from .guild_region_pullover import extract_narrative_syntax, _grab, _CITE_RE

# Canonical org filenames to ingest.
ORG_FILES = {
    "aelthar-keldor-org-sheet.md",
}

# Sub-sheets that are NOT standalone organizations.
SKIP_FILES: set[str] = set()


def _org_type(text: str) -> str:
    """Derive a normalized organization_type from the type label."""
    t = (text or "").lower()
    if "dark guild" in t:
        return "dark_guild"
    if "faction" in t:
        return "faction"
    if "order" in t:
        return "order"
    if "guild" in t:
        return "guild"
    return "organization"


def extract_metadata(md_text: str) -> dict:
    name = _grab(md_text, "Name")
    if name:
        name = _CITE_RE.sub("", name)
        name = re.sub(r"\s*\([^)]*\)\s*$", "", name).strip()
    otype = _grab(md_text, "Organization Type") or _grab(md_text, "Org Type")
    scale = (
        _grab(md_text, "Scale & Tier")
        or _grab(md_text, "Geopolitical Scale")
        or _grab(md_text, "Classification")
    )
    leader = _grab(md_text, "Leader")
    base = _grab(md_text, "Base of Operations") or _grab(md_text, "Headquarters")
    return {
        "name": name,
        "organization_type": _org_type(otype),
        "scale_tier": _CITE_RE.sub("", scale).strip(),
        "leader": _CITE_RE.sub("", leader).strip(),
        "base_of_operations": _CITE_RE.sub("", base).strip(),
    }


def extract_org(md_text: str, source_path: str = "") -> dict:
    """Compile an org markdown into an upsert_organization() payload."""
    md_text = md_text.replace("\\n", "\n")
    meta = extract_metadata(md_text)
    if not meta["name"]:
        raise ValueError("could not resolve organization name")
    # Orgs reuse the region NS layout verbatim.
    ns = extract_narrative_syntax(md_text)
    return {
        "name": meta["name"],
        "organization_type": meta["organization_type"],
        "scale_tier": meta["scale_tier"],
        "leader": meta["leader"],
        "base_of_operations": meta["base_of_operations"],
        "description": "",
        "structural_fault": ns["structural_fault"],
        "sixth_guard": ns["sixth_guard"],
        "levers": ns["levers"],
    }


def extract_file(path: str) -> list[dict]:
    md_text = open(path, encoding="utf-8", errors="ignore").read()
    try:
        return [extract_org(md_text, source_path=path)]
    except ValueError as e:
        return [{"error": str(e), "file": path}]
