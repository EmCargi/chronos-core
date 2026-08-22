"""Deterministic SxM1 Bestiary pullover extractor.

Parses the canonical SxM1 stat-block pages in
``shota-monsters-digital-dm/sxm1-besm-folder/Bestiary/*.md`` into
``upsert_character()`` payloads WITHOUT an LLM. Each page carries explicit
BESM stats (Body/Mind/Soul/CV/HP/EP/CP) plus a verbatim Tamer's Memo, so this
is a direct, deterministic compile — no rank-ladder derivation needed.

Mirrors the Guild RPG pullover (`guild_pullover.py`) in spirit and shape, but
the SxM1 source is higher-fidelity: numeric stats are explicit in the markdown,
so they are used verbatim, with formula fallbacks only when a field is absent
(Guild's explicit-over-derived precedence).

Skip policy (per design-pass ruling 2026-08-21):
- ``data-sparse`` tag anywhere in the page (the ~23 Fifth-Stratum SxM2-only
  bosses with no SxM1 stats) -> skipped, reason logged.
- Missing/incomplete BESM stat block (no Body/Mind/Soul rows) -> skipped.
- Duplicate source name -> second occurrence skipped.

No DB writes happen here. The dry-run CLI (`sxm1_pullover_dryrun.py`) reviews
the sweep; the actual ingest (Phase 2) wires these payloads in behind a
safe-ingest guard so the 94 existing card-derived rows are not clobbered.
"""

import json
import os
import re

SETTING_ID = "shota_x_monsters"

# Bestiary Tier label -> (roster rank_label, canonical CP). The explicit CP
# Budget row in the stat block takes precedence when present; this map is the
# fallback + the human-readable label. (Design-pass ruling #4.)
TIER_MAP = {
    "common mob": ("Mob", 25),
    "area leader": ("Leader", 60),
    "area boss": ("Boss", 120),
}


def _stat_int(md_text: str, label: str) -> int | None:
    """Pull an integer from a `| **Label** | N | ...` stat-block row."""
    m = re.search(rf"\|\s*\*\*{label}\*\*\s*\|\s*(\d+)", md_text)
    return int(m.group(1)) if m else None


def _title(md_text: str) -> str:
    m = re.search(r"^#\s+(.+)$", md_text, re.M)
    return m.group(1).strip() if m else ""


def _tier_text(md_text: str) -> str:
    m = re.search(r"\*\*Tier:\*\*\s*([^\n]+)", md_text)
    return m.group(1).strip() if m else ""


def _resolve_rank(tier_text: str, explicit_cp: int | None) -> tuple[str, int]:
    """Return (rank_label, points_budget) from the Tier label + table CP."""
    low = tier_text.lower()
    for key, (label, cp) in TIER_MAP.items():
        if key in low:
            return label, explicit_cp or cp
    return "Unknown", explicit_cp or 25


def _parse_memo(md_text: str) -> str:
    """Capture the verbatim Tamer's Memo block (blockquote lines)."""
    m = re.search(r"##\s*📖\s*Monster Memo\s*\n(.*?)(?=\n##\s|\Z)", md_text, re.S)
    if not m:
        return ""
    block = m.group(1)
    lines = [ln.lstrip("> ").strip() for ln in block.splitlines() if ln.strip().startswith(">")]
    return "\n".join(lines).strip()


def parse_stat_block(md_text: str) -> dict:
    """Extract explicit stats with formula fallbacks (design-pass ruling #2).

    Supports both Bestiary layouts:
    - two-column: ``| **Body** | 4 | **Mind** | 2 | ...`` (CP in a ``CP Budget`` row)
    - compact single-row: ``| Body 5 | Mind 2 | Soul 4 | CV 4 | HP 45 | EP 25 |``
      (CP in the heading, e.g. ``## BESM Stat Block (25 CP)``)

    Explicit HP/EP/CV win; missing values fall back to standard BESM math so a
    partially-populated table still yields a complete payload.
    """
    body = _stat_int(md_text, "Body")
    mind = _stat_int(md_text, "Mind")
    soul = _stat_int(md_text, "Soul")
    cv = hp = ep = None

    # Compact single-row layout: | Body 5 | Mind 2 | Soul 4 | CV 4 | HP 45 | EP 25 |
    if body is None or mind is None or soul is None:
        compact = re.search(
            r"\|\s*Body\s+(\d+)\s*\|\s*Mind\s+(\d+)\s*\|\s*Soul\s+(\d+)\s*\|"
            r"\s*CV\s+(\d+)\s*\|\s*HP\s+(\d+)\s*\|\s*EP\s+(\d+)\s*\|",
            md_text,
        )
        if compact:
            body, mind, soul, cv, hp, ep = (int(x) for x in compact.groups())
        if body is None or mind is None or soul is None:
            return {}

    # Two-column overrides take precedence only when actually present.
    cv2 = _stat_int(md_text, "CV")
    if cv2 is not None:
        cv = cv2
    hp2 = _stat_int(md_text, "HP")
    if hp2 is not None:
        hp = hp2
    ep2 = _stat_int(md_text, "EP")
    if ep2 is not None:
        ep = ep2

    cp = _stat_int(md_text, "CP Budget")
    # Compact layout carries CP in the heading, not a table row.
    if cp is None:
        cp_h = re.search(r"Stat Block\s*\((\d+)\s*CP\)", md_text, re.I)
        if cp_h:
            cp = int(cp_h.group(1))

    acv = cv if cv is not None else (body + mind + soul) // 3
    dcv = (cv - 2) if cv is not None else max(1, acv - 2)
    max_hp = hp if hp is not None else (body + soul) * 5
    max_ep = ep if ep is not None else (mind + soul) * 5

    return {
        "stat_body": body,
        "stat_mind": mind,
        "stat_soul": soul,
        "acv": acv,
        "dcv": dcv,
        "max_hp": max_hp,
        "max_ep": max_ep,
        "points_budget": cp,
    }


