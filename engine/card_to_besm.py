"""Deterministic BESM 4e sheet compiler for Shota x Monsters V2 character cards.

Turns a freeform SillyTavern V2 card's markdown description into a mechanical
roster row WITHOUT an LLM. Grounds every decision in the published conversion
material instead of model guesswork:

- Tier ladder & CP budgets: "shota_x_monsters_2_besm4e_plan.md" 5-Tier Monster
  Hierarchy (Tier 1: 25-45 CP ... Tier 5: 150-250+ CP).
- Stat ranks per tier: the beta bestiary's hand-built stat blocks (Slime 10
  ranks, Slime Prince 12, Goblin Leader 17, bosses ~30), grown sub-linearly the
  way JRPG HP explodes vs BESM's 2 CP/rank economy.
- Archetype distribution: the Guild RPG 5 foundational systemic templates
  (Frontline Defender, Evasive Striker, Arcane Artillery, Ranged Marksman,
  Divine Support).
- Stat caps: besm-character-creation power levels, clamped by CharacterSchema's
  1-12 rank bound.

The output "SYSTEM DATA" block is the same copy-pasteable canonical block
batch_ingest METHOD 1 already parses, so staged cards flow through the existing
authoritative pipeline untouched.
"""

import re


# Tier detection is keyed off the game's own HP stat (the honest difficulty
# ladder). Brackets chosen so the observed SxM1 distribution falls cleanly:
# goblins/slimes/bee spirits < 260, mid-foes to 800, leaders to 2600,
# stratum generals to 9000, bosses/archdemons above.
TIER_HP_BRACKETS = [
    (260, 1, 35, 10, 7),    # Tier 1: 25-45 CP, Human power level
    (800, 2, 57, 12, 9),    # Tier 2: 50-65 CP, Adventurer
    (2600, 3, 82, 17, 12),  # Tier 3: 70-95 CP, Heroic
    (9000, 4, 120, 23, 12), # Tier 4: 100-140 CP, Mythical
    (float("inf"), 5, 200, 30, 12),  # Tier 5: 150-250+ CP, Superhuman+
]

ARCHETYPES = {
    "Frontline Defender": {"Body": 0.45, "Mind": 0.20, "Soul": 0.35},
    "Evasive Striker": {"Body": 0.40, "Mind": 0.35, "Soul": 0.25},
    "Arcane Artillery": {"Body": 0.15, "Mind": 0.55, "Soul": 0.30},
    "Ranged Marksman": {"Body": 0.35, "Mind": 0.40, "Soul": 0.25},
    "Divine Support": {"Body": 0.20, "Mind": 0.30, "Soul": 0.50},
    "Balanced": {"Body": 0.35, "Mind": 0.30, "Soul": 0.35},
}

ARCHETYPE_ORDER = [
    "Frontline Defender", "Divine Support", "Arcane Artillery",
    "Ranged Marksman", "Evasive Striker", "Balanced",
]

ARCHETYPE_KEYWORDS = {
    "Frontline Defender": [
        "tank", "bodyguard", "defensive", "defender", "shield", "armor",
        "armour", "absorb", "protect", "frontline", "front-line", "block",
        "guard", "interpose", "meatshield", "bunker",
    ],
    "Evasive Striker": [
        "striker", "skirmish", "hit-and-run", "hit & run", "melee", "brawler",
        "close-range", "assault", "berserk", "counter", "flurry", "ambush",
        "rapid", "agile", "evasion", "evasive", "mobility", "speed", "blitz",
    ],
    "Arcane Artillery": [
        "magic", "mage", "caster", "spell", "elemental", "sorcer", "arcane",
        "dark magic", "dark-type", "necromanc", "curse", "blasting",
        "channel", "incant", "witch", "wizard", "void",
    ],
    "Ranged Marksman": [
        "ranged", "archer", "sniper", "marksman", "long-range", "long range",
        "projec", "aerial", "flying", "shooter", "distance", "bow", "arrow",
    ],
    "Divine Support": [
        "support", "healer", "healing", "heal", "buff", "reviv", "regenerat",
        "crowd control", "debuff", "utility", "drain", "life steal",
        "manipulat", "disable", "control", "ward", "bless",
    ],
}


def get_combat_profile_table(description: str) -> str:
    """Return the Combat Profile region of a card description ('' if absent)."""
    m = re.search(r"\*\*Combat Profile:?\*\*\s*(.*?)(?=\n\*\*|\Z)", description, re.DOTALL)
    return m.group(1).strip() if m else ""


