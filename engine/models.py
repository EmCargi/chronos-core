from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
import random

class CharacterSchema(BaseModel):
    name: str
    gender: str = ""
    race: str = ""
    points_budget: int = 75
    stat_body: int = Field(..., ge=1, le=12)
    stat_mind: int = Field(..., ge=1, le=12)
    stat_soul: int = Field(..., ge=1, le=12)
    current_hp: Optional[int] = None
    current_ep: Optional[int] = None

    # BESM rules fields — populated from roster DB at runtime
    shock_value: int = 0
    combat_techniques: List[Dict[str, Any]] = []
    skills: List[Dict[str, Any]] = []
    defects: List[Dict[str, Any]] = []
    spellbook: List[Dict[str, Any]] = []

    @property
    def max_hp(self) -> int:
        return (self.stat_body + self.stat_soul) * 5

    @property
    def max_ep(self) -> int:
        return (self.stat_mind + self.stat_soul) * 5

    @property
    def base_acv(self) -> int:
        return (self.stat_body + self.stat_mind + self.stat_soul) // 3

    @property
    def base_dcv(self) -> int:
        return self.base_acv - 2

    @property
    def shock_value_computed(self) -> int:
        """Recompute from base HP + Hardboiled techniques."""
        base_sv = self.max_hp // 5
        hardboiled = sum(10 * t.get("level", 1) for t in self.combat_techniques
                         if isinstance(t, dict) and t.get("name", "").lower() == "hardboiled")
        return min(base_sv + hardboiled, self.max_hp // 2)

class NodeSchema(BaseModel):
    node_id: str
    title: str
    description: str
    exits: Dict[str, str]
    required_check: Optional[Dict[str, Any]] = None

def execute_action_check(stat_rank: int, skill_rank: int, difficulty_value: int) -> dict:
    """
    Rolls 2d6 cleanly using python's random.randint(1, 6).
    Calculates total: roll_sum + stat_rank + skill_rank.
    Returns a dictionary tracking success status and details.
    """
    die1 = random.randint(1, 6)
    die2 = random.randint(1, 6)
    roll_sum = die1 + die2
    total = roll_sum + stat_rank + skill_rank
    success = total >= difficulty_value
    return {
        "success": success,
        "roll": roll_sum,
        "total": total,
        "target": difficulty_value
    }


# ── obstacle dice, edge dice & resistance ────────────────────────────────

def _roll_with_obstacle(stat: int, target: int, minor: bool = False, major: bool = False) -> dict:
    """Roll 2d6 + stat vs target. Minor/Major obstacles add extra dice, keep lowest 2.
    Two minors compound into one major (BESM modifier rules)."""
    if minor and major:
        major = True
        minor = False
    if minor:
        dice = sorted(random.randint(1, 6) for _ in range(3))
        dice = dice[:2]
    elif major:
        dice = sorted(random.randint(1, 6) for _ in range(4))
        dice = dice[:2]
    elif minor and minor:
        pass
    else:
        dice = [random.randint(1, 6), random.randint(1, 6)]
    roll_sum = sum(dice)
    total = roll_sum + stat
    return {
        "success": total >= target,
        "roll": roll_sum,
        "total": total,
        "target": target,
        "obstacle": "minor" if minor else ("major" if major else None),
    }


def _roll_with_edge(stat: int, target: int, minor: bool = False, major: bool = False) -> dict:
    """Roll 2d6 + stat vs target. Minor/Major edges add extra dice, keep highest 2.
    Mirror of _roll_with_obstacle. Two minors compound into one major."""
    if minor and major:
        major = True
        minor = False
    if minor:
        dice = sorted((random.randint(1, 6) for _ in range(3)), reverse=True)
        dice = dice[:2]
    elif major:
        dice = sorted((random.randint(1, 6) for _ in range(4)), reverse=True)
        dice = dice[:2]
    else:
        dice = [random.randint(1, 6), random.randint(1, 6)]
    roll_sum = sum(dice)
    total = roll_sum + stat
    return {
        "success": total >= target,
        "roll": roll_sum,
        "total": total,
        "target": target,
        "edge": "minor" if minor else ("major" if major else None),
    }


def resistance_check(stat: int, target: int,
                     minor_obstacle: bool = False,
                     major_obstacle: bool = False) -> dict:
    """Generic Body/Soul resistance roll: 2d6 + stat ≥ target, with optional obstacle dice.
    Returns success, roll, total, target, obstacle, margin (TN − total on fail)."""
    result = _roll_with_obstacle(stat, target, minor=minor_obstacle, major=major_obstacle)
    result["margin"] = max(0, target - result["total"]) if not result["success"] else 0
    return result


# ── shock & knockout ────────────────────────────────────────────────────

def check_shock(character, damage_taken: int) -> dict:
    """BESM 4e Shock Check (§4.3): if damage ≥ SV, roll Soul vs TN 12 (standard)
    or TN 18 (severe, damage ≥ 2×SV). Failure = stunned or unconscious.

    Returns status_key (None/shocked/unconscious/knockout) and durations."""
    sv = character.shock_value_computed
    if damage_taken < sv:
        return {"triggered": False, "status_key": None}

    severe = damage_taken >= sv * 2
    target = 18 if severe else 12
    result = resistance_check(character.stat_soul, target)

    if result["success"]:
        return {
            "triggered": True, "severity": "severe" if severe else "standard",
            "status_key": None, **result,
        }

    knocked_out = result["margin"] > character.stat_soul
    if knocked_out:
        rounds = max(1, 8 - character.stat_body)
        return {
            "triggered": True, "severity": "severe" if severe else "standard",
            "status_key": "unconscious", "unconscious_rounds": rounds, **result,
        }
    return {
        "triggered": True, "severity": "severe" if severe else "standard",
        "status_key": "shocked", "stunned": True, **result,
    }


# ── incapacitation (sleep, paralysis, petrifaction) ─────────────────────

def check_incapacitation(character, obstacle: str = "none") -> dict:
    """BESM Incapacitating Enhancement: opposed Body/Soul (whichever higher)
    roll to resist sleep, paralysis, or petrifaction. Obstacle level varies
    by enhancement assignment (2=minor, 4=major)."""
    stat = max(character.stat_body, character.stat_soul)
    minor = obstacle == "minor"
    major = obstacle == "major"
    return resistance_check(stat, 12, minor_obstacle=minor, major_obstacle=major)


# ── poison resistance ───────────────────────────────────────────────────

POISON_TARGETS = {1: 12, 2: 15, 3: 18}

def check_poison_resistance(character, blight_level: int = 1) -> dict:
    """BESM Blight check: Body Stat roll vs TN 12/15/18 per Blight level.
    Pass → damage reduced to 20%. Fail → full damage. Immutable +2/level not
    yet wired (character has no immutable field)."""
    target = POISON_TARGETS.get(blight_level, 12)
    result = resistance_check(character.stat_body, target)
    result["blight_level"] = blight_level
    result["damage_multiplier"] = 0.2 if result["success"] else 1.0
    return result


# ── status ailments (Extras ledger: delivery vectors, decay, cognitive) ──

POISON_VECTORS = {
    "injury":   {"armour_blocked": True,  "ingested_multiplier": 1.0, "note": "blocked by AR/Force Field absorbing all damage"},
    "contact":  {"armour_blocked": False, "ingested_multiplier": 1.0, "note": "ignores AR unless airtight full-body coverage"},
    "ingested": {"armour_blocked": False, "ingested_multiplier": 2.0, "note": "damage doubled on ingestion"},
    "inhaled":  {"armour_blocked": False, "ingested_multiplier": 1.0, "note": "area effect; gas masks/airtight grant immunity"},
}

# Continuing-decay survival checks: hourly → Major Obstacle, daily → Minor
DECAY_CHECK_TN = 15


def resolve_poison_delivery(vector: str, damage: int,
                            target_ar: int = 0, force_field: int = 0,
                            has_gas_mask: bool = False) -> dict:
    """Resolve a poison's delivery vector (Extras pp.259-261).

    Returns whether the poison got through, the damage actually applied (raw
    × 2 for ingested), and the immunity/blocking rationale."""
    spec = POISON_VECTORS.get(vector.lower())
    if not spec:
        return {"valid": False, "reason": f"unknown vector '{vector}'",
                "applies": False, "damage": 0}
    if vector == "injury" and (target_ar >= damage or force_field >= damage):
        return {"valid": True, "applies": False, "damage": 0,
                "reason": "armour/force field absorbed the full blow"}
    if vector == "inhaled" and has_gas_mask:
        return {"valid": True, "applies": False, "damage": 0,
                "reason": "gas mask / airtight immunity"}
    applied = int(damage * spec["ingested_multiplier"])
    return {"valid": True, "applies": True, "damage": applied,
            "reason": spec["note"]}


def continuing_poison_tick(original_damage: int, assignments: int) -> dict:
    """Continuing Enhancement tick: at end of each round, victim loses
    20% of the original damage. Lasts 1 round per assignment. AR gives zero
    protection against the recurring damage."""
    return {
        "tick_damage": max(1, original_damage // 5),
        "rounds_remaining_after_tick": max(0, assignments - 1),
        "armour_protected": False,
    }


def decay_survival_check(stat_body: int, interval: str) -> dict:
    """Slow-acting poison/disease survival check: TN 15 Body roll with an
    obstacle per interval — hourly → Major Obstacle, daily → Minor."""
    major = interval == "hourly"
    minor = interval == "daily"
    return resistance_check(stat_body, DECAY_CHECK_TN,
                            minor_obstacle=minor, major_obstacle=major)


def treat_poison(healer_stat: int, skill_rank: int, blight_level: int = 1) -> dict:
    """Field treatment: healer rolls a Skill Check vs the poison's Blight TN
    (12/15/18). Success neutralizes the toxin and stops continuing ticks."""
    target = POISON_TARGETS.get(blight_level, 12)
    result = execute_action_check(healer_stat, skill_rank, target)
    result["blight_level"] = blight_level
    result["neutralized"] = result["success"]
    return result


def sleep_state_breaks(ailment: str, damage_taken: bool = False,
                       loud_noise: bool = False) -> dict:
    """Interruption rules (Extras p.242, 652): Sleep breaks on loud noise or
    damage; Paralysis and Stone cannot be broken early (magic only)."""
    key = ailment.lower()
    if key in ("paralyzed", "paralysis", "stone", "petrified"):
        return {"breakable": False, "broken": False, "reason": "magic only (Lesser Restoration / Halidom / Exorcism)"}
    if key in ("sleep", "asleep", "sleeping"):
        broken = damage_taken or loud_noise
        return {"breakable": True, "broken": broken,
                "reason": None if broken else "needs loud noise or physical damage"}
    return {"breakable": False, "broken": False, "reason": f"unknown ailment '{ailment}'"}


def stun_recovery_per_hour(character) -> int:
    """Stun damage recovery: Body Stat every hour (vs standard daily rate).
    Cannot kill — unconscious at 0 HP from stun, never dead by stun damage."""
    return character.stat_body


# ── mind control & cognitive subversion (Extras pp.560-567) ─────────────

CONTROL_GRADIENT = {
    1: "basic non-aggressive suggestions",
    2: "simple non-aggressive tasks",
    3: "complex non-aggressive routing",
    4: "aggressive commands",
    5: "erase brief recent memories",
    6: "rewrite complex long-term memories",
}


def mind_control_gradient(level: int) -> str:
    """Label the severity of a successful Mind Control by Attribute Level."""
    return CONTROL_GRADIENT.get(level, f"unknown level {level}")


def mind_control_resistance(defender_mind: int, defender_soul: int,
                            controller_mind: int, mc_level: int,
                            mind_shield_level: int = 0) -> dict:
    """Opposed Mind/Soul break check: defender rolls higher-of Mind/Soul +
    Mind Shield (×2 per level) vs controller's Mind + MC Level. Winner = whole
    contest. 3 successive failures → immune to that caster for 24h (caller).
    """
    defender_stat = max(defender_mind, defender_soul)
    defender_total = defender_stat + 2 * mind_shield_level
    controller_total = controller_mind + mc_level
    if defender_total >= controller_total:
        winner = "defender"
        break_success = True
    else:
        winner = "controller"
        break_success = False
    return {
        "winner": winner,
        "break_success": break_success,
        "defender_total": defender_total,
        "controller_total": controller_total,
        "defender_stat": defender_stat,
        "mind_shield_level": mind_shield_level,
    }


def against_nature_break_check(edict: str) -> int:
    """Break clause (Extras pp.561-562): target's Stat check to break control
    gains an Edge depending on how distasteful the command is.
    Returns edge weight: 0=none, 1=minor, 2=major."""
    key = edict.lower()
    if "lethal" in key or "loved one" in key or "harm self" in key:
        return 2
    if "humiliat" in key or "distasteful" in key or "against code" in key:
        return 1
    return 0


def exorcism_clash(exorcist_soul: int, exorcism_level: int,
                   controller_soul: int, mc_level: int) -> dict:
    """Exorcism Attribute clash (p.516): (Soul + 2×Exorcism) vs
    (Controller Soul + MC Level). Success shatters control; failure alerts the
    controller."""
    exorcist_total = exorcist_soul + 2 * exorcism_level
    controller_total = controller_soul + mc_level
    success = exorcist_total >= controller_total
    return {
        "success": success,
        "exorcist_total": exorcist_total,
        "controller_total": controller_total,
        "controller_alerted": not success,
    }


# ── wound penalties ──────────────────────────────────────────────────────

def wound_obstacle(character) -> str | None:
    """BESM wound-difficulty penalties: HP ≤ 50% → Minor Obstacle, HP < SV → Major Obstacle.
    Returns "minor", "major", or None if healthy."""
    hp = character.current_hp
    if hp is None:
        return None
    max_hp = character.max_hp
    sv = character.shock_value_computed
    if hp <= 0:
        return "major"
    if hp < sv:
        return "major"
    if hp <= max_hp / 2:
        return "minor"
    return None


# ── falling damage ───────────────────────────────────────────────────────

FALLING_DAMAGE_TABLE = [
    (2, (2, 3), 10),
    (3, (3, 5), 15),
    (4, (5, 7), 20),
    (5, (7, 10), 25),
    (6, (10, 20), 30),
    (8, (20, 50), 40),
    (12, (50, 100), 50),
    (16, (100, 200), 80),
    (20, (200, 500), 100),
    (24, (500, 9999), 150),
]

def falling_damage(distance_meters: float) -> int:
    """BESM falling damage: distance → HP. No safe threshold.
    Acrobatics halving applied by caller (not wired — no skill field on CharacterSchema)."""
    if distance_meters < 2:
        return 0
    for floor, (lo, hi), damage in FALLING_DAMAGE_TABLE:
        if lo <= distance_meters <= hi:
            return damage
    return 150


# ── range penalties ──────────────────────────────────────────────────────

def range_obstacle(max_range: float, distance: float) -> str | None:
    """BESM range-distance penalties. Effective=within 1/5 max (none).
    Intermediate=1/5 to 1/2 max → Minor Obstacle.
    Remote=1/2 to max → Major Obstacle. Beyond max → None (out of range signal)."""
    if distance <= 0:
        return None
    if distance > max_range:
        return None
    if distance <= max_range / 5:
        return None
    if distance <= max_range / 2:
        return "minor"
    return "major"


# ── modifier stacking & combat resolution ────────────────────────────────

# Modifier weights for stacking: 1 = minor, 2 = major.
# These are INT counts, not strings — they stack arithmetically per BESM rules.
# e.g., 2 minor edges → 1 major edge (2 × 1 = 2). 1 major + 1 minor → 3 → 1 major + spillover.

def resolve_modifier_stack(edge_count: int, obstacle_count: int) -> dict:
    """Resolve raw edge/obstacle counts through BESM modifier interaction laws.

    edge_count and obstacle_count are integer weights (1 per minor, 2 per major).
    Returns resolved edge level, obstacle level, spillover, and mulligans.

    Laws applied:
      1. Cancellation — equal weights cancel
      2. Compounding — two minors (weight ≥ 2) → major
      3. Spillover — weight > 2 → opposite effect on opponent
      4. Mulligans — each extra minor edge beyond major → 1 reroll option
    """
    net = edge_count - obstacle_count

    if net > 0:
        edge_level = min(net, 2)
        spillover = max(0, net - 2)
        obstacle_level = 0
        mulligans = spillover
    elif net < 0:
        edge_level = 0
        obstacle_level = min(-net, 2)
        spillover = max(0, -net - 2)
        mulligans = 0
    else:
        edge_level = obstacle_level = spillover = mulligans = 0

    return {
        "edge": None if edge_level == 0 else ("minor" if edge_level == 1 else "major"),
        "obstacle": None if obstacle_level == 0 else ("minor" if obstacle_level == 1 else "major"),
        "spillover": spillover,
        "mulligans": mulligans,
        "raw_edge": edge_count,
        "raw_obstacle": obstacle_count,
    }


def resolve_combat_roll(acv: int, attack_edge: int, attack_obstacle: int,
                         dcv: int, defence_edge: int, defence_obstacle: int) -> dict:
    """Full combat resolution: attacker vs defender each roll 2d6 + CV + modifiers.

    Edge/obstacle counts are resolved through cancellations/compounding/spillover.
    Attack hits if attacker total > defender total (BESM tie goes to defender by
    default, but ties are rare with 2d6 margin).

    Returns hit, attack/defence totals, applied modifiers, and margins.
    """
    att_mods = resolve_modifier_stack(attack_edge, attack_obstacle)
    def_mods = resolve_modifier_stack(defence_edge, defence_obstacle)

    has_edge = att_mods["edge"] is not None
    has_obstacle = att_mods["obstacle"] is not None
    att_roll = _resolve_roll(acv, 12, has_edge, att_mods["edge"],
                             has_obstacle, att_mods["obstacle"])

    has_d_edge = def_mods["edge"] is not None
    has_d_obstacle = def_mods["obstacle"] is not None
    def_roll = _resolve_roll(dcv, 12, has_d_edge, def_mods["edge"],
                             has_d_obstacle, def_mods["obstacle"])

    hit = att_roll["total"] > def_roll["total"]

    return {
            "hit": hit,
            "attack_total": att_roll["total"],
            "attack_roll": att_roll["roll"],
            "defence_total": def_roll["total"],
            "defence_roll": def_roll["roll"],
            "attack_mods": att_mods,
            "defence_mods": def_mods,
        }


# ── size & scale ─────────────────────────────────────────────────────────

SIZE_GRID = {
    -3: {"category": "Diminutive", "mass": "500 g – 2 kg",
         "strength_mult": 1/100, "strength_damage": -30, "armour": -30,
         "ranged_mod": 6, "range_mult": 1/8},
    -2: {"category": "Tiny", "mass": "500 g – 2 kg",
         "strength_mult": 1/25, "strength_damage": -20, "armour": -20,
         "ranged_mod": 4, "range_mult": 1/4},
    -1: {"category": "Small", "mass": "6–20 kg",
         "strength_mult": 1/5, "strength_damage": -10, "armour": -10,
         "ranged_mod": 2, "range_mult": 1/2},
    0:  {"category": "Medium", "mass": "50–150 kg",
         "strength_mult": 1, "strength_damage": 0, "armour": 0,
         "ranged_mod": 0, "range_mult": 1},
    1:  {"category": "Large", "mass": "200–1,200 kg",
         "strength_mult": 5, "strength_damage": 10, "armour": 10,
         "ranged_mod": -2, "range_mult": 2},
    2:  {"category": "Huge", "mass": "1.5–8 tonnes",
         "strength_mult": 25, "strength_damage": 20, "armour": 20,
         "ranged_mod": -4, "range_mult": 4},
    3:  {"category": "Mammoth", "mass": "10–60 tonnes",
         "strength_mult": 100, "strength_damage": 30, "armour": 30,
         "ranged_mod": -6, "range_mult": 8},
    4:  {"category": "Gigantic", "mass": "75–500 tonnes",
         "strength_mult": 500, "strength_damage": 40, "armour": 40,
         "ranged_mod": -8, "range_mult": 15},
    5:  {"category": "Gargantuan", "mass": "550–4,000 tonnes",
         "strength_mult": 2500, "strength_damage": 50, "armour": 50,
         "ranged_mod": -10, "range_mult": 30},
    6:  {"category": "Colossal", "mass": "4k–30k tonnes",
         "strength_mult": 10000, "strength_damage": 60, "armour": 60,
         "ranged_mod": -12, "range_mult": 60},
}

def size_lookup(size_rank: int) -> dict | None:
    return SIZE_GRID.get(size_rank)

def size_strength_damage(size_rank: int, base_damage: int = 0) -> int:
    """Physical strike damage modified by size. D-rank weapon vs Colossal → auto-fatal."""
    entry = SIZE_GRID.get(size_rank, SIZE_GRID[0])
    return max(0, base_damage + entry["strength_damage"])

def size_armour_rating(size_rank: int) -> int:
    """Innate AR from sheer mass. Negative ranks = damage TAKEN bonus (vulnerability)."""
    entry = SIZE_GRID.get(size_rank, SIZE_GRID[0])
    return entry["armour"]

def size_ranged_modifier(size_rank: int) -> int:
    """To-hit/DCV modifier for ranged combat. Positive = tiny target (harder to hit)."""
    entry = SIZE_GRID.get(size_rank, SIZE_GRID[0])
    return entry["ranged_mod"]

def size_range_multiplier(size_rank: int) -> float:
    """Weapon range and speed scaled by size. ×60 for Colossal."""
    entry = SIZE_GRID.get(size_rank, SIZE_GRID[0])
    return entry["range_mult"]

def size_knockback(attacker_size: int, defender_size: int) -> dict:
    """Absolute Knockback: attacker ≥ 2 sizes larger → auto knockback 10m per rank difference.
    Smaller attackers can still knock back, but must overcome standard physics."""
    diff = attacker_size - defender_size
    if diff >= 2:
        return {"auto_knockback": True, "distance_meters": 10 * diff}
    return {"auto_knockback": False, "distance_meters": 0}

def size_collapse_damage(structure_size: int) -> dict:
    """Building/pillar collapse: AR = 10 × size_rank. Collapse at 5× AR in one hit.
    Adjacent characters take half AR unless Reflex save."""
    ar = max(10, 10 * structure_size)
    return {
        "structure_ar": ar,
        "collapse_threshold": 5 * ar,
        "fallout_damage": ar // 2,
    }


# ── defensive absorption layers 1-4 ──────────────────────────────────────
# Layer 5 (Shock/Trauma) = check_shock() — already built above.

def resolve_active_defence(dcv: int, shield_edge: int = 0,
                           defending_other: bool = False,
                           interpose_body: bool = False) -> dict:
    """Layer 1: Active Parry/Shield. Opposed defence roll against incoming attack.
    shield_edge: 0=none, 1=minor (Potent -1), 2=major (Potent -2/Tower).
    defending_other adds Minor Obstacle. interpose_body cancels the obstacle.
    Returns (parried, roll_total, edge_applied, obstacle_applied)."""
    edge = max(0, min(shield_edge, 2))
    obstacle = 0
    if defending_other:
        obstacle = 1
    if interpose_body and defending_other:
        obstacle = 0  # no net modifier when interposing

    mods = resolve_modifier_stack(edge, obstacle)
    roll = _resolve_roll(dcv, 0, mods["edge"] is not None, mods["edge"],
                         mods["obstacle"] is not None, mods["obstacle"])

    return {
        "parried": False,  # caller compares roll["total"] vs attack_total
        "defence_total": roll["total"],
        "defence_roll": roll["roll"],
        "edge_applied": mods["edge"],
        "obstacle_applied": mods["obstacle"],
    }


def resolve_force_field(damage: int, force_field_ar: int,
                        piercing_ranks: int = 0) -> dict:
    """Layer 2: Force Field / Energy Barrier. Reduces damage by effective AR.
    Piercing: -10 AR per rank. Crash Rule: if damage exceeds reduced AR,
    field degrades 1 level (caller applies).
    Returns (remaining, effective_ar, degraded)."""
    effective = max(0, force_field_ar - 10 * piercing_ranks)
    remaining = max(0, damage - effective)
    return {
        "remaining_damage": remaining,
        "effective_ar": effective,
        "degraded": remaining > 0 and effective > 0,
    }


def resolve_armour(damage: int, armour_rating: int,
                   penetrating_ranks: int = 0,
                   non_penetrating: bool = False,
                   gap_half: bool = False,
                   gap_bypass: bool = False) -> dict:
    """Layer 3: Physical Armour. Flat damage reduction.
    Penetrating: -10 AR per rank. Non-Penetrating weapon: +10 AR to target.
    Gap called shots: half AR (Minor Obstacle on attack) or bypass (Major Obstacle).
    Returns (remaining, effective_ar)."""
    effective = armour_rating
    if non_penetrating:
        effective += 10
    effective = max(0, effective - 10 * penetrating_ranks)
    if gap_bypass:
        effective = 0
    elif gap_half:
        effective = effective // 2
    remaining = max(0, damage - effective)
    return {"remaining_damage": remaining, "effective_ar": effective}


def resolve_absorption(net_damage: int, absorption_level: int,
                       current_hp: int, max_hp: int,
                       current_ep: int, max_ep: int,
                       is_complex_weapon: bool = False) -> dict:
    """Layer 4: Kinetic Absorption. Converts 5 damage/level to HP or EP.
    Complex weapons (Continuing, Drain, Flare, Incapacitating, Irritant,
    Psychic, Stun, Tangle) bypass absorption entirely.
    Capped at 2× max HP/EP. Returns (final_damage, hp_gained, ep_gained)."""
    if is_complex_weapon or absorption_level <= 0:
        return {"final_damage": net_damage, "hp_gained": 0, "ep_gained": 0}

    convert = min(net_damage, absorption_level * 5)
    final = net_damage - convert

    hp_room = max(0, (max_hp * 2) - current_hp)
    ep_room = max(0, (max_ep * 2) - current_ep)

    hp_gain = 0
    ep_gain = 0
    remaining = convert

    if current_hp < max_hp:
        need = max_hp - current_hp
        hp_gain = min(need, remaining)
        remaining -= hp_gain

    hp_gain = min(hp_gain, hp_room)
    if remaining > 0:
        ep_gain = min(remaining, ep_room)

    return {"final_damage": final, "hp_gained": hp_gain, "ep_gained": ep_gain}


def resolve_attack_damage(incoming_damage: int,
                          force_field_ar: int = 0,
                          armour_rating: int = 0,
                          absorption_level: int = 0,
                          piercing_ranks: int = 0,
                          penetrating_ranks: int = 0,
                          non_penetrating: bool = False,
                          gap_half: bool = False,
                          gap_bypass: bool = False,
                          is_complex_weapon: bool = False,
                          current_hp: int = 100,
                          max_hp: int = 100,
                          current_ep: int = 100,
                          max_ep: int = 100) -> dict:
    """Full 4-layer damage resolution pipeline. Layer 1 (active parry) handled
    separately by the attack roll — this runs Layers 2-4 on a HIT.

    Returns layer-by-layer breakdown with net_damage at the end."""
    ff = resolve_force_field(incoming_damage, force_field_ar, piercing_ranks)
    ar = resolve_armour(ff["remaining_damage"], armour_rating,
                        penetrating_ranks, non_penetrating, gap_half, gap_bypass)
    abs_result = resolve_absorption(ar["remaining_damage"], absorption_level,
                                    current_hp, max_hp, current_ep, max_ep,
                                    is_complex_weapon)
    return {
        "incoming": incoming_damage,
        "after_force_field": ff["remaining_damage"],
        "force_field_ar": ff["effective_ar"],
        "force_field_degraded": ff["degraded"],
        "after_armour": ar["remaining_damage"],
        "effective_armour_ar": ar["effective_ar"],
        "net_damage": abs_result["final_damage"],
        "hp_absorbed": abs_result["hp_gained"],
        "ep_absorbed": abs_result["ep_gained"],
    }


# ── extended actions & opposed contests ──────────────────────────────────

EXTENDED_ACTION_MATRIX = {
    "standard":  {"mos_threshold": 10, "target": 12, "checks": 3},
    "complex":   {"mos_threshold": 15, "target": 15, "checks": 4},
    "legendary": {"mos_threshold": 25, "target": 18, "checks": 5},
    "mythic":    {"mos_threshold": 40, "target": 21, "checks": 6},
}


def init_extended_action(difficulty: str = "standard") -> dict:
    """Initialize a new extended action tracker."""
    tier = EXTENDED_ACTION_MATRIX.get(difficulty, EXTENDED_ACTION_MATRIX["standard"])
    return {
        "difficulty": difficulty,
        "mos_threshold": tier["mos_threshold"],
        "target": tier["target"],
        "checks_remaining": tier["checks"],
        "checks_total": tier["checks"],
        "cumulative_mos": 0,
        "completed": False,
        "crashed": False,
        "obstacle_level": None,  # escalates: None → "minor" → "major"
        "ep_drain": 0,
        "history": [],
    }


def resolve_extended_check(tracker: dict, stat: int, skill: int,
                           edge_weight: int = 0) -> dict:
    """Execute one check of an extended action. Updates tracker in place.
    edge_weight: 0=none, 1=minor edge, 2=major edge.

    Frictional Backlash: MoF ≥ 3 → Minor Obstacle on subsequent checks.
    Second failure with MoF ≥ 3 → Major Obstacle.
    Returns check result dict. Caller should update EP drain / guard alerts separately.
    """
    if tracker["completed"] or tracker["crashed"]:
        return {"error": "action already resolved", **tracker}

    obstacle = tracker["obstacle_level"]
    minor = obstacle == "minor"
    major = obstacle == "major"

    mods = resolve_modifier_stack(edge_weight, 1 if minor else (2 if major else 0))
    roll = _resolve_roll(stat + skill, tracker["target"],
                         mods["edge"] is not None, mods["edge"],
                         mods["obstacle"] is not None, mods["obstacle"])

    margin = roll["total"] - tracker["target"]
    fence = 0 if margin < 0 else margin

    tracker["checks_remaining"] -= 1
    if margin >= 0:
        tracker["cumulative_mos"] += fence

    if tracker["cumulative_mos"] >= tracker["mos_threshold"]:
        tracker["completed"] = True

    if tracker["checks_remaining"] <= 0 and not tracker["completed"]:
        tracker["crashed"] = True

    if margin <= -3:
        if tracker["obstacle_level"] is None:
            tracker["obstacle_level"] = "minor"
        elif tracker["obstacle_level"] == "minor":
            tracker["obstacle_level"] = "major"

    entry = {
        "total": roll["total"],
        "roll": roll["roll"],
        "target": tracker["target"],
        "margin": margin,
        "edge_applied": mods["edge"],
        "obstacle_applied": mods["obstacle"],
    }
    tracker["history"].append(entry)

    return {
        "check": entry,
        "cumulative_mos": tracker["cumulative_mos"],
        "mos_threshold": tracker["mos_threshold"],
        "checks_remaining": tracker["checks_remaining"],
        "completed": tracker["completed"],
        "crashed": tracker["crashed"],
        "obstacle_level": tracker["obstacle_level"],
    }


def resolve_opposed_contest(attacker_stat: int, attacker_skill: int,
                            defender_stat: int, defender_skill: int,
                            attacker_edge: int = 0,
                            defender_edge: int = 0) -> dict:
    """Active vs Reactive opposed contest. Aggressor wins ties.
    Returns margin, winner, and detection gradient if applicable."""
    att_mods = resolve_modifier_stack(attacker_edge, 0)
    def_mods = resolve_modifier_stack(defender_edge, 0)

    att_roll = _resolve_roll(attacker_stat + attacker_skill, 0,
                             att_mods["edge"] is not None, att_mods["edge"],
                             False, None)
    def_roll = _resolve_roll(defender_stat + defender_skill, 0,
                             def_mods["edge"] is not None, def_mods["edge"],
                             False, None)

    margin = att_roll["total"] - def_roll["total"]
    if margin >= 0:
        winner = "attacker"
    else:
        winner = "defender"

    gradient = detection_gradient(margin)

    return {
        "attacker_total": att_roll["total"],
        "attacker_roll": att_roll["roll"],
        "defender_total": def_roll["total"],
        "defender_roll": def_roll["roll"],
        "margin": margin,
        "winner": winner,
        "gradient": gradient,
    }


def detection_gradient(margin: int) -> str:
    """Stealth/perception result from opposed contest margin.
    Attacker is the infiltrator; positive margin = attacker successful."""
    if margin >= 12:
        return "Ghosted"
    if margin >= 6:
        return "Unaware"
    if margin >= 1:
        return "Suspicious"
    if margin >= -5:
        return "Alerted"
    return "Lockdown"


# ── combat technique enforcement ─────────────────────────────────────────

def _has_technique(techniques: list, name: str) -> int:
    """Return the highest level of a named technique across all assignments.
    Returns 0 if not present. Case-insensitive substring match."""
    best = 0
    target = name.lower()
    for t in (techniques or []):
        if isinstance(t, dict) and target in t.get("name", "").lower():
            best = max(best, t.get("level", 1))
    return best


def technique_obstacle_reduction(techniques: list, obstacle_type: str) -> int:
    """Return obstacle reduction from techniques: 0=none, 1=minor→none, 2=major→minor.

    Obstacle types and their techniques:
      range       → Far Shot removes range penalties
      movement    → Dead Eye removes speed penalties, Steady Hand removes sprint penalties
      called_shot → Precise Aim removes called shot obstacles
      multi_target → Multiple Targets removes multi-target obstacles
      darkness    → Blind Fighting / Blind Shooting (bypass entirely)
    """
    reduction = 0
    if obstacle_type == "range":
        reduction = max(reduction, _has_technique(techniques, "far shot"))
    elif obstacle_type == "movement":
        reduction = max(reduction, _has_technique(techniques, "dead eye"))
    elif obstacle_type == "sprint_ranged":
        reduction = max(reduction, _has_technique(techniques, "steady hand"))
    elif obstacle_type == "called_shot":
        reduction = max(reduction, _has_technique(techniques, "precise aim"))
    elif obstacle_type == "multi_target":
        reduction = max(reduction, _has_technique(techniques, "multiple targets"))
    elif obstacle_type == "darkness":
        if _has_technique(techniques, "blind fighting") or _has_technique(techniques, "blind shooting"):
            reduction = 3
    return reduction


def apply_obstacle_reduction(obstacle_weight: int, reduction: int) -> int:
    """Apply technique obstacle reduction. BESM: minor→none (reduction≥1),
    major→minor (reduction≥2). Returns adjusted obstacle weight."""
    if obstacle_weight <= 0:
        return 0
    if reduction >= 2 and obstacle_weight >= 2:
        return 1
    if reduction >= 1 and obstacle_weight <= 1:
        return 0
    return obstacle_weight


def technique_edge_bonus(techniques: list, edge_type: str) -> int:
    """Return edge weight from techniques: 0=none, 1=minor, 2=major.

    Edge types:
      initiative → Lightning Reflexes (1 per level, capped at major=2)
      amplify_aim → Precise Aim: Aim/Wait upgrades minor→major edge
    """
    if edge_type == "initiative":
        return min(_has_technique(techniques, "lightning reflexes"), 2)
    if edge_type == "amplify_aim":
        if _has_technique(techniques, "precise aim"):
            return 2
    return 0


def critical_damage_multiplier(natural_roll: int, margin_of_success: int,
                               has_critical_strike: bool = False) -> int:
    """BESM Critical Hit damage multiplier. Standard: MoS 12+ → ×2, 18+ → ×3.
    Critical Strike upgrades: 12+ → ×3, 18+ → ×4. Natural 12 → auto ×2.
    Returns multiplier (1 = normal hit, no crit)."""
    if has_critical_strike:
        if margin_of_success >= 18:
            return 4
        if margin_of_success >= 12:
            return 3
        if natural_roll == 12:
            return 2
    else:
        if margin_of_success >= 18:
            return 3
        if margin_of_success >= 12:
            return 2
        if natural_roll == 12:
            return 2
    return 1


def enhanced_knockback(acv: int, has_technique: bool = False) -> int:
    """Enhanced Knockback: adds 2 × ACV meters to knockback distance."""
    return 2 * acv if has_technique else 0


def rush_attack_damage_multiplier(has_rush_attack: bool = False,
                                   hit: bool = False) -> tuple:
    """Rush Attack: +1 Damage Multiplier on hit. On miss, Minor Obstacle
    on defence until next initiative phase.
    Returns (damage_multiplier_bonus, defence_obstacle)."""
    if not has_rush_attack:
        return (0, False)
    if hit:
        return (1, False)
    return (0, True)


# ── sanity & madness ─────────────────────────────────────────────────────

SANITY_TRAUMA_TABLE = {
    "mild":      {"target": 12, "sp_loss": 0},
    "moderate":  {"target": 15, "sp_loss": 1},
    "major":     {"target": 18, "sp_loss": 2},
    "severe":    {"target": 21, "sp_loss": 3},
    "catastrophic": {"target": 24, "sp_loss": 4},
}


def max_sanity_points(mind: int, soul: int,
                      unassailable: int = 0, unsettled: int = 0) -> int:
    """Derived max Sanity Points: Mind + Soul + 2/Unassailable - 2/Unsettled."""
    return max(0, mind + soul + 2 * unassailable - 2 * unsettled)


def check_sanity(mind: int, soul: int, current_sp: int,
                 trauma: str = "mild") -> dict:
    """BESM Sanity Check: 2d6 + avg(Mind,Soul)/2 vs TN per trauma magnitude.
    Returns pass, sp_loss, new_sp, target, roll details."""
    tier = SANITY_TRAUMA_TABLE.get(trauma, SANITY_TRAUMA_TABLE["mild"])
    stat = (mind + soul) // 2
    result = _roll_with_obstacle(stat, tier["target"])
    passed = result["success"]
    loss = tier["sp_loss"] if not passed else 0
    new_sp = max(0, current_sp - loss)
    return {
        "passed": passed,
        "sp_loss": loss,
        "new_sp": new_sp,
        "target": tier["target"],
        "trauma": trauma,
        "roll": result["roll"],
        "total": result["total"],
    }


def sanity_obstacle(sp: int) -> str | None:
    """Sanity spiral penalties: SP ≤ 4 → minor, SP ≤ 2 → major, SP ≤ 1
    → silence (narrative), SP = 0 → broken (unplayable).
    Returns None/minor/major based on obstacle dice only."""
    if sp <= 2:
        return "major"
    if sp <= 4:
        return "minor"
    return None


def sanity_recovery(method: str, mind: int = 0) -> dict:
    """Sanity Point recovery rates. Methods: therapy (TN 15, +1 SP),
    reassurance (+1, once/scene), self_guided (+1/week), supernatural (+2-4).
    Returns (sp_restored, tn_required)."""
    rates = {
        "therapy": (1, 15),
        "reassurance": (1, 0),
        "self_guided": (1, 0),
        "supernatural": (random.randint(2, 4), 0),
    }
    return dict(zip(("sp_restored", "tn"), rates.get(method, (0, 0))))


# ── catastrophic damage ──────────────────────────────────────────────────

def check_catastrophic_damage(character, damage_taken: int) -> dict:
    """BESM Catastrophic Damage: single hit ≥ max HP → Soul TN 12 or instant death.
    Returns (triggered, passed, roll details)."""
    if damage_taken < character.max_hp:
        return {"triggered": False, "passed": True}
    result = resistance_check(character.stat_soul, 12)
    return {
        "triggered": True,
        "passed": result["success"],
        "target": 12,
        "roll": result["roll"],
        "total": result["total"],
    }


# ── hemorrhage & first aid ───────────────────────────────────────────────

def hemorrhage_tick(injury_count: int = 1) -> int:
    """HP loss per round from bleeding. 1 HP per serious injury (cumulative)."""
    return injury_count


def first_aid_check(mind: int, skill: int) -> dict:
    """First Aid (TN 12): slows bleeding from -1/round to -1/10min."""
    return resistance_check(mind + skill, 12)


def surgery_check(mind: int, skill: int) -> dict:
    """Surgery (TN 15): permanently stops bleeding."""
    return resistance_check(mind + skill, 15)


# ── natural recovery ─────────────────────────────────────────────────────

def hp_recovery(body: int, days_rest: int,
                has_medical: bool = False, not_resting: bool = False) -> int:
    """Daily HP recovery: Body Stat/day. ×2 with Medical care.
    ÷2 if not resting. Returns total HP recovered."""
    rate = body
    if has_medical:
        rate *= 2
    if not_resting:
        rate = rate // 2
    return rate * days_rest


def ep_recovery(mind: int, soul: int, hours_rest: int,
                inspire_level: int = 0) -> int:
    """Hourly EP recovery: (Mind + Soul)//2 + Inspire level per hour."""
    return hours_rest * ((mind + soul) // 2 + inspire_level)


def stun_recovery_rate(body: int) -> int:
    """Stun damage recovery rate: Body Stat per hour."""
    return body


def stat_drain_recovery_rate() -> int:
    """Drained Stat points recover at 1 point/hour."""
    return 1


# ── defect enforcement ───────────────────────────────────────────────────

def _defect_rank(defects: list, name: str) -> int:
    """Return the highest rank of a named defect. 0 if not present.
    Matches by substring — 'Physical Impairment (leg)' matches 'physical impairment'."""
    best = 0
    target = name.lower()
    for d in (defects or []):
        if isinstance(d, dict) and target in d.get("name", "").lower():
            best = max(best, d.get("rank", 1))
    return best


def defect_hp_modifier(defects: list) -> int:
    """Fragile defect: -10/-20/-30 max HP per rank 1/2/3."""
    rank = _defect_rank(defects, "fragile")
    return -10 * rank if rank else 0


def defect_damage_modifier(defects: list) -> int:
    """Reduced Damage: -1/-2/-3 Damage Multiplier."""
    return -_defect_rank(defects, "reduced damage")


def defect_achilles_multiplier(defects: list, damage_source: str) -> float:
    """Achilles Heel: 2× damage from matching source. Caller checks match."""
    if not _defect_rank(defects, "achilles heel"):
        return 1.0
    # Caller passes the source label; this is a simple flag — actual source
    # matching is campaign-specific and handled at the call site.
    return 2.0


def defect_bane_damage(defects: list) -> int:
    """Bane damage per round: 10/20/30 per rank 1/2/3."""
    rank = _defect_rank(defects, "bane")
    return 10 * rank


def defect_weak_point_multiplier(defects: list) -> tuple:
    """Weak Point: double damage AND bypass armour on successful Called Shot.
    Returns (damage_multiplier, bypass_armour)."""
    if _defect_rank(defects, "weak point"):
        return (2.0, True)
    return (1.0, False)


def defect_sanity_modifier(defects: list) -> int:
    """Unsettled defect: -2/-4/-6 max SP per rank 1/2/3."""
    return -2 * _defect_rank(defects, "unsettled")


def defect_social_modifier(defects: list) -> int:
    """Demure defect: -2/-4/-6 SCV per rank 1/2/3."""
    return -2 * _defect_rank(defects, "demure")


def defect_blocks_recovery(defects: list) -> dict:
    """Nightmares/No Healing: returns dict of blocked recovery types.
    caller checks: if result['hp'] → no natural HP recovery, etc."""
    return {
        "hp": _defect_rank(defects, "no healing") > 0,
        "rest": _defect_rank(defects, "nightmares") > 0,
    }


def defect_shortcoming_obstacle(defects: list, aspect: str) -> str | None:
    """Shortcoming: Minor Obstacle (major aspect) or Major Obstacle (minor aspect).
    aspect is e.g. 'strength', 'perception', 'luck'. Caller determines major/minor.
    Returns 'minor', 'major', or None."""
    if not _defect_rank(defects, "shortcoming"):
        return None
    return "minor" if aspect in ("agility", "endurance", "strength", "creativity",
                                 "perception", "reason", "charisma", "luck", "willpower") else "major"


def defect_sensory_obstacle(defects: list) -> str | None:
    """Sensory Impairment: Major Obstacle on perception checks."""
    if _defect_rank(defects, "sensory impairment"):
        return "major"
    return None


def defect_phobia_check(character, defects: list, phobia_trigger: bool = True) -> dict:
    """Phobia: if triggered, Soul check to act. Fail → freeze/flee + major obstacle.
    Returns (triggered, passed, obstacle_on_fail)."""
    if not phobia_trigger or not _defect_rank(defects, "phobia"):
        return {"triggered": False, "passed": True}
    result = resistance_check(character.stat_soul, 12)
    return {
        "triggered": True,
        "passed": result["success"],
        "roll": result["roll"],
        "total": result["total"],
        "obstacle_on_fail": "major" if not result["success"] else None,
    }


def defect_distraction_check(character, defects: list,
                              trigger_present: bool = True) -> dict:
    """Easily Distracted: Mind/Soul TN 12 or lose round actions.
    Uses higher of Mind or Soul (GM discretion: depends on trigger type)."""
    if not trigger_present or not _defect_rank(defects, "easily distracted"):
        return {"triggered": False, "passed": True}
    stat = max(character.stat_mind, character.stat_soul)
    result = resistance_check(stat, 12)
    return {
        "triggered": True,
        "passed": result["success"],
        "roll": result["roll"],
        "total": result["total"],
        "loses_actions": not result["success"],
    }


# ── social combat value & society points ─────────────────────────────────

SOCIAL_DAMAGE_TABLE = [
    (1, 2, 1),
    (3, 5, 2),
    (6, 11, 3),
    (12, 17, 4),
    (18, 99, 5),
]


def social_combat_value(mind: int, soul: int,
                         social_mastery: int = 0,
                         scv_modifier: int = 0) -> int:
    """BESM derived SCV: (Mind + Soul)//2 + 2×Social Mastery + modifier.
    Negative scv_modifier handles Demure (-2/-4/-6)."""
    base = (mind + soul) // 2
    return max(0, base + 2 * social_mastery + scv_modifier)


def character_scv(character, social_mastery_level: int = 0) -> int:
    """Compute SCV from a CharacterSchema, querying defect modifiers automatically."""
    base = (character.stat_mind + character.stat_soul) // 2
    mastery_bonus = 2 * social_mastery_level
    demure_penalty = -2 * _defect_rank(character.defects, "demure")
    return max(0, base + mastery_bonus + demure_penalty)


def society_points(scv: int) -> int:
    """Base Society Points = SCV. Represents composure, dignity, standing."""
    return scv


def social_damage(margin_of_success: int) -> int:
    """Society Point damage from MoS in a social clash."""
    if margin_of_success <= 0:
        return 0
    for lo, hi, damage in SOCIAL_DAMAGE_TABLE:
        if lo <= margin_of_success <= hi:
            return damage
    return 5


def social_recovery(hours: int) -> int:
    """Society Points recover at 1 SP per hour of quiet downtime."""
    return hours


def social_defeat_obstacle(sp: int) -> str | None:
    """At 0 SP: permanent Major Obstacle in that social circle."""
    if sp <= 0:
        return "major"
    return None


def resolve_social_clash(attacker_scv: int, attacker_skill: int,
                          defender_scv: int, defender_skill: int,
                          attacker_edge: int = 0,
                          defender_edge: int = 0) -> dict:
    """Full social combat round: opposed SCV rolls, MoS → SP damage.
    Ties go to attacker (aggressor)."""
    contest = resolve_opposed_contest(attacker_scv, attacker_skill,
                                      defender_scv, defender_skill,
                                      attacker_edge, defender_edge)
    margin = contest["margin"]
    if margin < 0:
        sp_damage = 0
    else:
        sp_damage = social_damage(margin)

    return {
        "winner": contest["winner"],
        "margin": margin,
        "sp_damage": sp_damage,
        "attacker_total": contest["attacker_total"],
        "defender_total": contest["defender_total"],
    }


# ── spellbook resolver ───────────────────────────────────────────────────

def get_spell(spellbook: list, spell_name: str) -> dict | None:
    """Look up a spell in the character's spellbook. Case-insensitive substring match."""
    target = spell_name.lower()
    for s in (spellbook or []):
        if isinstance(s, dict) and target in s.get("name", "").lower():
            return s
    return None


def spell_ep_cost(spellbook: list, spell_name: str) -> int | None:
    """EP cost of casting a spell. None if spell not found."""
    s = get_spell(spellbook, spell_name)
    return s.get("ep_cost") if s else None


def cast_deplete_check(character, spell_name: str) -> dict:
    """Attempt to cast a spell. Deducts EP from character.
    Returns (cast_success, remaining_ep, spell_info, sixth_guard_triggered)."""
    s = get_spell(character.spellbook, spell_name)
    if not s:
        return {"cast_success": False, "error": f"Spell '{spell_name}' not in spellbook."}

    cost = s.get("ep_cost", 0)
    current = character.current_ep if character.current_ep is not None else character.max_ep
    after = current - cost

    return {
        "cast_success": True,
        "spell": s["name"],
        "ep_cost": cost,
        "ep_before": current,
        "ep_after": max(0, after),
        "sixth_guard": after <= 0,
        "effect": s.get("effect", ""),
        "kind": s.get("kind", ""),
    }


def spellbook_summary(spellbook: list) -> list[str]:
    """Human-readable spell list for TUI display."""
    lines = []
    for s in (spellbook or []):
        if isinstance(s, dict):
            lines.append(f'  [bold]{s.get("name", "?")}[/bold] '
                         f'({s.get("ep_cost", 0)} EP, {s.get("kind", "spell")}) '
                         f'— {s.get("effect", "")}')
    return lines


# ── bond progression ─────────────────────────────────────────────────────

BOND_PHASES = {
    "Surface": (0, 50),
    "Warmth": (51, 75),
    "Confidant": (76, 99),
    "Soulbound": (100, 100),
}


def bond_phase(trust: int) -> str:
    """Return the bond phase label for a trust score."""
    for phase, (lo, hi) in BOND_PHASES.items():
        if lo <= trust <= hi:
            return phase
    return "Surface"


def apply_trust(current: int, delta: int) -> int:
    """Apply a trust delta, clamped 0–100. Returns new score."""
    return max(0, min(100, current + delta))


TRUST_GAINS = {
    "kindness": 5,
    "competence": 5,
    "protect": 10,
    "vulnerable": 10,
    "intimacy": 10,
    "remember": 5,
    "heroic": 10,
}

TRUST_LOSSES = {
    "reckless": -15,
    "boundary_push": -20,
    "broken_promise": -25,
    "betrayal": -50,
}

TRUST_WITNESS_GAIN = 5
TRUST_FAVORITISM_TAX = -10


def gain_trust(current: int, reason: str, already_in_phase: bool = False) -> dict:
    """Apply a trust gain event. intimacy is once-per-phase.
    Returns (new_score, delta, phase_before, phase_after)."""
    delta = TRUST_GAINS.get(reason, 0)
    if reason == "intimacy" and already_in_phase:
        delta = 0
    phase_before = bond_phase(current)
    new = apply_trust(current, delta)
    return {"new_trust": new, "delta": delta, "phase_before": phase_before, "phase_after": bond_phase(new)}


def lose_trust(current: int, reason: str) -> dict:
    """Apply a trust loss event. Betrayal may reset to 0.
    Returns (new_score, delta, phase_before, phase_after)."""
    delta = TRUST_LOSSES.get(reason, 0)
    phase_before = bond_phase(current)
    new = apply_trust(current, delta)
    return {"new_trust": new, "delta": delta, "phase_before": phase_before, "phase_after": bond_phase(new)}


def shared_triumph(bond_dict: dict, hero: str) -> dict:
    """Shared Triumph: +10 to hero, +5 to all witnesses."""
    results = {}
    for name, trust in bond_dict.items():
        delta = TRUST_WITNESS_GAIN + (5 if name == hero else 0)
        results[name] = apply_trust(trust, delta)
    return results


def favoritism_tax(bond_dict: dict, favored: str) -> dict:
    """Favoritism Tax: -10 to all neglected NPCs, unless addressed."""
    results = {}
    for name, trust in bond_dict.items():
        if name == favored:
            results[name] = trust
        else:
            results[name] = apply_trust(trust, TRUST_FAVORITISM_TAX)
    return results


def group_bond_stats(bond_dict: dict) -> dict:
    """Group statistics: average trust and the lowest-trust member."""
    if not bond_dict:
        return {"average": 0, "lowest_name": None, "lowest_trust": 0}
    trusts = list(bond_dict.values())
    names = list(bond_dict.keys())
    avg = sum(trusts) // len(trusts)
    min_idx = trusts.index(min(trusts))
    return {"average": avg, "lowest_name": names[min_idx], "lowest_trust": trusts[min_idx]}


def _resolve_roll(stat: int, _target: int,
                  has_edge: bool, edge_level: str | None,
                  has_obstacle: bool, obstacle_level: str | None) -> dict:
    """Roll 2d6 + stat with resolved edge/obstacle (never both)."""
    if has_edge:
        minor = edge_level == "minor"
        major = edge_level == "major"
        return _roll_with_edge(stat, 0, minor=minor, major=major)
    elif has_obstacle:
        minor = obstacle_level == "minor"
        major = obstacle_level == "major"
        return _roll_with_obstacle(stat, 0, minor=minor, major=major)
    else:
        dice = [random.randint(1, 6), random.randint(1, 6)]
        return {
            "success": True,
            "roll": sum(dice),
            "total": sum(dice) + stat,
            "target": 0,
        }


# ── diceless BESM (Extras Ch.9: pure-algebraic resolution) ──────────────

# Edge/obstacle TCR values (minor +1 / major +2; mirrored negative for obstacles).
EDGE_TCR_VALUE = {"minor": 1, "major": 2}
OBSTACLE_TCR_VALUE = {"minor": -1, "major": -2}

# Table-15: Diceless Combat Margin of Success → outcome bands.
# (low, high) inclusive → label, duration, victor hp % loss, opponent hp % loss.
DICELESS_MOS_TABLE = [
    ((0, 0),      "stalemate",          "upwards of an hour or longer", 10, 10),
    ((1, 2),      "slight_success",     "dozens of minutes",            25, 25),
    ((3, 5),      "moderate_success",   "several minutes",              25, 50),
    ((6, 11),     "significant_success","approximately 1-2 minutes",    10, 75),
    ((12, 17),    "major_success",      "within 30 seconds",             5, 95),
    ((18, None),  "extreme_success",    "several seconds",               0, 100),
]


def compute_tcr(combat_value: int, weapon_damage: int = 0,
                current_hp: int = 0, extra_actions: int = 0,
                mulligans: int = 0, ep_expended: int = 0,
                edge: str | None = None,
                target_ar: int = 0, target_extra_defences: int = 0,
                obstacle: str | None = None) -> dict:
    """Total Combat Roll (Diceless BESM, Extras Ch.9 p135).

    Every term rounds down. EP and Mulligan spends must be declared in advance.
    Returns the TCR and each contributor for transparent narration.
    """
    dmg_mod = weapon_damage // 10
    hp_mod = current_hp // 20
    act_mod = extra_actions * 2
    mul_mod = mulligans
    ep_mod = ep_expended // 10
    edge_mod = EDGE_TCR_VALUE.get(edge, 0)
    ar_mod = -(target_ar // 10)
    def_mod = -(target_extra_defences * 2)
    obst_mod = OBSTACLE_TCR_VALUE.get(obstacle, 0)
    tcr = (combat_value + dmg_mod + hp_mod + act_mod + mul_mod + ep_mod
           + edge_mod + ar_mod + def_mod + obst_mod)
    return {
        "tcr": tcr,
        "combat_value": combat_value,
        "damage_mod": dmg_mod,
        "hp_mod": hp_mod,
        "action_mod": act_mod,
        "mulligan_mod": mul_mod,
        "ep_mod": ep_mod,
        "edge_mod": edge_mod,
        "armour_mod": ar_mod,
        "defence_mod": def_mod,
        "obstacle_mod": obst_mod,
    }


def resolve_diceless_combat(attacker_tcr: int, defender_tcr: int) -> dict:
    """Compare two TCRs and map the Margin of Success to Table-15.

    Returns who victor is, the MoS, the outcome band, and the HP losses
    (as % of max HP) for the narration layer to apply.
    """
    delta = attacker_tcr - defender_tcr
    if delta >= 0:
        is_attacker_victor = True
        mos = delta
    else:
        is_attacker_victor = False
        mos = -delta
    for (lo, hi), label, duration, hp_victor, hp_opponent in DICELESS_MOS_TABLE:
        if hi is None or lo <= mos <= hi:
            return {
                "attacker_wins": is_attacker_victor,
                "mos": mos,
                "band": label,
                "duration": duration,
                "victor_hp_loss_pct": hp_victor,
                "opponent_hp_loss_pct": hp_opponent,
            }
    raise ValueError(f"Unbounded MoS {mos}")


def diceless_battle(attacker: dict, defender: dict) -> dict:
    """Convenience wrapper: compute both TCRs then resolve the clash."""
    a = compute_tcr(**attacker)
    d = compute_tcr(**defender)
    result = resolve_diceless_combat(a["tcr"], d["tcr"])
    return {
        "attacker_tcr": a["tcr"],
        "defender_tcr": d["tcr"],
        **result,
    }


def hedged_check(stat: int, target: int,
                 edge: str | None = None, obstacle: str | None = None) -> dict:
    """Diceless non-combat resolution (BESM4 p182 hedging: auto-7 baseline).

    Edges raise the base (minor 8 / major 9), obstacles lower it (minor 6 /
    major 5). Net modifiers cancel — used when edge and obstacle both apply.
    """
    base = 7 + EDGE_TCR_VALUE.get(edge, 0) + OBSTACLE_TCR_VALUE.get(obstacle, 0)
    total = base + stat
    return {
        "success": total >= target,
        "rolled": base,
        "total": total,
        "target": target,
        "edge": edge,
        "obstacle": obstacle,
    }


# ── combat maneuvers & tactical stances (Extras: stances, called shots, grappling) ──

TACTICAL_ACTIONS_PER_ROUND = 1

# Called-shot definitions: obstacle weight (0/1/2), AR effect, damage multiplier.
# weight: 1=minor obstacle, 2=major obstacle (BESM Extras pp.157-160).
CALLED_SHOTS = {
    "disarm_melee":        {"weight": 1, "ar_effect": "ignore", "multiplier": 1, "hp_damage": False, "body_tn": 15},
    "disarm_ranged":       {"weight": 2, "ar_effect": "ignore", "multiplier": 1, "hp_damage": False, "body_tn": 15},
    "reduce_armour":       {"weight": 1, "ar_effect": "half",   "multiplier": 1, "hp_damage": True},
    "bypass_armour":       {"weight": 2, "ar_effect": "ignore", "multiplier": 1, "hp_damage": True},
    "vital_spot":          {"weight": 2, "ar_effect": "ignore", "multiplier": 2, "hp_damage": True},
    "weak_point_large":    {"weight": 1, "ar_effect": "ignore", "multiplier": 1, "hp_damage": True},
    "weak_point_small":    {"weight": 2, "ar_effect": "ignore", "multiplier": 1, "hp_damage": True},
    "weak_point_tiny":     {"weight": 2, "ar_effect": "ignore", "multiplier": 1, "hp_damage": True, "defender_edge": 1},
}

# Grapple/pin conditions (Extras pp.165-170). Grabbed: minor obstacle on melee
# attack/defence, major obstacle on movement tasks. Pinned: no actions.
GRAPPLE_MELEE_OBSTACLE = 1
GRAPPLE_TASK_OBSTACLE = 2
PIN_ESCAPE_OBSTACLE = 2
PAIN_DISSOCIATION_FACTOR = 5


def resolve_tactical_stance(stance: str, has_ranged: bool = False,
                            consecutive_rounds: int = 1) -> dict:
    """Resolve a declared tactical action (max one per round).

    stance: 'aim' | 'wait' | 'total_defence'. Rounds 2+ of aim/wait escalate
    minor → major edge. Returns edge weight for the next attack, or the
    defence edge for total defence."""
    key = stance.lower().replace(" ", "_")
    if key not in ("aim", "wait", "total_defence"):
        return {"valid": False, "reason": f"unknown tactical action '{stance}'",
                "attack_edge": 0, "defence_edge": 0, "can_attack": True}
    if key == "aim" and not has_ranged:
        return {"valid": False, "reason": "aim requires a ranged weapon",
                "attack_edge": 0, "defence_edge": 0, "can_attack": True}
    if key == "total_defence":
        return {"valid": True, "stance": key,
                "attack_edge": 0, "defence_edge": 2, "can_attack": False}
    edge = 1 if consecutive_rounds <= 1 else 2
    return {"valid": True, "stance": key, "attack_edge": edge,
            "defence_edge": 0, "can_attack": True}


def two_weapon_attack(same_target: bool = True, techniques: list = None) -> dict:
    """Attacks with two weapons: single target → minor obstacle; two targets →
    major obstacle. Two Weapons technique negates the penalty entirely."""
    weight = 1 if same_target else 2
    if _has_technique(techniques, "two weapons"):
        return {"obstacle": 0, "raw_weight": weight, "negated": True}
    return {"obstacle": weight, "raw_weight": weight, "negated": False}


def strike_to_wound(base_damage: int,
                    has_area: bool = False, has_autofire: bool = False,
                    has_spreading: bool = False) -> dict:
    """Striking to Wound: flat un-multiplied damage, minimum 1. Cannot combine
    with Area, Autofire, or Spreading enhancements."""
    if has_area or has_autofire or has_spreading:
        return {"valid": False, "reason": "cannot combine with Area/Autofire/Spreading",
                "damage": 0}
    return {"valid": True, "damage": max(1, base_damage), "flat": True}


def touch_attack(called_spot: bool = False) -> dict:
    """Touching a Target: passive Minor Edge. Called touch to a protected spot
    still requires the called-shot obstacle."""
    return {"edge": 1, "requires_called_shot": called_spot}


def resolve_called_shot(shot: str, techniques: list = None) -> dict:
    """Resolve a called shot: obstacle weight, AR effect, damage multiplier.
    Precise Aim reduces the obstacle weight by one tier."""
    spec = CALLED_SHOTS.get(shot.lower().replace(" ", "_"))
    if not spec:
        return {"valid": False, "reason": f"unknown called shot '{shot}'"}
    reduction = technique_obstacle_reduction(techniques or [], "called_shot")
    weight = apply_obstacle_reduction(spec["weight"], reduction)
    return {
        "valid": True, "shot": shot,
        "obstacle": weight, "ar_effect": spec["ar_effect"],
        "multiplier": spec.get("multiplier", 1),
        "hp_damage": spec.get("hp_damage", True),
        "body_tn": spec.get("body_tn"),
        "defender_edge": spec.get("defender_edge", 0),
    }


def grapple_attack_edges(attacker_free_hands: int, defender_free_hands: int,
                         size_rank_delta: int = 0) -> dict:
    """Initiating a grab: free-hand advantage. 1-3 more free hands → Minor Edge,
    4+ → Major Edge. A target two+ Size Ranks smaller is 'much weaker'
    (penalties escalate)."""
    delta = attacker_free_hands - defender_free_hands
    edge = 2 if delta >= 4 else (1 if delta >= 1 else 0)
    much_weaker = size_rank_delta >= 2
    return {"edge": edge, "free_hand_delta": delta, "much_weaker": much_weaker}


def grabbed_condition(grappler_body: int, target_body: int,
                      target_much_stronger: bool = False,
                      target_much_weaker: bool = False) -> dict:
    """The Grabbed condition: minor obstacle on melee attacks/defence, major on
    movement tasks. A much stronger target reduces penalties one tier; a much
    weaker target is completely paralyzed (no rolls permitted)."""
    if target_much_weaker:
        return {"paralyzed": True, "melee_obstacle": 0, "task_obstacle": 0,
                "can_act": False, "reason": "much weaker — no rolls permitted"}
    melee = GRAPPLE_MELEE_OBSTACLE
    task = GRAPPLE_TASK_OBSTACLE
    if target_much_stronger:
        melee = max(0, melee - 1)
        task = max(0, task - 1)
    return {"paralyzed": False, "melee_obstacle": melee, "task_obstacle": task,
            "can_act": True}


def escape_grapple(target_body: int, grappler_body: int,
                   damage_dealt: int = 0) -> dict:
    """Escape a grapple two ways: an opposed Body roll (caller resolves), or
    Pain Dissociation — inflicting ≥ 5 × grappler's Body auto-escapes."""
    threshold = PAIN_DISSOCIATION_FACTOR * grappler_body
    auto = damage_dealt >= threshold
    return {"auto_escape": auto, "threshold": threshold,
            "opposed_body": target_body >= 1, "method": "opposed roll or pain dissociation"}


def pin_condition(escape_obstacle: int = PIN_ESCAPE_OBSTACLE) -> dict:
    """Pin: target cannot attack or defend; Major Obstacle on escape rolls."""
    return {"can_attack": False, "can_defend": False,
            "escape_obstacle": escape_obstacle}


def multi_target_dispersion(num_targets: int, techniques: list = None) -> dict:
    """Multi-target dispersion: one attack roll, N defenders. 2 targets → minor
    obstacle, 3 → major; 4+ adds defender edges (4: minor, 5+: major).
    Multiple Targets technique reduces the obstacle."""
    if num_targets <= 1:
        return {"obstacle": 0, "defender_edge": 0}
    weight = 1 if num_targets == 2 else 2
    reduction = technique_obstacle_reduction(techniques or [], "multi_target")
    adjusted = apply_obstacle_reduction(weight, reduction)
    defender_edge = 0
    if num_targets >= 4:
        defender_edge = 1 if num_targets == 4 else 2
    return {"obstacle": adjusted, "defender_edge": defender_edge,
            "unified_roll": True}