def synthesize_card(name: str, character: dict, memo: str, tier: str) -> str:
    """Build a SillyTavern V2 card_json envelope (design-pass ruling #3)."""
    sd = (
        "[SYSTEM DATA: BESM 4E MECHANICS]\n"
        f"[Setting: {SETTING_ID}]\n"
        f"[Tier: {tier or 'Unknown'}]\n"
        f"[Points Budget: {character['points_budget']} / {character['points_budget']} CP]\n"
        f"[Stats: Body {character['stat_body']}, Mind {character['stat_mind']}, "
        f"Soul {character['stat_soul']}]\n"
        f"[Combat Values: ACV {character['acv']}, DCV {character['dcv']}. "
        f"HP {character['max_hp']}. EP {character['max_ep']}.]\n"
    )
    desc = (
        f"{sd}\n{name} — SxM1 bestiary entry (sxm1-besm-folder).\n\n"
        f"Monster Memo:\n{memo}\n"
    )
    card = {
        "spec": "chara_card_v2",
        "data": {
            "name": name,
            "description": desc,
            "creator_notes": memo,
            "creator": "sxm1-besm-folder",
            "tags": ["SxM1", "monster", tier or ""],
        },
    }
    return json.dumps(card, ensure_ascii=False)


def extract_character(md_text: str, source_path: str = "") -> dict:
    """Compile one Bestiary page into an upsert_character payload.

    Returns a dict with a ``skip`` key (reason string) when the page should not
    be ingested; otherwise a full roster-row payload including a ``card_json``
    string. Never raises — skip reasons are first-class so the dry run can log
    every excluded page with its exact cause (design-pass ruling #1).
    """
    name = _title(md_text)
    if not name:
        return {"name": os.path.basename(source_path), "skip": "no title heading"}

    # Ruling #1: data-sparse (SxM2-only bosses) -> explicit skip.
    if "data-sparse" in md_text.lower():
        return {"name": name, "skip": "data-sparse (SxM2-only, no SxM1 stats)"}

    stats = parse_stat_block(md_text)
    if not stats:
        return {"name": name, "skip": "missing/incomplete BESM stat block (no Body/Mind/Soul)"}

    tier = _tier_text(md_text)
    rank_label, points_budget = _resolve_rank(tier, stats.get("points_budget"))
    memo = _parse_memo(md_text)

    character = {
        "name": name,
        "rank_label": rank_label,
        "race": "Monster",
        "points_budget": points_budget,
        "stat_body": stats["stat_body"],
        "stat_mind": stats["stat_mind"],
        "stat_soul": stats["stat_soul"],
        "acv": stats["acv"],
        "dcv": stats["dcv"],
        "max_hp": stats["max_hp"],
        "max_ep": stats["max_ep"],
        "sixth_guard": "",
        "structural_fault": "",
        "levers": "",
        "combat_techniques": [],
        "skills": [],
        "defects": [],
        "monster_memo": memo,
    }
    character["card_json"] = synthesize_card(name, character, memo, tier)
    return character


def extract_file(path: str, seen: set | None = None) -> list[dict]:
    """Parse a Bestiary markdown file into one payload (with dedupe)."""
    seen = seen if seen is not None else set()
    md_text = open(path, encoding="utf-8", errors="ignore").read()
    payload = extract_character(md_text, source_path=path)
    if "skip" not in payload:
        if payload["name"] in seen:
            return [{"name": payload["name"], "skip": "duplicate source name"}]
        seen.add(payload["name"])
    return [payload]