def extract_game_hp(description: str) -> int:
    """Parse the game HP out of a card's Combat Profile markdown table.

    Handles both the row layout (`| HP | 23 |`) and the four-column layout
    (`| HP | MP | Exp | Gold |`). Returns 0 when no HP row is found.
    """
    table = get_combat_profile_table(description)
    if not table or "No stats" in table or "no stats" in table.lower():
        return 0
    row = re.search(r"\|\s*HP\s*\|\s*(\d+)\s*\|", table)
    if row:
        return int(row.group(1))
    col = re.search(r"\|\s*(\d+)\s*\|\s*(\d+)\s*\|", table)
    if col:
        return int(col.group(1))
    return 0


def detect_tier(description: str) -> tuple:
    """Map a card description to (tier, points_budget, stat_ranks, stat_cap)."""
    hp = extract_game_hp(description)
    for hp_max, tier, budget, ranks, cap in TIER_HP_BRACKETS:
        if hp <= hp_max:
            return tier, budget, ranks, min(cap, 12)
    return 5, 200, 30, 12


def classify_archetype(description: str) -> str:
    """Keyword-score the Combat Role text against the 5 systemic templates.

    Highest keyword hit wins; ties break in ARCHETYPE_ORDER (defender/support
    before striker/balanced for hybrid tags like "Support/tank hybrid").
    Returns 'Balanced' when no role text is present.
    """
    role_m = re.search(r"\*\*Combat Role:?\*\*\s*(.*)", description)
    role = role_m.group(1).lower() if role_m else ""
    if not role:
        return "Balanced"
    scores = {
        name: sum(1 for kw in kws if kw in role)
        for name, kws in ARCHETYPE_KEYWORDS.items()
    }
    best = max(scores, key=lambda n: (scores[n], -ARCHETYPE_ORDER.index(n)))
    if scores[best] == 0:
        return "Balanced"
    return best


def allocate_stats(archetype: str, stat_ranks: int, stat_cap: int) -> tuple:
    """Distribute BESM stat ranks across Body/Mind/Soul by archetype weights.

    Starts every stat at 1 (BESM minimum), then feeds the remaining ranks into
    the archetype's weighted priority order until the pool or the power-level
    cap is exhausted. Pure, deterministic, order-stable.
    """
    weights = ARCHETYPES.get(archetype, ARCHETYPES["Balanced"])
    stats = {"Body": 1, "Mind": 1, "Soul": 1}
    remaining = max(0, stat_ranks - 3)
    order = sorted(weights, key=lambda s: -weights[s])
    while remaining > 0:
        moved = False
        for stat in order:
            if remaining <= 0:
                break
            if stats[stat] < stat_cap:
                stats[stat] += 1
                remaining -= 1
                moved = True
        if not moved:
            break
    return stats["Body"], stats["Mind"], stats["Soul"]


def derive_acv(body: int, mind: int, soul: int) -> int:
    """BESM Combat Value: (Body + Mind + Soul) // 3."""
    return (body + mind + soul) // 3


def build_system_data_block(name: str, description: str,
                            race: str = "Unknown") -> dict:
    """Compile a card description into a canonical BESM SYSTEM DATA block.

    Returns a dict matching batch_ingest's METHOD 1 contract AND the dense
    [SYSTEM DATA: BESM 4E MECHANICS] text block for card injection:
      tier, points_budget, stat_body/mind/soul, acv, dcv, max_hp, max_ep,
      rank_label, race, system_data (the printable block).
    """
    tier, budget, ranks, cap = detect_tier(description)
    archetype = classify_archetype(description)
    body, mind, soul = allocate_stats(archetype, ranks, cap)
    max_hp = (body + soul) * 5
    max_ep = (mind + soul) * 5
    acv = derive_acv(body, mind, soul)
    dcv = max(1, acv - 2)

    block = (
        "[SYSTEM DATA: BESM 4E MECHANICS]\n"
        f"[Setting: shota_x_monsters]\n"
        f"[Rank: Tier {tier}]\n"
        f"[Points Budget: {budget} / {budget} CP]\n"
        f"[Stats: Body {body}, Mind {mind}, Soul {soul}]\n"
        f"[Combat Values: ACV {acv}, DCV {dcv}. HP {max_hp}. EP {max_ep}.]\n"
    )
    return {
        "name": name,
        "tier": tier,
        "points_budget": budget,
        "rank_label": f"Tier {tier}",
        "race": race or "Unknown",
        "archetype": archetype,
        "stat_body": body,
        "stat_mind": mind,
        "stat_soul": soul,
        "acv": acv,
        "dcv": dcv,
        "max_hp": max_hp,
        "max_ep": max_ep,
        "system_block": block,
    }